-- Migration 001: Chinese full-text search via zhparser
-- Purpose : Replace PostgreSQL 'simple' text search (0% hit rate on Chinese synonyms)
--           with 'chinese' configuration backed by zhparser word segmentation.
-- Requires: zhparser must be compiled into the Postgres binary
--           (use infrastructure/docker/Dockerfile.postgres).
-- Run once: psql "$DATABASE_URL" -f sql/migrations/001_chinese_fts.sql
-- Idempotent: safe to re-run

\set ON_ERROR_STOP on

BEGIN;

-- ── 1. Extension ─────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS zhparser;

-- ── 2. Text search configuration ─────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_ts_config WHERE cfgname = 'chinese'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = zhparser);
        ALTER TEXT SEARCH CONFIGURATION chinese
            ADD MAPPING FOR n, v, a, i, e, l WITH simple;
        RAISE NOTICE 'Created text search configuration: chinese';
    ELSE
        RAISE NOTICE 'Text search configuration "chinese" already exists, skipping.';
    END IF;
END $$;

-- ── 3. text_chunks.tsv → use 'chinese' ───────────────────────────────────────
DO $$
DECLARE
    current_expr text;
BEGIN
    SELECT generation_expression INTO current_expr
    FROM information_schema.columns
    WHERE table_name = 'text_chunks' AND column_name = 'tsv';

    IF current_expr IS NULL OR current_expr NOT LIKE '%chinese%' THEN
        ALTER TABLE text_chunks DROP COLUMN IF EXISTS tsv;
        ALTER TABLE text_chunks
            ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
                to_tsvector('chinese', content)
            ) STORED;
        RAISE NOTICE 'Rebuilt text_chunks.tsv with chinese config (full table rewrite).';
    ELSE
        RAISE NOTICE 'text_chunks.tsv already uses chinese config, skipping.';
    END IF;
END $$;

DROP INDEX IF EXISTS idx_tc_tsv;
CREATE INDEX IF NOT EXISTS idx_text_chunks_tsv_chinese ON text_chunks USING GIN (tsv);

-- ── 4. price_records: add tsv column ─────────────────────────────────────────
DO $$
DECLARE
    has_specification boolean;
    has_spec          boolean;
    fts_expr          text;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'price_records' AND column_name = 'specification'
    ) INTO has_specification;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'price_records' AND column_name = 'spec'
    ) INTO has_spec;

    IF has_specification THEN
        fts_expr := $e$to_tsvector('chinese',
            coalesce(material_name, '') || ' ' || coalesce(specification, ''))$e$;
    ELSIF has_spec THEN
        fts_expr := $e$to_tsvector('chinese',
            coalesce(material_name, '') || ' ' || coalesce(spec, ''))$e$;
    ELSE
        fts_expr := $e$to_tsvector('chinese', coalesce(material_name, ''))$e$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'price_records' AND column_name = 'tsv'
    ) THEN
        EXECUTE 'ALTER TABLE price_records DROP COLUMN tsv';
        RAISE NOTICE 'Dropped existing price_records.tsv, rebuilding with chinese config.';
    END IF;

    EXECUTE format(
        'ALTER TABLE price_records ADD COLUMN tsv tsvector GENERATED ALWAYS AS (%s) STORED',
        fts_expr
    );
    RAISE NOTICE 'Added price_records.tsv with chinese config.';
END $$;

CREATE INDEX IF NOT EXISTS idx_price_records_tsv_chinese ON price_records USING GIN (tsv);

-- ── 5. canonical_concepts: add tsv column (regular, not generated — array_to_string is STABLE) ──
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'canonical_concepts' AND column_name = 'tsv'
    ) THEN
        ALTER TABLE canonical_concepts DROP COLUMN tsv;
    END IF;

    ALTER TABLE canonical_concepts ADD COLUMN tsv tsvector;

    UPDATE canonical_concepts
       SET tsv = to_tsvector('chinese',
                     coalesce(concept_name, '') || ' ' ||
                     coalesce(array_to_string(aliases, ' '), ''));

    RAISE NOTICE 'Added canonical_concepts.tsv with chinese config.';
END $$;

-- Trigger to keep tsv in sync on INSERT / UPDATE
CREATE OR REPLACE FUNCTION canonical_concepts_tsv_trigger()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.tsv := to_tsvector('chinese',
                   coalesce(NEW.concept_name, '') || ' ' ||
                   coalesce(array_to_string(NEW.aliases, ' '), ''));
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trig_canonical_concepts_tsv ON canonical_concepts;
CREATE TRIGGER trig_canonical_concepts_tsv
    BEFORE INSERT OR UPDATE OF concept_name, aliases
    ON canonical_concepts
    FOR EACH ROW EXECUTE FUNCTION canonical_concepts_tsv_trigger();

CREATE INDEX IF NOT EXISTS idx_canonical_concepts_tsv_chinese
    ON canonical_concepts USING GIN (tsv);

COMMIT;

-- ── Verify ────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_ts_config WHERE cfgname = 'chinese') THEN
        RAISE NOTICE 'VERIFY OK: "chinese" text search configuration is active.';
        RAISE NOTICE 'Test: %', (
            SELECT to_tsvector('chinese', '电力电缆预应力混凝土')::text
        );
    ELSE
        RAISE WARNING 'VERIFY FAILED: "chinese" config not found — zhparser may not be installed.';
    END IF;
END $$;
