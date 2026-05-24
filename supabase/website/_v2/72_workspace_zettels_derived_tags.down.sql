-- Down migration for 72_workspace_zettels_derived_tags.sql.
--
-- LOSSY: rows that already had their derived-prefix tags split out of
-- `user_tags` will lose those tags entirely unless you fold derived_tags
-- back in BEFORE running this script:
--
--   UPDATE content.workspace_zettels
--      SET user_tags = ARRAY(SELECT DISTINCT t FROM unnest(user_tags || derived_tags) AS t)
--    WHERE array_length(derived_tags, 1) > 0;
--
-- After running the rollback, callers expecting `derived_tags` (Python
-- ContentRepository.upsert_workspace_zettel, routes._v2_assemble_graph node
-- emission) will fail. Coordinate with code rollback.

ALTER TABLE content.workspace_zettels DROP COLUMN IF EXISTS derived_tags;
