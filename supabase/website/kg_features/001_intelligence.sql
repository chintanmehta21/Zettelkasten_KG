-- ============================================================================
-- Intelligence Layer Migration (001)
-- Adds: pgvector embeddings, full-text search, enriched links, graph RPCs
-- Depends on: kg_public/schema.sql (base tables must exist)
-- ============================================================================

-- ── 1. pgvector extension + embedding column ───────────────────────────────

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE kg_nodes
    ADD COLUMN IF NOT EXISTS embedding vector(768);

CREATE INDEX IF NOT EXISTS idx_kg_nodes_embedding
    ON kg_nodes USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

COMMENT ON COLUMN kg_nodes.embedding IS 'Semantic embedding vector (768-dim, e.g. text-embedding-004)';


-- ── 2. Enriched link columns ───────────────────────────────────────────────

ALTER TABLE kg_links
    ADD COLUMN IF NOT EXISTS weight      INTEGER DEFAULT 5
        CHECK (weight >= 1 AND weight <= 10),
    ADD COLUMN IF NOT EXISTS link_type   TEXT    DEFAULT 'tag'
        CHECK (link_type IN ('tag', 'semantic', 'entity')),
    ADD COLUMN IF NOT EXISTS description TEXT;

COMMENT ON COLUMN kg_links.weight      IS 'Edge weight 1-10 (10 = strongest relationship)';
COMMENT ON COLUMN kg_links.link_type   IS 'Edge type: tag (shared tag), semantic (embedding similarity), entity (shared named entity)';
COMMENT ON COLUMN kg_links.description IS 'Human-readable description of the relationship';


-- ── 3. Full-text search column + index ─────────────────────────────────────

ALTER TABLE kg_nodes
    ADD COLUMN IF NOT EXISTS fts tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(summary, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(array_to_string(tags, ' '), '')), 'C')
        ) STORED;

CREATE INDEX IF NOT EXISTS idx_kg_nodes_fts
    ON kg_nodes USING GIN (fts);

COMMENT ON COLUMN kg_nodes.fts IS 'Auto-generated tsvector for full-text search (name=A, summary=B, tags=C)';


-- ── 4. Updated kg_graph_view with enriched link fields ─────────────────────

CREATE OR REPLACE VIEW kg_graph_view AS
SELECT
    u.id AS user_id,
    jsonb_build_object(
        'nodes',
        COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'id',      n.id,
                    'name',    n.name,
                    'group',   n.source_type,
                    'summary', n.summary,
                    'tags',    n.tags,
                    'url',     n.url,
                    'date',    COALESCE(n.node_date::text, '')
                )
            )
            FROM kg_nodes n
            WHERE n.user_id = u.id),
            '[]'::jsonb
        ),
        'links',
        COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'source',      l.source_node_id,
                    'target',      l.target_node_id,
                    'relation',    l.relation,
                    'weight',      l.weight,
                    'link_type',   l.link_type,
                    'description', l.description
                )
            )
            FROM kg_links l
            WHERE l.user_id = u.id),
            '[]'::jsonb
        )
    ) AS graph_data
FROM kg_users u;

COMMENT ON VIEW kg_graph_view IS 'Per-user graph data as JSONB {nodes, links} for frontend consumption';


-- ── 5. RPC: match_kg_nodes (semantic search) ───────────────────────────────

CREATE OR REPLACE FUNCTION match_kg_nodes(
    query_embedding  vector(768),
    match_threshold  float    DEFAULT 0.7,
    match_count      int      DEFAULT 10,
    target_user_id   uuid     DEFAULT NULL
)
RETURNS TABLE (
    id          text,
    name        text,
    source_type text,
    summary     text,
    tags        text[],
    url         text,
    similarity  float
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        n.id,
        n.name,
        n.source_type,
        n.summary,
        n.tags,
        n.url,
        1 - (n.embedding <=> query_embedding) AS similarity
    FROM public.kg_nodes n
    WHERE n.embedding IS NOT NULL
      AND (target_user_id IS NULL OR n.user_id = target_user_id)
      AND 1 - (n.embedding <=> query_embedding) > match_threshold
    ORDER BY n.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

COMMENT ON FUNCTION match_kg_nodes IS 'Semantic search: find nodes closest to a query embedding via cosine similarity';


-- ── 6. RPC: find_neighbors (k-hop traversal) ──────────────────────────────

CREATE OR REPLACE FUNCTION find_neighbors(
    p_user_id  uuid,
    p_node_id  text,
    p_depth    int DEFAULT 1
)
RETURNS TABLE (
    node_id    text,
    name       text,
    source_type text,
    depth      int,
    path       text[]
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE neighbors AS (
        -- Base case: the starting node at depth 0
        SELECT
            n.id            AS node_id,
            n.name          AS name,
            n.source_type   AS source_type,
            0               AS depth,
            ARRAY[n.id]     AS path
        FROM public.kg_nodes n
        WHERE n.user_id = p_user_id
          AND n.id = p_node_id

        UNION ALL

        -- Recursive case: traverse edges in both directions
        SELECT
            n2.id           AS node_id,
            n2.name         AS name,
            n2.source_type  AS source_type,
            nb.depth + 1    AS depth,
            nb.path || n2.id AS path
        FROM neighbors nb
        JOIN public.kg_links l
            ON l.user_id = p_user_id
           AND (
                (l.source_node_id = nb.node_id AND l.target_node_id = n2.id)
             OR (l.target_node_id = nb.node_id AND l.source_node_id = n2.id)
           )
        JOIN public.kg_nodes n2
            ON n2.user_id = p_user_id
           AND n2.id = CASE
                WHEN l.source_node_id = nb.node_id THEN l.target_node_id
                ELSE l.source_node_id
           END
        WHERE nb.depth < p_depth
          AND NOT (n2.id = ANY(nb.path))  -- cycle prevention
    )
    SELECT DISTINCT ON (neighbors.node_id)
        neighbors.node_id,
        neighbors.name,
        neighbors.source_type,
        neighbors.depth,
        neighbors.path
    FROM neighbors
    WHERE neighbors.depth > 0
    ORDER BY neighbors.node_id, neighbors.depth;
END;
$$;

COMMENT ON FUNCTION find_neighbors IS 'K-hop graph traversal from a starting node with cycle prevention';


-- ── 7. RPC: shortest_path (BFS) ───────────────────────────────────────────

CREATE OR REPLACE FUNCTION shortest_path(
    p_user_id   uuid,
    p_source_id text,
    p_target_id text,
    p_max_depth int DEFAULT 5
)
RETURNS TABLE (
    path        text[],
    depth       int
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE bfs AS (
        -- Base case: start from source
        SELECT
            ARRAY[p_source_id]  AS path,
            p_source_id         AS current_node,
            0                   AS depth

        UNION ALL

        -- Recursive case: expand frontier
        SELECT
            b.path || CASE
                WHEN l.source_node_id = b.current_node THEN l.target_node_id
                ELSE l.source_node_id
            END                 AS path,
            CASE
                WHEN l.source_node_id = b.current_node THEN l.target_node_id
                ELSE l.source_node_id
            END                 AS current_node,
            b.depth + 1         AS depth
        FROM bfs b
        JOIN public.kg_links l
            ON l.user_id = p_user_id
           AND (
                l.source_node_id = b.current_node
             OR l.target_node_id = b.current_node
           )
        WHERE b.depth < p_max_depth
          AND NOT (
              CASE
                  WHEN l.source_node_id = b.current_node THEN l.target_node_id
                  ELSE l.source_node_id
              END = ANY(b.path)
          )  -- cycle prevention
    )
    SELECT bfs.path, bfs.depth
    FROM bfs
    WHERE bfs.current_node = p_target_id
    ORDER BY bfs.depth
    LIMIT 1;
END;
$$;

COMMENT ON FUNCTION shortest_path IS 'BFS shortest path between two nodes in a user graph';


-- ── 8. RPC: top_connected_nodes ────────────────────────────────────────────

CREATE OR REPLACE FUNCTION top_connected_nodes(
    p_user_id  uuid,
    p_limit    int DEFAULT 10
)
RETURNS TABLE (
    node_id     text,
    name        text,
    source_type text,
    degree      bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        n.id            AS node_id,
        n.name          AS name,
        n.source_type   AS source_type,
        COUNT(l.id)     AS degree
    FROM public.kg_nodes n
    LEFT JOIN public.kg_links l
        ON l.user_id = p_user_id
       AND (l.source_node_id = n.id OR l.target_node_id = n.id)
    WHERE n.user_id = p_user_id
    GROUP BY n.id, n.name, n.source_type
    ORDER BY degree DESC
    LIMIT p_limit;
END;
$$;

COMMENT ON FUNCTION top_connected_nodes IS 'Nodes with the highest edge count (degree centrality)';


-- ── 9. RPC: isolated_nodes ─────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION isolated_nodes(
    p_user_id  uuid
)
RETURNS TABLE (
    node_id     text,
    name        text,
    source_type text,
    url         text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        n.id            AS node_id,
        n.name          AS name,
        n.source_type   AS source_type,
        n.url           AS url
    FROM public.kg_nodes n
    LEFT JOIN public.kg_links l
        ON l.user_id = p_user_id
       AND (l.source_node_id = n.id OR l.target_node_id = n.id)
    WHERE n.user_id = p_user_id
      AND l.id IS NULL
    ORDER BY n.created_at DESC;
END;
$$;

COMMENT ON FUNCTION isolated_nodes IS 'Nodes with zero edges (orphans)';


-- ── 10. RPC: top_tags ──────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION top_tags(
    p_user_id  uuid,
    p_limit    int DEFAULT 20
)
RETURNS TABLE (
    tag        text,
    frequency  bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        unnested        AS tag,
        COUNT(*)        AS frequency
    FROM public.kg_nodes n,
         unnest(n.tags) AS unnested
    WHERE n.user_id = p_user_id
    GROUP BY unnested
    ORDER BY frequency DESC
    LIMIT p_limit;
END;
$$;

COMMENT ON FUNCTION top_tags IS 'Most frequently used tags across a user knowledge graph';


-- ── 11. RPC: similar_nodes (tag overlap) ───────────────────────────────────

CREATE OR REPLACE FUNCTION similar_nodes(
    p_user_id  uuid,
    p_node_id  text,
    p_limit    int DEFAULT 10
)
RETURNS TABLE (
    node_id       text,
    name          text,
    source_type   text,
    shared_tags   text[],
    overlap_count bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        n2.id                       AS node_id,
        n2.name                     AS name,
        n2.source_type              AS source_type,
        array_agg(t1.tag)           AS shared_tags,
        COUNT(*)                    AS overlap_count
    FROM public.kg_nodes n1,
         unnest(n1.tags) AS t1(tag)
    JOIN public.kg_nodes n2
        ON n2.user_id = p_user_id
       AND n2.id != p_node_id
    JOIN unnest(n2.tags) AS t2(tag)
        ON t1.tag = t2.tag
    WHERE n1.user_id = p_user_id
      AND n1.id = p_node_id
    GROUP BY n2.id, n2.name, n2.source_type
    ORDER BY overlap_count DESC
    LIMIT p_limit;
END;
$$;

COMMENT ON FUNCTION similar_nodes IS 'Find nodes with the most shared tags to a given node';


-- ── 12. RPC: execute_kg_query (safe NL-to-SQL) ────────────────────────────

CREATE OR REPLACE FUNCTION execute_kg_query(
    query_text  text,
    p_user_id   uuid
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
DECLARE
    trimmed_query text;
    result        jsonb;
BEGIN
    trimmed_query := btrim(query_text);

    -- SELECT-only allowlist
    IF NOT (upper(left(trimmed_query, 6)) = 'SELECT') THEN
        RAISE EXCEPTION 'Only SELECT queries are allowed';
    END IF;

    -- Reject semicolons (prevent statement chaining)
    IF position(';' in trimmed_query) > 0 THEN
        RAISE EXCEPTION 'Semicolons are not allowed in queries';
    END IF;

    -- Enforce user_id scoping: query must reference the user's ID
    IF NOT (trimmed_query ~* ('user_id\s*=\s*''' || p_user_id::text || '''')) THEN
        RAISE EXCEPTION 'Query must filter by user_id = ''%''', p_user_id;
    END IF;

    -- Execute with result truncation
    EXECUTE format(
        'SELECT jsonb_agg(row_to_json(t)) FROM (SELECT * FROM (%s) sub LIMIT 50) t',
        trimmed_query
    ) INTO result;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$;

COMMENT ON FUNCTION execute_kg_query IS 'Execute SELECT-only SQL with user_id enforcement and 50-row limit';


-- ── 13. RPC: hybrid_kg_search (RRF fusion) ─────────────────────────────────

CREATE OR REPLACE FUNCTION hybrid_kg_search(
    query_text       text,
    query_embedding  vector(768) DEFAULT NULL,
    p_user_id        uuid        DEFAULT NULL,
    p_limit          int         DEFAULT 20,
    semantic_weight  float       DEFAULT 1.0,
    fulltext_weight  float       DEFAULT 1.0,
    graph_weight     float       DEFAULT 0.5,
    p_k              int         DEFAULT 60
)
RETURNS TABLE (
    node_id     text,
    name        text,
    source_type text,
    summary     text,
    tags        text[],
    url         text,
    rrf_score   float
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
BEGIN
    RETURN QUERY
    WITH
    -- Stream 1: Semantic search (via embedding cosine distance)
    semantic AS (
        SELECT
            n.id                                        AS node_id,
            ROW_NUMBER() OVER (
                ORDER BY n.embedding <=> query_embedding
            )                                           AS rank
        FROM public.kg_nodes n
        WHERE query_embedding IS NOT NULL
          AND n.embedding IS NOT NULL
          AND (p_user_id IS NULL OR n.user_id = p_user_id)
        ORDER BY n.embedding <=> query_embedding
        LIMIT p_limit * 3
    ),

    -- Stream 2: Full-text search (via tsvector)
    fulltext AS (
        SELECT
            n.id                                        AS node_id,
            ROW_NUMBER() OVER (
                ORDER BY ts_rank_cd(n.fts, websearch_to_tsquery('english', query_text)) DESC
            )                                           AS rank
        FROM public.kg_nodes n
        WHERE query_text IS NOT NULL
          AND query_text != ''
          AND n.fts @@ websearch_to_tsquery('english', query_text)
          AND (p_user_id IS NULL OR n.user_id = p_user_id)
        ORDER BY ts_rank_cd(n.fts, websearch_to_tsquery('english', query_text)) DESC
        LIMIT p_limit * 3
    ),

    -- Stream 3: Graph neighbors of top semantic hits (1-hop expansion)
    graph_neighbors AS (
        SELECT DISTINCT
            CASE
                WHEN l.source_node_id = s.node_id THEN l.target_node_id
                ELSE l.source_node_id
            END                                         AS node_id,
            s.rank                                      AS rank
        FROM semantic s
        JOIN public.kg_links l
            ON (p_user_id IS NULL OR l.user_id = p_user_id)
           AND (l.source_node_id = s.node_id OR l.target_node_id = s.node_id)
        WHERE s.rank <= 5  -- expand only from top-5 semantic hits
    ),

    -- Reciprocal Rank Fusion
    rrf AS (
        SELECT
            combined.node_id,
            SUM(combined.score) AS rrf_score
        FROM (
            SELECT node_id, semantic_weight  / (p_k + rank)::float AS score FROM semantic
            UNION ALL
            SELECT node_id, fulltext_weight  / (p_k + rank)::float AS score FROM fulltext
            UNION ALL
            SELECT node_id, graph_weight     / (p_k + rank)::float AS score FROM graph_neighbors
        ) combined
        GROUP BY combined.node_id
    )

    SELECT
        n.id            AS node_id,
        n.name          AS name,
        n.source_type   AS source_type,
        n.summary       AS summary,
        n.tags          AS tags,
        n.url           AS url,
        r.rrf_score     AS rrf_score
    FROM rrf r
    JOIN public.kg_nodes n
        ON n.id = r.node_id
       AND (p_user_id IS NULL OR n.user_id = p_user_id)
    ORDER BY r.rrf_score DESC
    LIMIT p_limit;
END;
$$;

COMMENT ON FUNCTION hybrid_kg_search IS '3-stream hybrid search: semantic + fulltext + graph neighbors with RRF fusion';


-- ── 14. Permissions ────────────────────────────────────────────────────────
-- Revoke default public access, grant only to authenticated + service_role

REVOKE ALL ON FUNCTION match_kg_nodes      FROM PUBLIC;
REVOKE ALL ON FUNCTION find_neighbors      FROM PUBLIC;
REVOKE ALL ON FUNCTION shortest_path       FROM PUBLIC;
REVOKE ALL ON FUNCTION top_connected_nodes FROM PUBLIC;
REVOKE ALL ON FUNCTION isolated_nodes      FROM PUBLIC;
REVOKE ALL ON FUNCTION top_tags            FROM PUBLIC;
REVOKE ALL ON FUNCTION similar_nodes       FROM PUBLIC;
REVOKE ALL ON FUNCTION execute_kg_query    FROM PUBLIC;
REVOKE ALL ON FUNCTION hybrid_kg_search    FROM PUBLIC;

GRANT EXECUTE ON FUNCTION match_kg_nodes      TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION find_neighbors      TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION shortest_path       TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION top_connected_nodes TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION isolated_nodes      TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION top_tags            TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION similar_nodes       TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION execute_kg_query    TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION hybrid_kg_search    TO authenticated, service_role;


-- ── Done ───────────────────────────────────────────────────────────────────
-- Run this migration AFTER kg_public/schema.sql has been applied.
-- Verify with: SELECT proname FROM pg_proc WHERE proname IN (
--   'match_kg_nodes','find_neighbors','shortest_path','top_connected_nodes',
--   'isolated_nodes','top_tags','similar_nodes','execute_kg_query','hybrid_kg_search'
-- );
