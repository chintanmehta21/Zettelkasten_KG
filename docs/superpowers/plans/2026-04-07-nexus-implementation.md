# Nexus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an experimental Nexus feature that connects YouTube/GitHub/Reddit/Twitter accounts, imports artifacts, bulk-summarizes them, and stores resulting Zettels into the existing knowledge graph path.

**Architecture:** Add a new Nexus API router and experimental UI page, implement provider-specific native OAuth + ingestion modules under `website/experimental_features/nexus/source_ingest`, store encrypted provider tokens in Supabase, and reuse the same summarize-and-persist pipeline by extracting shared persistence logic from `/api/summarize`.

**Tech Stack:** FastAPI, Supabase, native OAuth (PKCE/state), google-genai (`gemini-2.5-flash-lite` for Nexus bulk), existing website KG repository and graph store, pytest.

**Spec:** `docs/superpowers/specs/2026-04-07-nexus-design.md`

---

## File Map

### Create

1. `website/api/nexus.py`
2. `website/experimental_features/nexus/index.html`
3. `website/experimental_features/nexus/css/nexus.css`
4. `website/experimental_features/nexus/js/nexus.js`
5. `website/experimental_features/nexus/source_ingest/__init__.py`
6. `website/experimental_features/nexus/source_ingest/common/__init__.py`
7. `website/experimental_features/nexus/source_ingest/common/models.py`
8. `website/experimental_features/nexus/source_ingest/common/oauth_state.py`
9. `website/experimental_features/nexus/source_ingest/youtube/__init__.py`
10. `website/experimental_features/nexus/source_ingest/youtube/oauth.py`
11. `website/experimental_features/nexus/source_ingest/youtube/ingest.py`
12. `website/experimental_features/nexus/source_ingest/github/__init__.py`
13. `website/experimental_features/nexus/source_ingest/github/oauth.py`
14. `website/experimental_features/nexus/source_ingest/github/ingest.py`
15. `website/experimental_features/nexus/source_ingest/reddit/__init__.py`
16. `website/experimental_features/nexus/source_ingest/reddit/oauth.py`
17. `website/experimental_features/nexus/source_ingest/reddit/ingest.py`
18. `website/experimental_features/nexus/source_ingest/twitter/__init__.py`
19. `website/experimental_features/nexus/source_ingest/twitter/oauth.py`
20. `website/experimental_features/nexus/source_ingest/twitter/ingest.py`
21. `website/experimental_features/nexus/service/__init__.py`
22. `website/experimental_features/nexus/service/token_store.py`
23. `website/experimental_features/nexus/service/persist.py`
24. `website/experimental_features/nexus/service/bulk_import.py`
25. `supabase/website/nexus/schema.sql`
26. `tests/test_nexus_api.py`
27. `tests/test_nexus_bulk_import.py`
28. `tests/test_nexus_token_store.py`
29. `tests/test_nexus_providers.py`

### Modify

1. `website/app.py`
2. `website/api/routes.py`
3. `website/features/user_home/index.html`
4. `website/features/user_home/js/home.js`
5. `website/features/user_home/css/home.css`
6. `website/features/user_zettels/index.html`
7. `website/features/user_zettels/js/user_zettels.js`
8. `website/features/user_zettels/css/user_zettels.css`
9. `website/core/graph_store.py`
10. `website/core/supabase_kg/models.py`
11. `website/core/supabase_kg/repository.py`
12. `supabase/website/kg_public/schema.sql` (source type check update only if needed)
13. `telegram_bot/models/capture.py` (only if introducing explicit `twitter` source type)
14. `website/features/knowledge_graph/js/app.js` (only if introducing explicit `twitter` source color/filter)
15. `ops/requirements.txt` (only if crypto dependency is missing)

---

### Task 1: Scaffold Nexus route and static page

**Files:**
- Modify: `website/app.py`
- Create: `website/experimental_features/nexus/index.html`
- Create: `website/experimental_features/nexus/css/nexus.css`
- Create: `website/experimental_features/nexus/js/nexus.js`

- [ ] Add `NEXUS_DIR` path constant and static mounts in `website/app.py` for `/home/nexus/css` and `/home/nexus/js`.
- [ ] Add `GET /home/nexus` route in `website/app.py` returning the Nexus page.
- [ ] Create baseline Nexus page shell with provider cards, import controls, run list, and empty states.
- [ ] Add responsive styling in `nexus.css` with existing site style language and no purple accents.
- [ ] Add initialization JS in `nexus.js` that checks auth token and fetches `/api/nexus/providers`.
- [ ] Run: `pytest tests/test_website.py -v`
- [ ] Expected: existing website route tests remain green.

---

### Task 2: Add Nexus entry in avatar dropdowns

**Files:**
- Modify: `website/features/user_home/index.html`
- Modify: `website/features/user_home/js/home.js`
- Modify: `website/features/user_home/css/home.css`
- Modify: `website/features/user_zettels/index.html`
- Modify: `website/features/user_zettels/js/user_zettels.js`
- Modify: `website/features/user_zettels/css/user_zettels.css`

- [ ] Add `Nexus` menu item linking to `/home/nexus` in Home dropdown.
- [ ] Add `Nexus` menu item linking to `/home/nexus` in My Zettels dropdown.
- [ ] Update dropdown keyboard/focus handling if new item order requires it.
- [ ] Add CSS class styling for the new dropdown item icon state.
- [ ] Run quick UI smoke manually: `/home`, `/home/zettels`, avatar dropdown open/close, link navigation.

---

### Task 3: Add Supabase schema for Nexus tables

**Files:**
- Create: `supabase/website/nexus/schema.sql`
- Modify: `supabase/website/kg_public/schema.sql` (only if source_type enum/check needs update)

- [ ] Create DDL for `nexus_provider_accounts`, `nexus_ingest_runs`, `nexus_ingested_artifacts`.
- [ ] Add indexes and unique constraints (`user_id, provider`, `user_id, provider, artifact_id`).
- [ ] Add RLS policies for owner-only access and optional service role access.
- [ ] Add updated-at trigger for `nexus_provider_accounts`.
- [ ] If explicit `twitter` source type is used, update `kg_nodes.source_type` check constraint.
- [ ] Run SQL in Supabase staging and verify table creation.

---

### Task 4: Implement token encryption and token store

**Files:**
- Create: `website/experimental_features/nexus/service/token_store.py`
- Modify: `ops/requirements.txt` (only if needed)

- [ ] Implement `encrypt_token()` and `decrypt_token()` using app-level encryption key from `NEXUS_TOKEN_ENCRYPTION_KEY`.
- [ ] Implement token store CRUD for upsert/read/delete provider accounts.
- [ ] Ensure logs never print token plaintext.
- [ ] Add guardrails for missing encryption key (`503` style config error).
- [ ] Run: `pytest tests/test_nexus_token_store.py -v`
- [ ] Expected: encryption, decryption, and DB mapping tests pass.

---

### Task 5: Add Nexus common models and OAuth state utilities

**Files:**
- Create: `website/experimental_features/nexus/source_ingest/common/models.py`
- Create: `website/experimental_features/nexus/source_ingest/common/oauth_state.py`

- [ ] Define typed models for ingest item, provider account, import request, import result.
- [ ] Implement OAuth state generation/validation helpers (nonce + expiry).
- [ ] Implement PKCE helper utilities for providers requiring PKCE.
- [ ] Run: `pytest tests/test_nexus_providers.py -k "state or model" -v`

---

### Task 6: Implement YouTube native OAuth and ingest module

**Files:**
- Create: `website/experimental_features/nexus/source_ingest/youtube/oauth.py`
- Create: `website/experimental_features/nexus/source_ingest/youtube/ingest.py`

- [ ] Build YouTube auth URL with scopes and offline access.
- [ ] Implement callback token exchange and profile extraction.
- [ ] Implement fetchers for playlists and playlist items.
- [ ] Map each video artifact into ingest item model (title, url, body text, artifact_id, metadata).
- [ ] Preserve no-relogin behavior via account hinting and incremental consent settings.
- [ ] Add provider tests for URL generation and artifact mapping.

---

### Task 7: Implement GitHub native OAuth and ingest module

**Files:**
- Create: `website/experimental_features/nexus/source_ingest/github/oauth.py`
- Create: `website/experimental_features/nexus/source_ingest/github/ingest.py`

- [ ] Implement GitHub auth URL and callback exchange.
- [ ] Implement repo fetch (owned repos, optional starred repos).
- [ ] Map each repository into ingest item model with deterministic artifact_id.
- [ ] Add dedupe-safe artifact IDs (`owner/repo` form).
- [ ] Add tests for mapping and paging behavior.

---

### Task 8: Implement Reddit native OAuth and ingest module

**Files:**
- Create: `website/experimental_features/nexus/source_ingest/reddit/oauth.py`
- Create: `website/experimental_features/nexus/source_ingest/reddit/ingest.py`

- [ ] Implement Reddit OAuth URL, callback exchange, token refresh helpers.
- [ ] Implement saved items fetch (`/user/{username}/saved`).
- [ ] Map posts/comments into ingest item model and stable artifact IDs.
- [ ] Add tests for saved-item normalization and pagination boundaries.

---

### Task 9: Implement Twitter/X native OAuth and ingest module

**Files:**
- Create: `website/experimental_features/nexus/source_ingest/twitter/oauth.py`
- Create: `website/experimental_features/nexus/source_ingest/twitter/ingest.py`

- [ ] Implement OAuth 2.0 authorization code + PKCE flow.
- [ ] Implement bookmark fetch endpoint integration.
- [ ] Map tweet/bookmark payloads into ingest item model.
- [ ] Add robust handling for API access-level errors and missing scopes.
- [ ] Add tests for auth param generation and payload mapping.

---

### Task 10: Extract shared summarize-and-persist path

**Files:**
- Create: `website/experimental_features/nexus/service/persist.py`
- Modify: `website/api/routes.py`
- Modify: `website/core/graph_store.py`
- Modify: `website/core/supabase_kg/repository.py`
- Modify: `website/core/supabase_kg/models.py`

- [ ] Move current node persistence logic from `/api/summarize` into reusable service function.
- [ ] Keep file-store add, Supabase add, embedding generation, semantic linking, and entity extraction behavior equivalent.
- [ ] Update `/api/summarize` to call shared persistence service and preserve response contract.
- [ ] Add/adjust source prefix handling if explicit provider source values are introduced.
- [ ] Run: `pytest tests/test_website.py tests/test_supabase_kg.py -v`
- [ ] Expected: no regression in current summarize flow.

---

### Task 11: Implement Nexus bulk import service

**Files:**
- Create: `website/experimental_features/nexus/service/bulk_import.py`

- [ ] Implement batch execution with bounded concurrency and per-item retry policy.
- [ ] Force starting model to `gemini-2.5-flash-lite` for Nexus bulk summarize calls.
- [ ] Route each item through shared persistence service from Task 10.
- [ ] Track per-item success/failure and write run stats (`nexus_ingest_runs`).
- [ ] Upsert dedupe records into `nexus_ingested_artifacts`.
- [ ] Run: `pytest tests/test_nexus_bulk_import.py -v`

---

### Task 12: Build Nexus API router

**Files:**
- Create: `website/api/nexus.py`
- Modify: `website/app.py`

- [ ] Add `/api/nexus/providers` endpoint.
- [ ] Add `/api/nexus/connect/{provider}` endpoint.
- [ ] Add `/api/nexus/callback/{provider}` endpoint.
- [ ] Add `/api/nexus/disconnect/{provider}` endpoint.
- [ ] Add `/api/nexus/import/{provider}` and `/api/nexus/import/all` endpoints.
- [ ] Add `/api/nexus/runs` endpoint.
- [ ] Include router in app bootstrap with auth dependencies mirroring existing API style.
- [ ] Run: `pytest tests/test_nexus_api.py -v`

---

### Task 13: Wire Nexus frontend behavior

**Files:**
- Modify: `website/experimental_features/nexus/js/nexus.js`
- Modify: `website/experimental_features/nexus/index.html`
- Modify: `website/experimental_features/nexus/css/nexus.css`

- [ ] Fetch provider connection state and render connect/disconnect buttons.
- [ ] Trigger connect flow via `/api/nexus/connect/{provider}` and redirect to provider auth URL.
- [ ] Parse callback success/failure state and refresh provider cards.
- [ ] Trigger per-provider and import-all requests with progress states.
- [ ] Render import run summaries and item-level failures.
- [ ] Verify mobile viewport layout and button usability.

---

### Task 14: Optional source-type/UI extension for explicit Twitter source

**Files (only if chosen):**
- Modify: `telegram_bot/models/capture.py`
- Modify: `website/core/graph_store.py`
- Modify: `website/features/knowledge_graph/js/app.js`
- Modify: `website/features/user_home/css/home.css`
- Modify: `website/features/user_zettels/css/user_zettels.css`

- [ ] Add explicit `twitter` source support in enums/prefix maps.
- [ ] Add source badge color mapping for `twitter` across cards and KG view.
- [ ] Update filters to include `twitter` in graph and zettel screens.
- [ ] Add compatibility tests if source enum is expanded.

---

### Task 15: Full verification and regression pass

**Files:** all touched files

- [ ] Run targeted suite:
  - `pytest tests/test_nexus_api.py tests/test_nexus_bulk_import.py tests/test_nexus_token_store.py tests/test_nexus_providers.py -v`
- [ ] Run core regressions:
  - `pytest tests/test_website.py tests/test_supabase_kg.py tests/test_auth.py -v`
- [ ] Run broader non-live suite:
  - `pytest tests/ --ignore=tests/integration_tests -v`
- [ ] Manual checks:
  - `/home` dropdown has Nexus link.
  - `/home/zettels` dropdown has Nexus link.
  - `/home/nexus` page loads for authenticated users.
  - Provider connect -> callback -> import run completes for at least one provider in staging.

---

## Delivery checkpoints

1. Checkpoint A: Tasks 1-5 complete (page + schema + token store + OAuth scaffolding).
2. Checkpoint B: Tasks 6-9 complete (all provider ingest modules).
3. Checkpoint C: Tasks 10-13 complete (shared persistence + bulk import + API + UI).
4. Checkpoint D: Tasks 14-15 complete (optional source extension + full verification).

---

## Assumptions locked for execution

1. Native OAuth will be used for provider ingestion connections.
2. Supabase remains source of truth for provider tokens and import run metadata.
3. Nexus bulk imports default to `gemini-2.5-flash-lite` for cost/rate efficiency.
4. No provider-agnostic canonical URL orchestration layer will be introduced.
