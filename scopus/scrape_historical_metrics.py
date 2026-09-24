"""
Scrape and Push Historical Scopus Metrics for Inactive/Discontinued Journals
and Add Status Column ('active' / 'inactive')
"""

import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import requests
from scrapling import DynamicFetcher
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://phgozsfrqphpsznkmtcg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBoZ296c2ZycXBocHN6bmttdGNnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1NDMxMjgsImV4cCI6MjEwNDExOTEyOH0._EfGIRjfuJQNFecG4ia6pW_uYBaGpVyD52tcPKp7H58")

CHECKPOINT_FILE = "historical_metrics_checkpoint.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_checkpoint(data: dict):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def fetch_citescore_fast(sid: int) -> dict:
    """Fetch historical CiteScore via the fast JSON endpoint."""
    url = f"https://www.scopus.com/source/citescore/{sid}.uri"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            d = r.json()
            ly = d.get("lastYear")
            yinfo = d.get("yearInfo", {}).get(str(ly), {})
            rp = None
            for m in yinfo.get("metricType", []):
                if m.get("documentType") == "all":
                    rp = m.get("rp")
                    break
            return {"last_year": ly, "citescore": float(rp) if rp else None}
    except Exception:
        pass
    return {"last_year": None, "citescore": None}


def scrape_web_profile(sid: int) -> dict:
    """Scrape Scopus web profile page to extract historical SJR and SNIP."""
    res = {"sjr": None, "sjr_year": None, "snip": None, "snip_year": None}

    def parse(page):
        page.wait_for_timeout(2000)
        s_txt = page.inner_text("#sjrCard") if page.query_selector("#sjrCard") else ""
        sn_txt = page.inner_text("#snipCard") if page.query_selector("#snipCard") else ""

        # Parse SJR
        if s_txt:
            m_yr = re.search(r"SJR\s*([0-9]{4})", s_txt, re.I)
            m_val = re.search(r"([0-9]+\.?[0-9]*)", s_txt.split("\n")[-1] if "\n" in s_txt else s_txt)
            if m_val:
                res["sjr"] = float(m_val.group(1))
            if m_yr:
                res["sjr_year"] = int(m_yr.group(1))

        # Parse SNIP
        if sn_txt:
            m_yr = re.search(r"SNIP\s*([0-9]{4})", sn_txt, re.I)
            m_val = re.search(r"([0-9]+\.?[0-9]*)", sn_txt.split("\n")[-1] if "\n" in sn_txt else sn_txt)
            if m_val:
                res["snip"] = float(m_val.group(1))
            if m_yr:
                res["snip_year"] = int(m_yr.group(1))

    try:
        DynamicFetcher.fetch(f"https://www.scopus.com/sourceid/{sid}", page_action=parse)
    except Exception as e:
        print(f"  [!] SID {sid} scrape error: {e}", flush=True)

    return res


def main():
    print("=" * 70, flush=True)
    print("HISTORICAL SCOPUS METRICS SCRAPER & DATABASE SYNC", flush=True)
    print("=" * 70, flush=True)

    # 1. Load data
    df_null = pd.read_csv("journals_with_at_least_one_null_metric.csv")
    df_matched = pd.read_csv("matched_journals.csv")
    merged = pd.merge(df_null, df_matched[["id", "source_id"]], left_on="journal_id", right_on="id", how="left")

    checkpoint = load_checkpoint()
    print(f"Loaded checkpoint with {len(checkpoint)} existing entries.", flush=True)

    # 2. Fast CiteScore fetching for all mapped SIDs
    mapped = merged.dropna(subset=["source_id"]).copy()
    mapped["source_id"] = mapped["source_id"].astype(int)
    print(f"Total journals mapped to Scopus Source ID: {len(mapped)}", flush=True)

    needed_cs = [sid for sid in mapped["source_id"].unique() if str(sid) not in checkpoint or "citescore" not in checkpoint[str(sid)]]
    print(f"Fetching CiteScore JSON for {len(needed_cs)} journals...", flush=True)

    def fetch_cs_worker(sid):
        data = fetch_citescore_fast(sid)
        return sid, data

    if needed_cs:
        with ThreadPoolExecutor(max_workers=15) as ex:
            for sid, data in ex.map(fetch_cs_worker, needed_cs):
                sid_str = str(sid)
                if sid_str not in checkpoint:
                    checkpoint[sid_str] = {}
                checkpoint[sid_str]["citescore"] = data["citescore"]
                checkpoint[sid_str]["last_year"] = data["last_year"]
        save_checkpoint(checkpoint)
        print("Fast CiteScore fetching complete!", flush=True)

    # 3. Identify journals needing SJR / SNIP web profile scraping
    # Exclude book series ('sjr, snip' missing where CiteScore is already present)
    # Exclude unindexed
    # Exclude those who already have SJR and SNIP
    to_scrape_sids = []
    for _, row in mapped.iterrows():
        sid = row["source_id"]
        sid_str = str(sid)
        missing = str(row["missing_metrics"])
        
        # If it's a book series, SJR/SNIP do not exist
        if missing == "sjr, snip":
            continue
        
        # If SJR is already in CSV and SNIP is already in CSV, skip
        if pd.notna(row["sjr"]) and pd.notna(row["snip"]):
            continue

        # If already scraped in checkpoint
        cp_entry = checkpoint.get(sid_str, {})
        if "sjr" in cp_entry and "snip" in cp_entry:
            continue

        to_scrape_sids.append(sid)

    to_scrape_sids = list(set(to_scrape_sids))
    print(f"\nJournals requiring Scopus Web Profile scraping for SJR/SNIP: {len(to_scrape_sids)}", flush=True)

    # 4. Scrape web profiles using 6 parallel workers
    if to_scrape_sids:
        print("Starting parallel browser scraping (6 workers)...", flush=True)
        t_start = time.time()
        
        def web_worker(sid):
            metrics = scrape_web_profile(sid)
            return sid, metrics

        completed = 0
        total_scrape = len(to_scrape_sids)
        
        # Process in batches of 12 so we can checkpoint frequently
        batch_size = 12
        for b_start in range(0, total_scrape, batch_size):
            b_sids = to_scrape_sids[b_start:b_start + batch_size]
            with ThreadPoolExecutor(max_workers=6) as ex:
                results = list(ex.map(web_worker, b_sids))
            
            for sid, m in results:
                sid_str = str(sid)
                if sid_str not in checkpoint:
                    checkpoint[sid_str] = {}
                checkpoint[sid_str]["sjr"] = m["sjr"]
                checkpoint[sid_str]["sjr_year"] = m["sjr_year"]
                checkpoint[sid_str]["snip"] = m["snip"]
                checkpoint[sid_str]["snip_year"] = m["snip_year"]
            
            save_checkpoint(checkpoint)
            completed += len(b_sids)
            elapsed = time.time() - t_start
            rate = completed / elapsed if elapsed > 0 else 0
            eta = (total_scrape - completed) / rate if rate > 0 else 0
            print(f"  [{completed}/{total_scrape}] Scraped profiles (Elapsed: {elapsed:.0f}s, ETA: {eta:.0f}s)...", flush=True)

        print(f"\n[+] Finished scraping all web profiles in {time.time()-t_start:.1f}s!", flush=True)

    # 5. Merge historical metrics and update CSV files
    print("\nMerging historical metrics into master datasets...", flush=True)
    df_12k = pd.read_csv("scopus_12k_additional_data.csv")

    # Add status column: default 'active'
    df_12k["status"] = "active"

    # Set inactive for the 419 journals
    inactive_jids = set(df_null["journal_id"].astype(str).tolist())
    df_12k.loc[df_12k["journal_id"].astype(str).isin(inactive_jids), "status"] = "inactive"

    # Merge mapped source_id
    id_to_sid = dict(zip(df_matched["id"].astype(str), df_matched["source_id"]))

    recovered_cs = 0
    recovered_sjr = 0
    recovered_snip = 0

    for idx, row in df_12k.iterrows():
        jid = str(row["journal_id"])
        if jid in inactive_jids:
            sid = id_to_sid.get(jid)
            if pd.notna(sid):
                sid_str = str(int(sid))
                cp = checkpoint.get(sid_str, {})

                # Update CiteScore if currently null
                if pd.isna(row["citescore"]) and cp.get("citescore") is not None:
                    df_12k.at[idx, "citescore"] = cp["citescore"]
                    recovered_cs += 1

                # Update SJR if currently null
                if pd.isna(row["sjr"]) and cp.get("sjr") is not None:
                    df_12k.at[idx, "sjr"] = cp["sjr"]
                    recovered_sjr += 1

                # Update SNIP if currently null
                if pd.isna(row["snip"]) and cp.get("snip") is not None:
                    df_12k.at[idx, "snip"] = cp["snip"]
                    recovered_snip += 1

    print(f"Historical metrics populated:")
    print(f"  CiteScores recovered: {recovered_cs}")
    print(f"  SJR values recovered: {recovered_sjr}")
    print(f"  SNIP values recovered: {recovered_snip}")

    # Save updated scopus_12k_additional_data.csv
    df_12k.to_csv("scopus_12k_additional_data.csv", index=False)
    print("Saved scopus_12k_additional_data.csv with 'status' column and historical metrics.")

    # Update journals_with_at_least_one_null_metric.csv
    inactive_subset = df_12k[df_12k["status"] == "inactive"].copy()
    
    def get_missing(r):
        missing = []
        if pd.isna(r["citescore"]):
            missing.append("citescore")
        if pd.isna(r["sjr"]):
            missing.append("sjr")
        if pd.isna(r["snip"]):
            missing.append("snip")
        return ", ".join(missing) if missing else "none (historical data populated)"

    inactive_subset["missing_metrics"] = inactive_subset.apply(get_missing, axis=1)
    inactive_subset.to_csv("journals_with_at_least_one_null_metric.csv", index=False)
    print("Saved updated journals_with_at_least_one_null_metric.csv.")

    # Update journals_with_null_metrics.csv (only those where all 3 remain null)
    all_null_subset = df_12k[df_12k["citescore"].isna() & df_12k["sjr"].isna() & df_12k["snip"].isna()]
    all_null_subset.to_csv("journals_with_null_metrics.csv", index=False)
    print(f"Saved journals_with_null_metrics.csv ({len(all_null_subset)} remaining journals with 0 metrics).")

    # 6. Push to Supabase
    print("\nPushing updated metrics and status to Supabase...", flush=True)
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Check if 'status' column exists in Supabase
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r_check = requests.get(f"{SUPABASE_URL}/rest/v1/Scopus_additional_data?select=status&limit=1", headers=headers)
    has_status_col = (r_check.status_code == 200)

    if has_status_col:
        print("[+] 'status' column confirmed in Supabase table. Pushing full dataset including status...", flush=True)
    else:
        print("[!] Note: 'status' column does not exist yet in Supabase.", flush=True)
        print("    Pushing updated CiteScore, SJR, and SNIP metrics first.", flush=True)

    # Push inactive rows update
    records_to_push = []
    for _, r in inactive_subset.iterrows():
        rec = {
            "journal_id": str(r["journal_id"]),
            "citescore": None if pd.isna(r["citescore"]) else float(r["citescore"]),
            "sjr": None if pd.isna(r["sjr"]) else float(r["sjr"]),
            "snip": None if pd.isna(r["snip"]) else float(r["snip"]),
        }
        if has_status_col:
            rec["status"] = r["status"]
        records_to_push.append(rec)

    batch_size = 100
    for i in range(0, len(records_to_push), batch_size):
        b = records_to_push[i:i+batch_size]
        client.table("Scopus_additional_data").upsert(b, on_conflict="journal_id").execute()
    print(f"[+] Successfully pushed {len(records_to_push)} inactive records to Supabase!")

    if has_status_col:
        # Also push status='active' for the other 11,777 rows
        print("Pushing status='active' for active journals...", flush=True)
        active_records = [{"journal_id": str(r["journal_id"]), "status": "active"} for _, r in df_12k[df_12k["status"] == "active"].iterrows()]
        for i in range(0, len(active_records), 500):
            b = active_records[i:i+500]
            client.table("Scopus_additional_data").upsert(b, on_conflict="journal_id").execute()
        print("[+] Successfully set status='active' on all active journals in Supabase!")

    print("\n" + "=" * 70, flush=True)
    print("ALL HISTORICAL DATA SCRAPED, MERGED, AND PUSHED SUCCESSFULLY!", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
