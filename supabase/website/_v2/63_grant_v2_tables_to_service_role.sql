-- 63_grant_v2_tables_to_service_role.sql — backfill missing service_role table grants.
--
-- ROOT CAUSE (2026-05-21 production incident).
--   08_rls_policies.sql:4 issued
--       GRANT ALL ON ALL TABLES IN SCHEMA core, content, kg, rag, pipelines, billing
--           TO service_role;
--   which only covers tables EXISTING at that point (migrations 00-08).
--   52_default_privileges_hardening.sql sets ALTER DEFAULT PRIVILEGES for
--   FUTURE tables (post-52 only). Tables created BETWEEN (09-51) fall into a
--   gap: 08's do-block (lines 268-291) grants them service_role-only RLS
--   POLICIES, but no explicit table-level GRANT. PostgREST then returns
--   42501 "permission denied" for any direct table SELECT/INSERT/UPDATE/DELETE
--   from the supabase-py REST client, even though SECURITY DEFINER RPCs
--   continue to work.
--
--   Production symptom on 2026-05-21: operations_repo.get_operation() (which
--   does a direct PostgREST SELECT on core.operations) failed 42501 on every
--   poll. The /api/operations/{id} endpoint caught the exception, returned
--   202 + Retry-After, and the Add Zettel UI polled the full 300 s budget
--   without ever seeing the terminal `succeeded` state. Persistence itself
--   worked because the orchestrator writes through content.* tables (covered
--   by 08's grant) and ops_finalize is SECURITY DEFINER (bypasses table
--   grants).
--
-- AUDIT (2026-05-21) of every CREATE TABLE in migrations 09-51:
--   Missing explicit grant (impacted, fixed below):
--     * core.operations                       (48_operations.sql:10)
--     * billing.pricing_usage_counters        (44_functional_gates.sql:33)
--     * billing.pricing_action_ledger         (44_functional_gates.sql:53)
--   Already explicit (NOT impacted):
--     * pipelines.nexus_provider_tokens       (16_nexus_tokens.sql:29)
--     * kg.kg_node_aliases                    (22_kg_aliases_table.sql:45-46)
--     * pipelines.extraction_blocklist        (32_extraction_blocklist.sql:25-26)
--     * rag.retrieval_feedback_events         (34_retrieval_feedback_events.sql:101-102)
--     * kg.mv_refresh_log                     (35_retrieval_signal_views.sql:83-84)
--
-- DEFENSE IN DEPTH: also re-issue the schema-wide GRANT ALL ON ALL TABLES /
-- SEQUENCES / ROUTINES block from 08_rls_policies.sql:4-6. ALTER DEFAULT
-- PRIVILEGES (migration 52) covers post-52 future tables but NOT tables
-- already created. Re-issuing GRANT ON ALL captures the entire 09-62 range
-- in one statement so any table missed by this audit, or any future-applied
-- migration whose author forgets the explicit grant, is auto-covered.
-- (test_v2_gap_zone_tables_have_explicit_service_role_grant still requires
-- explicit per-table GRANTs as the primary mechanism; the schema-wide GRANT
-- is a backstop, not the contract.)
--
-- Forward-only, additive: pure GRANT, no REVOKE / DROP / DDL. Idempotent --
-- re-running has no effect. No application impact other than unblocking
-- previously-failing 42501 paths.

BEGIN;

-- (1) Explicit per-table grants for the three gap-zone tables identified
--     by the 2026-05-21 audit.
GRANT SELECT, INSERT, UPDATE, DELETE ON core.operations                TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON billing.pricing_usage_counters TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON billing.pricing_action_ledger  TO service_role;

-- (2) Defense-in-depth: re-issue the schema-wide GRANT block from
--     08_rls_policies.sql so any 09-62 table missed here, plus any future
--     table whose migration forgets explicit grants, is auto-covered. The
--     08 block ran before these tables existed; ALTER DEFAULT PRIVILEGES
--     (52) only applies to post-52 future tables. This statement closes
--     both gaps in one shot.
GRANT ALL ON ALL TABLES    IN SCHEMA core, content, kg, rag, pipelines, billing TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA core, content, kg, rag, pipelines, billing TO service_role;
GRANT ALL ON ALL ROUTINES  IN SCHEMA core, content, kg, rag, pipelines, billing TO service_role;

-- (3) Self-verification: assert service_role can now SELECT on every table
--     we expected this migration to cover. Fails the migration loudly if
--     the GRANT didn't take, instead of silently leaving a 42501 in prod.
DO $$
DECLARE
    missing text[];
BEGIN
    SELECT array_agg(qualified)
      INTO missing
      FROM (
          VALUES
              ('core.operations'),
              ('billing.pricing_usage_counters'),
              ('billing.pricing_action_ledger')
      ) AS expected(qualified)
     WHERE NOT has_table_privilege('service_role', qualified, 'SELECT');
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION
            '63_grant_v2_tables: service_role still missing SELECT on: %',
            missing;
    END IF;
END
$$;

COMMIT;

NOTIFY pgrst, 'reload schema';
