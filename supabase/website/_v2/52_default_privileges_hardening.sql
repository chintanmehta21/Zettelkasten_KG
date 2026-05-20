-- Phase 8.5: structural defense — set default privileges on every v2 schema
-- so any table created in the future (by a new migration, by pg_partman, or
-- by hand) starts with safe grants and cannot be exposed via PostgREST by
-- accident.
--
-- Background: a prior audit (2026-05-20) confirmed pg_default_acl has zero
-- rows for any v2 schema. That means a future table that someone forgets to
-- `ENABLE ROW LEVEL SECURITY` on AND that gets touched by any `GRANT ON ALL
-- TABLES IN SCHEMA` block downstream would be exposed to anon/authenticated.
-- ALTER DEFAULT PRIVILEGES locks the door at the schema level so the policy
-- gate (08_rls_policies.sql) is no longer the only safety net.
--
-- Scope (precise, per PG docs on ALTER DEFAULT PRIVILEGES):
--   * Affects ONLY objects created AFTER this migration runs.
--   * Does NOT touch any existing table, view, or sequence in these schemas.
--   * Does NOT alter pre-existing grants on the parent partitioned tables;
--     the explicit `GRANT ... ON ALL TABLES IN SCHEMA` blocks in
--     08_rls_policies.sql:8 remain authoritative for already-existing rows.
--
-- Service role keeps full DML so the website backend (UsageEventsRepository
-- and every future repository) continues to write through the v2 client.

DO $$
DECLARE
    sch text;
BEGIN
    FOREACH sch IN ARRAY ARRAY['core','content','kg','rag','pipelines','billing']
    LOOP
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM anon, authenticated',
            sch
        );
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON TABLES TO service_role',
            sch
        );
        RAISE NOTICE 'default privileges hardened on schema %', sch;
    END LOOP;
END
$$;
