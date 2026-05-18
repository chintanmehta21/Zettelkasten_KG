-- 45_url_dedup.sql — URL-identity dedup.
-- Collapse duplicate canonicals (keep newest per normalized_url), re-point
-- children, then make normalized_url the sole uniqueness key.
-- Idempotent: safe to re-apply.

BEGIN;

WITH ranked AS (
    SELECT id, normalized_url,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn,
           first_value(id) OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS keeper_id
    FROM content.canonical_zettels
),
losers AS (
    SELECT id AS loser_id, keeper_id FROM ranked WHERE rn > 1
)
UPDATE content.workspace_zettels wz
SET canonical_zettel_id = l.keeper_id
FROM losers l
WHERE wz.canonical_zettel_id = l.loser_id
  AND NOT EXISTS (
      SELECT 1 FROM content.workspace_zettels x
      WHERE x.workspace_id = wz.workspace_id AND x.canonical_zettel_id = l.keeper_id
  );

WITH ranked AS (
    SELECT id, normalized_url,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn,
           first_value(id) OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS keeper_id
    FROM content.canonical_zettels
),
losers AS (
    SELECT id AS loser_id, keeper_id FROM ranked WHERE rn > 1
)
UPDATE content.canonical_chunks cc
SET canonical_zettel_id = l.keeper_id
FROM losers l
WHERE cc.canonical_zettel_id = l.loser_id
  AND NOT EXISTS (
      SELECT 1 FROM content.canonical_chunks x
      WHERE x.canonical_zettel_id = l.keeper_id AND x.chunk_idx = cc.chunk_idx
  );

WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn
    FROM content.canonical_zettels
),
losers AS (SELECT id FROM ranked WHERE rn > 1)
DELETE FROM content.workspace_zettels wz USING losers l WHERE wz.canonical_zettel_id = l.id;

WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn
    FROM content.canonical_zettels
),
losers AS (SELECT id FROM ranked WHERE rn > 1)
DELETE FROM content.canonical_chunks cc USING losers l WHERE cc.canonical_zettel_id = l.id;

WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn
    FROM content.canonical_zettels
)
DELETE FROM content.canonical_zettels c USING ranked r
WHERE c.id = r.id AND r.rn > 1;

ALTER TABLE content.canonical_zettels
    DROP CONSTRAINT IF EXISTS canonical_zettels_normalized_url_content_hash_key;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'canonical_zettels_normalized_url_key'
          AND conrelid = 'content.canonical_zettels'::regclass
    ) THEN
        ALTER TABLE content.canonical_zettels
            ADD CONSTRAINT canonical_zettels_normalized_url_key UNIQUE (normalized_url);
    END IF;
END $$;

COMMIT;

NOTIFY pgrst, 'reload schema';
