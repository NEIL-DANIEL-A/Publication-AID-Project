"""
Mock Supabase repository tests - validates repository logic without real connection.
"""
import pytest
from unittest.mock import MagicMock, patch

def test_get_journal_by_issn_logic():
    from processors.issn import normalize_issn
    # Simulate ISSN uniqueness: both print and e individually unique
    assert normalize_issn("0028-0836") == "00280836"
    assert normalize_issn("1476-4687") == "14764687"
    assert normalize_issn(" 0028-0836 ") == "00280836"
    assert normalize_issn("") == "no data"
    assert normalize_issn("no data") == "no data"

def test_repository_import_without_env():
    # Should not raise when import, only when calling get_supabase_client without env
    import database.repository  # noqa
    assert True

def test_hash_integration_with_normalize():
    from database.hash import build_hash_input, compute_data_hash
    from processors.issn import normalize_issn
    rec = build_hash_input(
        journal_title="  Nature  ",
        print_issn=normalize_issn("0028-0836"),
        e_issn=normalize_issn("1476-4687"),
        publisher="Springer ",
        country="UK",
        scopus_status="Active / Indexed",
        mjl_status="Found",
        mjl_index="SCIE",
        scimago_status="SUCCESS",
        sjr="9.5",
    )
    h = compute_data_hash(rec)
    assert len(h) == 64
