-- supabase/website/_v2/45_rag_subgraph_for_pagerank.sql
--
-- P1-1: v2 port of the legacy `public.rag_subgraph_for_pagerank` RPC
-- (supabase/website/rag_chatbot/005_rag_rpcs.sql:287). The v1 function read
-- the induced subgraph from `public.kg_links` keyed by text node_id, scoped by
-- `p_user_id`. Both the v1 table and RPC were dropped in the DB v2 purge
-- (Phase 6/7.2; see _v2/28_drop_legacy_rpcs.sql), so the unqualified call in
-- website/features/rag_pipeline/retrieval/graph_score.py threw on every
-- request and the broad except silently degraded graph centrality to 0.0.
--
-- v2 mapping (verified against the v2 schema, not the legacy one):
--   * Identifier space: under v2 `RetrievalCandidate.node_id` is
--     `str(canonical_chunk_id)` (website/.../retrieval/hybrid.py:602,674),
--     NOT a kg bigint node id. The pagerank graph is therefore a
--     chunk-to-chunk graph, not the kg.kg_edges node graph.
--   * Edge surface: `rag.retrieval_signal_weights`
--     (_v2/04_rag_schema.sql:85) — the v2 chunk-to-chunk weighted-edge table
--     (source_canonical_chunk_id, target_canonical_chunk_id, weight,
--     query_class), workspace-scoped. This is the v2 equivalent of the v1
--     `kg_links` adjacency the legacy RPC read.
--   * Scoping convention: matches `rag.search_signal_weights`
--     (_v2/13_v2_kasten_rpcs.sql:33) exactly — `p_workspace_id uuid` +
--     `p_chunk_ids uuid[]`. The rag pipeline uniformly treats the
--     pipeline-level user_id as the workspace UUID; the JWT workspace_ids
--     gate enforces RLS. We deliberately drop the legacy `p_user_id` /
--     text[] signature in favour of the workspace/chunk v2 convention.
--
-- Semantics preserved from v1: return only the induced subgraph among the
-- candidate set (BOTH endpoints in p_chunk_ids), with a weight per edge.
-- v1 had no query_class dimension on kg_links; the v2 signal table does, so
-- we SUM weight across query_classes per (source, target) to collapse back to
-- the single-edge-weight shape the NetworkX scorer expects. COALESCE keeps
-- the v1 "default weight when null" behaviour (v1 used COALESCE(weight, 5)).

CREATE OR REPLACE FUNCTION rag.subgraph_for_pagerank(
    p_workspace_id  uuid,
    p_chunk_ids     uuid[]
) RETURNS TABLE (
    source_node_id  text,
    target_node_id  text,
    weight          double precision
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT (p_workspace_id = ANY (core.jwt_workspace_ids())
            OR current_setting('request.jwt.claims', true)::jsonb ->> 'role' = 'service_role') THEN
        RAISE EXCEPTION 'unauthorized' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
        SELECT rsw.source_canonical_chunk_id::text AS source_node_id,
               rsw.target_canonical_chunk_id::text AS target_node_id,
               SUM(COALESCE(rsw.weight, 5.0))::double precision AS weight
          FROM rag.retrieval_signal_weights rsw
         WHERE rsw.workspace_id = p_workspace_id
           AND rsw.source_canonical_chunk_id = ANY (p_chunk_ids)
           AND rsw.target_canonical_chunk_id = ANY (p_chunk_ids)
         GROUP BY rsw.source_canonical_chunk_id, rsw.target_canonical_chunk_id;
END $$;

GRANT EXECUTE ON FUNCTION rag.subgraph_for_pagerank(uuid, uuid[])
    TO authenticated, service_role;

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
