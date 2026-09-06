import time
from typing import Dict, List, Optional, Tuple

from database.connection import get_supabase_client
from processors.issn import normalize_issn


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #
def _fetch_one(table: str, filters: dict):
    client = get_supabase_client()
    q = client.table(table).select("*")
    for k, v in filters.items():
        q = q.eq(k, v)
    res = q.limit(1).execute()
    data = res.data or []
    return data[0] if data else None


def _eq_or_is_null(col: str, val: str):
    # Helper for unique ISSN lookup where value may be 'no data'
    if val == "no data" or not val:
        return None
    return val


# ------------------------------------------------------------------ #
# JOURNALS
# ------------------------------------------------------------------ #
def get_journal_by_issn(print_issn_raw: str, e_issn_raw: str) -> Optional[dict]:
    """
    Find journal by normalized print_issn or e_issn.
    Both ISSN are individually unique (per spec).
    Tries print first, then e, also cross-checks.
    Returns full journal row dict or None.
    """
    norm_p = normalize_issn(print_issn_raw)
    norm_e = normalize_issn(e_issn_raw)
    client = get_supabase_client()

    # Try normalized_print
    for norm in (norm_p, norm_e):
        if norm == "no data" or not norm:
            continue
        # Check both columns for cross-ISSN match (P of new may match E of existing)
        # Query 1: normalized_print == norm
        res = client.table("journals").select("*").eq("normalized_print", norm).limit(1).execute()
        if res.data:
            return res.data[0]
        # Query 2: normalized_e == norm
        res = client.table("journals").select("*").eq("normalized_e", norm).limit(1).execute()
        if res.data:
            return res.data[0]

    # Fallback title+publisher exact normalized match could be added, but ISSN is primary
    return None


def get_journal(journal_id: str) -> Optional[dict]:
    client = get_supabase_client()
    res = client.table("journals").select("*").eq("id", journal_id).limit(1).execute()
    return res.data[0] if res.data else None


def get_all_journals_map() -> Dict[str, dict]:
    """
    Bulk fetch all journals for fast in-memory lookup.
    Returns dict with keys: normalized_print and normalized_e -> journal row.
    Single query instead of 500+ per-journal queries (were ~100s for 257 journals).
    """
    client = get_supabase_client()
    res = client.table("journals").select("id, title, print_issn, e_issn, normalized_print, normalized_e, data_hash, publisher, country").execute()
    rows = res.data or []
    lookup: Dict[str, dict] = {}
    for row in rows:
        np = row.get("normalized_print")
        ne = row.get("normalized_e")
        if np and np != "no data":
            lookup[np] = row
            # Also allow cross lookup: same row accessible via both keys
        if ne and ne != "no data":
            lookup[ne] = row
        # Also handle cross: if journal has both, both keys point to same row
    return lookup


def get_all_journals_raw() -> List[dict]:
    client = get_supabase_client()
    res = client.table("journals").select("*").execute()
    return res.data or []


def insert_journal_full(journal_data: dict, cfr_data: dict, scopus_data: dict, mjl_data: dict, scimago_data: dict, data_hash: str, pipeline_run_id: str) -> str:
    """
    Insert journal + all source results in order.
    Returns journal_id.
    Designed for new journals (Case A).
    Uses sequential inserts; documented consistency: if scimago insert fails after journal, journal remains but flagged via pipeline_run failed_records.
    """
    client = get_supabase_client()
    # Insert journal
    norm_p = normalize_issn(journal_data.get("print_issn", ""))
    norm_e = normalize_issn(journal_data.get("e_issn", ""))
    journal_row = {
        "title": journal_data.get("title", ""),
        "print_issn": journal_data.get("print_issn", ""),
        "e_issn": journal_data.get("e_issn", ""),
        "normalized_print": norm_p,
        "normalized_e": norm_e,
        "publisher": journal_data.get("publisher", ""),
        "country": journal_data.get("country", ""),
        "data_hash": data_hash,
        "first_seen_at": "now()",
        "last_checked_at": "now()",
        "last_changed_at": "now()",
        "last_seen_pipeline_run_id": pipeline_run_id,
    }
    res = client.table("journals").insert(journal_row).execute()
    journal_id = res.data[0]["id"]

    # CFR
    cfr_row = {"journal_id": journal_id, **cfr_data}
    client.table("cfr_results").insert(cfr_row).execute()

    # Scopus
    if scopus_data:
        scopus_row = {"journal_id": journal_id, **scopus_data}
        client.table("scopus_results").insert(scopus_row).execute()

    # MJL
    if mjl_data:
        mjl_row = {"journal_id": journal_id, **mjl_data}
        client.table("mjl_results").insert(mjl_row).execute()

    # SCImago
    if scimago_data:
        scimago_row = {"journal_id": journal_id, **scimago_data}
        client.table("scimago_results").insert(scimago_row).execute()

    return journal_id


def update_journal_full(journal_id: str, journal_data: dict, cfr_data: dict, scopus_data: dict, mjl_data: dict, scimago_data: dict, data_hash: str, pipeline_run_id: str, changes: List[Tuple[str, str, str, str]]):
    """
    Update journal + source results for existing changed journal (Case C).
    changes: list of (source, field_name, old_value, new_value)
    """
    client = get_supabase_client()
    norm_p = normalize_issn(journal_data.get("print_issn", ""))
    norm_e = normalize_issn(journal_data.get("e_issn", ""))

    # Update journals master
    client.table("journals").update({
        "title": journal_data.get("title", ""),
        "print_issn": journal_data.get("print_issn", ""),
        "e_issn": journal_data.get("e_issn", ""),
        "normalized_print": norm_p,
        "normalized_e": norm_e,
        "publisher": journal_data.get("publisher", ""),
        "country": journal_data.get("country", ""),
        "data_hash": data_hash,
        "last_checked_at": "now()",
        "last_changed_at": "now()",
        "last_seen_pipeline_run_id": pipeline_run_id,
    }).eq("id", journal_id).execute()

    # Upsert source tables (update if exists)
    if cfr_data is not None:
        # Use upsert via update (cfr_results has unique journal_id)
        existing = client.table("cfr_results").select("journal_id").eq("journal_id", journal_id).limit(1).execute()
        if existing.data:
            client.table("cfr_results").update(cfr_data).eq("journal_id", journal_id).execute()
        else:
            client.table("cfr_results").insert({"journal_id": journal_id, **cfr_data}).execute()

    if scopus_data is not None:
        existing = client.table("scopus_results").select("journal_id").eq("journal_id", journal_id).limit(1).execute()
        if existing.data:
            client.table("scopus_results").update(scopus_data).eq("journal_id", journal_id).execute()
        else:
            client.table("scopus_results").insert({"journal_id": journal_id, **scopus_data}).execute()

    if mjl_data is not None:
        existing = client.table("mjl_results").select("journal_id").eq("journal_id", journal_id).limit(1).execute()
        if existing.data:
            client.table("mjl_results").update(mjl_data).eq("journal_id", journal_id).execute()
        else:
            client.table("mjl_results").insert({"journal_id": journal_id, **mjl_data}).execute()

    if scimago_data is not None:
        existing = client.table("scimago_results").select("journal_id").eq("journal_id", journal_id).limit(1).execute()
        if existing.data:
            client.table("scimago_results").update(scimago_data).eq("journal_id", journal_id).execute()
        else:
            client.table("scimago_results").insert({"journal_id": journal_id, **scimago_data}).execute()

    # Record changes
    for source, field_name, old_v, new_v in changes:
        record_change(journal_id, pipeline_run_id, source, field_name, old_v, new_v)

    # For unchanged case, still update last_checked_at without last_changed_at
    return journal_id


def touch_journal_checked(journal_id: str, pipeline_run_id: str):
    """Mark existing unchanged journal as checked (Case B)."""
    client = get_supabase_client()
    client.table("journals").update({
        "last_checked_at": "now()",
        "last_seen_pipeline_run_id": pipeline_run_id,
    }).eq("id", journal_id).execute()


# ------------------------------------------------------------------ #
# PIPELINE RUNS
# ------------------------------------------------------------------ #
def create_pipeline_run(total_cfr: int) -> str:
    client = get_supabase_client()
    res = client.table("pipeline_runs").insert({
        "started_at": "now()",
        "status": "running",
        "total_cfr": total_cfr,
    }).execute()
    return res.data[0]["id"]


def finish_pipeline_run(run_id: str, status: str, duration: float, stats: dict, error: str = None):
    client = get_supabase_client()
    payload = {
        "finished_at": "now()",
        "duration_seconds": duration,
        "status": status,
        "total_scopus_active": stats.get("total_scopus_active"),
        "total_mjl_processed": stats.get("total_mjl_processed"),
        "total_scimago_processed": stats.get("total_scimago_processed"),
        "new_records": stats.get("new_records", 0),
        "updated_records": stats.get("updated_records", 0),
        "unchanged_records": stats.get("unchanged_records", 0),
        "failed_records": stats.get("failed_records", 0),
        "duplicate_skipped": stats.get("duplicate_skipped", 0),
    }
    if error:
        payload["error"] = error
    # duplicate_skipped column may not exist on old DB - try, fallback without it
    try:
        client.table("pipeline_runs").update(payload).eq("id", run_id).execute()
    except Exception as e:
        if "duplicate_skipped" in str(e):
            payload.pop("duplicate_skipped", None)
            client.table("pipeline_runs").update(payload).eq("id", run_id).execute()
        else:
            raise


# ------------------------------------------------------------------ #
# CHANGES
# ------------------------------------------------------------------ #
def record_change(journal_id: str, pipeline_run_id: str, source: str, field_name: str, old_value: Optional[str], new_value: Optional[str]):
    client = get_supabase_client()
    client.table("journal_changes").insert({
        "journal_id": journal_id,
        "pipeline_run_id": pipeline_run_id,
        "source": source,
        "field_name": field_name,
        "old_value": str(old_value) if old_value is not None else None,
        "new_value": str(new_value) if new_value is not None else None,
    }).execute()


def get_existing_full(journal_id: str) -> dict:
    """
    Fetch full existing data for hash comparison and field diff.
    Returns dict with keys for all sources.
    """
    client = get_supabase_client()
    journal = client.table("journals").select("*").eq("id", journal_id).limit(1).execute().data[0]
    cfr = client.table("cfr_results").select("*").eq("journal_id", journal_id).limit(1).execute()
    scopus = client.table("scopus_results").select("*").eq("journal_id", journal_id).limit(1).execute()
    mjl = client.table("mjl_results").select("*").eq("journal_id", journal_id).limit(1).execute()
    scimago = client.table("scimago_results").select("*").eq("journal_id", journal_id).limit(1).execute()
    return {
        "journal": journal,
        "cfr": cfr.data[0] if cfr.data else {},
        "scopus": scopus.data[0] if scopus.data else {},
        "mjl": mjl.data[0] if mjl.data else {},
        "scimago": scimago.data[0] if scimago.data else {},
    }


def insert_skipped_record(pipeline_run_id: str, journal_title: str, print_issn: str, e_issn: str, normalized_print: str, normalized_e: str, publisher: str, country: str, sl_no: str, reason: str, duplicate_of_issn: str, duplicate_of_title: str):
    """Insert a skipped (deduplicated) CFR record for audit."""
    client = get_supabase_client()
    try:
        client.table("skipped_records").insert({
            "pipeline_run_id": pipeline_run_id,
            "sl_no": sl_no,
            "journal_title": journal_title,
            "print_issn": print_issn,
            "e_issn": e_issn,
            "normalized_print": normalized_print,
            "normalized_e": normalized_e,
            "publisher": publisher,
            "country": country,
            "reason": reason,
            "duplicate_of_issn": duplicate_of_issn,
            "duplicate_of_title": duplicate_of_title,
        }).execute()
    except Exception as e:
        # Table may not exist on old DB - log and continue
        print(f"[WARNING] Could not insert skipped_records (table may not exist): {e}")


def get_skipped_records(pipeline_run_id: str) -> List[dict]:
    client = get_supabase_client()
    res = client.table("skipped_records").select("*").eq("pipeline_run_id", pipeline_run_id).execute()
    return res.data or []


# ------------------------------------------------------------------ #
# BULK READS (5 queries total for all journals + child tables)
# ------------------------------------------------------------------ #
def bulk_get_child_map(table: str, journal_ids: List[str], id_col: str = "journal_id") -> Dict[str, dict]:
    """
    Bulk fetch all rows from a child table for given journal_ids.
    Returns dict: journal_id -> row (first match if multiple).
    1 query per table.
    """
    if not journal_ids:
        return {}
    client = get_supabase_client()
    CHUNK = 500
    result = {}
    for i in range(0, len(journal_ids), CHUNK):
        chunk = journal_ids[i:i + CHUNK]
        res = client.table(table).select("*").in_(id_col, chunk).execute()
        for row in (res.data or []):
            jid = row.get(id_col)
            if jid and jid not in result:
                result[jid] = row
    return result


# ------------------------------------------------------------------ #
# BULK WRITES
# ------------------------------------------------------------------ #
BATCH_SIZE = 80


def bulk_touch_journals(journal_ids: List[str], pipeline_run_id: str):
    """Update last_checked_at + last_seen_pipeline_run_id for unchanged journals. 1 query."""
    if not journal_ids:
        return
    client = get_supabase_client()
    CHUNK = 500
    for i in range(0, len(journal_ids), CHUNK):
        chunk = journal_ids[i:i + CHUNK]
        client.table("journals").update({
            "last_checked_at": "now()",
            "last_seen_pipeline_run_id": pipeline_run_id,
        }).in_("id", chunk).execute()


def bulk_update_journals(rows: List[dict]):
    """
    Bulk update changed journals. Each row must have 'id' key.
    1 query (chunked).
    """
    if not rows:
        return
    client = get_supabase_client()
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        client.table("journals").upsert(chunk, on_conflict="id").execute()


def bulk_insert_journals(rows: List[dict]) -> List[dict]:
    """
    Bulk insert new journals. Returns list of inserted rows with IDs.
    Chunked to avoid payload limits.
    """
    if not rows:
        return []
    client = get_supabase_client()
    inserted = []
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        res = client.table("journals").insert(chunk).execute()
        inserted.extend(res.data or [])
    return inserted


def bulk_upsert_child(table: str, rows: List[dict], id_col: str = "journal_id"):
    """
    Bulk upsert child table rows (cfr/scopus/mjl/scimago).
    Uses update+insert fallback since Supabase PostgREST upsert needs unique constraint.
    1 query per chunk.
    """
    if not rows:
        return
    client = get_supabase_client()
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        client.table(table).upsert(chunk, on_conflict=id_col).execute()


def bulk_insert_changes(changes: List[dict]):
    """Bulk insert journal_changes rows. 1 query."""
    if not changes:
        return
    client = get_supabase_client()
    for i in range(0, len(changes), BATCH_SIZE):
        chunk = changes[i:i + BATCH_SIZE]
        client.table("journal_changes").insert(chunk).execute()
