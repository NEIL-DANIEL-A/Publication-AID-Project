# Publication-AID

Automated Python pipeline that collects academic journal data from CFR Anna University portal, verifies Scopus, MJL, and SCImago indexing, extracts Article Processing Charges (APC) and Elsevier GPOA discounts, and persists incrementally to **Supabase PostgreSQL** with an automated Validation & Human Approval Layer.

## Pipeline Architecture

```
CFR Portal (12,000+ journals)
  → Scopus Verification (local, Elsevier ext_list.xlsx)
  → APC & GPOA Lookup (Wiley, Elsevier, Springer Nature, SAGE, OUP)
  → MJL Hybrid Verification (direct POST + Playwright fallback)
  → SCImago Enrichment (SJR, Quartile, H-Index, Coverage)
  → Change Detection & Validation Layer (change_proposals table)
  → Supabase PostgreSQL (~2-4s bulk DB persistence / admin approval)
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
# Run database/schema.sql and database/schema_validation.sql in SQL Editor
copy .env.example .env
# Edit .env with SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY)
```

## Run

```powershell
# Full pipeline with Validation & Approval Layer (Default for CI/CD)
python main.py --workers 5 --validate

# Direct production write (legacy / bypass approval)
python main.py --workers 5 --direct

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
│   ├── repository.py        # Bulk read/write, proposal creation, approval/rejection logic
│   ├── schema.sql           # Base tables (journals, child tables, changes, runs)
│   └── schema_validation.sql# Validation layer tables (change_proposals, indexes)
├── scrapers/
│   ├── cfr_data_collection.py  # CFR Anna University portal scraper
│   ├── scopus.py               # Local Scopus verification against official source list
│   ├── apc.py                  # Multi-publisher APC price lists + Elsevier GPOA parser
│   ├── mjl.py                  # Hybrid MJL (Clarivate direct POST + Playwright)
│   └── scimago.py              # SCImago scientometrics scraper (RLock thread-safe)
├── processors/
│   └── issn.py              # ISSN normalization & validation
├── tests/                   # 24 unit & integration tests
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
| `change_proposals` | Validation layer: PENDING proposals for NEW, MODIFIED, and REMOVED records |
| `pipeline_runs` | Execution history, duration, record metrics, and validation status |
| `journal_changes` | Field-level change audit trail |
| `skipped_records` | Deduplicated / malformed ISSN audit records |

## Incremental Updates & Change Detection

- **Deterministic Hashing:** SHA-256 computed across 35 normalized attributes (including APC values and GPOA discount flags). Differences in punctuation and `&` vs `AND` are normalized.
- **Validation Layer (`--validate`):**
  - **NEW** → Creates `PENDING` proposal in `change_proposals` (production untouched).
  - **MODIFIED** → Creates `PENDING` proposal with field-level diffs for review.
  - **REMOVED** → Flags missing records as `PENDING` removal proposal.
  - **UNCHANGED** → Bulk updates `last_checked_at` timestamp directly in production.
- **Admin Approval:** When proposals are approved via `approve_proposals()`, changes and child relations are applied atomically to production tables.

## Automation & CI/CD

Runs daily at 02:00 IST via GitHub Actions (`.github/workflows/cron.yml`):
- Executes with `--validate` flag to guarantee changes require verification.
- Exports results to an Excel artifact (`output/cfr_scopus_mjl_scimago_results.xlsx`) for downstream reporting.

## Known Notes & Considerations

- **CFR Portal SSL:** `verify=False` is used due to Anna University's intermediate SSL certificate configuration.
- **Scopus Master List:** Checks and refreshes the official Elsevier Source Title List (~19MB) for accurate local indexing verification.
- **SCImago Concurrency:** Default worker count is 5 to prevent rate-limiting or anti-bot triggering.

