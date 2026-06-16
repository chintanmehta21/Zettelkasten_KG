-- Migration 87 (Community Graph Part B / Phase 0 — P0-c): least-privilege
-- public-read role + RLS fail-closed policy.
--
-- WHY: the app talks to Supabase via the service_role client, which has
-- BYPASSRLS — so RLS is INERT on the app path and the app-layer WHERE filter is
-- the only runtime gate there. The decisive upgrade (design D4, APPROVED
-- 2026-06-16): serve view=global through a SEPARATE non-BYPASSRLS, SELECT-only
-- role that OWNS the community RPC (migration 88). Because a SECURITY DEFINER
-- function executes as its owner, the RPC body runs as community_reader, and a
-- forgotten predicate then FAILS CLOSED at the row level via the policy below —
-- under opt-out, that policy protects the marked-PRIVATE subset.
--
-- Mirrors 79_stats_reader_role.sql (NOLOGIN role + hard timeouts + static
-- least-priv SELECT grants) and the RLS-policy idiom in 29_kasten_sharing_rls.sql.
-- community_reader needs SELECT on every table the RPC reads (it runs AS this
-- role): content.workspace_zettels + content.canonical_zettels (the surface) and
-- core.workspaces + core.profiles (attribution display_name join).
-- Idempotent: pg_roles guard + DROP/CREATE POLICY + IF NOT EXISTS grants.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'community_reader') THEN
    CREATE ROLE community_reader NOLOGIN;
  END IF;
END $$;

-- Hard guardrails (a runaway public-graph aggregation must not starve OLTP /
-- OOM the 2 GB droplet). Mirrors 79's stats_reader settings.
ALTER ROLE community_reader SET statement_timeout = '30s';
ALTER ROLE community_reader SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE community_reader SET lock_timeout = '5s';
ALTER ROLE community_reader SET work_mem = '32MB';

GRANT USAGE ON SCHEMA content, core TO community_reader;

-- Static least-privilege grant list. community_reader OWNS the community RPC
-- (88) and runs its body; these are exactly the tables that RPC reads.
GRANT SELECT ON
  content.workspace_zettels,
  content.canonical_zettels,
  core.workspaces,
  core.profiles
TO community_reader;

-- Fail-closed RLS: RLS is already ENABLED on content.workspace_zettels
-- (08_rls_policies.sql:22). Add a SELECT policy scoping community_reader to
-- PUBLIC (non-private, non-deleted) rows ONLY. service_role keeps BYPASSRLS
-- (its own FOR ALL policy is unchanged); authenticated's own-workspace SELECT
-- policy is unchanged; there is NO anon SELECT policy (verified) so PostgREST
-- anon cannot read this table.
DROP POLICY IF EXISTS workspace_zettels_community_reader_select ON content.workspace_zettels;
CREATE POLICY workspace_zettels_community_reader_select ON content.workspace_zettels
    FOR SELECT TO community_reader USING (is_private = false AND deleted_at IS NULL);

COMMIT;

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
