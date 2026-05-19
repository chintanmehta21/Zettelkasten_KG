-- 49_operations_sweep.sql — pg_cron TTL sweep for core.operations.
--
-- Gap: a gunicorn worker recycled mid-synth never writes a terminal state,
-- leaving rows stuck status='accepted' indefinitely. This job sweeps ALL rows
-- past their expires_at (default now()+24h), which covers stuck-accepted rows
-- as a strict subset. Succeeded/failed rows past TTL are also collected —
-- intentional; they are no longer poll-reachable from the client.
--
-- Cadence: hourly at :00 UTC. The table is small (one row per in-flight op)
-- and the DELETE is index-range-scan on operations_expires_at_idx — no lock
-- contention at current scale.
--
-- pg_cron already enabled project-wide (confirmed: 36/37 do not CREATE
-- EXTENSION pg_cron). Idempotent guard follows 37's DO $$ IF NOT EXISTS idiom.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'sweep_stale_operations'
    ) THEN
        PERFORM cron.schedule(
            'sweep_stale_operations',
            '0 * * * *',
            $cron$DELETE FROM core.operations WHERE expires_at < now()$cron$
        );
    END IF;
END$$;

COMMIT;

NOTIFY pgrst, 'reload schema';
