-- ===================================================================
-- Journal Data Validation & Approval Layer
-- Extends existing schema.sql — run AFTER the base schema.
-- Implements: Automated Collection → Validation → Human Approval → Production
-- ===================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -------------------------------------------------------------------
-- 1. Extend pipeline_runs with approval workflow
-- -------------------------------------------------------------------
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pipeline_runs' AND column_name='validation_status') THEN
    ALTER TABLE pipeline_runs ADD COLUMN validation_status TEXT NOT NULL DEFAULT 'direct'
      CHECK (validation_status IN ('direct','pending_review','approved','rejected','partially_approved'));
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pipeline_runs' AND column_name='requires_approval') THEN
    ALTER TABLE pipeline_runs ADD COLUMN requires_approval BOOLEAN NOT NULL DEFAULT false;
  END IF;
END $$;

-- -------------------------------------------------------------------
-- 2. Change Proposals — the validation boundary
-- Each pipeline run in validation mode creates one row per NEW / MODIFIED /
-- POTENTIALLY REMOVED journal. UNCHANGED journals do NOT create proposals
-- (they are just touched). Admin approves/rejects each proposal; approved
-- proposals are then applied to production tables.
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS change_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_run_id UUID NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    journal_id UUID REFERENCES journals(id) ON DELETE SET NULL, -- NULL for NEW journals
    sl_no TEXT,
    change_type TEXT NOT NULL CHECK (change_type IN ('NEW','MODIFIED','REMOVED')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    -- Snapshots for audit / UI
    old_data JSONB,        -- null for NEW; production snapshot for MODIFIED/REMOVED
    new_data JSONB,        -- null for REMOVED; collected snapshot for NEW/MODIFIED
    diff_summary JSONB,    -- [{source, field, old_value, new_value}] for MODIFIED
    -- Child payloads so approval can replay without re-scraping
    journal_payload JSONB, -- journals row to insert/update
    cfr_payload JSONB,
    scopus_payload JSONB,
    mjl_payload JSONB,
    scimago_payload JSONB,
    apc_payload JSONB,     -- array of apc rows (1:many)
    data_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT,
    review_note TEXT
);

CREATE INDEX IF NOT EXISTS change_proposals_pipeline_run_id_idx ON change_proposals(pipeline_run_id);
CREATE INDEX IF NOT EXISTS change_proposals_journal_id_idx ON change_proposals(journal_id);
CREATE INDEX IF NOT EXISTS change_proposals_status_idx ON change_proposals(status);
CREATE INDEX IF NOT EXISTS change_proposals_change_type_idx ON change_proposals(change_type);
-- Unique index enforcing max 1 PENDING proposal per existing journal
CREATE UNIQUE INDEX IF NOT EXISTS change_proposals_pending_journal_idx ON change_proposals(journal_id) WHERE status = 'PENDING' AND journal_id IS NOT NULL;
-- Unique index enforcing max 1 PENDING proposal per new journal (sl_no)
CREATE UNIQUE INDEX IF NOT EXISTS change_proposals_pending_new_sl_no_idx ON change_proposals(sl_no) WHERE status = 'PENDING' AND change_type = 'NEW' AND sl_no IS NOT NULL;

-- -------------------------------------------------------------------
-- 3. Optionally track journals that disappeared from CFR source
-- (Not a separate table — REMOVED proposals in change_proposals cover it,
--  but this view helps admin.)
-- -------------------------------------------------------------------
-- No extra table needed; REMOVED proposals have change_type='REMOVED'.

-- -------------------------------------------------------------------
-- 4. Helper view: pending proposals per run
-- -------------------------------------------------------------------
CREATE OR REPLACE VIEW v_pending_proposals AS
SELECT
    p.id,
    p.pipeline_run_id,
    pr.started_at,
    p.journal_id,
    p.sl_no,
    p.change_type,
    p.status,
    p.diff_summary,
    p.created_at
FROM change_proposals p
JOIN pipeline_runs pr ON pr.id = p.pipeline_run_id
WHERE p.status = 'PENDING'
ORDER BY pr.started_at DESC, p.change_type, p.sl_no;

-- -------------------------------------------------------------------
-- 5. Comments
-- -------------------------------------------------------------------
COMMENT ON TABLE change_proposals IS 'Validation & Approval Layer: each NEW/MODIFIED/REMOVED journal from a pipeline run requires admin approval before touching production tables.';
COMMENT ON COLUMN change_proposals.old_data IS 'JSON snapshot of production row + children before change (null for NEW)';
COMMENT ON COLUMN change_proposals.new_data IS 'JSON snapshot of collected data for this run (null for REMOVED)';
COMMENT ON COLUMN change_proposals.diff_summary IS 'Field-level diff array [{source, field, old_value, new_value}] for MODIFIED; empty for NEW/REMOVED';
