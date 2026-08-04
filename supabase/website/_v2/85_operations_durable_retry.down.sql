-- Down-migration for 85_operations_durable_retry.sql.
--
-- Restores the fail-only reaper from 65_reaper_threshold_10m.sql so a rollback
-- leaves the watchdog functional rather than absent — an operations row stuck
-- in 'running' with no sweep would poll as 202-pending until its 24h TTL.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule(
            'reap_stuck_running_operations',
            '*/2 * * * *',
            $cron$
            UPDATE core.operations
            SET status='failed',
                error=jsonb_build_object(
                    'type','https://zettelkasten.in/problems/errors/worker-lost',
                    'title','Background worker lost',
                    'status',500,
                    'detail','The worker handling this operation did not finalize within the watchdog window.',
                    'code','worker-lost'
                ),
                updated_at=now()
            WHERE status='running'
              AND updated_at < now() - interval '10 minutes'
            $cron$
        );
    END IF;
END$$;

DROP FUNCTION IF EXISTS core.ops_reclaim_stale(interval);
DROP FUNCTION IF EXISTS core.ops_claim_next();
DROP FUNCTION IF EXISTS core.ops_step_get(uuid, text, text, text);
DROP FUNCTION IF EXISTS core.ops_step_put(uuid, text, text, jsonb, text);
DROP FUNCTION IF EXISTS core.ops_heartbeat(uuid, text);

DROP TABLE IF EXISTS core.operation_steps;

DROP INDEX IF EXISTS core.operations_queued_created_idx;
DROP INDEX IF EXISTS core.operations_running_heartbeat_idx;

ALTER TABLE core.operations
    DROP COLUMN IF EXISTS heartbeat_at,
    DROP COLUMN IF EXISTS max_attempts,
    DROP COLUMN IF EXISTS attempts;

COMMIT;

NOTIFY pgrst, 'reload schema';
