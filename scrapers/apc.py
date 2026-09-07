"""
APC (Article Processing Charge) verification for Wiley, Elsevier, Springer Nature.
Downloads bulk price lists, parses them, and builds ISSN -> APC lookup maps.
"""

import io
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config.apc_sources import APC_SOURCES, APC_COLUMN_ALIASES
from processors.issn import normalize_issn

logger = logging.getLogger(__name__)

# Cache directory for downloaded APC files
APC_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "apc_cache")


def _find_column(df: pd.DataFrame, target_key: str, fallback: str = "") -> str:
    """
    Find column in DataFrame using aliases from APC_COLUMN_ALIASES.
    Returns actual column name if found, else fallback.
    """
    aliases = APC_COLUMN_ALIASES.get(target_key, [target_key])
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for alias in aliases:
        alias_lower = alias.lower().strip()
        for col_lower, col_orig in cols_lower.items():
            if alias_lower == col_lower or alias_lower in col_lower:
                return col_orig
    return fallback


def _download_file(url: str, dest_path: str, timeout: int = 60) -> bool:
    """Download a file from URL to dest_path. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        logger.warning(f"Download failed for {url}: {e}")
        return False


def _parse_wiley_xlsx(filepath: str, issn_col: str, apc_col: str, mode_col: str, publisher_label: str, header_row: int = 0) -> List[dict]:
    """
    Parse Wiley Open Access Excel. Returns list of dicts:
    [{"issn": "1234-5678", "apc_usd": "3500", "mode": "Gold", "publisher": "Wiley"}, ...]
    """
    results = []
    try:
        df = pd.read_excel(filepath, dtype=str, engine="openpyxl", header=header_row)
    except Exception as e:
        logger.warning(f"Failed to read Wiley xlsx {filepath}: {e}")
        return results

    issn_found = _find_column(df, "issn", issn_col)
    apc_found = _find_column(df, "apc_usd", apc_col)
    mode_found = _find_column(df, "mode", mode_col)

    if not issn_found or issn_found not in df.columns:
        logger.warning(f"Wiley xlsx: ISSN column not found. Available: {list(df.columns)}")
        return results

    for _, row in df.iterrows():
        raw_issn = str(row.get(issn_found, "")).strip()
        norm = normalize_issn(raw_issn)
        if norm == "no data" or not norm:
            continue
        apc_val = str(row.get(apc_found, "")).strip() if apc_found and apc_found in df.columns else ""
        mode_val = str(row.get(mode_found, "")).strip() if mode_found and mode_found in df.columns else ""
        if apc_val and apc_val.lower() not in ("", "n/a", "na", "none", "varies", "contact"):
            results.append({
                "issn": norm,
                "apc_value": apc_val,
                "apc_currency": "USD",
                "mode_raw": mode_val,
                "publisher": publisher_label,
            })
    return results


def _parse_elsevier_xlsx(filepath: str, issn_col: str, apc_col: str, mode_col: str, header_row: int = 0) -> List[dict]:
    """
    Parse Elsevier Article Publishing Charge Excel. Returns list of dicts.
    """
    results = []
    try:
        df = pd.read_excel(filepath, dtype=str, engine="openpyxl", header=header_row)
    except Exception as e:
        logger.warning(f"Failed to read Elsevier xlsx {filepath}: {e}")
        return results

    issn_found = _find_column(df, "issn", issn_col)
    apc_found = _find_column(df, "apc_usd", apc_col)
    mode_found = _find_column(df, "mode", mode_col)

    if not issn_found or issn_found not in df.columns:
        logger.warning(f"Elsevier xlsx: ISSN column not found. Available: {list(df.columns)}")
        return results

    for _, row in df.iterrows():
        raw_issn = str(row.get(issn_found, "")).strip()
        norm = normalize_issn(raw_issn)
        if norm == "no data" or not norm:
            continue
        apc_val = str(row.get(apc_found, "")).strip() if apc_found and apc_found in df.columns else ""
        mode_val = str(row.get(mode_found, "")).strip() if mode_found and mode_found in df.columns else ""
        if apc_val and apc_val.lower() not in ("", "n/a", "na", "none", "varies", "contact"):
            results.append({
                "issn": norm,
                "apc_value": apc_val,
                "apc_currency": "USD",
                "mode_raw": mode_val,
                "publisher": "Elsevier",
            })
    return results


def _parse_oup_xlsx(filepath: str, issn_col: str, apc_col: str, currency_col: str, mode_col: str, header_row: int = 0) -> List[dict]:
    """
    Parse Oxford University Press APC pricing Excel.
    Columns: ISSN, APC Base Currency, APC rate, Journal Type.
    Returns list of dicts with apc_currency from the currency column.
    """
    results = []
    try:
        df = pd.read_excel(filepath, dtype=str, engine="openpyxl", header=header_row)
    except Exception as e:
        logger.warning(f"Failed to read OUP xlsx {filepath}: {e}")
        return results

    issn_found = _find_column(df, "issn", issn_col)
    apc_found = _find_column(df, "apc_rate", apc_col)
    currency_found = _find_column(df, "apc_currency", currency_col)
    mode_found = _find_column(df, "mode", mode_col)

    if not issn_found or issn_found not in df.columns:
        logger.warning(f"OUP xlsx: ISSN column not found. Available: {list(df.columns)}")
        return results

    for _, row in df.iterrows():
        raw_issn = str(row.get(issn_found, "")).strip()
        norm = normalize_issn(raw_issn)
        if norm == "no data" or not norm:
            continue
        apc_val = str(row.get(apc_found, "")).strip() if apc_found and apc_found in df.columns else ""
        cur_val = str(row.get(currency_found, "")).strip().upper() if currency_found and currency_found in df.columns else ""
        mode_val = str(row.get(mode_found, "")).strip() if mode_found and mode_found in df.columns else ""
        if cur_val in ("", "N/A", "NA", "NONE"):
            cur_val = ""
        if apc_val and apc_val.lower() not in ("", "n/a", "na", "none", "varies", "contact"):
            results.append({
                "issn": norm,
                "apc_value": apc_val,
                "apc_currency": cur_val or "USD",
                "mode_raw": mode_val,
                "publisher": "Oxford University Press",
            })
    return results


def _parse_sage_xlsx(filepath: str, issn_col: str, apc_col: str, apc_gbp_col: str, mode_label: str, header_row: int = 0) -> List[dict]:
    """
    Parse SAGE Hybrid (Sage Choice) APC Excel.
    Stores both USD and GBP as separate entries with different publisher labels.
    Returns list of dicts.
    """
    results = []
    try:
        df = pd.read_excel(filepath, dtype=str, engine="openpyxl", header=header_row)
    except Exception as e:
        logger.warning(f"Failed to read SAGE xlsx {filepath}: {e}")
        return results

    issn_found = _find_column(df, "issn", issn_col)
    # Find USD column - try exact match then partial
    apc_usd_found = ""
    for col in df.columns:
        if "$" in str(col) or "usd" in str(col).lower():
            apc_usd_found = col
            break
    if not apc_usd_found:
        apc_usd_found = _find_column(df, "apc_usd", apc_col)

    # Find GBP column - look for £ or gbp
    apc_gbp_found = ""
    for col in df.columns:
        if "\u00a3" in str(col) or "gbp" in str(col).lower():
            apc_gbp_found = col
            break
    if not apc_gbp_found:
        apc_gbp_found = _find_column(df, "apc_gbp", apc_gbp_col)

    if not issn_found or issn_found not in df.columns:
        logger.warning(f"SAGE xlsx: ISSN column not found. Available: {list(df.columns)}")
        return results

    for _, row in df.iterrows():
        raw_issn = str(row.get(issn_found, "")).strip()
        norm = normalize_issn(raw_issn)
        if norm == "no data" or not norm:
            continue

        # USD entry
        apc_usd = str(row.get(apc_usd_found, "")).strip() if apc_usd_found and apc_usd_found in df.columns else ""
        if apc_usd and apc_usd.lower() not in ("", "n/a", "na", "none", "varies", "contact"):
            results.append({
                "issn": norm,
                "apc_value": apc_usd,
                "apc_currency": "USD",
                "mode_raw": mode_label,
                "publisher": "SAGE",
            })

        # GBP entry
        apc_gbp = str(row.get(apc_gbp_found, "")).strip() if apc_gbp_found and apc_gbp_found in df.columns else ""
        if apc_gbp and apc_gbp.lower() not in ("", "n/a", "na", "none", "varies", "contact"):
            results.append({
                "issn": norm,
                "apc_value": apc_gbp,
                "apc_currency": "GBP",
                "mode_raw": mode_label,
                "publisher": "SAGE (GBP)",
            })

    return results


def _parse_sage_gold_oa_xlsx(filepath: str, title_col: str, apc_col: str, currency_col: str, mode_label: str, header_row: int = 0) -> List[dict]:
    """
    Parse SAGE Gold OA APC Excel (no ISSN column).
    Returns list of dicts with title for later matching.
    """
    results = []
    try:
        df = pd.read_excel(filepath, dtype=str, engine="openpyxl", header=header_row)
    except Exception as e:
        logger.warning(f"Failed to read SAGE Gold OA xlsx {filepath}: {e}")
        return results

    title_found = _find_column(df, "journal_title", title_col)
    if not title_found or title_found not in df.columns:
        # Try to find any title-like column
        for col in df.columns:
            if "title" in str(col).lower() or "journal" in str(col).lower():
                title_found = col
                break

    apc_found = _find_column(df, "apc_usd", apc_col)
    cur_found = _find_column(df, "apc_currency", currency_col)

    if not title_found:
        logger.warning(f"SAGE Gold OA xlsx: Title column not found. Available: {list(df.columns)}")
        return results

    for _, row in df.iterrows():
        title = str(row.get(title_found, "")).strip()
        if not title or title.lower() in ("nan", "none", ""):
            continue

        apc_val = str(row.get(apc_found, "")).strip() if apc_found and apc_found in df.columns else ""
        cur_val = str(row.get(cur_found, "")).strip().upper() if cur_found and cur_found in df.columns else ""

        if apc_val and apc_val.lower() not in ("", "n/a", "na", "none", "varies", "contact"):
            results.append({
                "issn": "",  # No ISSN - will be matched by title later
                "title": title,
                "apc_value": apc_val,
                "apc_currency": cur_val or "USD",
                "mode_raw": mode_label,
                "publisher": "SAGE",
            })

    return results


def _parse_springer_pdf(filepath: str) -> List[dict]:
    """
    Parse Springer Nature APC PDF via pdfplumber.
    Extracts table rows with ISSN, APC (EUR/USD/GBP), and OA mode.
    Returns list of dicts.
    """
    results = []
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber not installed - cannot parse Springer Nature PDF")
        return results

    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    header = [str(c).strip() if c else "" for c in table[0]]
                    header_lower = [h.lower() for h in header]

                    # Find column indices
                    issn_idx = None
                    apc_eur_idx = None
                    apc_usd_idx = None
                    apc_gbp_idx = None
                    mode_idx = None

                    for i, h in enumerate(header_lower):
                        if "issn" in h and issn_idx is None:
                            issn_idx = i
                        if "eur" in h and apc_eur_idx is None:
                            apc_eur_idx = i
                        if "usd" in h and apc_usd_idx is None:
                            apc_usd_idx = i
                        if "gbp" in h and apc_gbp_idx is None:
                            apc_gbp_idx = i
                        if any(k in h for k in ("type", "mode", "access")) and mode_idx is None:
                            mode_idx = i

                    if issn_idx is None:
                        continue

                    for row in table[1:]:
                        if not row or len(row) <= issn_idx:
                            continue
                        raw_issn = str(row[issn_idx] or "").strip()
                        norm = normalize_issn(raw_issn)
                        if norm == "no data" or not norm:
                            continue

                        # Prefer USD, fallback to EUR, then GBP
                        apc_val = ""
                        apc_currency = ""
                        for idx, cur in [(apc_usd_idx, "USD"), (apc_eur_idx, "EUR"), (apc_gbp_idx, "GBP")]:
                            if idx is not None and idx < len(row):
                                val = str(row[idx] or "").strip()
                                if val and val.lower() not in ("", "n/a", "na", "none", "varies", "contact"):
                                    apc_val = val
                                    apc_currency = cur
                                    break

                        mode_val = ""
                        if mode_idx is not None and mode_idx < len(row):
                            mode_val = str(row[mode_idx] or "").strip()

                        if apc_val:
                            results.append({
                                "issn": norm,
                                "apc_value": apc_val,
                                "apc_currency": apc_currency,
                                "mode_raw": mode_val,
                                "publisher": "Springer Nature",
                            })
    except Exception as e:
        logger.warning(f"Failed to parse Springer Nature PDF {filepath}: {e}")

    return results


def _normalize_mode(mode_raw: str) -> str:
    """Normalize OA mode to lowercase + strip."""
    if not mode_raw:
        return ""
    return mode_raw.lower().strip()


def _build_issn_map(records: List[dict]) -> Dict[str, List[dict]]:
    """
    Build ISSN -> list of APC records, deduplicated per (issn, publisher).
    If the same ISSN appears multiple times from the same publisher (e.g. different
    license modes in Wiley OA + Hybrid files), keep only the first occurrence.
    Returns dict: normalized_issn -> [{"apc_value", "apc_currency", "mode_raw", "publisher", "mode_normalized"}, ...]
    """
    issn_map: Dict[str, List[dict]] = {}
    seen_publishers: Dict[str, set] = {}  # issn -> set of publishers already added
    for rec in records:
        issn = rec["issn"]
        publisher = rec.get("publisher", "")
        entry = {
            "apc_value": rec.get("apc_value", ""),
            "apc_currency": rec.get("apc_currency", ""),
            "mode_raw": rec.get("mode_raw", ""),
            "mode_normalized": _normalize_mode(rec.get("mode_raw", "")),
            "publisher": publisher,
        }
        if issn not in issn_map:
            issn_map[issn] = []
            seen_publishers[issn] = set()
        if publisher not in seen_publishers[issn]:
            issn_map[issn].append(entry)
            seen_publishers[issn].add(publisher)
    return issn_map


def _build_title_map(records: List[dict]) -> Dict[str, List[dict]]:
    """
    Build title_lower -> list of APC records for journals without ISSN.
    Used for SAGE Gold OA which has no ISSN column.
    """
    title_map: Dict[str, List[dict]] = {}
    for rec in records:
        title = rec.get("title", "").strip().lower()
        if not title:
            continue
        entry = {
            "apc_value": rec.get("apc_value", ""),
            "apc_currency": rec.get("apc_currency", ""),
            "mode_raw": rec.get("mode_raw", ""),
            "mode_normalized": _normalize_mode(rec.get("mode_raw", "")),
            "publisher": rec.get("publisher", ""),
        }
        if title not in title_map:
            title_map[title] = []
        title_map[title].append(entry)
    return title_map


class APCVerifier:
    """
    Bulk APC verification for Wiley, Elsevier, Springer Nature.

    Usage:
        verifier = APCVerifier()
        verifier.load_all()
        result = verifier.lookup("1234-5678")
        # result = {"apc_value": "3500", "apc_currency": "USD", "mode_raw": "Gold", ...}
    """

    def __init__(self, cache_dir: str = None):
        self.cache_dir = cache_dir or APC_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)
        self.issn_map: Dict[str, List[dict]] = {}
        self.title_map: Dict[str, List[dict]] = {}  # title_lower -> list of APC records (for Gold OA without ISSN)
        self.stats = {
            "wiley_oa_count": 0,
            "wiley_hybrid_count": 0,
            "elsevier_count": 0,
            "springer_count": 0,
            "oup_count": 0,
            "sage_count": 0,
            "total_issns": 0,
            "load_time": 0.0,
        }
        self._loaded = False

    def load_all(self) -> None:
        """Download and parse all publisher APC files. Builds unified ISSN map."""
        load_start = time.perf_counter()
        all_records = []

        for publisher, sources in APC_SOURCES.items():
            for src in sources:
                src_name = src["name"]
                print(f"  [APC] Loading {src_name}...", end=" ", flush=True)

                if "pdf_url" in src:
                    # Springer Nature PDF
                    records = self._load_springer(src)
                    self.stats["springer_count"] = len(records)
                elif "direct_url" in src:
                    records = self._load_excel_direct(src)
                    if "Wiley OA" in src_name:
                        self.stats["wiley_oa_count"] = len(records)
                    elif "Wiley Hybrid" in src_name:
                        self.stats["wiley_hybrid_count"] = len(records)
                    elif "Elsevier" in src_name:
                        self.stats["elsevier_count"] = len(records)
                    elif "OUP" in src_name:
                        self.stats["oup_count"] = len(records)
                    elif "SAGE" in src_name:
                        self.stats["sage_count"] = len(records)
                else:
                    records = []

                all_records.extend(records)
                print(f"{len(records)} journals")

        # Separate records with ISSN (for issn_map) and without ISSN but with title (for title_map)
        issn_records = [r for r in all_records if r.get("issn")]
        title_records = [r for r in all_records if not r.get("issn") and r.get("title")]

        self.issn_map = _build_issn_map(issn_records)
        self.title_map = _build_title_map(title_records)
        self.stats["total_issns"] = len(self.issn_map)
        self.stats["total_title_only"] = len(self.title_map)
        self.stats["load_time"] = round(time.perf_counter() - load_start, 2)
        self._loaded = True

    def _load_excel_direct(self, src: dict) -> List[dict]:
        """Download Excel from direct URL and parse."""
        dest = os.path.join(self.cache_dir, src["filename"])
        url = src.get("direct_url", "")
        header_row = src.get("header_row", 0)

        if not url:
            return []

        # Try to download; keep cached file if download fails
        tmp = dest + ".tmp"
        if _download_file(url, tmp):
            # Download succeeded - replace cached file
            if os.path.exists(dest):
                os.remove(dest)
            os.rename(tmp, dest)
        elif not os.path.exists(dest):
            return []

        if "Wiley" in src["name"]:
            return _parse_wiley_xlsx(dest, src["issn_col"], src["apc_col"], src["mode_col"], "Wiley", header_row)
        elif "Elsevier" in src["name"]:
            return _parse_elsevier_xlsx(dest, src["issn_col"], src["apc_col"], src["mode_col"], header_row)
        elif "OUP" in src["name"]:
            currency_col = src.get("apc_currency_col", "")
            return _parse_oup_xlsx(dest, src["issn_col"], src["apc_col"], currency_col, src["mode_col"], header_row)
        elif "SAGE" in src["name"]:
            if "Gold OA" in src["name"]:
                title_col = src.get("title_col", "")
                currency_col = src.get("currency_col", "")
                return _parse_sage_gold_oa_xlsx(dest, title_col, src["apc_col"], currency_col, src.get("mode_label", ""), header_row)
            else:
                apc_gbp_col = src.get("apc_gbp_col", "")
                mode_label = src.get("mode_label", "")
                return _parse_sage_xlsx(dest, src["issn_col"], src["apc_col"], apc_gbp_col, mode_label, header_row)
        return []

    def _load_springer(self, src: dict) -> List[dict]:
        """Download Springer Nature PDF and parse."""
        dest = os.path.join(self.cache_dir, src["filename"])
        url = src.get("pdf_url", "")

        if not url:
            return []

        if os.path.exists(dest):
            os.remove(dest)

        if not _download_file(url, dest):
            if os.path.exists(dest):
                pass
            else:
                return []

        return _parse_springer_pdf(dest)

    def lookup(self, issn: str) -> Optional[dict]:
        """
        Look up APC for a given ISSN.
        Returns dict with apc_value, apc_currency, mode_raw, mode_normalized, publisher.
        Returns None if not found.
        """
        if not self._loaded:
            return None
        norm = normalize_issn(issn)
        if norm == "no data" or not norm:
            return None
        entries = self.issn_map.get(norm, [])
        if not entries:
            return None
        # Return first match (primary)
        return entries[0] if entries else None

    def lookup_by_title(self, title: str) -> Optional[dict]:
        """
        Look up APC by journal title (for journals without ISSN, e.g. SAGE Gold OA).
        Returns dict with apc_value, apc_currency, mode_raw, mode_normalized, publisher.
        Returns None if not found.
        """
        if not self._loaded:
            return None
        title_lower = title.strip().lower()
        if not title_lower:
            return None
        entries = self.title_map.get(title_lower, [])
        if not entries:
            return None
        return entries[0] if entries else None

    def lookup_all(self, issn: str) -> List[dict]:
        """
        Look up ALL APC entries for a given ISSN (keep both duplicates across publishers).
        Returns list of dicts.
        """
        if not self._loaded:
            return []
        norm = normalize_issn(issn)
        if norm == "no data" or not norm:
            return []
        return self.issn_map.get(norm, [])


def verify_apc_indexing(journals: list) -> Tuple[Dict[str, dict], dict]:
    """
    Bulk APC verification for CFR journals.

    Args:
        journals: list of CFRJournal objects (need .print_issn, .e_issn)

    Returns:
        (issn_map, stats) where:
        - issn_map: dict keyed by sl_no -> {"apc_value", "apc_currency", "mode_raw", ...}
        - stats: dict with load time + per-publisher counts
    """
    verifier = APCVerifier()
    verifier.load_all()

    results = {}
    for j in journals:
        # Try print ISSN first, then E-ISSN
        for issn in (j.print_issn, j.e_issn):
            entry = verifier.lookup(issn)
            if entry:
                results[j.sl_no] = entry
                break

    return results, verifier.stats
