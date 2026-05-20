-- 59_reaper_threshold_7m.sql — bump stuck-running reaper from 5 → 7 minutes.
--
-- PR #39 / Wave-1 W1.4 (2026-05-20). The frontend Add Zettel polling budget
-- moved from 180s → 300s (5 min) in C1 to give long YouTube/PDF pipelines
-- legitimate room to finish. The reaper threshold must stay STRICTLY ABOVE
-- the polling budget so a slow-but-progressing operation is never reaped
-- under the client's polling window: a row legitimately still `running`
-- at t=4:30 should NOT be flipped to `failed` 30s later just because the
-- old 5-min reaper window expired.
--
-- 7 minutes = 5 min poll budget + 2 min slack. The slack covers:
--   * the final `ops_finalize` round-trip latency
--   * one additional gunicorn worker retry on transient PostgREST hiccup
--   * lazy-enrichment Phase 1 commit lag (the persist write that flips the
--     row to `succeeded` lands AFTER the LLM summary, not before)
--
-- Idempotent: cron.unschedule + cron.schedule. Safe to reapply on a fresh
-- DB build (migration 57 may not exist yet on a new clone — guard with
-- DO block + EXCEPTION WHEN OTHERS for the unschedule).

BEGIN;

DO $$
BEGIN
    -- Drop the prior schedule if present. Migration 57 is the parent; a
    -- fresh clone applies 57 first (cadence */2, threshold 5min) and then
    -- this file rewrites the threshold. EXCEPTION traps the cron.unschedule
    -- 'job not found' so a clean DB without 57 still applies cleanly.
    BEGIN
        PERFORM cron.unschedule('reap_stuck_running_operations');
    EXCEPTION WHEN OTHERS THEN
        -- Job did not exist (fresh clone before 57 ran, or pg_cron
        -- absent in a test fixture). Both cases are recoverable: the
        -- schedule call below is the authoritative source of truth.
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
          AND updated_at < now() - interval '7 minutes'
        $cron$
    );
END$$;

COMMIT;

NOTIFY pgrst, 'reload schema';
