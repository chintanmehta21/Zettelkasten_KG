-- 61_enrichment_jobs_reaper.sql — pg_cron watchdog for stuck enrichment jobs.
--
-- PR #39 / Wave-3 follow-up (2026-05-20). Companion to migration 60
-- (core.zettel_enrichment_jobs). Mirrors the stuck-running reaper for
-- core.operations (migration 57 -> 59) — same threshold (5 min) and the
-- same RFC 9457 worker-lost shape on the error column.
--
-- Why this is needed:
--   * `enrich_claim_next` flips status queued -> running. If the in-process
--     worker crashes mid-handle (OOM-kill, deploy mid-flight, container
--     recycle, asyncio TaskGroup cancellation) the row stays `running`
--     until expires_at (24h default). The partial unique index on
--     (canonical_zettel_id, kind) WHERE status IN (queued, running, succeeded)
--     would then BLOCK a re-enqueue of the same zettel for 24h, even
--     though the previous attempt is dead.
--   * Flipping the row to `failed` lets the operator OR a future
--     re-enqueue-on-active hook re-queue cleanly, AND surfaces the issue
--     in observability (rows with error.code='worker-lost' = ops alert).
--
-- Threshold rationale: handler budget is bounded by the underlying Gemini
-- batch-embed call (~tens of seconds for 200 chunks). 5 minutes is far
-- past any legitimate single-handler run; matches the operations reaper.
-- Cadence: every 2 minutes (same as ops reaper; idempotent upsert).

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'reap_stuck_running_enrichment_jobs'
    ) THEN
        PERFORM cron.schedule(
            'reap_stuck_running_enrichment_jobs',
            '*/2 * * * *',
            $cron$
            UPDATE core.zettel_enrichment_jobs
            SET status='failed',
                error=jsonb_build_object(
                    'type','https://zettelkasten.in/problems/errors/worker-lost',
                    'title','Background worker lost',
                    'status',500,
                    'detail','The enrichment handler did not finalize within the watchdog window.',
                    'code','worker-lost'
                ),
                completed_at=now(),
                updated_at=now()
            WHERE status='running'
              AND updated_at < now() - interval '5 minutes'
            $cron$
        );
    END IF;
END$$;

COMMIT;

NOTIFY pgrst, 'reload schema';
