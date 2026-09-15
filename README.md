# Publication-AID

Automated Python pipeline that collects academic journal data from CFR Anna University portal, verifies Scopus, MJL, and SCImago indexing, extracts Article Processing Charges (APC) and Elsevier GPOA discounts, and persists incrementally to **Supabase PostgreSQL**.

## Pipeline Architecture

```
CFR Portal (12,000+ journals)
  → Scopus Verification (local, Elsevier ext_list.xlsx)
  → APC & GPOA Lookup (Wiley, Elsevier, Springer Nature, SAGE, OUP)
  → MJL Hybrid Verification (direct POST + Playwright fallback)
  → SCImago Enrichment (SJR, Quartile, H-Index, Coverage)
  → Hash-based Change Detection (35 normalized fields + APC/GPOA)
  → Supabase PostgreSQL (~2-4s bulk DB persistence)
```

## Setup

```powershell
# 1. Activate venv
.\.venv\Scripts\activate

# 2. Install deps
pip install -r requirements.txt

# 3. Browser engines (one-time)
scrapling install
playwright install chromium

# 4. Supabase Setup
# Create project at https://supabase.com
# Run database/schema.sql in SQL Editor
copy .env.example .env
# Edit .env with SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY)
```

## Run

```powershell
# Full pipeline (Direct production write - changes detected via hash)
python main.py --workers 5

# Source only (CFR portal scrape)
python main.py --source-only

# Single ISSN SCImago lookup
python main.py --scimago-only --issn 01296612

# Batch from Excel
python main.py --input issns.xlsx

# Run test suite
python -m pytest tests -v
```

## Architecture

```
Publication-AID-Project/
├── main.py                  # Pipeline orchestrator, CLI dispatch, bulk DB logic
├── models.py                # Dataclasses: CFRJournal, ScopusVerificationResult, MJLVerificationResult, JournalResult
├── config/
│   ├── apc_sources.py       # APC source URLs, columns, and parser definitions
│   └── urls.py              # Centralized endpoints (CFR, Scopus, MJL, SCImago, GPOA)
├── database/
│   ├── connection.py        # Thread-safe Supabase client singleton
│   ├── hash.py              # SHA256 deterministic hash (35 normalized fields + APC/GPOA)
│   ├── repository.py        # Bulk read/write, change detection, field-level diff
│   ├── schema.sql           # Base tables (journals, child tables, changes, runs)
│   └── schema_validation.sql# DEPRECATED - Validation layer removed
├── scrapers/
│   ├── cfr_data_collection.py  # CFR Anna University portal scraper
│   ├── scopus.py               # Local Scopus verification against official source list
│   ├── apc.py                  # Multi-publisher APC price lists + Elsevier GPOA parser
│   ├── mjl.py                  # Hybrid MJL (Clarivate direct POST + Playwright)
│   └── scimago.py              # SCImago scientometrics scraper (RLock thread-safe)
├── processors/
│   └── issn.py              # ISSN normalization & validation
├── tests/                   # 19 unit & integration tests
├── FLAWS_AND_FIXES.md       # Documented flaws, logic errors, and fixes
└── output/
    └── scopus_source_title_list.xlsx  # Downloaded Scopus master list (gitignored)
```

## Database Schema

| Table | Purpose |
|---|---|
| `journals` | Master catalog (`title`, `print_issn`, `e_issn`, `data_hash`, etc.) |
| `cfr_results` | CFR portal metadata per journal (`sl_no`, etc.) |
| `scopus_results` | Scopus indexing status, coverage, and source record ID |
| `mjl_results` | Clarivate MJL/WoS verification status, index (SCIE/SSCI/AHCI/ESCI) |
| `scimago_results` | SCImago scientometrics (SJR, Quartile, H-Index, Coverage) |
| `apc_results` | Multi-currency Article Processing Charges & GPOA discount details |
| `pipeline_runs` | Execution history, duration, record metrics |
| `journal_changes` | Field-level change audit trail |
| `skipped_records` | Deduplicated / malformed ISSN audit records |

## Incremental Updates & Change Detection

- **Deterministic Hashing:** SHA-256 computed across 35 normalized attributes (including APC values and GPOA discount flags). Differences in punctuation and `&` vs `AND` are normalized.
- **Hash-based Change Detection:**
  - **NEW** → Inserted with `first_seen_at`, `last_checked_at`, `last_changed_at`
  - **MODIFIED** → Field-level diff recorded in `journal_changes`, `data_hash` updated, `last_changed_at` set
  - **UNCHANGED** → Bulk updates `last_checked_at` timestamp directly in production
  - **REMOVED** → Not auto-deleted; tracked via missing `last_seen_pipeline_run_id`
- **Audit Trail:** All field-level changes recorded in `journal_changes` with old/new values

## APC & GPOA Details

- **Publishers:** Wiley (OA + Hybrid), Elsevier, Springer Nature (Hybrid + Fully OA), SAGE (Hybrid + Gold OA), OUP
- **Elsevier GPOA:** 84 journals in 20% pilot → **pay only 20% of list price** (80% discount)
  - `apc_value` = discounted price (20% of original)
  - `original_apc_value` = list price
  - `discounted_apc_value` = same as apc_value
  - `discount_percent` = 80
  - `is_highlighted` = true
- **Springer Nature:** Coordinate-based PDF parsing handles wrapped Imprint column
  - Hybrid: ~25 journals, Fully OA: 5 journals (manual fallback)
  - Clean numeric APC values (no commas)

## Automation & CI/CD

Runs daily at 02:00 IST via GitHub Actions (`.github/workflows/cron.yml`):
- Executes `python main.py --workers 5`
- No validation layer - direct production writes with hash-based change detection
- No Excel artifact export (removed)

## Known Notes & Considerations

- **CFR Portal SSL:** `verify=False` used due to Anna University's intermediate SSL certificate configuration.
- **Scopus Master List:** Checks and refreshes the official Elsevier Source Title List (~19MB) for accurate local indexing verification.
- **SCImago Concurrency:** Default worker count is 5 to prevent rate-limiting or anti-bot triggering.
- **Live-Only Data:** All external sources fetched live; download failures raise `RuntimeError` (no cache fallback).
- **OUP APC:** Currently failing (source URL/Excel format issue) - returns 0 journals.
- **Springer Nature:** Coordinate-based PDF parser handles wrapped Imprint column; 5 Fully OA journals via manual fallback.
- **GPOA Discount:** Pay 20% of list price (80% discount), not 20% off.

## Key Fixes (See FLAWS_AND_FIXES.md)

1. **GPOA Discount Direction** - Fixed from "20% off" to "20% of list price" (80% discount)
2. **Springer PDF Parsing** - Coordinate-based extraction handles wrapped Imprint column
3. **Live-Only Fetching** - Removed cache fallback; failures raise RuntimeError
3. **Database Cleanup** - Fixed 84 Elsevier GPOA + 34 Springer records
4. **Removed Validation Layer** - Simplified to direct production with hash-based change detection