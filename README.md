# Publication-AID

Automated Python pipeline that collects academic journal data from CFR Anna University portal, verifies Scopus/MJL/SCImago indexing, and persists incrementally to **Supabase PostgreSQL**.

## Pipeline

```
CFR Portal (256 journals)
  → Scopus Verification (local, 19MB ext_list.xlsx)
  → MJL Hybrid (direct POST + Playwright fallback)
  → SCImago (SJR, Quartile, H-Index, Coverage)
  → Supabase (5 reads + 9 writes, ~2-4s DB time)
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

# 4. Supabase
# Create project at https://supabase.com
# Run database/schema.sql in SQL Editor
copy .env.example .env
# Edit .env with SUPABASE_URL and SUPABASE_KEY
```

## Run

```powershell
# Full pipeline (CFR → Scopus → MJL → SCImago → Supabase)
python main.py --workers 5

# Source only (CFR scrape)
python main.py --source-only

# Single ISSN
python main.py --scimago-only --issn 01296612

# Batch from Excel
python main.py --input issns.xlsx

# Tests
python -m pytest tests -q
```

## Architecture

```
Publication-AID-Project/
├── main.py                  # 4-stage orchestrator + bulk DB persistence
├── models.py                # CFRJournal, ScopusVerificationResult, MJLVerificationResult, JournalResult
├── config/
│   └── urls.py              # Centralized URLs (CFR, Scopus, MJL, SCImago)
├── database/
│   ├── connection.py        # Supabase client singleton
│   ├── hash.py              # SHA256 hash (26 fields, & vs AND normalized)
│   ├── repository.py        # Bulk read/write, per-journal CRUD, pipeline_runs
│   └── schema.sql           # 7 tables + indexes + triggers
├── scrapers/
│   ├── cfr_data_collection.py  # CFR portal scraper
│   ├── scopus.py               # Local Scopus verification
│   ├── mjl.py                  # Hybrid MJL (POST + Playwright)
│   └── scimago.py              # SCImago scraper (RLock thread-safe)
├── processors/
│   └── issn.py              # ISSN normalization
├── tests/                   # 13 tests (hash, change detection, repository mock)
└── output/
    └── scopus_source_title_list.xlsx  # Downloaded 19MB (gitignored)
```

## Database

7 tables in Supabase PostgreSQL:

| Table | Purpose |
|---|---|
| `journals` | Master list (title, ISSN, publisher, country, data_hash) |
| `cfr_results` | CFR portal data per journal |
| `scopus_results` | Scopus indexing status |
| `mjl_results` | MJL/WoS verification |
| `scimago_results` | SCImago scientometrics (SJR, Quartile, H-Index) |
| `pipeline_runs` | Run history with stats |
| `journal_changes` | Field-level change history |
| `skipped_records` | CFR duplicate ISSN audit |

## Incremental Update

**Hash:** SHA256 of 26 normalized fields (`database/hash.py`). `&` vs `AND` produces same hash.

**3 cases per journal:**
- **New** → INSERT journal + child tables
- **Unchanged** → UPDATE `last_checked_at` only (1 bulk query)
- **Changed** → UPDATE all tables + INSERT `journal_changes` diff

**Bulk operations:** 5 reads (journals + 4 child tables) + 9 writes (insert/update/touch/changes). DB time ~2-4s vs previous ~62s per-row.

## Cron

GitHub Actions daily at 02:00 IST (`.github/workflows/cron.yml`).

## Known Limitations

- CFR: `verify=False` (SSL intermediate cert missing)
- Scopus: Force downloads 19MB every run (per spec)
- SCImago: `workers=5` default, increase risks 429/403
- MJL: Direct POST may need update if Clarivate changes API
- Supabase: RLS requires `service_role` key or disabled for tables
