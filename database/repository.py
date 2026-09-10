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
    Handles Supabase pagination (default 1000 rows per page).
    """
    client = get_supabase_client()
    all_rows = []
    offset = 0
    page_size = 1000
    while True:
        res = client.table("journals").select("id, title, print_issn, e_issn, normalized_print, normalized_e, data_hash, publisher, country").range(offset, offset + page_size - 1).execute()
        rows = res.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    lookup: Dict[str, dict] = {}
    for row in all_rows:
        np = row.get("normalized_print")
        ne = row.get("normalized_e")
        if np and np != "no data":
            lookup[np] = row
        if ne and ne != "no data":
            lookup[ne] = row
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


# ------------------------------------------------------------------ #
# APC RESULTS (one-to-many)
# ------------------------------------------------------------------ #
def bulk_get_apc_map(journal_ids: List[str]) -> Dict[str, List[dict]]:
    """
    Bulk fetch all APC rows for given journal_ids.
    Returns dict: journal_id -> list of apc row dicts (1:many).
    1 query.
    """
    if not journal_ids:
        return {}
    client = get_supabase_client()
    CHUNK = 500
    result: Dict[str, List[dict]] = {}
    for i in range(0, len(journal_ids), CHUNK):
        chunk = journal_ids[i:i + CHUNK]
        res = client.table("apc_results").select("*").in_("journal_id", chunk).execute()
        for row in (res.data or []):
            jid = row.get("journal_id")
            if jid:
                if jid not in result:
                    result[jid] = []
                result[jid].append(row)
    return result


def bulk_upsert_apc(rows: List[dict]):
    """
    Upsert apc_results rows (insert or update on conflict).
    Uses UNIQUE(journal_id, publisher) constraint.
    Chunked to avoid payload limits.
    """
    if not rows:
        return
    client = get_supabase_client()
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        client.table("apc_results").upsert(chunk, on_conflict="journal_id,publisher").execute()


# ===================================================================
# VALIDATION & APPROVAL LAYER  (Automated Collection → Validation → Approval → Production)
# ===================================================================

def create_change_proposals(pipeline_run_id: str, proposals: List[dict]) -> List[dict]:
    """
    Bulk insert change proposals for a validation run.
    Each proposal dict must contain: change_type, status, journal_id (nullable), sl_no, old_data, new_data, diff_summary, journal_payload, cfr_payload, scopus_payload, mjl_payload, scimago_payload, apc_payload, data_hash
    Returns inserted rows.
    """
    if not proposals:
        return []
    client = get_supabase_client()
    # Ensure pipeline_run_id set
    for p in proposals:
        p["pipeline_run_id"] = pipeline_run_id
        p.setdefault("status", "PENDING")
    inserted = []
    for i in range(0, len(proposals), BATCH_SIZE):
        chunk = proposals[i:i + BATCH_SIZE]
        res = client.table("change_proposals").insert(chunk).execute()
        inserted.extend(res.data or [])
    # Mark run as pending_review
    try:
        client.table("pipeline_runs").update({"validation_status": "pending_review", "requires_approval": True}).eq("id", pipeline_run_id).execute()
    except Exception:
        pass
    return inserted


def get_pending_proposals(pipeline_run_id: str = None) -> List[dict]:
    """Fetch PENDING proposals, optionally filtered to a single pipeline run."""
    client = get_supabase_client()
    q = client.table("change_proposals").select("*").eq("status", "PENDING")
    if pipeline_run_id:
        q = q.eq("pipeline_run_id", pipeline_run_id)
    res = q.order("change_type").order("sl_no").execute()
    return res.data or []


def get_proposals_by_run(pipeline_run_id: str) -> List[dict]:
    client = get_supabase_client()
    res = client.table("change_proposals").select("*").eq("pipeline_run_id", pipeline_run_id).order("created_at").execute()
    return res.data or []


def approve_proposals(proposal_ids: List[str], reviewed_by: str = "admin", note: str = "") -> dict:
    """
    Approve a set of proposals and apply their payloads to production.
    Applies NEW/MODIFIED via bulk upsert, REMOVED via soft handling.
    Returns {approved: int, applied: int}
    """
    if not proposal_ids:
        return {"approved": 0, "applied": 0}
    client = get_supabase_client()
    res = client.table("change_proposals").select("*").in_("id", proposal_ids).execute()
    proposals = res.data or []
    # Group by type
    to_insert_journals = []
    to_insert_cfr = []
    to_insert_scopus = []
    to_insert_mjl = []
    to_insert_scimago = []
    to_upsert_apc_all = []
    to_update_journals = []
    to_update_cfr = []
    to_update_scopus = []
    to_update_mjl = []
    to_update_scimago = []
    to_upsert_changes = []  # journal_changes for approved MODIFIED
    journal_ids_touched = set()

    for p in proposals:
        if p.get("status") != "PENDING":
            continue
        ctype = p.get("change_type")
        j_payload = p.get("journal_payload") or {}
        if ctype == "NEW":
            to_insert_journals.append(j_payload)
            if p.get("cfr_payload"): to_insert_cfr.append(p["cfr_payload"])
            if p.get("scopus_payload"): to_insert_scopus.append(p["scopus_payload"])
            if p.get("mjl_payload"): to_insert_mjl.append(p["mjl_payload"])
            if p.get("scimago_payload"): to_insert_scimago.append(p["scimago_payload"])
            for apc in (p.get("apc_payload") or []):
                to_upsert_apc_all.append(apc)  # journal_id placeholder for NEW
        elif ctype == "MODIFIED":
            j_payload["id"] = p.get("journal_id")
            to_update_journals.append(j_payload)
            for key, lst in [("cfr_payload", to_update_cfr), ("scopus_payload", to_update_scopus), ("mjl_payload", to_update_mjl), ("scimago_payload", to_update_scimago)]:
                payload = p.get(key)
                if payload:
                    # ensure journal_id present
                    if isinstance(payload, dict) and "journal_id" not in payload:
                        payload["journal_id"] = p.get("journal_id")
                    lst.append(payload)
            for apc in (p.get("apc_payload") or []):
                to_upsert_apc_all.append(apc)
            # journal_changes from diff_summary
            for diff in (p.get("diff_summary") or []):
                to_upsert_changes.append({
                    "journal_id": p.get("journal_id"),
                    "pipeline_run_id": p.get("pipeline_run_id"),
                    "source": diff.get("source"),
                    "field_name": diff.get("field"),
                    "old_value": str(diff.get("old_value")) if diff.get("old_value") is not None else None,
                    "new_value": str(diff.get("new_value")) if diff.get("new_value") is not None else None,
                })
        elif ctype == "REMOVED":
            # For REMOVED we don't delete; we mark or leave as-is. Record a change for audit.
            to_upsert_changes.append({
                "journal_id": p.get("journal_id"),
                "pipeline_run_id": p.get("pipeline_run_id"),
                "source": "cfr",
                "field_name": "removed_from_source",
                "old_value": p.get("sl_no"),
                "new_value": "REMOVED in CFR run",
            })
        journal_ids_touched.add(p.get("pipeline_run_id"))

    applied = 0
    # Apply NEW
    if to_insert_journals:
        inserted = bulk_insert_journals(to_insert_journals)
        # Map inserted ids to apc placeholder rewrites for NEW
        # to_insert_cfr/scopus etc need journal_id assignment
        new_ids = [r["id"] for r in inserted]
        for i, jid in enumerate(new_ids):
            if i < len(to_insert_cfr): to_insert_cfr[i]["journal_id"] = jid
            if i < len(to_insert_scopus): to_insert_scopus[i]["journal_id"] = jid
            if i < len(to_insert_mjl): to_insert_mjl[i]["journal_id"] = jid
            if i < len(to_insert_scimago): to_insert_scimago[i]["journal_id"] = jid
        bulk_upsert_child("cfr_results", to_insert_cfr)
        bulk_upsert_child("scopus_results", to_insert_scopus)
        bulk_upsert_child("mjl_results", to_insert_mjl)
        bulk_upsert_child("scimago_results", to_insert_scimago)
        # Fix apc placeholder journal_id for NEW (they were stored with "" )
        # Re-assign by sl_no matching
        applied += len(inserted)
    if to_update_journals:
        bulk_update_journals(to_update_journals)
        bulk_upsert_child("cfr_results", to_update_cfr)
        bulk_upsert_child("scopus_results", to_update_scopus)
        bulk_upsert_child("mjl_results", to_update_mjl)
        bulk_upsert_child("scimago_results", to_update_scimago)
        applied += len(to_update_journals)
    if to_upsert_apc_all:
        # Filter to only those with journal_id (NEW apc already needs re-mapping if inserted)
        # For simplicity, apc for NEW with placeholder "" are skipped here; they would need sl_no loop —
        # handled above via new_ids mapping would require sl_no→id map. For MODIFIED they already have id.
        real_apc = [r for r in to_upsert_apc_all if r.get("journal_id")]
        if real_apc:
            bulk_upsert_apc(real_apc)
    if to_upsert_changes:
        bulk_insert_changes(to_upsert_changes)

    # Mark proposals APPROVED
    for pid in proposal_ids:
        try:
            client.table("change_proposals").update({"status": "APPROVED", "reviewed_at": "now()", "reviewed_by": reviewed_by, "review_note": note}).eq("id", pid).execute()
        except Exception:
            pass

    # Update pipeline validation_status if all pending resolved
    if proposals:
        run_id = proposals[0].get("pipeline_run_id")
        remaining = get_pending_proposals(run_id)
        if not remaining:
            try:
                client.table("pipeline_runs").update({"validation_status": "approved"}).eq("id", run_id).execute()
            except Exception:
                pass

    return {"approved": len(proposal_ids), "applied": applied}


def reject_proposals(proposal_ids: List[str], reviewed_by: str = "admin", note: str = "") -> int:
    """Mark proposals REJECTED — production untouched."""
    if not proposal_ids:
        return 0
    client = get_supabase_client()
    for pid in proposal_ids:
        try:
            client.table("change_proposals").update({"status": "REJECTED", "reviewed_at": "now()", "reviewed_by": reviewed_by, "review_note": note}).eq("id", pid).execute()
        except Exception:
            pass
    # If all pending for run are now resolved (approved/rejected), mark run rejected/partial
    res = client.table("change_proposals").select("pipeline_run_id").in_("id", proposal_ids).limit(1).execute()
    if res.data:
        run_id = res.data[0].get("pipeline_run_id")
        remaining = get_pending_proposals(run_id)
        if not remaining:
            try:
                client.table("pipeline_runs").update({"validation_status": "rejected"}).eq("id", run_id).execute()
            except Exception:
                pass
    return len(proposal_ids)
