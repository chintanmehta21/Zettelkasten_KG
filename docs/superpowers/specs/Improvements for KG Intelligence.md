# Targeted Improvements for KG Intelligence Layer Design (M1–M6)

## Overview

This report reviews the "KG Intelligence Layer — Native Design Spec" and proposes concrete, module-by-module improvements to robustness, performance, observability, and extensibility. The focus is on low-level implementation and configuration changes rather than generic best practices. External research on community detection performance, pgvector indexing, and reciprocal rank fusion informs several of the recommendations.[^1][^2][^3][^4][^5]

[^1]

## Global / Cross-Cutting Improvements

### Configuration and Feature Flags

- Introduce a single `kg_intel` config object (e.g., `kg_intel.yaml` or environment-backed settings class) controlling thresholds and flags such as `dedup_similarity_threshold`, `semantic_match_threshold`, `max_gleanings`, `graph_weight`, and RRF `k`. This avoids hard-coded values across modules and supports iterative tuning without code changes.[^1]
- Add per-user or per-tenant overrides for heavy features like M1 gleaning, NL query, and M6 hybrid retrieval to throttle cost-sensitive users or run A/B tests.[^1]

### Observability and Metrics

- Standardize structured logging for each LLM and RPC call, including: latency, status (success/timeout/error), token counts (approximate), and truncated prompts. This will make it easier to correlate cost and latency regressions with specific modules.[^1]
- Add minimal counters/gauges (via OpenTelemetry or a lightweight in-process metrics registry) for: number of semantic links created, distribution of link weights, number of hybrid-search calls, and RPC error rates.[^1]

### Backpressure and Rate Limiting

- Reuse the existing rate limit helper but add independent buckets for: entity extraction, embeddings, NL query, and hybrid search. This prevents a single heavy client from saturating Gemini calls across modules.[^1]
- Add a bounded work queue for expensive background work (e.g., backfill embeddings, heavy gleaning runs) with a simple policy: drop oldest or skip new work when the queue is saturated, returning a soft warning to the user instead of blocking the main path.[^1]

## Module M1: Entity-Relationship Extraction

### Prompt and Schema Robustness

- Explicitly instruct the model to re-use entity identifiers and canonicalize name variants within the prompt, not just in post-processing, for example: "If multiple phrases refer to the same entity (e.g., 'JS' and 'JavaScript'), choose a single canonical name and use it consistently for all relationships." This reduces dedup work and improves consistency of descriptions.[^1]
- Extend the schema to include an optional `confidence: float` field per entity and relationship. Downstream, only persist links above a configurable confidence threshold and log or store low-confidence results separately for inspection.[^1]

### Gleaning and Cost Control

- Make `max_gleanings` adaptive: start at 1, but if the first extraction already returns a high count of entities and relationships, skip the gleaning pass for that document to save tokens and latency. A simple heuristic is to skip when entity count exceeds a configurable ceiling (e.g., 25–30 entities).[^1]
- Track per-document extraction latency and use it to dynamically disable gleaning for very long or slow documents in subsequent calls (e.g., when p95 extraction latency exceeds 6–7 seconds).[^1]

### Dedup and Entity Resolution

- Cache embeddings of frequent entity names in memory for the lifetime of the process to avoid re-embedding common entities like "Python", "React", or "PostgreSQL" during dedup. Use a small LRU cache keyed by normalized id.[^1]
- When using embedding-based deduplication, incorporate type into the similarity decision: only auto-merge entities when both cosine similarity exceeds the threshold and types match (case-insensitive). This avoids accidental merging of conceptually similar but distinct types (e.g., "React" as Technology vs "React team" as Organization).[^1]

### Cross-Node Entity Linking

- Introduce a small cap on entity-based links per node (e.g., at most N entity links created per summary) to avoid a combinatorial explosion when a document mentions many entities that already exist elsewhere in the graph.[^1]
- Add a follow-up batch task (driven by the embeddings backfill script) that periodically scans for popular entities and creates or updates cross-node entity links in controlled batches instead of doing all cross-node linking inside the request path.[^1]

## Module M2: Semantic Embeddings (pgvector)

### Embedding Model and Versioning

- Store both `embedding_model` and `embedding_task_type` in the node metadata (`metadata.embedding_model`, `metadata.embedding_task`) to support future migrations that may separate query and document spaces.[^1]
- Add an internal migration helper that can re-embed all nodes when the model changes, using `generate_embeddings_batch` and writing a lightweight checkpoint marker after each batch to allow safe restarts.[^1]

### Indexing Strategy

- Plan a staged rollout for pgvector indexing: keep sequential scan for small graphs, then introduce IVFFlat or HNSW when node counts exceed specific thresholds (e.g., IVFFlat at 10–30k vectors, HNSW near or beyond 50k, where benchmarks show HNSW gains in QPS and latency).[^6][^7][^8]
- Define index-creation migrations ahead of time but keep them commented or guarded by feature flags. When switching to HNSW, ensure `hnsw.ef_search` is set to a reasonable range (e.g., 80–120) for better recall-latency trade-offs.[^7][^6]

### Similarity Thresholds and Link Creation

- Make `match_threshold` in `match_kg_nodes` dynamic based on observed similarity distributions: start with 0.75, then log similarity scores for auto-links and adjust down (e.g., 0.70) or up (0.80+) per user based on measured noise vs coverage.[^1]
- Replace pure thresholding with "top-K + floor" in `_semantic_link` as hinted in the spec: for each node, create semantic links only to the best K similar nodes above a minimum floor (e.g., K=5, floor 0.70) to avoid over-linking on popular topics while still promoting strong edges.[^1]

### Failure Handling and Degradation

- On repeated 429s from the embedding model, set a short-lived in-memory circuit-breaker flag that disables new embeddings for a window (e.g., 60–120 seconds), allowing the pipeline to continue without embedding work instead of hammering the API.[^1]
- If embeddings are unavailable for a node, write an explicit metadata flag (e.g., `metadata.has_embedding=false`) to distinguish between "not yet processed" and "permanent failure" and avoid repeated backfill attempts for permanently failing records.[^1]

## Module M3: Graph Intelligence (NetworkX)

### Algorithm Choices and Parameters

- Expose Louvain `resolution` and `threshold` parameters via configuration to allow tuning community granularity without code changes. For example, start at `resolution=1.0` and `threshold=1e-7`, but be prepared to lower resolution if communities are too fragmented.[^9][^10]
- Consider switching from exact betweenness centrality to approximate variants using node sampling (the `k` parameter) for graphs that approach thousands of nodes, where full betweenness can become costly. Persist `k` in metrics metadata for debug visibility.[^3][^9]

### Stability and Determinism

- Set the random seed in Louvain (`seed` argument) for deterministic community assignments across cache refreshes, which will reduce visual "flicker" when community IDs change between runs on nearly identical graphs.[^9]
- Normalize community IDs to a compact, stable ordering (e.g., sort communities by size and assign IDs sequentially) before sending them to the frontend to avoid label reordering when new nodes appear.[^1]

### Performance and Memory

- Add a simple guard in `_build_networkx_graph` to skip edges whose endpoints no longer exist in the node set (e.g., due to inconsistent data or partial cache invalidation) to prevent NetworkX from materializing orphan nodes and bloating memory.[^1]
- For larger graphs, consider moving analytics computation to a background task kicked off by explicit cache invalidation (e.g., after `POST /api/summarize`), then serving stale-but-reasonable metrics until the next analytics snapshot completes, rather than blocking the first GET /api/graph cache miss.[^3]

## Module M4: Natural Language Graph Query (Text-to-SQL)

### Safer SQL Generation and Validation

- Expand the mutation regex to catch `CREATE`, `ANALYZE`, `VACUUM`, and `CALL` in addition to the already-covered verbs, closing off more potential prompt-injection primitives.[^1]
- Add an explicit length and complexity budget for generated SQL (e.g., character limit and maximum number of joins), rejecting queries that exceed this in order to avoid pathologically complex plans that risk timeouts even if they pass `EXPLAIN`.[^1]

### User-Id Scoping and Flexibility

- Refine the user_id enforcement rule to also accept queries that use parameterized forms like `user_id IN ('<uuid>')` or `user_id = '<uuid>'::uuid`, by widening the regex to match both direct equality and IN-list patterns, while still defaulting to false-reject on uncertain cases.[^1]
- Include a short, LLM-generated explanation of the SQL in the response payload alongside the formatted natural-language answer, so advanced users can see how their question was translated and identify misalignments for future prompts.[^1]

### Error Feedback Loop

- When EXPLAIN fails, capture the error text (truncated) and add it to an internal "SQL correction" prompt that includes examples of common mistakes and how they were fixed, giving the retry a more guided correction path than just the raw error string.[^1]
- Log invalid queries and LLM outputs (with redaction of user-sensitive data) into a small corpus that can later be used to fine-tune prompts or drive adoption of a dedicated NL-to-SQL tool such as Vanna, which has been shown to improve SQL generation quality in PostgreSQL contexts.[^11][^12][^1]

## Module M5: Graph Traversal RPCs

### SQL and Recursion Safety

- For `find_neighbors` and `shortest_path`, add explicit caps on the maximum depth exposed to clients (e.g., max_depth <= 6–8) at both the RPC and API layers to prevent accidental or maliciously deep traversals, even with the existing `statement_timeout` safeguard.[^1]
- Include an early exit condition in the recursive CTE when row counts exceed a configured limit, short-circuiting expensive traversals and returning a partial but safe result with a flag indicating truncation.[^1]

### Indexing and Data Layout

- Ensure there are composite indexes on `(user_id, source_node_id)` and `(user_id, target_node_id)` for `kg_links`, and on `(user_id, id)` for `kg_nodes`, to keep recursive joins performant as link counts grow.[^1]
- Consider periodically clustering the `kg_links` table by one of these indexes when row counts are high, as this can measurably improve range-scan performance on large graphs according to PostgreSQL best practices.[^1]

### API Surface and Ergonomics

- Add an optional `relation_filter` parameter for `find_neighbors` and `similar_nodes` so that clients can request neighbors only through certain link types (`'semantic'`, `'tag'`, `'entity'`), yielding more interpretable results.[^1]
- Return simple summary metadata, such as total nodes visited or path length distribution, in addition to the main node/path results, to help users understand the shape of their traversals.[^1]

## Module M6: Hybrid Retrieval

### RRF Configuration and Diagnostics

- Expose RRF `k` and per-stream weights via configuration and log them for every call, confirming that the system is indeed using the canonical `k=60` baseline from the Reciprocal Rank Fusion literature while still allowing experimentation if needed.[^13][^12][^11]
- Include per-result diagnostics in the ranked output showing each stream's rank and contribution to the final RRF score, which is useful for debugging surprising rankings and for tuning stream weights.[^11]

### Stream Behavior and Fallbacks

- When no embeddings exist for any node, degrade gracefully to a pure full-text or graph-based ranking but still return an RRF-style score to keep the output format consistent.[^1]
- If the query embedding fails, set a flag in the response such as `semantic_disabled=true` and automatically fall back to full-text + graph fusion, so that clients do not have to implement special-case handling for embedding failures.[^1]

### Graph-Aware Boosting

- In addition to using direct 1-hop neighbors as a graph stream, optionally incorporate a small number of 2-hop neighbors with a lower weight, especially when `p_seed_node_id` is provided by the UI (e.g., "find related to this note" interactions). Use a separate RRF weight for 2-hop contributions to avoid overwhelming direct matches.[^1]
- Use community membership from M3 as an additional soft boost factor: nodes in the same Louvain community as a strong semantic or keyword match can receive a small multiplicative bonus to their RRF score, which often improves topical coherence of result sets.[^10][^9]

## Integration and Pipeline-Level Improvements

### Summarize Pipeline

- Introduce a small, configurable retry for embedding generation and entity extraction on transient network failures, with exponential backoff, but do not retry more than once to avoid impacting the 30-second budget.[^1]
- Persist a combined "enrichment version" marker in node metadata (e.g., `metadata.enrichment_version=1`) so that future schema or algorithmic changes can selectively reprocess only nodes created with older enrichment versions.[^1]

### GET /api/graph Response

- Include a `meta` section in the graph response summarizing analytics metadata such as `num_nodes`, `num_links`, `num_communities`, `num_components`, `metrics_computed_at`, and NetworkX parameters (e.g., `resolution`, `k` for betweenness sampling). This will aid both debugging and future UI enhancements.[^9][^1]
- Add a lightweight checksum or version number for the graph analytics snapshot so the frontend can tell when metrics have materially changed and, if desired, animate or re-layout accordingly.[^1]

## Conclusion

The existing design spec already captures a strong, framework-free blueprint for adding intelligence to the Supabase-backed KG across extraction, embeddings, analytics, NL query, traversal, and hybrid retrieval. The improvements proposed here focus on making each module more tunable, observable, and resilient under growth and real-world loads, grounded in established research on community detection, vector indexing, and hybrid ranking methods. Implemented iteratively, these changes should preserve the current performance envelope while giving ample room for experimentation and future scale.[^2][^4][^5][^8][^12][^6][^7][^13][^10][^3][^11][^9][^1]

---

## References

1. [2026-03-30-kg-intelligence-design.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/45240349/d9800410-64c5-4aee-af4e-3833d4f89801/2026-03-30-kg-intelligence-design.md) - # KG Intelligence Layer — Native Design Spec

**Date**: 2026-03-30
**Status**: Draft v4 — pending us...

2. [A high-performance evolutionary multiobjective community detection algorithm](https://link.springer.com/10.1007/s13278-025-01519-7) - Community detection in complex networks is fundamental across social, biological, and technological ...

3. [Performance Evaluation of Python Libraries for Community Detection on Large Social Network Graphs](http://ijcs.net/ijcs/index.php/ijcs/article/view/4019) - ...insights into these communities. Community detection can be performed using various libraries and...

4. [Faster unfolding of communities: speeding up the Louvain algorithm](https://arxiv.org/pdf/1503.01322.pdf) - ... modularity, but has been applied to a variety of methods. As such,
speeding up the Louvain algor...

5. [Accurate and Scalable Many-Node Simulation](https://arxiv.org/pdf/2401.09877.pdf) - Accurate performance estimation of future many-node machines is challenging
because it requires deta...

6. [IVFFlat vs HNSW in pgvector with text‑embedding‑3‑large. When is it worth switching?](https://www.reddit.com/r/Rag/comments/1pijk7q/ivfflat_vs_hnsw_in_pgvector_with/) - IVFFlat vs HNSW in pgvector with text‑embedding‑3‑large. When is it worth switching?

7. [pgvector optimization: HNSW vs IVFFlat for semantic search](https://www.linkedin.com/posts/alok-tapdiya-83867b2_postgresql-pgvector-vectorsearch-activity-7418676758490648576-4Kpi) - Which pgvector optimization gives you the BIGGEST performance win in real production RAG/search work...

8. [Ivfflat](https://pixion.co/blog/choosing-your-index-with-pg-vector-flat-vs-hnsw-vs-ivfflat) - Are you navigating the complex world of vector databases in Postgres? Explore PGVector and its index...

9. [louvain_partitions — NetworkX 3.6.1 documentation](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.community.louvain.louvain_partitions.html) - Louvain Community Detection Algorithm is a simple method to extract the community structure of a net...

10. [What is the Louvain Method?](https://www.puppygraph.com/blog/louvain) - The Louvain method works by iteratively improving modularity through local node movements and graph ...

11. [Reciprocal Rank Fusion (RRF) for Hybrid Search](https://apxml.com/courses/advanced-vector-search-llms/chapter-3-hybrid-search-approaches/rrf-fusion-algorithms) - Reciprocal Rank Fusion (RRF) offers an elegant solution that sidesteps the score normalization probl...

12. [Understanding Reciprocal Rank Fusion in Hybrid Search](https://glaforge.dev/posts/2026/02/10/advanced-rag-understanding-reciprocal-rank-fusion-in-hybrid-search/) - By setting k = 60 k=60 (the industry standard), RRF prioritizes consensus over individual outliers. ...

13. [Reciprocal Rank Fusion outperforms Condorcet and ...](https://cormack.uwaterloo.ca/cormacksigir09-rrf)
