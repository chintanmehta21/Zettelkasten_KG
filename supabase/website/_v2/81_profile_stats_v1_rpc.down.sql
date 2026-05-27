-- 81_profile_stats_v1_rpc.down.sql
-- Reverse migration 81. Safe to run even if function never existed.

BEGIN;

DROP FUNCTION IF EXISTS core.profile_stats_v1(uuid);

COMMIT;

NOTIFY pgrst, 'reload schema';
