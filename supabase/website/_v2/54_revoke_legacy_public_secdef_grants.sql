-- Phase 8.5: clear advisor lints 0028 + 0029 (anon/authenticated can execute
-- SECURITY DEFINER fn) on every legacy public.* SECURITY DEFINER function.
--
-- REVOKE EXECUTE FROM anon, authenticated. This is reversible and does NOT
-- drop any function. 18 of the 19 functions are dead code (reference v1
-- public.kg_*/rag_*/nexus_* tables dropped 2026-05-11) and will be dropped in
-- a follow-up Phase D migration (55_drop_legacy_public_functions.sql) along
-- with the expected_schema.json manifest update and the anchor_seed_bandit.py
-- caller removal.
--
-- The 19th, `public.rls_auto_enable`, is the function backing the active
-- event_trigger `ensure_rls` (DDL command end) and MUST be kept. It is only
-- meant to fire from the event_trigger, never as a PostgREST RPC. REVOKE
-- closes the unintended RPC exposure without touching the trigger wiring.
--
-- Audit evidence (2026-05-20):
--   * SELECT evtname, evtenabled FROM pg_event_trigger WHERE evtfoid =
--     'public.rls_auto_enable'::regproc → ensure_rls / O (enabled).
--   * to_regclass('public.kg_bandit_posteriors') = NULL — bandit fns broken.
--   * No trigger in pg_trigger references any public.* fn (tgisinternal=f).
--
-- service_role retains EXECUTE on every function below (it's the only role
-- expected to invoke any of these, and that's how the event_trigger fn must
-- keep working since event_triggers fire as the table-modifying role +
-- DEFINER context — postgres + service_role both have EXECUTE via PUBLIC
-- inheritance prior to this REVOKE).

REVOKE EXECUTE ON FUNCTION public.execute_kg_query(query_text text, p_user_id uuid)                                  FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.explain_kg_query(query_text text, p_user_id uuid)                                  FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.find_neighbors(p_user_id uuid, p_node_id text, p_depth integer)                    FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.get_kg_graph(p_user_id uuid, p_limit integer, p_offset integer)                    FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.get_kg_stats(p_user_id uuid)                                                       FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.handle_new_user()                                                                  FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.hybrid_kg_search(query_text text, query_embedding vector, p_user_id uuid, p_limit integer, semantic_weight double precision, fulltext_weight double precision, graph_weight double precision, p_k integer, p_seed_node_id text) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.isolated_nodes(p_user_id uuid)                                                     FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.kg_expand_subgraph(p_user_id uuid, p_node_ids text[], p_depth integer)             FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.kg_refresh_usage_edges_agg()                                                       FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.nexus_housekeeping(p_oauth_retention interval, p_run_retention interval)           FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.rag_bulk_add_to_sandbox(p_user_id uuid, p_sandbox_id uuid, p_tags text[], p_tag_mode text, p_source_types text[], p_node_ids text[], p_added_via text) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.rag_replace_node_chunks(p_user_id uuid, p_node_id text)                            FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.rag_subgraph_for_pagerank(p_user_id uuid, p_node_ids text[])                       FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable()                                                                  FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.shortest_path(p_user_id uuid, p_source_id text, p_target_id text, p_max_depth integer) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.similar_nodes(p_user_id uuid, p_node_id text, p_limit integer)                     FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.top_connected_nodes(p_user_id uuid, p_limit integer)                               FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.top_tags(p_user_id uuid, p_limit integer)                                          FROM anon, authenticated;

NOTIFY pgrst, 'reload schema';
