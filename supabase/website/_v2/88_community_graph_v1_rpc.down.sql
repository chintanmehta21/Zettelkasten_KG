-- Reverse migration 88. Drop the function (also unblocks dropping
-- community_reader in 87.down). Idempotent.
BEGIN;
  DROP FUNCTION IF EXISTS content.community_graph_v1(int, float);
COMMIT;
NOTIFY pgrst, 'reload schema';
