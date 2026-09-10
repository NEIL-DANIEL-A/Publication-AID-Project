-- Publication-AID Supabase Schema
-- Run in Supabase SQL Editor (single execution)
-- Requires pgcrypto for gen_random_uuid()

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ===================================================================
-- JOURNALS (master)
-- ===================================================================
CREATE TABLE IF NOT EXISTS journals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    print_issn TEXT,
    e_issn TEXT,
    normalized_print TEXT,
    normalized_e TEXT,
    publisher TEXT,
    country TEXT,
    data_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_changed_at TIMESTAMPTZ,
    last_seen_pipeline_run_id UUID
);

-- Both ISSN individually unique when present and not 'no data'
CREATE UNIQUE INDEX IF NOT EXISTS journals_print_issn_uq ON journals(normalized_print) WHERE normalized_print IS NOT NULL AND normalized_print <> 'no data' AND normalized_print <> '';
CREATE UNIQUE INDEX IF NOT EXISTS journals_eissn_uq ON journals(normalized_e) WHERE normalized_e IS NOT NULL AND normalized_e <> 'no data' AND normalized_e <> '';
CREATE INDEX IF NOT EXISTS journals_data_hash_idx ON journals(data_hash);
CREATE INDEX IF NOT EXISTS journals_title_idx ON journals(title);
CREATE INDEX IF NOT EXISTS journals_last_checked_idx ON journals(last_checked_at);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS journals_updated_at ON journals;
CREATE TRIGGER journals_updated_at BEFORE UPDATE ON journals FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===================================================================
-- CFR RESULTS (one-to-one)
-- ===================================================================
CREATE TABLE IF NOT EXISTS cfr_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_id UUID NOT NULL REFERENCES journals(id) ON DELETE CASCADE,
    sl_no TEXT,
    journal_title TEXT,
    print_issn TEXT,
    e_issn TEXT,
    publisher TEXT,
    country TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(journal_id)
);
CREATE INDEX IF NOT EXISTS cfr_results_journal_id_idx ON cfr_results(journal_id);
DROP TRIGGER IF EXISTS cfr_results_updated_at ON cfr_results;
CREATE TRIGGER cfr_results_updated_at BEFORE UPDATE ON cfr_results FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===================================================================
-- SCOPUS RESULTS (one-to-one)
-- ===================================================================
CREATE TABLE IF NOT EXISTS scopus_results (
    journal_id UUID PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
    scopus_status TEXT,
    match_type TEXT,
    sourcerecord_id TEXT,
    source_title TEXT,
    scopus_publisher TEXT,
    scopus_coverage TEXT,
    scopus_issn TEXT,
    scopus_eissn TEXT,
    raw_active_status TEXT,
    raw_discontinued_flag TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS scopus_results_status_idx ON scopus_results(scopus_status);
DROP TRIGGER IF EXISTS scopus_results_updated_at ON scopus_results;
CREATE TRIGGER scopus_results_updated_at BEFORE UPDATE ON scopus_results FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===================================================================
-- MJL RESULTS (one-to-one)
-- ===================================================================
CREATE TABLE IF NOT EXISTS mjl_results (
    journal_id UUID PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
    mjl_status TEXT,
    mjl_index TEXT,
    mjl_issn_used TEXT,
    mjl_match_type TEXT,
    mjl_source_title TEXT,
    execution_time DOUBLE PRECISION,
    error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mjl_results_status_idx ON mjl_results(mjl_status);
DROP TRIGGER IF EXISTS mjl_results_updated_at ON mjl_results;
CREATE TRIGGER mjl_results_updated_at BEFORE UPDATE ON mjl_results FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===================================================================
-- SCIMAGO RESULTS (one-to-one)
-- ===================================================================
CREATE TABLE IF NOT EXISTS scimago_results (
    journal_id UUID PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
    scimago_status TEXT,
    journal_id_external TEXT,
    matched_issn TEXT,
    sjr TEXT,
    quartile TEXT,
    h_index TEXT,
    coverage TEXT,
    url TEXT,
    execution_time DOUBLE PRECISION,
    error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS scimago_results_status_idx ON scimago_results(scimago_status);
CREATE INDEX IF NOT EXISTS scimago_results_quartile_idx ON scimago_results(quartile);
DROP TRIGGER IF EXISTS scimago_results_updated_at ON scimago_results;
CREATE TRIGGER scimago_results_updated_at BEFORE UPDATE ON scimago_results FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===================================================================
-- PIPELINE RUNS
-- ===================================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    duration_seconds DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'running', -- running | success | failed
    total_cfr INT,
    total_scopus_active INT,
    total_mjl_processed INT,
    total_scimago_processed INT,
    new_records INT DEFAULT 0,
    updated_records INT DEFAULT 0,
    unchanged_records INT DEFAULT 0,
    failed_records INT DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS pipeline_runs_started_idx ON pipeline_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS pipeline_runs_status_idx ON pipeline_runs(status);

-- ===================================================================
-- JOURNAL CHANGES (history)
-- ===================================================================
CREATE TABLE IF NOT EXISTS journal_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_id UUID NOT NULL REFERENCES journals(id) ON DELETE CASCADE,
    pipeline_run_id UUID REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    source TEXT NOT NULL, -- cfr | scopus | mjl | scimago | journal
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS journal_changes_journal_id_idx ON journal_changes(journal_id);
CREATE INDEX IF NOT EXISTS journal_changes_pipeline_run_id_idx ON journal_changes(pipeline_run_id);
CREATE INDEX IF NOT EXISTS journal_changes_source_idx ON journal_changes(source);
CREATE INDEX IF NOT EXISTS journal_changes_changed_at_idx ON journal_changes(changed_at DESC);

-- ===================================================================
-- SKIPPED RECORDS (CFR deduplication audit)
-- ===================================================================
CREATE TABLE IF NOT EXISTS skipped_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_run_id UUID REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    sl_no TEXT,
    journal_title TEXT,
    print_issn TEXT,
    e_issn TEXT,
    normalized_print TEXT,
    normalized_e TEXT,
    publisher TEXT,
    country TEXT,
    reason TEXT NOT NULL, -- duplicate_issn
    duplicate_of_issn TEXT, -- which ISSN caused skip
    duplicate_of_title TEXT, -- title of kept record
    skipped_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS skipped_records_pipeline_run_id_idx ON skipped_records(pipeline_run_id);
CREATE INDEX IF NOT EXISTS skipped_records_print_issn_idx ON skipped_records(normalized_print);
CREATE INDEX IF NOT EXISTS skipped_records_e_issn_idx ON skipped_records(normalized_e);

-- ===================================================================
-- APC RESULTS (one-to-many: 1 journal can have multiple publisher APCs)
-- ===================================================================
CREATE TABLE IF NOT EXISTS apc_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_id UUID NOT NULL REFERENCES journals(id) ON DELETE CASCADE,
    publisher TEXT NOT NULL,           -- 'Wiley', 'Elsevier', 'Springer Nature'
    apc_value TEXT,                    -- raw string from file (e.g. '3500', '2950')
    apc_currency TEXT,                 -- 'USD', 'EUR', 'GBP', 'JPY'
    apc_mode_raw TEXT,                 -- raw OA mode from file (e.g. 'Gold', 'Hybrid')
    apc_mode_normalized TEXT,          -- lowercased + stripped version of apc_mode_raw
    source_file TEXT,                  -- which file this came from (for audit)
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS apc_results_journal_id_idx ON apc_results(journal_id);
CREATE INDEX IF NOT EXISTS apc_results_publisher_idx ON apc_results(publisher);
CREATE INDEX IF NOT EXISTS apc_results_mode_normalized_idx ON apc_results(apc_mode_normalized);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name='apc_results_journal_publisher_uniq') THEN
    ALTER TABLE apc_results ADD CONSTRAINT apc_results_journal_publisher_uniq UNIQUE (journal_id, publisher);
  END IF;
END $$;
-- GPOA discount columns (Elsevier geographical pricing 20% off)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='apc_results' AND column_name='has_gpoa_discount') THEN
    ALTER TABLE apc_results ADD COLUMN has_gpoa_discount BOOLEAN NOT NULL DEFAULT false;
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='apc_results' AND column_name='original_apc_value') THEN
    ALTER TABLE apc_results ADD COLUMN original_apc_value TEXT;
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='apc_results' AND column_name='discounted_apc_value') THEN
    ALTER TABLE apc_results ADD COLUMN discounted_apc_value TEXT;
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='apc_results' AND column_name='discount_percent') THEN
    ALTER TABLE apc_results ADD COLUMN discount_percent INT;
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='apc_results' AND column_name='is_highlighted') THEN
    ALTER TABLE apc_results ADD COLUMN is_highlighted BOOLEAN NOT NULL DEFAULT false;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS apc_results_gpoa_idx ON apc_results(has_gpoa_discount) WHERE has_gpoa_discount = true;
DROP TRIGGER IF EXISTS apc_results_updated_at ON apc_results;
CREATE TRIGGER apc_results_updated_at BEFORE UPDATE ON apc_results FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Add FK for journals.last_seen_pipeline_run_id after pipeline_runs exists
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name='journals_last_seen_run_fk') THEN
    ALTER TABLE journals ADD CONSTRAINT journals_last_seen_run_fk FOREIGN KEY (last_seen_pipeline_run_id) REFERENCES pipeline_runs(id) ON DELETE SET NULL;
  END IF;
END $$;

-- Add duplicate_skipped count to pipeline_runs if not exists
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pipeline_runs' AND column_name='duplicate_skipped') THEN
    ALTER TABLE pipeline_runs ADD COLUMN duplicate_skipped INT DEFAULT 0;
  END IF;
END $$;

-- Validation & Approval Layer is in schema_validation.sql — run it separately after this file
