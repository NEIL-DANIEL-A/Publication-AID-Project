# AGENT CONTEXT — POC-Scimago

> Paste this into a new agent's first prompt. Last updated: 2026-09-04.

---

## 1. Project TL;DR

Python pipeline at `c:\Users\neil-\Projects\POC-Scimago` that:
1. Scrapes journal records from CFR Anna University portal (English journal list).
2. Normalizes Print-ISSN / E-ISSN.
3. Queries SCImago for SJR, Quartile, H-Index, Coverage per ISSN.
4. Exports enriched Excel workbook.

**This is a POC only. The full APC/master-Excel system has NOT been started.**

---

## 2. Current State

- **Everything is working.** All 4 run modes verified:
  - `python main.py --source-only` → 257 CFR journals in 0.3s → `output/cfr_journals.xlsx`
  - `python main.py` → 257 CFR journals + SCImago enrichment in 5.86 min → `output/cfr_scimago_results.xlsx` (254 SUCCESS, 3 PARTIAL, 0 FAILED)
  - `python main.py --scimago-only --issn 01296612` → single ISSN test
  - `python main.py --input test_input.xlsx` → batch ISSN from Excel
- **No current task.** Ask the user what to do next.

---

## 3. Architecture & Files That Matter

```
main.py                         # CLI + orchestrator (4 modes)
models.py                       # CFRJournal + JournalResult dataclasses
scrapers/cfr_data_collection.py # Stage 1: Scrapes CFR portal
scrapers/scimago.py             # Stage 2: SCImago ISSN lookup (canonical copy)
processors/issn.py              # normalize_issn() → returns "no data" not ""
scimago_scraper.py (ROOT)       # OLD dead code — NOT imported, DO NOT use
output/cfr_scimago_results.xlsx # Latest complete run result (257×16)
output/cfr_journals.xlsx        # Latest CFR-only result (257×6)
test_input.xlsx                 # 27-ISSN regression test file
```

**Run environment**: Windows, `.venv` at project root, activate with `.\.venv\Scripts\activate`. No env vars, no API keys, no database.

---

## 4. Important Decisions (Final — Do NOT Re-debate)

| Decision | Choice | Reason |
|---|---|---|
| HTTP strategy | `Fetcher.get()` first, Playwright fallback only on Cloudflare challenge | Speed; SCImago rarely blocks |
| CFR SSL | `verify=False` | CFR server has broken intermediate cert chain on Windows OpenSSL |
| CFR encoding | `response.body.decode('latin-1')` + `Adaptor()` | `response.text` returns empty string (UTF-8 decode fails on `\xa0` bytes) |
| ISSN normalization fallback | Returns `"no data"` string | Consistent with all other fallback values |
| Source URL in CFR | NOT ADDED | CFR table has no source URL column; user explicitly forbade this |
| Duplicates | Report, do NOT delete | User: "Do NOT silently delete duplicates" |
| Concurrency | None (sequential only) | User: "Do NOT introduce multiprocessing or concurrency yet" |
| Module separation | `scrapers/` knows nothing about each other; `main.py` orchestrates | User explicitly required this |

---

## 5. Known Issues

| Issue | Status | Details |
|---|---|---|
| 3 PARTIAL journals | Accepted/Not fixed | Quartile selector fails on non-standard SCImago pages (e.g., `RUPKATHA JOURNAL`, `RUSSIAN LITERATURE`) |
| `scimago_scraper.py` at root | Dead code | Not deleted; user never asked. Candidate for deletion. NOT imported by current `main.py` |
| `normalize_issn` mismatch | Root file returns `""`, `processors/issn.py` returns `"no data"` | Root file is dead code, ignore it |

---

## 6. Exact Current Task

**None.** The previous agent's work is complete. Ask the user: "What would you like to work on next?"

**Do NOT start any feature without the user's explicit instruction.**

---

## 7. What NOT to Investigate

- `scimago_scraper.py` at project root — dead code
- CFR pagination — already handled (dynamic, future-proof even though current list is 1 page)
- CFR SSL errors — already solved with `verify=False`
- CFR `response.text` — known empty; use `response.body.decode('latin-1')` + `Adaptor()`
- Scrapling internal logger — already silenced in both scraper modules
- Adding `source_url` to CFR data — explicitly forbidden
- Concurrency — explicitly not requested yet

---

## 8. First Actions for New Agent

1. Read `AGENT_HANDOFF.md` for full details.
2. Ask the user what to work on next.
3. When given a task, run the appropriate verification command to confirm the working baseline:
   ```powershell
   .\.venv\Scripts\activate
   python main.py --scimago-only --issn 01296612
   ```
   Expected: SUCCESS, ~1.5s, SJR=0.328, Q2, H-Index=17, Coverage=1974-2026.
4. Read only the specific files relevant to the user's new task (see table in Section 3).
5. Do NOT do broad codebase exploration — the handoff files are complete.
