-- 75_ops_finalize_extended_ttl.down.sql — revert ops_finalize to the
-- migration-51 body (no expires_at bump on terminal states).

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
           updated_at = now()
     WHERE user_id = p_user_id
       AND operation_id = p_operation_id
       AND status IN ('queued', 'running')
    RETURNING status INTO v_status;

    RETURN v_status;
END;
$$;

GRANT EXECUTE ON FUNCTION core.ops_finalize(uuid, text, text, jsonb, jsonb) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
