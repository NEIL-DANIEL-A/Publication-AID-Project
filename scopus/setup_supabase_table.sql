-- SQL Migration for Supabase table: Scopus_additional_data
-- Run this in your Supabase Dashboard -> SQL Editor

-- 1. Add the required columns to Scopus_additional_data
ALTER TABLE IF EXISTS public."Scopus_additional_data"
    ADD COLUMN IF NOT EXISTS journal_id UUID REFERENCES public.journals(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS journal_name TEXT,
    ADD COLUMN IF NOT EXISTS issn TEXT,
    ADD COLUMN IF NOT EXISTS e_issn TEXT,
    ADD COLUMN IF NOT EXISTS publisher TEXT,
    ADD COLUMN IF NOT EXISTS subject_area TEXT,
    ADD COLUMN IF NOT EXISTS citescore NUMERIC,
    ADD COLUMN IF NOT EXISTS sjr NUMERIC,
    ADD COLUMN IF NOT EXISTS snip NUMERIC,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- 2. Add Unique Constraint on journal_id to allow upserts
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'unique_scopus_additional_journal_id'
    ) THEN
        ALTER TABLE public."Scopus_additional_data"
            ADD CONSTRAINT unique_scopus_additional_journal_id UNIQUE (journal_id);
    END IF;
END $$;

-- 3. Create indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_scopus_add_journal_id ON public."Scopus_additional_data"(journal_id);
CREATE INDEX IF NOT EXISTS idx_scopus_add_citescore ON public."Scopus_additional_data"(citescore DESC);

-- 4. Enable RLS and grant INSERT / SELECT / UPDATE permissions to anon and authenticated
ALTER TABLE public."Scopus_additional_data" ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow anon and service read and write" ON public."Scopus_additional_data";

CREATE POLICY "Allow anon and service read and write"
    ON public."Scopus_additional_data"
    FOR ALL
    TO anon, authenticated, service_role
    USING (true)
    WITH CHECK (true);
