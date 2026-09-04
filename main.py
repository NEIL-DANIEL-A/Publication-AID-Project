import argparse
import json
import os
import sys
import time
import pandas as pd
from scimago_scraper import ScimagoScraper
from models import JournalResult

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
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(input_path):
        print(f"[ERROR] Input Excel file not found: {input_path}")
        sys.exit(1)
        
    print(f"[INFO] Loading input Excel: {input_path}")
    df = pd.read_excel(input_path, dtype=str)
    
    # Locate ISSN column (case-insensitive)
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


def main():
    parser = argparse.ArgumentParser(description="SCImago Journal Scraper POC using Scrapling")
    parser.add_argument("--issn", type=str, default=None, help="Single ISSN to scrape (default: 01296612)")
    parser.add_argument("--input", type=str, default=None, help="Path to input Excel file with an 'ISSN' column")
    
    args = parser.parse_args()
    
    if args.input:
        run_excel_batch(args.input)
    else:
        target_issn = args.issn if args.issn else DEFAULT_ISSN
        run_single_issn(target_issn)


if __name__ == "__main__":
    main()
