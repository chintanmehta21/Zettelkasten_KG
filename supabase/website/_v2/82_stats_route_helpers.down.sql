-- 82_stats_route_helpers.down.sql
-- Reverse migration 82. Safe to run regardless of whether the functions exist.

BEGIN;

DROP FUNCTION IF EXISTS core.profile_stats_etag_probe_v1(uuid);
DROP FUNCTION IF EXISTS billing.pricing_get_quota_snapshot_batch(uuid, jsonb);

NOTIFY pgrst, 'reload schema';

COMMIT;
