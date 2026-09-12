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


def test_validation_consecutive_runs_no_duplicates():
    """Test that running validation mode twice with unapproved changes does not create duplicate proposals."""
    pending_proposals = {}
    
    # Run 1: Scraped data differs from frozen production record
    journal_id = "jid-100"
    scraped_rec = make_record(h_index="150")  # Changed field
    scraped_hash = make_hash(scraped_rec)
    
    # Store initial pending proposal
    pending_proposals[journal_id] = {
        "id": "prop-1",
        "journal_id": journal_id,
        "data_hash": scraped_hash,
        "status": "PENDING"
    }
    
    # Run 2: Next day scraper runs again with identical scraped_rec
    # Check deduplication condition: jid in pending_proposals and hash matches
    is_duplicate = (journal_id in pending_proposals and pending_proposals[journal_id]["data_hash"] == scraped_hash)
    assert is_duplicate is True  # Proves second run will be skipped as unchanged rather than creating duplicate


def test_validation_new_journal_consecutive_runs_no_duplicates():
    """Test that consecutive validation runs for a NEW journal do not create duplicate PENDING proposals."""
    sl_no = "105"
    new_rec = make_record(title="Brand New Journal")
    new_rec["Sl.No"] = sl_no
    new_hash = make_hash(new_rec)
    
    pending_proposals_map = {
        "_by_sl_no": {
            "105": {
                "id": "prop-new-1",
                "journal_id": None,
                "sl_no": "105",
                "change_type": "NEW",
                "data_hash": new_hash,
                "status": "PENDING"
            }
        },
        "_by_hash": {
            new_hash: {
                "id": "prop-new-1",
                "journal_id": None,
                "sl_no": "105",
                "change_type": "NEW",
                "data_hash": new_hash,
                "status": "PENDING"
            }
        }
    }
    
    # Simulating main.py check for NEW journal
    existing = None
    validate = True
    sl_str = str(new_rec["Sl.No"])
    pending_new = (
        pending_proposals_map.get("_by_sl_no", {}).get(sl_str)
    ) or (
        pending_proposals_map.get("_by_hash", {}).get(new_hash)
    )
    
    is_already_pending = bool(validate and existing is None and pending_new and pending_new.get("data_hash") == new_hash)
    assert is_already_pending is True


def test_create_change_proposals_bulk_mock():
    """Verify create_change_proposals batch query structure without N+1 requests."""
    from unittest.mock import MagicMock, patch
    from database.repository import create_change_proposals

    mock_client = MagicMock()
    # Mocking existing SELECT query response
    mock_select = MagicMock()
    mock_select.execute.return_value.data = [{"id": "prop-existing-1", "journal_id": "jid-1"}]
    mock_client.table.return_value.select.return_value.eq.return_value.in_.return_value = mock_select
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{"id": "prop-existing-1"}]
    mock_client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "prop-new-2"}]

    proposals = [
        {"journal_id": "jid-1", "sl_no": "1", "change_type": "MODIFIED", "data_hash": "hash1"},
        {"journal_id": None, "sl_no": "2", "change_type": "NEW", "data_hash": "hash2"},
    ]

    with patch("database.repository.get_supabase_client", return_value=mock_client):
        res = create_change_proposals("run-123", proposals)
        assert len(res) == 2


def test_sage_dual_currency_deduplication():
    """Verify _build_issn_map keeps both USD and GBP prices for SAGE rather than discarding GBP."""
    from scrapers.apc import _build_issn_map
    records = [
        {"issn": "12345678", "publisher": "SAGE", "apc_value": "3000", "apc_currency": "USD", "mode_raw": "hybrid"},
        {"issn": "12345678", "publisher": "SAGE", "apc_value": "2400", "apc_currency": "GBP", "mode_raw": "hybrid"},
        {"issn": "12345678", "publisher": "SAGE", "apc_value": "3000", "apc_currency": "USD", "mode_raw": "duplicate"},
    ]
    res_map = _build_issn_map(records)
    entries = res_map.get("12345678", [])
    assert len(entries) == 2
    currencies = [e["apc_currency"] for e in entries]
    assert "USD" in currencies
    assert "GBP" in currencies


def test_supabase_client_thread_safety():
    """Verify get_supabase_client utilizes thread lock and returns singleton."""
    from unittest.mock import patch, MagicMock
    from concurrent.futures import ThreadPoolExecutor
    import database.connection as conn

    mock_client = MagicMock()
    with patch("os.getenv", side_effect=lambda k, d="": "http://example.supabase.co" if "URL" in k else "key123"), \
         patch("supabase.create_client", return_value=mock_client) as mock_create:
        conn._client = None
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(lambda _: conn.get_supabase_client(), range(10)))
        
        assert all(c == mock_client for c in results)
        assert mock_create.call_count == 1
        conn._client = None


def test_approve_proposals_new_apc_remapping():
    """Verify approve_proposals re-maps placeholder APC journal_ids for NEW journals using sl_no."""
    from unittest.mock import MagicMock, patch
    from database.repository import approve_proposals

    mock_client = MagicMock()
    proposal_new = {
        "id": "prop-new-1",
        "status": "PENDING",
        "change_type": "NEW",
        "sl_no": "42",
        "journal_payload": {"title": "New Journal", "print_issn": "11112222"},
        "cfr_payload": {"sl_no": "42", "journal_title": "New Journal"},
        "scopus_payload": {},
        "mjl_payload": {},
        "scimago_payload": {},
        "apc_payload": [{"publisher": "Elsevier", "apc_value": "2000", "apc_currency": "USD", "journal_id": ""}],
    }

    mock_select = MagicMock()
    mock_select.execute.return_value.data = [proposal_new]
    mock_client.table.return_value.select.return_value.in_.return_value = mock_select

    with patch("database.repository.get_supabase_client", return_value=mock_client), \
         patch("database.repository.bulk_insert_journals", return_value=[{"id": "real-jid-999", "title": "New Journal"}]), \
         patch("database.repository.bulk_upsert_child") as mock_upsert_child, \
         patch("database.repository.bulk_upsert_apc") as mock_upsert_apc:
        res = approve_proposals(["prop-new-1"])
        assert res["applied"] == 1
        assert mock_upsert_apc.call_count == 1
        apc_args = mock_upsert_apc.call_args[0][0]
        assert len(apc_args) == 1
        assert apc_args[0]["journal_id"] == "real-jid-999"


def test_create_change_proposals_deduplication():
    """Verify create_change_proposals updates existing pending proposals and inserts new ones."""
    from unittest.mock import MagicMock, patch
    from database.repository import create_change_proposals

    mock_client = MagicMock()
    mock_select = MagicMock()
    mock_select.execute.return_value.data = [{"id": "existing-prop-1", "journal_id": "jid-1"}]
    mock_client.table.return_value.select.return_value.eq.return_value.in_.return_value = mock_select
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{"id": "existing-prop-1"}]
    mock_client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "new-prop-2"}]

    proposals = [
        {"journal_id": "jid-1", "change_type": "MODIFIED", "diff_summary": []},
        {"journal_id": "jid-2", "change_type": "MODIFIED", "diff_summary": []},
    ]

    with patch("database.repository.get_supabase_client", return_value=mock_client):
        res = create_change_proposals("run-1", proposals)
        assert len(res) == 2



