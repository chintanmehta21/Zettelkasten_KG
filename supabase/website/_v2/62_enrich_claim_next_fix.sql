-- 62_enrich_claim_next_fix.sql — HOTFIX for migration 60's broken claim RPC.
--
-- PR #40 (2026-05-21). Migration 60 shipped `core.enrich_claim_next()` with
-- an UPDATE statement that referenced the bare column name ``attempts``:
--
--     UPDATE core.zettel_enrichment_jobs
--        SET status   = 'running',
--            attempts = attempts + 1,    -- <-- AMBIGUOUS in plpgsql
--            ...
--
-- The function declares ``attempts`` as an OUT column on its
-- ``RETURNS TABLE(...)`` clause. Inside the plpgsql body, that OUT column
-- becomes a variable in scope. Postgres can't disambiguate the RHS ``attempts``
-- between the table column and the OUT variable and raises:
--
--     ERROR  42702: column reference "attempts" is ambiguous
--     DETAIL: It could refer to either a PL/pgSQL variable or a table column.
--
-- Live consequence (observed 2026-05-20 → 2026-05-21): every worker poll
-- raises this APIError, so the queue NEVER drains. Naruto's
-- ``ZoibAbdQf58`` (canonical 2f5f7fe3-...) plus every Add-Zettel since the
-- 2026-05-20T18:54Z deploy is stuck ``queued`` with attempts=0.
--
-- Fix: add the ``#variable_conflict use_column`` plpgsql directive at the
-- top of the function body. This tells the parser: when a name is
-- ambiguous, prefer the table column. The directive is a recognised
-- comment-style hint in plpgsql (NOT a SQL comment) — see PostgreSQL docs
-- ``41.10.1. Variable Substitution`` and ``41.11.1 Plpgsql function
-- arguments``. Zero behaviour change to working RPCs; only kills the
-- ambiguity error.
--
-- Why we only patch ``enrich_claim_next`` and not the other plpgsql RPCs
-- in migration 60: ``enrich_finalize`` and ``enrich_requeue`` return scalar
-- ``text`` (no OUT-table columns), so no name shadowing exists today.
-- Touching them adds zero value and expands the hotfix blast radius. If a
-- similar bug surfaces in those later, we'll patch them in a follow-up.
--
-- Migration safety:
--   * CREATE OR REPLACE — no DROP, function OID stable, grants preserved.
--   * Function signature unchanged (same OUT columns, same arg list).
--   * SECURITY DEFINER + search_path unchanged.
--   * No table touched, no data migrated, no index rebuilt.
--   * Idempotent — re-applying is a no-op.

BEGIN;

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
#variable_conflict use_column
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

    -- Bump attempts + flip queued -> running. Fully qualified table name on
    -- WHERE keeps the partial unique index happy; the SET clause now
    -- references the column unambiguously courtesy of the directive above.
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
    'Claim one queued enrichment job atomically (FOR UPDATE SKIP LOCKED). Increments attempts; returns row or empty when queue is drained. PR #40 hotfix: `#variable_conflict use_column` directive disambiguates the bare `attempts` reference from the OUT-table column of the same name (migration 60 left this broken, freezing the queue from 2026-05-20T18:54Z deploy).';

-- service_role GRANT was set in migration 60 and survives CREATE OR REPLACE;
-- no re-grant needed.

COMMIT;

NOTIFY pgrst, 'reload schema';
