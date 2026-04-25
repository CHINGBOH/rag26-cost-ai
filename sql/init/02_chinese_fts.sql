-- 02_chinese_fts.sql
-- Install zhparser extension and create Chinese text search configuration.
-- Runs automatically on fresh container init (docker-entrypoint-initdb.d).
-- For existing databases: run sql/migrations/001_chinese_fts.sql manually.
--
-- Requires: zhparser compiled into the Postgres image (see infrastructure/docker/Dockerfile.postgres)

-- 1. Install extension
CREATE EXTENSION IF NOT EXISTS zhparser;

-- 2. Create Chinese text search configuration
--    Maps core POS tags (noun, verb, adjective, idiom, etc.) through simple dictionary
--    so tokens are passed through unchanged (exact match after segmentation).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_ts_config WHERE cfgname = 'chinese'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = zhparser);
        ALTER TEXT SEARCH CONFIGURATION chinese
            ADD MAPPING FOR n, v, a, i, e, l WITH simple;
    END IF;
END $$;

-- 3. Upgrade text_chunks.tsv from 'simple' to 'chinese' segmentation
--    Drop and recreate the generated column; PostgreSQL rewrites all rows automatically.
ALTER TABLE text_chunks DROP COLUMN IF EXISTS tsv;
ALTER TABLE text_chunks
    ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('chinese', content)
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_text_chunks_tsv_chinese
    ON text_chunks USING GIN (tsv);

-- 4. Add Chinese FTS column to price_records (material_name + spec/specification)
--    Handle both column name variants (spec in init schema, specification in code).
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
        fts_expr := $expr$to_tsvector('chinese',
            coalesce(material_name, '') || ' ' || coalesce(specification, ''))$expr$;
    ELSIF has_spec THEN
        fts_expr := $expr$to_tsvector('chinese',
            coalesce(material_name, '') || ' ' || coalesce(spec, ''))$expr$;
    ELSE
        fts_expr := $expr$to_tsvector('chinese', coalesce(material_name, ''))$expr$;
    END IF;

    -- Drop old tsv column if it exists
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'price_records' AND column_name = 'tsv'
    ) THEN
        EXECUTE 'ALTER TABLE price_records DROP COLUMN tsv';
    END IF;

    EXECUTE format(
        'ALTER TABLE price_records ADD COLUMN tsv tsvector GENERATED ALWAYS AS (%s) STORED',
        fts_expr
    );
END $$;

CREATE INDEX IF NOT EXISTS idx_price_records_tsv_chinese
    ON price_records USING GIN (tsv);

-- 5. Add Chinese FTS column to canonical_concepts (concept_name + aliases)
-- Regular column (not GENERATED) because array_to_string is STABLE, not IMMUTABLE
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'canonical_concepts' AND column_name = 'tsv'
    ) THEN
        ALTER TABLE canonical_concepts ADD COLUMN tsv tsvector;
        UPDATE canonical_concepts
           SET tsv = to_tsvector('chinese',
                         coalesce(concept_name, '') || ' ' ||
                         coalesce(array_to_string(aliases, ' '), ''));
    END IF;
END $$;

-- Trigger to keep tsv in sync
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
