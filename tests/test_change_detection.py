"""
Test incremental behavior per spec section 22.
Uses mocked repository (in-memory dict) to avoid real Supabase.
"""
import pytest
from unittest.mock import MagicMock, patch
from database.hash import build_hash_input, compute_data_hash
from models import CFRJournal

# Helper to create journal record similar to main.py results
def make_record(title="Nature", print_issn="0028-0836", e_issn="1476-4687", publisher="Springer", country="UK",
                scopus_status="Active / Indexed", mjl_status="Found", mjl_index="SCIE", scimago_status="SUCCESS",
                sjr="9.5", quartile="Q1", h_index="400", coverage="2020-2024"):
    return {
        "Full Journal Title": title,
        "Print-ISSN": print_issn,
        "E-ISSN": e_issn,
        "Publisher": publisher,
        "Country": country,
        "Scopus Indexing Status": scopus_status,
        "Scopus Match Type": "Print ISSN",
        "Scopus Source Record ID": "123",
        "Scopus Source Title": title,
        "Scopus Publisher": publisher,
        "Scopus Coverage": coverage,
        "MJL Status": mjl_status,
        "MJL Index": mjl_index,
        "MJL Matched ISSN": print_issn,
        "MJL Source Title": title,
        "SCImago Matched ISSN": print_issn,
        "SCImago Journal ID": "12345",
        "SJR": sjr,
        "Quartile": quartile,
        "H-Index": h_index,
        "SCImago Coverage": coverage,
        "SCImago URL": "https://example.com",
        "SCImago Status": scimago_status,
        "SCImago Error": "",
    }

def make_hash(rec):
    return compute_data_hash(build_hash_input(
        journal_title=rec["Full Journal Title"],
        print_issn=rec["Print-ISSN"],
        e_issn=rec["E-ISSN"],
        publisher=rec["Publisher"],
        country=rec["Country"],
        scopus_status=rec["Scopus Indexing Status"],
        scopus_match_type=rec["Scopus Match Type"],
        scopus_source_title=rec["Scopus Source Title"],
        scopus_sourcerecord_id=rec["Scopus Source Record ID"],
        scopus_publisher=rec["Scopus Publisher"],
        scopus_coverage=rec["Scopus Coverage"],
        mjl_status=rec["MJL Status"],
        mjl_index=rec["MJL Index"],
        mjl_issn_used=rec["MJL Matched ISSN"],
        mjl_source_title=rec["MJL Source Title"],
        scimago_status=rec["SCImago Status"],
        scimago_journal_id=rec["SCImago Journal ID"],
        scimago_matched_issn=rec["SCImago Matched ISSN"],
        sjr=rec["SJR"],
        quartile=rec["Quartile"],
        h_index=rec["H-Index"],
        scimago_coverage=rec["SCImago Coverage"],
        scimago_url=rec["SCImago URL"],
    ))

# In-memory mock DB
class MockDB:
    def __init__(self):
        self.journals = {}  # key -> {data_hash, rec}
        self.changes = []

    def get_journal_by_issn(self, p, e):
        from processors.issn import normalize_issn
        np = normalize_issn(p)
        ne = normalize_issn(e)
        for v in self.journals.values():
            if v["rec"]["Print-ISSN"] == p or v["rec"]["E-ISSN"] == e:
                # Simplified: match either
                if np != "no data" and normalize_issn(v["rec"]["Print-ISSN"]) == np:
                    return {"id": v["id"], "data_hash": v["hash"], "rec": v["rec"]}
                if ne != "no data" and normalize_issn(v["rec"]["E-ISSN"]) == ne:
                    return {"id": v["id"], "data_hash": v["hash"], "rec": v["rec"]}
        return None

    def insert(self, rec):
        h = make_hash(rec)
        jid = f"id-{len(self.journals)+1}"
        self.journals[jid] = {"id": jid, "hash": h, "rec": rec}
        return jid, "new"

    def upsert(self, rec):
        existing = self.get_journal_by_issn(rec["Print-ISSN"], rec["E-ISSN"])
        if not existing:
            return self.insert(rec)
        old_hash = existing["data_hash"]
        new_hash = make_hash(rec)
        if old_hash == new_hash:
            return existing["id"], "unchanged"
        # Determine changed fields
        old_rec = existing["rec"]
        changed_fields = []
        for k in rec:
            if str(rec[k] or "").strip() != str(old_rec.get(k, "") or "").strip():
                changed_fields.append(k)
                self.changes.append((k, old_rec.get(k), rec[k]))
        # update
        self.journals[existing["id"]] = {"id": existing["id"], "hash": new_hash, "rec": rec}
        return existing["id"], f"updated:{changed_fields}"


def test_case_A_empty_db_insert():
    db = MockDB()
    rec = make_record()
    assert db.get_journal_by_issn(rec["Print-ISSN"], rec["E-ISSN"]) is None
    jid, status = db.insert(rec)
    assert status == "new"
    assert jid.startswith("id-")


def test_case_B_unchanged():
    db = MockDB()
    rec = make_record()
    db.insert(rec)
    existing = db.get_journal_by_issn(rec["Print-ISSN"], rec["E-ISSN"])
    assert existing is not None
    jid2, status = db.upsert(rec)
    assert status == "unchanged"
    assert len(db.changes) == 0


def test_case_C_single_field_changed():
    db = MockDB()
    rec = make_record(h_index="120", quartile="Q2", sjr="0.842")
    db.insert(rec)
    rec2 = make_record(h_index="121", quartile="Q2", sjr="0.842")
    jid, status = db.upsert(rec2)
    assert "updated" in status
    # Should have 1 change for H-Index
    h_changes = [c for c in db.changes if c[0] == "H-Index"]
    assert len(h_changes) == 1
    assert h_changes[0][1] == "120"
    assert h_changes[0][2] == "121"


def test_case_D_multiple_fields_changed():
    db = MockDB()
    rec = make_record(h_index="120", quartile="Q2", sjr="0.842")
    db.insert(rec)
    rec2 = make_record(h_index="121", quartile="Q1", sjr="0.901")
    db.changes.clear()
    jid, status = db.upsert(rec2)
    assert "updated" in status
    # Expect 3 changes: H-Index, Quartile, SJR
    assert len(db.changes) == 3
    fields = {c[0] for c in db.changes}
    assert fields == {"H-Index", "Quartile", "SJR"}


def test_case_E_normalization():
    db = MockDB()
    rec1 = make_record(title="Nature ", print_issn="0028-0836")
    rec2 = make_record(title="Nature", print_issn="0028-0836")
    h1 = make_hash(rec1)
    h2 = make_hash(rec2)
    assert h1 == h2  # whitespace normalized

    db.insert(rec1)
    jid, status = db.upsert(rec2)
    assert status == "unchanged"

    # ISSN formatting
    rec3 = make_record(title="Test", print_issn="0129-6612")
    rec4 = make_record(title="Test", print_issn="01296612")
    # These raw hashes differ, but via normalized ISSN they should be same when using normalize_issn
    from processors.issn import normalize_issn
    rec3n = make_record(title="Test", print_issn=normalize_issn("0129-6612"))
    rec4n = make_record(title="Test", print_issn=normalize_issn("01296612"))
    assert make_hash(rec3n) == make_hash(rec4n)
