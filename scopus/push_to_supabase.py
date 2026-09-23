"""
Push Scopus Journal Data to Supabase Table

Reads scraped Scopus journal CSV files and performs batch upsert
into the Supabase 'scopus_journals' table.
"""

import argparse
import csv
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional

try:
    from supabase import create_client, Client
except ImportError:
    print("[!] Error: supabase-py is not installed. Run: pip install supabase", file=sys.stderr)
    sys.exit(1)


def load_env_file(filepath: str = ".env"):
    """Loads environment variables from a .env file if present."""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and not os.environ.get(key):
                        os.environ[key] = val


def parse_numeric(val: Any) -> Optional[float]:
    """Parses numeric values for CiteScore, SJR, SNIP safely. Returns None if invalid or N/A."""
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


def clean_str(val: Any) -> str:
    """Cleans string value, returning 'N/A' if empty or none."""
    if val is None:
        return "N/A"
    s = str(val).strip()
    return s if s and s != "nan" else "N/A"


def push_csv_to_supabase(
    csv_file: str,
    supabase_url: Optional[str] = None,
    supabase_key: Optional[str] = None,
    table_name: str = "scopus_journals",
    batch_size: int = 500,
) -> int:
    """
    Reads CSV and uploads rows to Supabase in batches.
    """
    load_env_file()

    url = supabase_url or os.environ.get("SUPABASE_URL")
    key = supabase_key or os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("\n[!] Error: Missing Supabase credentials.", file=sys.stderr)
        print("Please provide SUPABASE_URL and SUPABASE_KEY either via:", file=sys.stderr)
        print("  1. Environment variables (SUPABASE_URL, SUPABASE_KEY)", file=sys.stderr)
        print("  2. In a .env file (see .env.example)", file=sys.stderr)
        print("  3. Via CLI flags: --url <URL> --key <KEY>\n", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to Supabase at: {url} ...")
    supabase: Client = create_client(url, key)

    if not os.path.exists(csv_file):
        print(f"[!] Error: File '{csv_file}' not found.", file=sys.stderr)
        sys.exit(1)

    records: List[Dict[str, Any]] = []
    print(f"Reading '{csv_file}' ...")
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record = {
                "journal_name": clean_str(row.get("Journal Name") or row.get("journal_name")),
                "publisher": clean_str(row.get("Publisher") or row.get("publisher")),
                "issn": clean_str(row.get("ISSN") or row.get("issn")),
                "e_issn": clean_str(row.get("E-ISSN") or row.get("e_issn")),
                "subject_area": clean_str(row.get("Subject Area") or row.get("subject_area")),
                "citescore": parse_numeric(row.get("CiteScore") or row.get("citescore")),
                "sjr": parse_numeric(row.get("SJR") or row.get("sjr")),
                "snip": parse_numeric(row.get("SNIP") or row.get("snip")),
            }
            records.append(record)

    total_records = len(records)
    print(f"[+] Parsed {total_records} records from CSV.")

    if total_records == 0:
        print("[!] No records found to push.")
        return 0

    print(f"Uploading to table '{table_name}' in batches of {batch_size} ...")
    uploaded_count = 0
    t_start = time.time()

    for i in range(0, total_records, batch_size):
        batch = records[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_records + batch_size - 1) // batch_size

        try:
            # Upsert into table with conflict on (journal_name, issn, e_issn)
            res = supabase.table(table_name).upsert(batch, on_conflict="journal_name,issn,e_issn").execute()
            uploaded_count += len(batch)
            pct = (uploaded_count / total_records) * 100
            print(f"  [Batch {batch_num}/{total_batches}] Pushed {len(batch)} rows ({uploaded_count}/{total_records} - {pct:.1f}%)")
        except Exception as e:
            # Fallback to standard insert if upsert constraint not yet established
            print(f"  [Batch {batch_num}] Upsert failed ({e}), attempting standard insert...")
            try:
                res = supabase.table(table_name).insert(batch).execute()
                uploaded_count += len(batch)
                print(f"  [Batch {batch_num}/{total_batches}] Inserted {len(batch)} rows")
            except Exception as e2:
                print(f"  [!] Failed to insert batch {batch_num}: {e2}", file=sys.stderr)

    elapsed = time.time() - t_start
    print(f"\n[+] Successfully pushed {uploaded_count}/{total_records} records to Supabase in {elapsed:.2f}s!")
    return uploaded_count


def main():
    parser = argparse.ArgumentParser(description="Push Scopus Journal CSV data to Supabase.")
    parser.add_argument("--csv", type=str, default="scopus_journals.csv", help="Path to CSV file (default: scopus_journals.csv)")
    parser.add_argument("--table", type=str, default="scopus_journals", help="Supabase table name (default: scopus_journals)")
    parser.add_argument("--url", type=str, default=None, help="Supabase Project URL")
    parser.add_argument("--key", type=str, default=None, help="Supabase API key (service_role or anon)")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size for upload (default: 500)")

    args = parser.parse_args()
    push_csv_to_supabase(
        csv_file=args.csv,
        supabase_url=args.url,
        supabase_key=args.key,
        table_name=args.table,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
