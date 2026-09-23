"""
Pipeline: Fetch Scopus Metrics (CiteScore, SJR, SNIP) for 12,196 Supabase Journals
and Push directly into 'Scopus_additional_data'.
"""

import html
import json
import math
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional
import pandas as pd
import requests
from scrapling import DynamicFetcher, Selector
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://phgozsfrqphpsznkmtcg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBoZ296c2ZycXBocHN6bmttdGNnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1NDMxMjgsImV4cCI6MjEwNDExOTEyOH0._EfGIRjfuJQNFecG4ia6pW_uYBaGpVyD52tcPKp7H58")


def norm_issn(val: Any) -> Optional[str]:
    """Normalizes an ISSN string to 8 alphanumeric characters without hyphens."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().replace("-", "").replace(".0", "")
    if len(s) == 7:
        s = "0" + s
    return s.upper() if len(s) == 8 else None


def format_issn(val: Optional[str]) -> str:
    """Formats an 8-char normalized ISSN as XXXX-XXXX."""
    if not val or len(val) != 8:
        return "N/A"
    return f"{val[:4]}-{val[4:]}"


def parse_numeric(val: Any) -> Optional[float]:
    """Parses numeric metric values, returning None for missing or N/A."""
    if val is None:
        return None
    s = str(val).strip()
    if s in ["", "N/A", "no data", "nan", "None", "-"]:
        return None
    try:
        f = float(s.replace(",", ""))
        return None if math.isnan(f) else f
    except ValueError:
        return None


def run_pipeline():
    t_start = time.time()
    print("=" * 70, flush=True)
    print("SCOPUS METRICS PIPELINE FOR SUPABASE JOURNALS", flush=True)
    print("=" * 70, flush=True)

    # 1. Connect to Supabase
    print(f"\n[1/5] Connecting to Supabase ({SUPABASE_URL}) ...", flush=True)
    client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 2. Fetch all journals from 'journals' table
    print("[2/5] Fetching all rows from 'journals' table ...", flush=True)
    all_journals = []
    page_size = 1000
    offset = 0

    while True:
        res = client.table("journals").select("id, title, print_issn, e_issn, normalized_print, normalized_e, publisher").range(offset, offset + page_size - 1).execute()
        data = res.data
        if not data:
            break
        all_journals.extend(data)
        offset += len(data)
        print(f"      Fetched {len(all_journals)} journals ...", end="\r", flush=True)
        if len(data) < page_size:
            break

    print(f"\n      [+] Total journals fetched from database: {len(all_journals)}", flush=True)

    # 3. Load Scopus Master List & Map to Source IDs
    print("\n[3/5] Mapping journals to Scopus Source IDs via Master Registry ...", flush=True)
    master_file = "scopus_master_list.xlsx"
    if not os.path.exists(master_file):
        print(f"      [!] {master_file} missing. Downloading...", flush=True)
        url = "https://downloads.ctfassets.net/o78em1y1w4i4/7xtaTxNiNcWRTeZkV86eNy/69cf2d506c905dc299531fdc93049dbb/ext_list_Aug_2026.xlsx"
        r = requests.get(url, stream=True)
        with open(master_file, "wb") as f:
            for ch in r.iter_content(chunk_size=1024 * 1024):
                f.write(ch)

    df_scopus = pd.read_excel(master_file, sheet_name="Scopus Sources Aug. 2026")

    # Build master lookup
    scopus_lookup = {}
    for _, r in df_scopus.iterrows():
        sid = r["Sourcerecord ID"]
        title = r["Source Title"]
        pub = r["Publisher"]
        issn = norm_issn(r["ISSN"])
        eissn = norm_issn(r["EISSN"])
        entry = {
            "source_id": sid,
            "scopus_title": title,
            "scopus_publisher": pub,
            "scopus_issn": format_issn(issn),
            "scopus_eissn": format_issn(eissn)
        }
        if issn:
            scopus_lookup[issn] = entry
        if eissn:
            scopus_lookup[eissn] = entry

    matched_journals = []
    for j in all_journals:
        p = norm_issn(j.get("normalized_print") or j.get("print_issn"))
        e = norm_issn(j.get("normalized_e") or j.get("e_issn"))

        info = None
        if p and p in scopus_lookup:
            info = scopus_lookup[p]
        elif e and e in scopus_lookup:
            info = scopus_lookup[e]

        matched_journals.append({
            "journal_id": j["id"],
            "title": j["title"],
            "print_issn": j.get("print_issn") or format_issn(p),
            "e_issn": j.get("e_issn") or format_issn(e),
            "source_id": info["source_id"] if info else None,
            "scopus_publisher": info["scopus_publisher"] if info else (j.get("publisher") or "N/A"),
            "norm_p": p,
            "norm_e": e
        })

    indexed_count = sum(1 for j in matched_journals if j["source_id"] is not None)
    print(f"      [+] Matched: {indexed_count} / {len(matched_journals)} journals ({indexed_count/len(matched_journals)*100:.1f}%)", flush=True)

    # 4. Stream CiteScore, SJR, SNIP for all matched sources
    print("\n[4/5] Establishing authenticated Scopus session to stream metrics ...", flush=True)
    session = requests.Session()

    def auth_session(page):
        page.wait_for_timeout(3000)
        cookies = page.context.cookies()
        for c in cookies:
            session.cookies.set(c["name"], c["value"], domain=c.get("domain"))
        session.headers.update({
            "User-Agent": page.evaluate("navigator.userAgent"),
            "Referer": "https://www.scopus.com/sources.uri"
        })

    DynamicFetcher.fetch("https://www.scopus.com/sources.uri", page_action=auth_session)
    print(f"      [+] Session authenticated with {len(session.cookies)} cookies.", flush=True)

    # Stream sources table in 200-item chunks
    metrics_by_source_id = {}
    metrics_by_issn = {}

    print("      Streaming Scopus metrics catalog in 200-item batches...", flush=True)
    offset = 0
    batch_size = 200
    max_sources = 52000

    while offset < max_sources:
        payload = {
            "sortField": "citescore",
            "sortDirection": "desc",
            "sourceSelectionType": "all",
            "offset": str(offset),
            "resultsPerPage": str(batch_size),
            "year": "2025"
        }
        try:
            r = session.post("https://www.scopus.com/sources.uri", data=payload, timeout=20)
            if r.status_code == 200:
                sel = Selector(r.text)
                pre = sel.css("#resultsJson")
                if not pre:
                    print(f"\n      [!] Could not find #resultsJson on offset {offset}. Stopping stream.", flush=True)
                    break

                raw_json = html.unescape(pre[0].text)
                data = json.loads(raw_json)
                results = data.get("results", [])
                if not results:
                    break

                for item in results:
                    sid = str(item.get("id")) if item.get("id") else None
                    issn_norm = norm_issn(item.get("issn"))
                    metric_data = {
                        "citescore": parse_numeric(item.get("citescore")),
                        "sjr": parse_numeric(item.get("sjr")),
                        "snip": parse_numeric(item.get("snip")),
                        "publisher": item.get("publisher"),
                        "subarea": item.get("subarea")
                    }
                    if sid:
                        metrics_by_source_id[sid] = metric_data
                    if issn_norm:
                        metrics_by_issn[issn_norm] = metric_data

                offset += len(results)
                print(f"        Processed {len(metrics_by_source_id)} source metrics (offset {offset} / {data.get('totalResultsCount', 50040)}) ...", end="\r", flush=True)

                if len(results) < batch_size:
                    break
            else:
                print(f"\n      [!] POST failed with status {r.status_code}", flush=True)
                break
        except Exception as ex:
            print(f"\n      [!] Exception on offset {offset}: {ex}", flush=True)
            break

    print(f"\n      [+] Completed streaming! Unique sources with metrics: {len(metrics_by_source_id)}", flush=True)

    # 5. Assemble and Push to Supabase 'Scopus_additional_data'
    print("\n[5/5] Assembling final dataset and pushing to Supabase 'Scopus_additional_data' ...", flush=True)
    final_records = []

    for j in matched_journals:
        sid_str = str(j["source_id"]) if j["source_id"] else None
        
        # Look up metric by source_id first, then by normalized print/e issn
        m = None
        if sid_str and sid_str in metrics_by_source_id:
            m = metrics_by_source_id[sid_str]
        elif j["norm_p"] and j["norm_p"] in metrics_by_issn:
            m = metrics_by_issn[j["norm_p"]]
        elif j["norm_e"] and j["norm_e"] in metrics_by_issn:
            m = metrics_by_issn[j["norm_e"]]
        else:
            m = {}

        rec = {
            "journal_id": j["journal_id"],
            "journal_name": j["title"],
            "issn": j["print_issn"] or "N/A",
            "e_issn": j["e_issn"] or "N/A",
            "publisher": m.get("publisher") or j["scopus_publisher"] or "N/A",
            "subject_area": m.get("subarea") or "N/A",
            "citescore": m.get("citescore"),
            "sjr": m.get("sjr"),
            "snip": m.get("snip")
        }
        final_records.append(rec)

    # Save local CSV backup
    backup_file = "scopus_12k_additional_data.csv"
    pd.DataFrame(final_records).to_csv(backup_file, index=False)
    print(f"      [+] Saved local backup CSV to '{backup_file}'.", flush=True)

    # Batch upload to Supabase
    table_name = "Scopus_additional_data"
    batch_upload_size = 500
    total = len(final_records)
    uploaded = 0

    print(f"      Uploading {total} records to '{table_name}' in chunks of {batch_upload_size} ...", flush=True)

    for i in range(0, total, batch_upload_size):
        chunk = final_records[i : i + batch_upload_size]
        batch_num = (i // batch_upload_size) + 1
        total_batches = (total + batch_upload_size - 1) // batch_upload_size

        try:
            client.table(table_name).upsert(chunk, on_conflict="journal_id").execute()
            uploaded += len(chunk)
            pct = (uploaded / total) * 100
            print(f"        [Batch {batch_num}/{total_batches}] Uploaded {uploaded}/{total} ({pct:.1f}%) ...", end="\r", flush=True)
        except Exception as e:
            # Fallback to insert
            try:
                client.table(table_name).insert(chunk).execute()
                uploaded += len(chunk)
            except Exception as e2:
                print(f"\n      [!] Batch {batch_num} error: {e2}", flush=True)

    elapsed = time.time() - t_start
    print(f"\n\n" + "=" * 70, flush=True)
    print(f"[SUCCESS] Pipeline completed in {elapsed:.1f} seconds (~{elapsed/60:.1f} minutes)!", flush=True)
    print(f"          Total Journals Processed: {total}", flush=True)
    print(f"          Successfully Uploaded:   {uploaded}", flush=True)
    print(f"          Local Backup CSV:        {backup_file}", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    run_pipeline()
