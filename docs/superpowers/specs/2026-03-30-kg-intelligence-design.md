# KG Intelligence Layer — Native Design Spec

**Date**: 2026-03-30
**Status**: Draft — pending user approval
**Approach**: B (Native Stack) — zero LangChain, zero Neo4j
**Research basis**: 17 subagents, 3 rounds, source code analysis of LLMGraphTransformer + GraphCypherQAChain

---

## Executive Summary

Add five intelligence capabilities to the existing Supabase-backed knowledge graph without introducing LangChain, Neo4j, or any heavy framework. The design replaces every LangChain KG feature with a native equivalent that is either superior or equivalent, using only tools already in the stack plus two lightweight additions (`networkx`, `numpy`).

**Performance envelope (hard constraints):**
- `GET /api/graph` — under **2 seconds** (currently ~150ms via `kg_graph_view`)
- Full summarize workflow (`POST /api/summarize`) — under **30 seconds** end-to-end
- Incremental overhead per module — budgeted and measured via latency subagent
- Backend must remain featherweight for mobile web (no heavy imports on cold start)

**New dependencies:**
- `networkx>=3.2` (~1.5MB, pure Python, no C extensions)
- `numpy>=1.26` (~15MB, already an indirect dep of several packages)

---

## Architecture Overview

```
                     POST /api/summarize
                            │
              ┌─────────────┴──────────────┐
              ▼                             ▼
     Existing Pipeline              New Intelligence Layer
     ─────────────────              ──────────────────────
     extract content                M1: Entity Extraction
     Gemini summarize        ──►    M2: Embedding Generation
     tag generation                 M3: Semantic Auto-Link
     write note                     M4: Graph Analytics (cached)
              │                             │
              └─────────────┬──────────────┘
                            ▼
                     Supabase KG
                 (kg_nodes + kg_links)
                            │
              ┌─────────────┴──────────────┐
              ▼                             ▼
     GET /api/graph                 New Query Endpoints
     (existing, + enriched)         ─────────────────────
     PageRank, community            M5: NL Graph Query
     labels in response             M6: Graph Traversal RPCs
                                    M7: Hybrid Retrieval
```

**Modules (parallelizable for implementation):**

| Module | Name | Files Touched | Can Parallel? |
|--------|------|---------------|---------------|
| M1 | Entity-Relationship Extraction | new: `website/core/supabase_kg/entity_extractor.py` | Yes |
| M2 | Semantic Embeddings (pgvector) | new: `website/core/supabase_kg/embeddings.py`, schema migration | Yes |
| M3 | Graph Intelligence (NetworkX) | new: `website/core/supabase_kg/analytics.py`, modify: `routes.py`, `app.js` | After M2 |
| M4 | NL Graph Query (Text-to-SQL) | new: `website/core/supabase_kg/nl_query.py`, new route | Yes |
| M5 | Graph Traversal RPCs | new: SQL migration, modify: `repository.py` | Yes |
| M6 | Hybrid Retrieval | new: `website/core/supabase_kg/retrieval.py`, new route | After M2 + M5 |

---

## Module M1: Entity-Relationship Extraction

### What LangChain Does (Benchmark)

LLMGraphTransformer (`langchain-experimental`):
- System prompt: "You are a top-tier algorithm for extracting information in structured formats"
- Dynamic Pydantic schema generation with `allowed_nodes` / `allowed_relationships`
- Two modes: tool-calling (structured output) and prompt-based (JSON parse + `json_repair`)
- Post-processing: title-case IDs, uppercase relationship types, camelCase properties
- Strict-mode filtering against allowed type lists
- Entity dedup: exact `(id, type)` set — **no fuzzy matching**
- Single-pass only, no gleaning, no coreference resolution beyond prompt instructions
- 5 trivial few-shot examples (Adam/Microsoft scenario)

### What We Build (Superior)

A native entity extractor using Gemini structured output with techniques borrowed from Microsoft GraphRAG and KGGen that LLMGraphTransformer lacks.

**Key advantages over LangChain:**
1. **Two-step extraction** — free-form analysis first, then structured formatting (+13% accuracy per CleanLab benchmark)
2. **Gleaning loop** — multi-pass "did you miss anything?" pattern (up to 2x entity recall per GraphRAG paper)
3. **Embedding-based entity dedup** — cosine similarity at 0.90 threshold (vs LangChain's exact-match-only)
4. **Relationship strength scoring** — 1-10 numeric weight (LangChain has none)
5. **Entity descriptions** — rich descriptions per entity (LangChain has none)
6. **Domain-specific prompt** — tailored to tech articles, not generic

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
entities (technologies, concepts, tools, people, organizations) and
their relationships. Analyze the following content thoroughly.

User: Identify ALL entities and relationships in this content. For each
entity, provide its name, type, and a one-sentence description. For
each relationship, provide source, target, type, strength (1-10), and
a brief description. Think step by step.

TITLE: {title}
CONTENT: {summary}
```

**Step 2 — Structured formatting** (Gemini `response_json_schema`):
```
System: Convert the analysis into the exact JSON schema provided.
Use ONLY these entity types: {allowed_entity_types}
Use ONLY these relationship types: {allowed_relationship_types}

User: {free_form_analysis_from_step_1}
```

JSON schema enforced via `response_mime_type="application/json"` + `response_schema` parameter. Schema defined as Pydantic model, converted via `model_json_schema()`.

**Step 3 — Gleaning loop** (optional, `max_gleanings >= 1`):
```
System: Review the extraction. MANY entities and relationships were
missed in the previous extraction. Add any additional entities and
relationships found in the original content below.

User: Original content: {summary}
Already extracted: {step_2_result}
Add ONLY new entities and relationships not already captured.
```

After gleaning response, merge results. If the LLM returns nothing new, stop.

**Post-processing:**
1. Normalize entity IDs: lowercase, strip special chars, use most complete form
2. Normalize relationship types: UPPER_SNAKE_CASE
3. Deduplicate entities:
   - Exact match on normalized ID → merge
   - If `enable_entity_dedup` and embeddings available: embed entity names, merge pairs with cosine similarity > `dedup_similarity_threshold`
4. Validate against allowed types (case-insensitive), drop non-conforming
5. Drop entities without IDs, relationships without source/target

**Integration point:** Called from `routes.py` `/api/summarize` AFTER `summarize_url()` returns. Entity extraction runs on the `brief_summary` field (200-500 tokens, well within context window — no chunking needed).

**Latency budget:** Step 1 (~1.5s) + Step 2 (~1s) + Step 3 gleaning (~1.5s if enabled) = **~4s total** with gleaning, ~2.5s without. This runs in parallel with the embedding generation (M2), so net impact on the workflow is the max of (M1, M2) ≈ 4s.

**Graceful degradation:** If entity extraction fails (rate limit, timeout), the summarize endpoint returns normally without entities — existing tag-based linking still works. Entities are additive, never blocking.

### Tests for M1

**Test 1 — `test_entity_extraction_basic`**: Mock Gemini responses. Feed a tech article summary mentioning Python, TensorFlow, and Google. Assert: 3 entities extracted with correct types, at least 1 relationship, all types within allowed lists.

**Test 2 — `test_entity_extraction_gleaning`**: Mock first Gemini call returning 2 entities, gleaning call returning 1 more. Assert: final result has 3 entities. Verify gleaning prompt includes previously extracted entities.

**Test 3 — `test_entity_dedup_embedding`**: Create two entities "JavaScript" and "JS" with mock embeddings having 0.95 cosine similarity. Assert: they merge into a single canonical entity. Create "Python" and "React" with 0.3 similarity. Assert: they remain separate.

---

## Module M2: Semantic Embeddings (pgvector)

### What LangChain Does (Benchmark)

`SupabaseVectorStore` (`langchain-community`):
- Wraps pgvector with LangChain's document abstraction
- Requires `documents` table and `match_documents` RPC function
- Supports similarity search with metadata filtering
- Just a thin wrapper — no algorithmic value over direct pgvector

### What We Build (Equivalent, Zero Framework Overhead)

Direct Gemini embeddings + pgvector in Supabase. No wrapper, no extra package.

### Schema Migration: `supabase/website_kg/002_add_embeddings.sql`

```sql
-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding column to existing kg_nodes
ALTER TABLE kg_nodes ADD COLUMN IF NOT EXISTS embedding vector(768);

-- HNSW index for fast cosine similarity (only needed at >1K nodes)
-- Start without index; add when node count exceeds 1000
-- CREATE INDEX idx_kg_nodes_embedding
--     ON kg_nodes USING hnsw (embedding vector_cosine_ops)
--     WITH (m = 16, ef_construction = 64);

-- Similarity search RPC function
CREATE OR REPLACE FUNCTION match_kg_nodes(
    query_embedding vector(768),
    match_threshold float DEFAULT 0.75,
    match_count int DEFAULT 10,
    target_user_id uuid DEFAULT NULL
)
RETURNS TABLE (
    id text,
    name text,
    source_type text,
    summary text,
    tags text[],
    url text,
    similarity float
)
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT
        n.id,
        n.name,
        n.source_type,
        n.summary,
        n.tags,
        n.url,
        1 - (n.embedding <=> query_embedding) AS similarity
    FROM public.kg_nodes n
    WHERE (target_user_id IS NULL OR n.user_id = target_user_id)
      AND n.embedding IS NOT NULL
      AND 1 - (n.embedding <=> query_embedding) > match_threshold
    ORDER BY n.embedding <=> query_embedding ASC
    LIMIT least(match_count, 200);
$$;

REVOKE EXECUTE ON FUNCTION match_kg_nodes FROM public, anon;
GRANT EXECUTE ON FUNCTION match_kg_nodes TO authenticated, service_role;
```

### File: `website/core/supabase_kg/embeddings.py`

**Functions:**
- `generate_embedding(text: str, task_type: str = "SEMANTIC_SIMILARITY") -> list[float]`
  - Uses existing `genai.Client` from `google-genai` SDK
  - Model: `gemini-embedding-001`
  - Dimensions: 768 (via `output_dimensionality` MRL truncation)
  - L2-normalizes the truncated vector: `embedding / np.linalg.norm(embedding)`
  - Rate-limit handling: reuses `_is_rate_limited()` pattern from `summarizer.py`
  - Returns empty list on failure (graceful degradation)

- `generate_embeddings_batch(texts: list[str], task_type: str = "SEMANTIC_SIMILARITY") -> list[list[float]]`
  - Batch API: up to 250 texts per call
  - For backfill script usage

- `find_similar_nodes(repo: KGRepository, user_id: UUID, embedding: list[float], threshold: float = 0.75, limit: int = 10) -> list[dict]`
  - Calls `match_kg_nodes` Supabase RPC function
  - Returns list of `{id, name, source_type, similarity}` dicts

**Integration into `routes.py` `/api/summarize`:**

After `summarize_url()` returns and before `repo.add_node()`:
1. Generate embedding from `brief_summary` text (~200ms)
2. Pass embedding to `KGNodeCreate` (new optional field: `embedding: list[float] | None`)
3. After node insert, call `find_similar_nodes()` with the new embedding
4. Create semantic links for matches above threshold that don't already have tag-based links
5. Semantic links use `relation = "semantic"` to distinguish from tag-based links

**Updated `KGNodeCreate` model:**
```python
class KGNodeCreate(BaseModel):
    id: str
    name: str
    source_type: str
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    url: str
    node_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None  # NEW: 768-dim vector
```

**Updated `repository.py` `add_node()`:**
- Include `embedding` in the INSERT payload if present
- After `_auto_link()` (tag-based), call `_semantic_link()` (embedding-based)
- `_semantic_link()`: calls `match_kg_nodes` RPC, creates links for similarity > 0.75 that don't already exist as tag links

**Latency budget:** Embedding generation ~200ms. Similarity search via pgvector ~10ms (sequential scan at <1K nodes). Total: **~250ms**. Runs in parallel with M1 entity extraction.

**Backfill script:** `scripts/backfill_embeddings.py`
- Reads all nodes missing embeddings: `SELECT id, summary FROM kg_nodes WHERE embedding IS NULL`
- Batches of 50 (Gemini batch limit per request for safe rate-limiting)
- Generates embeddings, updates rows
- Reports progress: `Embedded 50/300 nodes...`

### Tests for M2

**Test 1 — `test_generate_embedding`**: Mock `genai.Client.models.embed_content()`. Assert: returns list of 768 floats. Assert: result is L2-normalized (norm ≈ 1.0).

**Test 2 — `test_semantic_link_creation`**: Create two nodes with embeddings having 0.85 cosine similarity. Call `_semantic_link()`. Assert: a link with `relation="semantic"` is created between them. Create a third node with 0.5 similarity. Assert: no link created.

**Test 3 — `test_embedding_graceful_degradation`**: Mock Gemini API to raise `ClientError(429)`. Assert: `generate_embedding()` returns empty list. Assert: node is still created without embedding. Assert: no crash in the summarize pipeline.

---

## Module M3: Graph Intelligence (NetworkX)

### What LangChain Does (Benchmark)

LangChain provides **zero** graph algorithm capabilities. No PageRank, no community detection, no centrality. This module has no LangChain equivalent — it's a net-new capability.

Neo4j's Graph Data Science library provides 70+ algorithms, but requires a Neo4j database. NetworkX provides the same algorithms for in-memory graphs, which is sufficient at <10K nodes.

### What We Build

Server-side graph analytics computed on cache refresh, results included in the `/api/graph` response for frontend visualization.

### File: `website/core/supabase_kg/analytics.py`

**Function: `compute_graph_metrics(graph: KGGraph) -> GraphMetrics`**

```python
@dataclass
class GraphMetrics:
    """Pre-computed graph metrics for frontend consumption."""
    pagerank: dict[str, float]        # node_id -> score
    communities: dict[str, int]       # node_id -> community_id
    betweenness: dict[str, float]     # node_id -> centrality score
    closeness: dict[str, float]       # node_id -> centrality score
    num_communities: int
    num_components: int
    computed_at: str                   # ISO timestamp
```

**Pipeline:**
1. Build `nx.Graph()` from `KGGraph.nodes` + `KGGraph.links`
2. Skip computation if graph has < 3 nodes (return empty metrics)
3. Compute in order (all sub-5ms at 1K nodes):
   - `nx.pagerank(G, alpha=0.85)` → node importance for sizing
   - `nx.community.louvain_communities(G, resolution=1.0)` → topic clusters
   - `nx.betweenness_centrality(G)` → bridge nodes
   - `nx.closeness_centrality(G)` → well-connected nodes
   - `nx.number_connected_components(G)` → isolated clusters
4. Return `GraphMetrics` dataclass

**Integration into `routes.py` `/api/graph`:**

Modify `graph_data()` to compute metrics alongside graph fetch:

```python
@router.get("/graph")
async def graph_data():
    # ... existing cache logic ...
    graph = repo.get_graph(UUID(user_id))
    metrics = compute_graph_metrics(graph)

    result = graph.model_dump()
    # Enrich nodes with metrics
    for node in result["nodes"]:
        nid = node["id"]
        node["pagerank"] = metrics.pagerank.get(nid, 0)
        node["community"] = metrics.communities.get(nid, 0)
        node["betweenness"] = metrics.betweenness.get(nid, 0)
    result["meta"] = {
        "communities": metrics.num_communities,
        "components": metrics.num_components,
        "computed_at": metrics.computed_at,
    }
    # ... cache and return ...
```

**Frontend changes (`app.js`):**

1. **Node sizing** — replace degree-based sizing with PageRank:
   ```javascript
   // Current (app.js ~line 206):
   // const deg = nodeDegrees[node.id] || 1;
   // const baseRadius = Math.min(2 + deg * 0.3, 5);

   // New:
   const pr = node.pagerank || 0;
   const maxPr = Math.max(...graphData.nodes.map(n => n.pagerank || 0), 0.001);
   const baseRadius = 2 + (pr / maxPr) * 4; // 2-6 range
   ```

2. **Community color overlay** — add a thin ring around each node in the community color:
   - Keep source-type fill colors (amber for YouTube, teal for GitHub, etc.)
   - Add a `SpriteText` ring or border using a community-indexed palette
   - Community palette: 10 distinct colors, cycling for > 10 communities

**Latency budget:** All algorithms combined take ~1-5ms at 1K nodes. This runs once per 30s cache refresh cycle. **Zero additional latency** on cache hits. On cache miss: adds ~5ms to the Supabase fetch round-trip (~150ms), negligible.

### Tests for M3

**Test 1 — `test_compute_metrics_basic`**: Create a KGGraph with 5 nodes and 6 links forming a triangle + chain. Assert: all nodes have pagerank > 0, at least 1 community detected, betweenness values exist for all nodes.

**Test 2 — `test_compute_metrics_empty_graph`**: Pass empty KGGraph (0 nodes). Assert: returns empty metrics without crashing. Pass KGGraph with 1 node and 0 links. Assert: returns metrics with pagerank = {node: 1.0}, 1 community, 1 component.

**Test 3 — `test_graph_response_enrichment`**: Mock `get_graph()` to return a test graph. Call `GET /api/graph`. Assert: response nodes contain `pagerank`, `community`, `betweenness` fields. Assert: response contains `meta.communities` and `meta.components`.

---

## Module M4: Natural Language Graph Query (Text-to-SQL)

### What LangChain Does (Benchmark)

GraphCypherQAChain (`langchain-neo4j`):
- Auto-introspects Neo4j schema via APOC `apoc.meta.data()`
- Prompt: "Generate Cypher statement to query a graph database. Schema: {schema}. Question: {question}"
- `CypherQueryCorrector`: regex-based relationship direction fixer (direction only, not syntax)
- Executes Cypher, formats response with second LLM call
- **No error recovery** — raises on Cypher execution failure
- **Known SQL injection vulnerability** (CVE-2024-8309)
- Requires Neo4j (not available on Supabase)

### What We Build (More Robust)

A native NL-to-SQL pipeline using Gemini + Supabase RPC with:
- Schema-in-prompt (trivial with 2 tables)
- `EXPLAIN` validation before execution (more robust than CypherQueryCorrector)
- Error-and-retry loop (feeds SQL errors back to Gemini — LangChain doesn't do this)
- Read-only execution via `SECURITY DEFINER` function
- Domain-specific few-shot examples for KG query patterns

### File: `website/core/supabase_kg/nl_query.py`

**Class: `NLGraphQuery`**

```python
class NLGraphQuery:
    """Natural language to SQL query engine for the knowledge graph."""

    def __init__(self, genai_client, supabase_client):
        self._genai = genai_client
        self._sb = supabase_client
        self._model = "gemini-2.5-flash"

    async def ask(self, question: str, user_id: UUID) -> NLQueryResult:
        """Convert natural language question to SQL, execute, format answer."""
```

**`NLQueryResult` model:**
```python
class NLQueryResult(BaseModel):
    question: str
    sql: str
    raw_result: list[dict]
    answer: str              # Natural language formatted answer
    latency_ms: int
    retries: int             # 0 = first attempt succeeded
```

**System prompt (domain-specific, with schema + few-shot examples):**

```
You are a PostgreSQL expert that converts natural language questions about
a personal knowledge graph into SQL queries.

DATABASE SCHEMA:
- kg_nodes(id TEXT, user_id UUID, name TEXT, source_type TEXT, summary TEXT,
           tags TEXT[], url TEXT, node_date DATE, embedding vector(768), metadata JSONB)
- kg_links(id UUID, user_id UUID, source_node_id TEXT, target_node_id TEXT,
           relation TEXT)

RULES:
- ALWAYS filter by user_id = '{user_id}'
- For tag searches: tags @> ARRAY['tag'] or tags && ARRAY['tag1','tag2']
- For text search: name ILIKE '%term%' or summary ILIKE '%term%'
- For graph traversal: use WITH RECURSIVE CTEs with depth limits
- Return ONLY valid PostgreSQL SQL. No markdown, no backticks, no explanation.
- LIMIT results to 50 rows maximum.
- NEVER use DELETE, UPDATE, INSERT, DROP, ALTER, or TRUNCATE.

EXAMPLES:

Q: What topics do I read about most?
A: SELECT unnest(tags) AS tag, COUNT(*) AS frequency FROM kg_nodes
   WHERE user_id = '{user_id}' GROUP BY tag ORDER BY frequency DESC LIMIT 20;

Q: What articles are related to machine learning?
A: SELECT id, name, source_type, url FROM kg_nodes
   WHERE user_id = '{user_id}' AND tags @> ARRAY['machine-learning']
   ORDER BY node_date DESC LIMIT 20;

Q: How are "attention mechanisms" and "system design" connected?
A: WITH RECURSIVE search AS (
     SELECT id AS node_id, ARRAY[id] AS path, 0 AS depth
     FROM kg_nodes WHERE user_id = '{user_id}' AND name ILIKE '%attention%'
     UNION ALL
     SELECT CASE WHEN l.source_node_id = s.node_id THEN l.target_node_id
            ELSE l.source_node_id END,
            s.path || CASE WHEN l.source_node_id = s.node_id THEN l.target_node_id
            ELSE l.source_node_id END, s.depth + 1
     FROM search s JOIN kg_links l ON l.user_id = '{user_id}'
       AND (l.source_node_id = s.node_id OR l.target_node_id = s.node_id)
     WHERE s.depth < 5 AND CASE WHEN l.source_node_id = s.node_id
       THEN l.target_node_id ELSE l.source_node_id END <> ALL(s.path)
   ) SELECT s.path, s.depth, n.name FROM search s
     JOIN kg_nodes n ON n.user_id = '{user_id}' AND n.id = s.node_id
     WHERE n.name ILIKE '%system design%' ORDER BY s.depth LIMIT 1;

Q: Show me isolated articles with no connections
A: SELECT n.id, n.name, n.source_type, n.url FROM kg_nodes n
   LEFT JOIN kg_links l ON l.user_id = '{user_id}'
     AND (l.source_node_id = n.id OR l.target_node_id = n.id)
   WHERE n.user_id = '{user_id}' AND l.id IS NULL
   ORDER BY n.node_date DESC;

Q: What are my most connected articles?
A: SELECT n.id, n.name, n.source_type, COUNT(DISTINCT l.id) AS connections
   FROM kg_nodes n LEFT JOIN kg_links l ON l.user_id = '{user_id}'
     AND (l.source_node_id = n.id OR l.target_node_id = n.id)
   WHERE n.user_id = '{user_id}' GROUP BY n.id, n.name, n.source_type
   ORDER BY connections DESC LIMIT 20;
```

**Pipeline:**
1. Generate SQL via Gemini (system prompt + user question)
2. **Safety check**: reject if SQL contains `DELETE|UPDATE|INSERT|DROP|ALTER|TRUNCATE` (regex)
3. **Validation**: execute `EXPLAIN {sql}` via Supabase RPC — if it fails, feed error to Gemini for retry (max 1 retry)
4. Execute validated SQL via Supabase RPC
5. Format raw results with second Gemini call: "Answer this question based on these query results: {question} Results: {json_results}"
6. Return `NLQueryResult`

**Supabase RPC for safe execution:**

```sql
-- Migration: 003_add_query_functions.sql
CREATE OR REPLACE FUNCTION execute_kg_query(
    query_text TEXT,
    p_user_id UUID
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET statement_timeout = '5s'
AS $$
DECLARE
    result JSONB;
BEGIN
    -- Safety: reject mutations
    IF query_text ~* '(DELETE|UPDATE|INSERT|DROP|ALTER|TRUNCATE|GRANT|REVOKE)' THEN
        RAISE EXCEPTION 'Only SELECT queries are allowed';
    END IF;

    EXECUTE format('SELECT jsonb_agg(row_to_json(t)) FROM (%s) t', query_text)
    INTO result;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$;

REVOKE EXECUTE ON FUNCTION execute_kg_query FROM public, anon;
GRANT EXECUTE ON FUNCTION execute_kg_query TO service_role;
```

**New API endpoint:**

```python
@router.post("/graph/query")
async def nl_graph_query(body: NLQueryRequest, request: Request):
    """Natural language query against the knowledge graph."""
    # Rate limit: 5 queries/min (more expensive than summarize)
    ...
```

**Latency budget:** SQL generation ~1.5s + validation ~50ms + execution ~10ms + formatting ~1s = **~2.5s total**. This is a separate endpoint, not on the critical path of `/api/summarize` or `/api/graph`.

### Tests for M4

**Test 1 — `test_nl_query_basic`**: Mock Gemini to return a simple SELECT SQL. Mock Supabase RPC to return test rows. Assert: `NLQueryResult` has correct SQL, raw_result, and formatted answer.

**Test 2 — `test_nl_query_rejects_mutations`**: Send "Delete all my articles". Assert: safety check rejects the generated SQL. Assert: HTTP 400 response with appropriate error message.

**Test 3 — `test_nl_query_error_retry`**: Mock first Gemini SQL generation to produce invalid SQL (EXPLAIN fails). Mock retry to produce valid SQL. Assert: final result succeeds with `retries=1`.

---

## Module M5: Graph Traversal RPCs

### What LangChain Does (Benchmark)

Neo4j Cypher provides elegant pattern matching: `MATCH (a)-[*1..5]->(b)` in one line. LangChain's `CypherQueryCorrector` fixes relationship direction only. No path finding, no component detection built into LangChain itself.

### What We Build (Equivalent at Scale)

PostgreSQL recursive CTE functions exposed as Supabase RPCs. Verbose but functionally equivalent, with sub-5ms execution at 10K nodes.

### Schema Migration: `supabase/website_kg/003_add_graph_functions.sql`

**6 RPC functions:**

#### 1. `find_neighbors(p_user_id, p_node_id, p_depth)`
K-hop neighbor query — "find articles related to X within N hops".

```sql
CREATE OR REPLACE FUNCTION find_neighbors(
    p_user_id UUID,
    p_node_id TEXT,
    p_depth INT DEFAULT 2
)
RETURNS TABLE (
    node_id TEXT, name TEXT, source_type TEXT, summary TEXT,
    tags TEXT[], url TEXT, depth INT
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
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
```

#### 2. `shortest_path(p_user_id, p_source_id, p_target_id, p_max_depth)`
Path query — "how are X and Y connected?"

```sql
CREATE OR REPLACE FUNCTION shortest_path(
    p_user_id UUID, p_source_id TEXT, p_target_id TEXT,
    p_max_depth INT DEFAULT 10
)
RETURNS TABLE (path TEXT[], depth INT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
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
```

#### 3. `top_connected_nodes(p_user_id, p_limit)`
Degree centrality — "what are my most connected articles?"

#### 4. `isolated_nodes(p_user_id)`
Orphan detection — "show me articles with no connections"

#### 5. `top_tags(p_user_id, p_limit)`
Tag frequency — "what are my most common topics?"

#### 6. `similar_nodes(p_user_id, p_node_id, p_limit)`
Tag-overlap similarity — "find nodes sharing the most tags with X"

(Full SQL for 3-6 follows the patterns in the recursive CTE research — see research artifacts.)

**Repository integration:**
Add methods to `KGRepository`:
- `find_neighbors(user_id, node_id, depth=2) -> list[dict]`
- `shortest_path(user_id, source_id, target_id) -> dict | None`
- `top_connected(user_id, limit=20) -> list[dict]`
- `isolated_nodes(user_id) -> list[dict]`
- `top_tags(user_id, limit=20) -> list[dict]`

Each calls `self._client.rpc("function_name", params).execute()`.

**Latency budget:** All RPC functions sub-5ms at 10K nodes. Network round-trip to Supabase ~100ms. Total per call: **~100ms**.

### Tests for M5

**Test 1 — `test_find_neighbors_rpc`**: Seed a small test graph (5 nodes, chain topology: A→B→C→D→E). Call `find_neighbors(A, depth=2)`. Assert: returns B (depth 1) and C (depth 2) but NOT D or E.

**Test 2 — `test_shortest_path_rpc`**: Same chain graph. Call `shortest_path(A, E)`. Assert: path = [A, B, C, D, E], depth = 4. Call `shortest_path(A, A)`. Assert: empty result (no self-path).

**Test 3 — `test_isolated_nodes_rpc`**: Create 3 nodes, link only 2 of them. Call `isolated_nodes()`. Assert: returns exactly the unlinked node.

---

## Module M6: Hybrid Retrieval

### What LangChain Does (Benchmark)

`GraphRetriever` (langchain-graph-retriever):
- Vector search → follow metadata-defined edges → combined results
- Results combined via **naive string concatenation** — no ranking algorithm
- No Supabase adapter exists

### What We Build (Superior — Reciprocal Rank Fusion)

Three-stream retrieval: pgvector semantic search + PostgreSQL full-text search (tsvector) + graph traversal (recursive CTE), combined via Reciprocal Rank Fusion (RRF) — the documented Supabase hybrid search pattern.

### Schema Migration Addition (in `002_add_embeddings.sql`):

```sql
-- Add full-text search index
ALTER TABLE kg_nodes ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_kg_nodes_fts ON kg_nodes USING GIN (fts);

-- Hybrid search RPC (3-stream: semantic + fulltext + graph neighbors)
CREATE OR REPLACE FUNCTION hybrid_kg_search(
    query_text TEXT,
    query_embedding vector(768),
    p_user_id UUID,
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
        SELECT n.id, ROW_NUMBER() OVER (ORDER BY ts_rank(n.fts, websearch_to_tsquery('english', query_text)) DESC) AS rank
        FROM public.kg_nodes n
        WHERE n.user_id = p_user_id AND n.fts @@ websearch_to_tsquery('english', query_text)
        LIMIT match_count * 2
    ),
    graph_neighbors AS (
        SELECT CASE WHEN l.source_node_id = p_seed_node_id THEN l.target_node_id
                    ELSE l.source_node_id END AS id,
               ROW_NUMBER() OVER (ORDER BY l.created_at DESC) AS rank
        FROM public.kg_links l
        WHERE p_seed_node_id IS NOT NULL
          AND l.user_id = p_user_id
          AND (l.source_node_id = p_seed_node_id OR l.target_node_id = p_seed_node_id)
        LIMIT match_count * 2
    ),
    combined AS (
        SELECT
            COALESCE(s.id, f.id, g.id) AS id,
            COALESCE(1.0 / (k + s.rank), 0) * semantic_weight +
            COALESCE(1.0 / (k + f.rank), 0) * fulltext_weight +
            COALESCE(1.0 / (k + g.rank), 0) * graph_weight AS score
        FROM semantic s
        FULL OUTER JOIN fulltext f ON s.id = f.id
        FULL OUTER JOIN graph_neighbors g ON COALESCE(s.id, f.id) = g.id
    )
    SELECT n.id, n.name, n.source_type, n.summary, n.tags, n.url, c.score
    FROM combined c
    JOIN public.kg_nodes n ON n.user_id = p_user_id AND n.id = c.id
    ORDER BY c.score DESC
    LIMIT match_count;
$$;
```

### File: `website/core/supabase_kg/retrieval.py`

**Function: `hybrid_search(query: str, user_id: UUID, seed_node_id: str | None = None) -> list[dict]`**
1. Generate query embedding via `generate_embedding(query, task_type="RETRIEVAL_QUERY")`
2. Call `hybrid_kg_search` Supabase RPC with query text + embedding + optional seed node
3. Return ranked results

**New API endpoint:**

```python
@router.post("/graph/search")
async def graph_search(body: SearchRequest, request: Request):
    """Hybrid semantic + fulltext + graph search."""
    ...
```

**Latency budget:** Embedding generation ~200ms + RPC execution ~50ms + network ~100ms = **~350ms total**.

### Tests for M6

**Test 1 — `test_hybrid_search_all_streams`**: Seed a graph with nodes containing various text and embeddings. Query with a term that matches keyword ("python"), embedding (similar vector), and graph neighbor (linked node). Assert: results from all 3 streams appear, top result has highest combined score.

**Test 2 — `test_hybrid_search_graceful_without_embeddings`**: Query against nodes that have no embeddings. Assert: still returns results from fulltext + graph streams. Assert: no error.

**Test 3 — `test_hybrid_search_performance`**: Seed 500 nodes with embeddings. Time the search. Assert: total latency < 500ms.

---

## Integration: Updated `/api/summarize` Pipeline

After all modules are integrated, the summarize flow becomes:

```
POST /api/summarize { url }
  │
  ├─ 1. summarize_url(url)                      [existing, ~8-15s]
  │     → title, summary, tags, source_type
  │
  ├─ 2. PARALLEL:
  │     ├─ generate_embedding(brief_summary)      [M2, ~200ms]
  │     └─ extract_entities(brief_summary)        [M1, ~2.5-4s]
  │
  ├─ 3. add_node() with embedding                [existing + M2, ~100ms]
  │     ├─ _auto_link() tag-based                [existing]
  │     └─ _semantic_link() embedding-based       [M2, ~100ms]
  │
  ├─ 4. Store entities in metadata                [M1, ~10ms]
  │     (kg_nodes.metadata.entities = [...])
  │
  └─ 5. Invalidate graph cache                   [existing]
       (next GET /api/graph recomputes M3 analytics)

Total: ~15-20s (within 30s budget)
```

**Entity storage strategy:** Entities extracted by M1 are stored in `kg_nodes.metadata.entities` as a JSON array. This avoids schema changes and keeps entities associated with their source node. If entity-level KG queries become needed later, a separate `kg_entities` table can be added as a future enhancement.

---

## Performance Budget Summary

| Operation | Current | After Enhancement | Budget | Status |
|-----------|---------|-------------------|--------|--------|
| `GET /api/graph` (cache hit) | ~1ms | ~1ms | < 2s | OK |
| `GET /api/graph` (cache miss) | ~150ms | ~160ms (+NetworkX 5ms) | < 2s | OK |
| `POST /api/summarize` | ~8-15s | ~15-20s (+embeddings 200ms, +entities ~4s parallel) | < 30s | OK |
| `POST /api/graph/query` | N/A | ~2.5s | < 5s | OK |
| `POST /api/graph/search` | N/A | ~350ms | < 1s | OK |
| RPC: `find_neighbors` | N/A | ~100ms (network) | < 500ms | OK |
| RPC: `shortest_path` | N/A | ~100ms (network) | < 500ms | OK |
| Cold start (import overhead) | ~200ms | ~250ms (+networkx ~50ms) | < 500ms | OK |

**Latency verification plan:** After each module is implemented, spawn a latency measurement subagent that:
1. Calls each endpoint 10 times
2. Measures p50, p95, p99 latency
3. Compares against the budget above
4. Flags any endpoint exceeding its budget

---

## New Dependencies (requirements.txt additions)

```
# Graph algorithms (PageRank, community detection, centrality)
networkx>=3.2

# Vector normalization for MRL-truncated embeddings
numpy>=1.26
```

**No other new dependencies.** Everything else uses existing packages: `google-genai` (Gemini API), `supabase` (database), `fastapi` (routes), `pydantic` (models).

---

## File Change Summary

| File | Change Type | Module |
|------|-------------|--------|
| `website/core/supabase_kg/entity_extractor.py` | **NEW** | M1 |
| `website/core/supabase_kg/embeddings.py` | **NEW** | M2 |
| `website/core/supabase_kg/analytics.py` | **NEW** | M3 |
| `website/core/supabase_kg/nl_query.py` | **NEW** | M4 |
| `website/core/supabase_kg/retrieval.py` | **NEW** | M6 |
| `supabase/website_kg/002_add_embeddings.sql` | **NEW** | M2, M6 |
| `supabase/website_kg/003_add_graph_functions.sql` | **NEW** | M4, M5 |
| `website/core/supabase_kg/models.py` | MODIFY (add embedding field to KGNodeCreate, add NLQueryResult, SearchResult) | M2, M4 |
| `website/core/supabase_kg/repository.py` | MODIFY (add _semantic_link, add RPC wrappers) | M2, M5 |
| `website/core/supabase_kg/__init__.py` | MODIFY (export new modules) | All |
| `website/api/routes.py` | MODIFY (enrich /api/graph, add /graph/query, /graph/search) | M3, M4, M6 |
| `website/knowledge_graph/js/app.js` | MODIFY (PageRank sizing, community overlay) | M3 |
| `requirements.txt` | MODIFY (add networkx, numpy) | M3 |
| `scripts/backfill_embeddings.py` | **NEW** | M2 |
| `tests/test_entity_extractor.py` | **NEW** | M1 |
| `tests/test_embeddings.py` | **NEW** | M2 |
| `tests/test_analytics.py` | **NEW** | M3 |
| `tests/test_nl_query.py` | **NEW** | M4 |
| `tests/test_graph_rpcs.py` | **NEW** | M5 |
| `tests/test_hybrid_retrieval.py` | **NEW** | M6 |

---

## Implementation Order & Parallelism

```
Phase 1 (parallel — no dependencies between them):
  ├─ M1: Entity Extraction
  ├─ M2: Semantic Embeddings + pgvector migration
  ├─ M4: NL Graph Query
  └─ M5: Graph Traversal RPCs + SQL migration

Phase 2 (depends on M2):
  ├─ M3: Graph Intelligence (needs graph data for NetworkX)
  └─ M6: Hybrid Retrieval (needs embeddings + RPCs)

Phase 3 (integration):
  ├─ Wire all modules into /api/summarize pipeline
  ├─ Update /api/graph response with analytics
  └─ Add /api/graph/query and /api/graph/search endpoints

Phase 4 (verification):
  ├─ Run all tests
  ├─ Spawn latency measurement subagent
  ├─ Verify all performance budgets met
  └─ Backfill embeddings for existing nodes
```

Each Phase 1 module can be assigned to a separate subagent for parallel execution.
