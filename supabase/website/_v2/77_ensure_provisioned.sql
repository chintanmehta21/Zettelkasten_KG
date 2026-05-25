-- 77_ensure_provisioned.sql
-- Idempotent JIT provisioning RPC — belt-and-braces for the rare case where
-- the AFTER INSERT trigger chain on auth.users (handle_new_auth_user ->
-- create_personal_workspace) failed silently or hasn't yet propagated.
--
-- Called from /api/me only when the v2 profile lookup returns None. Safe to
-- call any number of times for the same user (idempotent).
--
-- Schema invariants (see _v2/01_core_schema.sql):
--   * core.profiles.id = auth.users.id  (PK + FK ON DELETE CASCADE)
--   * core.workspaces has partial unique index
--       idx_workspaces_owner_personal ON (owner_profile_id) WHERE is_personal
--     → ON CONFLICT must target that index explicitly (bare ON CONFLICT DO
--       NOTHING does NOT cover partial unique indexes).
--   * core.workspace_members PK is (workspace_id, profile_id).
--   * trg_profile_personal_workspace fires AFTER INSERT on core.profiles and
--     creates the personal workspace + owner membership. So in the *happy*
--     path the first INSERT INTO core.profiles below transitively does all
--     three inserts; this RPC's later inserts become true no-ops.
--   * trg_workspace_members_jwt_sync updates auth.users.raw_app_meta_data on
--     membership INSERT, so the workspace_ids JWT claim is repaired too.
--
-- Versioned, immutable (schema-drift gate frozen).

CREATE OR REPLACE FUNCTION core.ensure_provisioned(
    p_auth_user_id  uuid,
    p_email         text DEFAULT NULL,
    p_display_name  text DEFAULT NULL
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
-- search_path='' (stricter than sibling 53's pg_catalog,public). Auth-path
-- function stays hardened per 2024-2026 Supabase advisory; body uses pg_catalog only.
SET search_path = ''
AS $$
DECLARE
    v_profile_id     uuid;
    v_workspace_id   uuid;
    v_resolved_email text;
    v_resolved_name  text;
BEGIN
    IF p_auth_user_id IS NULL THEN
        RAISE EXCEPTION 'ensure_provisioned: p_auth_user_id must not be null'
            USING ERRCODE = '22023';
    END IF;

    -- Resolve email + display_name from auth.users when not supplied. The
    -- handle_new_auth_user trigger uses raw_user_meta_data ->> 'name'; we
    -- accept 'full_name' too for parity with the OAuth provider payloads
    -- (Google / GitHub) where the JIT path is the most likely caller.
    IF p_email IS NULL OR p_display_name IS NULL THEN
        SELECT u.email,
               COALESCE(
                   u.raw_user_meta_data ->> 'name',
                   u.raw_user_meta_data ->> 'full_name'
               )
          INTO v_resolved_email, v_resolved_name
          FROM auth.users u
         WHERE u.id = p_auth_user_id;
    END IF;

    v_resolved_email := COALESCE(p_email, v_resolved_email);
    v_resolved_name  := COALESCE(p_display_name, v_resolved_name);

    -- Idempotent profile insert. Fires trg_profile_personal_workspace on first
    -- success (which creates workspace + membership). ON CONFLICT path is a
    -- no-op and the trigger does NOT re-fire — that's handled below.
    INSERT INTO core.profiles (id, email, display_name)
    VALUES (p_auth_user_id, v_resolved_email, v_resolved_name)
    ON CONFLICT (id) DO NOTHING;

    v_profile_id := p_auth_user_id;

    -- Backfill personal workspace + membership if missing. The membership
    -- check is the canonical "is this user provisioned?" predicate (the JWT
    -- sync trigger keys off it, and /api/me's v2 path needs at least one
    -- membership). Cover both cases: trigger didn't fire (no workspace) AND
    -- workspace exists but membership row is gone.
    IF NOT EXISTS (
        SELECT 1 FROM core.workspace_members
         WHERE profile_id = v_profile_id
    ) THEN
        -- Partial unique idx_workspaces_owner_personal requires explicit
        -- conflict target (WHERE clause mirrored). If the row already exists
        -- (trigger fired but membership got deleted out-of-band), this falls
        -- through and we look the row up below.
        INSERT INTO core.workspaces (owner_profile_id, name, is_personal)
        VALUES (v_profile_id, 'Personal', true)
        ON CONFLICT (owner_profile_id) WHERE is_personal DO NOTHING
        RETURNING id INTO v_workspace_id;

        IF v_workspace_id IS NULL THEN
            SELECT w.id
              INTO v_workspace_id
              FROM core.workspaces w
             WHERE w.owner_profile_id = v_profile_id
               AND w.is_personal
             LIMIT 1;
        END IF;

        -- If we still have no workspace something has gone very wrong (the
        -- INSERT silently failed AND the SELECT found nothing). Surface it
        -- instead of pressing on with a NULL FK that would fail downstream.
        IF v_workspace_id IS NULL THEN
            RAISE EXCEPTION 'ensure_provisioned: failed to create or locate personal workspace for profile %', v_profile_id
                USING ERRCODE = 'P0001';
        END IF;

        INSERT INTO core.workspace_members (workspace_id, profile_id, role)
        VALUES (v_workspace_id, v_profile_id, 'owner')
        ON CONFLICT (workspace_id, profile_id) DO NOTHING;
    END IF;

    RETURN v_profile_id;
END;
$$;

GRANT EXECUTE ON FUNCTION core.ensure_provisioned(uuid, text, text) TO authenticated, service_role;
REVOKE EXECUTE ON FUNCTION core.ensure_provisioned(uuid, text, text) FROM PUBLIC, anon;

COMMENT ON FUNCTION core.ensure_provisioned(uuid, text, text) IS
  'Idempotent JIT provisioning RPC — inserts profile + personal workspace + '
  'owner membership for an auth user if any are missing. Called from /api/me '
  'only when v2 profile lookup returns None (rare — trigger failure window). '
  'Safe to call repeatedly: profile and membership inserts both use '
  'ON CONFLICT DO NOTHING with the correct (partial) unique-index targets. '
  'Raises SQLSTATE 42501 via trg_workspaces_allowlist_check if the profile '
  'allowlist_status != ''allowed''; callers must map 42501 to HTTP 403.';

NOTIFY pgrst, 'reload schema';
