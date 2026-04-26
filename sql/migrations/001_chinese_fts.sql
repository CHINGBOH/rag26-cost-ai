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

-- ── Migration 001b: Canonical concept aliases for synonym coverage ──────────────
-- These aliases enable the alias-expansion retrieval path to resolve industry
-- synonyms and abbreviations (砼→混凝土, 高压导线→电力电缆, etc.).
-- Idempotent: INSERT ON CONFLICT (concept_name) DO UPDATE merges new aliases.
BEGIN;

-- Add umbrella alias mappings for major construction material categories.
-- ON CONFLICT requires a unique constraint on concept_name; if the table
-- uses (concept_type, concept_name) as the unique key, adjust accordingly.
WITH upserts (concept_type, concept_name, normalized_name, aliases) AS (
    VALUES
      ('material'::text,'电力电缆','电力电缆',ARRAY['输电电缆','供电线缆','高压导线','电力传输线','动力电缆','高压线缆']),
      ('material','控制电缆','控制电缆',ARRAY['弱电线缆','控制线','仪表电缆','信号控制线','弱电电缆','通讯控制线']),
      ('material','混凝土','混凝土',ARRAY['砼','抗渗砼','C30砼','C25砼','细石砼','细骨料砼']),
      ('work','木模板','木模板',ARRAY['木工','模板工','木模','模板安装','木模安装','竹胶板模板']),
      ('material','钢筋混凝土','钢筋混凝土',ARRAY['钢砼','RC构件','钢筋砼','配筋混凝土']),
      ('material','豆石混凝土','豆石混凝土',ARRAY['豆石砼','细石混凝土','细骨料混凝土','豆砾石混凝土']),
      ('material','绝缘电线','绝缘电线',ARRAY['绝缘导线','BV电线','铜芯绝缘线','BV导线','铜芯塑料线','绝缘铜线','导线']),
      ('material','防水混凝土','防水混凝土',ARRAY['防渗砼','抗渗砼','防水砼','抗渗混凝土','防渗混凝土','C30P6','防水C30']),
      ('material','沥青混凝土','沥青混凝土',ARRAY['热拌沥青混合料','沥青混合料','AC混合料','沥青砼','沥青路面料','热拌料']),
      ('work','模板制安','模板制安',ARRAY['模板支拆','木模安装','模板拆支','模板制作安装','钢模板安装','模板工程']),
      ('work','安全文明施工措施费','安全文明施工措施费',ARRAY['文明施工费','安全文明费','施工安全文明费','安全措施费','文明施工措施费']),
      ('work','普工人工费','普工人工费',ARRAY['普通工人工费','普通工费用','普工费','普通工费','普通工劳务费','杂工费'])
)
INSERT INTO canonical_concepts (concept_type, concept_name, normalized_name, aliases)
SELECT concept_type, concept_name, normalized_name, aliases FROM upserts
ON CONFLICT DO NOTHING;

-- Refresh tsv for the inserted/updated concepts
UPDATE canonical_concepts
SET tsv = to_tsvector('chinese', concept_name || ' ' || COALESCE(array_to_string(aliases, ' '), ''))
WHERE concept_name IN (
  '电力电缆','控制电缆','混凝土','木模板','钢筋混凝土','豆石混凝土',
  '绝缘电线','防水混凝土','沥青混凝土','模板制安','安全文明施工措施费','普工人工费'
);

COMMIT;
