-- Phase 8.5.D-3 (2026-05-20): fresh-build-safe re-assertion of the REVOKEs
-- shipped by 54_revoke_legacy_public_secdef_grants.sql (FROM anon,
-- authenticated) and 55_revoke_public_grant_on_secdef.sql (FROM PUBLIC) on
-- the 19 legacy public.* SECURITY DEFINER functions.
--
-- Why this exists:
--   PostgreSQL has NO native `REVOKE ... IF EXISTS` for functions. 54 + 55
--   emit raw REVOKE statements that fail with `42883 undefined_function`
--   when the target function does not exist. On the production droplet
--   those fns DO exist (the v1 carryover), so 54 + 55 applied cleanly and
--   are now checksum-locked in `core._migrations_applied`. On a fresh
--   Supabase CI build (Fresh-Supabase _v2 apply gate in migration-ci.yml)
--   the legacy fns are absent — every REVOKE line in 54 errors, the runner
--   aborts the whole-file transaction (apply_migrations.py wraps each file
--   in a single tx), and 55 + 56 never run. This blocks every PR.
--
-- Fix:
--   Idempotent DO-block. pg_proc EXISTS guard short-circuits each REVOKE on
--   a per-signature basis: if the function is absent we RAISE NOTICE and
--   skip; if present we REVOKE EXECUTE from both role-sets (anon +
--   authenticated AND PUBLIC) in one pass. Mirrors the FOREACH-over-ARRAY
--   pattern used by 52_default_privileges_hardening.sql.
--
-- Production semantics:
--   No-op re-assertion. On prod, fns still exist for `rls_auto_enable`
--   (kept — event_trigger backing); for the other 18, migration 56 drops
--   them so the EXISTS guard short-circuits after 56 runs. Re-REVOKEing an
--   already-revoked grant is a documented no-op in PG. Sub-second runtime.
--
-- CI semantics:
--   On fresh build, migration-ci.yml is updated in lockstep to also
--   --skip-files 54 + 55 (alongside the existing 15). 58 runs and finds
--   zero fns (or only `rls_auto_enable` if event_trigger backing was
--   pre-installed by Supabase stack init), logs the skipped names, exits
--   cleanly. Fresh-Supabase gate now passes.
--
-- Why a DO block, not EXCEPTION WHEN OTHERS:
--   The exception-swallowing pattern hides real errors (typos, permission
--   surprises) along with the expected "function not found". The pg_proc
--   EXISTS guard is surgical: only the missing-function case is short-
--   circuited; every other failure mode still aborts the migration.
--
-- 19 signatures verified identical between 54 and 55 (2026-05-20).

DO $$
DECLARE
    sig text;
    legacy_signatures CONSTANT text[] := ARRAY[
        'public.execute_kg_query(text, uuid)',
        'public.explain_kg_query(text, uuid)',
        'public.find_neighbors(uuid, text, integer)',
        'public.get_kg_graph(uuid, integer, integer)',
        'public.get_kg_stats(uuid)',
        'public.handle_new_user()',
        'public.hybrid_kg_search(text, vector, uuid, integer, double precision, double precision, double precision, integer, text)',
        'public.isolated_nodes(uuid)',
        'public.kg_expand_subgraph(uuid, text[], integer)',
        'public.kg_refresh_usage_edges_agg()',
        'public.nexus_housekeeping(interval, interval)',
        'public.rag_bulk_add_to_sandbox(uuid, uuid, text[], text, text[], text[], text)',
        'public.rag_replace_node_chunks(uuid, text)',
        'public.rag_subgraph_for_pagerank(uuid, text[])',
        'public.rls_auto_enable()',
        'public.shortest_path(uuid, text, text, integer)',
        'public.similar_nodes(uuid, text, integer)',
        'public.top_connected_nodes(uuid, integer)',
        'public.top_tags(uuid, integer)'
    ];
BEGIN
    FOREACH sig IN ARRAY legacy_signatures
    LOOP
        -- regprocedure cast normalizes the signature against pg_proc and
        -- raises 42883 if absent. Wrap the lookup in a sub-block so the
        -- missing-fn case is locally caught WITHOUT masking errors from
        -- the REVOKE statements themselves.
        DECLARE
            fn_oid oid;
        BEGIN
            fn_oid := sig::regprocedure::oid;
        EXCEPTION
            WHEN undefined_function THEN
                RAISE NOTICE 'migration 58: skipping absent legacy fn %', sig;
                CONTINUE;
        END;

        EXECUTE format(
            'REVOKE EXECUTE ON FUNCTION %s FROM anon, authenticated',
            sig
        );
        EXECUTE format(
            'REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC',
            sig
        );
    END LOOP;
END
$$;

NOTIFY pgrst, 'reload schema';
