# AGENT HANDOFF

> **Date**: 2026-09-04 | **Project**: POC-Scimago | **Location**: `c:\Users\neil-\Projects\POC-Scimago`

---

## 1. TL;DR

**What this project is**: A Python scraping pipeline that:
1. Collects all journal records from the CFR Anna University portal.
2. Normalizes Print-ISSNs and E-ISSNs.
3. Queries SCImago for journal scientometrics (SJR, Quartile, H-Index, Coverage) per ISSN.
4. Exports a combined Excel workbook.

**What we are trying to achieve**: Automate ISSN-based journal enrichment from CFR to SCImago for research publication analysis. This is a **Proof of Concept** only — the full APC/master-Excel integration system has NOT been started.

**Current status**: The core pipeline is **fully implemented and tested**. All 4 run modes work. A complete run against the live CFR site returned 257/257 journals enriched successfully.

**Immediate next task**: **None defined yet.** The user will specify the next increment. No current blockers. Do NOT start any new feature without explicit user instruction.

---

## 2. Project Overview

### Purpose
POC to prove CFR → ISSN normalization → SCImago metric extraction pipeline is reliable and fast enough for production use.

### Tech Stack
- **Language**: Python 3.10+ (Windows)
- **Scraping**: [`scrapling`](https://github.com/D4Vinci/Scrapling) ≥0.4.15 with `[all]` extras (Playwright included)
- **Excel I/O**: `pandas` ≥2.2.0 + `openpyxl` ≥3.1.0
- **HTTP Engine**: `scrapling.fetchers.Fetcher` (curl-cffi based, fast, TLS fingerprinting)
- **Stealth Fallback**: `scrapling.fetchers.StealthySession` (Playwright browser, only used when Cloudflare challenge is detected)
- **Virtual environment**: `.venv` at project root; activate with `.\.venv\Scripts\activate`

### Architecture
```
main.py                         # CLI orchestrator
├── run_source_only()           # Mode A: CFR only
├── run_complete_pipeline()     # Mode B: CFR + SCImago (default)
├── run_single_issn()           # Mode C: SCImago-only (single ISSN test)
└── run_excel_batch()           # Mode D: Batch ISSN from Excel

scrapers/cfr_data_collection.py # Scrapes CFR portal (stateless, no SCImago knowledge)
scrapers/scimago.py             # Resolves single ISSN via SCImago (no CFR knowledge)
processors/issn.py              # ISSN normalization (pure function, no I/O)
models.py                       # CFRJournal + JournalResult dataclasses
```

### Important Directories
- `output/` — all generated files (created automatically; NEVER commit)
- `output/debug/` — diagnostic HTML files, saved only when scraping fails
- `scrapers/` — all scraper modules
- `processors/` — data transformation functions
- `.venv/` — virtual environment (DO NOT touch)

---

## 3. Current Implementation

### CFR Data Collection (`scrapers/cfr_data_collection.py`)
- **Status**: COMPLETE
- **Main function**: `scrape_cfr_journals(start_url=START_URL) → (List[CFRJournal], int)`
- **URL**: `https://cfr.annauniv.edu/research/academics/english-journals-list.php`
- **Current behavior**: Single page, 257 rows. All 257 extracted correctly.
- **Pagination**: Fully implemented dynamic discovery via `find_next_page_url()` — inspects `rel="next"`, text anchors (`next`, `>`, `»`), aria-labels, CSS classes. The CFR English list is currently a single page, but the scraper handles multi-page sites correctly if CFR ever paginates.
- **SSL**: Uses `verify=False` because CFR's server has an incomplete certificate chain (not recognized by Windows OpenSSL). This is expected and intentional.
- **Encoding**: Response body decoded via `latin-1` (CFR sends bytes with `\xa0` non-breaking spaces that are NOT valid UTF-8 despite claiming UTF-8). The `Adaptor(decoded_html)` parses the resulting string.
- **Deduplication**: Reports duplicate titles, Print-ISSNs, E-ISSNs to terminal. Does NOT silently delete records — all duplicates are preserved in output.

### ISSN Normalization (`processors/issn.py`)
- **Status**: COMPLETE
- **Function**: `normalize_issn(issn: str) → str`
- Strips everything except digits and `X`/`x` (the ISSN check character). Uppercases. Returns `"no data"` for empty/invalid/placeholder values (`"none"`, `"nan"`, `"null"`, `"-"`, `"nil"`, `"na"`, `"n/a"`).
- Original CFR ISSN values are preserved verbatim in output. Normalized values are used ONLY for SCImago URL queries.

### SCImago Scraper (`scrapers/scimago.py`)
- **Status**: COMPLETE. This is a copy of the original `scimago_scraper.py` with two changes:
  - `DEBUG_DIR` path fixed to `os.path.dirname(os.path.dirname(__file__))` so it points to project root `output/debug/` (not `scrapers/output/debug/`).
  - `normalize_issn` removed from this file; now imported from `processors.issn`.
- **Class**: `ScimagoScraper(headless=True, verbose=True)` — context manager.
- **Method**: `scraper.scrape_journal(issn_input: str) → JournalResult`
- **Two-step process**:
  1. Fetches `https://www.scimagojr.com/journalsearch.php?q={issn}` → extracts journal ID from href param `q` with `tip=sid`.
  2. Fetches `https://www.scimagojr.com/journalsearch.php?q={journal_id}&tip=sid&clean=0` → extracts SJR, Quartile, H-Index, Coverage.
- **HTTP strategy**: Fast `Fetcher.get()` first. Falls back to `StealthySession` (Playwright) only if Cloudflare challenge is detected or non-200 response.
- **`verbose=False`** in batch/pipeline mode (clean 1-liner per ISSN). **`verbose=True`** in single-ISSN mode (full diagnostic output).
- **Status values**: `SUCCESS` (all 4 metrics), `PARTIAL` (some metrics), `FAILED` (none or fatal error).
- **Fallback values**: `"no data"` string (NOT `None`, NOT empty string).

### Original `scimago_scraper.py` (project root)
- **Status**: STILL EXISTS and is still used by `--input` (batch Excel) mode and old references.
- **Note**: This is a deliberate leftover. The user did NOT ask to delete it. `main.py` imports `ScimagoScraper` from `scrapers.scimago` for pipeline modes, and from `scimago_scraper` for `run_excel_batch()` — WAIT, actually check: `main.py` imports `from scrapers.scimago import ScimagoScraper` at the top for ALL modes. The root `scimago_scraper.py` is now unused by main.py but is still present.

### Pipeline Orchestrator (`main.py`)
- **Status**: COMPLETE
- **Imports**: `from scrapers.scimago import ScimagoScraper`, `from scrapers.cfr_data_collection import scrape_cfr_journals`, `from processors.issn import normalize_issn`
- **Key function**: `run_complete_pipeline()` — orchestrates CFR collection → ISSN normalization → SCImago loop with Print→E-ISSN fallback → Excel export
- **Fallback logic** (inside loop):
  1. `normalize_issn(print_issn)` → query SCImago
  2. If SUCCESS/PARTIAL → store, record `matched_issn = print_issn`
  3. Else if `norm_e != "no data"` → query E-ISSN
  4. If E-ISSN succeeds → store, record `matched_issn = e_issn`
  5. If both fail → `status = "not found"`, all SCImago fields = `"no data"`
- **Output path**: `output/cfr_scimago_results.xlsx` (fallback: `output/cfr_scimago_results_latest.xlsx` on PermissionError)
- **Timing**: `time.perf_counter()` for CFR collection duration, per-journal time (stored in `Processing Time (sec)` column), and total pipeline wall-clock time.

### Data Models (`models.py`)
- **Status**: COMPLETE
```python
@dataclass
class CFRJournal:        # sl_no, journal_title, print_issn, e_issn, publisher, country
class JournalResult:     # issn, journal_id, sjr, quartile, h_index, coverage, search_url, journal_url, status, error, execution_time
```

---

## 4. What We Have Already Done

1. **Initial POC**: Built single-ISSN SCImago scraper using `Fetcher.get()` with Playwright fallback. Extracts SJR, Quartile.
2. **Extended extraction**: Added H-Index (from `<div class="cuadrado">` containing `<h2>H-Index</h2>` → `.hindexnumber`) and Coverage (from `<h2>Coverage</h2>` → `.cuadrado-detail`).
3. **Batch Excel mode**: `--input` flag reads Excel with `ISSN` column (case-insensitive), scrapes all, writes `output/scimago_results.xlsx`.
4. **Execution timing**: `time.perf_counter()` per ISSN and overall batch. `execution_time: float` field on `JournalResult`.
5. **Terminal formatting fix**: Silenced Scrapling internal fetch logger via `scrapling_log.setLevel(logging.WARNING)` (logger is a `LoggerProxy` wrapping `scrapling_logger`). Batch mode prints clean 1-liners; single mode prints full diagnostic card.
6. **Fixed `Total Time` duplicate label**: Was printing two lines with identical `Total Time` label (one seconds, one minutes). Now merged to single: `Total Batch Time: X.XX seconds (X.XX minutes)`.
7. **CFR collection module**: `scrapers/cfr_data_collection.py` — dynamic pagination, latin-1 encoding fix, `verify=False`, cell text cleaning (`\xa0` → space).
8. **Module restructure**: Created `scrapers/` and `processors/` packages. Moved SCImago scraper copy to `scrapers/scimago.py` with fixed DEBUG_DIR and imported `normalize_issn` from `processors.issn`.
9. **Complete pipeline run**: Executed `python main.py` against live CFR + SCImago. Result: 257 journals, 254 SUCCESS, 3 PARTIAL, 0 FAILED. Total time: 351.78 sec (~5.86 min). Average: 1.37 sec/journal.
10. **Handoff documentation**: This file + `AGENT_CONTEXT.md`.

---

## 5. Important Decisions

### Decision 1: `scrapling.Fetcher` (HTTP) first, Playwright fallback
- **Decided**: Use fast curl-based HTTP fetcher as primary. Only spin up `StealthySession` if Cloudflare challenge detected.
- **Why**: SCImago typically serves journal pages without Cloudflare challenge. HTTP fetcher is ~10x faster and uses no browser resources.
- **Rejected**: Always using Playwright (too slow, ~5-10s per page), always using HTTP (fails on challenge pages).

### Decision 2: `verify=False` for CFR
- **Decided**: Use `verify=False` when fetching CFR URLs.
- **Why**: CFR's server (`cfr.annauniv.edu`) presents an SSL certificate chain that Windows OpenSSL cannot validate (missing intermediate certificate). There is no workaround short of installing the intermediate cert manually.
- **Rejected**: Trying to add system certificates (user did not want environment changes), switching to `requests` library.

### Decision 3: latin-1 decoding for CFR responses
- **Decided**: Decode `response.body` bytes with `latin-1` (fallback chain: `utf-8` → `latin-1` → `cp1252`).
- **Why**: CFR pages contain `\xa0` (non-breaking space) bytes that are invalid in UTF-8 but valid in latin-1. The response claims `Content-Type: UTF-8` but is actually latin-1 encoded.
- **Rejected**: Using `response.text` directly (Scrapling raises `UnicodeDecodeError` during lxml parsing of the body).

### Decision 4: Separate `scrapers/` and `processors/` packages
- **Decided**: Keep CFR scraper and SCImago scraper as independent modules. Neither knows about the other. `main.py` orchestrates.
- **Why**: User explicitly requested "keep the modules independent."
- **Rejected**: Merging CFR + SCImago into one combined scraper class.

### Decision 5: No concurrency
- **Decided**: Sequential processing only.
- **Why**: User explicitly said "process sequentially, do NOT introduce multiprocessing or concurrency yet."
- **Rejected**: asyncio, threading, ProcessPoolExecutor. Will be revisited after baseline measurement.

### Decision 6: `normalize_issn` returns `"no data"` not `None`/`""`
- **Decided**: Invalid/empty ISSNs normalize to the string `"no data"`.
- **Why**: Consistent with all other fallback values in the project. Prevents `None` comparisons scattered throughout code.
- **Note**: The original `scimago_scraper.py` (root-level) uses the old `normalize_issn` that returns `""` — this is NOT the canonical version. `processors/issn.py` is canonical.

### Decision 7: Keep original `scimago_scraper.py` at root
- **Decided**: NOT deleted.
- **Why**: User never asked to delete it. The `--input` batch Excel mode in the original `main.py` was working. Deleting it without instruction would be overstepping.
- **Implication**: `scimago_scraper.py` is now a dead file (not imported by current `main.py`). It can be deleted when user is ready.

### Decision 8: No `source_url` field anywhere
- **Decided**: Absolutely no `source_url` field on `CFRJournal` or in Excel output.
- **Why**: User was explicit: "Do NOT create or add a source_url field. The CFR table does not provide one."
- **The only URL stored**: `SCImago URL` (= the journal page URL from SCImago).

### Decision 9: Preserve all CFR duplicates
- **Decided**: Detect and report duplicates but keep all records.
- **Why**: User said "Do NOT silently delete duplicates."
- **Result**: 2 duplicate journal titles found in the 257 records (different journals with same title, different ISSNs). 0 duplicate Print-ISSNs. 0 duplicate E-ISSNs.

---

## 6. Requirements & User Intent

### Hard Requirements (Non-Negotiable)
- Use `scrapling` library for all web scraping. NO Selenium, NO BeautifulSoup, NO UiPath.
- CFR data model: exactly `sl_no`, `journal_title`, `print_issn`, `e_issn`, `publisher`, `country`. No extra fields.
- No `source_url` field anywhere in CFR data.
- `normalize_issn` must return `"no data"` for invalid/empty ISSNs (not `""` or `None`).
- Print-ISSN tried first in SCImago; E-ISSN fallback if Print fails.
- `scimago_matched_issn` column to indicate which ISSN produced the successful match.
- One failed journal must NOT stop the pipeline.
- Sequential processing only (no concurrency).
- No artificial delays (`time.sleep`).
- Overall timing measured with independent `time.perf_counter()` (NOT sum of individual times).
- Output Excel file: `output/cfr_scimago_results.xlsx` with exactly the 16 columns listed in section 3.

### Preferences
- Clean, aligned terminal output (no ANSI carriage-return overwrites from Scrapling internal logger).
- `PermissionError` fallback when output file is open in Excel.
- `"no data"` string (not `None`) for all missing fields.
- Progress printed with `flush=True` so output appears in real-time when piped.

### Explicitly NOT Wanted
- Full APC / master-Excel integration system (not this POC).
- Selenium, BeautifulSoup, UiPath.
- Multiprocessing or async concurrency.
- Deleting or rewriting the existing SCImago scraper.
- Adding fake/synthetic fields to CFR data.
- `time.sleep()` artificial delays.
- Rebuilding anything from scratch.

---

## 7. Known Problems / Bugs / Limitations

### Bug 1: Terminal output garbling on Windows (SOLVED)
- **Symptom**: Scrapling internal `[INFO] Fetched...` logs used carriage returns (`\r`), overwriting previous print lines.
- **Fix**: `scrapling_log.setLevel(logging.WARNING)` where `scrapling_log` is imported from `scrapling.core.utils._utils`. This is done at module level in both `scimago_scraper.py` and `scrapers/scimago.py`.

### Bug 2: `response.text` is empty for CFR (KNOWN, HANDLED)
- **Symptom**: `len(res.text) == 0` even on 200 response.
- **Cause**: Scrapling's `text` property decodes using UTF-8 and silently returns empty string on decode error. CFR body is latin-1.
- **Fix**: Use `res.body.decode('latin-1')` and feed the resulting string to `Adaptor(decoded_html)`. Already implemented in `scrapers/cfr_data_collection.py`.

### Bug 3: Root `scimago_scraper.py` has old `normalize_issn` 
- **Symptom**: `normalize_issn` at root returns `""` for empty ISSNs instead of `"no data"`.
- **Status**: Not a bug in active code path (root file is not currently imported). But if someone imports it directly, behavior differs from `processors.issn.normalize_issn`.
- **Fix needed**: Delete `scimago_scraper.py` when user approves, or add a deprecation warning.

### Limitation 1: CFR SSL verification disabled
- **Symptom**: `verify=False` on all CFR requests.
- **Risk**: Man-in-the-middle is theoretically possible. Acceptable for a local POC.

### Limitation 2: PARTIAL status for 3 journals
- **Symptoms**: 3 journals returned PARTIAL (some metrics extracted but not all 4). Specifically observed: `RUPKATHA JOURNAL ON INTERDISCIPL` (Quartile missing), `RUSSIAN LITERATURE` (Quartile missing).
- **Cause**: These journals' SCImago pages have non-standard HTML for Quartile. The quartile selector didn't find a `Q1/Q2/Q3/Q4` span in the expected location.
- **Not investigated further** — user did not ask to fix this.

### Limitation 3: Sequential pipeline takes ~5.86 minutes for 257 journals
- **Average**: 1.37 seconds per journal. 2 SCImago requests per journal when E-ISSN fallback is needed.
- **Concurrency is the fix** — but not yet requested.

---

## 8. Important Files

| File/Directory | Purpose | Why Agent Should Care |
|---|---|---|
| `main.py` | CLI entry point + pipeline orchestration | All 4 run modes defined here; import graph starts here |
| `models.py` | `CFRJournal` + `JournalResult` dataclasses | Canonical data structures; do NOT add `source_url` |
| `scrapers/cfr_data_collection.py` | Scrapes CFR portal | CFR encoding quirk (latin-1), `verify=False`, pagination logic here |
| `scrapers/scimago.py` | SCImago scraper (canonical copy) | All extraction selectors here; imports `normalize_issn` from `processors.issn` |
| `processors/issn.py` | ISSN normalization | Canonical `normalize_issn`; returns `"no data"` not `""` |
| `scimago_scraper.py` (root) | Original scraper (now dead code) | Do NOT modify or rely on; candidate for deletion |
| `output/cfr_scimago_results.xlsx` | Latest complete pipeline output | 257 rows × 16 columns; verify here if debugging |
| `output/cfr_journals.xlsx` | Source-only mode output | 257 rows × 6 CFR columns |
| `output/debug/` | Diagnostic HTML dumps | Check here when a journal fails to parse |
| `test_input.xlsx` | Test batch Excel with 27 ISSNs | Used for regression testing `--input` mode |
| `requirements.txt` | Dependencies | 3 deps: scrapling[all], pandas, openpyxl |

---

## 9. Configuration / Environment

### No environment variables required.

### Python Virtual Environment
```powershell
# Location
c:\Users\neil-\Projects\POC-Scimago\.venv

# Activate (PowerShell)
.\.venv\Scripts\activate
```

### Dependencies (`requirements.txt`)
```
scrapling[all]>=0.4.15
pandas>=2.2.0
openpyxl>=3.1.0
```

### Playwright Browser (one-time setup, already installed)
```powershell
# Already done. Only needed if setting up fresh environment:
scrapling install
```

### External Services
- **CFR portal**: `https://cfr.annauniv.edu/research/academics/english-journals-list.php` — public, no auth, SSL verify disabled required.
- **SCImago**: `https://www.scimagojr.com/journalsearch.php` — public, no auth, no API key. Rate-limiting observed if too many concurrent requests (hence sequential processing).

### No database, no Docker, no API keys, no secrets.

---

## 10. Commands

```powershell
# Activate virtual environment
.\.venv\Scripts\activate

# --- RUNNING ---

# Mode A: CFR source-only (scrape CFR, export cfr_journals.xlsx)
python main.py --source-only

# Mode B: Complete pipeline (CFR + SCImago, export cfr_scimago_results.xlsx) [DEFAULT]
python main.py

# Mode C: SCImago single ISSN test
python main.py --scimago-only --issn 01296612

# Mode D: Batch from input Excel (legacy mode)
python main.py --input test_input.xlsx

# --- DEBUGGING ---

# Quick CFR fetch test (verifies encoding fix + structure)
.\.venv\Scripts\python -c "
from scrapers.cfr_data_collection import scrape_cfr_journals
journals, pages = scrape_cfr_journals()
print(f'{len(journals)} journals from {pages} pages')
print(journals[0])
"

# Quick SCImago single ISSN test
.\.venv\Scripts\python -c "
from scrapers.scimago import ScimagoScraper
with ScimagoScraper(headless=True, verbose=True) as s:
    r = s.scrape_journal('01296612')
    print(r)
"

# Verify normalize_issn
.\.venv\Scripts\python -c "
from processors.issn import normalize_issn
print(normalize_issn('0129-6612'))   # 01296612
print(normalize_issn(''))             # no data
print(normalize_issn('none'))         # no data
"

# Verify Excel output columns and shape
.\.venv\Scripts\python -c "
import pandas as pd
df = pd.read_excel('output/cfr_scimago_results.xlsx')
print(df.columns.tolist())
print(df.shape)
print(df['Status'].value_counts())
"
```

---

## 11. Current Task

**There is no currently defined next task.** The user will specify what to build next.

**Do NOT start any new feature without the user's explicit instruction.**

The pipeline is complete, tested, and outputs are verified. The POC phase is done.

Possible next requests from the user (speculation only, do NOT act on these):
- Integration with the full APC / master-Excel system
- Concurrency / performance optimization for 1000+ journals
- Additional data sources beyond English journals list (MBA list, supplementary lists)
- Retry logic for PARTIAL status journals

---

## 12. Do NOT Waste Time On

- **Re-reading `scimago_scraper.py` (root)**: It is dead code. The canonical version is `scrapers/scimago.py`.
- **Investigating CFR SSL errors**: Already solved with `verify=False`. Do NOT try alternative certificate approaches.
- **Investigating CFR pagination**: The current list is 1 page (257 rows). Pagination code is already implemented and future-proof.
- **Re-investigating `response.text` for CFR**: Known to return empty string. Use `response.body.decode('latin-1')` + `Adaptor()`. Already implemented.
- **Re-investigating Scrapling internal logger**: Already silenced via `scrapling_log.setLevel(logging.WARNING)` in both scraper modules.
- **Redesigning the module structure**: User explicitly approved the current `scrapers/` + `processors/` layout.
- **Adding concurrency**: Explicitly not requested yet.
- **Adding `source_url` to CFR data**: Explicitly forbidden by user.
- **Investigating the `--input` batch mode regression**: It works correctly (27 ISSNs in 41.37s tested).
- **Modifying extraction selectors for PARTIAL journals**: Not requested. 3 PARTIAL out of 257 is acceptable for POC.

---

## 13. Conversation Summary

1. **Request 1**: Build SCImago scraper POC. Extract Journal ID, SJR, Quartile from ISSN. → Built `scimago_scraper.py`, `models.py`, `main.py` with single-ISSN mode and batch Excel mode.

2. **Request 2**: Add H-Index and Coverage extraction. → Added `extract_h_index()` (looks for `<h2>H-Index</h2>` in `.cuadrado` parent) and `extract_coverage()` (looks for `<h2>Coverage</h2>` → `.cuadrado-detail`).

3. **Request 3**: Add detailed execution-time tracking (per-ISSN + overall). → `time.perf_counter()` per ISSN, stored as `execution_time: float` on `JournalResult`. Batch summary with estimates for 100/500/1000 ISSNs.

4. **Request 4**: Fix terminal formatting errors (garbled output). → Silenced Scrapling internal `log` logger. Made batch mode use clean 1-liners. Replaced `≈` with `~` (Windows cp1252 issue).

5. **Request 5**: Fix duplicate `Total Time` label. → Merged into single `Total Batch Time: X.XX seconds (X.XX minutes)`.

6. **Request 6**: Large extension: Add CFR Data Collection as Stage 1. → Created `scrapers/cfr_data_collection.py`, `scrapers/scimago.py`, `processors/issn.py`, `scrapers/__init__.py`, `processors/__init__.py`, updated `models.py` with `CFRJournal`, rewrote `main.py` to orchestrate 4 modes. Fixed CFR encoding (latin-1 + `Adaptor`). Fixed CFR SSL (`verify=False`). Ran full pipeline: 257 journals, 0 failures, 5.86 min.

7. **Request 7**: Create project reference document → Created artifact `project_reference.md` (in agent brain dir, not project).

8. **Request 8** (this): Create agent handoff package → Created `AGENT_HANDOFF.md` + `AGENT_CONTEXT.md`.

---

## 14. Open Questions

None currently open. All implementation decisions have been made. Awaiting user direction for next feature.

---

## 15. Recommended First Actions for New Agent

1. **Read this file** (you're already doing it).
2. **Read `AGENT_CONTEXT.md`** for a compressed view.
3. **Do NOT explore the codebase broadly** — the handoff documents cover it.
4. **Ask the user**: "What would you like to work on next?"
5. When the user specifies a task, re-read only the relevant source files using the table in Section 8.
6. Before writing any code, verify the current state with: `python main.py --scimago-only --issn 01296612` (should return SUCCESS in ~1.5s with SJR, Quartile, H-Index, Coverage).
7. Before modifying pipeline code, verify: `python main.py --source-only` (should return 257 journals from 1 page in ~0.3s).
8. If the user's request involves the CFR scraper, read `scrapers/cfr_data_collection.py` lines 1–60 first.
9. If the user's request involves SCImago extraction, read `scrapers/scimago.py` lines 185–299 (the extraction methods).
10. If the user asks about the data model, read `models.py` (34 lines, fast to read).
