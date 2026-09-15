# PROJECT_WORKING.md — Complete End-to-End Documentation

> **Last updated**: 2026-09-15 | **Repository**: Publication-AID-Project  
> **Purpose**: Explain the ACTUAL working of the entire project from start to finish, based strictly on the current source code.

---

## 1. What Does This Project Do?

Publication-AID is an automated Python pipeline that:

1. **Collects** academic journal listings from the CFR Anna University portal (Chennai, India) (~12,201 journals across disciplines)
2. **Verifies** each journal's Scopus indexing status against the official Elsevier Source Title List
3. **Fetches & Calculates** Article Processing Charges (APC) and Elsevier GPOA discounts across Wiley, Elsevier, Springer Nature, SAGE, and OUP
4. **Verifies** each journal's Clarivate Master Journal List (MJL / Web of Science) indexing
5. **Scrapes** SCImago Journal Rank (SJR) scientometrics for each journal
6. **Detects changes** via SHA256 hash of 35 normalized fields (plus APC aggregates)
7. **Persists** all data incrementally to Supabase PostgreSQL, detecting new/changed/unchanged records via hash comparison

The pipeline runs daily via GitHub Actions cron at 02:00 IST.

---

## 2. Architecture Diagram

```
                          START
                            │
                            ▼
                       main.py:919
                            │
                   ┌────────┴────────┐
                   │  CLI Dispatch   │
                   └────────┬────────┘
                            │
             ┌──────────────┼──────────────┬──────────────┐
             ▼              ▼              ▼              ▼
        --source-only  --scimago-only  --input        [DEFAULT]
             │              │              │              │
             ▼              ▼              ▼              ▼
     run_source_only  run_single_issn  run_excel_batch  run_complete_pipeline
                                                    │
                               ┌─────────────────────┤
                               ▼                     │
                     Stage 1: CFR Collection         │
                     scrape_cfr_journals()           │
                     12201 journals → 12196 (dedup ISSN)  │
                               │                     │
                               ▼                     │
                     Stage 2: Scopus Verification    │
                     verify_scopus_indexing()        │
                     25MB Excel → in-memory map      │
                     11801 Active/Indexed            │
                               │                     │
                               ▼                     │
                     Stage 3: MJL Verification       │
                     verify_mjl_indexing()           │
                     Direct POST → Playwright fallback│
                     Active → Found / Not Found      │
                               │                     │
                               ▼                     │
                     Stage 4: SCImago Enrichment     │
                     process_eligible_pair()         │
                     ThreadPool + RLock              │
                     Active → SJR/Q/H/Coverage       │
                               │                     │
                               ▼                     │
                     ┌─────────────────────┐         │
                     │  PHASE 1: Bulk Read │         │
                     │  5 queries total    │         │
                     └─────────┬───────────┘         │
                               │                     │
                               ▼                     │
                     ┌──────────────────────┐        │
                     │  PHASE 2: In-Memory  │        │
                     │  Hash compare        │        │
                     │  Field diff          │        │
                     │  0 queries           │        │
                     └─────────┬────────────┘        │
                               │                     │
                               ▼                     │
                     ┌──────────────────────┐        │
                     │  PHASE 3: Bulk Write │        │
                     │  ~9 queries total    │        │
                     └─────────┬────────────┘        │
                               │                     │
                               ▼                     │
                     ┌──────────────────────┐        │
                     │  Pipeline Run Record  │        │
                     └─────────┬────────────┘        │
                               │                     │
                               ▼                     │
                              END                    │
```

---

## 3. Project Structure

```
Publication-AID-Project/
├── main.py                      # CLI entry + 4-stage orchestrator (~1200 lines)
├── models.py                    # Dataclasses: CFRJournal, ScopusVerificationResult,
│                                #   MJLVerificationResult, JournalResult, APCResult (~80 lines)
├── config/
│   ├── __init__.py              # empty
│   ├── apc_sources.py           # Publisher APC URLs & parsing rules (120 lines)
│   └── urls.py                  # Centralized URLs for all stages (26 lines)
├── database/
│   ├── __init__.py              # Re-exports get_supabase_client, CRUD functions
│   ├── connection.py            # Supabase client singleton, env validation (43 lines)
│   ├── hash.py                  # SHA256 hashing, 35-field builder, normalization (108 lines)
│   ├── repository.py            # Bulk read/write, change detection, pipeline runs (473 lines)
│   ├── schema.sql               # Base tables + indexes + triggers (198 lines)
│   └── schema_validation.sql    # DEPRECATED - Validation layer removed
├── scrapers/
│   ├── __init__.py              # Re-exports all scraper classes/functions
│   ├── cfr_data_collection.py   # CFR portal scraper (243 lines)
│   ├── scopus.py                # Local Scopus verification via Excel (294 lines)
│   ├── mjl.py                   # Hybrid MJL (Clarivate direct POST + Playwright) (577 lines)
│   ├── scimago.py               # SCImago scraper with RLock (516 lines)
│   └── apc.py                   # APC price lists + Elsevier GPOA parser (800+ lines)
├── processors/
│   ├── __init__.py              # Re-exports normalize_issn
│   └── issn.py                  # ISSN normalization (24 lines)
├── tests/                       # 19 unit & integration tests
│   ├── __init__.py              # empty
│   ├── test_hash.py             # Hash & ISSN normalization tests
│   ├── test_change_detection.py # Incremental behavior & proposal deduplication tests
│   └── test_repository_mock.py  # Repository logic tests
├── FLAWS_AND_FIXES.md           # Documented flaws, logic errors, and fixes
├── output/
│   ├── .gitkeep                 # kept in git
│   └── scopus_source_title_list.xlsx  # 25MB downloaded Scopus list (gitignored)
├── apc_cache/                   # Cached APC files (gitignored)
├── .env                         # Credentials (gitignored)
├── .env.example                 # Template
├── .gitignore                   # 46 lines
├── .github/workflows/cron.yml   # Daily 02:00 IST cron
├── requirements.txt             # Dependencies
└── README.md                    # Project overview
```

### File Responsibilities

| File | Responsibility | Called By |
|------|---------------|-----------|
| `main.py` | CLI dispatch, 4-stage orchestration, DB persistence | User / GitHub Actions |
| `models.py` | Data structures for each pipeline stage | All scrapers, main.py |
| `config/urls.py` | Single source of truth for all external URLs | All scrapers |
| `database/connection.py` | Supabase client creation, env validation | repository.py |
| `database/hash.py` | SHA256 hash computation, field normalization | main.py, tests |
| `database/repository.py` | All database operations (bulk read/write, change detection) | main.py |
| `database/schema.sql` | Table definitions (run once in Supabase) | Manual setup |
| `scrapers/cfr_data_collection.py` | Scrape CFR Anna University portal | main.py |
| `scrapers/scopus.py` | Local Scopus verification against official source list | main.py |
| `scrapers/mjl.py` | Verify MJL/WoS indexing (hybrid POST + Playwright) | main.py |
| `scrapers/scimago.py` | SCImago scientometrics scraper | main.py |
| `scrapers/apc.py` | Multi-publisher APC price lists + Elsevier GPOA parser | main.py |
| `processors/issn.py` | ISSN normalization & validation | All modules |

---

## 4. main.py — Complete Orchestration

### Entry Point

`main.py:919` `main()` parses CLI arguments and dispatches:

```
main()
  ├── --source-only        → run_source_only()          (line 192)
  ├── --scimago-only       → run_single_issn()          (line 68)
  ├── --input <file>       → run_excel_batch()          (line 85)
  ├── --issn <issn>        → run_single_issn()          (line 68)
  └── [default]            → run_complete_pipeline()    (line 206)
```

### run_complete_pipeline() — Actual Execution Sequence

```
run_complete_pipeline(scopus_file, workers)                    # line 206
│
├─ Stage 1: CFR Collection                                     # line 218
│  ├─ scrape_cfr_journals()                                    # scrapers/cfr_data_collection.py:182
│  │  Returns: (List[CFRJournal], total_pages)
│  ├─ report_duplicates(journals)                              # main.py:177 — counts dup titles/ISSNs
│  └─ CFR Dedup by ISSN                                        # main.py:228-261
│     ├─ seen_issns dict tracks normalized ISSN → title
│     ├─ If ISSN seen → skip, add to cfr_skipped_details
│     └─ 12201 → 12196 (duplicate 2572-3618 cross-print/e)
│
├─ Stage 2: Scopus Verification                                # line 264
│  ├─ from scrapers.scopus import verify_scopus_indexing
│  ├─ verify_scopus_indexing(journals, scopus_file)            # scrapers/scopus.py:262
│  │  ├─ ScopusVerifier(scopus_file, force_redownload=True)   # line 127
│  │  │  ├─ ensure_scopus_dataset() → download if needed      # line 110
│  │  │  │  ├─ Deletes old file
│  │  │  │  ├─ Fetches ELSEVIER_SCOPUS_POLICY_URL
│  │  │  │  ├─ Parses HTML for ext_list .xlsx link
│  │  │  │  └─ Downloads 25MB to output/scopus_source_title_list.xlsx
│  │  │  └─ _load_and_build_index()                           # line 155
│  │  │     ├─ pd.read_excel("Scopus Sources*")
│  │  │     ├─ Builds issn_map: Dict[normalized_issn → record]
│  │  │     └─ ~74,000 ISSN entries
│  │  └─ Loops journals → verify_journal() for each           # line 226
│  │     ├─ Tries normalized Print-ISSN → issn_map lookup
│  │     ├─ Falls back to normalized E-ISSN → issn_map lookup
│  │     └─ Returns ScopusVerificationResult
│  ├─ Filters: eligible = Active/Indexed, skipped = others
│  └─ Returns: verified_pairs, stats dict
│
├─ Stage 3: MJL Verification                                   # line 288
│  ├─ eligible_pairs = [(j,s) for j,s in verified_pairs if s.scopus_status == "Active / Indexed"]
│  ├─ from scrapers.mjl import verify_mjl_indexing
│  ├─ verify_mjl_indexing(eligible_pairs, headless, verbose, max_workers)  # scrapers/mjl.py:459
│  │  ├─ Phase 1: Direct POST via ThreadPoolExecutor          # line 475
│  │  │  ├─ _direct_verify_single(journal) per journal        # line 423
│  │  │  │  ├─ _direct_post_mjl(formatted_issn)               # line 191
│  │  │  │  │  ├─ urllib.request.Request POST to MJL_API_URL
│  │  │  │  │  ├─ JSON payload with searchValue, filters, uuid4
│  │  │  │  │  └─ Returns raw JSON string or None
│  │  │  │  ├─ _parse_mjl_response(raw, norm)                 # line 114
│  │  │  │  │  ├─ Parses journalProfiles, totalRecords
│  │  │  │  │  ├─ Exact ISSN match → "Found" + _extract_wos_indexes
│  │  │  │  │  ├─ Single result → "Found" + "Single Result"
│  │  │  │  │  └─ Otherwise → "Not Found"
│  │  │  │  └─ Tries Print-ISSN first, falls back to E-ISSN
│  │  │  └─ Collects results + needs_fallback list
│  │  └─ Phase 2: Playwright fallback for failures            # line 497
│  │     └─ MJLVerifier.verify_journal() for each failure
│  ├─ Returns: List[(CFRJournal, ScopusResult, MJLResult)]
│  └─ mjl_lookup dict: sl_no → MJLVerificationResult
│
├─ Stage 4: SCImago Enrichment                                 # line 313
│  ├─ process_eligible_pair(idx_pair, scraper) per eligible   # line 324
│  │  ├─ Tries Print-ISSN → scraper.scrape_journal()
│  │  ├─ Falls back to E-ISSN if Print failed
│  │  ├─ Combines CFR + Scopus + MJL + SCImago into record dict
│  │  └─ Returns (idx, record, is_success, timing, ...)
│  ├─ ThreadPoolExecutor(max_workers=workers)                  # line 420
│  ├─ Shared ScimagoScraper instance with RLock
│  ├─ Re-orders results by original CFR Sl.No
│  └─ Appends skipped (non-Active) journals with "skipped" values
│
├─ APC Verification (Stage 2b)                                 # line 300
│  ├─ from scrapers.apc import verify_apc_indexing
│  ├─ verify_apc_indexing(eligible_pairs, headless, verbose, max_workers)
│  │  ├─ APCVerifier.load_all() → downloads + parses all sources
│  │  │  ├─ Wiley OA / Hybrid
│  │  │  ├─ Elsevier APC + GPOA (20% of list price = 80% discount)
│  │  │  ├─ SAGE Hybrid / Gold OA
│  │  │  ├─ Springer Nature Hybrid / Fully OA (coordinate-based PDF parsing)
│  │  │  └─ OUP (currently failing - 0 journals)
│  │  └─ Returns apc_lookup dict: sl_no → APC entry
│  └─ apc_lookup dict used in record dict for DB write
│
├─ DB Persistence (Supabase)                                   # line 476
│  ├─ use_db = DB_AVAILABLE and is_supabase_configured()       # line 479
│  ├─ create_pipeline_run(total_cfr)                           # line 486
│  ├─ Persist cfr_skipped_details to skipped_records           # line 492
│  ├─ PHASE 1: Bulk READ (5 queries)                          # line 514
│  │  ├─ get_all_journals_map()                                # repository.py:66
│  │  ├─ bulk_get_child_map("cfr_results", ids)               # repository.py:323
│  │  ├─ bulk_get_child_map("scopus_results", ids)
│  │  ├─ bulk_get_child_map("mjl_results", ids)
│  │  ├─ bulk_get_child_map("scimago_results", ids)
│  │  ├─ bulk_get_apc_map(ids)                                 # NEW: APC 1:many
│  ├─ PHASE 2: In-memory classify (0 queries)                 # line 547
│  │  ├─ For each result:
│  │  │  ├─ Compute new_hash via build_hash_input + compute_data_hash
│  │  │  ├─ _lookup_existing(print, e) → in journals_map
│  │  │  ├─ Case A (new): collect for bulk insert
│  │  │  ├─ Case B (unchanged): add to to_touch_ids
│  │  │  └─ Case C (changed): field-level diff → collect for bulk update
│  │  └─ Collects all_changes for journal_changes table
│  ├─ PHASE 3: Bulk WRITE (~9 queries)                        # line 795
│  │  ├─ bulk_insert_journals(to_insert_journals)             # repository.py:377
│  │  ├─ bulk_upsert_child (4 tables for new journals)        # repository.py:393
│  │  ├─ bulk_upsert_apc(to_upsert_apc)                       # NEW: APC 1:many
│  │  ├─ bulk_update_journals(to_update_journals)             # repository.py:364
│  │  ├─ bulk_upsert_child (4 tables for changed journals)
│  │  ├─ bulk_upsert_apc(to_upsert_apc)                       # NEW: APC 1:many
│  │  ├─ bulk_touch_journals(to_touch_ids, pipeline_run_id)   # repository.py:350
│  │  └─ bulk_insert_changes(all_changes)                     # repository.py:407
│  └─ finish_pipeline_run(pipeline_run_id, "success", ...)     # line 861
│
└─ Print summary with timing for each stage                   # line 878
```

---

## 5. Key Fixes Applied (2026-09-15)

See `FLAWS_AND_FIXES.md` for complete documentation.

| Issue | Fix | Files |
|-------|-----|-------|
| **GPOA Discount Direction** | Changed from "20% off" (80% of list) to "20% of list price" (80% discount) | `scrapers/apc.py`: `_calc_gpoa_discount()`, `_apply_gpoa_discount()` |
| **Springer PDF Parsing** | Coordinate-based character extraction with digit reconstruction for garbled wrapped Imprint column | `scrapers/apc.py`: `_parse_springer_pdf()` |
| **Live-Only Fetching** | Removed cache fallback; download failures raise `RuntimeError` | `scrapers/apc.py`: `_load_excel_direct()`, `_load_springer()`, `_fetch_elsevier_gpoa_issns()` |
| **Database Cleanup** | Fixed 84 Elsevier GPOA records (80% discount) + 34 Springer records (comma removal) | Manual fix scripts |
| **MJL Product Code C→AHCI** | Removed `C` from AHCI mapping; only `H` maps to AHCI; added `jcrCategories[].jcrEdition` as authoritative | `scrapers/mjl.py`: `_extract_wos_indexes()` |
| **Removed Validation Layer** | Removed `change_proposals` table, `--validate`/`--direct` flags, Excel artifact export | `main.py`, `database/repository.py`, `.github/workflows/cron.yml` |

---

## 6. Current Status

| Metric | Value |
|--------|-------|
| CFR Journals | 12,196 (after dedup) |
| Scopus Active/Indexed | 11,801 |
| MJL Found | ~8,000 |
| SCImago SUCCESS | ~9,500 |
| APC Coverage | 3,923 journals |
| Elsevier GPOA | 84 journals (20% of list = 80% discount) |
| Springer Hybrid | ~25 journals (coordinate-based parsing) |
| Springer Fully OA | 5 journals (manual fallback) |
| Tests | 19/19 passing |
| Pipeline Stability | Stable: 0 new / 0 updated / 12196 unchanged on consecutive runs |

---

## 7. Remaining Technical Debt

| Priority | Issue | Effort |
|----------|-------|--------|
| High | Springer Fully OA PDF parser (different layout) | Medium |
| High | OUP APC source (dead URL/format issue) | Low |
| Medium | Springer Hybrid parser over-extracts (2029 rows vs ~25 journals) | Medium |
| Medium | No retry logic for transient network failures | Low |
| Low | Add structured logging (JSON) | Low |
| Low | Add metrics/monitoring endpoints | Low |

---

## 7. Verification Checklist

- [x] All 19 unit tests pass
- [x] GPOA discount: 5030 → 1006 (20% of list price)
- [x] Springer Acta Mechanica Sinica: 1614-3116 → 4390 USD
- [x] Springer Fully OA: 5 manual fallback entries loaded
- [x] 84 Elsevier GPOA records corrected in DB
- [x] 34 Springer Nature records corrected in DB (commas removed)
- [x] Pipeline runs without cache fallback (live-only)
- [x] All 19 tests pass
- [x] Pipeline stable: `0 new | 0 updated | 12196 unchanged` on consecutive runs