-- Down migration for 70_pipeline_runs_state_machine.sql.
-- WARNING: Postgres cannot drop enum values (CANNOT DROP VALUE 'succeeded_empty' /
-- 'failed_retryable' from pipelines.pipeline_run_status). The values remain
-- after a down-migration; only the new columns + partial index are removed.
-- Application code must continue to handle the extra enum values forever.

DROP INDEX IF EXISTS pipelines.idx_pipeline_runs_retry_eligible;
ALTER TABLE pipelines.pipeline_runs DROP COLUMN IF EXISTS attempt_count;
ALTER TABLE pipelines.pipeline_runs DROP COLUMN IF EXISTS retry_eligible_after;
-- enum values cannot be dropped in Postgres; left in place (no-op).
