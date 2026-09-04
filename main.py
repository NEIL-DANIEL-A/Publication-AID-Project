import argparse
import collections
import json
import os
import sys
import time
from typing import List

import pandas as pd

from models import CFRJournal, JournalResult
from processors.issn import normalize_issn
from scrapers.cfr_data_collection import scrape_cfr_journals
from scrapers.scimago import ScimagoScraper

DEFAULT_ISSN = "01296612"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def print_single_result(result: JournalResult):
    print("\n========================================")
    print("SCIMAGO POC")
    print("========================================")
    print(f"ISSN       : {result.issn}")
    print(f"Journal ID : {result.journal_id}")
    print(f"SJR        : {result.sjr}")
    print(f"Quartile   : {result.quartile}")
    print(f"H-Index    : {result.h_index}")
    print(f"Coverage   : {result.coverage}")
    print(f"Status     : {result.status}")
    if result.error:
        print(f"Error      : {result.error}")
    print("\n----------------------------------------")
    print(f"ISSN Execution Time : {result.execution_time:.2f} seconds")
    print("----------------------------------------")
    print(f"Search URL : {result.search_url}")
    print(f"Journal URL: {result.journal_url}")
    print("========================================\n")


def run_single_issn(issn: str):
    """Run SCImago scraping for a single ISSN (standalone test mode)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"[INFO] Starting SCImago POC for ISSN: {issn}")

    with ScimagoScraper(headless=True, verbose=True) as scraper:
        result = scraper.scrape_journal(issn)

    print_single_result(result)

    result_path = os.path.join(OUTPUT_DIR, "result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=4)
    print(f"[SUCCESS] Result saved to {result_path}")
    return result


def run_excel_batch(input_path: str):
    """Batch process ISSNs from an input Excel file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(input_path):
        print(f"[ERROR] Input Excel file not found: {input_path}")
        sys.exit(1)

    print(f"[INFO] Loading input Excel: {input_path}")
    df = pd.read_excel(input_path, dtype=str)

    issn_col = None
    for col in df.columns:
        if str(col).strip().upper() == "ISSN":
            issn_col = col
            break

    if not issn_col:
        print(f"[ERROR] Column 'ISSN' not found in {input_path}. Available columns: {list(df.columns)}")
        sys.exit(1)

    issn_list = df[issn_col].dropna().astype(str).tolist()
    total_count = len(issn_list)
    print(f"[INFO] Found {total_count} ISSNs to process.\n")

    results = []
    success_count = 0
    partial_count = 0
    failed_count = 0
    individual_times = []

    batch_start = time.perf_counter()

    with ScimagoScraper(headless=True, verbose=False) as scraper:
        for idx, raw_issn in enumerate(issn_list, 1):
            res = scraper.scrape_journal(raw_issn)

            if res.status == "SUCCESS":
                success_count += 1
                status_str = f"[{res.status}]"
            elif res.status == "PARTIAL":
                partial_count += 1
                status_str = f"[{res.status}]"
            else:
                failed_count += 1
                status_str = f"[{res.status}: {res.error}]"

            individual_times.append(res.execution_time)

            print(
                f"[{idx}/{total_count}] ISSN: {raw_issn:<10} -> JID: {res.journal_id:<12} | "
                f"SJR: {res.sjr:<6} | Quartile: {res.quartile:<2} | H-Index: {res.h_index:<4} | "
                f"Coverage: {res.coverage:<25} ({res.execution_time:.2f}s) {status_str}"
            )

            results.append({
                "ISSN": res.issn,
                "Journal ID": res.journal_id,
                "SJR": res.sjr,
                "Quartile": res.quartile,
                "H-Index": res.h_index,
                "Coverage": res.coverage,
                "Status": res.status,
                "Error": res.error or "",
                "Execution Time (seconds)": res.execution_time,
            })

    batch_end = time.perf_counter()
    total_batch_time = round(batch_end - batch_start, 2)
    total_batch_minutes = round(total_batch_time / 60.0, 2)
    average_time = round(sum(individual_times) / total_count, 2) if total_count > 0 else 0.0

    out_df = pd.DataFrame(results)
    out_path = os.path.join(OUTPUT_DIR, "scimago_results.xlsx")
    try:
        out_df.to_excel(out_path, index=False)
        saved_file = out_path
    except PermissionError:
        alt_path = os.path.join(OUTPUT_DIR, "scimago_results_latest.xlsx")
        out_df.to_excel(alt_path, index=False)
        saved_file = alt_path

    # Print Batch Summary
    print("\n========================================")
    print("SCIMAGO BATCH SUMMARY")
    print("========================================")
    print(f"Total ISSNs     : {total_count}")
    print(f"Successful      : {success_count}")
    print(f"Partial         : {partial_count}")
    print(f"Failed          : {failed_count}")
    print()
    print(f"Total Batch Time: {total_batch_time:.2f} seconds ({total_batch_minutes:.2f} minutes)")
    print()
    print(f"Average / ISSN  : {average_time:.2f} seconds")
    print()
    print("Estimates based on measured average:")
    print(f"  100 ISSNs  ~ {(100 * average_time / 60.0):.1f} minutes")
    print(f"  500 ISSNs  ~ {(500 * average_time / 60.0):.1f} minutes")
    print(f"  1000 ISSNs ~ {(1000 * average_time / 60.0):.1f} minutes")
    print("========================================\n")
    print(f"[SUCCESS] Results saved to {saved_file}")


def report_duplicates(journals: List[CFRJournal]):
    """Analyze and report duplicates in CFR journals list."""
    titles = [j.journal_title.strip().upper() for j in journals if j.journal_title]
    p_issns = [normalize_issn(j.print_issn) for j in journals if normalize_issn(j.print_issn) != "no data"]
    e_issns = [normalize_issn(j.e_issn) for j in journals if normalize_issn(j.e_issn) != "no data"]

    dup_titles = sum(count - 1 for count in collections.Counter(titles).values() if count > 1)
    dup_p_issns = sum(count - 1 for count in collections.Counter(p_issns).values() if count > 1)
    dup_e_issns = sum(count - 1 for count in collections.Counter(e_issns).values() if count > 1)

    print(f"Duplicate journal titles: {dup_titles}")
    print(f"Duplicate Print-ISSNs: {dup_p_issns}")
    print(f"Duplicate E-ISSNs: {dup_e_issns}")


def run_source_only():
    """Scrape CFR website and export CFR records to output/cfr_journals.xlsx."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("[INFO] Starting CFR Data Collection (Source-Only Mode)...")

    cfr_start = time.perf_counter()
    journals, total_pages = scrape_cfr_journals()
    cfr_duration = time.perf_counter() - cfr_start

    print(f"[TIME] CFR collection duration: {cfr_duration:.2f} seconds")
    report_duplicates(journals)

    rows = []
    for j in journals:
        rows.append({
            "Sl.No": j.sl_no,
            "Full Journal Title": j.journal_title,
            "Print-ISSN": j.print_issn,
            "E-ISSN": j.e_issn,
            "Publisher": j.publisher,
            "Country": j.country,
        })

    out_df = pd.DataFrame(rows)
    out_path = os.path.join(OUTPUT_DIR, "cfr_journals.xlsx")
    try:
        out_df.to_excel(out_path, index=False)
        saved_file = out_path
    except PermissionError:
        alt_path = os.path.join(OUTPUT_DIR, "cfr_journals_latest.xlsx")
        out_df.to_excel(alt_path, index=False)
        saved_file = alt_path

    print(f"[SUCCESS] CFR journals saved to {saved_file} ({len(journals)} records)")
    return journals


def run_complete_pipeline():
    """
    Complete pipeline:
    CFR collection -> ISSN normalization -> SCImago lookup (Print -> fallback E-ISSN) -> Final Excel.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pipeline_start = time.perf_counter()

    # Stage 1: CFR Collection
    print("[INFO] Stage 1: Starting CFR Data Collection...")
    cfr_start = time.perf_counter()
    journals, total_pages = scrape_cfr_journals()
    cfr_duration = time.perf_counter() - cfr_start
    print(f"[TIME] CFR collection duration: {cfr_duration:.2f} seconds\n")

    report_duplicates(journals)
    print()

    # Stage 2: SCImago Enrichment
    print("[INFO] Stage 2: SCImago Enrichment (Print-ISSN with E-ISSN fallback)...")
    results = []
    scimago_attempted = 0
    scimago_successful = 0
    scimago_failed = 0
    journal_processing_times = []

    with ScimagoScraper(headless=True, verbose=False) as scraper:
        for idx, j in enumerate(journals, 1):
            j_start = time.perf_counter()
            scimago_attempted += 1

            norm_print = normalize_issn(j.print_issn)
            norm_e = normalize_issn(j.e_issn)

            matched_issn = "no data"
            scimago_res = None

            # 1. Try Print-ISSN first
            if norm_print != "no data":
                res = scraper.scrape_journal(norm_print)
                if res.status in ["SUCCESS", "PARTIAL"]:
                    scimago_res = res
                    matched_issn = j.print_issn
                elif res.status == "FAILED" and norm_e == "no data":
                    scimago_res = res

            # 2. Try E-ISSN fallback if Print-ISSN failed or was missing
            if (scimago_res is None or scimago_res.status == "FAILED") and norm_e != "no data":
                res = scraper.scrape_journal(norm_e)
                if res.status in ["SUCCESS", "PARTIAL"]:
                    scimago_res = res
                    matched_issn = j.e_issn
                elif scimago_res is None:
                    scimago_res = res

            j_time = round(time.perf_counter() - j_start, 2)
            journal_processing_times.append(j_time)

            if scimago_res and scimago_res.status in ["SUCCESS", "PARTIAL"]:
                scimago_successful += 1
                status_display = scimago_res.status
                err_display = scimago_res.error or ""
                j_id = scimago_res.journal_id
                sjr_val = scimago_res.sjr
                q_val = scimago_res.quartile
                h_val = scimago_res.h_index
                cov_val = scimago_res.coverage
                scimago_url = scimago_res.journal_url
            else:
                scimago_failed += 1
                status_display = "not found"
                err_display = "Journal not found on SCImago"
                j_id = "no data"
                sjr_val = "no data"
                q_val = "no data"
                h_val = "no data"
                cov_val = "no data"
                scimago_url = "no data"

            # Progress output
            print(
                f"[{idx}/{len(journals)}] {j.journal_title[:32]:<32} | "
                f"P:{j.print_issn or 'none':<9} E:{j.e_issn or 'none':<9} -> "
                f"Match: {matched_issn:<10} | Q: {q_val:<2} | SJR: {sjr_val:<6} | ({j_time:.2f}s) [{status_display}]",
                flush=True
            )

            results.append({
                "Sl.No": j.sl_no,
                "Full Journal Title": j.journal_title,
                "Print-ISSN": j.print_issn,
                "E-ISSN": j.e_issn,
                "Publisher": j.publisher,
                "Country": j.country,
                "SCImago Matched ISSN": matched_issn,
                "SCImago Journal ID": j_id,
                "SJR": sjr_val,
                "Quartile": q_val,
                "H-Index": h_val,
                "Coverage": cov_val,
                "SCImago URL": scimago_url,
                "Status": status_display,
                "Error": err_display,
                "Processing Time (sec)": j_time,
            })

    total_pipeline_time = round(time.perf_counter() - pipeline_start, 2)
    avg_journal_time = round(sum(journal_processing_times) / len(journals), 2) if journals else 0.0

    # Write output to Excel
    out_df = pd.DataFrame(results)
    out_path = os.path.join(OUTPUT_DIR, "cfr_scimago_results.xlsx")
    try:
        out_df.to_excel(out_path, index=False)
        saved_file = out_path
    except PermissionError:
        alt_path = os.path.join(OUTPUT_DIR, "cfr_scimago_results_latest.xlsx")
        out_df.to_excel(alt_path, index=False)
        saved_file = alt_path

    # Print Pipeline Summary
    print("\n========================================")
    print("PIPELINE SUMMARY")
    print("========================================")
    print(f"CFR pages scraped:       {total_pages}")
    print(f"CFR journals collected:  {len(journals)}")
    print()
    print(f"SCImago attempted:       {scimago_attempted}")
    print(f"SCImago successful:      {scimago_successful}")
    print(f"SCImago failed:          {scimago_failed}")
    print()
    print(f"CFR collection time:     {cfr_duration:.2f} sec")
    print(f"Total execution time:    {total_pipeline_time:.2f} sec ({round(total_pipeline_time / 60.0, 2)} min)")
    print(f"Average journal time:    {avg_journal_time:.2f} sec")
    print("========================================\n")
    print(f"[SUCCESS] Results saved to {saved_file}")


def main():
    parser = argparse.ArgumentParser(description="CFR Journal Collection & SCImago Scraper")
    parser.add_argument("--source-only", action="store_true", help="Scrape only CFR journals and export to Excel")
    parser.add_argument("--scimago-only", action="store_true", help="Run only SCImago POC on a given ISSN")
    parser.add_argument("--issn", type=str, default=None, help="Single ISSN to scrape (used with --scimago-only)")
    parser.add_argument("--input", type=str, default=None, help="Path to input Excel file with an 'ISSN' column")

    args = parser.parse_args()

    if args.source_only:
        run_source_only()
    elif args.scimago_only:
        target_issn = args.issn if args.issn else DEFAULT_ISSN
        run_single_issn(target_issn)
    elif args.input:
        run_excel_batch(args.input)
    elif args.issn:
        run_single_issn(args.issn)
    else:
        run_complete_pipeline()


if __name__ == "__main__":
    main()
