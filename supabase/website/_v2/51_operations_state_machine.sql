-- 51_operations_state_machine.sql — async-ops redesign Phase 1.
--
-- Replaces the per-worker in-memory _OPERATIONS/_IN_FLIGHT/_OPERATION_TASKS
-- dicts with a Postgres-as-only-truth state machine: an expanded status CHECK
-- + a partial UNIQUE index for Stripe/Brandur-style per-(user,request_hash)
-- idempotency + three SECURITY DEFINER RPCs (ops_accept / ops_start /
-- ops_finalize) whose WHERE-clause state guards make the 8-bug Codex class
-- impossible by construction (no blind UPDATE, no terminal-overwrite, no
-- duplicate-finalize race).
--
-- Operator decision (2026-05-20): drop CREATE INDEX CONCURRENTLY and build the
-- partial unique index inline in this single transactional file. Rationale:
-- core.operations is a small operational queue (sub-second build, brief
-- ACCESS EXCLUSIVE well within the 180s GUNICORN_TIMEOUT envelope). The
-- migration runner (ops/scripts/apply_migrations.py) wraps each file in
-- psycopg `autocommit=False`, so CONCURRENTLY (which forbids transactions)
-- cannot run via the runner anyway.
--
-- Co-apply: ship with the Python adapter (Phase 2) so 'accepted' is no longer
-- written by the app after deploy. Backfill rewrites any in-flight 'accepted'
-- rows to 'queued' BEFORE the CHECK swap so the new constraint accepts them.
-- Versioned, immutable (schema-drift gate frozen).

BEGIN;

-- (1) Data backfill: rewrite legacy 'accepted' to the new 'queued' lexicon
-- BEFORE the CHECK swap, otherwise the new constraint rejects in-flight rows.
UPDATE core.operations SET status = 'queued' WHERE status = 'accepted';

-- (2) CHECK swap. The inline CHECK on column `status` in 48_operations.sql
-- was unnamed at create-time, so Postgres assigned the conventional default
-- name `operations_status_check` (table_basename + '_' + colname + '_check').
-- `DROP CONSTRAINT IF EXISTS` is a no-op if the name doesn't match — the
-- new ADD CONSTRAINT below is the authoritative guard either way.
ALTER TABLE core.operations
    DROP CONSTRAINT IF EXISTS operations_status_check;
ALTER TABLE core.operations
    ADD CONSTRAINT operations_status_check
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired'));

-- (3) Partial UNIQUE index on (user_id, request_hash) WHERE status active.
-- Implements Stripe/Brandur idempotency-key semantics scoped per user:
-- terminal failed/cancelled/expired rows DO NOT block a fresh accept (caller
-- can retry after a server-side failure); terminal succeeded DOES dedup
-- (replay protection — same request returns same result).
CREATE UNIQUE INDEX IF NOT EXISTS ops_user_req_hash_active_uniq
    ON core.operations (user_id, request_hash)
    WHERE status IN ('queued', 'running', 'succeeded');

-- (4) RPCs. All SECURITY DEFINER + SET search_path so a compromised search
-- path in the service-role session cannot shadow `core.operations`.

-- ops_accept: atomic INSERT … ON CONFLICT DO NOTHING against the partial
-- unique index, then return the canonical row + is_new flag. The CTE pattern
-- guarantees exactly one row is returned whether the INSERT fired or the
-- caller hit an existing active op.
CREATE OR REPLACE FUNCTION core.ops_accept(
    p_user_id      uuid,
    p_operation_id text,
    p_request_hash text,
    p_accepted     jsonb,
    p_ttl_seconds  int DEFAULT 86400
)
RETURNS TABLE(operation_id text, status text, is_new boolean)
LANGUAGE sql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
    WITH ins AS (
        INSERT INTO core.operations (
            user_id, operation_id, request_hash, status,
            response, error, expires_at
        )
        VALUES (
            p_user_id, p_operation_id, p_request_hash, 'queued',
            p_accepted, NULL,
            now() + (p_ttl_seconds || ' seconds')::interval
        )
        ON CONFLICT (user_id, request_hash)
            WHERE status IN ('queued', 'running', 'succeeded')
            DO NOTHING
        RETURNING operation_id, status
    )
    SELECT operation_id, status, true AS is_new FROM ins
    UNION ALL
    SELECT operation_id, status, false AS is_new
      FROM core.operations
     WHERE user_id = p_user_id
       AND request_hash = p_request_hash
       AND status IN ('queued', 'running', 'succeeded')
       AND NOT EXISTS (SELECT 1 FROM ins)
     LIMIT 1
$$;

COMMENT ON FUNCTION core.ops_accept(uuid, text, text, jsonb, int) IS
    'Idempotent accept: INSERT…ON CONFLICT DO NOTHING via partial unique index '
    '(user_id, request_hash) WHERE status IN (queued,running,succeeded). '
    'Returns the canonical row + is_new=false on duplicate active request.';

-- ops_start: queued -> running transition. WHERE status='queued' guards
-- against double-start; returns NULL via RETURNING when no row matched
-- (already running, terminal, or nonexistent).
CREATE OR REPLACE FUNCTION core.ops_start(
    p_user_id      uuid,
    p_operation_id text
)
RETURNS text
LANGUAGE sql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
    UPDATE core.operations
       SET status = 'running',
           updated_at = now()
     WHERE user_id = p_user_id
       AND operation_id = p_operation_id
       AND status = 'queued'
    RETURNING status;
$$;

COMMENT ON FUNCTION core.ops_start(uuid, text) IS
    'queued -> running transition guard. Returns NULL on no-op (already '
    'running, terminal, or nonexistent).';

-- ops_finalize: (queued|running) -> (succeeded|failed|cancelled). The WHERE
-- status IN ('queued','running') predicate is THE bug-class killer: a second
-- finalize attempt against a row already in a terminal state is a silent
-- no-op (RETURNING NULL), so the create_accepted-overwrite and duplicate-
-- finalize races from the legacy in-memory design cannot fire here.
CREATE OR REPLACE FUNCTION core.ops_finalize(
    p_user_id      uuid,
    p_operation_id text,
    p_target       text,
    p_response     jsonb,
    p_error        jsonb
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = 'core', 'public'
AS $$
DECLARE
    v_status text;
BEGIN
    IF p_target NOT IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'ops_finalize: invalid target status %, must be one of (succeeded, failed, cancelled)', p_target
            USING ERRCODE = '22023';
    END IF;

    UPDATE core.operations
       SET status     = p_target,
           response   = p_response,
           error      = p_error,
           updated_at = now()
     WHERE user_id = p_user_id
       AND operation_id = p_operation_id
       AND status IN ('queued', 'running')
    RETURNING status INTO v_status;

    RETURN v_status;
END;
$$;

COMMENT ON FUNCTION core.ops_finalize(uuid, text, text, jsonb, jsonb) IS
    '(queued|running) -> terminal transition guard. Returns NULL on no-op '
    'when row is already terminal — kills the duplicate-finalize bug class.';

-- (5) GRANT EXECUTE to service_role. Migration 48 relied on RLS for the
-- table; for SECURITY DEFINER functions, PostgREST additionally requires
-- explicit EXECUTE on the function. Without these grants the new RPCs
-- return 401/403 to the v2 service-role client.
GRANT EXECUTE ON FUNCTION core.ops_accept(uuid, text, text, jsonb, int) TO service_role;
GRANT EXECUTE ON FUNCTION core.ops_start(uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION core.ops_finalize(uuid, text, text, jsonb, jsonb) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
