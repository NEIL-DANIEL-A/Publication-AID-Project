"""
Complete Missing Scopus Metrics:
Resumes streaming from offset 17,200 to 50,040 to capture all remaining Scopus sources,
updates scopus_12k_additional_data.csv, and upserts them into Supabase.
"""

import html
import json
import math
import os
import time
from typing import Any, Optional
import pandas as pd
import requests
from scrapling import DynamicFetcher, Selector
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://phgozsfrqphpsznkmtcg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBoZ296c2ZycXBocHN6bmttdGNnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1NDMxMjgsImV4cCI6MjEwNDExOTEyOH0._EfGIRjfuJQNFecG4ia6pW_uYBaGpVyD52tcPKp7H58")


def norm_issn(val: Any) -> Optional[str]:
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().replace("-", "").replace(".0", "")
    if len(s) == 7:
        s = "0" + s
    return s.upper() if len(s) == 8 else None


def parse_numeric(val: Any) -> Optional[float]:
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


def main():
    print("=" * 70)
    print("RESUMING SCOPUS STREAM FOR REMAINING SOURCES (Offset 17,200 -> 50,040)")
    print("=" * 70)

    # 1. Load existing data
    csv_file = "scopus_12k_additional_data.csv"
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} does not exist!")
        return

    df = pd.read_csv(csv_file)
    missing_mask = df["citescore"].isna()
    print(f"Total journals: {len(df)}")
    print(f"Journals currently with CiteScore: {(~missing_mask).sum()}")
    print(f"Journals missing CiteScore: {missing_mask.sum()}")

    # Build lookup of missing journals by normalized ISSN
    missing_by_issn = {}
    for idx, row in df[missing_mask].iterrows():
        p = norm_issn(row.get("issn"))
        e = norm_issn(row.get("e_issn"))
        if p:
            missing_by_issn[p] = idx
        if e:
            missing_by_issn[e] = idx

    # Also load master list for source_id mapping
    df_master = pd.read_excel("scopus_master_list.xlsx", sheet_name="Scopus Sources Aug. 2026")
    source_to_idx = {}
    for _, r in df_master.iterrows():
        sid = str(r["Sourcerecord ID"])
        p = norm_issn(r["ISSN"])
        e = norm_issn(r["EISSN"])
        target_idx = None
        if p and p in missing_by_issn:
            target_idx = missing_by_issn[p]
        elif e and e in missing_by_issn:
            target_idx = missing_by_issn[e]
        if target_idx is not None:
            source_to_idx[sid] = target_idx

    print(f"Tracked missing journals mapped to Scopus Source IDs: {len(source_to_idx)}")

    # 2. Authenticate session with Scopus
    print("\nConnecting to Scopus via DynamicFetcher ...")
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
    print(f"Session established with {len(session.cookies)} cookies.")

    # 3. Stream from offset 17200 to 50040
    offset = 17200
    batch_size = 200
    max_sources = 51000
    recovered_count = 0
    updated_indices = set()

    print(f"Streaming from offset {offset} to {max_sources} with rate-limit protection ...")

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
            r = session.post("https://www.scopus.com/sources.uri", data=payload, timeout=25)
            if r.status_code == 429:
                print(f"\n[!] Rate limited (429) at offset {offset}. Backing off for 6 seconds...")
                time.sleep(6)
                continue
            elif r.status_code != 200:
                print(f"\n[!] Non-200 status {r.status_code} at offset {offset}. Backing off for 4 seconds...")
                time.sleep(4)
                continue

            sel = Selector(r.text)
            pre = sel.css("#resultsJson")
            if not pre:
                print(f"\n[!] #resultsJson not found at offset {offset}.")
                break

            data = json.loads(html.unescape(pre[0].text))
            results = data.get("results", [])
            if not results:
                print(f"\nNo more results at offset {offset}.")
                break

            for item in results:
                sid = str(item.get("id")) if item.get("id") else None
                issn_norm = norm_issn(item.get("issn"))
                
                target_idx = None
                if sid and sid in source_to_idx:
                    target_idx = source_to_idx[sid]
                elif issn_norm and issn_norm in missing_by_issn:
                    target_idx = missing_by_issn[issn_norm]

                if target_idx is not None and target_idx not in updated_indices:
                    cs = parse_numeric(item.get("citescore"))
                    sjr = parse_numeric(item.get("sjr"))
                    snip = parse_numeric(item.get("snip"))
                    pub = item.get("publisher")
                    sub = item.get("subarea")

                    if cs is not None or sjr is not None or snip is not None:
                        df.at[target_idx, "citescore"] = cs
                        df.at[target_idx, "sjr"] = sjr
                        df.at[target_idx, "snip"] = snip
                        if pub and pd.isna(df.at[target_idx, "publisher"]):
                            df.at[target_idx, "publisher"] = pub
                        if sub and pd.isna(df.at[target_idx, "subject_area"]):
                            df.at[target_idx, "subject_area"] = sub

                        updated_indices.add(target_idx)
                        recovered_count += 1

            offset += len(results)
            print(f"Offset {offset}/50040 | Recovered new metrics: {recovered_count} ...", end="\r", flush=True)

            if len(results) < batch_size:
                break

            time.sleep(0.35)  # Rate limit safety delay

        except Exception as e:
            print(f"\n[!] Error at offset {offset}: {e}")
            time.sleep(3)

    print(f"\n\nStreaming completed! Recovered metrics for {recovered_count} additional journals.")

    # 4. Save updated local CSV
    df.to_csv(csv_file, index=False)
    print(f"Saved updated CSV to '{csv_file}'.")
    new_total_cs = df["citescore"].notna().sum()
    print(f"New total journals with CiteScore: {new_total_cs}/{len(df)} ({new_total_cs/len(df)*100:.1f}%)")

    # 5. Push updated records to Supabase
    if updated_indices:
        print(f"\nUpserting {len(updated_indices)} newly updated records to Supabase 'Scopus_additional_data' ...")
        client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        updated_rows = df.loc[list(updated_indices)].to_dict(orient="records")

        # Clean NaN to None for JSON
        for r in updated_rows:
            for k, v in r.items():
                if pd.isna(v):
                    r[k] = None

        batch_size_up = 500
        total_up = len(updated_rows)
        for i in range(0, total_up, batch_size_up):
            chunk = updated_rows[i : i + batch_size_up]
            client.table("Scopus_additional_data").upsert(chunk, on_conflict="journal_id").execute()
            print(f"Uploaded {min(i + batch_size_up, total_up)}/{total_up} ...", end="\r", flush=True)

        print("\nSupabase update complete!")


if __name__ == "__main__":
    main()
