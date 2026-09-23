# Scopus Metric Scraping & Supabase Pipeline

This module fetches real-time Scopus metrics (**CiteScore**, **SJR**, **SNIP**, **Subject Area**, and **Publisher**) for academic journals from Supabase and pushes the enriched dataset back into Supabase.

---

## 📂 Contents

| File | Description |
| :--- | :--- |
| `fetch_and_push_12k.py` | Main end-to-end pipeline: fetches journals from `journals`, maps against Scopus registry, streams metrics in bulk, saves CSV backup, and upserts to `Scopus_additional_data`. |
| `complete_missing_metrics.py` | Resumption script: streams full catalog (offsets 17,200 – 50,040) with rate-limit protection to recover all remaining journal metrics. |
| `scrape_scopus.py` | Standalone browser/dynamic scraper using `Scrapling` for detailed Scopus web profile scraping. |
| `push_to_supabase.py` | Utility to push local CSV data directly into Supabase tables in batches. |
| `setup_supabase_table.sql` | SQL schema migration creating the `Scopus_additional_data` table, indexes, unique constraints, and RLS policies. |
| `schema.sql` | Base schema reference for the Supabase database. |
| `scopus_12k_additional_data.csv`| Enriched dataset of 12,196 journals with Scopus CiteScore, SJR, SNIP, publisher, and subject area. |
| `journals_with_null_metrics.csv` | List of 285 discontinued or inactive journals where all 3 metrics (CiteScore, SJR, SNIP) are NULL. |
| `journals_with_at_least_one_null_metric.csv` | List of 419 journals where at least one metric (CiteScore, SJR, or SNIP) is NULL. |
| `matched_journals.csv` | Initial mapping of Supabase journals to Scopus Sourcerecord IDs via normalized ISSN / E-ISSN. |
| `scopus_journals.csv` | Sample verification dataset of top Scopus journals. |
| `.env.example` | Environment variables template (`SUPABASE_URL`, `SUPABASE_KEY`). |

---

## 🚀 Setup & Execution

### 1. Install Dependencies
```bash
pip install scrapling playwright requests pandas supabase openpyxl
scrapling install
```

### 2. Configure Credentials
Copy `.env.example` to `.env` and set your Supabase credentials:
```env
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_KEY=<your-anon-or-service-key>
```

### 3. Run Pipeline
```bash
python fetch_and_push_12k.py
```
*(If the 26MB Elsevier master Excel list `scopus_master_list.xlsx` is not present locally, `fetch_and_push_12k.py` will automatically download it on first run).*
