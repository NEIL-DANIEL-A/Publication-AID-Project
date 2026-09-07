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
        bulk_get_child_map,
        bulk_get_apc_map,
        bulk_touch_journals,
        bulk_update_journals,
        bulk_insert_journals,
        bulk_upsert_child,
        bulk_insert_changes,
        bulk_upsert_apc,
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
    print(f"[SUCCESS] Batch complete ({total_count} ISSNs, {total_batch_time:.2f}s)")


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
    """Scrape CFR website and print CFR records."""
    print("[INFO] Starting CFR Data Collection (Source-Only Mode)...")

    cfr_start = time.perf_counter()
    journals, total_pages = scrape_cfr_journals()
    cfr_duration = time.perf_counter() - cfr_start

    print(f"[TIME] CFR collection duration: {cfr_duration:.2f} seconds")
    report_duplicates(journals)
    print(f"[SUCCESS] CFR journals collected ({len(journals)} records)")
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

    # Stage 2b: APC Verification (only for Active/Indexed journals)
    eligible_pairs = [(j, s) for j, s in verified_pairs if s.scopus_status == "Active / Indexed"]
    skipped_pairs  = [(j, s) for j, s in verified_pairs if s.scopus_status != "Active / Indexed"]

    print(f"[INFO] Stage 2b: APC Verification (Active/Indexed: {len(eligible_pairs)} journals)...")
    apc_start_time = time.perf_counter()

    from scrapers.apc import APCVerifier
    apc_verifier = APCVerifier()
    apc_verifier.load_all()

    # Build sl_no -> APC lookup for eligible journals
    apc_lookup = {}
    for j, _ in eligible_pairs:
        # First try ISSN-based lookup
        for issn in (j.print_issn, j.e_issn):
            entry = apc_verifier.lookup(issn)
            if entry:
                apc_lookup[j.sl_no] = entry
                break
        # If no ISSN match, try title-based lookup (for SAGE Gold OA)
        if j.sl_no not in apc_lookup:
            entry = apc_verifier.lookup_by_title(j.journal_title)
            if entry:
                apc_lookup[j.sl_no] = entry

    apc_duration = round(time.perf_counter() - apc_start_time, 2)
    apc_found_count = len(apc_lookup)
    apc_not_found = len(eligible_pairs) - apc_found_count

    print(f"\n--- APC Verification Summary ---")
    print(f"  APC Found           : {apc_found_count}")
    print(f"  APC Not Found       : {apc_not_found}")
    print(f"  Wiley OA            : {apc_verifier.stats.get('wiley_oa_count', 0)}")
    print(f"  Wiley Hybrid        : {apc_verifier.stats.get('wiley_hybrid_count', 0)}")
    print(f"  Elsevier            : {apc_verifier.stats.get('elsevier_count', 0)}")
    print(f"  Springer Nature     : {apc_verifier.stats.get('springer_count', 0)}")
    print(f"  Oxford Univ Press   : {apc_verifier.stats.get('oup_count', 0)}")
    print(f"  SAGE                : {apc_verifier.stats.get('sage_count', 0)}")
    print(f"  APC Stage Time      : {apc_duration:.2f} sec")
    print(f"--------------------------------\n")

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

        # APC data (from Stage 2b, only for Active/Indexed)
        apc_res = apc_lookup.get(j.sl_no)
        apc_value_val = apc_res.get("apc_value", "no data") if apc_res else "no data"
        apc_currency_val = apc_res.get("apc_currency", "no data") if apc_res else "no data"
        apc_mode_val = apc_res.get("mode_raw", "no data") if apc_res else "no data"

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
            "APC Value": apc_value_val,
            "APC Currency": apc_currency_val,
            "APC Mode": apc_mode_val,
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
            "APC Value": "no data",
            "APC Currency": "no data",
            "APC Mode": "no data",
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

        # ----------------------------------------------------------------
        # PHASE 1: Bulk READ (6 queries total, not 500+)
        # ----------------------------------------------------------------
        print(f"[INFO] DB PHASE 1: Bulk fetching existing data (6 queries)...", flush=True)
        phase1_start = time.perf_counter()
        try:
            from processors.issn import normalize_issn as _norm
            journals_map = get_all_journals_map()
            unique_journals = len(set(v["id"] for v in journals_map.values())) if journals_map else 0
            journal_ids = list(set(v["id"] for v in journals_map.values())) if journals_map else []
            # Bulk fetch all 5 child tables (1 query each)
            cfr_map = bulk_get_child_map("cfr_results", journal_ids)
            scopus_map = bulk_get_child_map("scopus_results", journal_ids)
            mjl_map = bulk_get_child_map("mjl_results", journal_ids)
            scimago_map = bulk_get_child_map("scimago_results", journal_ids)
            apc_map = bulk_get_apc_map(journal_ids)
            phase1_time = time.perf_counter() - phase1_start
            print(f"[INFO] DB PHASE 1: Loaded {unique_journals} journals + {len(cfr_map)} cfr + {len(scopus_map)} scopus + {len(mjl_map)} mjl + {len(scimago_map)} scimago + {len(apc_map)} apc in {phase1_time:.2f}s (6 queries)", flush=True)
        except Exception as e:
            print(f"[WARNING] Bulk fetch failed, falling back to per-journal lookup: {e}")
            journals_map = {}
            cfr_map = {}
            scopus_map = {}
            mjl_map = {}
            scimago_map = {}
            apc_map = {}

        def _lookup_existing(print_raw, e_raw):
            for norm in (_norm(print_raw), _norm(e_raw)):
                if norm == "no data" or not norm:
                    continue
                if norm in journals_map:
                    return journals_map[norm]
            return None

        def _compute_apc_aggregate(apc_entries: List[dict]) -> str:
            """Compute deterministic aggregate string from APC records for hashing."""
            if not apc_entries:
                return ""
            # Sort by publisher+currency+value for deterministic order
            sorted_entries = sorted(apc_entries, key=lambda e: (
                _normalize_value(e.get("publisher", "")),
                _normalize_value(e.get("apc_currency", "")),
                _normalize_value(e.get("apc_value", "")),
            ))
            parts = []
            for e in sorted_entries:
                pub = _normalize_value(e.get("publisher", ""))
                cur = _normalize_value(e.get("apc_currency", ""))
                val = _normalize_value(e.get("apc_value", ""))
                parts.append(f"{pub}:{cur}:{val}")
            return "|".join(parts)

        def _compute_apc_mode_aggregate(apc_entries: List[dict]) -> str:
            """Compute deterministic aggregate string of APC modes for hashing."""
            if not apc_entries:
                return ""
            modes = sorted(set(
                _normalize_value(e.get("apc_mode_normalized", e.get("mode_raw", "")))
                for e in apc_entries
                if _normalize_value(e.get("apc_mode_normalized", e.get("mode_raw", "")))
            ))
            return "|".join(modes)

        # ----------------------------------------------------------------
        # PHASE 2: In-memory classify + hash compare + field diff (0 queries)
        # ----------------------------------------------------------------
        print(f"[INFO] DB PHASE 2: In-memory hash compare + field diff...", flush=True)
        phase2_start = time.perf_counter()
        from processors.issn import normalize_issn as _n2

        to_insert_journals = []   # new journal rows
        to_insert_cfr = []        # cfr rows for new journals
        to_insert_scopus = []     # etc.
        to_insert_mjl = []
        to_insert_scimago = []
        to_upsert_apc = []        # apc rows to upsert (new + updated journals)
        to_update_journals = []   # updated journal rows (with id)
        to_update_cfr = []
        to_update_scopus = []
        to_update_mjl = []
        to_update_scimago = []
        to_touch_ids = []         # unchanged journal ids
        all_changes = []          # journal_changes rows
        new_issn_map = {}         # norm -> id for new journals in this run
        total = len(results)

        for idx, rec in enumerate(results, 1):
            if idx == 1 or idx % 50 == 0 or idx == total:
                print(f"[PHASE2 {idx}/{total}] {rec.get('Full Journal Title','?')[:35]:35} ...", flush=True)

            # Compute new hash
            _mjl_match_for_hash = "No Match" if rec["MJL Status"] in ("Not Found", "Unable to Verify", "skipped", "no data") else "Print ISSN" if rec["MJL Matched ISSN"] not in ("no data", "skipped", "") else "No Match"

            # Compute APC aggregates for hash
            _apc_val = rec.get("APC Value", "no data")
            _apc_cur = rec.get("APC Currency", "no data")
            _apc_mode = rec.get("APC Mode", "no data")
            _apc_for_hash = ""
            _apc_mode_for_hash = ""
            if _apc_val not in ("no data", "", "N/A"):
                # Use APC lookup's publisher (not CFR publisher) to match _compute_apc_aggregate
                _apc_entry = apc_lookup.get(rec["Sl.No"])
                _apc_pub = _apc_entry.get("publisher", "") if _apc_entry else ""
                _apc_for_hash = f"{_normalize_value(_apc_pub)}:{_normalize_value(_apc_cur)}:{_normalize_value(_apc_val)}"
                _apc_mode_for_hash = _normalize_value(_apc_mode) if _apc_mode not in ("no data", "", "N/A") else ""

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
                scopus_issn="",
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
                apc_aggregate=_apc_for_hash,
                apc_mode_aggregate=_apc_mode_for_hash,
            )
            new_hash = compute_data_hash(hash_input)

            # Prepare payloads
            norm_p = _n2(rec["Print-ISSN"])
            norm_e = _n2(rec["E-ISSN"])
            journal_row = {
                "title": rec["Full Journal Title"],
                "print_issn": rec["Print-ISSN"],
                "e_issn": rec["E-ISSN"],
                "normalized_print": norm_p,
                "normalized_e": norm_e,
                "publisher": rec["Publisher"],
                "country": rec["Country"],
                "data_hash": new_hash,
            }
            cfr_row = {
                "sl_no": rec["Sl.No"],
                "journal_title": rec["Full Journal Title"],
                "print_issn": rec["Print-ISSN"],
                "e_issn": rec["E-ISSN"],
                "publisher": rec["Publisher"],
                "country": rec["Country"],
            }
            scopus_row = {
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
            mjl_exec = rec.get("MJL Execution Time (sec)", "no data")
            try:
                mjl_exec_val = float(mjl_exec) if str(mjl_exec).replace(".", "", 1).isdigit() else None
            except:
                mjl_exec_val = None
            mjl_row = {
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
            scimago_row = {
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
                # Case A: New - collect for bulk insert
                to_insert_journals.append(journal_row)
                to_insert_cfr.append(cfr_row)
                to_insert_scopus.append(scopus_row)
                to_insert_mjl.append(mjl_row)
                to_insert_scimago.append(scimago_row)
                # Collect APC rows (1:many - could be multiple publishers)
                _apc_entries = apc_lookup.get(rec["Sl.No"], [])
                if _apc_entries:
                    _apc_list = [_apc_entries] if isinstance(_apc_entries, dict) else _apc_entries
                    for _apc_e in _apc_list:
                        to_upsert_apc.append({
                            "journal_id": "",  # filled after bulk insert
                            "publisher": _apc_e.get("publisher", ""),
                            "apc_value": _apc_e.get("apc_value", ""),
                            "apc_currency": _apc_e.get("apc_currency", ""),
                            "apc_mode_raw": _apc_e.get("mode_raw", ""),
                            "apc_mode_normalized": _apc_e.get("mode_normalized", ""),
                            "source_file": "bulk",
                        })
                # Track for duplicate ISSN within same run
                for norm in (norm_p, norm_e):
                    if norm and norm != "no data":
                        new_issn_map[norm] = len(to_insert_journals) - 1  # index into list
                db_stats["new_records"] += 1
            else:
                jid = existing["id"]
                # Recompute old hash from bulk-fetched child data (catches manual DB edits)
                old_cfr = cfr_map.get(jid, {})
                old_scopus = scopus_map.get(jid, {})
                old_mjl = mjl_map.get(jid, {})
                old_scimago = scimago_map.get(jid, {})
                old_apc = apc_map.get(jid, [])
                old_apc_aggregate = _compute_apc_aggregate(old_apc)
                old_apc_mode_aggregate = _compute_apc_mode_aggregate(old_apc)
                old_hash_input = build_hash_input(
                    journal_title=existing.get("title", ""),
                    print_issn=existing.get("print_issn", ""),
                    e_issn=existing.get("e_issn", ""),
                    publisher=existing.get("publisher", ""),
                    country=existing.get("country", ""),
                    cfr_sl_no=old_cfr.get("sl_no", ""),
                    scopus_status=old_scopus.get("scopus_status", ""),
                    scopus_match_type=old_scopus.get("match_type", ""),
                    scopus_source_title=old_scopus.get("source_title", ""),
                    scopus_sourcerecord_id=old_scopus.get("sourcerecord_id", ""),
                    scopus_publisher=old_scopus.get("scopus_publisher", ""),
                    scopus_coverage=old_scopus.get("scopus_coverage", ""),
                    scopus_issn=old_scopus.get("scopus_issn", ""),
                    scopus_eissn=old_scopus.get("scopus_eissn", ""),
                    scopus_raw_active=old_scopus.get("raw_active_status", ""),
                    scopus_raw_discontinued=old_scopus.get("raw_discontinued_flag", ""),
                    mjl_status=old_mjl.get("mjl_status", ""),
                    mjl_index=old_mjl.get("mjl_index", ""),
                    mjl_issn_used=old_mjl.get("mjl_issn_used", ""),
                    mjl_match_type=old_mjl.get("mjl_match_type", ""),
                    mjl_source_title=old_mjl.get("mjl_source_title", ""),
                    scimago_status=old_scimago.get("scimago_status", ""),
                    scimago_journal_id=old_scimago.get("journal_id_external", ""),
                    scimago_matched_issn=old_scimago.get("matched_issn", ""),
                    sjr=old_scimago.get("sjr", ""),
                    quartile=old_scimago.get("quartile", ""),
                    h_index=old_scimago.get("h_index", ""),
                    scimago_coverage=old_scimago.get("coverage", ""),
                    scimago_url=old_scimago.get("url", ""),
                    apc_aggregate=old_apc_aggregate,
                    apc_mode_aggregate=old_apc_mode_aggregate,
                )
                old_hash_computed = compute_data_hash(old_hash_input)

                if old_hash_computed == new_hash:
                    # Case B: Unchanged
                    to_touch_ids.append(jid)
                    db_stats["unchanged_records"] += 1
                else:
                    # Case C: Changed - field-level diff
                    changes = []
                    for field, new_v in [("title", rec["Full Journal Title"]), ("publisher", rec["Publisher"]), ("country", rec["Country"])]:
                        old_v = existing.get(field, "")
                        if _normalize_value(old_v) != _normalize_value(new_v):
                            changes.append(("journal", field, old_v, new_v))
                    cfr_old_sl = old_cfr.get("sl_no", "")
                    if _normalize_value(cfr_old_sl) != _normalize_value(rec["Sl.No"]):
                        changes.append(("cfr", "sl_no", cfr_old_sl, rec["Sl.No"]))
                    for f, new_v in [
                        ("scopus_status", rec["Scopus Indexing Status"]),
                        ("match_type", rec["Scopus Match Type"]),
                        ("source_title", rec["Scopus Source Title"]),
                        ("sourcerecord_id", rec["Scopus Source Record ID"]),
                        ("scopus_publisher", rec["Scopus Publisher"]),
                        ("scopus_coverage", rec["Scopus Coverage"]),
                    ]:
                        old_v = old_scopus.get(f, "")
                        if _normalize_value(old_v) != _normalize_value(new_v):
                            changes.append(("scopus", f, old_v, new_v))
                    _new_mjl_match = "No Match" if rec["MJL Status"] in ("Not Found", "Unable to Verify", "skipped", "no data") else "Print ISSN" if rec["MJL Matched ISSN"] not in ("no data", "skipped", "") else "No Match"
                    for f, new_v in [("mjl_status", rec["MJL Status"]), ("mjl_index", rec["MJL Index"]), ("mjl_issn_used", rec["MJL Matched ISSN"]), ("mjl_match_type", _new_mjl_match), ("mjl_source_title", rec["MJL Source Title"])]:
                        old_v = old_mjl.get(f, "")
                        if _normalize_value(old_v) != _normalize_value(new_v):
                            changes.append(("mjl", f, old_v, new_v))
                    for f, new_v in [
                        ("sjr", rec["SJR"]), ("quartile", rec["Quartile"]), ("h_index", rec["H-Index"]),
                        ("coverage", rec["SCImago Coverage"]), ("scimago_status", rec["SCImago Status"]),
                        ("journal_id_external", rec["SCImago Journal ID"]), ("matched_issn", rec["SCImago Matched ISSN"]),
                        ("url", rec["SCImago URL"]),
                    ]:
                        old_v = old_scimago.get(f, "")
                        if _normalize_value(old_v) != _normalize_value(new_v):
                            changes.append(("scimago", f, old_v, new_v))
                    if not changes:
                        changes.append(("journal", "data_hash", old_hash_computed, new_hash))

                    # Collect for bulk update
                    journal_row["id"] = jid
                    journal_row["last_changed_at"] = "now()"
                    to_update_journals.append(journal_row)
                    cfr_row["journal_id"] = jid
                    to_update_cfr.append(cfr_row)
                    scopus_row["journal_id"] = jid
                    to_update_scopus.append(scopus_row)
                    mjl_row["journal_id"] = jid
                    to_update_mjl.append(mjl_row)
                    scimago_row["journal_id"] = jid
                    to_update_scimago.append(scimago_row)
                    # Collect APC for upsert (1:many)
                    _apc_entries = apc_lookup.get(rec["Sl.No"], [])
                    if _apc_entries:
                        _apc_list = [_apc_entries] if isinstance(_apc_entries, dict) else _apc_entries
                        for _apc_e in _apc_list:
                            to_upsert_apc.append({
                                "journal_id": jid,
                                "publisher": _apc_e.get("publisher", ""),
                                "apc_value": _apc_e.get("apc_value", ""),
                                "apc_currency": _apc_e.get("apc_currency", ""),
                                "apc_mode_raw": _apc_e.get("mode_raw", ""),
                                "apc_mode_normalized": _apc_e.get("mode_normalized", ""),
                                "source_file": "bulk",
                            })
                    for src, fld, old_v, new_v in changes:
                        all_changes.append({
                            "journal_id": jid,
                            "pipeline_run_id": pipeline_run_id or "",
                            "source": src,
                            "field_name": fld,
                            "old_value": str(old_v) if old_v is not None else None,
                            "new_value": str(new_v) if new_v is not None else None,
                        })
                    db_stats["updated_records"] += 1

        phase2_time = time.perf_counter() - phase2_start
        print(f"[INFO] DB PHASE 2: Classified {db_stats['new_records']} new | {db_stats['updated_records']} updated | {db_stats['unchanged_records']} unchanged in {phase2_time:.3f}s (0 queries)", flush=True)

        # ----------------------------------------------------------------
        # PHASE 3: Bulk WRITE (queries total, not 500+)
        # ----------------------------------------------------------------
        print(f"[INFO] DB PHASE 3: Bulk writing to Supabase...", flush=True)
        phase3_start = time.perf_counter()

        # 1. Bulk insert NEW journals (get IDs back for child tables)
        new_ids = []
        if to_insert_journals:
            # Deduplicate by normalized_print ISSN to avoid constraint violations
            seen_print = set()
            dedup_journals = []
            dedup_cfr = []
            dedup_scopus = []
            dedup_mjl = []
            dedup_scimago = []
            for i, j in enumerate(to_insert_journals):
                np = j.get("normalized_print", "")
                if np and np != "no data" and np in seen_print:
                    continue
                if np and np != "no data":
                    seen_print.add(np)
                dedup_journals.append(j)
                dedup_cfr.append(to_insert_cfr[i])
                dedup_scopus.append(to_insert_scopus[i])
                dedup_mjl.append(to_insert_mjl[i])
                dedup_scimago.append(to_insert_scimago[i])
            if len(dedup_journals) < len(to_insert_journals):
                print(f"  [DEDUP] Removed {len(to_insert_journals) - len(dedup_journals)} duplicate ISSN journals", flush=True)
            to_insert_journals = dedup_journals
            to_insert_cfr = dedup_cfr
            to_insert_scopus = dedup_scopus
            to_insert_mjl = dedup_mjl
            to_insert_scimago = dedup_scimago

            print(f"  [WRITE] Inserting {len(to_insert_journals)} new journals...", flush=True)
            inserted = bulk_insert_journals(to_insert_journals)
            new_ids = [r["id"] for r in inserted]
            # Assign journal_id to child rows
            for i, jid in enumerate(new_ids):
                to_insert_cfr[i]["journal_id"] = jid
                to_insert_scopus[i]["journal_id"] = jid
                to_insert_mjl[i]["journal_id"] = jid
                to_insert_scimago[i]["journal_id"] = jid
            # Update new_issn_map with real IDs
            for i, jid in enumerate(new_ids):
                norm_p_i = to_insert_journals[i].get("normalized_print", "")
                norm_e_i = to_insert_journals[i].get("normalized_e", "")
                if norm_p_i and norm_p_i != "no data":
                    new_issn_map[norm_p_i] = jid
                if norm_e_i and norm_e_i != "no data":
                    new_issn_map[norm_e_i] = jid

        # 2-5. Bulk upsert child tables for NEW journals
        bulk_upsert_child("cfr_results", to_insert_cfr)
        bulk_upsert_child("scopus_results", to_insert_scopus)
        bulk_upsert_child("mjl_results", to_insert_mjl)
        bulk_upsert_child("scimago_results", to_insert_scimago)

        # 6. Bulk upsert APC rows for NEW journals (assign journal_id from new_ids)
        if to_upsert_apc:
            apc_idx = 0
            for i, jid in enumerate(new_ids):
                _sl_no = to_insert_cfr[i].get("sl_no", "")
                _has_apc = _sl_no in apc_lookup
                if _has_apc and apc_idx < len(to_upsert_apc):
                    to_upsert_apc[apc_idx]["journal_id"] = jid
                    apc_idx += 1
            bulk_upsert_apc(to_upsert_apc)

        # 7. Bulk update CHANGED journals
        if to_update_journals:
            print(f"  [WRITE] Updating {len(to_update_journals)} changed journals...", flush=True)
            bulk_update_journals(to_update_journals)

        # 8-11. Bulk upsert child tables for CHANGED journals
        bulk_upsert_child("cfr_results", to_update_cfr)
        bulk_upsert_child("scopus_results", to_update_scopus)
        bulk_upsert_child("mjl_results", to_update_mjl)
        bulk_upsert_child("scimago_results", to_update_scimago)

        # 13. Bulk touch UNCHANGED journals (1 query)
        if to_touch_ids:
            print(f"  [WRITE] Touching {len(to_touch_ids)} unchanged journals...", flush=True)
            bulk_touch_journals(to_touch_ids, pipeline_run_id or "")

        # 14. Bulk insert CHANGES
        if all_changes:
            print(f"  [WRITE] Inserting {len(all_changes)} change records...", flush=True)
            bulk_insert_changes(all_changes)

        # Log updated field summaries
        if db_stats["updated_records"] > 0:
            field_counts = collections.Counter(c["source"] for c in all_changes)
            print(f"  [UPDATED] Field changes: {dict(field_counts)}", flush=True)

        phase3_time = time.perf_counter() - phase3_start
        db_duration = round(phase1_time + phase2_time + phase3_time, 2)
        print(f"[INFO] DB PHASE 3: Bulk write complete in {phase3_time:.2f}s", flush=True)
        print(f"[INFO] DB persistence complete: {db_stats['new_records']} new | {db_stats['updated_records']} updated | {db_stats['unchanged_records']} unchanged | {db_stats['failed_records']} failed in {db_duration:.2f}s (was ~62s)", flush=True)
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
    print(f"APC Verification (Active)   : {len(eligible_pairs)}")
    print(f"  APC Found                 : {apc_found_count}")
    print(f"  APC Not Found             : {apc_not_found}")
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
    print(f"APC stage time              : {apc_duration:.2f} sec")
    print(f"MJL stage time              : {mjl_duration:.2f} sec")
    print(f"SCImago stage time          : {scimago_duration:.2f} sec")
    if use_db:
        print(f"DB persistence time       : {db_duration:.2f} sec")
    print(f"TOTAL PIPELINE TIME         : {total_pipeline_time:.2f} sec ({round(total_pipeline_time / 60.0, 2)} min)")
    print("========================================\n")
    if use_db and pipeline_run_id:
        print(f"[SUCCESS] Pipeline run {pipeline_run_id} persisted to Supabase")


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

