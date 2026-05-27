-- 83_stats_rpc_volatility.down.sql
-- Revert the stats RPC volatility metadata to the original declarations from
-- migrations 81/82. This rollback reintroduces PostgreSQL's SET-in-STABLE
-- runtime error and should only be used when the SET LOCAL statements are also
-- removed or the RPCs are otherwise replaced.

BEGIN;

ALTER FUNCTION billing.pricing_get_quota_snapshot_batch(uuid, jsonb) STABLE;
ALTER FUNCTION core.profile_stats_etag_probe_v1(uuid) STABLE;
ALTER FUNCTION core.profile_stats_v1(uuid) STABLE;

NOTIFY pgrst, 'reload schema';

COMMIT;
