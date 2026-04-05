# KG Intelligence Layer — Verification Report

**Date**: 2026-04-06
**Verified against**: `docs/superpowers/specs/2026-03-30-kg-intelligence-design.md` + `docs/superpowers/plans/2026-03-30-kg-intelligence.md`
**Overall Status**: ⚠️ **PARTIAL — FUNCTIONAL CORE WITH CRITICAL RUNTIME BUGS**

---

## Executive Summary

The KG Intelligence Layer implementation delivers all six modules (M1–M6) described in the design spec. All Python files exist, the SQL migration is deployed, API routes are wired, and the frontend consumes PageRank-based sizing. The architecture goals are satisfied: **zero LangChain, zero Neo4j**, NetworkX + numpy + pgvector stack, and Gemini-native integration.

However, the implementation contains **five runtime-breaking integration bugs** — all in the Python → Supabase RPC call layer — that render M2 (find_similar_nodes), M4 (NL query) and M6 (hybrid search) non-functional in production. These bugs stem from **parameter-name drift** between the SQL migration and the Python wrappers that call it: the SQL function contracts evolved (e.g., `target_user_id` vs `match_user_id`, bare `query_text` vs `p_query_text`, column `node_id` vs Python's `id`) but Python wrappers were not synchronized. A sixth critical bug in M2 omits `output_dimensionality=768` from the Gemini embed call, which will return 3072-dim vectors that cannot insert into the `vector(768)` column.

M3 (Graph Analytics) is fully compliant and passes all runtime tests (3-node chain, empty, single-node, 2-node, disconnected). M5 (Graph Traversal RPCs) is correct: all 6 parameter names align between SQL and Python wrappers. The schema migration implements all 9 RPC functions with correct `SECURITY DEFINER SET search_path = ''` hardening plus `statement_timeout='5s'`. Twenty planned test files are missing — zero tests were written across all six modules.

Overall spec feature completeness is ~65% when weighted by correctness: the scaffolding exists everywhere, but the integration layer needs targeted fixes before this system can be considered operational.

---

## Module Status Overview

| Module | Status | Implementation File | Key Finding |
|--------|--------|---------------------|-------------|
| **M1 Entity Extraction** | ⚠️ PARTIAL | `website/features/kg_features/entity_extractor.py` | Functional, but gleaning is single-shot (not multi-turn), few-shot example missing, entity/rel type lists diverge from spec |
| **M2 Semantic Embeddings** | ❌ FAIL | `website/features/kg_features/embeddings.py` | Two critical runtime bugs: (1) `output_dimensionality=768` not passed → API returns 3072-dim, pgvector insert fails; (2) RPC parameter name mismatch (`match_user_id` vs `target_user_id`) |
| **M3 Graph Analytics** | ✅ PASS | `website/features/kg_features/analytics.py` | All 5 nx.* calls match spec exactly; all live tests pass |
| **M4 NL Graph Query** | ❌ FAIL | `website/features/kg_features/nl_query.py` | RPC call missing required `p_user_id` param; safety check is denylist (spec requires allowlist); EXPLAIN pre-validation entirely absent; source_type enum mismatch |
| **M5 Graph Traversal RPCs** | ✅ PASS | `website/core/supabase_kg/repository.py` + `supabase/website/kg_features/001_intelligence.sql` | All 6 wrappers parameter-aligned with SQL; cycle prevention + depth caps correct |
| **M6 Hybrid Retrieval** | ❌ FAIL | `website/features/kg_features/retrieval.py` | Every RPC parameter name mismatches SQL (`p_query_text` vs `query_text` etc.); return column names mismatch (`id` vs `node_id`, `score` vs `rrf_score`); `p_seed_node_id` sent but SQL has no such param |
| **Schema migration** | ⚠️ PARTIAL | `supabase/website/kg_features/001_intelligence.sql` | All 9 RPCs + fts + pgvector column + kg_graph_view present; SQL weights diverge from spec; IVFFlat index created despite spec saying defer HNSW |
| **Frontend integration** | ✅ PASS | `website/features/knowledge_graph/js/app.js` | PageRank-based node sizing wired (L212, L232, L265-266, L331-332) |
| **Test suite** | ❌ FAIL | `tests/` | Zero of 20 planned test files exist |

---

## Detailed Module Analysis

### M1: Entity Extraction

**Status**: ⚠️ PARTIAL
**File**: `website/features/kg_features/entity_extractor.py` (350 lines)
**Spec reference**: lines 404–573

#### What Was Expected (from spec)

- Pydantic models: `ExtractedEntity`, `ExtractedRelationship` (with `strength: 1–10`), `ExtractionResult`
- `ExtractionConfig` dataclass with:
  - 10 allowed entity types: `Technology, Concept, Tool, Language, Framework, Person, Organization, Pattern, Algorithm, Platform`
  - 9 allowed relationship types: `USES, IMPLEMENTS, EXTENDS, PART_OF, CREATED_BY, RELATED_TO, ALTERNATIVE_TO, DEPENDS_ON, INSPIRED_BY`
  - `max_gleanings=1` (hard cap 3), `enable_entity_dedup=True`, `dedup_similarity_threshold=0.90`, `model="gemini-2.5-flash"`
- Two-step pipeline:
  1. Step 1: free-form extraction with grounding instruction + domain-specific few-shot example
  2. Step 2: structured JSON via `response_mime_type="application/json"` + `response_schema`
- Multi-turn conversation gleaning loop — model sees its own prior reasoning (GraphRAG-style messages)
- Termination on zero-NEW entities (diff against already-extracted IDs)
- `_deduplicate_entities` with cosine similarity AND type-matching guard (prevents "React" Tech ↔ "React" Org merge)
- Post-processing: normalize IDs (lowercase, strip special chars), UPPER_SNAKE_CASE relationships, validate against allowed types
- 10s timeout per Gemini call, graceful degradation on failure
- `existing_types` schema-drift prevention (query Supabase for types already used)
- Integration: wired into `/api/summarize`, entities stored in `kg_nodes.metadata.entities`

#### What Was Found (in code)

All three Pydantic models present (lines 33, 40, 49). `ExtractionConfig` dataclass (lines 58–72) with `max_gleanings: int = 1`, `enable_entity_dedup: bool = True`, `dedup_similarity_threshold: float = 0.90`, `model: str = "gemini-2.5-flash"`. Hard cap enforced at line 221: `max_gleanings = min(self.config.max_gleanings, 3)`. Two prompts exist: `_ANALYSIS_PROMPT` (L86–104) contains GROUNDING RULE but **no few-shot example**. `_STRUCTURED_PROMPT` (L106–116) and `_GLEANING_PROMPT` (L118–134). Dedup (L152–190) uses `np.dot` for cosine with type guard at L180–181 (`if entity.type != kept_ent.type: continue`). Post-processing (L307–348) applies normalization and validates types. All 3 Gemini calls wrapped in `asyncio.wait_for(..., timeout=10.0)` (L230, L246, L267). Graceful degradation returns empty `ExtractionResult()` on exception (L300–305). Integration in `website/api/routes.py` L482–499 via `asyncio.create_task(_extract_entities())` — fire-and-forget. Syntax check: `SYNTAX OK`.

**Allowed entity types actually implemented (L61–64):**
```
"PERSON", "ORGANIZATION", "TECHNOLOGY", "CONCEPT",
"TOOL", "LANGUAGE", "FRAMEWORK", "PLATFORM", "TOPIC"
```
(9 types, UPPERCASE)

**Allowed relationship types (L65–68):**
```
"USES", "CREATED_BY", "RELATED_TO", "PART_OF",
"DEPENDS_ON", "ALTERNATIVE_TO", "IMPLEMENTS", "EXTENDS"
```
(8 types)

#### Missing or Divergent Features

| # | Spec Requirement | Actual | Impact |
|---|------------------|--------|--------|
| 1 | 10 entity types including `Pattern`, `Algorithm` | 9 types; missing `Pattern` + `Algorithm`; added non-specced `TOPIC` | Domain-specific misses (e.g., "Chain-of-Thought" algorithm extracted as CONCEPT) |
| 2 | 9 relationship types including `INSPIRED_BY` | 8 types; missing `INSPIRED_BY` | Cannot capture inspiration-based relationships |
| 3 | Few-shot example (React/Meta/Andrew Clark) in Step 1 prompt | None — prompt has only grounding rule | Likely degrades extraction quality; spec called this out as key differentiator vs LangChain |
| 4 | Multi-turn conversation gleaning (`contents=[msg1, response1, msg2, ...]`) | Single-shot re-prompts with prior JSON inlined as text | Gleaning pass cannot leverage model's prior reasoning chain |
| 5 | Terminate on zero-NEW entities (diff against extracted set) | Terminates on absolute empty entities list | Loop may continue spuriously, inflating API calls |
| 6 | `existing_types` schema-drift prevention (query Supabase) | Not implemented | Type vocabulary drifts across sessions ("Framework" vs "Library") |
| 7 | File location `website/core/supabase_kg/entity_extractor.py` | Lives at `website/features/kg_features/entity_extractor.py` | Cosmetic; imports updated consistently |

#### Pros

1. **Robust graceful degradation** — single try/except returns empty `ExtractionResult()` on ANY failure (timeout, malformed JSON, rate limit). Caller contract is blocking-safe; never needs to handle exceptions.
2. **Correct type-matched dedup guard** — prevents exact false-merge scenario called out in spec. `if entity.type != kept_ent.type: continue` at L180 is textbook-correct.
3. **Strong post-processing pipeline** — `_postprocess` normalizes IDs, uppercases types, filters against allowed sets, validates relationship endpoints against `valid_ids`, rejects self-loops.
4. **Structured output correctly enforced** — both `response_mime_type="application/json"` AND `response_schema=ExtractionResult`, enabling Gemini's native JSON-schema constraint.
5. **Timeouts + max_gleanings hard cap** — 10s asyncio.wait_for on all 3 API calls + `min(self.config.max_gleanings, 3)` enforces spec latency budget.

#### Cons

1. **Missing few-shot example** — Spec mandates domain-specific React/Meta/Andrew Clark example in Step 1 prompt. Zero examples in implementation. Likely impacts extraction quality.
2. **Gleaning is NOT multi-turn** — Spec explicitly mandates GraphRAG-style conversation history where model "sees its own prior reasoning". Implementation uses stateless single-turn calls with prior JSON stuffed into prompt text.
3. **Allowed type lists diverge from spec** — entity types missing `Pattern`/`Algorithm`, added non-specced `TOPIC`; relationship types missing `INSPIRED_BY`.
4. **No `existing_types` schema-drift prevention** — each extraction runs in isolation, no query for already-used types injected into Step 2 prompt.
5. **Gleaning termination rule too loose** — terminates on absolute empty list rather than zero-NEW, wasting API calls if gleaning re-returns already-extracted entities.

---

### M2: Semantic Embeddings

**Status**: ❌ FAIL (two critical runtime bugs)
**File**: `website/features/kg_features/embeddings.py`
**Spec reference**: lines 575–657

#### What Was Expected (from spec)

- Model: `gemini-embedding-001` (GA, NOT deprecated `text-embedding-004`)
- Dimensions: **768 via `output_dimensionality` MRL truncation parameter**
- L2 normalization required (MRL-truncated vectors are NOT unit-length)
- `generate_embedding(text, task_type="RETRIEVAL_DOCUMENT")`
- `generate_embeddings_batch()` for bulk
- `should_create_semantic_link(sim, threshold=0.75)`
- `find_similar_nodes()` via `match_kg_nodes` RPC
- 60s rate-limit cooldown using global timestamp + `time.monotonic()`
- Graceful degradation: returns `[]` on failure
- Integration: embedding generated in `/api/summarize`, stored on node creation, semantic links created via `_semantic_link()`

#### What Was Found (in code)

`_EMBEDDING_MODEL = "gemini-embedding-001"` (L22) ✅, `_EMBEDDING_DIMS = 768` (L23) ✅, `_RATE_LIMIT_COOLDOWN_SECS = 60` (L24) ✅. All 4 functions defined: `generate_embedding` (L41), `generate_embeddings_batch` (L91), `should_create_semantic_link` (L140), `find_similar_nodes` (L145). Cooldown uses `_last_rate_limit_ts: float = 0.0` (L26) + `time.monotonic()` (L57, L82) ✅. 429 detection via `"429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)` (L80–82). L2 normalization present (L72–78): `norm = np.linalg.norm(vec); if norm > 0: vec = vec / norm` ✅. Syntax check: `SYNTAX OK`.

**Gemini API call (L66–71) — verbatim:**
```python
response = client.models.embed_content(
    model=_EMBEDDING_MODEL,
    contents=text,
    config={"task_type": task_type},
)
```

**find_similar_nodes RPC call (L163–173) — verbatim:**
```python
response = supabase_client.rpc(
    "match_kg_nodes",
    {
        "query_embedding": embedding,
        "match_user_id": user_id,            # ← BUG: SQL expects "target_user_id"
        "match_threshold": threshold,
        "match_count": limit,
    },
).execute()
```

**SQL function signature (`001_intelligence.sql` L98–103):**
```sql
CREATE OR REPLACE FUNCTION match_kg_nodes(
    query_embedding  vector(768),
    match_threshold  float    DEFAULT 0.7,
    match_count      int      DEFAULT 10,
    target_user_id   uuid     DEFAULT NULL
)
```

#### Missing or Divergent Features

| # | Critical? | Issue |
|---|-----------|-------|
| 1 | 🔴 CRITICAL | **`output_dimensionality=768` NOT passed to API.** Gemini `gemini-embedding-001` defaults to **3072 dims**; returned 3072-dim vector cannot insert into `vector(768)` DB column → every embedding insert will raise pgvector dimension mismatch error. The `_EMBEDDING_DIMS = 768` constant is declared but never referenced in the API call. |
| 2 | 🔴 CRITICAL | **RPC parameter name mismatch**: Python passes `match_user_id`, SQL function declares `target_user_id`. PostgREST uses named-argument dispatch → every call returns PGRST202 "function not found". Semantic search is completely broken. |
| 3 | ⚠️ MINOR | 429 detection uses fragile string sniffing (`"429" in str(exc)`) rather than exception type check. |
| 4 | ⚠️ MINOR | `_semantic_link()` method does not exist in repository. `/api/summarize` generates embedding and UPDATEs the `embedding` column directly, but does NOT create semantic links between similar nodes. Auto-linking on similarity > 0.75 step is missing entirely. |
| 5 | ⚠️ MINOR | Default threshold divergence: Python=0.75 vs SQL `match_threshold DEFAULT 0.7` (non-breaking since Python always passes explicit value). |
| 6 | ⚠️ COSMETIC | SQL file comment line 18 still references deprecated `text-embedding-004` despite spec explicitly deprecating it. |

#### Pros

1. **Model choice correct** — uses `gemini-embedding-001` (GA), not deprecated `text-embedding-004`.
2. **L2 normalization is mathematically correct** — numpy `linalg.norm` + division, guarded against zero with `if norm > 0`, uses `float64` precision.
3. **Clean cooldown mechanism** — `time.monotonic()` immune to clock jumps, proper `global` declarations, mirrors existing `summarizer.py` pattern.
4. **Graceful degradation thorough** — all paths return `[]` (or list-of-empties preserving length for batch).
5. **task_type parameter exposed** — caller can pass `RETRIEVAL_QUERY` (M6) or `SEMANTIC_SIMILARITY` (M1 dedup) as needed.

#### Cons

1. **🔴 SHOW-STOPPER: Missing `output_dimensionality=768`** — breaks every insert into `vector(768)` column. One-line fix: add `"output_dimensionality": 768` to both config dicts (L67–71, L114–118).
2. **🔴 SHOW-STOPPER: RPC param name `match_user_id` should be `target_user_id`** — one-line fix at L168.
3. **No defensive length assertion** — even after fix, should `assert len(raw) == _EMBEDDING_DIMS` before returning to catch drift.
4. **Fragile 429 detection** — prefer `isinstance(exc, google.api_core.exceptions.ResourceExhausted)` or `exc.code == 429`.
5. **Module-level cooldown is worker-local** — each uvicorn worker has its own clock; under multi-worker deployment quota can still be exhausted.
6. **Missing `_semantic_link()` integration** — embeddings are generated and stored but no semantic links are created between similar nodes, defeating a core M2 deliverable.

---

### M3: Graph Analytics

**Status**: ✅ PASS
**File**: `website/features/kg_features/analytics.py`
**Spec reference**: lines 660–752

#### What Was Expected (from spec)

- `GraphMetrics` dataclass with 7 fields: pagerank, communities, betweenness, closeness, num_communities, num_components, computed_at
- `_build_networkx_graph` using `nx.Graph()` (UNDIRECTED)
- `nx.pagerank(G, alpha=0.85)`
- `nx.community.louvain_communities(G, resolution=1.0, seed=42)` (deterministic)
- `nx.betweenness_centrality(G, k=min(100, len(G)))`
- `nx.closeness_centrality(G, wf_improved=True)`
- `nx.number_connected_components(G)`
- Edge cases: empty graph → empty metrics; single node → `pagerank={id:1.0}, 1 community, 1 component`
- Integration: enriches `/api/graph` per-node
- Frontend: PageRank replaces degree-based sizing

#### What Was Found (in code)

All 7 GraphMetrics fields present (L22–32). `_build_networkx_graph` uses `nx.Graph()` (L39) ✅. All 5 NetworkX calls match spec parameters **exactly**:

| # | Spec | Actual (line) | Match |
|---|------|---------------|-------|
| 1 | `nx.pagerank(G, alpha=0.85)` | L83 | ✅ EXACT |
| 2 | `nx.community.louvain_communities(G, resolution=1.0, seed=42)` | L90–92 | ✅ EXACT |
| 3 | `nx.betweenness_centrality(G, k=min(100, len(G)))` | L105 | ✅ EXACT |
| 4 | `nx.closeness_centrality(G, wf_improved=True)` | L112 | ✅ EXACT |
| 5 | `nx.number_connected_components(G)` | L118 | ✅ EXACT |

Each call is wrapped in try/except + logger.warning + zero-dict fallback — defensive beyond spec.

**Live test output (3-node chain a↔b↔c):**
```
PR={'a': 0.2567, 'b': 0.4865, 'c': 0.2567}
Communities=1
Components=1
Betweenness={'a': 0.0, 'b': 1.0, 'c': 0.0}
Closeness={'a': 0.667, 'b': 1.0, 'c': 0.667}
ALL TESTS PASSED
```

Center node `b` correctly has highest PageRank (~0.486) and highest betweenness (1.0 — it's the single bridge). All 5 runtime tests pass: 3-node chain, empty graph, single node, 2-node, disconnected (2 components).

API integration: `_enrich_graph_with_analytics()` at `website/api/routes.py` L106–127 adds `pagerank, community, betweenness, closeness` per node + `meta: {communities, components, computed_at}`.

Frontend: `website/features/knowledge_graph/js/app.js` L212, L232, L265–266, L331–332 implements `baseRadius = 2 + (node.pagerank / _maxPagerank) * 4` — matches spec exactly.

#### Missing or Divergent Features

1. **File path deviation** — spec says `website/core/supabase_kg/analytics.py`; actual at `website/features/kg_features/analytics.py`. Cosmetic.
2. **Node `tags` attribute dropped** — spec's `_build_networkx_graph` stores `tags=node.tags`; impl only stores `name` + `group`. No downstream impact (no metric uses tags).
3. **Skip threshold differs** — spec says "Skip if < 3 nodes"; impl only short-circuits 0 and 1 nodes. A 2-node graph runs the full pipeline (works correctly; arguably more useful than spec).

#### Pros

1. **Every nx.* call matches spec parameters verbatim** — zero deviation in algorithmic params.
2. **Deterministic Louvain via seed=42** — prevents visual color flicker on frontend across cache refreshes.
3. **Robust graceful degradation** — try/except per-algorithm with zero-dict fallback exceeds spec requirements.
4. **Clean edge-case handling** — empty graph and single-node special-cased correctly.
5. **Correct undirected semantics** — `nx.Graph()` matches bidirectional KG link semantics.

#### Cons

1. **File path differs from spec** — imports all updated correctly, but integration docs referencing the spec path will be stale.
2. **Node `tags` attribute dropped** in `_build_networkx_graph` — minor info loss.
3. **No explicit numpy dependency validation** — if numpy is missing, try/except swallows ImportError and silently degrades.
4. **Single-node closeness returns 0.0** — potentially misleading (undefined, not zero).
5. **Loose skip threshold** — violates spec's stated "<3 nodes" rule even though behavior is fine.

---

### M4: NL Graph Query

**Status**: ❌ FAIL (one critical runtime bug + multiple spec divergences)
**File**: `website/features/kg_features/nl_query.py`
**Spec reference**: lines 755–853

#### What Was Expected (from spec)

- `NLQueryResult` Pydantic: question, sql, raw_result, answer, latency_ms, retries
- `NLQueryError(status_code, user_message)` exception
- System prompt with: full schema, **VALID source_type VALUES: youtube/github/reddit/substack/medium/generic**, DOMAIN VOCABULARY (9 mappings), RULES
- `_strip_sql_artifacts()`: regex to remove markdown fences
- **`_safety_check()`: SELECT-only allowlist** (`^\s*SELECT\b` regex) + semicolon rejection
- **EXPLAIN validation** via RPC on generated SQL (critical differentiator vs LangChain)
- Guided retry with COMMON_MISTAKES (5 items per spec) on EXPLAIN failure
- `execute_kg_query` RPC with **user_id enforcement**
- Python-side cap `[:50]`
- Error HTTP codes: 400 (safety/parse), 504 (timeout), 500 (generic, no PG error leak)
- API endpoint `POST /api/graph/query` with 5 req/min rate limit

#### What Was Found (in code)

`NLQueryResult` (L25–32) with all 6 fields ✅. `NLQueryError` (L35–41) with status_code + user_message ✅. System prompt (L55–108) contains schema + source_type list + domain vocabulary + 6 rules. `_strip_sql_artifacts` (L146–151) with regex `r"```(?:sql)?\s*\n?(.*?)\n?\s*```"` + `re.DOTALL`. `_safety_check` (L154–164) + `_UNSAFE_RE` (L140–143). `_COMMON_MISTAKES` (L121–134) with 4 items. Execute call (L208–211): `self._sb.rpc("execute_kg_query", {"query_text": sql})`. Result cap `raw_result = raw_result[:50]` at L242. Error codes: 504 timeout (L272), 500 generic (L275), 400 safety (L161, L164). API endpoint wired at `website/api/routes.py` L346 with `_QUERY_RATE_LIMIT = 5` (L334). Syntax check: `SYNTAX OK`.

**SQL function signature (`001_intelligence.sql` L431):**
```sql
CREATE OR REPLACE FUNCTION execute_kg_query(
    query_text  text,
    p_user_id   uuid        -- NOT NULL, no default
)
```

#### Missing or Divergent Features

| # | Critical? | Issue |
|---|-----------|-------|
| 1 | 🔴 CRITICAL | **RPC call missing `p_user_id` parameter.** Python passes `{"query_text": sql}` only; SQL requires both `query_text` AND `p_user_id`. Every call fails with "function does not exist" or "missing parameter". SQL function's user_id enforcement (L458–460: `IF NOT (trimmed_query ~* 'user_id\s*=\s*...')`) cannot even be reached. |
| 2 | ⚠️ HIGH | **Safety check is a DENYLIST, not allowlist.** `_UNSAFE_RE` blocks 9 mutation keywords but misses `COPY`, `DO`, `SET`, `CALL`, `COMMENT`, `VACUUM`, `ANALYZE`, `REINDEX`. Spec explicitly warns: "An allowlist is strictly more robust than a denylist". (Mitigated by SQL RPC's own allowlist, but Python layer diverges from spec.) |
| 3 | ⚠️ HIGH | **EXPLAIN validation step entirely absent.** No `EXPLAIN` calls anywhere in the file. Spec mandates pre-validation via `EXPLAIN {sql}` RPC before execution. Retry fires on execution failure instead of EXPLAIN failure. |
| 4 | ⚠️ MEDIUM | **source_type enum mismatch**: prompt lists `youtube, github, reddit, newsletter, web` vs spec's `youtube, github, reddit, substack, medium, generic`. Real KG data uses `ss-`/`md-` prefixes (substack/medium), so generated queries against production data will return empty sets. |
| 5 | ⚠️ MEDIUM | COMMON_MISTAKES has 4 items vs spec's 5; item 1 in code (`tags @> ARRAY['x']` flagged as wrong) **contradicts** spec (which lists `@>` as valid alternative). |
| 6 | ⚠️ MEDIUM | Generic 500 handler leaks raw PG error text: `f"Query failed: {exc}"` at L275. Spec explicitly says "no raw PG error leaked". |
| 7 | ⚠️ MINOR | DOMAIN VOCABULARY has 3 short lines vs spec's 9 detailed semantic mappings (articles/videos/repos/newsletters/connections/topics/related/isolated). |

#### Pros

1. **Defense-in-depth result cap** — `raw_result[:50]` matches RPC's server-side `LIMIT 50`.
2. **Markdown fence stripping** — uses `re.DOTALL` to handle multi-line SQL.
3. **Guided retry loop** — DB exception → formatted retry prompt with `_COMMON_MISTAKES` → re-execute. `retries=1` surfaced in result.
4. **Async I/O hygiene** — Gemini calls wrapped in `asyncio.to_thread(...)` + `asyncio.wait_for(timeout=10.0)`.
5. **Clean exception semantics** — three distinct exit paths (NLQueryError pass-through, TimeoutError → 504, Exception → 500).

#### Cons

1. **🔴 SHOW-STOPPER: RPC call missing `p_user_id`** — every invocation fails at runtime. One-line fix at L210: add `"p_user_id": self._user_id` to rpc args dict.
2. **Denylist instead of allowlist** — violates spec's explicit security guidance. Denylist misses `COPY/DO/SET/CALL/COMMENT` etc.
3. **EXPLAIN pre-validation missing** — positioned as key differentiator vs LangChain (spec L768); completely absent. Retries only on execution failure.
4. **source_type enum mismatch with production data** — queries against real KG will silently return empty results for newsletter content.
5. **PG error leakage** — `f"Query failed: {exc}"` violates spec's "no raw PG error leaked" contract.

---

### M5: Graph Traversal RPCs

**Status**: ✅ PASS (minor spec divergences, all non-breaking)
**Files**: `supabase/website/kg_features/001_intelligence.sql` (L140–427) + `website/core/supabase_kg/repository.py` (L545–611)
**Spec reference**: lines 854–895

#### What Was Expected (from spec)

- 6 RPC functions: `find_neighbors`, `shortest_path`, `top_connected_nodes`, `isolated_nodes`, `top_tags`, `similar_nodes`
- All with `SECURITY DEFINER SET search_path = '' SET statement_timeout = '5s'`
- `find_neighbors`: recursive CTE with array-based cycle prevention
- `shortest_path`: recursive CTE BFS with `LIMIT 1`
- Python wrappers with depth caps: `find_neighbors: min(depth, 8)`, `shortest_path: min(max_depth, 10)`

#### What Was Found (in code)

All 6 SQL functions present at lines 142, 215, 280, 318, 354, 386. All 6 wrappers in `repository.py` at lines 545–611. All parameter names match between SQL and Python. Security hardening (SECURITY DEFINER + search_path + statement_timeout=5s) applied uniformly across all 9 functions in the migration.

#### Cross-Reference Table

| Function | SQL Params | Python rpc() Args | Match? | Security | Depth Cap |
|----------|-----------|-------------------|--------|----------|-----------|
| `find_neighbors` | `(p_user_id, p_node_id, p_depth DEFAULT 1)` | `{"p_user_id", "p_node_id", "p_depth": min(depth,8)}` | ✅ | SD+sp+5s | ✅ min(depth,8) |
| `shortest_path` | `(p_user_id, p_source_id, p_target_id, p_max_depth DEFAULT 5)` | `{"p_user_id", "p_source_id", "p_target_id", "p_max_depth": min(max_depth,10)}` | ✅ | SD+sp+5s | ✅ min(max_depth,10) |
| `top_connected_nodes` | `(p_user_id, p_limit DEFAULT 10)` | `{"p_user_id", "p_limit"}` | ✅ | SD+sp+5s | n/a |
| `isolated_nodes` | `(p_user_id)` | `{"p_user_id"}` | ✅ | SD+sp+5s | n/a |
| `top_tags` | `(p_user_id, p_limit DEFAULT 20)` | `{"p_user_id", "p_limit"}` | ✅ | SD+sp+5s | n/a |
| `similar_nodes` | `(p_user_id, p_node_id, p_limit DEFAULT 10)` | `{"p_user_id", "p_node_id", "p_limit"}` | ✅ | SD+sp+5s | n/a |

**find_neighbors cycle prevention verified:**
```sql
-- base case seeds path array
SELECT n.id, ..., 0 AS depth, ARRAY[n.id] AS path
-- recursive case appends and checks membership
SELECT ..., nb.depth + 1, nb.path || n2.id
WHERE nb.depth < p_depth
  AND NOT (n2.id = ANY(nb.path))   -- ✅ array-based cycle guard
```

**shortest_path BFS + LIMIT 1 verified:**
```sql
SELECT bfs.path, bfs.depth FROM bfs
WHERE bfs.current_node = p_target_id
ORDER BY bfs.depth
LIMIT 1;
```

#### Missing or Divergent Features

| # | Impact | Issue |
|---|--------|-------|
| 1 | LOW | `find_neighbors` SQL `p_depth DEFAULT 1`, spec says `DEFAULT 2`. Masked: Python always passes depth. |
| 2 | LOW | `shortest_path` SQL `p_max_depth DEFAULT 5`, spec says `DEFAULT 10`. Masked. |
| 3 | LOW | `top_connected_nodes` SQL `p_limit DEFAULT 10`, spec says `DEFAULT 20`. Masked. |
| 4 | MEDIUM | `find_neighbors` return columns: SQL returns `(node_id, name, source_type, depth, path)`; spec specified additional `summary, tags, url`. Consumers need second fetch to hydrate. |
| 5 | LOW | `isolated_nodes` missing `node_date DATE` return column; ordering uses `created_at DESC` not `node_date DESC`. |
| 6 | LOW | `top_tags` missing `node_count BIGINT` return column. |
| 7 | LOW | SQL uses `LANGUAGE plpgsql` with BEGIN/END wrapper; spec specified `LANGUAGE sql STABLE`. Loses planner volatility hint and adds minor overhead. |
| 8 | LOW | Python wrapper names drift: `top_connected` (not `top_connected_nodes`), `similar_by_tags` (not `similar_nodes`). Only RPC string matters at runtime. |

#### Pros

1. **Security hardening is textbook-perfect** — every function has `SECURITY DEFINER`, `search_path=''`, `statement_timeout='5s'`, `REVOKE FROM PUBLIC`, scoped `GRANT`.
2. **Runaway-recursion defense in depth** — triple-guarded: 5s DB timeout + Python-side depth caps + CTE `WHERE depth < p_depth`.
3. **Parameter names perfectly aligned** — all 6 wrappers match SQL keyword-arg names. No runtime RPC failures.
4. **Cycle prevention via array membership** — `NOT (id = ANY(path))` in both recursive CTEs.
5. **Graceful failure mode** — every wrapper try/except with logger.warning and safe empty default.

#### Cons

1. **`LANGUAGE plpgsql` instead of `LANGUAGE sql STABLE`** — loses STABLE volatility marker that could benefit planner caching for read-only queries.
2. **Missing return columns** — `find_neighbors` lacks summary/tags/url; `isolated_nodes` lacks node_date; `top_tags` lacks node_count. Forces consumer round-trips.
3. **SQL defaults contradict spec** — `find_neighbors` 1 vs 2, `shortest_path` 5 vs 10, `top_connected_nodes` 10 vs 20. Hidden footgun if external callers invoke without explicit args.
4. **`shortest_path` doesn't validate `p_source_id` ownership** — nonexistent source silently returns empty rather than explicit error.
5. **Wrapper naming inconsistency** — `top_connected` / `similar_by_tags` drift from SQL names, harms grep-ability.

---

### M6: Hybrid Retrieval

**Status**: ❌ FAIL (three critical runtime bugs + spec-SQL drift)
**File**: `website/features/kg_features/retrieval.py`
**SQL**: `supabase/website/kg_features/001_intelligence.sql` L477–582
**Spec reference**: lines 897–936

#### What Was Expected (from spec)

- 3-stream RRF: semantic (pgvector cosine), fulltext (tsvector websearch_to_tsquery), graph (1-hop neighbors)
- Default weights: `semantic=0.5, fulltext=0.3, graph=0.2`
- `k=60` RRF constant
- `p_seed_node_id TEXT DEFAULT NULL` optional — graph stream skipped when null
- Python wrapper generates query embedding with `task_type='RETRIEVAL_QUERY'`
- Graceful fallback when embedding fails: fulltext+graph only with renormalized weights
- `POST /api/graph/search` API endpoint

#### What Was Found (in code)

**SQL `hybrid_kg_search` signature (L477–495):**
```sql
CREATE OR REPLACE FUNCTION hybrid_kg_search(
    query_text       text,
    query_embedding  vector(768) DEFAULT NULL,
    p_user_id        uuid        DEFAULT NULL,
    p_limit          int         DEFAULT 20,
    semantic_weight  float       DEFAULT 1.0,      -- ← spec: 0.5
    fulltext_weight  float       DEFAULT 1.0,      -- ← spec: 0.3
    graph_weight     float       DEFAULT 0.5,      -- ← spec: 0.2
    p_k              int         DEFAULT 60
)
RETURNS TABLE (
    node_id     text,          -- ← Python reads "id"
    name        text,
    source_type text,
    summary     text,
    tags        text[],
    url         text,
    rrf_score   float           -- ← Python reads "score"
)
```

**Python `hybrid_search` function (L40–142):** defaults `semantic_weight=0.5, fulltext_weight=0.3, graph_weight=0.2` ✅ (match spec, not SQL). Calls `generate_embedding(query, task_type="RETRIEVAL_QUERY")` (L83) ✅. Graceful fallback when embedding returns `[]` (L86–98) with renormalized ft+gr weights ✅. Syntax check: `SYNTAX OK`.

**Python rpc_params dict (L99–111):**
```python
rpc_params = {
    "p_user_id": user_id,
    "p_query_text": query,              # ← SQL expects "query_text"
    "p_query_embedding": query_embedding if query_embedding else None,   # ← SQL "query_embedding"
    "p_semantic_weight": sem_w,         # ← SQL "semantic_weight"
    "p_fulltext_weight": ft_w,          # ← SQL "fulltext_weight"
    "p_graph_weight": gr_w,             # ← SQL "graph_weight"
    "p_limit": limit,
}
if seed_node_id:
    rpc_params["p_seed_node_id"] = seed_node_id   # ← SQL has NO such parameter
```

**Python result mapping (L117–128):**
```python
HybridSearchResult(
    id=row.get("id", ""),               # ← SQL returns "node_id"
    ...
    score=float(row.get("score", 0.0))  # ← SQL returns "rrf_score"
)
```

**API endpoint `POST /api/graph/search`** wired at `website/api/routes.py` L376 ✅.

#### Missing or Divergent Features

| # | Critical? | Issue |
|---|-----------|-------|
| 1 | 🔴 CRITICAL | **5 of 8 RPC parameter names mismatch SQL function.** Python sends `p_query_text, p_query_embedding, p_semantic_weight, p_fulltext_weight, p_graph_weight`; SQL expects `query_text, query_embedding, semantic_weight, fulltext_weight, graph_weight` (no `p_` prefix). PostgREST named-arg dispatch → function-not-found error. |
| 2 | 🔴 CRITICAL | **Return column names mismatch.** Python reads `row["id"]` and `row["score"]`; SQL returns `node_id` and `rrf_score`. Even if RPC call succeeded, every result would have `id=""` and `score=0.0`. |
| 3 | 🔴 CRITICAL | **`p_seed_node_id` sent but SQL has no such parameter.** When frontend passes `seed_node_id` in request body, RPC call fails even more loudly. |
| 4 | ⚠️ MEDIUM | **Deployed SQL weight defaults violate spec** (1.0/1.0/0.5 vs 0.5/0.3/0.2). Low impact because Python overrides, but dangerous for other callers. |
| 5 | ⚠️ MEDIUM | **Graph stream semantics changed.** Spec promises `p_seed_node_id`-driven expansion; deployed SQL auto-expands from top-5 semantic hits (`WHERE s.rank <= 5`). When embedding fails (fallback path), graph stream becomes empty — contradicts Python fallback's assumption. |
| 6 | ⚠️ LOW | No integration test caught this — `test_hybrid_retrieval.py` doesn't exist. |

#### Pros

1. **Python wrapper has excellent graceful-degradation logic** — weight normalization, empty-embedding fallback with renormalization, exception catch, per-row malformed-result tolerance.
2. **SQL RRF formula is mathematically correct** — classic Cormack et al. `1/(k+rank) * weight` summed via `UNION ALL + GROUP BY`.
3. **SQL uses `ts_rank_cd`** (cover density) which is more sophisticated than spec's `ts_rank`, plus `websearch_to_tsquery` handles natural-language operators.
4. **Python wrapper defaults match spec** (0.5/0.3/0.2).
5. **API endpoint fully wired** — rate limiting + Supabase guard + auth-aware user_id.
6. **Indexes present** — IVFFlat on embedding + GIN on fts.

#### Cons

1. **🔴 SHOW-STOPPER: 5 RPC param names mismatch SQL** — every call fails. Fix: strip `p_` prefix from `p_query_text`, `p_query_embedding`, `p_semantic_weight`, `p_fulltext_weight`, `p_graph_weight` in L102–108.
2. **🔴 SHOW-STOPPER: Return column names mismatch** — Fix: change `row.get("id")` → `row.get("node_id")` and `row.get("score")` → `row.get("rrf_score")` at L120, L126.
3. **🔴 SHOW-STOPPER: `p_seed_node_id` does not exist in SQL** — either add to SQL function or remove from Python.
4. **Spec drift uncommunicated** — SQL and Python wrappers written against different contracts; no one reconciled.
5. **Deployed SQL weight defaults violate spec** — any direct SQL caller gets wrong behavior.
6. **Graph stream auto-seed semantics silently changed** — if embedding fails, graph stream becomes empty, defeating fallback's intent.

---

## Schema Migration Verification

**File**: `C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\supabase\website\kg_features\001_intelligence.sql` (614 lines)
**Plan expected location**: `supabase/website/kg_public/002_add_intelligence.sql` (path differs)

| Feature | Expected | Actual | Status |
|---------|----------|--------|--------|
| `CREATE EXTENSION IF NOT EXISTS vector` | Required | L9 ✓ | ✅ |
| `kg_nodes.embedding vector(768)` | Required | L12 ✓ | ✅ |
| pgvector index | Spec: "defer HNSW" | IVFFlat lists=100 L15-16 | ⚠️ DIVERGENCE |
| `kg_links.weight INT 1-10` | DEFAULT NULL per spec | DEFAULT 5 L23 | ⚠️ |
| `kg_links.link_type TEXT` | `tag/semantic/entity` | Present L25 ✓ | ✅ |
| `kg_links.description TEXT` | Required | Present L26 ✓ | ✅ |
| `kg_nodes.fts tsvector GENERATED` | `coalesce(name) \|\| coalesce(summary)` | Weighted `setweight(A=name, B=summary, C=tags)` L37-43 | ⚠️ RICHER THAN SPEC |
| GIN index on fts | Required | Present L45-46 ✓ | ✅ |
| `kg_graph_view` updated | weight/link_type/description | Present L53-91 ✓ | ✅ |
| `match_kg_nodes` RPC | Semantic search | L98 ✓ | ✅ |
| `find_neighbors` RPC | Recursive CTE | L142 ✓ | ✅ |
| `shortest_path` RPC | BFS LIMIT 1 | L215 ✓ | ✅ |
| `top_connected_nodes` RPC | Degree ranking | L280 ✓ | ✅ |
| `isolated_nodes` RPC | Zero-degree | L318 ✓ | ✅ |
| `top_tags` RPC | Tag frequency | L354 ✓ | ✅ |
| `similar_nodes` RPC | Tag overlap | L386 ✓ | ✅ |
| `execute_kg_query` RPC | NL-query exec | L431 ✓ | ✅ |
| `hybrid_kg_search` RPC | 3-stream RRF | L477 ✓ | ✅ |
| `SECURITY DEFINER` on all | Required | ✓ all 9 | ✅ |
| `SET search_path = ''` on all | Required | ✓ all 9 | ✅ |
| `SET statement_timeout='5s'` | Required | ✓ all 9 | ✅ |
| REVOKE ALL FROM PUBLIC | All 9 | L588-596 ✓ | ✅ |
| GRANT EXECUTE | authenticated+service_role | L598-606 ✓ | ⚠️ execute_kg_query granted to authenticated too (spec: service_role only) |
| `LANGUAGE sql STABLE` for M5 | Spec requirement | All use `LANGUAGE plpgsql` | ⚠️ DIVERGENCE |
| `hybrid_kg_search` weights | 0.5/0.3/0.2 | 1.0/1.0/0.5 | ❌ SPEC VIOLATION |
| `hybrid_kg_search` params | `query_text, query_embedding, semantic_weight...` | matches spec signature; BUT Python wrapper uses wrong names | ❌ INTEGRATION BREAK |
| `hybrid_kg_search` return cols | `id, score` per spec | `node_id, rrf_score` | ❌ INTEGRATION BREAK |

---

## API Routes Verification

**File**: `C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\website\api\routes.py`

| Endpoint | Expected | Actual | Status |
|----------|----------|--------|--------|
| `GET /api/graph` enriched with analytics | pagerank, community, betweenness, closeness per node | `_enrich_graph_with_analytics()` L106-127 ✓ | ✅ |
| `POST /api/graph/query` | NL query, 5/min rate limit | L346, `_QUERY_RATE_LIMIT = 5` L334 ✓ | ✅ |
| `POST /api/graph/search` | Hybrid retrieval | L376 ✓ | ✅ (but M6 is broken internally) |
| `POST /api/summarize` | Embedding gen + entity extraction | L458-499 ✓ | ⚠️ no semantic link creation |
| `/api/summarize` embedding storage | Via KGNodeCreate field | Via direct UPDATE (workaround) | ⚠️ |
| `/api/summarize` entity task | asyncio.create_task fire-and-forget | L482 ✓ | ✅ |

---

## Frontend Verification

**File**: `C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\website\features\knowledge_graph\js\app.js`

| Feature | Expected | Actual | Status |
|---------|----------|--------|--------|
| PageRank-based node sizing | `baseRadius = 2 + (pagerank/max) * 4` | L265-266, L331-332 ✓ | ✅ |
| `_maxPagerank` tracking | Required | L212, L232 ✓ | ✅ |
| In-place node updates (flicker fix) | Not in M3 spec, but present | Observed 2026-04-01 | ✅ |

---

## Design Spec Compliance Summary

**Total spec features checked**: ~85 individual items across M1–M6 + schema + integration.

| Category | Passing | Divergent | Missing | Broken |
|----------|---------|-----------|---------|--------|
| Architecture (zero LangChain/Neo4j, deps) | 3 | 1 (file paths) | 0 | 0 |
| Schema migration | 12 | 6 | 0 | 0 |
| M1 Entity Extraction | 10 | 5 | 2 (few-shot, existing_types) | 0 |
| M2 Semantic Embeddings | 6 | 1 (threshold) | 1 (_semantic_link) | **2 (output_dim, RPC param)** |
| M3 Graph Analytics | 10 | 2 | 0 | 0 |
| M4 NL Graph Query | 7 | 4 | 2 (EXPLAIN, allowlist) | **1 (p_user_id)** |
| M5 Graph Traversal RPCs | 10 | 5 | 0 | 0 |
| M6 Hybrid Retrieval | 6 | 2 | 0 | **3 (params, cols, p_seed)** |
| API routes integration | 5 | 1 | 0 | 0 |
| Frontend PageRank | 2 | 0 | 0 | 0 |
| **TOTALS** | **71** | **27** | **5** | **6** |

**Weighted completeness**: ~65% (passing+divergent where divergence is non-breaking counted as 0.5).

### Top Critical Spec Violations

1. 🔴 **M2**: `output_dimensionality=768` not passed to Gemini → 3072-dim vectors fail pgvector insert.
2. 🔴 **M2**: `match_user_id` vs `target_user_id` RPC param mismatch → semantic search broken.
3. 🔴 **M4**: `execute_kg_query` RPC call missing required `p_user_id` → NL query broken.
4. 🔴 **M6**: 5 RPC param names have `p_` prefix but SQL function doesn't → hybrid search broken.
5. 🔴 **M6**: Return columns `id`/`score` read instead of `node_id`/`rrf_score` → empty results even if RPC succeeded.
6. 🔴 **M6**: `p_seed_node_id` sent to SQL function that doesn't accept it.
7. ⚠️ **M4**: EXPLAIN pre-validation entirely absent (spec's key LangChain differentiator).
8. ⚠️ **M4**: Safety check is denylist, not allowlist (spec explicitly warns against this).
9. ⚠️ **M1**: Gleaning is single-shot, not multi-turn GraphRAG conversation.
10. ⚠️ **M1**: Few-shot example absent from Step 1 prompt.

---

## Implementation Plan Compliance Summary

**Plan**: `docs/superpowers/plans/2026-03-30-kg-intelligence.md`
**File Map tracked items**: ~19

### Existence

| File | Expected Path (plan) | Actual Location | Exists? |
|------|---------------------|-----------------|---------|
| Schema migration | `supabase/website/kg_public/002_add_intelligence.sql` | `supabase/website/kg_features/001_intelligence.sql` | ✅ (different path) |
| `__init__.py` (kg_features) | `website/core/supabase_kg/` | `website/features/kg_features/` | ✅ (different path, minimal content) |
| `embeddings.py` | `website/core/supabase_kg/` | `website/features/kg_features/` | ✅ |
| `analytics.py` | `website/core/supabase_kg/` | `website/features/kg_features/` | ✅ |
| `entity_extractor.py` | `website/core/supabase_kg/` | `website/features/kg_features/` | ✅ |
| `nl_query.py` | `website/core/supabase_kg/` | `website/features/kg_features/` | ✅ |
| `retrieval.py` | `website/core/supabase_kg/` | `website/features/kg_features/` | ✅ |
| `repository.py` (modifications) | 6 RPC wrappers + `_semantic_link` + add_node embedding | 6 RPC wrappers ✓, **no `_semantic_link`**, **add_node has no embedding param** | ⚠️ PARTIAL |
| `models.py` (modifications) | Add embedding/weight/link_type/description fields | **None added** | ❌ MISSING |
| `supabase_kg/__init__.py` (exports) | Export new modules | **Not updated** | ❌ MISSING |
| `routes.py` (modifications) | /api/graph enrichment, query endpoint, search endpoint, summarize integration | All present | ✅ |
| `app.js` (PageRank sizing) | Frontend | Present | ✅ |
| `ops/requirements.txt` | networkx>=3.2, numpy>=1.26 | Present L40, L43 | ✅ |
| `scripts/backfill_embeddings.py` | One-time backfill | **Does not exist** | ❌ MISSING |

### Test Files (all 6 missing — 20 tests total)

| File | Expected Tests | Exists? |
|------|----------------|---------|
| `tests/test_embeddings.py` | 3 | ❌ |
| `tests/test_analytics.py` | 3 | ❌ |
| `tests/test_entity_extractor.py` | 3 | ❌ |
| `tests/test_nl_query.py` | 5 | ❌ |
| `tests/test_graph_rpcs.py` | 3 | ❌ |
| `tests/test_hybrid_retrieval.py` | 3 | ❌ |

**Tests written: 0 of 20.** Violates TDD workflow described in the plan.

### Plan Task Completion

| Category | Completion |
|----------|-----------|
| SQL migration | 100% (location differs; 1 weight/permission drift) |
| Python intelligence modules (5 files exist) | 100% functional skeleton (but integration bugs) |
| Repository modifications | ~60% (RPCs done, `_semantic_link` + `add_node` embedding support missing) |
| Models modifications | 0% (no field additions) |
| API routes integration | 100% |
| Frontend PageRank sizing | 100% |
| Requirements | 100% |
| `__init__.py` exports | 0% |
| Backfill script | 0% |
| Test suite | 0% |

**Overall plan task completion: ~65%**

---

## Test File Status

All 6 test files listed in the plan are **missing**. No unit tests were written for the KG Intelligence Layer. This is the single largest gap — it prevented the integration bugs (M2, M4, M6 RPC parameter mismatches) from being caught before merge. Had even one of the 20 planned tests actually executed against a real Supabase instance, every broken integration would have surfaced immediately.

---

## Recommendations

### Priority 1 — Critical runtime bugs (must fix before M2/M4/M6 are usable)

1. **`embeddings.py` L67 & L114**: add `"output_dimensionality": 768` to the config dict passed to `client.models.embed_content`.
2. **`embeddings.py` L168**: rename `"match_user_id"` → `"target_user_id"` in the `match_kg_nodes` RPC args.
3. **`nl_query.py` L210 & L237**: add `"p_user_id": self._user_id` to the `execute_kg_query` RPC args dict. Requires storing `user_id` on the `NLGraphQuery` instance (constructor).
4. **`retrieval.py` L102–108**: strip `p_` prefix from `p_query_text`, `p_query_embedding`, `p_semantic_weight`, `p_fulltext_weight`, `p_graph_weight`.
5. **`retrieval.py` L120 & L126**: change `row.get("id", "")` → `row.get("node_id", "")` and `row.get("score", 0.0)` → `row.get("rrf_score", 0.0)`.
6. **`retrieval.py` L110–111 OR SQL migration**: either remove `p_seed_node_id` from Python rpc_params OR add `p_seed_node_id TEXT DEFAULT NULL` parameter to `hybrid_kg_search` SQL function + wire graph stream to use it when present.

### Priority 2 — Spec divergences that should be reconciled

7. **`nl_query.py` L154**: replace denylist `_UNSAFE_RE` with SELECT-only allowlist `re.match(r'^\s*SELECT\b', sql.strip(), re.IGNORECASE)`.
8. **`nl_query.py`**: implement EXPLAIN pre-validation step — call an `explain_kg_query` RPC (not currently defined) before `execute_kg_query`, retry once on EXPLAIN failure.
9. **`nl_query.py` system prompt**: fix source_type enum to `'youtube', 'github', 'reddit', 'substack', 'medium', 'generic'` to match production KG node data.
10. **`nl_query.py` L275**: replace `f"Query failed: {exc}"` with generic "Query execution failed" to avoid leaking PG error text.
11. **`entity_extractor.py` L61–68**: add `PATTERN`, `ALGORITHM` entity types and `INSPIRED_BY` relationship type per spec.
12. **`entity_extractor.py` L86–104**: add domain-specific few-shot example (React/Meta/Andrew Clark per spec L475–485).
13. **`entity_extractor.py`**: refactor gleaning loop to use true multi-turn conversation via `contents=[...messages...]`.
14. **SQL migration**: update `hybrid_kg_search` weight defaults to spec values (0.5/0.3/0.2) for direct callers.
15. **`repository.py`**: add `_semantic_link()` method and call it after node creation in `/api/summarize` when similarity > 0.75.

### Priority 3 — Test coverage

16. **Write all 20 planned tests.** Start with integration tests hitting real Supabase — these would have caught every P1 bug immediately.
17. **Add CI step**: run integration tests on PR merge to prevent contract drift between Python and SQL.

### Priority 4 — Polish

18. **Rename Python wrappers**: `top_connected` → `top_connected_nodes`, `similar_by_tags` → `similar_nodes` to match SQL function names for grep-ability.
19. **Update SQL migration header comment** (L18) to remove `text-embedding-004` reference.
20. **Update plan doc** or move migration file to `supabase/website/kg_public/` to match plan path.
21. **Restrict `execute_kg_query` GRANT** to `service_role` only per spec.
22. **Convert M5 functions from `LANGUAGE plpgsql` to `LANGUAGE sql STABLE`** for planner optimization.

---

## File Path Reference

- Spec: `docs/superpowers/specs/2026-03-30-kg-intelligence-design.md`
- Plan: `docs/superpowers/plans/2026-03-30-kg-intelligence.md`
- Migration: `supabase/website/kg_features/001_intelligence.sql`
- M1: `website/features/kg_features/entity_extractor.py`
- M2: `website/features/kg_features/embeddings.py`
- M3: `website/features/kg_features/analytics.py`
- M4: `website/features/kg_features/nl_query.py`
- M6: `website/features/kg_features/retrieval.py`
- Repository: `website/core/supabase_kg/repository.py`
- Models: `website/core/supabase_kg/models.py`
- API: `website/api/routes.py`
- Frontend: `website/features/knowledge_graph/js/app.js`
- Requirements: `ops/requirements.txt`

---

**End of Report.**
