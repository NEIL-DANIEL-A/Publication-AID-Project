"""
Push Coverage and Source Type to Supabase 'Scopus_additional_data' Table

Reads 'scopus_12k_additional_data.csv' and batch upserts 'coverage' and 'source_type'
into the Supabase 'Scopus_additional_data' table.
"""

import csv
import os
import sys
import time
from typing import List, Dict, Any
import requests
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://phgozsfrqphpsznkmtcg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBoZ296c2ZycXBocHN6bmttdGNnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1NDMxMjgsImV4cCI6MjEwNDExOTEyOH0._EfGIRjfuJQNFecG4ia6pW_uYBaGpVyD52tcPKp7H58")


def main():
    print("=" * 70, flush=True)
    print("PUSH COVERAGE & SOURCE TYPE TO SUPABASE", flush=True)
    print("=" * 70, flush=True)

    client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 1. Check if columns exist in Supabase table
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r_check = requests.get(f"{SUPABASE_URL}/rest/v1/Scopus_additional_data?select=coverage,source_type&limit=1", headers=headers)

    if r_check.status_code != 200:
        print("\n[!] ATTENTION: The 'coverage' and/or 'source_type' columns do not exist yet in Supabase.", flush=True)
        print("    Please run the following SQL migration in your Supabase SQL Editor first:\n", flush=True)
        print('    ALTER TABLE public."Scopus_additional_data"', flush=True)
        print("        ADD COLUMN IF NOT EXISTS coverage TEXT,", flush=True)
        print("        ADD COLUMN IF NOT EXISTS source_type TEXT;\n", flush=True)
        print("    After running the SQL query above, re-run this script to push all rows.", flush=True)
        sys.exit(1)

    print("[+] Columns 'coverage' and 'source_type' confirmed in Supabase table!", flush=True)

    # 2. Read scopus_12k_additional_data.csv
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_file = os.path.join(script_dir, "scopus_12k_additional_data.csv")

    if not os.path.exists(csv_file):
        print(f"[!] Error: File '{csv_file}' not found.", flush=True)
        sys.exit(1)

    records: List[Dict[str, Any]] = []
    print(f"Reading '{csv_file}' ...", flush=True)
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            jid = row.get("journal_id")
            cov = row.get("coverage", "").strip()
            st = row.get("source_type", "").strip()
            if jid:
                records.append({
                    "journal_id": str(jid),
                    "coverage": cov if cov else None,
                    "source_type": st if st else None
                })

    total = len(records)
    print(f"[+] Loaded {total} journal records to sync.", flush=True)

    # 3. Batch upsert into Scopus_additional_data
    table_name = "Scopus_additional_data"
    batch_size = 500
    uploaded = 0
    t_start = time.time()

    print(f"Uploading to '{table_name}' in batches of {batch_size} ...", flush=True)
    for i in range(0, total, batch_size):
        chunk = records[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        try:
            client.table(table_name).upsert(chunk, on_conflict="journal_id").execute()
            uploaded += len(chunk)
            pct = (uploaded / total) * 100
            print(f"  [Batch {batch_num}/{total_batches}] Synced {uploaded}/{total} ({pct:.1f}%) ...", end="\r", flush=True)
        except Exception as e:
            print(f"\n  [!] Batch {batch_num} error: {e}", flush=True)

    elapsed = time.time() - t_start
    print(f"\n\n[SUCCESS] Successfully pushed coverage & source_type for {uploaded}/{total} journals in {elapsed:.1f}s!", flush=True)


if __name__ == "__main__":
    main()
