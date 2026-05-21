-- 64_grant_all_v2_tables_to_service_role.sql --
-- Explicit per-table GRANT to service_role for EVERY v2 table.
--
-- This is the comprehensive companion to 63_grant_v2_tables_to_service_role.sql.
-- Where 63 fixed the three gap-zone tables (core.operations,
-- billing.pricing_usage_counters, billing.pricing_action_ledger) that broke
-- production on 2026-05-21, this migration extends the same explicit-grant
-- contract to EVERY table in the v2 schemas — including the foundational
-- tables that previously relied only on the schema-wide GRANT in
-- 08_rls_policies.sql:4 and the post-52 tables that previously relied on
-- ALTER DEFAULT PRIVILEGES in 52_default_privileges_hardening.sql.
--
-- Rationale: schema-wide and default-privilege GRANTs are correct today but
-- have well-known failure modes:
--   (a) GRANT ALL ON ALL TABLES IN SCHEMA … only covers tables existing at
--       statement time (this is what caused the May 21 bug).
--   (b) ALTER DEFAULT PRIVILEGES only applies to future tables created by the
--       same role that issued the ALTER, and can be silently shadowed by a
--       later ALTER on the same schema.
--   (c) Both can be silently revoked by a Supabase platform update or a hand
--       SQL session that issues schema-wide REVOKE.
-- Per-table GRANTs are immune to (a)-(c) and are statically auditable from
-- the SQL files. After this migration, every v2 table has an explicit grant
-- recorded in a versioned migration, and tests/unit/supabase_v2/
-- test_schema_files.py enforces this invariant on every PR.
--
-- Forward-only, additive, idempotent. Re-issuing GRANT ALL is a no-op. No
-- REVOKE, no DROP, no DDL changes. Live tables only — the two dropped
-- billing tables (pricing_entitlement_consumption, pricing_plan_entitlements
-- per 44_functional_gates.sql:29-30) are intentionally excluded.

BEGIN;

-- ───────────────────────────────────────────────────────────────────────────
-- core (10 tables)
-- ───────────────────────────────────────────────────────────────────────────
GRANT ALL ON core._migrations_applied      TO service_role;
GRANT ALL ON core.profiles                 TO service_role;
GRANT ALL ON core.workspaces               TO service_role;
GRANT ALL ON core.workspace_members        TO service_role;
GRANT ALL ON core.usage_events             TO service_role;
GRANT ALL ON core.usage_aggregates         TO service_role;
GRANT ALL ON core.quotas                   TO service_role;
GRANT ALL ON core.soft_delete_queue        TO service_role;
GRANT ALL ON core.operations               TO service_role;
GRANT ALL ON core.zettel_enrichment_jobs   TO service_role;

-- ───────────────────────────────────────────────────────────────────────────
-- content (5 tables)
-- ───────────────────────────────────────────────────────────────────────────
GRANT ALL ON content.embedding_model_versions    TO service_role;
GRANT ALL ON content.canonical_zettels           TO service_role;
GRANT ALL ON content.canonical_chunks            TO service_role;
GRANT ALL ON content.workspace_zettels           TO service_role;
GRANT ALL ON content.workspace_chunk_membership  TO service_role;

-- ───────────────────────────────────────────────────────────────────────────
-- kg (5 tables)
-- ───────────────────────────────────────────────────────────────────────────
GRANT ALL ON kg.kg_nodes              TO service_role;
GRANT ALL ON kg.kg_edges              TO service_role;
GRANT ALL ON kg.chunk_node_mentions   TO service_role;
GRANT ALL ON kg.kg_node_aliases       TO service_role;
GRANT ALL ON kg.mv_refresh_log        TO service_role;

-- ───────────────────────────────────────────────────────────────────────────
-- rag (11 tables)
-- ───────────────────────────────────────────────────────────────────────────
GRANT ALL ON rag.kastens                            TO service_role;
GRANT ALL ON rag.kasten_members                     TO service_role;
GRANT ALL ON rag.kasten_zettels                     TO service_role;
GRANT ALL ON rag.chat_sessions                      TO service_role;
GRANT ALL ON rag.chat_messages                      TO service_role;
GRANT ALL ON rag.retrieval_signal_weights           TO service_role;
GRANT ALL ON rag.retrieval_scorer_registry          TO service_role;
GRANT ALL ON rag.retrieval_scorer_version           TO service_role;
GRANT ALL ON rag.retrieval_pipeline_config          TO service_role;
GRANT ALL ON rag.retrieval_pipeline_config_history  TO service_role;
GRANT ALL ON rag.retrieval_feedback_events          TO service_role;

-- ───────────────────────────────────────────────────────────────────────────
-- pipelines (4 tables)
-- ───────────────────────────────────────────────────────────────────────────
GRANT ALL ON pipelines.pipeline_runs           TO service_role;
GRANT ALL ON pipelines.pipeline_run_items      TO service_role;
GRANT ALL ON pipelines.nexus_provider_tokens   TO service_role;
GRANT ALL ON pipelines.extraction_blocklist    TO service_role;

-- ───────────────────────────────────────────────────────────────────────────
-- billing (11 tables — 2 dropped in #44 NOT listed)
-- ───────────────────────────────────────────────────────────────────────────
GRANT ALL ON billing.pricing_billing_profiles   TO service_role;
GRANT ALL ON billing.pricing_orders             TO service_role;
GRANT ALL ON billing.pricing_subscriptions      TO service_role;
GRANT ALL ON billing.pricing_balances           TO service_role;
GRANT ALL ON billing.pricing_payment_events     TO service_role;
GRANT ALL ON billing.pricing_plan_cache         TO service_role;
GRANT ALL ON billing.pricing_refunds            TO service_role;
GRANT ALL ON billing.pricing_disputes           TO service_role;
GRANT ALL ON billing.pricing_webhook_events     TO service_role;
GRANT ALL ON billing.pricing_usage_counters     TO service_role;
GRANT ALL ON billing.pricing_action_ledger      TO service_role;

-- ───────────────────────────────────────────────────────────────────────────
-- Defense-in-depth: dynamic catch-all for any table that exists in a v2
-- schema but is NOT listed above (future migrations, partman partitions,
-- ad-hoc tables created outside this file). Belt-and-suspenders only — the
-- regression test in tests/unit/supabase_v2/test_schema_files.py requires
-- every CREATE TABLE in _v2/*.sql to have a NAMED grant above this block.
-- ───────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT format('%I.%I', schemaname, tablename) AS qtn
          FROM pg_tables
         WHERE schemaname IN ('core', 'content', 'kg', 'rag', 'pipelines', 'billing')
           AND NOT has_table_privilege('service_role', format('%I.%I', schemaname, tablename), 'SELECT')
    LOOP
        EXECUTE format('GRANT ALL ON %s TO service_role', r.qtn);
        RAISE NOTICE '64_grant_all_v2_tables: backfilled GRANT ALL on % (was missing)', r.qtn;
    END LOOP;
END
$$;

-- ───────────────────────────────────────────────────────────────────────────
-- Re-issue ALTER DEFAULT PRIVILEGES (mirror of 52_default_privileges_hardening
-- — explicit re-state in case any role/owner changes have silently shadowed
-- 52's defaults). Forward-only: applies to tables created AFTER this point.
-- ───────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    sch text;
BEGIN
    FOREACH sch IN ARRAY ARRAY['core', 'content', 'kg', 'rag', 'pipelines', 'billing']
    LOOP
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON TABLES TO service_role',
            sch
        );
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON SEQUENCES TO service_role',
            sch
        );
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT EXECUTE ON ROUTINES TO service_role',
            sch
        );
    END LOOP;
END
$$;

-- ───────────────────────────────────────────────────────────────────────────
-- Self-verification: every v2 table MUST have service_role SELECT after this
-- migration. Fails the apply loudly if any table is still missing privileges
-- — prevents the silent regression that caused the May 21 incident.
-- ───────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    missing text[];
BEGIN
    SELECT array_agg(format('%I.%I', schemaname, tablename))
      INTO missing
      FROM pg_tables
     WHERE schemaname IN ('core', 'content', 'kg', 'rag', 'pipelines', 'billing')
       AND NOT has_table_privilege('service_role', format('%I.%I', schemaname, tablename), 'SELECT');
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION
            '64_grant_all_v2_tables: service_role missing SELECT after migration on: %',
            missing;
    END IF;
END
$$;

COMMIT;

NOTIFY pgrst, 'reload schema';
