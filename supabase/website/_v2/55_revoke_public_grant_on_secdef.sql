-- Phase 8.5 follow-up: 54_*.sql REVOKE'd EXECUTE from anon + authenticated
-- on 19 public.* SECURITY DEFINER fns. Verification showed 4 of them still
-- callable by anon/authenticated because those roles inherit EXECUTE via the
-- implicit `GRANT EXECUTE TO PUBLIC` that every CREATE FUNCTION assigns by
-- default. REVOKE FROM <role> is a no-op when the role only has the
-- privilege via PUBLIC, so we must REVOKE FROM PUBLIC explicitly.
--
-- Effect: these 4 fns become invocable only by postgres (the table owner —
-- ownership rights are not removable by REVOKE) and service_role (retained
-- via the explicit grant in 08_rls_policies.sql:268-291 service_role_all
-- pattern + any direct grants).
--
-- rls_auto_enable() is the active event_trigger backing fn (ensure_rls,
-- ddl_command_end, enabled). REVOKE FROM PUBLIC does not break the
-- event_trigger because: (a) all DDL on this database is performed by
-- postgres (via apply_migrations.py / partman cron / dashboard owner role),
-- which retains EXECUTE as the function owner; (b) anon/authenticated cannot
-- perform DDL on any schema regardless.
--
-- Belt-and-braces: apply REVOKE FROM PUBLIC to ALL 19 SECDEF fns, not just
-- the 4 stragglers. Idempotent and ensures no future regression if a
-- function is recreated with default PUBLIC grant.

REVOKE EXECUTE ON FUNCTION public.execute_kg_query(query_text text, p_user_id uuid)                                  FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.explain_kg_query(query_text text, p_user_id uuid)                                  FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.find_neighbors(p_user_id uuid, p_node_id text, p_depth integer)                    FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_kg_graph(p_user_id uuid, p_limit integer, p_offset integer)                    FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_kg_stats(p_user_id uuid)                                                       FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.handle_new_user()                                                                  FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hybrid_kg_search(query_text text, query_embedding vector, p_user_id uuid, p_limit integer, semantic_weight double precision, fulltext_weight double precision, graph_weight double precision, p_k integer, p_seed_node_id text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.isolated_nodes(p_user_id uuid)                                                     FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.kg_expand_subgraph(p_user_id uuid, p_node_ids text[], p_depth integer)             FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.kg_refresh_usage_edges_agg()                                                       FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.nexus_housekeeping(p_oauth_retention interval, p_run_retention interval)           FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.rag_bulk_add_to_sandbox(p_user_id uuid, p_sandbox_id uuid, p_tags text[], p_tag_mode text, p_source_types text[], p_node_ids text[], p_added_via text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.rag_replace_node_chunks(p_user_id uuid, p_node_id text)                            FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.rag_subgraph_for_pagerank(p_user_id uuid, p_node_ids text[])                       FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable()                                                                  FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.shortest_path(p_user_id uuid, p_source_id text, p_target_id text, p_max_depth integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.similar_nodes(p_user_id uuid, p_node_id text, p_limit integer)                     FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.top_connected_nodes(p_user_id uuid, p_limit integer)                               FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.top_tags(p_user_id uuid, p_limit integer)                                          FROM PUBLIC;

NOTIFY pgrst, 'reload schema';
