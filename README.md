# CFR Data Collection & SCImago Scraper Pipeline

A modular Python pipeline that collects academic journal lists from the CFR Anna University portal, normalizes Print and Electronic ISSNs, queries SCImago for key scientometric indicators (SJR, Quartile, H-Index, Coverage), and exports enriched datasets to Excel.

---

## 1. Project Purpose

The purpose of this project is to automate the discovery and enrichment of recognized academic journals:
1. **CFR Data Collection**: Scrapes journal records published on the CFR portal ([CFR English Journals List](https://cfr.annauniv.edu/research/academics/english-journals-list.php)).
2. **ISSN Normalization**: Strips formatting and non-numeric characters from Print-ISSN and E-ISSN.
3. **SCImago Scientometrics Lookup**: Queries SCImago using Print-ISSN first, with automatic fallback to E-ISSN.
4. **Combined Reporting**: Exports structured Excel workbooks with per-journal processing times and overall pipeline metrics.

---

## 2. Architecture & Directory Structure

```text
POC-Scimago/
│
├── main.py                     # Central CLI & pipeline orchestrator
├── models.py                   # Dataclasses: CFRJournal, JournalResult
│
├── scrapers/
│   ├── __init__.py             # Exposes scrape_cfr_journals, ScimagoScraper
│   ├── cfr_data_collection.py  # CFR portal scraping & pagination handler
│   └── scimago.py              # SCImago scraper (fast HTTP Fetcher + stealth browser)
│
├── processors/
│   ├── __init__.py             # Exposes normalize_issn
│   └── issn.py                 # ISSN normalization and sanitization logic
│
├── output/
│   ├── cfr_journals.xlsx       # Output of source-only mode
│   ├── cfr_scimago_results.xlsx# Output of complete pipeline
│   ├── scimago_results.xlsx    # Output of batch mode (--input)
│   ├── result.json             # Output of single ISSN mode
│   └── debug/                  # Diagnostic HTML dumps saved on errors
│
├── requirements.txt            # Project dependencies
└── README.md                   # Documentation
```

### Module Separation of Concerns
- `scrapers/cfr_data_collection.py` knows **nothing** about SCImago. It only scrapes the CFR table and returns `CFRJournal` records.
- `scrapers/scimago.py` knows **nothing** about CFR. It only resolves an individual ISSN against SCImago.
- `processors/issn.py` handles ISSN string cleanup and validation.
- `main.py` orchestrates the stages, handles fallback logic, tracks execution times, and exports Excel reports.

---

## 3. Installation

Ensure Python 3.10+ is installed on Windows:

```powershell
# 1. Activate virtual environment
.\.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install browser engine for Scrapling stealth mode (one-time)
scrapling install
```

---

## 4. How to Run

### Mode A: Source-Only Mode (CFR Collection Only)

Scrapes all CFR journal list pages and exports only the raw CFR fields to `output/cfr_journals.xlsx`:

```powershell
python main.py --source-only
```

**Output Columns**:
`Sl.No`, `Full Journal Title`, `Print-ISSN`, `E-ISSN`, `Publisher`, `Country`

---

### Mode B: Complete Pipeline (CFR + SCImago Enrichment)

Scrapes CFR records, normalizes ISSNs, checks SCImago (Print-ISSN then E-ISSN fallback), and outputs `output/cfr_scimago_results.xlsx`:

```powershell
python main.py
```

**Output Columns**:
1. `Sl.No`
2. `Full Journal Title`
3. `Print-ISSN`
4. `E-ISSN`
5. `Publisher`
6. `Country`
7. `SCImago Matched ISSN`
8. `SCImago Journal ID`
9. `SJR`
10. `Quartile`
11. `H-Index`
12. `Coverage`
13. `SCImago URL`
14. `Status`
15. `Error`
16. `Processing Time (sec)`

---

### Mode C: SCImago-Only Mode (Single ISSN Test)

Tests the SCImago lookup on a single ISSN without touching the CFR website:

```powershell
python main.py --scimago-only --issn 01296612
```

---

### Mode D: Batch Excel Mode (Existing Test Feature)

Processes an arbitrary Excel file containing an `ISSN` column:

```powershell
python main.py --input test_input.xlsx
```

---

## 5. CFR Pagination Handling

The CFR scraper (`scrapers/cfr_data_collection.py`):
- Connects to the starting URL dynamically.
- Automatically inspects the DOM for next-page links (`rel="next"`, anchors with `next`, `>`, `»`, pagination classes).
- Maintains a `visited_urls` set to prevent duplicate page visits or infinite pagination loops.
- Does **not** hardcode page numbers.

---

## 6. ISSN Normalization

Defined in `processors/issn.py`:
- Strips hyphens, spaces, and punctuation (`r"[^0-9Xx]"`).
- Normalizes check characters to uppercase (e.g., `X`).
- Returns `"no data"` if the input is empty or contains placeholders (`"-"`, `"none"`, `"nan"`, `"null"`).
- The original CFR values (`Print-ISSN` and `E-ISSN`) are preserved verbatim in the output; normalized values are used strictly for SCImago querying.

---

## 7. Print-ISSN → E-ISSN Fallback Logic

For every journal in the CFR collection:
1. `Print-ISSN` is normalized and queried against SCImago.
2. If SCImago returns `SUCCESS` or `PARTIAL`, that result is kept, and `SCImago Matched ISSN` is recorded as the Print-ISSN.
3. If Print-ISSN yields no match (`FAILED`) or is empty, the pipeline queries `E-ISSN`.
4. If E-ISSN succeeds, `SCImago Matched ISSN` is recorded as the E-ISSN.
5. If both fail, `Status` is marked as `"not found"`, and SCImago metrics are set to `"no data"`.

---

## 8. SCImago Extraction

The SCImago scraper extracts 4 scientometric metrics using CSS selectors and regex patterns:
- **SJR**: `.hsjr` or `.hindexnumber.hindex-white`
- **Quartile**: `.hindexnumber.hindex-white span` or `span.Q1/Q2/Q3/Q4`
- **H-Index**: `div.cuadrado` container possessing an `<h2>H-Index</h2>` header → `.hindexnumber`
- **Coverage**: `div.cuadrado` container possessing an `<h2>Coverage</h2>` header → `.cuadrado-detail`

---

## 9. Timing & Performance Measurements

The pipeline uses `time.perf_counter()` to provide granular measurements:
- **CFR Collection Duration**: Wall-clock time to fetch and parse all CFR pages.
- **Per-Journal Processing Time**: Time taken to normalize, query Print-ISSN, query E-ISSN fallback (if applicable), and parse the SCImago response.
- **Total Pipeline Time**: Wall-clock time from start to final Excel generation.

### Pipeline Summary Output Example

```text
========================================
PIPELINE SUMMARY
========================================
CFR pages scraped:       1
CFR journals collected:  257

SCImago attempted:       257
SCImago successful:      257
SCImago failed:          0

CFR collection time:     0.30 sec
Total execution time:    351.78 sec (5.86 min)
Average journal time:    1.37 sec
========================================

[SUCCESS] Results saved to C:\Users\neil-\Projects\POC-Scimago\output\cfr_scimago_results.xlsx
```

---

## 10. Known Limitations & Notes

1. **Sequential Execution**: Processing 257 journals takes ~5.8 minutes at ~1.37s/journal. Concurrency is not yet introduced to avoid aggressive rate-limiting by SCImago.
2. **CFR SSL Certificate**: The CFR Anna University server does not supply an intermediate certificate chain recognized by default Windows OpenSSL trust stores. Requests to CFR are fetched with `verify=False`.
3. **File Lock Fallback**: If `cfr_scimago_results.xlsx` or `cfr_journals.xlsx` is currently open in Microsoft Excel when writing, the script automatically writes to `*_latest.xlsx` to avoid a crash.
