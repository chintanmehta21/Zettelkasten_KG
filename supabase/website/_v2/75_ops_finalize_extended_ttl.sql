-- 75_ops_finalize_extended_ttl.sql — extend core.operations TTL on terminal
-- non-success states so post-hoc failure analysis has a 7-day window instead
-- of 24 hours.
--
-- Why: the 24h `expires_at` on core.operations (migration 48) was designed
-- around the client-polling lifecycle: a row only needs to survive long
-- enough for the front-end to fetch the result. For *successful* operations
-- that lifecycle is the right one — the durable record is the
-- workspace_zettel row, the operations row is just the rendezvous point.
-- For *failed* and *cancelled* operations the operations row is the ONLY
-- durable trace (workspace_zettel was never written), and 24h is too short
-- to support a meaningful failure-pattern audit. The 2026-05-25 Nimit sweep
-- found exactly one in-window failure for him; everything older was already
-- pruned, so the engine appeared healthier than it actually is.
--
-- Change: extend `expires_at` to now() + 7 days when ops_finalize transitions
-- to `failed` or `cancelled`. `succeeded` keeps its original 24h schedule —
-- bumping succeeded rows would inflate the table for no analytical gain
-- (the canonical/workspace record IS the durable trace).
--
-- Forward-compat: the sweep/reaper RPCs (49_operations_sweep, 57_stuck_running_reaper,
-- 59_reaper_threshold_7m, 65_reaper_threshold_10m) all key off `expires_at`,
-- so bumping the column here is the ONLY change needed — the reapers
-- naturally respect the new horizon.
--
-- Versioned, immutable (schema-drift gate frozen).

BEGIN;

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
           updated_at = now(),
           -- 7-day forensic window on failed/cancelled; succeeded keeps its
           -- original (24h-from-accept) schedule. CASE-expression makes the
           -- assignment idempotent on retries (failed rows that re-finalize
           -- keep extending — the WHERE guard below limits to queued|running
           -- so practically this only sets the value once).
           expires_at = CASE
               WHEN p_target IN ('failed', 'cancelled')
                   THEN now() + interval '7 days'
               ELSE expires_at
           END
     WHERE user_id = p_user_id
       AND operation_id = p_operation_id
       AND status IN ('queued', 'running')
    RETURNING status INTO v_status;

    RETURN v_status;
END;
$$;

COMMENT ON FUNCTION core.ops_finalize(uuid, text, text, jsonb, jsonb) IS
    '(queued|running) -> terminal transition guard. Returns NULL on no-op '
    'when row is already terminal — kills the duplicate-finalize bug class. '
    'Migration 75 (2026-05-25): bumps expires_at to now()+7d on failed/cancelled '
    'so post-hoc failure analysis has a meaningful window; succeeded keeps 24h.';

-- Re-grant after CREATE OR REPLACE just to be sure the EXECUTE bit didn't
-- get dropped by any RLS hardening migration that ran in between.
GRANT EXECUTE ON FUNCTION core.ops_finalize(uuid, text, text, jsonb, jsonb) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
