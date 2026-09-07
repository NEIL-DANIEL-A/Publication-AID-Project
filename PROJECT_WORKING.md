# PROJECT_WORKING.md — Complete End-to-End Documentation

> **Last updated**: 2026-09-07 | **Repository**: Publication-AID-Project  
> **Purpose**: Explain the ACTUAL working of the entire project from start to finish, based strictly on the current source code.

---

## 1. What Does This Project Do?

Publication-AID is an automated Python pipeline that:

1. **Collects** academic journal listings from the CFR Anna University portal (Chennai, India)
2. **Verifies** each journal's Scopus indexing status against the official Elsevier Source Title List
3. **Verifies** each journal's Clarivate Master Journal List (MJL / Web of Science) indexing
4. **Scrapes** SCImago Journal Rank (SJR) scientometrics for each journal
5. **Persists** all data incrementally to Supabase PostgreSQL, detecting new/changed/unchanged records via SHA256 hash of 29 fields

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
                    257 rows → 256 (dedup ISSN)     │
                              │                     │
                              ▼                     │
                    Stage 2: Scopus Verification    │
                    verify_scopus_indexing()        │
                    19MB Excel → in-memory map      │
                    256 → ~224 Active/Indexed        │
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
├── main.py                      # CLI entry + 4-stage orchestrator (946 lines)
├── models.py                    # 4 dataclasses: CFRJournal, ScopusVerificationResult,
│                                #   MJLVerificationResult, JournalResult (63 lines)
├── config/
│   ├── __init__.py              # empty
│   └── urls.py                  # Centralized URLs for all 4 stages (26 lines)
├── database/
│   ├── __init__.py              # Re-exports get_supabase_client, CRUD functions
│   ├── connection.py            # Supabase client singleton, env validation (43 lines)
│   ├── hash.py                  # SHA256 hashing, 29-field builder, normalization (108 lines)
│   ├── repository.py            # Bulk read/write, per-journal CRUD, pipeline runs (414 lines)
│   └── schema.sql               # 7 tables + indexes + triggers (198 lines)
├── scrapers/
│   ├── __init__.py              # Re-exports all scraper classes/functions
│   ├── cfr_data_collection.py   # CFR portal scraper (243 lines)
│   ├── scopus.py                # Local Scopus verification via Excel (294 lines)
│   ├── mjl.py                   # Hybrid MJL: POST + Playwright (577 lines)
│   └── scimago.py               # SCImago scraper with RLock (516 lines)
├── processors/
│   ├── __init__.py              # Re-exports normalize_issn
│   └── issn.py                  # ISSN normalization (24 lines)
├── tests/
│   ├── __init__.py              # empty
│   ├── test_hash.py             # 5 hash tests
│   ├── test_change_detection.py # 5 incremental behavior tests
│   └── test_repository_mock.py  # 3 repository logic tests
├── output/
│   ├── .gitkeep                 # kept in git
│   ├── scopus_source_title_list.xlsx  # 19MB downloaded Scopus list (gitignored)
│   └── debug/
│       └── .gitkeep
├── .env                         # Credentials (gitignored)
├── .env.example                 # Template
├── .gitignore                   # 46 lines
├── .github/workflows/cron.yml   # Daily 02:00 IST cron
├── requirements.txt             # 5 dependencies
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
| `database/repository.py` | All database operations (bulk + per-journal) | main.py |
| `database/schema.sql` | Table definitions (run once in Supabase) | Manual setup |
| `scrapers/cfr_data_collection.py` | Scrape CFR Anna University portal | main.py |
| `scrapers/scopus.py` | Verify Scopus indexing via local Excel | main.py |
| `scrapers/mjl.py` | Verify MJL/WoS indexing (hybrid) | main.py |
| `scrapers/scimago.py` | Scrape SCImago scientometrics | main.py |
| `processors/issn.py` | Normalize ISSN strings | All modules |

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
│     └─ 257 → 256 (duplicate 2572-3618 cross-print/e)
│
├─ Stage 2: Scopus Verification                                # line 264
│  ├─ from scrapers.scopus import verify_scopus_indexing
│  ├─ verify_scopus_indexing(journals, scopus_file)            # scrapers/scopus.py:262
│  │  ├─ ScopusVerifier(scopus_file, force_redownload=True)   # line 127
│  │  │  ├─ ensure_scopus_dataset() → download if needed      # line 110
│  │  │  │  ├─ Deletes old file
│  │  │  │  ├─ Fetches ELSEVIER_SCOPUS_POLICY_URL
│  │  │  │  ├─ Parses HTML for ext_list .xlsx link
│  │  │  │  └─ Downloads 19MB to output/scopus_source_title_list.xlsx
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
├─ DB Persistence (Supabase)                                   # line 476
│  ├─ use_db = DB_AVAILABLE and is_supabase_configured()       # line 479
│  ├─ create_pipeline_run(total_cfr)                           # line 486
│  ├─ Persist cfr_skipped_details to skipped_records           # line 492
│  ├─ PHASE 1: Bulk READ (5 queries)                          # line 514
│  │  ├─ get_all_journals_map()                                # repository.py:66
│  │  ├─ bulk_get_child_map("cfr_results", ids)               # repository.py:323
│  │  ├─ bulk_get_child_map("scopus_results", ids)
│  │  ├─ bulk_get_child_map("mjl_results", ids)
│  │  └─ bulk_get_child_map("scimago_results", ids)
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
│  │  ├─ bulk_update_journals(to_update_journals)             # repository.py:364
│  │  ├─ bulk_upsert_child (4 tables for changed journals)
│  │  ├─ bulk_touch_journals(to_touch_ids, pipeline_run_id)   # repository.py:350
│  │  └─ bulk_insert_changes(all_changes)                     # repository.py:407
│  └─ finish_pipeline_run(pipeline_run_id, "success", ...)     # line 861
│
└─ Print summary with timing for each stage                   # line 878
```

---

## 5. CFR Scraper — Complete Working

**File**: `scrapers/cfr_data_collection.py` (243 lines)  
**Entry**: `scrape_cfr_journals(start_url=CFR_START_URL)` at line 182

### Starting Point

- **CFR**: Centre for Research, Anna University — lists approved academic journals
- **URL**: `https://cfr.annauniv.edu/research/academics/english-journals-list.php` (from `config/urls.py:7`)
- **Access method**: `scrapling.fetchers.Fetcher.get(url, verify=False)` — HTTP request with SSL verification disabled

### Data Collection Process

1. `scrape_cfr_journals()` loops pages via `while current_url and current_url not in visited_urls` (line 193)
2. For each page:
   - `Fetcher.get(current_url, verify=False)` → HTTP GET (line 197)
   - Response body decoded: tries `utf-8 → latin-1 → cp1252 → iso-8859-1` (lines 206-211)
   - `Adaptor(decoded_html)` parses HTML (line 216)
   - `parse_cfr_table_rows(doc)` extracts journal rows (line 217)
   - `find_next_page_url(doc, current_url)` checks for pagination (line 227)

### Table Parsing (`parse_cfr_table_rows`, line 92)

1. Finds `<table>` elements via `doc.css("table")`
2. Identifies the target table by checking first row headers for "SL", "TITLE", "ISSN" keywords (lines 114-118)
3. Builds column mapping from header texts (lines 121-133):
   - "SL" or "S.NO" → `sl_no`
   - "TITLE" or "JOURNAL" → `title`
   - "PRINT" + "ISSN" → `print_issn`
   - "E-" or "ONLINE" or "ELECTRONIC" → `e_issn`
   - "PUBLISHER" → `publisher`
   - "COUNTRY" → `country`
4. Iterates data rows (skipping header), extracts 6 fields per row via `tds[index].text` (lines 143-161)
5. `clean_cell_text()` (line 44): replaces `\xa0` with space, collapses whitespace

### Pagination (`find_next_page_url`, line 55)

Checks for:
- `a[rel="next"]` (line 63)
- Anchor text containing "next", ">", "»" (line 80)
- `aria-label` with "next" (line 82)
- CSS class "next" with "page" or "pagination" (line 86)

### Output

Returns `List[CFRJournal]` where `CFRJournal` (models.py:6) has:
- `sl_no`, `journal_title`, `print_issn`, `e_issn`, `publisher`, `country`

### Error Handling

- HTTP non-200: prints error, saves debug HTML, breaks (line 199)
- 0 journals on page: prints warning, saves debug HTML (line 220)
- Exception: prints error, saves debug HTML, breaks (line 234)

---

## 6. Scopus Verification — Complete Working

**File**: `scrapers/scopus.py` (294 lines)  
**Entry**: `verify_scopus_indexing(journals, source_file, force_redownload=True)` at line 262

### Why Scopus Is Used

Scopus is a major academic citation database. The project verifies which CFR journals are indexed in Scopus and their status (Active, Inactive, Discontinued).

### Source of Scopus Data

**NOT** scraped from scopus.com. Instead, uses the official **Elsevier Source Title List** — a downloadable Excel file containing all Scopus-indexed journals.

### Download Process (`download_scopus_dataset`, line 42)

1. Fetches `ELSEVIER_SCOPUS_POLICY_URL` = `https://www.elsevier.com/solutions/scopus/how-scopus-works/content/content-policy-and-selection` (config/urls.py:10)
2. Parses HTML with `Adaptor` to find `.xlsx` link containing "ext_list" or "source_title" or "scopus_source" (lines 68-78)
3. Regex fallback: `href=["']([^"']*ctfassets[^"']*ext_list[^"']*\.xlsx?)` (line 81)
4. Downloads file to `output/scopus_source_title_list.xlsx` (~19MB)
5. `force_redownload=True` (hardcoded) — deletes old copy and downloads fresh every run

### Index Building (`ScopusVerifier._load_and_build_index`, line 155)

1. `pd.ExcelFile(path)` → validates sheet starts with "Scopus Sources" (line 162)
2. `pd.read_excel(xl, sheet_name, header=0, dtype=str)` → loads ~74,000 rows (line 164)
3. For each row:
   - Normalizes ISSN via `normalize_issn()` (lines 183-184)
   - Determines status from "Active or Inactive" and "Titles Discontinued by Scopus" columns (lines 186-198):
     - "Discontinued by Scopus" → `Discontinued`
     - "Active" → `Active / Indexed`
     - "Inactive" → `Inactive`
     - Other → `Unable to Verify`
     - Empty → `Not Indexed`
   - Builds `issn_map[normalized_issn] = record` (lines 212-221)

### Verification (`verify_journal`, line 226)

1. Normalizes journal's Print-ISSN and E-ISSN
2. Looks up `issn_map[norm_p]` → match_type = "Print ISSN"
3. Falls back to `issn_map[norm_e]` → match_type = "E-ISSN"
4. Returns `ScopusVerificationResult` with 10 fields

### Output Model — `ScopusVerificationResult` (models.py:18)

| Field | Type | Meaning |
|-------|------|---------|
| `scopus_status` | str | "Active / Indexed", "Inactive", "Discontinued", "Not Indexed", "Unable to Verify" |
| `match_type` | str | "Print ISSN", "E-ISSN", "No Match" |
| `sourcerecord_id` | str | Scopus source record ID |
| `source_title` | str | Journal title in Scopus |
| `scopus_issn` | str | ISSN as listed in Scopus |
| `scopus_eissn` | str | E-ISSN as listed in Scopus |
| `scopus_publisher` | str | Publisher name in Scopus |
| `scopus_coverage` | str | Coverage dates |
| `raw_active_status` | str | Raw "Active"/"Inactive" from Excel |
| `raw_discontinued_flag` | str | Raw discontinued flag from Excel |

---

## 7. MJL Verification — Complete Working

**File**: `scrapers/mjl.py` (577 lines)  
**Entry**: `verify_mjl_indexing(active_pairs, headless, verbose, max_workers)` at line 459

### Why Hybrid

- **Direct HTTP POST** (~0.4s/journal): Fast, thread-safe, no browser needed. Used as primary.
- **Playwright browser** (~3s/journal): Robust fallback when POST fails (403, network error). Only used when needed.

### Phase 1: Direct POST (`_direct_verify_single`, line 423)

1. Formats ISSN with hyphen: `"01296612"` → `"0129-6612"` (line 428-431)
2. `_direct_post_mjl(formatted_issn)` (line 191):
   - Builds payload via `_build_mjl_payload()` (line 172):
     ```json
     {"searchValue": "0129-6612", "pageNum": 1, "pageSize": 10,
      "sortOrder": [{"name": "RELEVANCE", "order": "DESC"}],
      "filters": [...], "searchIdentifier": "<uuid4>"}
     ```
   - POST to `MJL_API_URL` = `https://mjl.clarivate.com/api/mjl/jprof/public/rank-search` (config/urls.py:16)
   - Headers: `Referer: mjl.clarivate.com`, `X-1P-AppId: mjl`, `Authorization: Bearer`, `Accept: application/json` (lines 163-170)
   - `urllib.request.urlopen(req, timeout=10)` — no browser (line 201)
   - Returns raw JSON string or `None`
3. `_parse_mjl_response(raw, norm_issn)` (line 114):
   - Parses `journalProfiles` array from JSON
   - For each profile: extracts `issn`, `eissn`, `products[]`
   - If searched ISSN matches profile ISSN exactly → "Found" + `_extract_wos_indexes(products)` (line 138)
   - If `totalRecords == 1` → "Found" + "Single Result" (line 146)
   - Otherwise → "Not Found" (line 156)
4. `_extract_wos_indexes(products)` (line 67):
   - Checks `description` substring for index names: "science citation index expanded" → SCIE, "social sciences citation index" → SSCI, "arts & humanities citation index" → AHCI, "emerging sources citation index" → ESCI
   - Falls back to `productCode` mapping: `D→SCIE, E→SSCI, C/H→AHCI, F→ESCI` (line 47)
5. Threading: `ThreadPoolExecutor(max_workers)` for all journals in parallel (line 481)
6. Journals where `_direct_verify_single` returns `None` → added to `needs_fallback` list

### Phase 2: Playwright Fallback (`MJLVerifier`, line 216)

Only runs if Phase 1 returned `None` for any journal.

1. Lazy init: `_start()` only called when fallback needed (line 363-364)
2. Browser setup:
   - `sync_playwright()` → `chromium.launch(headless, args=["--no-sandbox"])` (line 245-252)
   - New context with user-agent, viewport, cookies (line 253-267)
   - Route abort for pendo/vidyard/analytics/recaptcha (line 269-272)
3. Pre-warm: `goto(MJL_HOME_URL)` + `sleep(4)` + remove overlays (lines 274-279)
4. `_search_issn(formatted_issn)` (line 306):
   - `goto(MJL_SEARCH_BASE.format(issn=formatted_issn))` (line 328)
   - Intercepts XHR via `page.on("response", on_response)` (line 326)
   - Captures response from URL containing `MJL_API_PATTERN = "rank-search"` (line 318)
   - Returns raw JSON body or `None` on timeout
5. `verify_journal()` tries Print-ISSN first, falls back to E-ISSN (lines 372-416)

### Output Model — `MJLVerificationResult` (models.py:36)

| Field | Type | Meaning |
|-------|------|---------|
| `mjl_status` | str | "Found", "Not Found", "Unable to Verify" |
| `mjl_index` | str | "SCIE", "SSCI", "AHCI", "ESCI", or "no data" |
| `mjl_issn_used` | str | Which ISSN was searched (formatted with hyphen) |
| `mjl_match_type` | str | "Print ISSN", "E-ISSN", "Exact ISSN", "Single Result", "No Match" |
| `mjl_source_title` | str | Journal title from MJL response |

### MJL Flow Diagram

```
MJL Input (CFRJournal, ScopusResult)
   │
   ▼
Phase 1: Direct POST (ThreadPool, ~0.4s/journal)
   │
   ├── POST to MJL_API_URL with JSON payload
   │
   ├── Response OK?
   │   ├── YES → _parse_mjl_response()
   │   │         ├── ISSN match found? → "Found" + WoS indexes
   │   │         ├── Single result? → "Found" + "Single Result"
   │   │         └── No match → "Not Found"
   │   │
   │   └── NO (None) → Add to needs_fallback
   │
   ▼
Phase 2: Playwright Fallback (only for failures, ~3s/journal)
   │
   ├── MJLVerifier._start() (lazy browser init)
   ├── goto MJL_SEARCH_BASE?issn=...
   ├── Intercept rank-search XHR response
   ├── _parse_mjl_response()
   └── Return result
```

---

## 8. SCImago Scraper — Complete Working

**File**: `scrapers/scimago.py` (516 lines)  
**Entry**: `ScimagoScraper.scrape_journal(issn_input)` at line 300

### Input

An ISSN string (e.g., `"0129-6612"` or `"01296612"`).

### ISSN Normalization

`normalize_issn("0129-6612")` → strips `[^0-9Xx]` → `"01296612"` (processors/issn.py:20)

### Search URL

`SCIMAGO_SEARCH_BASE = "https://www.scimagojr.com/journalsearch.php?q={issn}"` (config/urls.py:21)

### Search Process (`scrape_journal`, line 300)

1. Normalize ISSN → `normalize_issn(issn_input)` (line 307)
2. `search_scimago(norm_issn)` (line 140):
   - Builds `search_url = SEARCH_BASE_URL.format(issn=norm_issn)`
   - `fetch_url(search_url)` (line 118):
     - First tries `Fetcher.get(url)` — fast HTTP (line 125)
     - If HTTP 200 and no challenge page → returns response
     - Otherwise: `with _stealth_lock: session.fetch(url)` — browser (line 130-132)
3. Check `search_response.status != 200` → FAILED (line 334)
4. `extract_journal_id(search_response, norm_issn)` (line 148):
   - Checks `is_challenge_page(response.text)` → FAILED (line 153)
   - Searches `<a>` hrefs for `journalsearch.php?tip=sid` (line 160-167)
   - Parses `q` parameter from URL query string → must be digits
   - Regex fallback: `r"journalsearch\.php\?q=(\d+)&(?:amp;)?tip=sid"` (line 170)
5. `fetch_journal_page(journal_id)` (line 176):
   - `JOURNAL_BASE_URL.format(journal_id=journal_id)` = `https://www.scimagojr.com/journalsearch.php?q={id}&tip=sid&clean=0`
   - `fetch_url(journal_url)` — same HTTP-first, browser-fallback pattern

### Journal ID

From URL like `https://www.scimagojr.com/journalsearch.php?q=23067&tip=sid&clean=0`, the journal ID is `q=23067`.

### Extracted Fields

| Field | HTML Source | Selector/Method | Line |
|-------|-----------|-----------------|------|
| **SJR** | `.hsjr` element | `response.css(".hsjr")` → regex `\d+(?:\.\d+)?` | 184-195 |
| | `.hindexnumber.hindex-white` fallback | `response.css(".hindexnumber.hindex-white")` → regex `\b\d+\.\d+\b` | 197-201 |
| **Quartile** | `.hindexnumber.hindex-white span` | CSS class regex `\b(Q[1-4])\b` on span class or text | 210-236 |
| | `.hindexnumber` fallback | Regex `\b(Q[1-4])\b` on element text | 233-236 |
| **H-Index** | `<h2>` containing "H-Index" | `h2` text → parent `.hindexnumber` text | 245-258 |
| | `<div>` containing "h-index" fallback | `div.css(".hindexnumber")` text | 260-267 |
| **Coverage** | `<h2>` containing "Coverage" | `h2` text → parent `.cuadrado-detail` text | 275-288 |
| | `<div>` containing "coverage" fallback | `div.css(".cuadrado-detail")` text | 290-296 |

### Status Determination (line 430-442)

- All 4 fields extracted → `SUCCESS`
- Any field extracted → `PARTIAL`
- No fields extracted → `FAILED`

### Security/Challenge Handling (`is_challenge_page`, line 22)

Detects: "just a moment", "turnstile", "challenge-platform", "checking your browser", "access denied", "cf-challenge"

When detected: saves debug HTML, returns FAILED.

### Thread Safety

- `_stealth_lock = threading.RLock()` (line 61)
- `_get_stealth_session()` acquires lock before creating/accessing `StealthySession` (line 89)
- `fetch_url()` acquires lock before browser access (lines 130-132, 136-138)
- `StealthySession(headless, max_pages=5, disable_resources=True, timeout=10000, retries=2, solve_cloudflare=True)` (lines 93-101)
- Multiple threads share one browser instance, serialized by RLock

### Output Model — `JournalResult` (models.py:48)

| Field | Type | Meaning |
|-------|------|---------|
| `issn` | str | Normalized ISSN |
| `journal_id` | str | SCImago numeric ID or "no data" |
| `sjr` | str | SJR value or "no data" |
| `quartile` | str | Q1/Q2/Q3/Q4 or "no data" |
| `h_index` | str | H-Index value or "no data" |
| `coverage` | str | Coverage years or "no data" |
| `search_url` | str | URL used for search |
| `journal_url` | str | URL of journal page |
| `status` | str | "SUCCESS", "PARTIAL", "FAILED" |
| `error` | str | Error message or None |
| `execution_time` | float | Seconds for this ISSN |

---

## 9. ISSN Processing

**File**: `processors/issn.py` (24 lines)

### `normalize_issn(issn: str) -> str`

1. Returns `"no data"` for: `None`, `""`, `"no data"`, `"none"`, `"nan"`, `"null"`, `"-"`, `"nil"`, `"na"`, `"n/a"` (line 17)
2. `re.sub(r"[^0-9Xx]", "", val).upper()` — strips everything except digits and X/x, uppercases (line 20)
3. Returns `"no data"` if result is empty (line 22)

### Examples

| Input | Output |
|-------|--------|
| `"0129-6612"` | `"01296612"` |
| `"2377-6277"` | `"23776277"` |
| `" 0028-0836 "` | `"00280836"` |
| `""` | `"no data"` |
| `"no data"` | `"no data"` |
| `"ISSN 1234-5678"` | `"12345678"` |

---

## 10. Data Models

**File**: `models.py` (63 lines)

### `CFRJournal` (line 6)

| Field | Type | Source | When Populated |
|-------|------|--------|----------------|
| `sl_no` | str | CFR portal table | Stage 1 |
| `journal_title` | str | CFR portal table | Stage 1 |
| `print_issn` | str | CFR portal table | Stage 1 |
| `e_issn` | str | CFR portal table | Stage 1 |
| `publisher` | str | CFR portal table | Stage 1 |
| `country` | str | CFR portal table | Stage 1 |

### `ScopusVerificationResult` (line 18)

| Field | Type | Source | When Populated |
|-------|------|--------|----------------|
| `scopus_status` | str | Scopus Excel | Stage 2 |
| `match_type` | str | Scopus Excel | Stage 2 |
| `sourcerecord_id` | str | Scopus Excel | Stage 2 (default "no data") |
| `source_title` | str | Scopus Excel | Stage 2 (default "no data") |
| `scopus_issn` | str | Scopus Excel | Stage 2 (default "no data") |
| `scopus_eissn` | str | Scopus Excel | Stage 2 (default "no data") |
| `scopus_publisher` | str | Scopus Excel | Stage 2 (default "no data") |
| `scopus_coverage` | str | Scopus Excel | Stage 2 (default "no data") |
| `raw_active_status` | str | Scopus Excel | Stage 2 (default "no data") |
| `raw_discontinued_flag` | str | Scopus Excel | Stage 2 (default "no data") |

### `MJLVerificationResult` (line 36)

| Field | Type | Source | When Populated |
|-------|------|--------|----------------|
| `mjl_status` | str | MJL API/Playwright | Stage 3 |
| `mjl_index` | str | MJL API/Playwright | Stage 3 (default "no data") |
| `mjl_issn_used` | str | MJL API/Playwright | Stage 3 (default "no data") |
| `mjl_match_type` | str | MJL API/Playwright | Stage 3 (default "No Match") |
| `mjl_source_title` | str | MJL API/Playwright | Stage 3 (default "no data") |

### `JournalResult` (line 48)

| Field | Type | Source | When Populated |
|-------|------|--------|----------------|
| `issn` | str | SCImago scraper | Stage 4 |
| `journal_id` | str | SCImago scraper | Stage 4 |
| `sjr` | str | SCImago scraper | Stage 4 |
| `quartile` | str | SCImago scraper | Stage 4 |
| `h_index` | str | SCImago scraper | Stage 4 |
| `coverage` | str | SCImago scraper | Stage 4 |
| `search_url` | str | SCImago scraper | Stage 4 |
| `journal_url` | str | SCImago scraper | Stage 4 |
| `status` | str | SCImago scraper | Stage 4 |
| `error` | str | SCImago scraper | Stage 4 (default None) |
| `execution_time` | float | SCImago scraper | Stage 4 (default 0.0) |

---

## 11. Data Transformation Through the Pipeline

One journal record changes as it passes through the system:

```
CFR Portal HTML
   │
   ▼
CFRJournal(sl_no, journal_title, print_issn, e_issn, publisher, country)
   │
   ▼ Scopus Verification
( CFRJournal, ScopusVerificationResult )
   │  Adds: scopus_status, match_type, sourcerecord_id, source_title,
   │        scopus_publisher, scopus_coverage, raw flags
   │
   ▼ MJL Verification (Active/Indexed only)
( CFRJournal, ScopusVerificationResult, MJLVerificationResult )
   │  Adds: mjl_status, mjl_index, mjl_issn_used, mjl_source_title
   │
   ▼ SCImago Enrichment (Active/Indexed only)
Record dict with 29+ fields:
   │  CFR: Sl.No, Full Journal Title, Print-ISSN, E-ISSN, Publisher, Country
   │  Scopus: Scopus Indexing Status, Match Type, Source Record ID,
   │          Source Title, Publisher, Coverage
   │  MJL: Status, Index, Matched ISSN, Source Title
   │  SCImago: Journal ID, SJR, Quartile, H-Index, Coverage, URL, Status, Error
   │
   ▼ ISSN Normalization
journal_row: { normalized_print, normalized_e, ... }
   │
   ▼ Hash Computation
new_hash = SHA256( sorted JSON of 29 normalized fields )
   │
   ▼ Database Comparison
   ├── New → to_insert list
   ├── Unchanged → to_touch list
   └── Changed → to_update list + all_changes
   │
   ▼ Bulk Write to Supabase
INSERT/UPDATE/TOUCH
```

---

## 12. Database Architecture

### `connection.py` (43 lines)

- `get_supabase_client()` (line 10): Singleton pattern. Reads `SUPABASE_URL` + `SUPABASE_KEY` (or `SUPABASE_SERVICE_ROLE_KEY`) from `.env` via `load_dotenv()`. Raises `RuntimeError` if missing.
- `is_supabase_configured()` (line 39): Returns `True` if env vars present (no client creation).

### `schema.sql` (198 lines) — 7 Tables

#### 1. `journals` (master, line 10)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | `gen_random_uuid()` |
| `title` | TEXT NOT NULL | Journal title |
| `print_issn` | TEXT | Raw Print-ISSN |
| `e_issn` | TEXT | Raw E-ISSN |
| `normalized_print` | TEXT | Normalized Print-ISSN |
| `normalized_e` | TEXT | Normalized E-ISSN |
| `publisher` | TEXT | Publisher name |
| `country` | TEXT | Country |
| `data_hash` | TEXT | SHA256 hash of 29 fields |
| `created_at` | TIMESTAMPTZ | Auto-set |
| `updated_at` | TIMESTAMPTZ | Auto-updated via trigger |
| `first_seen_at` | TIMESTAMPTZ | First pipeline seen |
| `last_checked_at` | TIMESTAMPTZ | Last pipeline check |
| `last_changed_at` | TIMESTAMPTZ | Last data change |
| `last_seen_pipeline_run_id` | UUID FK | → pipeline_runs |

**Indexes**: `normalized_print` UNIQUE (partial, not "no data"), `normalized_e` UNIQUE (partial), `data_hash`, `title`, `last_checked_at`

#### 2. `cfr_results` (one-to-one, line 46)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `journal_id` | UUID FK CASCADE | → journals, UNIQUE |
| `sl_no` | TEXT | |
| `journal_title` | TEXT | |
| `print_issn` | TEXT | |
| `e_issn` | TEXT | |
| `publisher` | TEXT | |
| `country` | TEXT | |

#### 3. `scopus_results` (one-to-one, line 65)

| Column | Type | Notes |
|--------|------|-------|
| `journal_id` | UUID PK FK CASCADE | → journals |
| `scopus_status` | TEXT | |
| `match_type` | TEXT | |
| `sourcerecord_id` | TEXT | |
| `source_title` | TEXT | |
| `scopus_publisher` | TEXT | |
| `scopus_coverage` | TEXT | |
| `scopus_issn` | TEXT | |
| `scopus_eissn` | TEXT | |
| `raw_active_status` | TEXT | |
| `raw_discontinued_flag` | TEXT | |

#### 4. `mjl_results` (one-to-one, line 86)

| Column | Type | Notes |
|--------|------|-------|
| `journal_id` | UUID PK FK CASCADE | → journals |
| `mjl_status` | TEXT | |
| `mjl_index` | TEXT | |
| `mjl_issn_used` | TEXT | |
| `mjl_match_type` | TEXT | |
| `mjl_source_title` | TEXT | |
| `execution_time` | DOUBLE PRECISION | |
| `error` | TEXT | |

#### 5. `scimago_results` (one-to-one, line 104)

| Column | Type | Notes |
|--------|------|-------|
| `journal_id` | UUID PK FK CASCADE | → journals |
| `scimago_status` | TEXT | |
| `journal_id_external` | TEXT | SCImago numeric ID |
| `matched_issn` | TEXT | |
| `sjr` | TEXT | |
| `quartile` | TEXT | |
| `h_index` | TEXT | |
| `coverage` | TEXT | |
| `url` | TEXT | |
| `execution_time` | DOUBLE PRECISION | |
| `error` | TEXT | |

#### 6. `pipeline_runs` (line 126)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `started_at` | TIMESTAMPTZ | |
| `finished_at` | TIMESTAMPTZ | |
| `duration_seconds` | DOUBLE PRECISION | |
| `status` | TEXT | "running", "success", "failed" |
| `total_cfr` | INT | |
| `total_scopus_active` | INT | |
| `total_mjl_processed` | INT | |
| `total_scimago_processed` | INT | |
| `new_records` | INT | |
| `updated_records` | INT | |
| `unchanged_records` | INT | |
| `failed_records` | INT | |
| `duplicate_skipped` | INT | Added via ALTER TABLE |
| `error` | TEXT | |

#### 7. `journal_changes` (line 148)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `journal_id` | UUID FK CASCADE | → journals |
| `pipeline_run_id` | UUID FK SET NULL | → pipeline_runs |
| `source` | TEXT | "cfr", "scopus", "mjl", "scimago", "journal" |
| `field_name` | TEXT | |
| `old_value` | TEXT | |
| `new_value` | TEXT | |
| `changed_at` | TIMESTAMPTZ | |

#### 8. `skipped_records` (line 166)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `pipeline_run_id` | UUID FK SET NULL | → pipeline_runs |
| `sl_no` | TEXT | |
| `journal_title` | TEXT | |
| `print_issn` | TEXT | |
| `e_issn` | TEXT | |
| `normalized_print` | TEXT | |
| `normalized_e` | TEXT | |
| `publisher` | TEXT | |
| `country` | TEXT | |
| `reason` | TEXT NOT NULL | "duplicate_issn" |
| `duplicate_of_issn` | TEXT | |
| `duplicate_of_title` | TEXT | |
| `skipped_at` | TIMESTAMPTZ | |

### ER Diagram

```
pipeline_runs ←─── journals ───→ cfr_results
                    │    │
                    │    ├──→ scopus_results
                    │    ├──→ mjl_results
                    │    └──→ scimago_results
                    │
                    ├──→ journal_changes
                    └──→ skipped_records
```

---

## 13. Database Duplicate Detection

### How Existing Journals Are Found

**Primary key**: Normalized ISSN (both Print and E-ISSN are individually unique).

`get_all_journals_map()` (repository.py:66) fetches all journals in 1 query and builds a dict:

```python
lookup[normalized_print] = journal_row
lookup[normalized_e] = journal_row
```

`_lookup_existing(print_raw, e_raw)` (main.py:538) checks:
1. Normalize both ISSNs
2. For each normalized ISSN, check if it exists in `journals_map`
3. Return first match or `None`

This is O(1) per journal, all in memory.

---

## 14. Hashing and Change Detection

### `database/hash.py` — 29 Fields

`build_hash_input()` (line 46) accepts 29 parameters and returns a dict with 29 keys:

| # | Key | Source |
|---|-----|--------|
| 1 | `title` | CFR journal_title |
| 2 | `print_issn` | CFR print_issn |
| 3 | `e_issn` | CFR e_issn |
| 4 | `publisher` | CFR publisher |
| 5 | `country` | CFR country |
| 6 | `cfr_sl_no` | CFR sl_no |
| 7 | `scopus_status` | Scopus status |
| 8 | `scopus_match_type` | Scopus match type |
| 9 | `scopus_source_title` | Scopus source title |
| 10 | `scopus_sourcerecord_id` | Scopus record ID |
| 11 | `scopus_publisher` | Scopus publisher |
| 12 | `scopus_coverage` | Scopus coverage |
| 13 | `scopus_issn` | Scopus ISSN (currently "") |
| 14 | `scopus_eissn` | Scopus EISSN (currently "") |
| 15 | `scopus_raw_active` | Scopus raw active (currently "") |
| 16 | `scopus_raw_discontinued` | Scopus raw discontinued (currently "") |
| 17 | `mjl_status` | MJL status |
| 18 | `mjl_index` | MJL WoS index |
| 19 | `mjl_issn_used` | MJL ISSN searched |
| 20 | `mjl_match_type` | MJL match type |
| 21 | `mjl_source_title` | MJL source title |
| 22 | `scimago_status` | SCImago status |
| 23 | `scimago_journal_id` | SCImago journal ID |
| 24 | `scimago_matched_issn` | SCImago matched ISSN |
| 25 | `sjr` | SCImago SJR |
| 26 | `quartile` | SCImago quartile |
| 27 | `h_index` | SCImago H-Index |
| 28 | `scimago_coverage` | SCImago coverage |
| 29 | `scimago_url` | SCImago URL |

(Note: `scopus_issn`, `scopus_eissn`, `scopus_raw_active`, `scopus_raw_discontinued` are passed as empty strings — included in hash for future use but currently static.)

### Normalization (`_normalize_value`, line 5)

1. `None` → `""` (line 8)
2. Strip whitespace, lowercase (lines 9, 14)
3. Placeholders → `""`: `"none"`, `"no data"`, `"null"`, `"nan"`, `"n/a"`, `"na"`, `"nil"`, `"-"` (line 11)
4. `"&"` → `" and "` (line 17) — so "EAST & WEST" and "EAST AND WEST" hash identically
5. Collapse whitespace: `re.sub(r"\s+", " ", s)` (line 20)
6. Normalize colon/comma spacing (lines 21-22)

### Hash Computation (`compute_data_hash`, line 35)

```python
normalized = _normalize_record(record)    # normalize all values
canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
return hashlib.sha256(canonical.encode("utf-8")).hexdigest()  # 64-char hex string
```

### Change Detection

In `main.py` PHASE 2 (line 547):
1. Compute `new_hash` from current scraped data
2. Recompute `old_hash_computed` from bulk-fetched DB values (not stored `data_hash` — catches manual DB edits)
3. If `old_hash_computed == new_hash` → unchanged
4. If different → field-level diff to identify which fields changed

---

## 15. Repository Layer

### Bulk Operations

| Function | Purpose | Queries |
|----------|---------|---------|
| `get_all_journals_map()` | Fetch all journals for O(1) lookup | 1 |
| `bulk_get_child_map(table, ids)` | Fetch all child table rows by journal IDs | 1 per table |
| `bulk_touch_journals(ids, run_id)` | Update `last_checked_at` for unchanged | 1 |
| `bulk_update_journals(rows)` | Upsert changed journals | 1 (chunked by 80) |
| `bulk_insert_journals(rows)` | Insert new journals, return IDs | 1 (chunked by 80) |
| `bulk_upsert_child(table, rows)` | Upsert child table rows | 1 per table (chunked) |
| `bulk_insert_changes(changes)` | Insert journal_changes rows | 1 (chunked by 80) |

### Per-Journal Operations

| Function | Purpose | Used By |
|----------|---------|---------|
| `get_journal_by_issn(p, e)` | Find journal by normalized ISSN | Fallback if bulk fails |
| `get_journal(id)` | Fetch single journal | Manual queries |
| `get_existing_full(id)` | Fetch journal + all 4 child tables | Legacy (replaced by bulk) |
| `insert_journal_full(...)` | Insert journal + 4 children | Legacy fallback |
| `update_journal_full(...)` | Update journal + 4 children + changes | Legacy fallback |
| `touch_journal_checked(id, run_id)` | Update timestamps only | Legacy fallback |
| `record_change(...)` | Insert single journal_changes row | Legacy fallback |
| `insert_skipped_record(...)` | Insert CFR dedup audit record | CFR dedup |
| `create_pipeline_run(total)` | Create new pipeline run record | Pipeline start |
| `finish_pipeline_run(id, status, ...)` | Update run with results | Pipeline end |

---

## 16. Bulk Database Persistence

### PHASE 1: Bulk READ (5 queries)

```python
journals_map = get_all_journals_map()           # 1 query: SELECT id, normalized_*, data_hash FROM journals
cfr_map = bulk_get_child_map("cfr_results", ids)    # 1 query: SELECT * FROM cfr_results WHERE journal_id IN (...)
scopus_map = bulk_get_child_map("scopus_results", ids)  # 1 query
mjl_map = bulk_get_child_map("mjl_results", ids)      # 1 query
scimago_map = bulk_get_child_map("scimago_results", ids) # 1 query
```

### PHASE 2: In-memory classify (0 queries)

For each of 256 results:
1. Compute `new_hash` from scraped data
2. `_lookup_existing(print, e)` → O(1) dict lookup
3. If `None` → Case A: new → collect in `to_insert_*` lists
4. If exists:
   - Recompute `old_hash_computed` from bulk-fetched child data (catches manual DB edits)
   - If same → Case B: unchanged → add to `to_touch_ids`
   - If different → Case C: changed → field-level diff, collect in `to_update_*` lists + `all_changes`

### PHASE 3: Bulk WRITE (~9 queries)

```python
bulk_insert_journals(to_insert_journals)         # 1 query, returns IDs
bulk_upsert_child("cfr_results", to_insert_cfr)  # 1 query (for new journals)
bulk_upsert_child("scopus_results", ...)
bulk_upsert_child("mjl_results", ...)
bulk_upsert_child("scimago_results", ...)
bulk_update_journals(to_update_journals)          # 1 query (for changed journals)
bulk_upsert_child("cfr_results", to_update_cfr)  # 1 query (for changed journals)
bulk_upsert_child("scopus_results", ...)
bulk_upsert_child("mjl_results", ...)
bulk_upsert_child("scimago_results", ...)
bulk_touch_journals(to_touch_ids, pipeline_run_id) # 1 query (unchanged)
bulk_insert_changes(all_changes)                  # 1 query
```

All bulk writes are chunked by `BATCH_SIZE = 80` (repository.py:347) to avoid payload limits.

---

## 17. Pipeline Runs

### Creation

`create_pipeline_run(total_cfr)` (repository.py:218):
```sql
INSERT INTO pipeline_runs (started_at, status, total_cfr) VALUES (now(), 'running', $1)
```
Returns the new run UUID.

### Completion

`finish_pipeline_run(run_id, "success", duration, stats)` (repository.py:228):
```sql
UPDATE pipeline_runs SET finished_at=now(), duration_seconds=$1, status='success',
  total_scopus_active=$2, total_mjl_processed=$3, total_scimago_processed=$4,
  new_records=$5, updated_records=$6, unchanged_records=$7, failed_records=$8
WHERE id=$9
```

### Status Values

- `"running"` — pipeline started
- `"success"` — pipeline completed successfully
- `"failed"` — pipeline failed (set only if top-level exception occurs)

### Checking Runs

```sql
SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1;
-- Shows: status, duration_seconds, new/updated/unchanged/failed counts
```

---

## 18. Timing and Performance

`time.perf_counter()` is used throughout for precise wall-clock timing.

### Per-Stage Timing (main.py)

| Stage | Variable | Line | Measures |
|-------|----------|------|----------|
| CFR | `cfr_duration` | 222 | `scrape_cfr_journals()` |
| Scopus init | `scopus_init_time` | 271 | Excel load + index construction |
| Scopus verify | `scopus_verify_time` | 272 | Per-journal ISSN lookup |
| MJL | `mjl_duration` | 298 | `verify_mjl_indexing()` (POST + fallback) |
| SCImago | `scimago_duration` | 443 | ThreadPool SCImago scraping |
| DB Phase 1 | `phase1_time` | 528 | Bulk read |
| DB Phase 2 | `phase2_time` | 791 | In-memory classify |
| DB Phase 3 | `phase3_time` | 853 | Bulk write |
| Total | `total_pipeline_time` | 876 | Everything |

### Per-Journal Timing

- SCImago: `execution_time` in `JournalResult` (scimago.py:444)
- MJL: printed but not stored in result

---

## 19. Error Handling

### CFR Scraper

- HTTP non-200: prints error, saves debug HTML, breaks out of loop (line 199)
- 0 journals: prints warning, saves debug HTML (line 220)
- Exception: prints error, saves debug HTML, breaks (line 234)
- **Pipeline continues** — partial CFR data is used

### Scopus

- Download fails: falls back to existing cached file (line 119)
- No cached file: raises `FileNotFoundError` (line 121) — **pipeline stops**
- Missing columns: raises `KeyError` (line 170) — **pipeline stops**

### MJL

- Direct POST returns None → added to `needs_fallback` list (line 490)
- Playwright fails → `MJLVerificationResult(mjl_status="Unable to Verify")` (line 531)
- **Pipeline continues** — journals marked as "Unable to Verify"

### SCImago

- HTTP non-200: returns FAILED (line 339)
- No journal ID found: returns FAILED (line 360)
- Security challenge: returns FAILED (line 385)
- Exception: returns FAILED (line 461)
- **Pipeline continues** — journals marked as FAILED

### Database

- Supabase not configured: skips DB entirely, prints info (line 874)
- `create_pipeline_run` fails: sets `pipeline_run_id = None`, continues (line 488)
- Bulk fetch fails: falls back to empty dicts, continues (line 531)
- Individual skipped record insert fails: prints warning, continues (line 507)
- `finish_pipeline_run` fails: prints warning (line 872)

---

## 20. Output Files

### `output/scopus_source_title_list.xlsx`

- Created by: `download_scopus_dataset()` (scopus.py:42)
- When: Every run (force_redownload=True)
- Role: Source data for Scopus verification
- Size: ~19MB
- Gitignored: Yes (`output/*` in .gitignore)

### `output/debug/`

- Created by: `save_cfr_debug_html()` (cfr_data_collection.py:32), `ScimagoScraper.save_debug_html()` (scimago.py:105)
- When: On errors, 0-row pages, or missing fields
- Role: Diagnostic HTML dumps
- Gitignored: Yes (`output/debug/*`)

### No Excel Output

The pipeline no longer writes Excel output files. Supabase is the sole source of truth.

---

## 21. Tests

13 tests across 3 files, all using mocked Supabase (no real DB required).

### `tests/test_hash.py` — 5 tests

| Test | What It Verifies |
|------|------------------|
| `test_hash_deterministic` | Same input → same SHA256, length 64 |
| `test_hash_normalization_whitespace_casing` | Whitespace/casing differences → same hash |
| `test_hash_none_vs_empty` | `None` vs `"no data"` vs `""` → same hash |
| `test_hash_issn_formatting` | Hyphenated vs plain ISSN differs (raw); normalized ISSN same |
| `test_hash_changed_field` | Changed h_index → different hash |

### `tests/test_change_detection.py` — 5 tests

Uses `MockDB` in-memory dict to simulate repository.

| Test | What It Verifies |
|------|------------------|
| `test_case_A_empty_db_insert` | Empty DB → insert → "new" |
| `test_case_B_unchanged` | Same data → "unchanged", 0 changes |
| `test_case_C_single_field_changed` | H-Index changed → "updated", 1 change |
| `test_case_D_multiple_fields_changed` | H-Index + Quartile + SJR → "updated", 3 changes |
| `test_case_E_normalization` | Whitespace normalization → same hash → "unchanged" |

### `tests/test_repository_mock.py` — 3 tests

| Test | What It Verifies |
|------|------------------|
| `test_get_journal_by_issn_logic` | `normalize_issn` produces correct results |
| `test_repository_import_without_env` | Import doesn't crash without .env |
| `test_hash_integration_with_normalize` | Hash + normalize_issn integration produces 64-char hash |

---

## 22. Complete Example Walkthrough

### Input: ISSN `0129-6612` (Journal of Chemical Sciences, Anna University)

```
Step 1: CFR Collection
  Function: scrape_cfr_journals()
  File: scrapers/cfr_data_collection.py:182
  Input: CFR_START_URL
  Output: CFRJournal(sl_no="104", journal_title="JOURNAL OF CHEMICAL SCIENCES",
          print_issn="0129-6612", e_issn="0973-7754", publisher="ANNA UNIV CHENNAI",
          country="India")

Step 2: Scopus Verification
  Function: verify_scopus_indexing() → ScopusVerifier.verify_journal()
  File: scrapers/scopus.py:226
  Input: CFRJournal
  Process: normalize_issn("0129-6612") → "01296612" → issn_map lookup
  Output: ScopusVerificationResult(scopus_status="Active / Indexed",
          match_type="Print ISSN", source_title="Journal of Chemical Sciences", ...)

Step 3: MJL Verification (only if Active/Indexed)
  Function: verify_mjl_indexing() → _direct_verify_single()
  File: scrapers/mjl.py:423
  Input: CFRJournal
  Process: _direct_post_mjl("0129-6612") → POST to MJL_API_URL
  Output: MJLVerificationResult(mjl_status="Found", mjl_index="SCIE",
          mjl_issn_used="0129-6612", mjl_match_type="Print ISSN", ...)

Step 4: SCImago Enrichment (only if Active/Indexed)
  Function: process_eligible_pair() → ScimagoScraper.scrape_journal()
  File: scrapers/scimago.py:300
  Input: normalized ISSN "01296612"
  Process:
    - search_scimago("01296612") → https://www.scimagojr.com/journalsearch.php?q=01296612
    - extract_journal_id() → e.g., "18907"
    - fetch_journal_page("18907")
    - extract_sjr() → ".hsjr" element
    - extract_quartile() → "Q2"
    - extract_h_index() → "34"
    - extract_coverage() → "1974-2026"
  Output: JournalResult(status="SUCCESS", sjr="1.2", quartile="Q2", h_index="34", ...)

Step 5: ISSN Normalization
  Function: normalize_issn()
  File: processors/issn.py:4
  Input: "0129-6612"
  Output: "01296612"

Step 6: Hash Computation
  Function: build_hash_input() → compute_data_hash()
  File: database/hash.py:46, 35
  Input: 29 fields from all 4 stages
  Process: _normalize_value each field → json.dumps(sort_keys=True) → SHA256
  Output: 64-char hex string (e.g., "a1b2c3...")

Step 7: DB Lookup
  Function: _lookup_existing("0129-6612", "0973-7754")
  File: main.py:538
  Process: normalize_issn("0129-6612") → "01296612" → journals_map["01296612"]
  Output: existing journal row or None

Step 8: Case Determination
  - If None → Case A: new → to_insert list
  - If exists, hash same → Case B: unchanged → to_touch list
  - If exists, hash different → Case C: changed → to_update list + field diffs

Step 9: Bulk Write
  Function: bulk_insert_journals() or bulk_update_journals() or bulk_touch_journals()
  File: database/repository.py:377, 364, 350
  Output: Supabase tables updated
```

---

## 23. Failure Walkthrough

### Case 1: Invalid ISSN

- `normalize_issn("")` → `"no data"`
- Scopus: `norm_p == "no data"` → skipped in lookup → "Not Indexed"
- MJL: `norm_p == "no data"` → skipped → "Unable to Verify"
- SCImago: `norm_issn == "no data"` → returns FAILED with "Empty or invalid ISSN"

### Case 2: CFR Cannot Be Accessed

- `Fetcher.get(url)` returns non-200 or exception
- Prints error, saves debug HTML, breaks loop
- Pipeline continues with partial data (or 0 journals)
- Scopus/MJL/SCImago process whatever CFR data was collected

### Case 3: Scopus Source File Unavailable

- `download_scopus_dataset()` fails
- Falls back to existing cached `scopus_source_title_list.xlsx`
- If no cached file: raises `FileNotFoundError` → **pipeline stops**

### Case 4: MJL POST Fails

- `_direct_post_mjl()` returns `None`
- Journal added to `needs_fallback` list
- If browser fallback succeeds → result used
- If browser also fails → `MJLVerificationResult(mjl_status="Unable to Verify")`

### Case 5: MJL Browser Fallback Fails

- `MJLVerifier._search_issn()` returns `None` (timeout, navigation error)
- Returns `MJLVerificationResult(mjl_status="Unable to Verify")`
- Pipeline continues

### Case 6: SCImago Cannot Find Journal

- `extract_journal_id()` returns `None`
- Returns FAILED with "No matching journal found on SCImago"
- Pipeline continues — journal gets "no data" for all SCImago fields

### Case 7: SCImago Security Challenge

- `is_challenge_page()` detects challenge indicators
- Saves debug HTML
- Returns FAILED with "Security challenge page encountered"
- Pipeline continues

### Case 8: One Extracted Field Missing

- SCImago returns `PARTIAL` status (some fields extracted, some "no data")
- Pipeline continues — partial data stored

### Case 9: Journal Already Exists in DB

- `_lookup_existing()` returns existing row
- Hash recomputed from DB values
- If hash matches → Case B: `to_touch_ids` (just update `last_checked_at`)
- No data changes, no `journal_changes` inserted

### Case 10: Journal Exists But Data Changed

- `_lookup_existing()` returns existing row
- Hash differs → Case C
- Field-level diff identifies which fields changed
- Collected in `to_update_*` lists + `all_changes` for `journal_changes`
- Bulk update writes new data + change history

### Case 11: Supabase Write Fails

- Bulk operations use `try/except` where possible
- `finish_pipeline_run` catches exceptions (line 872)
- Individual skipped record inserts catch exceptions (line 507)
- Pipeline continues — partial data may be written

---

## 24. Actual URLs

| Source | URL | Purpose | Used By |
|--------|-----|---------|---------|
| CFR | `https://cfr.annauniv.edu/research/academics/english-journals-list.php` | Journal listing | cfr_data_collection.py |
| Scopus | `https://www.elsevier.com/solutions/scopus/how-scopus-works/content/content-policy-and-selection` | Download source title list | scopus.py |
| MJL Search | `https://mjl.clarivate.com/search-results?issn={issn}` | Journal search page | mjl.py (Playwright) |
| MJL API | `https://mjl.clarivate.com/api/mjl/jprof/public/rank-search` | POST endpoint | mjl.py (direct POST) |
| MJL Home | `https://mjl.clarivate.com/search-results` | Pre-warm + Referer | mjl.py |
| SCImago Search | `https://www.scimagojr.com/journalsearch.php?q={issn}` | ISSN search | scimago.py |
| SCImago Journal | `https://www.scimagojr.com/journalsearch.php?q={journal_id}&tip=sid&clean=0` | Journal detail page | scimago.py |

---

## 25. Scraping Method Comparison

| Scraper | Access Method | Browser? | HTTP/POST? | Data Source | Special Handling |
|---------|--------------|:--------:|:----------:|-------------|------------------|
| CFR | `Fetcher.get()` | No | HTTP GET | CFR portal HTML | SSL verify=False, encoding fallback |
| Scopus | `urllib.request` + `pd.read_excel` | No | HTTP GET + local file | 19MB Excel | Force download every run |
| MJL | `_direct_post_mjl()` + `MJLVerifier` | Fallback | HTTP POST + Playwright | MJL API JSON | Hybrid, ThreadPool, lazy browser |
| SCImago | `Fetcher.get()` + `StealthySession` | Fallback | HTTP GET + browser | SCImago HTML | RLock thread safety, challenge detection |

---

## 26. Current Architecture vs Future

| Area | Current Implementation | Status |
|------|----------------------|--------|
| CFR | Scrape Anna University portal | IMPLEMENTED |
| Scopus | Local Excel verification (Elsevier source title list) | IMPLEMENTED |
| MJL | Hybrid POST + Playwright | IMPLEMENTED |
| SCImago | HTTP + StealthySession browser fallback | IMPLEMENTED |
| Database | Supabase PostgreSQL | IMPLEMENTED |
| Bulk Operations | 5 reads + ~9 writes per run | IMPLEMENTED |
| Pipeline Tracking | pipeline_runs table | IMPLEMENTED |
| Change Detection | SHA256 hash + field-level diff | IMPLEMENTED |
| CFR Dedup | ISSN-based dedup + skipped_records audit | IMPLEMENTED |
| Frontend | Separate project (Publication-AID-Frontend) | SEPARATE REPO |
| Scheduling | GitHub Actions daily cron | IMPLEMENTED |
| API | None (Supabase direct) | NOT IMPLEMENTED |
| Authentication | None (service_role key) | NOT IMPLEMENTED |
| Rate Limiting | workers=5 default | BASIC |

---

## 27. Technology Stack

| Technology | Version/Source | Purpose |
|-----------|---------------|---------|
| Python | 3.10+ | Runtime |
| Scrapling | `>=0.4.15` | HTTP fetching, HTML parsing, StealthySession |
| Playwright | (via scrapling) | Browser automation (MJL fallback, SCImago fallback) |
| pandas | `>=2.2.0` | Excel reading (Scopus source list) |
| openpyxl | `>=3.1.0` | Excel file support for pandas |
| Supabase | `>=2.9.0` | PostgreSQL client (via postgrest) |
| python-dotenv | `>=1.0.0` | .env file loading |
| hashlib | stdlib | SHA256 hashing |
| json | stdlib | Serialization |
| threading | stdlib | RLock for SCImago thread safety |
| concurrent.futures | stdlib | ThreadPoolExecutor for MJL/SCImago |
| urllib | stdlib | MJL direct POST, Scopus download |
| argparse | stdlib | CLI argument parsing |

---

## 28. Security

### Environment Variables

- `.env` contains `SUPABASE_URL` and `SUPABASE_KEY` — **gitignored**
- `.env.example` provides template without values
- `SUPABASE_SERVICE_ROLE_KEY` optionally supported

### Credentials Handling

- `load_dotenv()` loads `.env` at module import time (connection.py:5)
- Client validates both URL and key before creation (line 24)
- Never logged or printed

### Browser/Session Handling

- CFR: `verify=False` — SSL intermediate cert not verified (line 197)
- MJL: Sets `OptanonAlertBoxClosed` cookie (line 262), blocks analytics
- SCImago: `StealthySession` with `solve_cloudflare=True` (line 100), `disable_resources=True`

### No CAPTCHA Solving

- SCImago: `is_challenge_page()` detects challenges but does NOT solve them
- Returns FAILED status when challenge detected

---

## 29. How the Project Works — Simple Explanation

The project is like a research assistant that checks every journal listed by Anna University against multiple databases.

**Step 1**: Go to the Anna University website and collect the list of approved journals (about 256 journals).

**Step 2**: For each journal, check if it's indexed in Scopus (a major academic database) by comparing against an official 19MB Excel file downloaded from Elsevier.

**Step 3**: For journals that are "Active/Indexed" in Scopus, check if they're also in the Clarivate Master Journal List (Web of Science). This is done by making HTTP POST requests to Clarivate's API — if that fails, a browser is used as backup.

**Step 4**: For the same active journals, scrape SCImago (a website that ranks journals) to get metrics like SJR score, Quartile ranking (Q1-Q4), H-Index, and coverage years.

**Step 5**: Compare all this data against what's already stored in Supabase (a PostgreSQL database). Using a SHA256 hash of all 29 fields, the system detects:
- **New journals** → insert into database
- **Unchanged journals** → just update the "last checked" timestamp
- **Changed journals** → update all fields and record what changed

Everything is done in bulk (5 database reads, ~9 writes) instead of one-by-one, making the database step fast.

---

## 30. Future Developer Guide

### If You Need to Modify...

| Task | File | Function/Class | What to Modify |
|------|------|----------------|----------------|
| Change CFR URL | `config/urls.py` | `CFR_START_URL` | Update URL string |
| Change Scopus URL | `config/urls.py` | `ELSEVIER_SCOPUS_POLICY_URL` | Update URL string |
| Change MJL API | `config/urls.py` | `MJL_API_URL` | Update URL string |
| Change SCImago URL | `config/urls.py` | `SCIMAGO_SEARCH_BASE` | Update URL template |
| Add CFR field | `scrapers/cfr_data_collection.py` | `parse_cfr_table_rows()` | Add column extraction |
| Add Scopus field | `scrapers/scopus.py` | `_load_and_build_index()` | Add to record dict |
| Add MJL field | `scrapers/mjl.py` | `_parse_mjl_response()` | Extract from API response |
| Add SCImago field | `scrapers/scimago.py` | Add `extract_*()` method | CSS selector + regex |
| Change hash fields | `database/hash.py` | `build_hash_input()` | Add/remove parameters + dict keys |
| Change normalization | `database/hash.py` | `_normalize_value()` | Modify normalization logic |
| Change ISSN normalization | `processors/issn.py` | `normalize_issn()` | Modify regex/cleanup |
| Add DB table | `database/schema.sql` | Add CREATE TABLE | Schema + repository function |
| Change bulk logic | `main.py` | PHASE 1/2/3 sections | Modify classify/write logic |
| Add pipeline stage | `main.py` | `run_complete_pipeline()` | Add new stage between existing |
| Change SCImago selectors | `scrapers/scimago.py` | `extract_*()` methods | Update CSS selectors |
| Change MJL payload | `scrapers/mjl.py` | `_build_mjl_payload()` | Modify JSON structure |
| Change concurrency | `main.py` | `ThreadPoolExecutor(max_workers=workers)` | Adjust workers param |

### Impact Chains

- Changing `normalize_issn` → affects ALL stages + hash
- Changing `build_hash_input` → affects hash comparison + all change detection
- Changing `schema.sql` → affects repository.py + main.py DB section
- Changing SCImago selectors → affects extract_sjr/quartile/h_index/coverage
- Changing MJL API payload → affects _direct_post_mjl + _parse_mjl_response

---

## 31. Limitations

| Limitation | Impact | Current Mitigation |
|-----------|--------|-------------------|
| CFR SSL `verify=False` | Security warning | Required for CFR's intermediate cert |
| Scopus force download 19MB every run | ~6s overhead | Per spec (`stay force`) |
| SCImago challenges (Cloudflare) | May fail for some journals | StealthySession fallback, debug HTML saved |
| MJL API may change | Direct POST may fail | Playwright fallback |
| workers=5 default | Slower than possible | Configurable via `--workers` |
| No transaction support | Partial writes possible | Pipeline continues, logs failures |
| Sequential CFR pages | CFR could be slow (currently 1 page) | Pagination implemented |
| No retry logic | Network failures not retried | Pipeline continues with partial data |
| `scopus_issn`/`scopus_eissn` in hash but always "" | Wasted hash space | Included for future use |
| SCImago ~1s/journal | 256 journals ~250s | Threaded with workers |
| No API/rate limiting | May hit rate limits | workers=5 helps |
