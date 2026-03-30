# Supabase Knowledge Graph Integration — Design Spec

**Date:** 2026-03-29
**Status:** Approved
**Scope:** Set up Supabase schema and Python client for multi-user knowledge graph storage

## Context

The knowledge graph currently uses file-based JSON storage (`graph.json`) with an in-memory
cache (`graph_store.py`). This works for single-user/single-instance but won't scale to
multi-user scenarios. We need a hosted PostgreSQL backend (Supabase) for the KG data layer.

**Constraints:**
- User authentication lives on Render — Supabase only stores user references
- No migration of live data yet — this sets up the schema and client code only
- Must coexist with the current file-based system until migration

## Architecture

```
Render (Auth)                    Supabase (Data)
┌──────────────┐                ┌──────────────────────┐
│ User signs in │───render_id──▶│ kg_users              │
│ Gets token    │                │   ├─ render_user_id   │
└──────┬───────┘                │   └─ display_name     │
       │                        │                        │
       │ API call with          │ kg_nodes               │
       │ user context           │   ├─ (user_id, id) PK  │
       ▼                        │   ├─ tags TEXT[]        │
┌──────────────┐                │   └─ metadata JSONB    │
│ FastAPI app   │──supabase-py─▶│                        │
│ (website/)    │                │ kg_links               │
└──────────────┘                │   ├─ source/target FK  │
                                │   └─ relation          │
                                └──────────────────────┘
```

## Schema

### Table: `kg_users`
Maps Render auth users to KG-local records. No passwords, no sessions — just a foreign key
anchor for KG data ownership.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK, auto-generated |
| `render_user_id` | TEXT | UNIQUE NOT NULL — external ID from Render auth |
| `display_name` | TEXT | Nullable |
| `email` | TEXT | Nullable |
| `avatar_url` | TEXT | Nullable |
| `is_active` | BOOLEAN | DEFAULT true |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |
| `updated_at` | TIMESTAMPTZ | DEFAULT now() |

### Table: `kg_nodes`
Knowledge graph nodes. Composite PK `(user_id, id)` allows the same node slug across users.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT | Node slug (e.g., `yt-attention`) |
| `user_id` | UUID | FK → kg_users.id |
| `name` | TEXT | NOT NULL — display title |
| `source_type` | TEXT | NOT NULL — youtube, reddit, github, substack, medium, generic |
| `summary` | TEXT | AI-generated summary |
| `tags` | TEXT[] | DEFAULT '{}' — GIN-indexed for filtering |
| `url` | TEXT | NOT NULL — original source URL |
| `node_date` | DATE | Date of the content |
| `metadata` | JSONB | DEFAULT '{}' — extensible extra data |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |
| `updated_at` | TIMESTAMPTZ | DEFAULT now() |

**PK:** `(user_id, id)`

### Table: `kg_links`
Edges between nodes, scoped to a single user's graph.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK, auto-generated |
| `user_id` | UUID | FK → kg_users.id |
| `source_node_id` | TEXT | FK → kg_nodes.id (composite with user_id) |
| `target_node_id` | TEXT | FK → kg_nodes.id (composite with user_id) |
| `relation` | TEXT | NOT NULL — the shared tag that connects them |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |

**Unique constraint:** `(user_id, source_node_id, target_node_id, relation)`

### Indexes
- `kg_nodes(tags)` — GIN index for tag-based queries (`@>`, `&&` operators)
- `kg_nodes(user_id, source_type)` — filter by source type per user
- `kg_nodes(user_id, node_date DESC)` — date-ordered listing per user
- `kg_links(user_id, source_node_id)` — outgoing edge lookup
- `kg_links(user_id, target_node_id)` — incoming edge lookup

### Row-Level Security (RLS)
All three tables have RLS enabled. Policies use `auth.uid()` for Supabase JWT-based access
and service role bypasses RLS for server-side operations.

- **Select/Insert/Update/Delete:** `user_id = auth.uid()` (users see only their own data)
- Service role key bypasses RLS for admin operations (migration, bulk import)

### Views
- `kg_graph_view(user_id)` — returns `{nodes: [...], links: [...]}` structure matching
  the frontend's expected format
- `kg_node_stats` — aggregated counts per user (node count, link count, tag distribution)

## Python Client Layer

**Location:** `website/core/supabase_kg/` (alongside existing `graph_store.py`)
Note: The `supabase/` top-level folder holds only SQL/config — Python code lives under
`website/core/` to avoid shadowing the `supabase` pip package.

### `website/core/supabase_kg/client.py`
Lazy-initialized singleton using `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` env vars.
Returns a `supabase.Client` instance. `is_supabase_configured()` checks env vars without init.

### `website/core/supabase_kg/models.py`
Pydantic models: `KGUser`, `KGNode`, `KGNodeCreate`, `KGLink`, `KGLinkCreate`, `KGGraph`,
`KGGraphNode`, `KGGraphLink`. Mirror the DB schema and provide validation/serialization.

### `website/core/supabase_kg/repository.py`
CRUD operations class `KGRepository`:
- `get_or_create_user(render_user_id, display_name, email)` → KGUser
- `get_user_by_render_id(render_user_id)` → KGUser | None
- `add_node(user_id, node)` → KGNode (also auto-discovers and creates links)
- `get_graph(user_id)` → KGGraph (nodes + links)
- `delete_node(user_id, node_id)` → bool
- `node_exists(user_id, url)` → bool (dedup check)
- `search_nodes(user_id, query, tags, source_types)` → list[KGNode]
- `get_stats(user_id)` → dict

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes (for Supabase features) | Project URL (e.g., `https://xxx.supabase.co`) |
| `SUPABASE_ANON_KEY` | Yes | Public anon key (for client-side, RLS-protected access) |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Service role key (server-side, bypasses RLS) |

## Migration Strategy (future)
1. Deploy schema to Supabase (run `schema.sql`)
2. Create a default user for existing graph data
3. Run a one-time migration script to import `graph.json` → Supabase tables
4. Update `graph_store.py` to read/write from Supabase instead of JSON
5. Keep `graph.json` as a static fallback for offline/dev mode

## File Structure
```
supabase/                              # Top-level: SQL/config only (not a Python package)
└── website_kg/
    └── schema.sql                     — Full DDL (tables, indexes, RLS, views)

website/core/supabase_kg/             # Python package (avoids shadowing pip supabase)
├── __init__.py
├── client.py                          — Supabase client singleton
├── models.py                          — Pydantic models
└── repository.py                      — CRUD operations
```
