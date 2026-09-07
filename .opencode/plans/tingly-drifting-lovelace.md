# Plan: APC Cost Integration (Multi-Publisher)

## Context
Add APC (Article Processing Charge) cost + OA mode extraction from per-publisher price lists. Each publisher hosts its own Excel/PDF with different headers; extract APC in original currencies (no conversion) + OA/subscription/hybrid/gold modes. Compare/merge like Scopus (local verify), persist to Supabase separate table. User: keep all currencies, keep both duplicates across publishers, separate table.

**Sources provided & probed (2026-09-07 WebFetch):**
- Wiley: 2 xlsx — `authors.wiley.com/asset/Wiley-Journal-APCs-{Open-Access,OnlineOpen}.xlsx` (OA + Hybrid APC, cols: Journal Title, ISSN, APC USD/GBP/EUR/JPY, License Types)
- Springer Nature: PDF via CMS API — `cms-resources.../27820862/data/v3` (420KB, 63 pages) — **not xlsx** (cols: Journal name, Imprint, eISSN, EUR/USD/GBP)
- Elsevier: 1 xlsx — `legacyfileshare.elsevier.com/els_com_pricing/article-publishing-charge.xlsx` (cols: Journal Title, ISSN, OA Status, APC USD/EUR/GBP)
- Taylor & Francis: 2 xlsx but **subscription pricing only** (`files.taylorandfrancis.com/early-journal*-pricelist-*.xlsx`) — **no bulk APC**. T&F APCs are per-journal HTML. Second Springer URL same pattern (fully OA PDF).

---

## Decisions & Open Items
- **keep both duplicates**: Same ISSN in Wiley + Elsevier → must not collapse to 1 row/journal. Requires `apc_results` as **1:many** (`id UUID PK, journal_id FK`) not `journal_id PK`. Unlike `scopus_results/mjl_results` which are 1:1.
- **Hash ambiguity**: 29-field hash in `database/hash.py:46` assumes 1:1. With 1:many APCs, hashing ambiguous. Options: (a) aggregate sorted string `"Elsevier: 3000 USD | Wiley: 3500 GBP"` → add `apc_aggregate` + `apc_mode_aggregate` to hash (detects change), or (b) exclude APC from hash, track via separate comparison. **Recommend (a)** — ask user to confirm.
- **Currencies**: Store raw `apc_amount TEXT + apc_currency TEXT` (e.g., "3290", "EUR") — TEXT preserves "no data", matches existing tables.
- **Modes**: Store `apc_mode TEXT` raw + `apc_mode_normalized TEXT` (gold/hybrid/subscription/open access). Map via per-publisher alias list.

---

## Architecture Change

```
main.py run_complete_pipeline:
  Stage 1 CFR (256) → Stage 2 Scopus → [NEW Stage 2b APC] → Stage 3 MJL → Stage 4 SCImago → DB
```

Stage 2b after Scopus (APC for all 256, not filtered like MJL/SCImago which filter Active/Indexed). Builds `apc_map` like `scopus_map`, then `process_eligible_pair` adds APC fields to record dict (26→31 cols).

DB: PHASE 1 5→6 reads (+ `apc_results`), PHASE 2 29→31 hash fields, PHASE 3 ~9→~11 writes.

---

## File Changes (ordered)

### 1. `config/urls.py` (26 lines)
Add:
```python
APC_WILEY_OA_URL = "https://authors.wiley.com/asset/Wiley-Journal-APCs-Open-Access.xlsx"
APC_WILEY_HYBRID_URL = "https://authors.wiley.com/asset/Wiley-Journal-APCs-OnlineOpen.xlsx"
APC_ELSEVIER_URL = "https://legacyfileshare.elsevier.com/els_com_pricing/article-publishing-charge.xlsx"
APC_SPRINGER_HYBRID_URL = "https://cms-resources.apps.public.k8s.springernature.io/springer-cms/rest/v1/content/27820862/data/v3"
APC_SOURCE_URLS = {"wiley_oa": ..., "wiley_hybrid": ..., "elsevier": ..., "springer_hybrid": ...}
# T&F subscription URL documented but excluded for APC
```

### 2. `models.py` (63 lines) — add dataclass
```python
@dataclass
class APCVerificationResult:
    apc_status: str = "Not Found"  # Found / Multiple Found / Not Found / Unable to Verify
    apc_match_type: str = "No Match"
    apc_amount: str = "no data"
    apc_currency: str = "no data"
    apc_issn_used: str = "no data"
    apc_mode: str = "no data"  # raw OA mode
    apc_mode_normalized: str = "no data"
    apc_source_title: str = "no data"
    apc_publisher: str = "no data"
```

### 3. `scrapers/apc.py` (NEW, ~350 lines) — mirror `scrapers/scopus.py:42` pattern
- `APC_COLUMN_ALIASES: Dict[publisher, Dict[canonical, List[str]]]` — e.g., `apc_usd: ["APC USD", "Article Processing Charge USD"]`, `issn: ["Online ISSN", "Print ISSN"]`
- `download_apc_dataset(url, dest_path) -> bool` — per-publisher urllib (xlsx vs pdf)
- `ensure_apc_datasets(output_dir, force) -> Dict[publisher, path]`
- `class APCVerifier`:
  - `__init__(output_dir, force=True)` → `self.issn_map: Dict[str, List[dict]]` (keep both) + `self.issn_primary_map: Dict[str, dict]` (first for simple lookup)
  - `_load_wiley(path)` / `_load_elsevier(path)` → `pd.read_excel` + alias matching
  - `_load_springer_pdf(path)` → `pdfplumber` parse tabular PDF (Journal, eISSN, EUR/USD/GBP). Requires new dep.
  - `verify_journal(journal) -> APCVerificationResult` — norm_p then norm_e lookup, handles Multiple Found
  - `verify_apc_indexing(journals, output_dir) -> Tuple[List[Tuple[CFRJournal, APCVerificationResult]], dict]`

**Risks:** PDF parsing fragile; header variance needs case-insensitive contains check; T&F APC absence documented.

### 4. `scrapers/__init__.py` (14 lines)
Add `from .apc import APCVerifier, verify_apc_indexing`

### 5. `database/schema.sql` (198 lines)
```sql
CREATE TABLE IF NOT EXISTS apc_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_id UUID NOT NULL REFERENCES journals(id) ON DELETE CASCADE,
    publisher TEXT,
    apc_status TEXT, apc_match_type TEXT, apc_amount TEXT, apc_currency TEXT,
    apc_issn_used TEXT, apc_mode TEXT, apc_mode_normalized TEXT, source_title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX apc_results_journal_id_idx ON apc_results(journal_id);
-- No UNIQUE(journal_id) — allows keep both
DO $$ ALTER TABLE pipeline_runs ADD COLUMN total_apc_processed INT DEFAULT 0; END $$;
```
Manual Supabase SQL run required.

### 6. `database/hash.py` (108 lines)
Extend `build_hash_input` with `apc_status="", apc_aggregate="", apc_mode_aggregate=""` → return dict keys same. Update every call site in main.py PHASE 2.

### 7. `database/repository.py` (414 lines)
- `bulk_get_apc_map(journal_ids) -> Dict[str, List[dict]]` — groups by journal_id (1:many, chunk 500)
- `bulk_upsert_apc(rows)` — delete WHERE journal_id IN (...) then insert (since 1:many, upsert on PK not journal_id)
- Update `get_existing_full` optionally fetches apc_results

### 8. `main.py` (946 lines)
- Import `verify_apc_indexing`
- Stage 2b after Scopus:
```python
from scrapers.apc import verify_apc_indexing
apc_pairs, apc_stats = verify_apc_indexing(journals, OUTPUT_DIR)
apc_lookup = {j.sl_no: r for j, r in apc_pairs}
```
- In `process_eligible_pair`, add `a_res = apc_lookup.get(j.sl_no)` → extend record dict with `APC Status/Amount/Currency/Mode/Publisher` (5 cols)
- PHASE 1: `apc_map = bulk_get_apc_map(journal_ids)` (+1 query)
- PHASE 2: extend `build_hash_input` call, add apc field diff
- PHASE 3: `bulk_upsert_apc(...)` (+2 queries)
- Update `finish_pipeline_run` stats + summary print

### 9. `requirements.txt` — add `pdfplumber>=0.11.0` if Springer PDF parsing chosen (else PyPDF2)

### 10. `tests/test_apc.py` — mock alias matching + synthetic Excel (low priority)

---

## Implementation Order
1. `config/urls.py` (5 min) → 2. `models.py` (5 min) → 3. `schema.sql` (10 min) → 4. `hash.py` (10 min) → 5. `scrapers/apc.py` (60-90 min) → 6. `scrapers/__init__.py` (2 min) → 7. `repository.py` (20 min) → 8. `main.py` (40 min) → 9. `requirements.txt` (5 min) → 10. tests (15 min)

Total ~3h

---

## Verification Plan
1. `py_compile` all modified files; `pytest tests -q` (13 existing)
2. Manual per-publisher: `python -c "from scrapers.apc import APCVerifier; v=APCVerifier('output', True); print(len(v.issn_map))"`
3. Dry run `python main.py --source-only` still works
4. Full run `python main.py --workers 5` — check Stage 2b logs, `SELECT * FROM apc_results LIMIT 5`, `SELECT publisher, count(*) FROM apc_results GROUP BY publisher`
5. First run hash migration → 256 updated (expected)

---

## Risks
- Springer PDF layout change → per-row try/except, save debug text
- T&F APC bulk missing → exclude, document
- Header variance → alias + `lower() in header.lower()` contains
- 1:many vs hash → aggregate sorted string
- Download failures → independent per publisher, log warn, continue

---

## Questions for User
1. Hash strategy: aggregate APC into hash vs exclude?
2. Confirm T&F APC exclusion OK?
3. Add `pdfplumber` dep?
4. APC for all 256 or only Active/Indexed?
