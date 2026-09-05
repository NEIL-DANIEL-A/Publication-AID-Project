# Publication-AID — CFR Data Collection & Publication AID Project

An automated end-to-end Python pipeline that collects academic journal listings from the CFR Anna University portal, verifies Scopus indexing locally against the official Elsevier Source Title List, verifies Clarivate MJL (WoS) via a hybrid direct-POST + Playwright fallback, scrapes SCImago scientometrics, and persists incrementally to **Supabase PostgreSQL** as the source of truth (Excel retained only as legacy debug).

---

## 1. Project Purpose

From initial POC to current state, the project has evolved through:

1. **Single-ISSN SCImago POC** (`scrapers/scimago.py:56` `ScimagoScraper.scrape_journal`) — SJR/Quartile extraction via `Fetcher.get` + `StealthySession` fallback.
2. **Extended SCImago metrics** — H-Index (`div.cuadrado` with `<h2>H-Index</h2>` `scrapers/scimago.py:235`) and Coverage (`<h2>Coverage</h2>` `scrapers/scimago.py:265`).
3. **CFR Data Collection** (`scrapers/cfr_data_collection.py:179` `scrape_cfr_journals`) — dynamic pagination, `verify=False:194` (CFR intermediate cert), `latin-1` decode `response.body.decode:205` + `Adaptor`.
4. **ISSN Normalization** (`processors/issn.py:4` `normalize_issn`) — `[^0-9Xx]` strip, uppercases `X`, returns `"no data"` for placeholders.
5. **Scopus Verification (local)** (`scrapers/scopus.py:126` `ScopusVerifier`) — downloads `ext_list` Excel from `ELSEVIER_SCOPUS_POLICY_URL:39`, builds `issn_map:130` (~5M lookups/s), classifies `Active / Indexed | Inactive | Discontinued | Not Indexed` (`scrapers/scopus.py:189`).
6. **MJL Verification Hybrid** (`scrapers/mjl.py:38` `MJL_SEARCH_BASE ?issn=`) — primary `urllib POST https://mjl.clarivate.com/api/mjl/jprof/public/rank-search` `json={"searchValue":issn}` (`scrapers/mjl.py:175` `_direct_post_mjl`), fallback `MJLVerifier:212` Playwright intercept `rank-search:288`, extracts `SCIE/SSCI/AHCI/ESCI` via `products[].productCode` + description (`scrapers/mjl.py:68`).
7. **Supabase Migration & Incremental Update** (`database/schema.sql:1`, `database/repository.py:31`, `database/hash.py:1`, `main.py:212` `run_complete_pipeline`) — `Supabase PostgreSQL` source of truth, `SHA256` deterministic hash, `new`/`updated`/`unchanged`/`failed` + `journal_changes` history + `skipped_records` audit for CFR duplicate ISSN.

Final pipeline per `main.py:232`:
```text
CFR Portal (https://cfr.annauniv.edu/research/academics/english-journals-list.php)
  → CFR Scraper (257 rows, 1 page, deduplicated 257->256 by ISSN)
  → ISSN Normalization (Print -> E fallback)
  → Scopus Verification (local 48,888 rec, 422 Active / 6 Inactive / 3 Discontinued / 3 Not Indexed)
  → MJL Hybrid (422 Active, direct POST ThreadPool 5 workers ~25s, 324 Found / 98 Not Found)
  → SCImago (422 Active, Fetcher->Stealth RLock, ThreadPool 5 workers ~114s, 422 SUCCESS)
  → Normalize Results (26 cols)
  → Build SHA256 (sorted JSON, & vs AND normalized)
  → Compare With Supabase (bulk get_all_journals_map 1 query)
  → INSERT (new) | UPDATE + journal_changes (changed) | DO NOTHING (unchanged) | skipped_records (CFR duplicate ISSN)
```

Supabase is **source of truth** (`database/schema.sql:9` `journals`); Excel `output/cfr_scopus_mjl_scimago_results.xlsx:452` is legacy (`output/*` ignored `.gitignore:37`).

---

## 2. Implemented Features (Exact)

### CFR Data Collection `scrapers/cfr_data_collection.py:1`
- `START_URL:25` `https://cfr.annauniv.edu/research/academics/english-journals-list.php`
- `scrape_cfr_journals(start_url):179` loops `visited_urls:186` `while current_url not in visited`, `Fetcher.get(verify=False):194`, decodes `response.body` via `utf-8 -> latin-1 -> cp1252` fallback `205`, `Adaptor(decoded_html):213`, `parse_cfr_table_rows:89` finds table with `SL`/`TITLE`/`ISSN` headers, maps `sl_no/title/print_issn/e_issn/publisher/country` via `header_col_indices:118`, `clean_cell_text:41` (`\xa0` -> space, `\s+` -> ` `).
- `find_next_page_url:52` checks `a[rel="next"]:60`, text `next/>/»` `66`, `aria-label`, `class next` `83`, `urljoin`.
- Current live CFR: 1 page, 257 rows, 2 duplicate titles (`folklore`, `logos (russian federation)` `report_duplicates:181`), 0 duplicate Print/E-ISSN separately but 1 cross duplicate `2572-3618` (sl_no 124 `EAST AND WEST` print vs 151 `EAST & WEST` e_issn) deduplicated to 256.
- `report_duplicates:181` counts `collections.Counter` titles/print/e separately, does not delete.
- `save_cfr_debug_html:29` dumps to `output/debug/` on 0 rows or exception.

### ISSN Processing `processors/issn.py:4`
- `normalize_issn(issn: str) -> str:4` strips `[^0-9Xx]` `re.sub:20` `.upper()`, returns `"no data"` for `None/""/"none"/"no data"/"nan"/"null"/"-"/"nil"/"na"/"n/a":17`.

### Scopus Verification `scrapers/scopus.py:1`
- `COL_SOURCERECORD_ID:19` ... `REQUIRED_COLUMNS:28`, `ELSEVIER_SCOPUS_POLICY_URL:39`.
- `download_scopus_dataset(dest_path):42` deletes old `50`, `urllib.request` `ELSEVIER_SCOPUS_POLICY_URL:58`, `Adaptor` finds `a` href with `ext_list/source_title/scopus_source` + `.xlsx`/`ctfassets` `71`, builds absolute URL `77`, regex fallback `80`, downloads `94` to `dest_path` `19.02 MB`, `force_redownload=True:127` per user `stay force`.
- `ensure_scopus_dataset:110` `force or not exists` -> `download`.
- `ScopusVerifier:126` `__init__(excel_path, force_redownload=True)` `issn_map:130` `load_time:165` `construction_time:223`.
- `_validate_source_file:136` checks `Scopus Sources*` sheet.
- `_load_and_build_index:155` `pd.ExcelFile:161` `read_excel:164` `74,473` ISSN entries, `normalize_issn:183`, `scopus_status:189` logic, `record dict:200` (`sourcerecord_id, source_title, scopus_issn/eissn, publisher, coverage, raw flags, scopus_status`), `issn_map[norm_p]=record:215` and `issn_map[norm_e]` if not already present.
- `verify_journal:226` `norm_p` -> `issn_map[Print]` else `norm_e` -> `E-ISSN` else `Not Indexed:256`, returns `ScopusVerificationResult:242` (`scopus_status, match_type: Print ISSN/E-ISSN/No Match, sourcerecord_id, source_title, ...`).
- `verify_scopus_indexing:262` loops journals, `stats:280` `active_indexed, inactive, discontinued, not_indexed, unable_to_verify`, `verification_time:276` `~0.0016s/434`.
- **Not changed per spec:** local lookup only, no `scopus.com` scraping.

### MJL Verification Hybrid `scrapers/mjl.py:1`
- `MJL_SEARCH_BASE:38` `https://mjl.clarivate.com/search-results?issn={issn}` varying ISSN exactly varies search (e.g., `2632-2153` tested `MACHINE LEARNING-SCIENCE AND TECHNOLOGY`).
- `MJL_API_URL:39` `POST https://mjl.clarivate.com/api/mjl/jprof/public/rank-search`.
- `_CORE_COLLECTION_CODES:48` `D->SCIE, E->SSCI, C/H->AHCI, F->ESCI` + `_PRODUCT_CODE_DESCRIPTIONS:56` `BA/BP/B7/CR/I/ES/JS/JH`.
- `_extract_wos_indexes:68` description substring `Science Citation Index Expanded`->`SCIE` etc. before code, returns `", ".join(sorted(set(core)))` else other else `"no data"`.
- `_parse_mjl_response:101` `journalProfiles`/`totalRecords`, exact ISSN match `normalize_issn:122` else `total==1 -> Single Result` else `Not Found:146`.
- `_build_mjl_payload:109` `{"searchValue":issn,"pageNum":1,"pageSize":10,"sortOrder":[{"name":"RELEVANCE","order":"DESC"}],"filters":[...PRODUCT_CODE...],"searchIdentifier":uuid4}`.
- `_direct_post_mjl:175` `urllib.request.Request POST` `MJL_API_URL` headers `Referer: .../search-results`, `X-1P-AppId: mjl`, `Authorization: Bearer`, `Accept: application/json` `141`, timeout `10`, validates `json.loads`, returns raw JSON or `None`.
- `MJLVerifier:212` `headless, verbose`, `_start:238` `sync_playwright` `chromium --no-sandbox`, `OptanonAlertBoxClosed` cookie, `route abort` tracking, `goto /search-results:267` pre-warm 4s, `_search_issn:278` `page.goto(MJL_SEARCH_BASE)` wait 3s, `on_response` capture `rank-search:288`.
- `verify_journal:324` helper `_try_issn` tries direct POST first (`0.4s`), logs `Direct POST`, on `None` lazy `self._start()` then browser fallback, `Print -> E` fallback `324/360`, returns `MJLVerificationResult` (`Found`/`Not Found`/`Unable to Verify`, `mjl_index`, `mjl_issn_used` formatted `XXXX-XXXX`, `mjl_match_type`).
- `verify_mjl_indexing:393` hybrid threaded: Phase1 `ThreadPoolExecutor(max_workers=5):425` ` _direct_verify_single` for all 422 Active (~0.16s/journal, `0.79s/5` measured, `249 resolved, 0 fallback` in last run `30.73s`), Phase2 browser fallback only for `needs_fallback` (0 in last run). Prints `[MJL 1/422] ... | [OK] Found | Index: AHCI (direct)`.
- **Status preservation per spec:** `Found` vs `Not Found` vs `Unable to Verify` vs `skipped` for non-Active.

### SCImago Scraping `scrapers/scimago.py:1`
- `SEARCH_BASE_URL:17` `https://www.scimagojr.com/journalsearch.php?q={issn}`, `JOURNAL_BASE_URL:18` `?q={journal_id}&tip=sid&clean=0`.
- `is_challenge_page:22` `just a moment/turnstile/...`.
- `ScimagoScraper:56` `headless, verbose, _stealth_session:60, _stealth_lock:59` `threading.RLock` for `ThreadPool` sharing (`main.py:357` `max_workers=5`).
- `_get_stealth_session:89` `with _stealth_lock` lazy `StealthySession(headless, max_pages=5, disable_resources, page_setup, timeout=10000, retries=2, solve_cloudflare):93`.
- `fetch_url:118` `Fetcher.get(url)` if `200` and not challenge else `with _stealth_lock: session.fetch`, similarly on exception.
- `search_scimago:137`, `extract_journal_id:143` `a[href*=journalsearch.php][tip=sid]` parse `q` `isdigit` else regex `journalsearch.php\?q=(\d+)`, `fetch_journal_page:171`.
- `extract_sjr:179` `.hsjr` regex, `extract_quartile:200` `Q[1-4]` in `span` class/text, `extract_h_index:235` `h2 H-Index` parent `.hindexnumber`, `extract_coverage:265` `h2 Coverage` ` .cuadrado-detail` regex `\d{4}...`.
- `scrape_journal:295` `normalize_issn:302` `no data` check, `search_response:327` `HTTP !=200` -> `FAILED`, `journal_id` `None` -> `FAILED`, `is_challenge_page:375` -> `FAILED`, extract 4 metrics `395`, `all -> SUCCESS:429`, `any -> PARTIAL:432`, `none -> FAILED:435`, `execution_time:439` `perf_counter`.
- `scrape_journals_batch:474` alternative threaded but pipeline uses custom `process_eligible_pair:351` in `main.py:357` sharing `ScimagoScraper` via `RLock`.
- `main.py:351` `process_eligible_pair` `Print -> E` fallback `322` like MJL.

### Database Layer `database/`

**`connection.py:1`** `load_dotenv()`, `get_supabase_client():7` singleton `create_client(url,key)` validates `SUPABASE_URL` + `SUPABASE_KEY`/`SUPABASE_SERVICE_ROLE_KEY`, raises `RuntimeError` if missing, `is_supabase_configured():20` bool check.

**`hash.py:1`** `build_hash_input:37` merges `title, print_issn, e_issn, publisher, country, scopus_*, mjl_*, scimago_*` 22 fields; `_normalize_value:5` `None`/`no data`/empty -> `""`, `lower`, `replace("&"," and ")`, `re.sub(r"\s+")` collapse, `:` and `,` spacing; `compute_data_hash:26` `json.dumps(sort_keys, separators)` -> `SHA256 hexdigest 64`. Test 5 whitespace/casing/`&` vs `AND` same hash.

**`models.py:1`** `JournalRow:2` (id, title, print/e, normalized, publisher, country, data_hash, timestamps, pipeline_run_id).

**`repository.py:1`** `get_journal_by_issn:31` cross `normalized_print`/`normalized_e` lookup (both unique), `get_journal:60`, `get_all_journals_map:66` bulk `SELECT id, normalized_print/e, data_hash` `1 query` vs `500+` before, `get_all_journals_raw:80`, `insert_journal_full:66` sequential `journals` -> `cfr_results` -> `scopus` -> `mjl` -> `scimago`, `update_journal_full:116` `UPDATE` + `record_change`, `touch_journal_checked:178`, `create_pipeline_run:190` `started_at now() status running`, `finish_pipeline_run:200` `finished_at, duration, total_*, new/updated/unchanged/failed/duplicate_skipped` (handles missing column), `record_change:222`, `get_existing_full:234` `5` selects, `insert_skipped_record:252`, `get_skipped_records`.

**`schema.sql:1`** `pgcrypto` + 7 tables:
- `journals:10` `id UUID PK`, `title, print_issn, e_issn, normalized_print/e, publisher, country, data_hash, created_at, updated_at, first_seen_at, last_checked_at, last_changed_at, last_seen_pipeline_run_id FK`; `UNIQUE INDEX` on `normalized_print/e` where `<> 'no data'` `29`, `data_hash/title/last_checked` indexes, `update_updated_at` trigger `36`.
- `cfr_results:46` `journal_id FK CASCADE` `UNIQUE(journal_id)` `sl_no, journal_title, ...`
- `scopus_results:65` `journal_id PK FK` `scopus_status, match_type, sourcerecord_id, source_title, ...`
- `mjl_results:86` `mjl_status, mjl_index, mjl_issn_used, mjl_match_type, source_title, execution_time, error`
- `scimago_results:104` `scimago_status, journal_id_external, matched_issn, sjr, quartile, h_index, coverage, url, execution_time, error`
- `pipeline_runs:126` `started_at, finished_at, duration_seconds, status, total_cfr, total_scopus_active, total_mjl_processed, total_scimago_processed, new/updated/unchanged/failed, duplicate_skipped` `193`.
- `journal_changes:148` `journal_id FK, pipeline_run_id FK, source, field_name, old_value, new_value, changed_at`
- `skipped_records:166` `pipeline_run_id FK, sl_no, journal_title, print_issn, e_issn, normalized_*, publisher, country, reason=duplicate_issn, duplicate_of_issn/title, skipped_at` + indexes `182`.

---

## 3. Pipeline Orchestrator `main.py:1`

**Imports:** `argparse, collections, json, os, sys, time, pandas`, `CFRJournal, JournalResult`, `normalize_issn`, `scrape_cfr_journals`, `ScimagoScraper`, optional `database` `DB_AVAILABLE` `try:9` `is_supabase_configured`.

**Functions:**
- `print_single_result:41`, `run_single_issn:62` `ScimagoScraper(verbose=True)` -> `output/result.json:72`, `run_excel_batch:79` `ISSN` column case-insensitive `70`, `report_duplicates:181` titles/print/e counts, `run_source_only:196` `output/cfr_journals.xlsx:220` 6 cols.

**`run_complete_pipeline:232` (4 stages):**
1. **CFR:** `scrape_cfr_journals:248` `0.18s` `257` raw -> `report_duplicates:251` `2 duplicate titles` -> deduplicate by `ISSN` only (`seen_issns:255` dict `normalized_print/e`, `any(n in seen): duplicate` -> `cfr_skipped_details:258` with `sl_no 151 EAST & WEST` kept `124 EAST AND WEST` `257->256` `skipped 1` `print [SKIPPED]` `265`).
2. **Scopus:** `verify_scopus_indexing:296` `force_redownload=True` `19.02MB` `5.86s load +3.11s build +0.0016s verify`, `Scopus total 434` was bug `257->434` double-append (fixed `main.py:261` dedent `deduped.append` outside `for n in norms`), now correctly `256` unique ISSN -> `422 Active / 6 Inactive / 3 Discontinued / 3 Not Indexed`.
3. **MJL:** `eligible_pairs = Active:316` `422` `verify_mjl_indexing:323` hybrid `direct POST:425` `5 workers` `30.73s` `324 Found / 98 Not Found` (last run `249 resolved, 0 fallback`).
4. **SCImago:** `process_eligible_pair:351` `Fetcher->Stealth RLock` `ThreadPool 5:447` `422` `114.20s` `422 SUCCESS` `0 Failed`.

**DB Persistence `503` (Supabase source of truth):**
- `use_db = DB_AVAILABLE and is_supabase_configured():506` else `Excel only`.
- `create_pipeline_run:513` `total_cfr=len(journals)` (256 after dedup).
- Persist `cfr_skipped_details` to `skipped_records:518` `insert_skipped_record:525` `print [SKIPPED-DB]`.
- Bulk `get_all_journals_map:545` `1 query` `0.27s` for `256` journals (`434 ISSN keys`), `def _lookup_existing:549` in-memory.
- Loop `results:564` (`256` eligible+skipped) `build_hash_input:570` `compute_data_hash:597` `22 fields` `SHA256`, `_lookup_existing:624`:
  - `None` -> `Case A new` `insert_journal_full:627` `new_records++` + add to `journals_map`.
  - `old_hash==new_hash` -> `Case B unchanged` `touch_journal_checked:641` `unchanged++`.
  - `old_hash!=new_hash` -> `Case C changed` `get_existing_full:647` `5` selects, `_normalize_value:629` diff per `journal/publisher/country`, `scopus_status/source_title`, `mjl_status/index/source_title`, `sjr/quartile/h_index/coverage/scimago_status` -> `update_journal_full:672` + `record_change` `updated++` (last run `0 new | 0 updated | 256 unchanged` after dedup fix, previously `434 unchanged` due to bug).
- `DB persistence complete: X new | Y updated | Z unchanged in 62.19s:719` (bulk `0.27s` + per-journal upserts `60s` for 256).
- `finish_pipeline_run:724` `duration` `total_*` stats.
- Fallback `Excel` `output/cfr_scopus_mjl_scimago_results.xlsx:744` legacy.

**Timing:** `cfr_duration:249`, `scopus_init_time:298`, `mjl_duration:325`, `scimago_duration:470`, `db_duration:718`, `total_pipeline_time:739` `224.10s (3.73min)` last run.

**CLI `main:794`:** `--source-only`, `--scimago-only --issn 01296612`, `--scopus-file`, `--issn`, `--input`, `--workers 5` `default 5`.

---

## 4. Architecture & Directory Structure

```text
Publication-AID-Project/
├── main.py                     # CLI + 4-stage orchestrator (820 lines)
├── models.py                   # CFRJournal:6, ScopusVerificationResult:18, MJLVerificationResult:36, JournalResult:48
├── database/
│   ├── __init__.py             # re-exports get_supabase_client etc.
│   ├── connection.py           # load_dotenv, get_supabase_client singleton, is_supabase_configured
│   ├── hash.py                 # _normalize_value, build_hash_input, compute_data_hash SHA256
│   ├── models.py               # JournalRow dataclass
│   ├── repository.py           # get_journal_by_issn, get_all_journals_map, insert/update, pipeline_runs, skipped_records
│   └── schema.sql              # 7 tables + indexes + triggers (198 lines)
├── scrapers/
│   ├── __init__.py             # re-exports scrape_cfr_journals, ScimagoScraper, ScopusVerifier, MJLVerifier
│   ├── cfr_data_collection.py  # CFR_URL:25, scrape_cfr_journals:179, find_next_page_url:52, parse_cfr_table_rows:89, clean_cell_text:41
│   ├── scopus.py               # ScopusVerifier:126, download_scopus_dataset:42, verify_scopus_indexing:262, COL_*:19
│   ├── mjl.py                  # MJL_SEARCH_BASE:38 ?issn=, _direct_post_mjl:175 urllib POST, MJLVerifier:212 Playwright, verify_mjl_indexing:393 hybrid, _extract_wos_indexes:68
│   └── scimago.py              # ScimagoScraper:56, SEARCH_BASE_URL:17, extract_sjr:179, quartile:200, h_index:235, coverage:265, RLock:59
├── processors/
│   ├── __init__.py             # re-exports normalize_issn
│   └── issn.py                 # normalize_issn:4 re [^0-9Xx]
├── tests/
│   ├── __init__.py
│   ├── test_hash.py            # 5 tests deterministic, whitespace, None vs empty, ISSN formatting, changed field
│   ├── test_change_detection.py # 5 scenarios A-E (new, unchanged, single change, multi, normalization)
│   └── test_repository_mock.py # 3 tests ISSN logic, import, hash integration
├── output/
│   ├── cfr_journals.xlsx       # Mode A 6 cols
│   ├── cfr_scopus_mjl_scimago_results.xlsx # Mode B 26 cols legacy
│   ├── scopus_source_title_list.xlsx # 19MB downloaded (ignored)
│   ├── .gitkeep / debug/.gitkeep
│   └── debug/                  # HTML dumps (ignored)
├── data/                       # ignored
├── .venv/                      # ignored
├── __pycache__/                # ignored
├── .env                        # ignored, created from .env.example
├── .env.example                # SUPABASE_URL=, SUPABASE_KEY=
├── .gitignore                  # .env, .venv, __pycache__, output/*, data/, *.log (46 lines, output/* + !output/.gitkeep handling)
├── requirements.txt            # scrapling[all]>=0.4.15, pandas>=2.2.0, openpyxl>=3.1.0, supabase>=2.9.0, python-dotenv>=1.0.0
└── README.md                   # this file
```

---

## 5. Setup

**Prerequisites:** `Python 3.10+` Windows, `.venv`, `supabase` project.

```powershell
# 1. Activate venv
.\.venv\Scripts\activate

# 2. Install deps
pip install -r requirements.txt

# 3. Browser engines (one-time)
scrapling install
playwright install chromium

# 4. Supabase (source of truth)
# Create project at https://supabase.com
# In Supabase SQL Editor, run database/schema.sql (single execution, 7 tables)
copy .env.example .env
# Edit .env:
# SUPABASE_URL=https://<project>.supabase.co
# SUPABASE_KEY=<service_role> # or anon if RLS disabled for tables
# Verify
.\.venv\Scripts\python -c "from database.connection import get_supabase_client; print(get_supabase_client().table('journals').select('id').limit(1).execute())"
# Should print {'data': []} not RuntimeError
```

**Without Supabase:** Pipeline gracefully skips DB `is_supabase_configured():506` `False` -> `[INFO] Supabase not configured - skipping DB, using Excel only` `637`, Excel remains.

---

## 6. How to Run

**Mode A - Source-Only:**
```powershell
python main.py --source-only
# output/cfr_journals.xlsx 6 cols, ~0.18s
```

**Mode B - Complete (CFR->Scopus->MJL->SCImago->Supabase) [DEFAULT]:**
```powershell
python main.py
# Options: --workers 5 (default 5) --scopus-file output/scopus_source_title_list.xlsx
```
Output terminal:
```text
[INFO] CFR deduplicated: 257 -> 256 (skipped 1 duplicate ISSN)
[SKIPPED] CFR duplicate ISSN 25723618 -> sl_no 151 'EAST & WEST' (kept 'EAST AND WEST')
...
Database (Supabase)       : 0 new | 0 updated | 256 unchanged | 0 failed | 1 CFR duplicate ISSN skipped
  DB time                 : 62.19 sec
...
[SUCCESS] Pipeline run 49ac490f... persisted to Supabase
[SUCCESS] Consolidated results saved to output/cfr_scopus_mjl_scimago_results.xlsx (legacy)
```
Supabase: `SELECT * FROM journals` `256` rows, `SELECT * FROM skipped_records WHERE pipeline_run_id=...` shows `151`, `SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1` shows `new/updated/unchanged`.

**Mode C - Single ISSN:**
```powershell
python main.py --scimago-only --issn 01296612
# or 2632-2153
# output/result.json
```

**Mode D - Batch Excel:**
```powershell
python main.py --input test_input.xlsx
# expects ISSN column, output/scimago_results.xlsx
```

**Tests (mocked, no Supabase):**
```powershell
.\.venv\Scripts\python -m pytest tests -v
# 13 passed: test_hash 5, test_change_detection 5 scenarios, test_repository_mock 3
```

---

## 7. Database Schema (Exact)

`journals` master `id UUID PK`, `title, print_issn, e_issn, normalized_print/e, publisher, country, data_hash, created_at, updated_at, first_seen_at, last_checked_at, last_changed_at, last_seen_pipeline_run_id FK`. Unique partial indexes on `normalized_print/e` where `<> 'no data'`.

`cfr_results` one-to-one `journal_id FK CASCADE` `UNIQUE(journal_id)` `sl_no, journal_title, print_issn, e_issn, publisher, country`.

`scopus_results` `journal_id PK FK` `scopus_status, match_type, sourcerecord_id, source_title, scopus_publisher, scopus_coverage, scopus_issn/eissn, raw flags`.

`mjl_results` `journal_id PK FK` `mjl_status, mjl_index, mjl_issn_used, mjl_match_type, source_title, execution_time, error`.

`scimago_results` `journal_id PK FK` `scimago_status, journal_id_external, matched_issn, sjr, quartile, h_index, coverage, url, execution_time, error`.

`pipeline_runs` `id, started_at, finished_at, duration_seconds, status running|success|failed, total_cfr, total_scopus_active, total_mjl_processed, total_scimago_processed, new/updated/unchanged/failed, duplicate_skipped, error`.

`journal_changes` `id, journal_id FK, pipeline_run_id FK, source, field_name, old_value, new_value, changed_at`.

`skipped_records` `id, pipeline_run_id FK, sl_no, journal_title, print_issn, e_issn, normalized_*, publisher, country, reason=duplicate_issn, duplicate_of_issn/title, skipped_at`.

Indexes on `data_hash, title, last_checked, journal_id, pipeline_run_id, source, print/e`.

---

## 8. Incremental Logic & Hash

**Hash `database/hash.py:1`:** `build_hash_input` 22 fields -> `_normalize_value` (`None/"no data"/""` -> `""`, `lower`, `&` -> ` and `, collapse whitespace) -> `json.dumps(sort_keys)` -> `SHA256`. `EAST & WEST` vs `EAST AND WEST` same hash.

**Cases `main.py:573`:**
- `A new` `get_journal_by_issn == None` -> `insert_journal_full` `new++`, add to `journals_map`.
- `B unchanged` `old_hash == new_hash` -> `touch_journal_checked` `unchanged++`, no `journal_changes`.
- `C changed` `old_hash != new_hash` -> `get_existing_full` `5` selects, `_normalize_value` diff per `journal/publisher/country`, `scopus_status/source_title`, `mjl_status/index/source_title`, `sjr/quartile/h_index/coverage/scimago_status` -> `update_journal_full` + `record_change` per field `updated++`.

**Bulk `get_all_journals_map:66`:** `1 query` `SELECT id, normalized_print/e, data_hash` -> dict `ISSN -> row` for `O(1)` lookup vs `500+` per-journal queries before. Progress `[DB 1/256]` every 50 + `[UPDATED]` per changed.

**Deduplication `main.py:252`:** `CFR` `257 -> 256` by `ISSN` only (both `print`/`e` cross), keeps duplicate titles (`folklore` etc.), logs `[SKIPPED] CFR duplicate ISSN 25723618` and persists to `skipped_records` for audit.

---

## 9. Execution Timing (Preserved `time.perf_counter`)

- `cfr_duration:249` `0.18s`
- `scopus_init:298` `5.86s load +3.11s build` `verification:299` `0.0016s`
- `mjl_duration:325` `30.73s` (direct POST `249 resolved, 0 fallback`)
- `scimago_duration:470` `114.20s` (`422` `ThreadPool 5`)
- `db_duration:718` `62.19s` (bulk `0.27s` + per-journal upserts)
- `total_pipeline_time:739` `224.10s (3.73min)` last run `434 unchanged` was bug double-count `257->434` (fixed `main.py:261` dedent `deduped.append` outside `for n in norms`).

---

## 10. Known Limitations

- `verify=False:194` CFR SSL intermediate missing.
- `force_redownload=True:127` Scopus download every run (19MB, 8s) per `stay force`.
- Concurrency `workers=5` default `main.py:232` - increase risks `429`/`403`.
- `MJL` direct POST `searchIdentifier:uuid4` may need update if Clarivate changes `filters`; fallback ensures.
- `Supabase` `RLS` requires `service_role` or disabled for tables.
- `output/*` ignored, legacy Excel still written.

---

## 11. Tests

`tests/test_hash.py` 5 tests, `tests/test_change_detection.py` 5 scenarios `A new` `B unchanged` `C single field` `D multi` `E normalization` via `MockDB` in-memory, `tests/test_repository_mock.py` 3 tests, `pytest 9.1.1` `13 passed`.

---

## 12. Definition of Done (Implemented)

- [x] Supabase connect `database/connection.py:7`
- [x] Schema `database/schema.sql:1` 7 tables
- [x] CFR/Scopus/MJL/SCImago stored
- [x] Pipeline runs tracked
- [x] New/unchanged/changed + `journal_changes`
- [x] `SHA256` `database/hash.py:26`
- [x] ISSN `processors/issn.py:4` preserved
- [x] Scraper logic intact, no `scopus.com` scraping, MJL `POST` + fallback preserved
- [x] Timing preserved `main.py:739`
- [x] Excel legacy, `Supabase` primary
- [x] `.env` protected `.gitignore:24` `.env.example` exists
- [x] Tests `tests/` 13 passed
- [x] Vertical slice `CFR->Supabase` verified `0 new | 0 updated | 256 unchanged` after dedup fix (previously `434` bug)
