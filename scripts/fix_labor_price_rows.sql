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

SELECT count(*) AS labor_rows_now FROM price_records WHERE unit = '工日';

COMMIT;
