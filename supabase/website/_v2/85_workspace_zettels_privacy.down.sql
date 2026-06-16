-- Reverse migration 85. Idempotent.
BEGIN;
  DROP INDEX IF EXISTS content.idx_workspace_zettels_community;
  ALTER TABLE content.workspace_zettels DROP COLUMN IF EXISTS made_private_at;
  ALTER TABLE content.workspace_zettels DROP COLUMN IF EXISTS is_private;
COMMIT;
NOTIFY pgrst, 'reload schema';
