import pytest
from database.hash import compute_data_hash, build_hash_input


def test_hash_deterministic():
    rec = build_hash_input("Nature", "0028-0836", "1476-4687", "Springer", "UK", scopus_status="Active / Indexed", mjl_status="Found", mjl_index="SCIE", scimago_status="SUCCESS", sjr="9.5", quartile="Q1", h_index="400")
    h1 = compute_data_hash(rec)
    h2 = compute_data_hash(rec)
    assert h1 == h2
    assert len(h1) == 64  # SHA256


def test_hash_normalization_whitespace_casing():
    rec1 = build_hash_input("Nature ", "0028-0836", "1476-4687", "Springer", "UK")
    rec2 = build_hash_input("Nature", "0028-0836", "1476-4687", "Springer", "UK")
    assert compute_data_hash(rec1) == compute_data_hash(rec2)

    rec3 = build_hash_input("NATURE", "0028-0836", "1476-4687", "SPRINGER", "uk")
    assert compute_data_hash(rec1) == compute_data_hash(rec3)


def test_hash_none_vs_empty():
    rec1 = build_hash_input("Nature", "0028-0836", "", "Springer", "UK", sjr=None)
    rec2 = build_hash_input("Nature", "0028-0836", "no data", "Springer", "UK", sjr="")
    assert compute_data_hash(rec1) == compute_data_hash(rec2)


def test_hash_issn_formatting():
    rec1 = build_hash_input("Test", "0129-6612", "", "Pub", "USA")
    rec2 = build_hash_input("Test", "01296612", "", "Pub", "USA")
    # ISSN normalization in hash is lowercased, but hyphens stripped only in _normalize_value?
    # _normalize_value does s.lower() not strip hyphens, so these will differ.
    # However repository uses normalize_issn for ISSN fields separately.
    # For hash, we normalize via lower+strip, so hyphen matters - test documents this
    assert compute_data_hash(rec1) != compute_data_hash(rec2)  # expected difference
    # Correct way: pass normalized ISSN via build_hash_input after normalize_issn
    from processors.issn import normalize_issn
    rec3 = build_hash_input("Test", normalize_issn("0129-6612"), "", "Pub", "USA")
    rec4 = build_hash_input("Test", normalize_issn("01296612"), "", "Pub", "USA")
    assert compute_data_hash(rec3) == compute_data_hash(rec4)


def test_hash_changed_field():
    base = build_hash_input("Nature", "0028-0836", "", "Springer", "UK", h_index="400", quartile="Q1")
    changed = build_hash_input("Nature", "0028-0836", "", "Springer", "UK", h_index="401", quartile="Q1")
    assert compute_data_hash(base) != compute_data_hash(changed)
