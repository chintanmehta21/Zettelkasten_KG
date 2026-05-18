-- 45_url_dedup.sql — URL-identity dedup.
-- Collapse duplicate canonicals (keep newest per normalized_url), re-point
-- children, then make normalized_url the sole uniqueness key.
-- Idempotent: safe to re-apply.
--
-- keeper_map is computed once and reused by every re-point/delete so the
-- keeper choice is deterministic (ORDER BY created_at DESC, id DESC) and
-- identical across all statements.

BEGIN;

CREATE TEMP TABLE keeper_map ON COMMIT DROP AS
SELECT id AS loser_id, keeper_id
FROM (
    SELECT id,
           row_number() OVER (PARTITION BY normalized_url
                              ORDER BY created_at DESC, id DESC) AS rn,
           first_value(id) OVER (PARTITION BY normalized_url
                                 ORDER BY created_at DESC, id DESC) AS keeper_id
    FROM content.canonical_zettels
) ranked
WHERE rn > 1;

-- Re-point workspace_zettels loser -> keeper (skip on UNIQUE collision).
UPDATE content.workspace_zettels wz
SET canonical_zettel_id = km.keeper_id
FROM keeper_map km
WHERE wz.canonical_zettel_id = km.loser_id
  AND NOT EXISTS (
      SELECT 1 FROM content.workspace_zettels x
      WHERE x.workspace_id = wz.workspace_id AND x.canonical_zettel_id = km.keeper_id
  );

-- Re-point canonical_chunks loser -> keeper (skip when keeper already has
-- a chunk at the same chunk_idx; that loser chunk is a true duplicate and
-- is deleted below by the loser canonical_chunks delete).
UPDATE content.canonical_chunks cc
SET canonical_zettel_id = km.keeper_id
FROM keeper_map km
WHERE cc.canonical_zettel_id = km.loser_id
  AND NOT EXISTS (
      SELECT 1 FROM content.canonical_chunks x
      WHERE x.canonical_zettel_id = km.keeper_id AND x.chunk_idx = cc.chunk_idx
  );

-- Re-point workspace_chunk_membership loser -> keeper-equivalents BEFORE the
-- loser canonical_chunks / workspace_zettels deletes. Both membership FKs
-- (canonical_chunk_id, workspace_zettel_id) CASCADE-delete, so without this
-- re-point, membership rows for real surviving workspaces would be silently
-- lost (RAG data loss). Loser canonical_chunk maps to the keeper chunk with
-- the same chunk_idx under the keeper canonical; loser workspace_zettel maps
-- to the keeper workspace_zettel for the same workspace. The membership PK
-- (workspace_id, canonical_chunk_id, workspace_zettel_id) is guarded with a
-- NOT EXISTS anti-collision clause.
UPDATE content.workspace_chunk_membership m
SET canonical_chunk_id  = kc.id,
    workspace_zettel_id = kwz.id
FROM keeper_map km
JOIN content.canonical_chunks lc
       ON lc.canonical_zettel_id = km.loser_id
JOIN content.canonical_chunks kc
       ON kc.canonical_zettel_id = km.keeper_id
      AND kc.chunk_idx = lc.chunk_idx
JOIN content.workspace_zettels lwz
       ON lwz.canonical_zettel_id = km.loser_id
JOIN content.workspace_zettels kwz
       ON kwz.canonical_zettel_id = km.keeper_id
      AND kwz.workspace_id = lwz.workspace_id
WHERE m.canonical_chunk_id  = lc.id
  AND m.workspace_zettel_id = lwz.id
  AND m.workspace_id        = kwz.workspace_id
  AND NOT EXISTS (
      SELECT 1 FROM content.workspace_chunk_membership x
      WHERE x.workspace_id        = m.workspace_id
        AND x.canonical_chunk_id  = kc.id
        AND x.workspace_zettel_id = kwz.id
  );

-- Delete any membership rows still pointing at a loser chunk or loser
-- workspace_zettel (true-dup collisions that could not be re-pointed). This
-- must precede the loser canonical_chunks / workspace_zettels deletes so the
-- CASCADE never reaches a membership row for a surviving real workspace.
DELETE FROM content.workspace_chunk_membership m
USING keeper_map km
WHERE m.canonical_chunk_id IN (
        SELECT id FROM content.canonical_chunks WHERE canonical_zettel_id = km.loser_id
      )
   OR m.workspace_zettel_id IN (
        SELECT id FROM content.workspace_zettels WHERE canonical_zettel_id = km.loser_id
      );

DELETE FROM content.workspace_zettels wz
USING keeper_map km
WHERE wz.canonical_zettel_id = km.loser_id;

DELETE FROM content.canonical_chunks cc
USING keeper_map km
WHERE cc.canonical_zettel_id = km.loser_id;

DELETE FROM content.canonical_zettels c
USING keeper_map km
WHERE c.id = km.loser_id;

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
