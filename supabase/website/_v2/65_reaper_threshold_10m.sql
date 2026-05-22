-- 65_reaper_threshold_10m.sql — bump stuck-running reaper from 7 → 10 minutes.
--
-- ADR-1 (summary-api-async-fixes branch). The frontend Add Zettel polling
-- budget moves from 300s → 420s (7 min) so long YouTube/PDF pipelines on the
-- 1 GB droplet can finish inside the client's polling window. The reaper
-- threshold must stay STRICTLY ABOVE the polling budget so a slow-but-
-- progressing operation is never flipped to `failed` while the client is
-- still legitimately polling it.
--
-- 10 minutes = 7 min poll budget + 3 min slack. The slack covers:
--   * the final `ops_finalize` round-trip latency
--   * one additional gunicorn worker retry on transient PostgREST hiccup
--   * lazy-enrichment Phase 1 commit lag (the persist write that flips the
--     row to `succeeded` lands AFTER the LLM summary, not before)
--
-- Schema-neutral: only reschedules the pg_cron job, no DDL — expected_schema
-- .json is unaffected. Idempotent: cron.unschedule + cron.schedule.

BEGIN;

DO $$
BEGIN
    BEGIN
        PERFORM cron.unschedule('reap_stuck_running_operations');
    EXCEPTION WHEN OTHERS THEN
        -- Job did not exist (fresh clone before 57/59 ran, or pg_cron absent
        -- in a test fixture). The schedule call below is authoritative.
        NULL;
    END;

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
END$$;

COMMIT;

NOTIFY pgrst, 'reload schema';
