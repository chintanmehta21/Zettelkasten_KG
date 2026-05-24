-- Migration 71 (Phase 3 / LD-8): pipeline_runs state machine extension.
--
-- (Plan-numbered "Migration 49" in 2026-05-23-kg-render-correctness-overhaul.md.
-- First renumbered to 70 because slot 49 was occupied; bumped again to 71
-- to stay sequential after a parallel master commit (0eaf172d) added
-- 68_hybrid_search_chunks_workspace.sql.)
--
-- 2026-05-23 REWRITE: the plan assumed `pipelines.pipeline_run_status` was
-- an ENUM type; CI revealed the actual schema (_v2/05_pipelines_schema.sql:11)
-- uses a TEXT column with a CHECK constraint
-- (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')).
-- ALTER TYPE ADD VALUE is therefore inapplicable; we replace the CHECK
-- constraint with an extended set.
--
-- Existing states (kept): 'queued', 'running', 'succeeded', 'failed', 'cancelled'.
-- New states added:
--   'succeeded_empty'  - terminal-but-retryable; edges=0 from a clean run
--                        (no candidates found). Retryable after 24h grace.
--   'failed_retryable' - transient failure (rate limit / RPC / network).
--                        Retryable after exponential backoff.
--   'failed_permanent' - terminal failure (corrupt input, schema invariant).
--                        NEVER retried; idempotency gate blocks.
--
-- Plus: retry_eligible_after timestamp + attempt_count for backoff scheduling.
--
-- Backfill: existing rows with status='succeeded' AND metrics->>'edges'::int = 0
-- migrate to 'succeeded_empty' so the new gate semantics take effect for the
-- Naruto-class workspaces that have terminally-empty KG runs.

BEGIN;
  SET LOCAL lock_timeout = '3s';
  SET LOCAL statement_timeout = '60s';

  -- Replace the CHECK constraint with the extended state set. The DROP/ADD
  -- is atomic within this transaction. Name discovered via:
  --   SELECT conname FROM pg_constraint WHERE conrelid = 'pipelines.pipeline_runs'::regclass;
  -- Postgres auto-names CHECK constraints as <table>_<column>_check.
  ALTER TABLE pipelines.pipeline_runs
    DROP CONSTRAINT IF EXISTS pipeline_runs_status_check;
  ALTER TABLE pipelines.pipeline_runs
    ADD CONSTRAINT pipeline_runs_status_check
    CHECK (status IN (
      'queued', 'running', 'succeeded', 'failed', 'cancelled',
      'succeeded_empty', 'failed_retryable', 'failed_permanent'
    ));

  -- LD-8: retry-scheduling columns.
  ALTER TABLE pipelines.pipeline_runs
    ADD COLUMN IF NOT EXISTS retry_eligible_after timestamptz;

  ALTER TABLE pipelines.pipeline_runs
    ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 1;
COMMIT;

-- Partial index for the retry-sweep query — outside the BEGIN/COMMIT so a
-- prior partial apply leaves a clean state. Idempotent via IF NOT EXISTS.
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_retry_eligible
  ON pipelines.pipeline_runs (kind, retry_eligible_after)
  WHERE status IN ('succeeded_empty', 'failed_retryable')
    AND retry_eligible_after IS NOT NULL;

-- Backfill: zero-edge succeeded → succeeded_empty for kg_extract runs.
-- Idempotent (the WHERE clause excludes already-converted rows).
UPDATE pipelines.pipeline_runs
   SET status = 'succeeded_empty',
       retry_eligible_after = finished_at + interval '24 hours'
 WHERE status = 'succeeded'
   AND kind = 'kg_extract'
   AND (metrics->>'edges')::int = 0
   AND finished_at IS NOT NULL;

COMMENT ON COLUMN pipelines.pipeline_runs.retry_eligible_after IS
  'LD-8: timestamp after which a succeeded_empty / failed_retryable run is eligible for replay.';
COMMENT ON COLUMN pipelines.pipeline_runs.attempt_count IS
  'LD-8: monotonic counter of retry attempts; used for exponential backoff in failed_retryable.';
