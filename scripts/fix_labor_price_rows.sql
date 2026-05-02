-- Repair labor-price rows in price_records.
--
-- Background: OCR table parser misaligns rows like
--   "铝合金门窗工 工日 371.00"
-- into:
--   material_name = "铝合金门窗工 工日"
--   specification = "371.00"
--   unit          = NULL
-- which makes the records invisible to "人工费" semantic search and
-- causes the agent to mis-attribute labor prices as material prices
-- (see issue #86 / Q5 regression on 2026-05).
--
-- UPSTREAM FIX (#91, commit pending): tools/ocr_ingest_pipeline.py now calls
-- _normalize_labor_row inside _build_record. Newly-ingested rows will be
-- correct. This SQL exists only to clean rows ingested BEFORE that fix —
-- after the next full re-ingest of historical PDFs it can be deleted.
--
-- This script repairs already-ingested rows. Re-run after every fresh
-- ingest of 信息价 PDFs until the upstream OCR pipeline is fixed.
--
-- Safe to re-run: only matches rows where unit IS NULL/empty AND
-- specification is purely numeric AND material_name ends in "工日".

BEGIN;

-- Pattern A: "X工 工日" + spec="数字" + unit empty
UPDATE price_records
SET material_name = regexp_replace(material_name, '\s*工日\s*$', ''),
    unit = '工日',
    specification = NULL
WHERE material_name ~ '工日\s*$'
  AND specification ~ '^[0-9.]+$'
  AND (unit IS NULL OR unit = '')
  AND price_tax_included IS NOT NULL;

-- Pattern B: material_name = bare "工日" (orphan rows)
UPDATE price_records
SET unit = '工日'
WHERE material_name = '工日'
  AND (unit IS NULL OR unit = '');

-- Pattern C: OCR-garbled rows where 工日 sits mid-string
-- (e.g. "工日 一", "X 工日 X", "AY 工日 A N") — keep noisy name,
-- just promote unit and clear numeric spec
UPDATE price_records
SET unit = '工日',
    specification = '',
    price_tax_included = COALESCE(price_tax_included, CAST(specification AS numeric))
WHERE material_name ~ '工日'
  AND specification ~ '^[0-9]+\.?[0-9]*$'
  AND (unit IS NULL OR unit = '');

SELECT count(*) AS labor_rows_now FROM price_records WHERE unit = '工日';

COMMIT;
