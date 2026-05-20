-- Phase 8.5: clear advisor lint 0011 (function_search_path_mutable) on all
-- live v2 functions. Adds `SET search_path = pg_catalog, public` so search
-- path is not mutable at call time (defense against search-path hijack).
--
-- Why `pg_catalog, public` (and not `''`):
--   * pgvector and pg_trgm extensions are installed in `public` (lint 0014
--     defer-flagged separately) — operators like `<=>`, `%`, `<%` need
--     `public` in the resolution path.
--   * Empty search_path would break any reference to a `public.*` operator or
--     extension type from these functions and is only safe once extensions
--     are relocated to a dedicated `extensions` schema (out of scope here).
--   * Industry-standard fix per splinter 0011 docs + Supabase issue #28507.
--
-- All 16 functions below are LANGUAGE plpgsql (verified in source files):
-- so the "SET clause disables SQL function inlining" caveat in issue #33131
-- does not apply (plpgsql functions don't inline anyway).
--
-- Ref audit: every function listed is reached only through internal v2 paths
-- (triggers, billing module, sign-up flow) — service_role and postgres
-- ownership are unchanged. No app code change required.

-- content schema (4 triggers/helpers)
ALTER FUNCTION content.canonical_chunks_fts_update()                       SET search_path = pg_catalog, public;
ALTER FUNCTION content.trg_orphan_check_after_delete()                     SET search_path = pg_catalog, public;
ALTER FUNCTION content.trg_orphan_check_after_softdelete()                 SET search_path = pg_catalog, public;
ALTER FUNCTION content.enqueue_canonical_shred_if_orphan(p_canonical_zettel_id uuid) SET search_path = pg_catalog, public;

-- core schema (4 auth / workspace helpers)
ALTER FUNCTION core.handle_new_auth_user()                                 SET search_path = pg_catalog, public;
ALTER FUNCTION core.create_personal_workspace()                            SET search_path = pg_catalog, public;
ALTER FUNCTION core.sync_workspace_ids_to_jwt()                            SET search_path = pg_catalog, public;
ALTER FUNCTION core.enforce_allowlist()                                    SET search_path = pg_catalog, public;

-- billing schema (3 pricing fns)
ALTER FUNCTION billing.pricing_active_plan(p_profile_id uuid)              SET search_path = pg_catalog, public;
ALTER FUNCTION billing.pricing_add_pack_credits(p_profile_id uuid, p_meter text, p_quantity integer)    SET search_path = pg_catalog, public;
ALTER FUNCTION billing.pricing_deduct_pack_credits(p_profile_id uuid, p_meter text, p_quantity integer) SET search_path = pg_catalog, public;

-- rag schema (4 triggers/asserts)
ALTER FUNCTION rag.notify_pipeline_config_change()                         SET search_path = pg_catalog, public;
ALTER FUNCTION rag.assert_kasten_owner_can_grant()                         SET search_path = pg_catalog, public;
ALTER FUNCTION rag.fn_auto_kasten_owner_member()                           SET search_path = pg_catalog, public;
ALTER FUNCTION rag.assert_chat_message_workspace_match()                   SET search_path = pg_catalog, public;

-- pipelines schema (1 trigger helper)
ALTER FUNCTION pipelines.fn_set_updated_at()                               SET search_path = pg_catalog, public;
