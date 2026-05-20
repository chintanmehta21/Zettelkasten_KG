-- 60_zettel_enrichment_jobs.sql — durable lazy-enrichment job queue.
--
-- PR #39 / Wave-3 B1 (2026-05-20). Moves the expensive parts of Add Zettel
-- persistence (chunk segmentation + Gemini batch embedding, currently inline
-- in website.core.persist._persist_supabase_v2_zettel) OFF the critical
-- HTTP-200 path. Each canonical zettel write enqueues one row here; an
-- in-process Python poller (one per gunicorn worker) drains the queue via
-- SELECT … FOR UPDATE SKIP LOCKED and runs the handler. Postgres is the
-- only coordination point — no Redis, no Celery, no new daemons — which
-- keeps the 2 GB DigitalOcean droplet's memory budget intact.
--
-- Design references:
--   * Brandur Leach — "Postgres-as-queue" (skip-locked) — primary pattern.
--   * River, pg-boss, graphile-worker — modern Postgres-backed job queues
--     using the same FOR UPDATE SKIP LOCKED + state-machine + retry loop.
--   * Stripe / RFC 9457 — error shape on the dead-letter row (`error` jsonb).
--
-- State machine: queued -> running -> {succeeded | failed | dead_letter}.
--   succeeded / failed are terminal; dead_letter is the absorbing state
--   reached when attempts >= max_attempts (handler keeps failing).
-- The state-guarded RPCs make every transition idempotent (mirrors the
-- core.ops_accept/start/finalize design in migration 51).

BEGIN;

CREATE TABLE IF NOT EXISTS core.zettel_enrichment_jobs (
    job_id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 uuid        NOT NULL,
    canonical_zettel_id     uuid        NOT NULL,
    workspace_zettel_id     uuid        NULL,
    kind                    text        NOT NULL,
    payload                 jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status                  text        NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter')),
    attempts                int         NOT NULL DEFAULT 0,
    max_attempts            int         NOT NULL DEFAULT 3,
    error                   jsonb       NULL,
    claimed_at              timestamptz NULL,
    completed_at            timestamptz NULL,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    -- TTL aligned with core.operations (24h). The sweep in 49_operations_sweep
    -- is per-table; a separate pg_cron job for THIS table lands in the
    -- companion repeatable migration if/when needed (defaults to the row
    -- naturally being terminal long before 24h).
    expires_at              timestamptz NOT NULL DEFAULT (now() + interval '24 hours')
);

-- Per-handler dedup guard: at most one ACTIVE (queued|running|succeeded) row
-- per (canonical_zettel_id, kind). Replays from a re-deployed worker therefore
-- no-op instead of duplicate-chunking the same zettel; backfill is also safe
-- to re-run on already-enriched zettels. Failed/dead_letter rows are NOT in
-- the partial index so an operator-triggered retry can re-enqueue cleanly.
CREATE UNIQUE INDEX IF NOT EXISTS zettel_enrichment_jobs_active_uniq
    ON core.zettel_enrichment_jobs (canonical_zettel_id, kind)
    WHERE status IN ('queued', 'running', 'succeeded');

-- Poller's hot path: claim the oldest queued row. Sort by created_at ASC.
CREATE INDEX IF NOT EXISTS zettel_enrichment_jobs_queued_idx
    ON core.zettel_enrichment_jobs (created_at)
    WHERE status = 'queued';

-- Stuck-running watchdog hook: see the companion repeatable reaper that
-- promotes long-`running` rows to `failed` if a worker crashes mid-handle.
CREATE INDEX IF NOT EXISTS zettel_enrichment_jobs_running_idx
    ON core.zettel_enrichment_jobs (updated_at)
    WHERE status = 'running';

-- TTL sweep companion.
CREATE INDEX IF NOT EXISTS zettel_enrichment_jobs_expires_idx
    ON core.zettel_enrichment_jobs (expires_at);

ALTER TABLE core.zettel_enrichment_jobs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS enrichment_jobs_service_all ON core.zettel_enrichment_jobs;
CREATE POLICY enrichment_jobs_service_all ON core.zettel_enrichment_jobs
    FOR ALL
    USING (core.is_service_role())
    WITH CHECK (core.is_service_role());

COMMENT ON TABLE core.zettel_enrichment_jobs IS
    'Durable lazy-enrichment job queue (PR #39 Wave-3). Drained by an in-process Python poller using SELECT FOR UPDATE SKIP LOCKED. State-guarded RPCs (enrich_claim_next, enrich_finalize) enforce idempotent transitions.';

-- ---------------------------------------------------------------------------
-- enrich_enqueue: idempotent INSERT (no-op on active duplicate).
-- Returns the canonical job_id and an is_new flag, mirroring ops_accept.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.enrich_enqueue(
    p_user_id             uuid,
    p_canonical_zettel_id uuid,
    p_workspace_zettel_id uuid,
    p_kind                text,
    p_payload             jsonb,
    p_max_attempts        int DEFAULT 3,
    p_ttl_seconds         int DEFAULT 86400
)
RETURNS TABLE(job_id uuid, status text, is_new boolean)
LANGUAGE sql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
    WITH ins AS (
        INSERT INTO core.zettel_enrichment_jobs (
            user_id, canonical_zettel_id, workspace_zettel_id,
            kind, payload, max_attempts, expires_at
        )
        VALUES (
            p_user_id, p_canonical_zettel_id, p_workspace_zettel_id,
            p_kind, COALESCE(p_payload, '{}'::jsonb), p_max_attempts,
            now() + (p_ttl_seconds || ' seconds')::interval
        )
        ON CONFLICT (canonical_zettel_id, kind)
            WHERE status IN ('queued', 'running', 'succeeded')
            DO NOTHING
        RETURNING job_id, status
    )
    SELECT job_id, status, true AS is_new FROM ins
    UNION ALL
    SELECT job_id, status, false AS is_new
      FROM core.zettel_enrichment_jobs
     WHERE canonical_zettel_id = p_canonical_zettel_id
       AND kind = p_kind
       AND status IN ('queued', 'running', 'succeeded')
       AND NOT EXISTS (SELECT 1 FROM ins)
     LIMIT 1
$$;

COMMENT ON FUNCTION core.enrich_enqueue(uuid, uuid, uuid, text, jsonb, int, int) IS
    'Idempotent enqueue: INSERT ON CONFLICT DO NOTHING via partial unique index on (canonical_zettel_id, kind) WHERE status IN (queued, running, succeeded). Returns canonical job + is_new flag.';

-- ---------------------------------------------------------------------------
-- enrich_claim_next: claim ONE oldest queued job for the worker.
-- Uses SELECT … FOR UPDATE SKIP LOCKED for safe multi-worker concurrency:
-- two workers polling simultaneously each get a distinct row (or NULL if
-- the queue is empty). Increments attempts so a row that fails to write
-- its terminal state doesn't get re-claimed forever.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.enrich_claim_next()
RETURNS TABLE(
    job_id                  uuid,
    user_id                 uuid,
    canonical_zettel_id     uuid,
    workspace_zettel_id     uuid,
    kind                    text,
    payload                 jsonb,
    attempts                int,
    max_attempts            int
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
DECLARE
    v_job_id uuid;
BEGIN
    -- Pick the oldest queued row, locking it so concurrent claim_next calls
    -- from other gunicorn workers (or other droplets, later) skip it.
    SELECT j.job_id INTO v_job_id
      FROM core.zettel_enrichment_jobs j
     WHERE j.status = 'queued'
     ORDER BY j.created_at ASC
     FOR UPDATE SKIP LOCKED
     LIMIT 1;

    IF v_job_id IS NULL THEN
        RETURN;  -- empty queue
    END IF;

    UPDATE core.zettel_enrichment_jobs
       SET status     = 'running',
           attempts   = attempts + 1,
           claimed_at = now(),
           updated_at = now()
     WHERE core.zettel_enrichment_jobs.job_id = v_job_id;

    RETURN QUERY
        SELECT j.job_id, j.user_id, j.canonical_zettel_id,
               j.workspace_zettel_id, j.kind, j.payload,
               j.attempts, j.max_attempts
          FROM core.zettel_enrichment_jobs j
         WHERE j.job_id = v_job_id;
END;
$$;

COMMENT ON FUNCTION core.enrich_claim_next() IS
    'Claim one queued enrichment job atomically (FOR UPDATE SKIP LOCKED). Increments attempts; returns row or empty when queue is drained.';

-- ---------------------------------------------------------------------------
-- enrich_finalize: (running) -> (succeeded | failed | dead_letter).
-- The WHERE status = 'running' guard makes duplicate finalize a no-op.
-- A handler that wants the row re-queued for retry should pass
-- target='failed'; if attempts < max_attempts the caller may then call
-- enrich_requeue (below). target='dead_letter' is absorbing.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.enrich_finalize(
    p_job_id  uuid,
    p_target  text,
    p_error   jsonb DEFAULT NULL
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
DECLARE
    v_status text;
BEGIN
    IF p_target NOT IN ('succeeded', 'failed', 'dead_letter') THEN
        RAISE EXCEPTION 'enrich_finalize: invalid target %, must be one of (succeeded, failed, dead_letter)', p_target
            USING ERRCODE = '22023';
    END IF;

    UPDATE core.zettel_enrichment_jobs
       SET status       = p_target,
           error        = p_error,
           completed_at = now(),
           updated_at   = now()
     WHERE job_id = p_job_id
       AND status = 'running'
    RETURNING status INTO v_status;

    RETURN v_status;
END;
$$;

COMMENT ON FUNCTION core.enrich_finalize(uuid, text, jsonb) IS
    '(running) -> terminal transition guard. NULL return on no-op (already terminal). Kills duplicate-finalize race for retried handler completions.';

-- ---------------------------------------------------------------------------
-- enrich_requeue: a handler that failed transiently and still has retries
-- available calls this to atomically reset the row back to 'queued'. If
-- attempts >= max_attempts, the row is moved to 'dead_letter' instead and
-- requires operator action to re-enqueue.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.enrich_requeue(
    p_job_id  uuid,
    p_error   jsonb DEFAULT NULL
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
DECLARE
    v_attempts int;
    v_max int;
    v_status text;
BEGIN
    SELECT attempts, max_attempts INTO v_attempts, v_max
      FROM core.zettel_enrichment_jobs
     WHERE job_id = p_job_id AND status = 'running'
     FOR UPDATE;

    IF v_attempts IS NULL THEN
        RETURN NULL;  -- not running / nonexistent
    END IF;

    IF v_attempts >= v_max THEN
        UPDATE core.zettel_enrichment_jobs
           SET status       = 'dead_letter',
               error        = p_error,
               completed_at = now(),
               updated_at   = now()
         WHERE job_id = p_job_id
        RETURNING status INTO v_status;
    ELSE
        UPDATE core.zettel_enrichment_jobs
           SET status       = 'queued',
               error        = p_error,
               updated_at   = now()
         WHERE job_id = p_job_id
        RETURNING status INTO v_status;
    END IF;

    RETURN v_status;
END;
$$;

COMMENT ON FUNCTION core.enrich_requeue(uuid, jsonb) IS
    'Transient-failure retry: running -> queued when attempts < max_attempts, else running -> dead_letter (absorbing).';

GRANT EXECUTE ON FUNCTION core.enrich_enqueue(uuid, uuid, uuid, text, jsonb, int, int) TO service_role;
GRANT EXECUTE ON FUNCTION core.enrich_claim_next() TO service_role;
GRANT EXECUTE ON FUNCTION core.enrich_finalize(uuid, text, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION core.enrich_requeue(uuid, jsonb) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
