-- 2026-05-24 — Workspace-wide hybrid search (dense + FTS + RRF).
--
-- Counterpart to ``content.hybrid_search_chunks_kasten`` (migration 26).
-- The kasten RPC is the only workspace-chunk retrieval surface today, so
-- the orchestrator's ``hybrid.py::_search`` short-circuits to ``return []``
-- when ``sandbox_id is None`` (no kasten selected on /home/rag → "Ask all
-- your zettels"). That code dead-end made the "All zettels" chat mode
-- always answer "I can't find that in your Zettels" regardless of how
-- many Zettels the user had — confirmed live during Naruto E2E
-- 2026-05-23 (session b0027aaf-5fe1-4389-8f47-cd8e68a7e0d8 returned
-- ctx_chars=57 used=0 — the assembler's literal empty-context string).
--
-- This RPC closes the gap. Mirrors the kasten RPC's contract (column
-- shape, RRF k=60, dense+FTS+fused CTEs, halfvec(768)) so the Python
-- adapter at ``website/features/rag_pipeline/retrieval/hybrid.py`` can
-- swap the RPC name based on scope without changing row parsing.
--
-- Research-backed deviations from a literal kasten→workspace copy
-- (sources: pgvector 0.7+/0.8 docs, Supabase HNSW guide, Crunchy Data,
-- ParadeDB Hybrid Search manual, AWS Aurora pgvector 0.8 writeup,
-- Cormack 2009 RRF; see PR #73 for the full transcript):
--
--   1. ``scoped_chunks`` is MATERIALIZED. Workspace scope can hit
--      thousands of chunks where kasten scope hits 50-300; without
--      MATERIALIZED the planner inlines the CTE and the global HNSW
--      sees the WHOLE corpus rather than the workspace subset — pgvector
--      docs flag this exact anti-pattern.
--   2. Transaction-local ``set_config(..., true)`` raises ``hnsw.ef_search``
--      + enables ``hnsw.iterative_scan=relaxed_order`` so the global HNSW
--      returns enough candidates when filtered down to one workspace.
--      MUST be ``true`` (transaction-scoped); ``false`` would poison the
--      Supabase pgbouncer pool. ``relaxed_order`` is safe — we re-rank
--      via RRF anyway.
--   3. Explicit auth gate at function entry: ``p_workspace_id`` MUST be
--      in the caller's JWT ``workspace_ids`` (or caller is service_role).
--      Same shape as ``content.list_workspace_chunks`` (02_content_schema).
--   4. ``p_candidate_cap`` (default 5000) LIMITs ``scoped_chunks`` so a
--      workspace that grows to 100k+ chunks never burns unbounded work
--      per query. RRF with top-k=20 rarely needs more than 5000.
--   5. ``workspace_chunk_membership.workspace_id`` is the predicate (one
--      hop fewer than the kasten path, which detoured via rag.kastens).
--      The existing index ``idx_workspace_chunks_workspace`` covers it.
--   6. RRF ``k=60`` unchanged. Per Cormack 2009 + BigDataBoutique 2023
--      empirical sweep, k=60 is collection-size-invariant.

CREATE OR REPLACE FUNCTION content.hybrid_search_chunks_workspace(
    p_workspace_id        uuid,
    p_query_text          text,
    p_query_embedding     halfvec(768),
    p_match_count         int DEFAULT 20,
    p_rrf_k               int DEFAULT 60,
    p_full_text_weight    double precision DEFAULT 1.0,
    p_semantic_weight     double precision DEFAULT 1.0,
    p_candidate_cap       int DEFAULT 5000
) RETURNS TABLE (
    canonical_chunk_id   uuid,
    canonical_zettel_id  uuid,
    chunk_idx            int,
    content              text,
    rrf_score            double precision,
    fts_rank             int,
    semantic_rank        int,
    raw_dense_score      double precision,
    raw_fts_score        double precision,
    title                text,
    source_type          text,
    publication_date     date,
    user_tags            text[],
    workspace_zettel_id  uuid
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
BEGIN
    -- Explicit auth gate (mirror of content.list_workspace_chunks).
    IF NOT (core.is_service_role()
            OR p_workspace_id = ANY (core.jwt_workspace_ids())) THEN
        RAISE EXCEPTION 'unauthorized' USING ERRCODE = '42501';
    END IF;

    -- Transaction-local GUCs for filtered HNSW. PgBouncer-safe.
    PERFORM set_config('hnsw.iterative_scan', 'relaxed_order', true);
    PERFORM set_config('hnsw.ef_search',      '120',           true);
    PERFORM set_config('hnsw.max_scan_tuples','40000',         true);

    RETURN QUERY
        WITH scoped_chunks AS MATERIALIZED (
            -- Pre-filter to workspace chunks; HNSW + GIN see only this
            -- subset. LIMIT bounds work on huge workspaces.
            SELECT cc.id              AS sc_chunk_id,
                   cc.canonical_zettel_id AS sc_zettel_id,
                   cc.chunk_idx       AS sc_chunk_idx,
                   cc.content         AS sc_content,
                   cc.embedding       AS sc_embedding,
                   cc.fts             AS sc_fts,
                   wz.id              AS sc_wz_id,
                   wz.user_tags       AS sc_user_tags,
                   cz.title           AS sc_title,
                   cz.source_type     AS sc_source_type,
                   cz.publication_date AS sc_pub_date
              FROM content.workspace_chunk_membership wcm
              JOIN content.workspace_zettels wz ON wz.id = wcm.workspace_zettel_id
              JOIN content.canonical_chunks cc ON cc.id = wcm.canonical_chunk_id
              JOIN content.canonical_zettels cz ON cz.id = cc.canonical_zettel_id
             WHERE wcm.workspace_id = p_workspace_id
               AND wz.deleted_at IS NULL
             LIMIT p_candidate_cap
        ),
        ft AS (
            SELECT sc_chunk_id AS chunk_id,
                   row_number() OVER (
                       ORDER BY ts_rank_cd(sc_fts, websearch_to_tsquery('english', p_query_text)) DESC
                   ) AS rank,
                   ts_rank_cd(sc_fts, websearch_to_tsquery('english', p_query_text))::double precision AS raw_fts
              FROM scoped_chunks
             WHERE sc_fts @@ websearch_to_tsquery('english', p_query_text)
             ORDER BY rank
             LIMIT p_match_count * 2
        ),
        sem AS (
            SELECT sc_chunk_id AS chunk_id,
                   row_number() OVER (
                       ORDER BY sc_embedding <=> p_query_embedding ASC
                   ) AS rank,
                   (1 - (sc_embedding <=> p_query_embedding))::double precision AS raw_cosine
              FROM scoped_chunks
             WHERE sc_embedding IS NOT NULL
             ORDER BY sc_embedding <=> p_query_embedding ASC
             LIMIT p_match_count * 2
        ),
        fused AS (
            SELECT COALESCE(ft.chunk_id, sem.chunk_id) AS chunk_id,
                   COALESCE(1.0 / (p_rrf_k + ft.rank), 0.0) * p_full_text_weight
                 + COALESCE(1.0 / (p_rrf_k + sem.rank), 0.0) * p_semantic_weight AS f_rrf_score,
                   ft.rank::int AS f_fts_rank,
                   sem.rank::int AS f_sem_rank,
                   sem.raw_cosine AS f_raw_dense,
                   ft.raw_fts AS f_raw_fts
              FROM ft
              FULL OUTER JOIN sem ON ft.chunk_id = sem.chunk_id
        )
        SELECT sc.sc_chunk_id::uuid,
               sc.sc_zettel_id::uuid,
               sc.sc_chunk_idx,
               sc.sc_content,
               fused.f_rrf_score,
               fused.f_fts_rank,
               fused.f_sem_rank,
               fused.f_raw_dense,
               fused.f_raw_fts,
               sc.sc_title,
               sc.sc_source_type,
               sc.sc_pub_date,
               sc.sc_user_tags,
               sc.sc_wz_id::uuid
          FROM fused
          JOIN scoped_chunks sc ON sc.sc_chunk_id = fused.chunk_id
         ORDER BY fused.f_rrf_score DESC
         LIMIT p_match_count;
END $$;

GRANT EXECUTE ON FUNCTION content.hybrid_search_chunks_workspace(
    uuid, text, halfvec, int, int, double precision, double precision, int
) TO authenticated, service_role;

NOTIFY pgrst, 'reload schema';
