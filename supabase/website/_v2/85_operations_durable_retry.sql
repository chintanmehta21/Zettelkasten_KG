-- 85_operations_durable_retry.sql — make accepted Add-Zettel work survive
-- an ungraceful worker death (SIGKILL / cgroup OOM / docker kill / cutover).
--
-- WHY (2026-08-02 incident, docs/claude_audits/youtube_ingest_failure_2026-08-02.md):
-- accepted work ran as a detached in-process asyncio task. A gunicorn
-- max_requests recycle cancelled one 37.8s in and the zettel was lost. PR #174
-- added a lifespan drain, which covers SIGNAL-initiated shutdown only. A cgroup
-- OOM kill is SIGKILL with zero grace — no Python handler runs at all, and the
-- droplet's app cgroup has already OOM-killed processes. Out-of-process
-- durability is the only mechanism that covers that case.
--
-- DESIGN: core.operations is ALREADY the cross-worker truth with state-guarded
-- RPCs (migration 51) and a stuck-running reaper (57 -> 59 -> 65). So we make
-- that row resumable rather than standing up a parallel queue:
--   * attempts / max_attempts  — bounded retry, then dead-letter
--   * heartbeat_at             — liveness, so a dead worker is detectable
--   * core.operation_steps     — per-step result journal
-- The reaper changes from "mark failed" to "requeue if attempts remain".
--
-- Pattern references: River / pg-boss / graphile-worker / Oban / Solid Queue
-- (Postgres-as-queue with SKIP LOCKED); Temporal Activity Heartbeat details
-- (the step journal is the same shape). Mirrors core.zettel_enrichment_jobs
-- (migration 60), which already proved this pattern in this codebase.
--
-- COST CONTROL (the reason the journal exists): Gemini has NO idempotency key
-- on generateContent — a naive retry re-runs and re-bills the whole pipeline.
-- The journal makes replay skip already-completed steps, so a crash costs the
-- tail step, not the whole ingest. The stale threshold MUST stay above the
-- longest legitimate LLM call or we would re-dispatch live jobs and bill
-- ourselves twice; 10 minutes vs a ~120s worst-case call is the safety margin.

BEGIN;

-- (1) Retry + liveness columns on the existing operations row. -----------------
ALTER TABLE core.operations
    ADD COLUMN IF NOT EXISTS attempts     int         NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_attempts int         NOT NULL DEFAULT 3,
    ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz NULL;

COMMENT ON COLUMN core.operations.attempts IS
    'Times this operation has been dispatched to a worker. Incremented by '
    'ops_start and ops_claim_next; compared against max_attempts by the reaper.';
COMMENT ON COLUMN core.operations.heartbeat_at IS
    'Last liveness ping from the owning worker. NULL while queued. A running '
    'row whose heartbeat is stale is presumed worker-dead and is requeued.';

-- Reaper/claim hot path: find stale running rows and queued rows cheaply.
CREATE INDEX IF NOT EXISTS operations_running_heartbeat_idx
    ON core.operations (heartbeat_at)
    WHERE status = 'running';
CREATE INDEX IF NOT EXISTS operations_queued_created_idx
    ON core.operations (created_at)
    WHERE status = 'queued';

-- (2) Per-step result journal. -------------------------------------------------
-- One row per (operation, step). Replay reads this BEFORE running a step and
-- reuses the stored result, so an expensive non-idempotent call (Gemini) is not
-- repeated. Written in its own short transaction the moment a step completes —
-- never batched to the end, or a crash loses everything the journal exists for.
CREATE TABLE IF NOT EXISTS core.operation_steps (
    user_id       uuid        NOT NULL,
    operation_id  text        NOT NULL,
    step_name     text        NOT NULL,
    result        jsonb       NOT NULL,
    -- Hash of the step's INPUT. On replay, a journal row whose input hash no
    -- longer matches is ignored rather than reused — protects against reusing
    -- a result computed from different inputs after a code change.
    input_hash    text        NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, operation_id, step_name)
);

COMMENT ON TABLE core.operation_steps IS
    'Step-result journal for resumable operations. Lets a retry after an '
    'ungraceful worker death skip already-completed steps instead of re-running '
    '(and re-billing) them. Pruned with its parent operation.';

ALTER TABLE core.operation_steps ENABLE ROW LEVEL SECURITY;

-- Explicit table grant. RLS policies are NOT a substitute for a table grant,
-- and the 09-51 migrations' missing grants caused the 2026-05-21 prod outage.
GRANT SELECT, INSERT, UPDATE, DELETE ON core.operation_steps TO service_role;

-- (3) ops_heartbeat: prove the owning worker is alive. -------------------------
CREATE OR REPLACE FUNCTION core.ops_heartbeat(
    p_user_id      uuid,
    p_operation_id text
)
RETURNS timestamptz
LANGUAGE sql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
    UPDATE core.operations
       SET heartbeat_at = now(),
           updated_at   = now()
     WHERE user_id = p_user_id
       AND operation_id = p_operation_id
       AND status = 'running'
    RETURNING heartbeat_at;
$$;

COMMENT ON FUNCTION core.ops_heartbeat(uuid, text) IS
    'Liveness ping from the worker owning a running operation. Returns NULL '
    'when the row is not running (already terminal, or reclaimed by the reaper).';

-- (4) Step journal accessors. --------------------------------------------------
CREATE OR REPLACE FUNCTION core.ops_step_put(
    p_user_id      uuid,
    p_operation_id text,
    p_step_name    text,
    p_result       jsonb,
    p_input_hash   text DEFAULT NULL
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
    INSERT INTO core.operation_steps (
        user_id, operation_id, step_name, result, input_hash
    )
    VALUES (p_user_id, p_operation_id, p_step_name, p_result, p_input_hash)
    ON CONFLICT (user_id, operation_id, step_name)
    DO UPDATE SET result = EXCLUDED.result,
                  input_hash = EXCLUDED.input_hash,
                  created_at = now();
$$;

CREATE OR REPLACE FUNCTION core.ops_step_get(
    p_user_id      uuid,
    p_operation_id text,
    p_step_name    text,
    p_input_hash   text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
    SELECT result
      FROM core.operation_steps
     WHERE user_id = p_user_id
       AND operation_id = p_operation_id
       AND step_name = p_step_name
       -- A NULL probe hash means "any"; otherwise the stored hash must match,
       -- so a result computed from stale inputs is recomputed, not reused.
       AND (p_input_hash IS NULL OR input_hash IS NOT DISTINCT FROM p_input_hash)
     LIMIT 1;
$$;

COMMENT ON FUNCTION core.ops_step_get(uuid, text, text, text) IS
    'Read a journaled step result for replay. Input-hash mismatch returns NULL '
    'so the step recomputes rather than reusing a result from different inputs.';

-- (5) ops_claim_next: pick up an orphaned/queued operation. --------------------
-- FOR UPDATE SKIP LOCKED so the 2 gunicorn workers never grab the same row.
-- The claim is a SHORT transaction inside this function; the actual work runs
-- with NO transaction open. Holding one across a ~120s LLM call would pin the
-- cluster-wide MVCC horizon and block autovacuum on every table in the project.
CREATE OR REPLACE FUNCTION core.ops_claim_next()
RETURNS TABLE (
    user_id      uuid,
    operation_id text,
    request_hash text,
    attempts     int,
    max_attempts int
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
BEGIN
    RETURN QUERY
    WITH claimed AS (
        SELECT o.user_id, o.operation_id
          FROM core.operations o
         WHERE o.status = 'queued'
           AND o.attempts < o.max_attempts
           AND o.expires_at > now()
         ORDER BY o.created_at
         FOR UPDATE SKIP LOCKED
         LIMIT 1
    )
    UPDATE core.operations op
       SET status       = 'running',
           attempts     = op.attempts + 1,
           heartbeat_at = now(),
           updated_at   = now()
      FROM claimed c
     WHERE op.user_id = c.user_id
       AND op.operation_id = c.operation_id
    RETURNING op.user_id, op.operation_id, op.request_hash,
              op.attempts, op.max_attempts;
END;
$$;

COMMENT ON FUNCTION core.ops_claim_next() IS
    'Claim one queued operation for this worker (FOR UPDATE SKIP LOCKED). '
    'Increments attempts so a row that keeps killing its worker dead-letters '
    'instead of looping forever.';

-- (6) Reaper: requeue instead of fail. -----------------------------------------
-- Supersedes the fail-only sweep from 57/59/65. A running row whose heartbeat
-- has gone stale means the worker died without finalizing (SIGKILL/OOM). If
-- attempts remain, put it back on the queue; only dead-letter once exhausted.
CREATE OR REPLACE FUNCTION core.ops_reclaim_stale(
    p_stale_after interval DEFAULT interval '10 minutes'
)
RETURNS TABLE (requeued bigint, dead_lettered bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
DECLARE
    v_requeued bigint := 0;
    v_dead     bigint := 0;
BEGIN
    -- Stale = no heartbeat within the window. COALESCE to updated_at so rows
    -- written before this migration (heartbeat_at NULL) are still reclaimable.
    WITH stale AS (
        SELECT o.user_id, o.operation_id, o.attempts, o.max_attempts
          FROM core.operations o
         WHERE o.status = 'running'
           AND COALESCE(o.heartbeat_at, o.updated_at) < now() - p_stale_after
         FOR UPDATE SKIP LOCKED
    ),
    requeue AS (
        UPDATE core.operations op
           SET status = 'queued',
               heartbeat_at = NULL,
               updated_at = now()
          FROM stale s
         WHERE op.user_id = s.user_id
           AND op.operation_id = s.operation_id
           AND s.attempts < s.max_attempts
        RETURNING 1
    ),
    deadletter AS (
        UPDATE core.operations op
           SET status = 'failed',
               error = jsonb_build_object(
                   'type','https://zettelkasten.in/problems/errors/worker-lost',
                   'title','Background worker lost',
                   'status',500,
                   'detail','The worker handling this operation died and the '
                            'retry budget is exhausted.',
                   'code','worker-lost'
               ),
               updated_at = now()
          FROM stale s
         WHERE op.user_id = s.user_id
           AND op.operation_id = s.operation_id
           AND s.attempts >= s.max_attempts
        RETURNING 1
    )
    SELECT (SELECT count(*) FROM requeue), (SELECT count(*) FROM deadletter)
      INTO v_requeued, v_dead;

    RETURN QUERY SELECT v_requeued, v_dead;
END;
$$;

COMMENT ON FUNCTION core.ops_reclaim_stale(interval) IS
    'Watchdog: requeue running operations whose worker died (stale heartbeat), '
    'dead-lettering only once max_attempts is exhausted. Replaces the fail-only '
    'sweep from migration 57/59/65 — that one destroyed recoverable work.';

-- (7) Repoint the cron job at the requeueing reaper. ---------------------------
-- cron.schedule upserts by jobname, so this is idempotent on re-apply.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule(
            'reap_stuck_running_operations',
            '*/2 * * * *',
            $cron$ SELECT core.ops_reclaim_stale(interval '10 minutes') $cron$
        );
    END IF;
END$$;

-- (8) Grants. ------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION core.ops_heartbeat(uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION core.ops_step_put(uuid, text, text, jsonb, text) TO service_role;
GRANT EXECUTE ON FUNCTION core.ops_step_get(uuid, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION core.ops_claim_next() TO service_role;
GRANT EXECUTE ON FUNCTION core.ops_reclaim_stale(interval) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
