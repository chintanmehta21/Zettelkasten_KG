-- 52_stuck_running_reaper.sql — pg_cron watchdog for stuck running ops.
--
-- Companion to migration 49 (sweep_stale_operations: TTL-based DELETE of
-- expires_at < now()). This job covers a different failure mode: a worker
-- that started a run (status='running') but never reached ops_finalize
-- because it crashed, was OOM-killed, or the container was recycled mid-run.
--
-- Without this, the row sits status='running' until expires_at (24h default),
-- making cross-worker polls observe a permanent 202-pending. We finalize
-- such rows as 'failed' with an RFC 9457 worker-lost error so the client's
-- next poll resolves to a terminal state immediately.
--
-- Threshold rationale: GUNICORN_TIMEOUT=180s is the hard wall for a single
-- request. A row whose updated_at is older than 5 minutes is definitively
-- past any legitimate run window (180s + slack) and is safe to reap.
-- queued rows are NOT touched — those may legitimately be slow to start
-- under burst and are the responsibility of the TTL sweep (migration 49).
--
-- Cadence: every 2 minutes. cron.schedule upserts by jobname, so reapplying
-- the migration is idempotent. Standalone job (NOT amending migration 49)
-- per the Phase-0 discovery decision: separate name keeps observability /
-- alerting / rollback per-concern.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'reap_stuck_running_operations'
    ) THEN
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
              AND updated_at < now() - interval '5 minutes'
            $cron$
        );
    END IF;
END$$;

COMMIT;

NOTIFY pgrst, 'reload schema';
