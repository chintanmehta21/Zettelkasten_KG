# Supabase KG Migration — Full Design Spec

**Date:** 2026-03-29
**Status:** Ready for implementation
**Goal:** Migrate knowledge graph from file-based `graph.json` to Supabase, wire API routes, verify sub-2s load time.

## Context

- 26 nodes (25 real + 1 test) and 46 links in `website/knowledge_graph/content/graph.json`
- Schema SQL exists at `supabase/website_kg/schema.sql` (3 tables, indexes, RLS, views)
- Python client layer exists at `website/core/supabase_kg/` (client, models, repository — 57 tests passing)
- **No tables exist in Supabase yet** — schema must be applied first
- Frontend JS fetches `/api/graph` with fallback to `/kg/content/graph.json`
- Current `GET /api/graph` reads from `graph_store.get_graph()` (file-based in-memory singleton)

## Approach: Direct Data Migration + API Rewire

### Why NOT re-extract from URLs?

The graph.json already contains clean summaries, normalized tags, and curated connections. Re-processing 25 URLs through Gemini would:
- Burn API quota (25+ Gemini calls)
- Produce different summaries (non-deterministic)
- Take 5-10 minutes vs 5 seconds
- Risk extraction failures (YouTube IP blocks, Reddit rate limits)

**Decision:** Migrate existing graph.json data directly. The data is already high-quality.

## Step 1: Apply Schema to Supabase

Run `supabase/website_kg/schema.sql` in the Supabase SQL Editor. This creates:
- `kg_users` — user records (maps to Render auth)
- `kg_nodes` — knowledge graph nodes (composite PK: user_id + id)
- `kg_links` — edges between nodes (scoped to user)
- All indexes (GIN on tags, user+source, user+date, user+url, link source/target)
- RLS policies (per-user isolation + service-role bypass)
- Views: `kg_user_stats`, `kg_graph_view`

## Step 2: Migration Script

Create `scripts/migrate_graph_to_supabase.py`:

```
1. Read graph.json
2. Create default user: render_user_id="default-web-user", display_name="Web User"
3. For each node in graph.json:
   - Map group name to source_type (youtube→youtube, reddit→reddit, etc.)
   - Insert via repository.add_node() WITHOUT auto-link (we have curated links)
4. For each link in graph.json:
   - Insert via repository.add_link()
5. Verify: get_graph() returns same node/link count
```

**Key decisions:**
- Skip `_auto_link` during migration — the existing links are curated and better than auto-discovered ones
- Use `source_type` directly from group field (they match the CHECK constraint values)
- The test node `web-test-title` is included (can be deleted later)

## Step 3: Wire API Routes to Supabase

Modify `website/api/routes.py`:

**`GET /api/graph`:**
```python
# If Supabase configured, read from Supabase
# Else fall back to file-based graph_store
if is_supabase_configured():
    repo = KGRepository()
    user = repo.get_or_create_user("default-web-user")
    graph = repo.get_graph(user.id)
    return graph.model_dump()
else:
    return get_graph()
```

**`POST /api/summarize`:**
```python
# After summarization, write to both stores:
# 1. File store (always — backward compat)
# 2. Supabase (if configured)
add_node(...)  # existing file store
if is_supabase_configured():
    repo = KGRepository()
    user = repo.get_or_create_user("default-web-user")
    repo.add_node(user.id, KGNodeCreate(...))
```

**Fallback guarantee:** If `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` are not set, everything works exactly as before via `graph_store.py`.

## Step 4: Performance Target (< 2s)

The graph is tiny (26 nodes, 46 links). `get_graph()` makes 2 Supabase queries:
- `SELECT * FROM kg_nodes WHERE user_id = ? ORDER BY node_date DESC`
- `SELECT * FROM kg_links WHERE user_id = ?`

With indexes on `(user_id, node_date DESC)` and `(user_id, source_node_id)`, both queries scan < 100 rows. Expected latency: **50-200ms** depending on Supabase region.

**If needed (unlikely):** Cache the graph in memory with a 30-second TTL. But 26 rows doesn't warrant caching.

## Step 5: Multi-User Model

| Phase | Behavior |
|-------|----------|
| **Now** | Single default user `"default-web-user"` owns all data. No auth. |
| **Next** | Add auth middleware (Render auth or simple API key). Each user gets their own graph via `user_id` scoping. |
| **Later** | Frontend login flow. User sees only their graph. Can share graphs via public links. |

RLS policies are already in the schema for Phase 2/3. The Python layer already accepts `user_id` on every method.

## Files Changed

| File | Change |
|------|--------|
| `scripts/migrate_graph_to_supabase.py` | **New** — one-time migration script |
| `website/api/routes.py` | Wire `GET /api/graph` and `POST /api/summarize` to Supabase |
| `website/core/supabase_kg/repository.py` | Add `add_node_raw()` method for migration (skips auto-link) |
| `tests/test_supabase_kg.py` | Add tests for raw migration path |
| `tests/test_website.py` | Update API tests for Supabase fallback logic |

## Success Criteria

1. Tables exist in Supabase dashboard (kg_users, kg_nodes, kg_links)
2. 26 nodes and 46 links present in Supabase
3. `GET /api/graph` returns Supabase data when configured
4. `GET /api/graph` falls back to graph.json when Supabase not configured
5. Full graph loads in < 2 seconds (measured from API response time)
6. All existing tests pass + new migration tests pass
7. `POST /api/summarize` dual-writes to both stores
