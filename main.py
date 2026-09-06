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

# Database (Supabase) - optional, graceful fallback to Excel if not configured
try:
    from database.connection import get_supabase_client, is_supabase_configured
    from database.hash import build_hash_input, compute_data_hash, _normalize_value
    from database.repository import (
        get_journal_by_issn,
        get_all_journals_map,
        get_existing_full,
        insert_journal_full,
        update_journal_full,
        touch_journal_checked,
        create_pipeline_run,
        finish_pipeline_run,
        insert_skipped_record,
    )
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    is_supabase_configured = lambda: False  # type: ignore
    _normalize_value = lambda v: str(v or "").strip().lower()  # type: ignore

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


def run_complete_pipeline(scopus_file: str = None, workers: int = 5):
    """
    Complete pipeline:
    CFR collection -> Scopus Verification -> MJL Verification (hybrid) -> SCImago lookup -> Consolidated Excel.
    Filtering: Only Scopus Active / Indexed journals proceed to MJL and SCImago.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pipeline_start = time.perf_counter()

    if scopus_file is None:
        scopus_file = os.path.join(OUTPUT_DIR, "scopus_source_title_list.xlsx")

    # Stage 1: CFR Collection
    print("[INFO] Stage 1: Starting CFR Data Collection...")
    cfr_start = time.perf_counter()
    journals, total_pages = scrape_cfr_journals()
    cfr_duration = time.perf_counter() - cfr_start
    print(f"[TIME] CFR collection duration: {cfr_duration:.2f} seconds\n")

    report_duplicates(journals)
    # Deduplicate CFR by ISSN (both Print and E-ISSN) - same ISSN appearing as Print in one row and E-ISSN in another (e.g., 2572-3618 at sl_no 124 and 151) would cause 2 DB updates per run
    # Skipped details are stored in skipped_records table for audit (so you know which one is skipped)
    seen_issns = {}
    deduped = []
    dup_skipped = 0
    cfr_skipped_details = []  # list of dicts for DB insert later
    for j in journals:
        norms = [n for n in (normalize_issn(j.print_issn), normalize_issn(j.e_issn)) if n != "no data"]
        duplicate_norm = next((n for n in norms if n in seen_issns), None)
        if duplicate_norm:
            dup_skipped += 1
            kept_title = seen_issns[duplicate_norm]
            print(f"[SKIPPED] CFR duplicate ISSN {duplicate_norm} -> sl_no {j.sl_no} '{j.journal_title[:40]}' (kept '{kept_title[:40]}')")
            cfr_skipped_details.append({
                "sl_no": j.sl_no,
                "journal_title": j.journal_title,
                "print_issn": j.print_issn,
                "e_issn": j.e_issn,
                "normalized_print": normalize_issn(j.print_issn),
                "normalized_e": normalize_issn(j.e_issn),
                "publisher": j.publisher,
                "country": j.country,
                "reason": "duplicate_issn",
                "duplicate_of_issn": duplicate_norm,
                "duplicate_of_title": kept_title,
            })
            continue
        for n in norms:
            seen_issns[n] = j.journal_title
        deduped.append(j)
    if dup_skipped:
        print(f"[INFO] CFR deduplicated: {len(journals)} -> {len(deduped)} (skipped {dup_skipped} duplicate ISSN)")
        journals = deduped
    # Keep skipped details for DB insert after pipeline_run_id is created
    # (attached to function attribute for later use)
    run_complete_pipeline._cfr_skipped_details = cfr_skipped_details
    print()

    # Stage 2: Scopus Verification
    print("[INFO] Stage 2: Scopus Verification (via official Source Title List)...")
    scopus_init_start = time.perf_counter()

    from scrapers.scopus import verify_scopus_indexing
    verified_pairs, scopus_stats = verify_scopus_indexing(journals, scopus_file)

    scopus_init_time = scopus_stats["dataset_load_time"] + scopus_stats["construction_time"]
    scopus_verify_time = scopus_stats["verification_time"]
    print(
        f"[INFO] Scopus Dataset Load: {scopus_stats['dataset_load_time']:.2f}s | "
        f"Index Construction: {scopus_stats['construction_time']:.2f}s | "
        f"Journal Verification: {scopus_verify_time:.4f}s"
    )

    print("\n--- Scopus Verification Summary ---")
    print(f"Total CFR Journals        : {scopus_stats['total_journals']}")
    print(f"  Scopus Active / Indexed : {scopus_stats['active_indexed']}")
    print(f"  Scopus Inactive         : {scopus_stats['inactive']}")
    print(f"  Scopus Discontinued     : {scopus_stats['discontinued']}")
    print(f"  Scopus Not Indexed      : {scopus_stats['not_indexed']}")
    print(f"  Scopus Unable to Verify : {scopus_stats['unable_to_verify']}")
    print("-----------------------------------\n")

    # Stage 3: MJL Index Verification (Clarivate Web of Science) - Hybrid
    eligible_pairs = [(j, s) for j, s in verified_pairs if s.scopus_status == "Active / Indexed"]
    skipped_pairs  = [(j, s) for j, s in verified_pairs if s.scopus_status != "Active / Indexed"]

    print(f"[INFO] Stage 3: MJL Index Verification (Active/Indexed: {len(eligible_pairs)} journals)...")
    mjl_start_time = time.perf_counter()

    from scrapers.mjl import verify_mjl_indexing
    mjl_triples = verify_mjl_indexing(eligible_pairs, headless=True, verbose=False, max_workers=workers)

    mjl_duration = round(time.perf_counter() - mjl_start_time, 2)

    mjl_found      = sum(1 for _, _, m in mjl_triples if m.mjl_status == "Found")
    mjl_not_found  = sum(1 for _, _, m in mjl_triples if m.mjl_status == "Not Found")
    mjl_unverified = sum(1 for _, _, m in mjl_triples if m.mjl_status == "Unable to Verify")

    print(f"\n--- MJL Verification Summary ---")
    print(f"  MJL Found           : {mjl_found}")
    print(f"  MJL Not Found       : {mjl_not_found}")
    print(f"  MJL Unable to Verify: {mjl_unverified}")
    print(f"  MJL Stage Time      : {mjl_duration:.2f} sec")
    print(f"--------------------------------\n")

    mjl_lookup = {j.sl_no: m for j, _, m in mjl_triples}

    # Stage 4: SCImago Enrichment (same eligible set)
    print(f"[INFO] Stage 4: SCImago Enrichment (Eligible Active/Indexed: {len(eligible_pairs)} | Skipped: {len(skipped_pairs)})...")

    results = []
    scimago_attempted = 0
    scimago_successful = 0
    scimago_failed = 0
    scimago_duration = 0.0

    scimago_start_time = time.perf_counter()

    def process_eligible_pair(idx_pair, scraper_inst):
        idx, (j, s_res) = idx_pair
        j_start = time.perf_counter()

        norm_print = normalize_issn(j.print_issn)
        norm_e = normalize_issn(j.e_issn)

        matched_issn = "no data"
        scimago_res = None

        # 1. Try Print-ISSN first
        if norm_print != "no data":
            res = scraper_inst.scrape_journal(norm_print)
            if res.status in ["SUCCESS", "PARTIAL"]:
                scimago_res = res
                matched_issn = j.print_issn
            elif res.status == "FAILED" and norm_e == "no data":
                scimago_res = res

        # 2. Try E-ISSN fallback if Print-ISSN failed or was missing
        if (scimago_res is None or scimago_res.status == "FAILED") and norm_e != "no data":
            res = scraper_inst.scrape_journal(norm_e)
            if res.status in ["SUCCESS", "PARTIAL"]:
                scimago_res = res
                matched_issn = j.e_issn
            elif scimago_res is None:
                scimago_res = res

        j_time = round(time.perf_counter() - j_start, 2)

        if scimago_res and scimago_res.status in ["SUCCESS", "PARTIAL"]:
            status_display = scimago_res.status
            err_display = scimago_res.error or ""
            j_id = scimago_res.journal_id
            sjr_val = scimago_res.sjr
            q_val = scimago_res.quartile
            h_val = scimago_res.h_index
            cov_val = scimago_res.coverage
            scimago_url = scimago_res.journal_url
            is_success = True
        else:
            status_display = "not found"
            err_display = "Journal not found on SCImago"
            j_id = "no data"
            sjr_val = "no data"
            q_val = "no data"
            h_val = "no data"
            cov_val = "no data"
            scimago_url = "no data"
            is_success = False

        m_res = mjl_lookup.get(j.sl_no)
        mjl_status_val  = m_res.mjl_status       if m_res else "no data"
        mjl_index_val   = m_res.mjl_index        if m_res else "no data"
        mjl_issn_val    = m_res.mjl_issn_used    if m_res else "no data"
        mjl_title_val   = m_res.mjl_source_title if m_res else "no data"

        record = {
            "Sl.No": j.sl_no,
            "Full Journal Title": j.journal_title,
            "Print-ISSN": j.print_issn,
            "E-ISSN": j.e_issn,
            "Publisher": j.publisher,
            "Country": j.country,
            "Scopus Indexing Status": s_res.scopus_status,
            "Scopus Match Type": s_res.match_type,
            "Scopus Source Record ID": s_res.sourcerecord_id,
            "Scopus Source Title": s_res.source_title,
            "Scopus Publisher": s_res.scopus_publisher,
            "Scopus Coverage": s_res.scopus_coverage,
            "MJL Status": mjl_status_val,
            "MJL Index": mjl_index_val,
            "MJL Matched ISSN": mjl_issn_val,
            "MJL Source Title": mjl_title_val,
            "SCImago Matched ISSN": matched_issn,
            "SCImago Journal ID": j_id,
            "SJR": sjr_val,
            "Quartile": q_val,
            "H-Index": h_val,
            "SCImago Coverage": cov_val,
            "SCImago URL": scimago_url,
            "SCImago Status": status_display,
            "SCImago Error": err_display,
            "SCImago Execution Time (sec)": j_time,
        }

        return idx, record, is_success, j_time, j.journal_title, s_res.scopus_status, sjr_val, q_val, status_display

    with ScimagoScraper(headless=True, verbose=False) as scraper:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        indexed_pairs = list(enumerate(eligible_pairs, 1))
        scimago_attempted = len(eligible_pairs)

        processed_records = {}

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(process_eligible_pair, item, scraper): item[0]
                for item in indexed_pairs
            }
            for future in as_completed(future_map):
                idx, record, is_success, j_time, title, sc_stat, sjr_val, q_val, status_display = future.result()
                processed_records[idx] = record
                if is_success:
                    scimago_successful += 1
                else:
                    scimago_failed += 1

                print(
                    f"[ELIGIBLE {idx}/{len(eligible_pairs)}] {title[:30]:<30} | "
                    f"Scopus: {sc_stat:<16} | SJR: {sjr_val:<6} | Q: {q_val:<2} ({j_time:.2f}s) [{status_display}]",
                    flush=True
                )

        # Re-sort results by original CFR Sl.No order
        for idx in range(1, len(eligible_pairs) + 1):
            results.append(processed_records[idx])

    scimago_duration = round(time.perf_counter() - scimago_start_time, 2)

    # Append skipped non-eligible journals (Discontinued, Inactive, Not Indexed)
    for j, s_res in skipped_pairs:
        results.append({
            "Sl.No": j.sl_no,
            "Full Journal Title": j.journal_title,
            "Print-ISSN": j.print_issn,
            "E-ISSN": j.e_issn,
            "Publisher": j.publisher,
            "Country": j.country,
            "Scopus Indexing Status": s_res.scopus_status,
            "Scopus Match Type": s_res.match_type,
            "Scopus Source Record ID": s_res.sourcerecord_id,
            "Scopus Source Title": s_res.source_title,
            "Scopus Publisher": s_res.scopus_publisher,
            "Scopus Coverage": s_res.scopus_coverage,
            "MJL Status": "skipped",
            "MJL Index": "skipped",
            "MJL Matched ISSN": "skipped",
            "MJL Source Title": "skipped",
            "SCImago Matched ISSN": "skipped",
            "SCImago Journal ID": "skipped",
            "SJR": "skipped",
            "Quartile": "skipped",
            "H-Index": "skipped",
            "SCImago Coverage": "skipped",
            "SCImago URL": "skipped",
            "SCImago Status": "skipped (not active in Scopus)",
            "SCImago Error": "",
            "SCImago Execution Time (sec)": 0.0,
        })

    # ------------------------------------------------------------------ #
    # Database incremental persistence (Supabase - source of truth)
    # ------------------------------------------------------------------ #
    use_db = DB_AVAILABLE and is_supabase_configured()
    db_stats = {"new_records": 0, "updated_records": 0, "unchanged_records": 0, "failed_records": 0}
    pipeline_run_id = None
    db_duration = 0.0

    if use_db:
        try:
            pipeline_run_id = create_pipeline_run(total_cfr=len(journals))
        except Exception as e:
            print(f"[WARNING] Could not create pipeline_run: {e}")
            pipeline_run_id = None

        # Persist skipped CFR duplicates (so you know which one is skipped)
        if pipeline_run_id and hasattr(run_complete_pipeline, '_cfr_skipped_details'):
            skipped_list = getattr(run_complete_pipeline, '_cfr_skipped_details', [])
            if skipped_list:
                print(f"[INFO] DB: Persisting {len(skipped_list)} skipped CFR duplicate(s) to skipped_records...", flush=True)
                for s in skipped_list:
                    try:
                        insert_skipped_record(
                            pipeline_run_id,
                            s["journal_title"], s["print_issn"], s["e_issn"],
                            s["normalized_print"], s["normalized_e"],
                            s["publisher"], s["country"], s["sl_no"],
                            s["reason"], s["duplicate_of_issn"], s["duplicate_of_title"]
                        )
                        print(f"  [SKIPPED-DB] sl_no {s['sl_no']} '{s['journal_title'][:35]}' ISSN {s['duplicate_of_issn']} (kept '{s['duplicate_of_title'][:30]}')", flush=True)
                    except Exception as e:
                        print(f"[WARNING] Could not insert skipped record {s['sl_no']}: {e}")
            # Track for pipeline summary
            db_stats["duplicate_skipped"] = len(skipped_list)
        else:
            db_stats["duplicate_skipped"] = 0

        # Bulk fetch for fast lookup (1 query vs 500+)
        print(f"[INFO] DB: Fetching existing journals for incremental check...", flush=True)
        bulk_start = time.perf_counter()
        try:
            from processors.issn import normalize_issn as _norm
            journals_map = get_all_journals_map()
            unique_journals = len(set(v["id"] for v in journals_map.values())) if journals_map else 0
            print(f"[INFO] DB: Loaded {unique_journals} existing journals ({len(journals_map)} ISSN keys) in {time.perf_counter()-bulk_start:.2f}s (bulk, 1 query)", flush=True)
            # Build lookup helper
            def _lookup_existing(print_raw, e_raw):
                for norm in (_norm(print_raw), _norm(e_raw)):
                    if norm == "no data" or not norm:
                        continue
                    if norm in journals_map:
                        return journals_map[norm]
                return None
        except Exception as e:
            print(f"[WARNING] Bulk fetch failed, falling back to per-journal lookup: {e}")
            journals_map = {}
            def _lookup_existing(print_raw, e_raw):
                return get_journal_by_issn(print_raw, e_raw)

        db_start = time.perf_counter()
        total = len(results)
        for idx, rec in enumerate(results, 1):
            # Progress log every record (fast) + summary every 50
            if idx == 1 or idx % 50 == 0 or idx == total:
                print(f"[DB {idx}/{total}] Processing {rec.get('Full Journal Title','?')[:35]:35} ...", flush=True)
            try:
                # Build hash input from ALL extracted fields (any field change -> new hash)
                # Compute mjl_match_type as stored in DB for consistent hashing
                _mjl_match_for_hash = "No Match" if rec["MJL Status"] in ("Not Found", "Unable to Verify", "skipped", "no data") else "Print ISSN" if rec["MJL Matched ISSN"] != "no data" and rec["MJL Matched ISSN"] != "skipped" else "No Match"
                hash_input = build_hash_input(
                    journal_title=rec["Full Journal Title"],
                    print_issn=rec["Print-ISSN"],
                    e_issn=rec["E-ISSN"],
                    publisher=rec["Publisher"],
                    country=rec["Country"],
                    cfr_sl_no=rec["Sl.No"],
                    scopus_status=rec["Scopus Indexing Status"],
                    scopus_match_type=rec["Scopus Match Type"],
                    scopus_source_title=rec["Scopus Source Title"],
                    scopus_sourcerecord_id=rec["Scopus Source Record ID"],
                    scopus_publisher=rec["Scopus Publisher"],
                    scopus_coverage=rec["Scopus Coverage"],
                    scopus_issn="",  # stored but not in record - keep "" for now
                    scopus_eissn="",
                    scopus_raw_active="",
                    scopus_raw_discontinued="",
                    mjl_status=rec["MJL Status"],
                    mjl_index=rec["MJL Index"],
                    mjl_issn_used=rec["MJL Matched ISSN"],
                    mjl_match_type=_mjl_match_for_hash,
                    mjl_source_title=rec["MJL Source Title"],
                    scimago_status=rec["SCImago Status"],
                    scimago_journal_id=rec["SCImago Journal ID"],
                    scimago_matched_issn=rec["SCImago Matched ISSN"],
                    sjr=rec["SJR"],
                    quartile=rec["Quartile"],
                    h_index=rec["H-Index"],
                    scimago_coverage=rec["SCImago Coverage"],
                    scimago_url=rec["SCImago URL"],
                )
                new_hash = compute_data_hash(hash_input)

                # Prepare DB payloads
                journal_data = {
                    "title": rec["Full Journal Title"],
                    "print_issn": rec["Print-ISSN"],
                    "e_issn": rec["E-ISSN"],
                    "publisher": rec["Publisher"],
                    "country": rec["Country"],
                }
                cfr_data = {
                    "sl_no": rec["Sl.No"],
                    "journal_title": rec["Full Journal Title"],
                    "print_issn": rec["Print-ISSN"],
                    "e_issn": rec["E-ISSN"],
                    "publisher": rec["Publisher"],
                    "country": rec["Country"],
                }
                scopus_data = {
                    "scopus_status": rec["Scopus Indexing Status"],
                    "match_type": rec["Scopus Match Type"],
                    "sourcerecord_id": rec["Scopus Source Record ID"],
                    "source_title": rec["Scopus Source Title"],
                    "scopus_publisher": rec["Scopus Publisher"],
                    "scopus_coverage": rec["Scopus Coverage"],
                    "scopus_issn": "",
                    "scopus_eissn": "",
                    "raw_active_status": "",
                    "raw_discontinued_flag": "",
                }
                # For skipped, execution_time is skipped string; handle
                mjl_exec = rec.get("MJL Execution Time (sec)", "no data")
                try:
                    mjl_exec_val = float(mjl_exec) if str(mjl_exec).replace(".", "", 1).isdigit() else None
                except:
                    mjl_exec_val = None
                mjl_data = {
                    "mjl_status": rec["MJL Status"],
                    "mjl_index": rec["MJL Index"],
                    "mjl_issn_used": rec["MJL Matched ISSN"],
                    "mjl_match_type": "No Match" if rec["MJL Status"] in ("Not Found", "Unable to Verify", "skipped") else "Print ISSN",
                    "mjl_source_title": rec["MJL Source Title"],
                    "execution_time": mjl_exec_val,
                    "error": "",
                }
                sci_exec = rec.get("SCImago Execution Time (sec)", 0.0)
                try:
                    sci_exec_val = float(sci_exec)
                except:
                    sci_exec_val = 0.0
                scimago_data = {
                    "scimago_status": rec["SCImago Status"],
                    "journal_id_external": rec["SCImago Journal ID"],
                    "matched_issn": rec["SCImago Matched ISSN"],
                    "sjr": rec["SJR"],
                    "quartile": rec["Quartile"],
                    "h_index": rec["H-Index"],
                    "coverage": rec["SCImago Coverage"],
                    "url": rec["SCImago URL"],
                    "execution_time": sci_exec_val,
                    "error": rec["SCImago Error"],
                }

                existing = _lookup_existing(rec["Print-ISSN"], rec["E-ISSN"])
                if existing is None:
                    # Case A: New
                    new_id = insert_journal_full(journal_data, cfr_data, scopus_data, mjl_data, scimago_data, new_hash, pipeline_run_id or "")
                    # Add to map for duplicate ISSN within same run
                    from processors.issn import normalize_issn as _n2
                    for norm in (_n2(rec["Print-ISSN"]), _n2(rec["E-ISSN"])):
                        if norm and norm != "no data":
                            journals_map[norm] = {"id": new_id, "data_hash": new_hash, **journal_data}
                    db_stats["new_records"] += 1
                    if idx % 10 == 0 or idx == total:
                        print(f"  -> [NEW] {rec['Full Journal Title'][:30]}", flush=True)
                else:
                    old_hash = existing.get("data_hash") or ""
                    if old_hash == new_hash:
                        # Case B: Unchanged
                        if pipeline_run_id:
                            touch_journal_checked(existing["id"], pipeline_run_id)
                        db_stats["unchanged_records"] += 1
                        if idx % 50 == 0:
                            print(f"  -> [UNCHANGED] {idx} processed", flush=True)
                    else:
                        # Case C: Changed - field-level diff
                        full_old = get_existing_full(existing["id"])
                        changes = []
                        # Compare journal-level fields (using same normalization as hash to suppress & vs AND etc.)
                        for field, new_v in [("title", rec["Full Journal Title"]), ("publisher", rec["Publisher"]), ("country", rec["Country"])]:
                            old_v = full_old["journal"].get(field if field != "title" else "title", "")
                            if _normalize_value(old_v) != _normalize_value(new_v):
                                changes.append(("journal", field, old_v, new_v))
                        # CFR sl_no (now part of hash)
                        cfr_old_sl = full_old["cfr"].get("sl_no", "")
                        if _normalize_value(cfr_old_sl) != _normalize_value(rec["Sl.No"]):
                            changes.append(("cfr", "sl_no", cfr_old_sl, rec["Sl.No"]))
                        # Scopus - compare all hash-relevant fields
                        for f, new_v in [
                            ("scopus_status", rec["Scopus Indexing Status"]),
                            ("match_type", rec["Scopus Match Type"]),
                            ("source_title", rec["Scopus Source Title"]),
                            ("sourcerecord_id", rec["Scopus Source Record ID"]),
                            ("scopus_publisher", rec["Scopus Publisher"]),
                            ("scopus_coverage", rec["Scopus Coverage"]),
                        ]:
                            old_v = full_old["scopus"].get(f, "")
                            if _normalize_value(old_v) != _normalize_value(new_v):
                                changes.append(("scopus", f, old_v, new_v))
                        # MJL - all fields including match_type (now in hash)
                        _new_mjl_match = "No Match" if rec["MJL Status"] in ("Not Found", "Unable to Verify", "skipped", "no data") else "Print ISSN" if rec["MJL Matched ISSN"] not in ("no data", "skipped", "") else "No Match"
                        for f, new_v in [("mjl_status", rec["MJL Status"]), ("mjl_index", rec["MJL Index"]), ("mjl_issn_used", rec["MJL Matched ISSN"]), ("mjl_match_type", _new_mjl_match), ("mjl_source_title", rec["MJL Source Title"])]:
                            old_v = full_old["mjl"].get(f, "")
                            if _normalize_value(old_v) != _normalize_value(new_v):
                                changes.append(("mjl", f, old_v, new_v))
                        # SCImago - all fields
                        for f, new_v in [
                            ("sjr", rec["SJR"]), ("quartile", rec["Quartile"]), ("h_index", rec["H-Index"]),
                            ("coverage", rec["SCImago Coverage"]), ("scimago_status", rec["SCImago Status"]),
                            ("journal_id_external", rec["SCImago Journal ID"]), ("matched_issn", rec["SCImago Matched ISSN"]),
                            ("url", rec["SCImago URL"]),
                        ]:
                            old_v = full_old["scimago"].get(f, "")
                            if _normalize_value(old_v) != _normalize_value(new_v):
                                changes.append(("scimago", f, old_v, new_v))
                        if not changes:
                            # Hash differed but no field diff due to normalization edge - treat as updated with hash only
                            changes.append(("journal", "data_hash", old_hash, new_hash))
                        update_journal_full(existing["id"], journal_data, cfr_data, scopus_data, mjl_data, scimago_data, new_hash, pipeline_run_id or "", changes)
                        # Update map hash for next duplicate check
                        existing["data_hash"] = new_hash
                        db_stats["updated_records"] += 1
                        print(f"  -> [UPDATED] {rec['Full Journal Title'][:30]} fields: {', '.join([c[1] for c in changes][:3])}", flush=True)

            except Exception as e:
                print(f"[WARNING] DB failed for {rec.get('Full Journal Title','?')[:30]}: {e}")
                db_stats["failed_records"] += 1

        db_duration = round(time.perf_counter() - db_start, 2)
        print(f"[INFO] DB persistence complete: {db_stats['new_records']} new | {db_stats['updated_records']} updated | {db_stats['unchanged_records']} unchanged | {db_stats['failed_records']} failed in {db_duration:.2f}s", flush=True)
        # Finish pipeline_run
        if pipeline_run_id:
            try:
                total_duration = round(time.perf_counter() - pipeline_start, 2)
                finish_pipeline_run(pipeline_run_id, "success", total_duration, {
                    "total_cfr": len(journals),
                    "total_scopus_active": scopus_stats.get("active_indexed", 0),
                    "total_mjl_processed": len(eligible_pairs),
                    "total_scimago_processed": len(eligible_pairs),
                    "new_records": db_stats["new_records"],
                    "updated_records": db_stats["updated_records"],
                    "unchanged_records": db_stats["unchanged_records"],
                    "failed_records": db_stats["failed_records"],
                })
            except Exception as e:
                print(f"[WARNING] Could not finish pipeline_run: {e}")
    else:
        print("[INFO] Supabase not configured (set SUPABASE_URL/KEY in .env) - skipping DB, using Excel only")

    total_pipeline_time = round(time.perf_counter() - pipeline_start, 2)

    # Write output to Excel (legacy, optional)
    # Excel is no longer source of truth; kept for debug if needed
    out_df = pd.DataFrame(results)
    out_path = os.path.join(OUTPUT_DIR, "cfr_scopus_mjl_scimago_results.xlsx")
    try:
        out_df.to_excel(out_path, index=False)
        saved_file = out_path
    except PermissionError:
        alt_path = os.path.join(OUTPUT_DIR, "cfr_scopus_mjl_scimago_results_latest.xlsx")
        out_df.to_excel(alt_path, index=False)
        saved_file = alt_path

    # Print Final Pipeline Execution Summary
    print("\n========================================")
    print("COMPLETE PIPELINE EXECUTION SUMMARY")
    print("========================================")
    print(f"Total CFR journals collected : {len(journals)}")
    print(f"  Scopus Active / Indexed   : {scopus_stats['active_indexed']}")
    print(f"  Scopus Inactive           : {scopus_stats['inactive']}")
    print(f"  Scopus Discontinued       : {scopus_stats['discontinued']}")
    print(f"  Scopus Not Indexed        : {scopus_stats['not_indexed']}")
    print(f"  Scopus Unable to Verify   : {scopus_stats['unable_to_verify']}")
    print()
    print(f"MJL Verification (Active)   : {len(eligible_pairs)}")
    print(f"  MJL Found                 : {mjl_found}")
    print(f"  MJL Not Found             : {mjl_not_found}")
    print(f"  MJL Unable to Verify      : {mjl_unverified}")
    print()
    print(f"Sent to SCImago (Active)    : {len(eligible_pairs)}")
    print(f"Skipped from SCImago        : {len(skipped_pairs)}")
    print(f"  SCImago Successful        : {scimago_successful}")
    print(f"  SCImago Failed            : {scimago_failed}")
    print()
    if use_db:
        print(f"Database (Supabase)       : {db_stats['new_records']} new | {db_stats['updated_records']} updated | {db_stats['unchanged_records']} unchanged | {db_stats['failed_records']} failed | {db_stats.get('duplicate_skipped',0)} CFR duplicate ISSN skipped")
        print(f"  DB time                 : {db_duration:.2f} sec")
        if db_stats.get('duplicate_skipped',0):
            print(f"  Skipped CFR duplicates logged to skipped_records table (query: SELECT * FROM skipped_records WHERE pipeline_run_id='{pipeline_run_id}')")
        print()
    print("--- Execution Times ---")
    print(f"CFR collection time         : {cfr_duration:.2f} sec")
    print(f"Scopus initialization       : {scopus_init_time:.2f} sec")
    print(f"Scopus verification         : {scopus_verify_time:.4f} sec")
    print(f"MJL stage time              : {mjl_duration:.2f} sec")
    print(f"SCImago stage time          : {scimago_duration:.2f} sec")
    if use_db:
        print(f"DB persistence time       : {db_duration:.2f} sec")
    print(f"TOTAL PIPELINE TIME         : {total_pipeline_time:.2f} sec ({round(total_pipeline_time / 60.0, 2)} min)")
    print("========================================\n")
    if use_db and pipeline_run_id:
        print(f"[SUCCESS] Pipeline run {pipeline_run_id} persisted to Supabase")
    print(f"[SUCCESS] Consolidated results saved to {saved_file} (legacy Excel)")


def main():
    parser = argparse.ArgumentParser(description="CFR Journal Collection, Scopus Verification & SCImago Scraper")
    parser.add_argument("--source-only", action="store_true", help="Scrape only CFR journals and export to Excel")
    parser.add_argument("--scimago-only", action="store_true", help="Run only SCImago POC on a given ISSN")
    parser.add_argument("--scopus-file", type=str, default=None, help="Path to official Scopus Source Title List Excel")
    parser.add_argument("--issn", type=str, default=None, help="Single ISSN to scrape (used with --scimago-only)")
    parser.add_argument("--input", type=str, default=None, help="Path to input Excel file with an 'ISSN' column")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent workers for SCImago scraping (default: 5)")

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
        scopus_path = args.scopus_file if args.scopus_file else os.path.join(OUTPUT_DIR, "scopus_source_title_list.xlsx")
        run_complete_pipeline(scopus_file=scopus_path, workers=args.workers)


if __name__ == "__main__":
    main()

