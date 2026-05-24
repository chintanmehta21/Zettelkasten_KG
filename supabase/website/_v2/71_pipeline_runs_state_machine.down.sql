-- Down migration for 71_pipeline_runs_state_machine.sql.
--
-- WARNING: rows whose status is one of the new values ('succeeded_empty',
-- 'failed_retryable', 'failed_permanent') would violate the original CHECK
-- constraint after this down migration. Convert them back to a base state
-- BEFORE running this script:
--
--   UPDATE pipelines.pipeline_runs
--      SET status = 'succeeded'
--    WHERE status IN ('succeeded_empty', 'failed_permanent');
--   UPDATE pipelines.pipeline_runs
--      SET status = 'failed'
--    WHERE status = 'failed_retryable';

DROP INDEX IF EXISTS pipelines.idx_pipeline_runs_retry_eligible;

ALTER TABLE pipelines.pipeline_runs DROP COLUMN IF EXISTS attempt_count;
ALTER TABLE pipelines.pipeline_runs DROP COLUMN IF EXISTS retry_eligible_after;

ALTER TABLE pipelines.pipeline_runs
  DROP CONSTRAINT IF EXISTS pipeline_runs_status_check;
ALTER TABLE pipelines.pipeline_runs
  ADD CONSTRAINT pipeline_runs_status_check
  CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'));
