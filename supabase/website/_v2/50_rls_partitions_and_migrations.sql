-- Phase 8.5: close Supabase Advisor "Policy Exists RLS Disabled" CRITICALs on
-- the new project (icmnskseuoteyirljswd) after the auth/project migration.
--
-- Findings from the prod audit (see plan in chat 2026-05-20):
--   * core._migrations_applied
--       - relrowsecurity = false
--       - policy 'service_role_all' (FOR ALL TO service_role USING true) exists
--         but is dormant because RLS is off.
--       - GRANTs accidentally allow authenticated DELETE/INSERT/SELECT/UPDATE:
--         any logged-in user could read/modify the migrations bookkeeping
--         table. This is the real risk the advisor is flagging.
--   * core.usage_events (parent)
--       - RLS enabled, policy usage_events_workspace_all applies to queries
--         through the parent.
--   * All 8 existing partitions (core.usage_events_default + 7 monthly)
--       - relrowsecurity = false. Direct partition queries bypass the parent
--         policy. PG does not cascade RLS from parent to child partitions.
--   * pg_partman parent has no template_table, so new monthly partitions
--       created by partman_run_maintenance also start with RLS off.
--
-- Ref audit: only service_role (website backend via UsageEventsRepository) and
-- postgres superuser (apply_migrations.py and ops scripts) touch these tables.
-- Both bypass RLS. No anon/authenticated consumer exists. Zero blast radius.

------------------------------------------------------------------------------
-- 1. core._migrations_applied — enable RLS, keep service_role_all policy,
--    revoke the over-broad authenticated/anon grants.
------------------------------------------------------------------------------
ALTER TABLE core._migrations_applied ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON core._migrations_applied FROM anon, authenticated;
-- service_role_all policy intentionally kept: it's the correct intent and
-- becomes effective now that RLS is on.

------------------------------------------------------------------------------
-- 2. core.usage_events — re-assert parent RLS (idempotent) + enable on every
--    existing child partition. No per-partition policy needed: direct
--    partition queries by authenticated are denied by default, which is the
--    desired outcome. service_role/postgres bypass RLS so backend writes and
--    aggregate jobs are unaffected.
------------------------------------------------------------------------------
ALTER TABLE core.usage_events ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT format('%I.%I', n.nspname, c.relname) AS qtn
        FROM pg_inherits i
        JOIN pg_class     c ON c.oid = i.inhrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.inhparent = 'core.usage_events'::regclass
          AND c.relrowsecurity = false
    LOOP
        EXECUTE 'ALTER TABLE ' || r.qtn || ' ENABLE ROW LEVEL SECURITY';
        RAISE NOTICE 'Enabled RLS on %', r.qtn;
    END LOOP;
END
$$;

------------------------------------------------------------------------------
-- 3. Maintenance function + daily cron to cover future partitions created by
--    partman_run_maintenance (02:15 daily per 07_partman_setup.sql). Runs
--    15 minutes after partman to catch newly-minted monthly children.
------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.enforce_rls_on_usage_events_partitions()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, core
AS $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT format('%I.%I', n.nspname, c.relname) AS qtn
        FROM pg_inherits i
        JOIN pg_class     c ON c.oid = i.inhrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.inhparent = 'core.usage_events'::regclass
          AND c.relrowsecurity = false
    LOOP
        EXECUTE 'ALTER TABLE ' || r.qtn || ' ENABLE ROW LEVEL SECURITY';
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION core.enforce_rls_on_usage_events_partitions() FROM PUBLIC;

DO $$
BEGIN
    PERFORM cron.schedule(
        'enforce_rls_usage_events_partitions',
        '30 2 * * *',
        $cron$SELECT core.enforce_rls_on_usage_events_partitions();$cron$
    );
EXCEPTION WHEN unique_violation THEN
    RAISE NOTICE 'cron job enforce_rls_usage_events_partitions already exists';
END
$$;
