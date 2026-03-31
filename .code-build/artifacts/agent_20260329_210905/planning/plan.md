# Implementation Plan — Supabase KG Integration (Gap-Fill)

## Context
The Supabase KG integration is 90% complete. Schema, client, models, and repository all exist and match the design spec. Two gaps remain.

## Task 1: Add `kg_graph_view` to schema.sql
**File:** `supabase/website_kg/schema.sql`
**What:** Add a SQL view `kg_graph_view` that returns `{nodes: [...], links: [...]}` per user, matching the frontend format. The spec calls for this alongside the existing `kg_user_stats` view.
**Approach:** Use `json_build_object` + `json_agg` to build the structure in SQL. Accept `user_id` as a filter via the view's WHERE clause (RLS will scope it).

## Task 2: Write unit tests for supabase_kg
**File:** `tests/test_supabase_kg.py`
**What:** Test client.py, models.py, and repository.py with mocked Supabase calls.
**Coverage needed:**
- **client.py**: Test `get_supabase_client()` raises RuntimeError when env vars missing; `is_supabase_configured()` returns correct bool
- **models.py**: Test serialization/deserialization of all 8 models (round-trip)
- **repository.py**: Test all CRUD methods with mocked `supabase.Client.table()` chain:
  - `get_or_create_user` (existing user, new user)
  - `add_node` (with auto-link triggering)
  - `get_node`, `delete_node`, `node_exists`
  - `search_nodes` (with/without filters)
  - `add_link` (success + duplicate)
  - `get_graph`, `get_stats`
  - `_normalize_tag` (prefix stripping)
  - `_auto_link` (shared tags discovery)

## Task 3: Run existing test suite
Verify all 305+ existing tests still pass after changes.

## Parallel Groups
- Group A (independent): Task 1, Task 2
- Group B (depends on A): Task 3
