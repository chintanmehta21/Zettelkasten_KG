-- Migration 71 (Phase 3 / LD-8): pipeline_runs state machine extension.
--
-- (Plan-numbered "Migration 49" in 2026-05-23-kg-render-correctness-overhaul.md.
-- First renumbered to 70 because slot 49 was occupied; bumped again to 71
-- to stay sequential after a parallel master commit (0eaf172d) added
-- 68_hybrid_search_chunks_workspace.sql. Design content unchanged.)
--
-- Today: status enum = ('pending'|'in_progress'|'succeeded'|'failed').
-- Idempotency gate blocks ALL future retries once 'succeeded' is written,
-- even for a "succeeded with edges=0" outcome that was actually a transient
-- quota failure. This causes Naruto-class permanent edgelessness.
--
-- New states:
--   'succeeded_empty'  - terminal-but-retryable; edges=0 from a clean run
--                        (no candidates found). Retryable after 24h grace.
--   'failed_retryable' - transient failure (rate limit / RPC / network).
--                        Retryable after exponential backoff.
-- Plus: retry_eligible_after timestamp for backoff scheduling.
--
-- Backfill: existing rows with status='succeeded' AND metrics->>'edges'::int = 0
-- migrate to 'succeeded_empty' so the new gate semantics take effect.
--
-- WARNING: ALTER TYPE ADD VALUE cannot run inside a transaction with other DDL
-- on older Postgres. Supabase's PG 15+ supports this in a single statement
-- set; if you encounter `cannot run inside a transaction block`, split this
-- file into two `psql -c` invocations: enum extension first, the rest second.

ALTER TYPE pipelines.pipeline_run_status
  ADD VALUE IF NOT EXISTS 'succeeded_empty';
ALTER TYPE pipelines.pipeline_run_status
  ADD VALUE IF NOT EXISTS 'failed_retryable';

ALTER TABLE pipelines.pipeline_runs
  ADD COLUMN IF NOT EXISTS retry_eligible_after timestamptz;

ALTER TABLE pipelines.pipeline_runs
  ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 1;

-- Partial index for the retry-sweep query.
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_retry_eligible
  ON pipelines.pipeline_runs (kind, retry_eligible_after)
  WHERE status IN ('succeeded_empty', 'failed_retryable')
    AND retry_eligible_after IS NOT NULL;

-- Backfill: zero-edge succeeded → succeeded_empty for kg_extract runs.
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
