-- 83_stats_rpc_volatility.sql
-- Fix production execution of the stats RPCs. Migrations 81 and 82 declared
-- these functions STABLE, but their PL/pgSQL bodies use SET LOCAL for per-call
-- timeouts/work_mem. PostgreSQL rejects SET inside non-VOLATILE functions, so
-- PostgREST surfaced profile stats as 500s. Keep the function bodies/grants
-- from 81/82 and correct only volatility here to avoid mutating applied
-- migration checksums.

BEGIN;

ALTER FUNCTION core.profile_stats_v1(uuid) VOLATILE;
ALTER FUNCTION core.profile_stats_etag_probe_v1(uuid) VOLATILE;
ALTER FUNCTION billing.pricing_get_quota_snapshot_batch(uuid, jsonb) VOLATILE;

NOTIFY pgrst, 'reload schema';

COMMIT;
