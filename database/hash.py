import hashlib
import json


def _normalize_value(v) -> str:
    """Normalize single value for hashing: strip whitespace, handle None/'None'/empty as 'no data' equivalent."""
    if v is None:
        return ""
    s = str(v).strip()
    # Treat placeholders as empty
    if s.lower() in ("", "none", "no data", "null", "nan", "n/a", "na", "nil", "-", "null"):
        # Use empty for hash so "None"/"no data"/"" are identical
        return ""
    s = s.lower()
    # Normalize title variations: "&" vs "and", multiple spaces, punctuation
    # so "EAST & WEST" and "EAST AND WEST" hash to same value (spec section 22 Test 5)
    s = s.replace("&", " and ")
    # Collapse whitespace and remove extra punctuation spacing
    import re
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*:\s*", ": ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s


def _normalize_record(record: dict) -> dict:
    """Normalize all values in record dict for deterministic hashing."""
    normalized = {}
    for k, v in record.items():
        # Keys are sorted later, but normalize values now
        normalized[k] = _normalize_value(v)
    return normalized


def compute_data_hash(record: dict) -> str:
    """
    Deterministic SHA-256 hash for journal record.
    Steps: normalize values -> sort keys -> canonical JSON -> SHA256.
    Same logical input always produces same hash even with whitespace/casing differences.
    """
    normalized = _normalize_record(record)
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_hash_input(
    journal_title: str,
    print_issn: str,
    e_issn: str,
    publisher: str,
    country: str,
    scopus_status: str = "",
    scopus_match_type: str = "",
    scopus_source_title: str = "",
    scopus_sourcerecord_id: str = "",
    scopus_publisher: str = "",
    scopus_coverage: str = "",
    scopus_issn: str = "",
    scopus_eissn: str = "",
    mjl_status: str = "",
    mjl_index: str = "",
    mjl_issn_used: str = "",
    mjl_source_title: str = "",
    scimago_status: str = "",
    scimago_journal_id: str = "",
    scimago_matched_issn: str = "",
    sjr: str = "",
    quartile: str = "",
    h_index: str = "",
    scimago_coverage: str = "",
    scimago_url: str = "",
) -> dict:
    """Helper to build consistent dict for hashing from all source fields."""
    return {
        "title": journal_title,
        "print_issn": print_issn,
        "e_issn": e_issn,
        "publisher": publisher,
        "country": country,
        "scopus_status": scopus_status,
        "scopus_match_type": scopus_match_type,
        "scopus_source_title": scopus_source_title,
        "scopus_sourcerecord_id": scopus_sourcerecord_id,
        "scopus_publisher": scopus_publisher,
        "scopus_coverage": scopus_coverage,
        "scopus_issn": scopus_issn,
        "scopus_eissn": scopus_eissn,
        "mjl_status": mjl_status,
        "mjl_index": mjl_index,
        "mjl_issn_used": mjl_issn_used,
        "mjl_source_title": mjl_source_title,
        "scimago_status": scimago_status,
        "scimago_journal_id": scimago_journal_id,
        "scimago_matched_issn": scimago_matched_issn,
        "sjr": sjr,
        "quartile": quartile,
        "h_index": h_index,
        "scimago_coverage": scimago_coverage,
        "scimago_url": scimago_url,
    }
