-- Reverse migration 89. Idempotent.
BEGIN;
  DROP FUNCTION IF EXISTS content.bump_community_cache_version();
  DROP TABLE IF EXISTS content.community_cache_version;
COMMIT;
NOTIFY pgrst, 'reload schema';
