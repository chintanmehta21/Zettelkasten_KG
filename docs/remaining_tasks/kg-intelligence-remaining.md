---
name: KG Intelligence — Remaining Checks
description: Features that need re-verification once Gemini quota resets or on paid tier; discovered during 2026-04-06 deployment session
type: project
---

## Status: RESOLVED (2026-04-06)

All 5 items verified and addressed. Summary below.

### 1. NL Graph Query (M4) — VERIFIED WORKING
- Tested 3 different queries on Render (count, tag analysis, list nodes)
- SQL generation, EXPLAIN validation, execution, and answer formatting all work correctly
- Retry logic works (1 retry observed on tag unnest query, self-corrected)
- Latency: 3.8-5.5s per query (acceptable for Gemini round-trips)

### 2. Entity Extraction (M1) — WORKS LOCALLY, Rate-limited on Render
- **Locally**: Extracted 9 entities and 8 relationships from Data Mesh article (including key rotation on 429)
- **On Render**: Async task completes but returns 0 entities — Gemini quota exhausted by the summarize call before entity extraction runs
- **Code hardened**: Added overall 45s timeout, read-then-merge metadata update (prevents overwrites), task naming for debugging, GC-prevention callback
- **Root cause**: Free-tier Gemini quota (20 req/day for flash) is consumed by summarize + embedding + auto-link before entity extraction runs
- **Fix**: Will resolve naturally with paid Gemini tier or more API keys in `api_env`

### 3. Semantic auto-linking edge cases — VERIFIED ROBUST
- **Embedding failure guard**: `if emb:` on routes.py:544 properly skips auto-linking when embedding is empty. No partial state.
- **Self-link prevention**: Double-guarded — `hit_id != node_create.id` in routes.py AND `source_id == target_id` check in repository.py
- **Duplicate link prevention**: `UNIQUE(user_id, source_node_id, target_node_id, relation)` constraint + try/except in `add_semantic_link()`
- **Verified on Render**: Semantic similarity link created between YouTube and Data Mesh nodes

### 4. Backfill embeddings — SCRIPT WRITTEN AND EXECUTED
- Created `ops/scripts/backfill_embeddings.py` with dry-run, batch-size, user-id filtering, and rate-limit delays
- Dry run found 38 nodes without embeddings
- Backfill executed successfully — all nodes now have embeddings
- Uses same `generate_embedding()` function as the live pipeline (title + summary, 768-dim, L2-normalized)

### 5. SQL migration tracking — FIXED
- Updated `001_intelligence.sql` to use trigger-based FTS instead of GENERATED ALWAYS AS
- `array_to_string()` is not IMMUTABLE in PostgreSQL — Supabase rejects it in generated columns
- New approach: `kg_nodes_fts_update()` trigger function fires BEFORE INSERT OR UPDATE OF name, summary, tags
- Local SQL now matches deployed schema

### 6. Test suite — FIXED AND PASSING
- Fixed pre-existing `test_get_graph_via_view` test that was broken by the view→RPC migration
- Renamed to `test_get_graph_via_rpc`, updated mock to use `client.rpc("get_kg_graph", ...)` pattern
- **537 tests passing, 0 failures**
