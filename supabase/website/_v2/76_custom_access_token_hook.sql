-- 76_custom_access_token_hook.sql
-- Custom Access Token Hook — injects workspace_ids into JWT app_metadata at mint time.
-- Closes the gotrue OAuth code-ordering defect where the JWT is issued before the
-- AFTER INSERT trigger chain on auth.users runs (upstream: supabase/auth#1280).
-- Industry precedent: Auth0 Post-Login Action, AWS Cognito Pre-Token Generation.
--
-- Contract per Supabase docs (Auth Hooks → Custom Access Token):
--   * Input  jsonb event of shape {user_id: uuid, claims: {...}, authentication_method: text}
--   * Output jsonb event with the same shape; mutate `claims` only.
--
-- Grants (industry-standard hard pin per Supabase 2024-2026 advisory):
--   * GRANT EXECUTE only to supabase_auth_admin (the gotrue role that invokes
--     hooks). REVOKE from PUBLIC, authenticated, anon so the hook cannot be
--     called by an end-user JWT or anonymous request.
--
-- Hook registration is a Dashboard step (Auth → Hooks → Custom Access Token);
-- this migration creates the function only. Registration is intentionally a
-- one-click operator action so a misconfigured hook cannot land via deploy.
--
-- Versioned, immutable (schema-drift gate frozen).

CREATE OR REPLACE FUNCTION core.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_claims        jsonb;
    v_auth_user_id  uuid;
    v_workspace_ids uuid[];
BEGIN
    v_auth_user_id := (event ->> 'user_id')::uuid;
    v_claims := event -> 'claims';

    -- Membership lookup is the canonical source of truth for which workspaces
    -- a user can act in. ORDER BY added_at for a stable JWT shape across mints
    -- (otherwise asyncpg-cached PostgREST clients see id-array re-ordering and
    -- trigger spurious cache invalidations).
    SELECT COALESCE(array_agg(wm.workspace_id ORDER BY wm.added_at), ARRAY[]::uuid[])
      INTO v_workspace_ids
    FROM core.workspace_members wm
    WHERE wm.profile_id = v_auth_user_id;

    -- Defensive: ensure claims and claims.app_metadata exist before nested set.
    -- gotrue passes claims as a non-null object today, but the hook contract
    -- doesn't *require* app_metadata to be present, so we materialize it.
    IF v_claims IS NULL THEN
        v_claims := '{}'::jsonb;
    END IF;
    IF v_claims -> 'app_metadata' IS NULL OR jsonb_typeof(v_claims -> 'app_metadata') <> 'object' THEN
        v_claims := jsonb_set(v_claims, '{app_metadata}', '{}'::jsonb, true);
    END IF;

    v_claims := jsonb_set(v_claims, '{app_metadata, workspace_ids}', to_jsonb(v_workspace_ids), true);

    RETURN jsonb_set(event, '{claims}', v_claims, true);
END;
$$;

GRANT EXECUTE ON FUNCTION core.custom_access_token_hook(jsonb) TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION core.custom_access_token_hook(jsonb) FROM PUBLIC, anon, authenticated;

COMMENT ON FUNCTION core.custom_access_token_hook(jsonb) IS
  'Supabase Auth Custom Access Token Hook — injects core.workspace_members → '
  'app_metadata.workspace_ids at JWT mint time. Register via Dashboard → Auth → '
  'Hooks → Custom Access Token. Closes JWT staleness on first OAuth signup '
  '(supabase/auth#1280 code-ordering defect).';

NOTIFY pgrst, 'reload schema';
