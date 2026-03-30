# KG Intelligence Layer — Native Design Spec

**Date**: 2026-03-30
**Status**: Draft v4 — pending user approval
**Approach**: B (Native Stack) — zero LangChain, zero Neo4j
**Research basis**: 17 research subagents + 5 review subagents, source code analysis of LLMGraphTransformer + GraphCypherQAChain

---

## Executive Summary

Add six intelligence capabilities to the existing Supabase-backed knowledge graph without introducing LangChain, Neo4j, or any heavy framework. The design replaces every LangChain KG feature with a native equivalent that is either superior or equivalent, using only tools already in the stack plus two lightweight additions (`networkx`, `numpy`).

**Performance envelope (hard constraints):**
- `GET /api/graph` — under **2 seconds** (currently ~150ms via `kg_graph_view`)
- Full summarize workflow (`POST /api/summarize`) — under **30 seconds** end-to-end
- Incremental overhead per module — budgeted and measured via latency subagent
- Backend must remain featherweight for mobile web (no heavy imports on cold start)

**New dependencies:**
- `networkx>=3.2` (~1.5MB, pure Python, no C extensions; Louvain built-in since v2.7)
- `numpy>=1.26` (~15MB, already an indirect dep of several packages)

---

## Architecture Overview

```
                     POST /api/summarize
                            |
              +-------------+-------------+
              v                           v
     Existing Pipeline            New Intelligence Layer
     -----------------            ----------------------
     extract content              M1: Entity Extraction
     Gemini summarize      -->    M2: Embedding Generation
     tag generation               M3: Semantic Auto-Link
     write note                   M4: Graph Analytics (cached)
              |                           |
              +-----------+---------------+
                          v
                     Supabase KG
                 (kg_nodes + kg_links)
                          |
              +-----------+--------------+
              v                          v
     GET /api/graph               New Query Endpoints
     (existing, + enriched)       ---------------------
     PageRank, community          M4: NL Graph Query
     labels in response           M5: Graph Traversal RPCs
                                  M6: Hybrid Retrieval
```

**Modules (parallelizable for implementation):**

| Module | Name | Files Touched | Can Parallel? |
|--------|------|---------------|---------------|
| M1 | Entity-Relationship Extraction | new: `entity_extractor.py` | Yes |
| M2 | Semantic Embeddings (pgvector) | new: `embeddings.py`, schema migration | Yes |
| M3 | Graph Intelligence (NetworkX) | new: `analytics.py`, modify: `routes.py`, `app.js` | After M2 |
| M4 | NL Graph Query (Text-to-SQL) | new: `nl_query.py`, new route | Yes |
| M5 | Graph Traversal RPCs | new: SQL migration, modify: `repository.py` | Yes |
| M6 | Hybrid Retrieval | new: `retrieval.py`, new route | After M2 + M5 |

All new Python files live under `website/core/supabase_kg/`.

---

## Schema Migration: `supabase/website_kg/002_add_intelligence.sql`

Consolidated migration for M1, M2, M5, M6 (run once):

```sql
-- ============================================================================
-- KG Intelligence Layer — Schema Migration
-- Adds: pgvector embeddings, link weights, fulltext search, graph RPCs
-- ============================================================================

-- 1. pgvector extension + embedding column
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE kg_nodes ADD COLUMN IF NOT EXISTS embedding vector(768);

-- 2. Link enhancements for M1 entity extraction
ALTER TABLE kg_links ADD COLUMN IF NOT EXISTS weight INTEGER DEFAULT NULL
    CHECK (weight IS NULL OR (weight BETWEEN 1 AND 10));
ALTER TABLE kg_links ADD COLUMN IF NOT EXISTS link_type TEXT DEFAULT 'tag'
    CHECK (link_type IN ('tag', 'semantic', 'entity'));
ALTER TABLE kg_links ADD COLUMN IF NOT EXISTS description TEXT DEFAULT NULL;

-- 3. Full-text search for M6 hybrid retrieval
ALTER TABLE kg_nodes ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, ''))
    ) STORED;
CREATE INDEX IF NOT EXISTS idx_kg_nodes_fts ON kg_nodes USING GIN (fts);

-- NOTE: HNSW index deferred until >5K nodes. Sequential scan is fast enough
-- for <10K vectors (~10ms). HNSW wins at scale (40.5 QPS at 0.998 recall
-- vs 2.6 QPS for IVFFlat). Params: m=16, ef_construction=64 for <10K.
-- CREATE INDEX idx_kg_nodes_embedding
--     ON kg_nodes USING hnsw (embedding vector_cosine_ops)
--     WITH (m = 16, ef_construction = 64);

-- 4. Update kg_graph_view to include new fields
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
            FROM kg_nodes n WHERE n.user_id = u.id),
            '[]'::jsonb
        ),
        'links',
        COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'source',    l.source_node_id,
                    'target',    l.target_node_id,
                    'relation',  l.relation,
                    'weight',    l.weight,
                    'link_type', l.link_type,
                    'description', l.description
                )
            )
            FROM kg_links l WHERE l.user_id = u.id),
            '[]'::jsonb
        )
    ) AS graph_data
FROM kg_users u;

-- 5. Similarity search RPC (M2)
-- IMPORTANT: PostgREST (supabase-py) does NOT support pgvector operators
-- (<=>). All similarity queries MUST go through RPC functions.
CREATE OR REPLACE FUNCTION match_kg_nodes(
    query_embedding vector(768),
    match_threshold float DEFAULT 0.75,
    match_count int DEFAULT 10,
    target_user_id uuid DEFAULT NULL
)
RETURNS TABLE (
    id text, name text, source_type text, summary text,
    tags text[], url text, similarity float
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
    SELECT n.id, n.name, n.source_type, n.summary, n.tags, n.url,
        1 - (n.embedding <=> query_embedding) AS similarity
    FROM public.kg_nodes n
    WHERE (target_user_id IS NULL OR n.user_id = target_user_id)
      AND n.embedding IS NOT NULL
      AND 1 - (n.embedding <=> query_embedding) > match_threshold
    ORDER BY n.embedding <=> query_embedding ASC
    LIMIT least(match_count, 200);
$$;

-- 6. Graph traversal RPCs (M5)
CREATE OR REPLACE FUNCTION find_neighbors(
    p_user_id UUID, p_node_id TEXT, p_depth INT DEFAULT 2
)
RETURNS TABLE (
    node_id TEXT, name TEXT, source_type TEXT, summary TEXT,
    tags TEXT[], url TEXT, depth INT
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' SET statement_timeout = '5s'
AS $$
    WITH RECURSIVE neighbors AS (
        SELECT n.id AS node_id, 0 AS depth, ARRAY[n.id] AS path
        FROM public.kg_nodes n
        WHERE n.user_id = p_user_id AND n.id = p_node_id
        UNION ALL
        SELECT
            CASE WHEN l.source_node_id = nb.node_id
                 THEN l.target_node_id ELSE l.source_node_id END,
            nb.depth + 1,
            nb.path || CASE WHEN l.source_node_id = nb.node_id
                 THEN l.target_node_id ELSE l.source_node_id END
        FROM neighbors nb
        JOIN public.kg_links l ON l.user_id = p_user_id
            AND (l.source_node_id = nb.node_id OR l.target_node_id = nb.node_id)
        WHERE nb.depth < p_depth
          AND CASE WHEN l.source_node_id = nb.node_id
               THEN l.target_node_id ELSE l.source_node_id END <> ALL(nb.path)
    )
    SELECT DISTINCT ON (nb2.node_id)
        nb2.node_id, kn.name, kn.source_type, kn.summary,
        kn.tags, kn.url, nb2.depth
    FROM neighbors nb2
    JOIN public.kg_nodes kn ON kn.user_id = p_user_id AND kn.id = nb2.node_id
    WHERE nb2.depth > 0
    ORDER BY nb2.node_id, nb2.depth;
$$;

CREATE OR REPLACE FUNCTION shortest_path(
    p_user_id UUID, p_source_id TEXT, p_target_id TEXT,
    p_max_depth INT DEFAULT 10
)
RETURNS TABLE (path TEXT[], depth INT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' SET statement_timeout = '5s'
AS $$
    WITH RECURSIVE search AS (
        SELECT n.id AS node_id, ARRAY[n.id] AS path, 0 AS depth
        FROM public.kg_nodes n
        WHERE n.user_id = p_user_id AND n.id = p_source_id
        UNION ALL
        SELECT
            CASE WHEN l.source_node_id = s.node_id
                 THEN l.target_node_id ELSE l.source_node_id END,
            s.path || CASE WHEN l.source_node_id = s.node_id
                 THEN l.target_node_id ELSE l.source_node_id END,
            s.depth + 1
        FROM search s
        JOIN public.kg_links l ON l.user_id = p_user_id
            AND (l.source_node_id = s.node_id OR l.target_node_id = s.node_id)
        WHERE CASE WHEN l.source_node_id = s.node_id
               THEN l.target_node_id ELSE l.source_node_id END <> ALL(s.path)
          AND s.depth < p_max_depth
    )
    SELECT search.path, search.depth FROM search
    WHERE search.node_id = p_target_id
    ORDER BY search.depth LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION top_connected_nodes(
    p_user_id UUID, p_limit INT DEFAULT 20
)
RETURNS TABLE (node_id TEXT, name TEXT, source_type TEXT, degree BIGINT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' SET statement_timeout = '5s'
AS $$
    SELECT n.id, n.name, n.source_type, COUNT(DISTINCT l.id) AS degree
    FROM public.kg_nodes n
    LEFT JOIN public.kg_links l ON l.user_id = p_user_id
        AND (l.source_node_id = n.id OR l.target_node_id = n.id)
    WHERE n.user_id = p_user_id
    GROUP BY n.id, n.name, n.source_type
    ORDER BY degree DESC LIMIT p_limit;
$$;

CREATE OR REPLACE FUNCTION isolated_nodes(p_user_id UUID)
RETURNS TABLE (node_id TEXT, name TEXT, source_type TEXT, url TEXT, node_date DATE)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' SET statement_timeout = '5s'
AS $$
    SELECT n.id, n.name, n.source_type, n.url, n.node_date
    FROM public.kg_nodes n
    LEFT JOIN public.kg_links l ON l.user_id = p_user_id
        AND (l.source_node_id = n.id OR l.target_node_id = n.id)
    WHERE n.user_id = p_user_id AND l.id IS NULL
    ORDER BY n.node_date DESC;
$$;

CREATE OR REPLACE FUNCTION top_tags(p_user_id UUID, p_limit INT DEFAULT 20)
RETURNS TABLE (tag TEXT, frequency BIGINT, node_count BIGINT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' SET statement_timeout = '5s'
AS $$
    SELECT unnest(n.tags) AS tag, COUNT(*) AS frequency,
           COUNT(DISTINCT n.id) AS node_count
    FROM public.kg_nodes n WHERE n.user_id = p_user_id
    GROUP BY tag ORDER BY frequency DESC LIMIT p_limit;
$$;

CREATE OR REPLACE FUNCTION similar_nodes(
    p_user_id UUID, p_node_id TEXT, p_limit INT DEFAULT 10
)
RETURNS TABLE (node_id TEXT, name TEXT, source_type TEXT,
               shared_tag_count BIGINT, shared_tags TEXT[])
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' SET statement_timeout = '5s'
AS $$
    WITH seed_tags AS (
        SELECT unnest(tags) AS tag FROM public.kg_nodes
        WHERE user_id = p_user_id AND id = p_node_id
    )
    SELECT n.id, n.name, n.source_type, COUNT(*) AS shared_tag_count,
           array_agg(st.tag ORDER BY st.tag) AS shared_tags
    FROM public.kg_nodes n
    JOIN LATERAL unnest(n.tags) AS nt(tag) ON TRUE
    JOIN seed_tags st ON st.tag = nt.tag
    WHERE n.user_id = p_user_id AND n.id <> p_node_id
    GROUP BY n.id, n.name, n.source_type
    ORDER BY shared_tag_count DESC LIMIT p_limit;
$$;

-- 7. NL Query safe executor (M4)
-- RETURNS JSONB (not TABLE) because NL queries produce varying column sets.
CREATE OR REPLACE FUNCTION execute_kg_query(query_text TEXT, p_user_id UUID)
RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' SET statement_timeout = '5s'
AS $$
DECLARE result JSONB;
BEGIN
    -- Safety: reject mutations (case-insensitive)
    IF query_text ~* '(DELETE|UPDATE|INSERT|DROP|ALTER|TRUNCATE|GRANT|REVOKE)' THEN
        RAISE EXCEPTION 'Only SELECT queries are allowed';
    END IF;
    -- Security: enforce user scoping — reject queries not filtering by user_id
    IF query_text !~* ('user_id\s*=\s*''' || p_user_id::text || '''') THEN
        RAISE EXCEPTION 'Query must filter by the authenticated user_id';
    END IF;
    EXECUTE format('SELECT jsonb_agg(row_to_json(t)) FROM (%s) t', query_text)
    INTO result;
    -- Defense-in-depth: truncate large result sets
    IF jsonb_array_length(COALESCE(result, '[]'::jsonb)) > 50 THEN
        result := (SELECT jsonb_agg(elem) FROM jsonb_array_elements(result) WITH ORDINALITY AS t(elem, idx) WHERE idx <= 50);
    END IF;
    RETURN COALESCE(result, '[]'::jsonb);
END;
$$;

-- 8. Hybrid search RPC (M6) — Reciprocal Rank Fusion
-- RRF formula: score = sum( (1/(k+rank)) * weight ) across streams
-- k=60 is the standard RRF constant (prevents top-ranked items from dominating)
CREATE OR REPLACE FUNCTION hybrid_kg_search(
    query_text TEXT, query_embedding vector(768), p_user_id UUID,
    p_seed_node_id TEXT DEFAULT NULL,
    semantic_weight FLOAT DEFAULT 0.5,
    fulltext_weight FLOAT DEFAULT 0.3,
    graph_weight FLOAT DEFAULT 0.2,
    match_count INT DEFAULT 20,
    k INT DEFAULT 60
)
RETURNS TABLE (
    id TEXT, name TEXT, source_type TEXT, summary TEXT,
    tags TEXT[], url TEXT, score FLOAT
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
    WITH semantic AS (
        SELECT n.id, ROW_NUMBER() OVER (ORDER BY n.embedding <=> query_embedding) AS rank
        FROM public.kg_nodes n
        WHERE n.user_id = p_user_id AND n.embedding IS NOT NULL
        LIMIT match_count * 2
    ),
    fulltext AS (
        SELECT n.id, ROW_NUMBER() OVER (
            ORDER BY ts_rank(n.fts, websearch_to_tsquery('english', query_text)) DESC
        ) AS rank
        FROM public.kg_nodes n
        WHERE n.user_id = p_user_id
          AND n.fts @@ websearch_to_tsquery('english', query_text)
        LIMIT match_count * 2
    ),
    graph_neighbors AS (
        SELECT CASE WHEN l.source_node_id = p_seed_node_id
                    THEN l.target_node_id ELSE l.source_node_id END AS id,
               ROW_NUMBER() OVER (ORDER BY l.created_at DESC) AS rank
        FROM public.kg_links l
        WHERE p_seed_node_id IS NOT NULL AND l.user_id = p_user_id
          AND (l.source_node_id = p_seed_node_id OR l.target_node_id = p_seed_node_id)
        LIMIT match_count * 2
    ),
    combined AS (
        SELECT COALESCE(s.id, f.id, g.id) AS id,
            COALESCE(1.0/(k + s.rank), 0) * semantic_weight +
            COALESCE(1.0/(k + f.rank), 0) * fulltext_weight +
            COALESCE(1.0/(k + g.rank), 0) * graph_weight AS score
        FROM semantic s
        FULL OUTER JOIN fulltext f ON s.id = f.id
        FULL OUTER JOIN graph_neighbors g ON COALESCE(s.id, f.id) = g.id
    )
    SELECT n.id, n.name, n.source_type, n.summary, n.tags, n.url, c.score
    FROM combined c
    JOIN public.kg_nodes n ON n.user_id = p_user_id AND n.id = c.id
    ORDER BY c.score DESC LIMIT match_count;
$$;

-- 9. Permissions
REVOKE EXECUTE ON FUNCTION match_kg_nodes FROM public, anon;
REVOKE EXECUTE ON FUNCTION find_neighbors FROM public, anon;
REVOKE EXECUTE ON FUNCTION shortest_path FROM public, anon;
REVOKE EXECUTE ON FUNCTION top_connected_nodes FROM public, anon;
REVOKE EXECUTE ON FUNCTION isolated_nodes FROM public, anon;
REVOKE EXECUTE ON FUNCTION top_tags FROM public, anon;
REVOKE EXECUTE ON FUNCTION similar_nodes FROM public, anon;
REVOKE EXECUTE ON FUNCTION execute_kg_query FROM public, anon;
REVOKE EXECUTE ON FUNCTION hybrid_kg_search FROM public, anon;

GRANT EXECUTE ON FUNCTION match_kg_nodes TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION find_neighbors TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION shortest_path TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION top_connected_nodes TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION isolated_nodes TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION top_tags TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION similar_nodes TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION execute_kg_query TO service_role;
GRANT EXECUTE ON FUNCTION hybrid_kg_search TO authenticated, service_role;
```

---

## Module M1: Entity-Relationship Extraction

### What LangChain Does (Benchmark)

LLMGraphTransformer (`langchain-experimental`):
- System prompt: "You are a top-tier algorithm for extracting information in structured formats"
- Dynamic Pydantic schema generation with `allowed_nodes`/`allowed_relationships`
- Two modes: tool-calling (structured output) and prompt-based (JSON parse + `json_repair`)
- Post-processing: title-case IDs, uppercase relationship types, camelCase properties
- Strict-mode filtering against allowed type lists
- Entity dedup: exact `(id, type)` set — **no fuzzy matching**
- Single-pass only, no gleaning, no coreference resolution beyond prompt instructions
- 5 trivial few-shot examples (Adam/Microsoft scenario)
- Grounding instruction: "Do not add any information that is not explicitly mentioned in the text"
- OpenAI gets real enum constraints; other LLMs only get description strings

### What We Build (Superior)

A native entity extractor using Gemini structured output with techniques from Microsoft GraphRAG and KGGen.

**Key advantages over LangChain:**
1. **Two-step extraction** — free-form analysis first, then structured formatting. Structured output alone degrades reasoning by 10-15% (CleanLab benchmark); two-step improved accuracy from 48% to 61%
2. **Gleaning loop** — multi-pass "did you miss anything?" pattern. Single-pass captures only 44-66% of facts (MINE benchmark); gleaning achieves up to 2x entity recall (GraphRAG paper)
3. **Embedding-based entity dedup** — cosine similarity at 0.90 threshold. Without coreference resolution, entity duplication is ~26%; with it drops to ~20% (CORE-KG study). Mem0 uses two-tier: 0.7 for candidate generation, 0.90-0.95 for auto-merge
4. **Relationship strength scoring** — 1-10 numeric weight stored in new `kg_links.weight` column
5. **Entity descriptions** — rich descriptions per entity, stored in `kg_nodes.metadata.entities`
6. **Domain-specific prompt** — tailored to tech articles with relevant few-shot examples
7. **Hallucination mitigation** — grounding instruction + type validation. Baseline hallucination rate is 15-18% for few-shot extraction (MINE benchmark)

**Relationship to KGGen:** KGGen uses a three-stage pipeline (generate/aggregate/cluster) achieving 66% fact retention vs GraphRAG's 48%. Our approach borrows the core insight — separate free-form generation from structured formatting — but uses a simpler two-step pipeline. The aggregation/clustering stages are addressed by post-processing dedup + embedding-based entity resolution. Full KGGen-style clustering is a future enhancement candidate.

### File: `website/core/supabase_kg/entity_extractor.py`

**Classes:**
- `ExtractedEntity(BaseModel)`: `id: str`, `type: str`, `description: str`
- `ExtractedRelationship(BaseModel)`: `source: str`, `target: str`, `type: str`, `strength: int` (1-10), `description: str`
- `ExtractionResult(BaseModel)`: `entities: list[ExtractedEntity]`, `relationships: list[ExtractedRelationship]`
- `EntityExtractor`: Main class, takes Gemini client + optional config

**Configuration:**
```python
@dataclass
class ExtractionConfig:
    allowed_entity_types: list[str] = field(default_factory=lambda: [
        "Technology", "Concept", "Tool", "Language", "Framework",
        "Person", "Organization", "Pattern", "Algorithm", "Platform",
    ])
    allowed_relationship_types: list[str] = field(default_factory=lambda: [
        "USES", "IMPLEMENTS", "EXTENDS", "PART_OF", "CREATED_BY",
        "RELATED_TO", "ALTERNATIVE_TO", "DEPENDS_ON", "INSPIRED_BY",
    ])
    max_gleanings: int = 1        # 0 = single-pass, 1 = one extra pass
    enable_entity_dedup: bool = True
    dedup_similarity_threshold: float = 0.90
    model: str = "gemini-2.5-flash"
```

**Extraction pipeline (3 steps):**

**Step 1 — Free-form analysis** (avoids structured output reasoning degradation):
```
System: You are an expert at analyzing technical content and identifying
entities (technologies, concepts, tools, people, organizations) and their
relationships. Do NOT add any entity or relationship that is not explicitly
mentioned in the content. Do NOT infer or hallucinate connections.

User: Identify ALL entities and relationships in this content. For each
entity, provide its name, type, and a one-sentence description. For each
relationship, provide source, target, type, strength (1-10), and a brief
description. Think step by step.

EXAMPLE:
Input: "React 19 introduces a new compiler that automatically memoizes
components, developed by Meta's React team led by Andrew Clark."
Output:
Entities: React (Technology, "JavaScript UI library for building interfaces"),
React Compiler (Tool, "Automatic memoization compiler for React 19"),
Meta (Organization, "Technology company that develops React"),
Andrew Clark (Person, "Engineering lead on React team at Meta")
Relationships: React Compiler -PART_OF-> React (9, "Built-in feature"),
Meta -CREATED_BY-> React (10, "Meta develops React"),
Andrew Clark -CREATED_BY-> React Compiler (8, "Leads the team")

TITLE: {title}
CONTENT: {summary}
```

**Step 2 — Structured formatting** (Gemini `response_json_schema`):
```
System: Convert the analysis into the exact JSON schema provided.
Use ONLY these entity types: {allowed_entity_types}
Use ONLY these relationship types: {allowed_relationship_types}
These entity types already exist in the knowledge graph: {existing_types}
Prefer reusing existing types over creating new ones.

User: {free_form_analysis_from_step_1}
```

JSON schema enforced via `response_mime_type="application/json"` + `response_schema` parameter. Schema defined as Pydantic model, converted via `model_json_schema()`.

**Step 3 — Gleaning loop** (optional, `max_gleanings >= 1`):

Structured as a multi-turn conversation (LLM sees its own prior reasoning, matching GraphRAG's approach):
- Messages: [Step 1 system, Step 1 user, Step 1 response, Step 2 prompt, Step 2 response, gleaning prompt]

```
System: Review the extraction. MANY entities and relationships were
missed in the previous extraction. Add any additional entities and
relationships found in the original content below.

User: Original content: {summary}
Already extracted: {step_2_result}
Add ONLY new entities and relationships not already captured.
```

**Termination:** If the gleaning response contains zero entities whose normalized IDs are not already in the extracted set, stop. GraphRAG uses logit bias for forced yes/no; since Gemini lacks logit bias, we use the zero-new-entities check.

**Post-processing:**
1. Normalize entity IDs: lowercase, strip special chars, use most complete form
2. Normalize relationship types: UPPER_SNAKE_CASE
3. Deduplicate entities:
   - Exact match on normalized ID -> merge
   - If `enable_entity_dedup` and embeddings available: embed entity names using `generate_embedding(name, task_type="SEMANTIC_SIMILARITY")`, merge pairs with cosine similarity > `dedup_similarity_threshold`
4. Validate against allowed types (case-insensitive), drop non-conforming
5. Drop entities without IDs, relationships without source/target
6. If Gemini returns malformed JSON despite `response_schema`, attempt `json.loads()` with markdown fence stripping. Log and return empty `ExtractionResult` on failure.

**Entity-to-schema mapping:**
- Entities are NOT separate `kg_nodes` rows — they are sub-node-level metadata stored in `kg_nodes.metadata.entities` as a JSONB array: `[{id, type, description}, ...]`
- This preserves the invariant that `kg_nodes` = URL-level content items
- Extracted relationships become `kg_links` rows with `link_type='entity'`, `weight` = strength score, `description` = relationship description
- The `source_node_id` and `target_node_id` reference the parent content nodes that mention the related entities
- Existing UNIQUE constraint on `kg_links` prevents duplicate edges

**Schema drift prevention:** Query existing entity types from the graph and include them in the Step 2 prompt. This mitigates inconsistent typing across sessions (e.g., "Framework" vs "Library" for the same concept).

**Cross-extraction entity description updates:** When an entity (e.g., "Python") is extracted from multiple articles, keep the longer/more informative description. Future: use GraphRAG's approach of summarizing multiple descriptions into a composite using an LLM call.

**Hallucination mitigation:**
- Grounding instruction in Step 1: "Do NOT add information not explicitly mentioned"
- Type validation in post-processing (drop non-conforming)
- Future: add `confidence: float` field to `ExtractedEntity`/`ExtractedRelationship`

**Integration point:** Called from `routes.py` `/api/summarize` AFTER `summarize_url()` returns. Runs on `brief_summary` (200-500 tokens, no chunking needed).

**Latency budget:** Step 1 (~1.5s) + Step 2 (~1s) + Step 3 gleaning (~1.5s) = **~4s total** with gleaning, ~2.5s without. Runs in parallel with M2 embedding generation. Each Gemini call uses a 10-second `timeout` parameter on the `generate_content()` call as a circuit-breaker; if any step exceeds it, skip remaining steps and return partial results.

**`max_gleanings` safety:** Config enforces `max_gleanings <= 3` (hard cap). At `max_gleanings=3`, worst-case latency = ~7s, still within the 30s budget when parallel with existing summarization. Default is 1 (one extra pass).

**`existing_types` query:** On each extraction call, query existing types via: `SELECT DISTINCT jsonb_array_elements(metadata->'entities')->>'type' AS entity_type FROM kg_nodes WHERE user_id = $1 AND metadata ? 'entities' LIMIT 50`. Cache the result in-memory with the same 30s TTL as the graph cache.

**Entity dedup embedding dependency:** M1 entity dedup uses `generate_embedding()` from M2's `embeddings.py`. This is NOT a circular dependency — M1 and M2 are both Phase 1 modules but M1's dedup is an internal post-processing step that imports M2's pure function, not M2's pipeline integration. The `generate_embedding()` function has no state dependencies on M2 being "complete."

**Cross-node entity relationship mapping:** When M1 extracts a relationship like "Python USES TensorFlow" from Article A:
1. Check if a `kg_links` row already exists between Article A and any other node whose `metadata.entities` contains "TensorFlow" (search via `metadata @> '{"entities": [{"id": "tensorflow"}]}'::jsonb`)
2. If found: create link between Article A and that node with `link_type='entity'`, `relation='USES'`, `weight=strength`
3. If not found (target entity only exists in the same article): skip — self-referencing entity links add no graph value
4. Future enhancement: when a new article mentions a known entity, retroactively create entity links to all articles containing that same entity

**Graceful degradation:** If extraction fails (rate limit, timeout), summarize returns normally. Entities are additive, never blocking.

### Tests for M1

**Test 1 — `test_entity_extraction_basic`**: Mock Gemini responses. Feed a tech article summary mentioning Python, TensorFlow, Google. Assert: 3 entities extracted with correct types, at least 1 relationship, all types within allowed lists. Assert: grounding instruction present in prompt.

**Test 2 — `test_entity_extraction_gleaning`**: Mock first Gemini call returning 2 entities, gleaning call returning 1 more. Assert: final result has 3 entities. Verify gleaning prompt includes previously extracted entities as multi-turn conversation.

**Test 3 — `test_entity_dedup_embedding`**: Create "JavaScript" and "JS" with mock embeddings (0.95 cosine similarity). Assert: merge into single canonical entity. Create "Python" and "React" (0.3 similarity). Assert: remain separate.

---

## Module M2: Semantic Embeddings (pgvector)

### What LangChain Does (Benchmark)

`SupabaseVectorStore` (`langchain-community`):
- Wraps pgvector with LangChain's document abstraction
- Requires `documents` table and `match_documents` RPC function
- Just a thin wrapper — no algorithmic value over direct pgvector

### What We Build (Equivalent, Zero Framework Overhead)

Direct Gemini embeddings + pgvector in Supabase. No wrapper, no extra package.

**Architecture decision:** Embeddings generated in the application layer (Python API) at insert time, NOT via Supabase triggers/Edge Functions. Rationale: no orphaned nodes without embeddings, no Edge Function complexity (pgmq + pg_net + pg_cron), simpler debugging.

**Important constraint:** PostgREST (supabase-py) does NOT support pgvector operators (`<=>`, `<->`) natively in `.select()` queries. All similarity operations MUST go through Supabase RPC functions. Regular inserts work fine (pass embedding as Python list).

**WARNING:** Embedding spaces are INCOMPATIBLE between Gemini embedding models. If the model is ever upgraded, ALL existing embeddings must be regenerated. Store model version in `kg_nodes.metadata.embedding_model` for tracking.

### File: `website/core/supabase_kg/embeddings.py`

**Functions:**
- `generate_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]`
  - Model: `gemini-embedding-001` (GA). Note: `text-embedding-004` is DEPRECATED.
  - Dimensions: 768 (via `output_dimensionality` MRL truncation)
  - L2-normalizes the truncated vector. IMPORTANT: MRL-truncated vectors are NOT unit-length from the API. L2-normalization is REQUIRED for cosine similarity to work correctly.
  - Rate-limit handling: reuses `_is_rate_limited()` pattern from `summarizer.py`
  - Returns empty list on failure (graceful degradation)
  - Task type guidance:
    - `RETRIEVAL_DOCUMENT` — default for stored content (node summaries)
    - `RETRIEVAL_QUERY` — for search queries (used by M6 hybrid search)
    - `SEMANTIC_SIMILARITY` — for pairwise comparison (used by M1 entity dedup)

- `generate_embeddings_batch(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]`
  - Batch API: up to 250 texts per request, max 20,000 tokens per request, first 2,048 tokens per text used (remainder silently truncated)
  - For backfill script usage

- `find_similar_nodes(repo, user_id, embedding, threshold=0.75, limit=10) -> list[dict]`
  - Calls `match_kg_nodes` Supabase RPC function

**Cosine similarity reference ranges** (for `gemini-embedding-001` at 768 dims):
- \> 0.90: near-duplicate content (dedup detection in M1)
- 0.80-0.90: strongly related, same topic — high-confidence links
- 0.70-0.80: moderately related — discovery links (default threshold 0.75)
- 0.60-0.70: loosely related, may be noisy
- < 0.60: not useful for linking

**Link strategy:** Fixed threshold (0.75) for simplicity at <1K nodes. If popular nodes accumulate too many links, switch to top-K + floor (e.g., top-5 per node with 0.65 minimum floor).

**Link strength scoring for dual-type links:**
- Tag-based: `strength = shared_tag_count / max(total_tags_a, total_tags_b)`
- Semantic: `strength = cosine_similarity` (from RPC)
- Combined: `0.4 * tag_overlap + 0.6 * cosine_similarity`

**Gemini Embedding Pricing:**
- Free tier: sufficient for dev and low-traffic (<1K nodes/day)
- Paid: $0.15/1M tokens (batch: $0.075/1M)
- ~200 tokens/node summary -> ~$0.00003/node. Full backfill of 300 nodes: free.

**Updated `KGNodeCreate` model** — add optional embedding field:
```python
embedding: list[float] | None = None  # 768-dim vector
```

**Integration into `routes.py`:** After `summarize_url()`, before `add_node()`:
1. Generate embedding from `brief_summary` (~200ms)
2. Pass to `KGNodeCreate`
3. After insert, `find_similar_nodes()` -> create semantic links (`link_type='semantic'`)

**Backfill script:** `scripts/backfill_embeddings.py` — reads nodes missing embeddings, batches of 50 (conservative for rate-limiting; API supports up to 250 per call but smaller batches avoid 429s on free tier), generates + updates.

**Note:** The `metadata JSONB` column already exists in the original schema (`schema.sql` line 48: `metadata JSONB NOT NULL DEFAULT '{}'`). No migration needed for `metadata.entities` or `metadata.embedding_model` — they use existing JSONB column.

**Latency budget:** Embedding ~200ms + similarity search ~10ms = **~250ms**. Parallel with M1.

### Tests for M2

**Test 1 — `test_generate_embedding`**: Mock `genai.Client.models.embed_content()`. Assert: 768 floats returned, L2-normalized (norm ~= 1.0).

**Test 2 — `test_semantic_link_creation`**: Two nodes with 0.85 cosine similarity. Assert: `link_type='semantic'` link created. Third node at 0.5 similarity: no link.

**Test 3 — `test_embedding_graceful_degradation`**: Mock 429 error. Assert: returns empty list, node created without embedding, no crash.

---

## Module M3: Graph Intelligence (NetworkX)

### What LangChain Does (Benchmark)

LangChain provides **zero** graph algorithm capabilities. NetworkX provides equivalent algorithms to Neo4j GDS for in-memory graphs, sufficient at <10K nodes.

### What We Build

Server-side graph analytics computed on cache refresh, enriching the `/api/graph` response.

### File: `website/core/supabase_kg/analytics.py`

**Graph construction:**
```python
def _build_networkx_graph(graph: KGGraph) -> nx.Graph:
    """Use nx.Graph (UNDIRECTED) — KG links are bidirectional (shared-tag
    relationships have no direction; source/target is arbitrary)."""
    G = nx.Graph()
    for node in graph.nodes:
        G.add_node(node.id, name=node.name, group=node.group, tags=node.tags)
    for link in graph.links:
        G.add_edge(link.source, link.target, relation=link.relation)
    return G
```

**Function: `compute_graph_metrics(graph: KGGraph) -> GraphMetrics`**

```python
@dataclass
class GraphMetrics:
    pagerank: dict[str, float]        # node_id -> score
    communities: dict[str, int]       # node_id -> community_id
    betweenness: dict[str, float]     # node_id -> centrality score
    closeness: dict[str, float]       # node_id -> centrality score
    num_communities: int
    num_components: int
    computed_at: str                   # ISO timestamp
```

**Pipeline:**
1. Build `nx.Graph()` from nodes + links
2. Skip if < 3 nodes (return empty metrics)
3. Compute:
   - `nx.pagerank(G, alpha=0.85)` -> node importance
   - `nx.community.louvain_communities(G, resolution=1.0)` -> topic clusters
     - `resolution` < 1.0 = fewer larger communities; > 1.0 = more smaller. Start at 1.0, tune.
     - Built into NetworkX since v2.7 — no `python-louvain` package needed
   - `nx.betweenness_centrality(G, k=min(100, len(G)))` -> bridge nodes
     - O(VE) Brandes algorithm. `k` parameter for approximate sampling at scale
   - `nx.closeness_centrality(G, wf_improved=True)` -> well-connected nodes
     - `wf_improved=True` REQUIRED for correct results on disconnected graphs
   - `nx.number_connected_components(G)` -> isolated clusters
4. Return `GraphMetrics`

**Performance benchmarks by scale:**

| Scale | PageRank | Betweenness | Louvain | Total |
|-------|----------|-------------|---------|-------|
| 60 nodes (now) | <1ms | <1ms | <1ms | <1ms |
| 1K nodes | ~1-5ms | ~10-50ms | ~5-20ms | ~20-75ms |
| 10K nodes | ~50-200ms | ~500ms-2s (use k=100) | ~100-500ms | ~1-3s |

**Scaling (50K+ nodes):** At 50K+ nodes, NetworkX exceeds acceptable latency (~33s PageRank at 875K). Mitigations: (1) use `k=100` for betweenness sampling, (2) move to background task, (3) evaluate `igraph` (14x faster). Current trajectory: ~60 nodes, 50K is ~137 years away.

**Integration into `routes.py`:** Enrich all nodes with metrics:
```python
node["pagerank"] = metrics.pagerank.get(nid, 0)
node["community"] = metrics.communities.get(nid, 0)
node["betweenness"] = metrics.betweenness.get(nid, 0)
node["closeness"] = metrics.closeness.get(nid, 0)
```

**Frontend (`app.js`):**
1. **Node sizing** — PageRank replaces degree-based:
   ```javascript
   const pr = node.pagerank || 0;
   const maxPr = Math.max(...graphData.nodes.map(n => n.pagerank || 0), 0.001);
   const baseRadius = 2 + (pr / maxPr) * 4;
   ```
2. **Community overlay** — keep source-type fill colors; add thin community-colored ring

**Integration with M6:** NetworkX community membership and graph structure feed M6's RRF ranking. The graph stream in M6 uses 1-hop neighbors from `kg_links` with `graph_weight=0.2` in the fusion. Community labels from Louvain can further boost same-community results. For M2's semantic auto-linking, a simpler formula applies: `link_strength = 0.4 * tag_overlap + 0.6 * cosine_similarity`.

**Latency budget:** ~1-5ms at 1K nodes. Runs once per 30s cache refresh. Zero impact on cache hits.

### Tests for M3

**Test 1 — `test_compute_metrics_basic`**: 5 nodes, 6 links (triangle + chain). Assert: all nodes have pagerank > 0, at least 1 community, betweenness + closeness values exist.

**Test 2 — `test_compute_metrics_empty_graph`**: 0 nodes -> empty metrics, no crash. 1 node -> pagerank = 1.0, 1 community, 1 component.

**Test 3 — `test_graph_response_enrichment`**: Mock graph, call `GET /api/graph`. Assert: nodes contain `pagerank`, `community`, `betweenness`, `closeness`. Assert: `meta.communities` and `meta.components` present.

---

## Module M4: Natural Language Graph Query (Text-to-SQL)

### What LangChain Does (Benchmark)

GraphCypherQAChain (`langchain-neo4j`):
- Auto-introspects schema via APOC
- CypherQueryCorrector: only fixes relationship direction (regex), not syntax
- **No error recovery** — raises on failure
- **CVE-2024-8309** SQL injection vulnerability
- Requires Neo4j

### What We Build (More Robust)

NL-to-SQL pipeline with EXPLAIN validation + error-retry (LangChain has neither).

**Note:** supabase-py cannot execute raw SQL — justifies the RPC approach for all queries.

**CVE-2024-8309 mitigation (defense-in-depth):** LangChain's GraphCypherQAChain was vulnerable to prompt injection generating destructive queries. Our defense is layered: (1) Python-side case-insensitive regex rejects mutations, (2) RPC independently re-validates, (3) RPC enforces user_id scoping (rejects queries not filtering by authenticated user), (4) RPC runs as SECURITY DEFINER with service_role only, (5) statement_timeout prevents resource exhaustion. Strictly more robust than LangChain.

### File: `website/core/supabase_kg/nl_query.py`

**System prompt** includes schema, domain vocabulary, source_type enum, and few-shot examples:

```
DATABASE SCHEMA:
- kg_nodes(id TEXT, user_id UUID, name TEXT, source_type TEXT, summary TEXT,
           tags TEXT[], url TEXT, node_date DATE, embedding vector(768), metadata JSONB)
- kg_links(id UUID, user_id UUID, source_node_id TEXT, target_node_id TEXT,
           relation TEXT, weight INTEGER, link_type TEXT)

VALID source_type VALUES: 'youtube', 'github', 'reddit', 'substack', 'medium', 'generic'

DOMAIN VOCABULARY:
- "articles" / "notes" / "content" / "saves" = kg_nodes
- "videos" / "YouTube" = kg_nodes WHERE source_type = 'youtube'
- "repos" / "code" / "GitHub" = kg_nodes WHERE source_type = 'github'
- "newsletters" / "Substack" = kg_nodes WHERE source_type = 'substack'
- "Reddit posts" / "discussions" = kg_nodes WHERE source_type = 'reddit'
- "connections" / "links" / "edges" = kg_links
- "topics" / "tags" / "categories" = unnest(tags) from kg_nodes
- "related to X" = JOIN kg_links on source/target
- "isolated" / "orphaned" = LEFT JOIN kg_links ... WHERE l.id IS NULL

RULES:
- ALWAYS filter by user_id = '{user_id}'
- Return ONLY valid PostgreSQL SQL. No markdown, no backticks, no explanation.
- LIMIT to 50 rows max. NEVER use mutation statements.
```

**Pipeline:**
1. Generate SQL via Gemini
1b. **Strip LLM artifacts**: `re.sub(r'^```(?:sql)?\s*|\s*```$', '', output.strip(), flags=re.MULTILINE).strip()` — LLMs frequently add markdown fences despite instructions
2. **Safety check**: `re.search(r'(DELETE|UPDATE|INSERT|DROP|ALTER|TRUNCATE|GRANT|REVOKE)', sql, re.IGNORECASE)` — must be case-insensitive, must include GRANT/REVOKE
3. **Validation**: `EXPLAIN {sql}` via RPC. On failure, feed error to Gemini for retry (max 1)
4. Execute via `execute_kg_query` RPC (5s timeout, enforces user_id scoping)
5. If RPC times out, return user-friendly error (not raw PG timeout)
6. **Python-side result cap (defense-in-depth):** `results = results[:50]` before formatting, in case RPC truncation is ever bypassed
7. Format with second Gemini call
8. Return `NLQueryResult`

**user_id regex trade-off:** The RPC's `user_id` check (`user_id\s*=\s*'<uuid>'`) may false-reject valid SQL using `IN (...)` or `::uuid` cast syntax. This is an accepted trade-off — false-reject (query fails, user rephrases) is strictly safer than false-accept (cross-user data leak). Document as intentional.

**Error responses:**

| Failure | HTTP | Message |
|---------|------|---------|
| Safety check rejects | 400 | "I can only answer questions, not modify the graph." |
| EXPLAIN fails after retry | 400 | "I couldn't understand that question. Try rephrasing." |
| RPC timeout (>5s) | 504 | "That query was too complex. Try a simpler question." |
| RPC error | 500 | "Something went wrong. Please try again." |
| Rate limit | 429 | "Too many queries. Wait {seconds}s." |
| Empty results | 200 | Answer: "No results found. Try different keywords." |

**API endpoint:** `POST /api/graph/query` — rate limit 5/min per IP (reuse existing `_check_rate_limit` with separate bucket). Return HTTP 429 with retry-after.

**Latency budget:** ~2.5s (generation 1.5s + validation 50ms + execution 10ms + formatting 1s). Separate endpoint, not on critical path.

### Future Enhancement: Vanna.ai

If NL query accuracy proves insufficient, Vanna.ai (MIT) is a drop-in upgrade:
- Native PostgreSQL + Gemini support
- RAG-based: train with `vn.train(ddl=..., sql=..., question=...)`
- FastAPI integration: `register_chat_routes(app, vn)`
- Self-improving: stores successful query pairs for future retrieval

### Tests for M4

**Test 1 — `test_nl_query_basic`**: Mock Gemini SQL + Supabase RPC. Assert: correct `NLQueryResult`.

**Test 2 — `test_nl_query_rejects_mutations`**: "Delete all my articles" -> safety check rejects -> HTTP 400.

**Test 3 — `test_nl_query_error_retry`**: First SQL invalid (EXPLAIN fails), retry succeeds. Assert: `retries=1`.

**Test 4 — `test_nl_query_timeout`**: Mock RPC timeout. Assert: HTTP 504, user-friendly message, no raw PG error leaked.

**Test 5 — `test_nl_query_strips_markdown`**: Mock Gemini returning SQL in \`\`\`sql fences. Assert: fences stripped, query executes successfully.

---

## Module M5: Graph Traversal RPCs

### What LangChain Does (Benchmark)

Neo4j Cypher: elegant `MATCH (a)-[*1..5]->(b)`. At <10K nodes, PostgreSQL recursive CTEs are functionally equivalent with sub-5ms execution (Alibaba benchmark: 2.1ms for 3-depth at 10M nodes).

### What We Build

6 RPC functions (full SQL in the consolidated migration above):
1. `find_neighbors(user_id, node_id, depth)` — k-hop neighbors
2. `shortest_path(user_id, source, target, max_depth)` — BFS path finding
3. `top_connected_nodes(user_id, limit)` — degree centrality
4. `isolated_nodes(user_id)` — orphan detection (LEFT JOIN IS NULL anti-join)
5. `top_tags(user_id, limit)` — tag frequency
6. `similar_nodes(user_id, node_id, limit)` — tag-overlap similarity

**Design notes:**
- All use `UNION ALL` with array-based cycle prevention (`<> ALL(path)`). For connected-component queries, `UNION` (auto-dedup) preferred over `UNION ALL`.
- PG14+ `CYCLE` clause available on Supabase (PG15+) as cleaner alternative
- `SECURITY DEFINER SET search_path = ''` per Supabase security advisor
- All M5 RPCs should include `SET statement_timeout = '5s'` to prevent runaway recursive CTEs (add to each function's SET line in the migration)
- I/O optimization (optional): `CLUSTER kg_links USING idx_kg_links_user_source;` periodically for large graphs

**Repository integration:** Add methods to `KGRepository`, each calling `self._client.rpc()`:
- `find_neighbors(user_id, node_id, depth=2) -> list[dict]`
- `shortest_path(user_id, source_id, target_id) -> dict | None`
- `top_connected(user_id, limit=20) -> list[dict]`
- `isolated_nodes(user_id) -> list[dict]`
- `top_tags(user_id, limit=20) -> list[dict]`
- `similar_nodes(user_id, node_id, limit=10) -> list[dict]`

**Latency:** Sub-5ms query + ~100ms network = **~100ms** per call.

### Tests for M5

**Test 1 — `test_find_neighbors_rpc`**: Chain A->B->C->D->E. `find_neighbors(A, depth=2)` returns B, C only.

**Test 2 — `test_shortest_path_rpc`**: `shortest_path(A, E)` returns [A,B,C,D,E], depth=4.

**Test 3 — `test_isolated_nodes_rpc`**: 3 nodes, 2 linked. `isolated_nodes()` returns the unlinked one.

---

## Module M6: Hybrid Retrieval

### What LangChain Does (Benchmark)

`GraphRetriever`: vector search + metadata edges, combined via **naive string concatenation**. No Supabase adapter. No ranking algorithm.

### What We Build (Superior — Reciprocal Rank Fusion)

**Why RRF over concatenation:** LangChain's GraphRetriever merges via naive string concatenation — a mediocre vector match sits alongside a strong keyword match with no quality distinction. RRF normalizes ranks so documents appearing in multiple streams (high semantic similarity AND strong keyword match) are boosted to the top.

**RRF formula:** For each document, score per stream = `1 / (k + rank)` where `rank` is position (1-indexed) and `k=60` (standard constant from Cormack et al. RRF paper — dampens high-rank dominance). Each stream's RRF score is multiplied by its weight, then summed.

Three streams:
- **Semantic**: pgvector cosine similarity (`<=>` operator)
- **Fulltext**: PostgreSQL tsvector with `websearch_to_tsquery` (handles natural language syntax: "machine learning -beginner", "react OR vue" — no explicit tsquery syntax needed from user)
- **Graph**: 1-hop neighbors from `kg_links` (optional, via `p_seed_node_id`)

**Weight defaults:** semantic=0.5 (dominant — captures meaning beyond keywords), fulltext=0.3 (catches exact terms embeddings miss: acronyms, proper nouns), graph=0.2 (leverages user's existing KG structure). For conversational queries, increase graph_weight to 0.3-0.4.

**Graph stream behavior:** `p_seed_node_id` is optional (DEFAULT NULL). When NULL, the graph stream is silently skipped — RRF runs with semantic + fulltext only. The `fts` column uses `GENERATED ALWAYS AS` (auto-updates when name/summary change, zero application code).

**Full SQL in consolidated migration above.**

### File: `website/core/supabase_kg/retrieval.py`

1. Generate query embedding via `generate_embedding(query, task_type="RETRIEVAL_QUERY")`
2. Call `hybrid_kg_search` RPC
3. Return ranked results

**API endpoint:** `POST /api/graph/search`

**Latency:** Embedding 200ms + RPC 50ms + network 100ms = **~350ms**.

### Tests for M6

**Test 1 — `test_hybrid_search_all_streams`**: Query matching keyword + embedding + neighbor. Assert: all 3 streams contribute, top result has highest combined score.

**Test 2 — `test_hybrid_search_without_embeddings`**: No embeddings on nodes. Assert: fulltext + graph still work.

**Test 3 — `test_hybrid_search_performance`**: 500 nodes with embeddings. Assert: < 500ms.

---

## Integration: Updated `/api/summarize` Pipeline

```
POST /api/summarize { url }
  |
  +-- 1. summarize_url(url)                      [existing, ~8-15s]
  |
  +-- 2. PARALLEL:
  |     +-- generate_embedding(brief_summary)     [M2, ~200ms]
  |     +-- extract_entities(brief_summary)       [M1, ~2.5-4s]
  |
  +-- 3. add_node() with embedding               [existing + M2, ~100ms]
  |     +-- _auto_link() tag-based (link_type='tag')    [existing]
  |     +-- _semantic_link() embedding-based (link_type='semantic')  [M2]
  |
  +-- 4. Store entities in metadata              [M1, ~10ms]
  |     (kg_nodes.metadata.entities = [...])
  |     Create entity relationship links (link_type='entity')
  |
  +-- 5. Invalidate graph cache                  [existing]
       (next GET /api/graph recomputes M3 analytics)

Total: ~15-20s (within 30s budget)
```

---

## Performance Budget Summary

| Operation | Current | After | Budget | Status |
|-----------|---------|-------|--------|--------|
| `GET /api/graph` (hit) | ~1ms | ~1ms | < 2s | OK |
| `GET /api/graph` (miss) | ~150ms | ~155-230ms (+NetworkX) | < 2s | OK |
| `POST /api/summarize` | ~8-15s | ~15-20s (+M1 parallel, +M2) | < 30s | OK |
| `POST /graph/query` | N/A | ~2.5s | < 5s | OK |
| `POST /graph/search` | N/A | ~350ms | < 1s | OK |
| RPC: `find_neighbors` | N/A | ~100ms (network) | < 500ms | OK |
| RPC: `shortest_path` | N/A | ~100ms (network) | < 500ms | OK |
| RPC: `top_connected_nodes` | N/A | ~100ms (network) | < 500ms | OK |
| RPC: `isolated_nodes` | N/A | ~100ms (network) | < 500ms | OK |
| RPC: `top_tags` | N/A | ~100ms (network) | < 500ms | OK |
| RPC: `similar_nodes` | N/A | ~100ms (network) | < 500ms | OK |
| Cold start | ~200ms | ~250ms (+networkx) | < 500ms | OK |

**Latency verification:** After each module, spawn a subagent that calls each endpoint 10x, measures p50/p95/p99, compares against budget, flags violations. Runs in Phase 4 against deployed Render instance (not localhost) to capture real network conditions. For `/api/summarize`, measure incremental overhead (compare with/without intelligence modules). If any endpoint exceeds budget, the implementing agent must optimize before completion.

---

## New Dependencies

```
networkx>=3.2    # Louvain built-in since 2.7
numpy>=1.26      # L2 normalization for MRL-truncated embeddings
```

---

## File Change Summary

| File | Change | Module |
|------|--------|--------|
| `website/core/supabase_kg/entity_extractor.py` | **NEW** | M1 |
| `website/core/supabase_kg/embeddings.py` | **NEW** | M2 |
| `website/core/supabase_kg/analytics.py` | **NEW** | M3 |
| `website/core/supabase_kg/nl_query.py` | **NEW** | M4 |
| `website/core/supabase_kg/retrieval.py` | **NEW** | M6 |
| `supabase/website_kg/002_add_intelligence.sql` | **NEW** | All |
| `website/core/supabase_kg/models.py` | MODIFY (embedding field, NLQueryResult) | M2, M4 |
| `website/core/supabase_kg/repository.py` | MODIFY (_semantic_link, RPC wrappers) | M2, M5 |
| `website/core/supabase_kg/__init__.py` | MODIFY (exports) | All |
| `website/api/routes.py` | MODIFY (enrich graph, new endpoints) | M3-M6 |
| `website/knowledge_graph/js/app.js` | MODIFY (PageRank sizing, community) | M3 |
| `requirements.txt` | MODIFY (networkx, numpy) | M3 |
| `scripts/backfill_embeddings.py` | **NEW** | M2 |
| `tests/test_entity_extractor.py` | **NEW** | M1 |
| `tests/test_embeddings.py` | **NEW** | M2 |
| `tests/test_analytics.py` | **NEW** | M3 |
| `tests/test_nl_query.py` | **NEW** | M4 |
| `tests/test_graph_rpcs.py` | **NEW** | M5 |
| `tests/test_hybrid_retrieval.py` | **NEW** | M6 |

---

## Implementation Order

```
Phase 1 (parallel — no dependencies):
  +-- M1: Entity Extraction
  +-- M2: Semantic Embeddings + migration
  +-- M4: NL Graph Query
  +-- M5: Graph Traversal RPCs

Phase 2 (depends on M2):
  +-- M3: Graph Intelligence (NetworkX)
  +-- M6: Hybrid Retrieval

Phase 3 (integration):
  +-- Wire into /api/summarize pipeline
  +-- Enrich /api/graph with analytics
  +-- Add /graph/query and /graph/search endpoints

Phase 4 (verification):
  +-- Run all 18 tests
  +-- Spawn latency measurement subagent per endpoint
  +-- Verify all performance budgets met
  +-- Backfill embeddings for existing nodes
```

Each Phase 1 module can be assigned to a separate subagent for parallel execution.
