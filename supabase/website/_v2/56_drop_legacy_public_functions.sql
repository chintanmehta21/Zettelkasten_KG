-- Phase 8.5 D: complete the v1 purge by dropping 27 legacy public.* functions
-- that survived Phase 8's table drop (2026-05-11). Most reference dropped v1
-- tables (public.kg_*/rag_*/nexus_*) and have been silently dead since then.
-- The accompanying anchor_seed_bandit.py + tests changes remove the only live
-- application caller path. expected_schema.json updated in lockstep so the
-- schema-drift gate (Phase 1C.5 protected knob) passes.
--
-- Audit (2026-05-20):
--   * EXECUTE already REVOKE'd from anon/authenticated/PUBLIC (54/55_*.sql),
--     so no PostgREST-callable surface change here.
--   * No trigger in pg_trigger references any of these fns (verified via
--     `SELECT * FROM pg_trigger WHERE tgfoid::regprocedure::text LIKE 'public.%'`
--     pre-deploy).
--   * `core.handle_new_auth_user` is the active auth.users trigger fn
--     (_v2/01_core_schema.sql:243-245); public.handle_new_user is dead.
--   * `public.rls_auto_enable` is KEPT — it backs the active event_trigger
--     `ensure_rls` (DDL command end). NOT in this DROP list.
--   * `public.set_limit/show_limit/...`, `public.array_to_vector/...`,
--     `public.hamming_distance/jaccard_distance/l2_norm`, etc. are pg_trgm
--     and pgvector extension functions. NOT in this DROP list.
--
-- Order: alphabetical, DROP IF EXISTS. CASCADE is intentionally NOT used —
-- if anything still depends on one of these, the migration should fail loudly
-- (not silently take dependents down).

DROP FUNCTION IF EXISTS public.chat_session_stats_update();
DROP FUNCTION IF EXISTS public.execute_kg_query(query_text text, p_user_id uuid);
DROP FUNCTION IF EXISTS public.explain_kg_query(query_text text, p_user_id uuid);
DROP FUNCTION IF EXISTS public.find_neighbors(p_user_id uuid, p_node_id text, p_depth integer);
DROP FUNCTION IF EXISTS public.get_kg_graph(p_user_id uuid, p_limit integer, p_offset integer);
DROP FUNCTION IF EXISTS public.get_kg_stats(p_user_id uuid);
DROP FUNCTION IF EXISTS public.handle_new_user();
DROP FUNCTION IF EXISTS public.hybrid_kg_search(query_text text, query_embedding vector, p_user_id uuid, p_limit integer, semantic_weight double precision, fulltext_weight double precision, graph_weight double precision, p_k integer, p_seed_node_id text);
DROP FUNCTION IF EXISTS public.immutable_array_to_text(text[]);
DROP FUNCTION IF EXISTS public.isolated_nodes(p_user_id uuid);
DROP FUNCTION IF EXISTS public.kg_expand_subgraph(p_user_id uuid, p_node_ids text[], p_depth integer);
DROP FUNCTION IF EXISTS public.kg_node_chunks_fts_update();
DROP FUNCTION IF EXISTS public.kg_nodes_fts_update();
DROP FUNCTION IF EXISTS public.kg_refresh_usage_edges_agg();
DROP FUNCTION IF EXISTS public.nexus_housekeeping(p_oauth_retention interval, p_run_retention interval);
DROP FUNCTION IF EXISTS public.rag_bandit_read_arms(p_user_id uuid, p_kasten_id uuid, p_bucket text);
DROP FUNCTION IF EXISTS public.rag_bandit_record_outcome(p_user_id uuid, p_kasten_id uuid, p_arm numeric, p_bucket text, p_reward integer);
DROP FUNCTION IF EXISTS public.rag_bulk_add_to_sandbox(p_user_id uuid, p_sandbox_id uuid, p_tags text[], p_tag_mode text, p_source_types text[], p_node_ids text[], p_added_via text);
DROP FUNCTION IF EXISTS public.rag_kasten_node_frequencies(p_kasten_id uuid);
DROP FUNCTION IF EXISTS public.rag_kasten_record_node_hit(p_kasten_id uuid, p_node_id text);
DROP FUNCTION IF EXISTS public.rag_replace_node_chunks(p_user_id uuid, p_node_id text);
DROP FUNCTION IF EXISTS public.rag_subgraph_for_pagerank(p_user_id uuid, p_node_ids text[]);
DROP FUNCTION IF EXISTS public.shortest_path(p_user_id uuid, p_source_id text, p_target_id text, p_max_depth integer);
DROP FUNCTION IF EXISTS public.similar_nodes(p_user_id uuid, p_node_id text, p_limit integer);
DROP FUNCTION IF EXISTS public.top_connected_nodes(p_user_id uuid, p_limit integer);
DROP FUNCTION IF EXISTS public.top_tags(p_user_id uuid, p_limit integer);
DROP FUNCTION IF EXISTS public.update_updated_at_column();

NOTIFY pgrst, 'reload schema';
