-- Reverse migration 87. Idempotent.
BEGIN;
  DROP POLICY IF EXISTS workspace_zettels_community_reader_select ON content.workspace_zettels;
  DROP POLICY IF EXISTS canonical_zettels_community_reader_select ON content.canonical_zettels;
  DROP POLICY IF EXISTS workspaces_community_reader_select ON core.workspaces;
  DROP POLICY IF EXISTS profiles_community_reader_select ON core.profiles;
  DO $$
  BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'community_reader') THEN
      -- Function 88 must be dropped (or re-owned) before the role can drop; the
      -- 88 down-migration handles that. If 88 is still present this REVOKE/DROP
      -- of grants is still safe.
      REVOKE SELECT ON
        content.workspace_zettels,
        content.canonical_zettels,
        core.workspaces,
        core.profiles
      FROM community_reader;
      REVOKE USAGE ON SCHEMA content, core FROM community_reader;
      DROP ROLE community_reader;
    END IF;
  END $$;
COMMIT;
NOTIFY pgrst, 'reload schema';
