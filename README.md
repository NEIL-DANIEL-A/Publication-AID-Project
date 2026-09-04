# SCImago Journal Scraper POC (Scrapling)

A lightweight Proof of Concept (POC) Python project to scrape SCImago journal metrics (**Journal ID**, **SJR**, **Quartile**, **H-Index**, **Coverage**, and **Execution Time**) given an ISSN, built with [Scrapling](https://github.com/D4Vinci/Scrapling).

---

## Requirements & Python Version

- **Python**: 3.11+ (Tested on Python 3.14)
- **Dependencies**: `scrapling[all]`, `pandas`, `openpyxl`
- **Browser Automation**: Patchright / Chromium browser binaries managed via Scrapling.

---

## Installation

1. **Navigate to the Project Directory**:
   ```bash
   cd POC-Scimago
   ```

2. **Create and Activate Virtual Environment**:
   ```bash
   # Windows (PowerShell)
   python -m venv .venv
   .\.venv\Scripts\activate

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Browser Binaries**:
   ```bash
   scrapling install
   # or
   patchright install chromium
   ```

---

## Usage

### 1. Single ISSN Mode (Default POC)

Run default test with ISSN `01296612`:
```bash
python main.py
```

Or pass any custom ISSN:
```bash
python main.py --issn 0129-6612
python main.py --issn 00000000
```

Results are printed to the console and saved to `output/result.json`.

### 2. Batch Excel Mode

Process an Excel sheet containing an `ISSN` column:
```bash
python main.py --input test_input.xlsx
```

Results are saved to `output/scimago_results.xlsx` (or `output/scimago_results_latest.xlsx` if locked) with columns:
- `ISSN`
- `Journal ID`
- `SJR`
- `Quartile`
- `H-Index`
- `Coverage`
- `Status`
- `Error`
- `Execution Time (seconds)`

---

## Expected Output

### Single-ISSN Output Example
```text
========================================
SCIMAGO POC
========================================
ISSN       : 01296612
Journal ID : 23067
SJR        : 0.328
Quartile   : Q2
H-Index    : 17
Coverage   : 1974-2026
Status     : SUCCESS

----------------------------------------
ISSN Execution Time : 1.53 seconds
----------------------------------------
Search URL : https://www.scimagojr.com/journalsearch.php?q=01296612
Journal URL: https://www.scimagojr.com/journalsearch.php?q=23067&tip=sid&clean=0
========================================
```

### Batch Summary Output Example
```text
========================================
SCIMAGO BATCH SUMMARY
========================================
Total ISSNs     : 12
Successful      : 12
Partial         : 0
Failed          : 0

Total Batch Time: 18.53 seconds (0.31 minutes)

Average / ISSN  : 1.54 seconds

Estimates based on measured average:
  100 ISSNs  ≈ 2.6 minutes
  500 ISSNs  ≈ 12.9 minutes
  1000 ISSNs ≈ 25.7 minutes
========================================
```

---

## Metric Extraction Details

1. **ISSN Normalization**: Strips hyphens, whitespace, and formatting (e.g. `0129-6612` $\rightarrow$ `01296612`).
2. **Journal ID**: Extracted by parsing query parameter `q` from target hrefs matching `journalsearch.php?q=...&tip=sid`.
3. **SJR**: Extracted using `.hsjr` tag (with fallback to `.hindexnumber.hindex-white`).
4. **Quartile**: Extracted dynamically using regex `r'\b(Q[1-4])\b'` across `.hindexnumber.hindex-white` card and span classes.
5. **H-Index**: Label-based extraction matching `<h2>H-Index</h2>` parent container `<div class="cuadrado">` and reading `.hindexnumber`.
6. **Coverage**: Label-based extraction matching `<h2>Coverage</h2>` parent container `<div class="cuadrado">` and reading `.cuadrado-detail` text (e.g., `1974-2026`).
7. **Per-ISSN Execution Time**: Measured using `time.perf_counter()` from normalization to result assembly.
8. **Batch Execution Time**: Wall-clock duration measured independently from start to final file export using `time.perf_counter()`.

---

## Error Handling & Debugging

- **Missing / Invalid Records**: If an ISSN has no journal entries (e.g., `00000000`), the scraper returns `"no data"` for missing fields and `status="FAILED"`.
- **Diagnostic HTML Dumps**: Saved to `output/debug/` when an extraction fails or returns missing metrics.
- **Security / Challenge Pages**: Automatically handles Cloudflare challenges via `solve_cloudflare=True` fallback.
