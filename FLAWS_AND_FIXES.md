# Flaws, Logic Errors, and Fixes Log

This document tracks all discovered flaws, logic errors, and their fixes in the Publication-AID pipeline.

---

## 1. APC Parser Issues

### 1.1 Springer Nature PDF Parsing - Wrapped Imprint Column
**Problem**: The Springer Nature Hybrid and Fully OA PDFs have a wrapped "Imprint" column where long publisher names wrap to the next line. Standard table extraction (pdfplumber `extract_tables()`) splits this wrapped text across cells, corrupting the ISSN and price columns.

**Impact**: 
- Garbled ISSN values (e.g., `"-p u b 4li,s3h9e0d"` instead of `4390`)
- Garbled price values in EUR/USD/GBP columns
- Missing journal entries (Acta Mechanica Sinica was completely missed)

**Root Cause**: pdfplumber's table extraction uses visual line detection which fails when cell content wraps across multiple lines.

**Fix**: Implemented coordinate-based character extraction (`page.chars`) with fixed column boundaries based on x-position analysis. Added digit extraction from garbled text for both ISSN and price values.

**Files Changed**: `scrapers/apc.py` - `_parse_springer_pdf()`

### 1.2 Springer Nature Fully OA PDF Different Layout
**Problem**: The Fully OA PDF has a completely different column layout than Hybrid:
- Columns merged: Journal+Imprint+eISSN in col 0, EUR+USD+GBP in col 1
- Standard column boundaries don't apply

**Fix**: Added manual fallback dictionary `_KNOWN_SPRINGER_FULLY_OA` with 5 known entries.

### 1.3 GPOA Discount Calculation - Wrong Direction
**Problem**: Elsevier GPOA was calculated as "20% off" (80% of list price) instead of "20% of list price" (80% discount).

**Original**: `discounted = original * 0.80` (20% off)
**Correct**: `discounted = original * 0.20` (20% of list = 80% discount)

**Impact**: 84 Elsevier journals had wrong discounted prices (e.g., 5030 → 4024 instead of 5030 → 1006)

**Fix**: Changed `_calc_gpoa_discount()` to multiply by `percent/100` (20%) instead of `(100-percent)/100` (80%). Updated `discount_percent` field to 80.

**Files Changed**: `scrapers/apc.py` - `_calc_gpoa_discount()`, `_apply_gpoa_discount()`

---

## 2. Data Source Issues

### 2.1 Live-Only Fetching Requirement
**Problem**: Pipeline used cached files as fallback when live downloads failed, leading to stale data.

**Fix**: Modified all fetchers to raise `RuntimeError` on download failure instead of falling back to cache:
- `_load_excel_direct()` for Wiley, Elsevier, OUP, SAGE
- `_load_springer()` for Springer Nature PDFs
- `_fetch_elsevier_gpoa_issns()` for GPOA list

**Files Changed**: `scrapers/apc.py` - `_load_excel_direct()`, `_load_springer()`, `_fetch_elsevier_gpoa_issns()`

### 2.2 OUP Cache Corruption
**Problem**: OUP_Charges.xlsx cache file was corrupted (0 bytes, not a valid zip/xlsx)

**Fix**: Live-only fetching will re-download on next run. If OUP URL is dead, pipeline will fail explicitly.

---

## 3. Database/Change Detection Issues

### 3.1 APC Change Detection False Positives
**Problem**: 116 journals flagged as "changed" due to:
1. Springer APC values with commas (`4,390` vs `4390`)
2. Elsevier GPOA wrong discount calculation
3. One garbled Springer record

**Fix**: 
- Fixed Springer parser to output clean numeric strings
- Fixed GPOA calculation
- Deleted garbled Acta Mechanica Sinica record
- Re-synced all 84 Elsevier GPOA + 34 Springer records

### 3.2 MJL Product Code C→AHCI Bug
**Problem**: MJL parser incorrectly mapped product code `C` to AHCI index.

**Fix**: Removed `C` from AHCI mapping; only `H` maps to AHCI. Added `jcrCategories[].jcrEdition` as authoritative source.

**Files Changed**: `scrapers/mjl.py` - `_extract_wos_indexes()`

---

## 4. Pipeline Architecture

### 4.1 Removed Validation Layer
**Removed Files**:
- `database/schema_validation.sql`
- `scripts/approve.py`
- Validation logic from `main.py` (`--validate`, `--direct` args, proposal creation)
- 8 validation functions from `database/repository.py`

### 4.2 Removed Legacy Excel Artifact
**Removed**: Excel export from `main.py` and `upload-artifact` step from `.github/workflows/cron.yml`

---

## 5. Testing Gaps

### 5.1 Missing Integration Tests
- No end-to-end test with live API calls
- No test for GPOA discount calculation with real data
- No test for Springer PDF parsing with actual PDFs

### 5.2 Missing Edge Case Tests
- ISSN with 'X' check digit
- Price values with currency symbols
- Garbled PDF rows with completely scrambled text

---

## 6. Remaining Technical Debt

| Priority | Issue | Effort |
|----------|-------|--------|
| High | Springer Fully OA PDF parser (different layout) | Medium |
| High | OUP APC source (dead URL?) | Low |
| Medium | Springer Hybrid parser over-extracts (2029 rows vs ~25 journals) | Medium |
| Medium | No retry logic for transient network failures | Low |
| Low | Add structured logging (JSON) | Low |
| Low | Add metrics/monitoring endpoints | Low |

---

## 6. Verification Checklist

- [x] All 19 unit tests pass
- [x] GPOA discount: 5030 → 1006 (20% of list price)
- [x] Springer Acta Mechanica Sinica: 1614-3116 → 4390 USD
- [x] Springer Fully OA: 5 manual fallback entries loaded
- [x] 84 Elsevier GPOA records corrected in DB
- [x] 34 Springer Nature records corrected in DB (commas removed)
- [x] Pipeline runs without cache fallback (live-only)
- [x] All 19 tests pass