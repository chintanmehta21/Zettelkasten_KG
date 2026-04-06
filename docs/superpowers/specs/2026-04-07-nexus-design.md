# Nexus Design Specification (Experimental)

**Date:** 2026-04-07
**Status:** Proposed and approved for implementation planning
**Owner:** Website experimental features

---

## 1. Objective

Build an experimental feature named `Nexus` under `website/experimental_features` that lets authenticated users connect external accounts (YouTube, GitHub, Reddit, Twitter/X), import artifacts, convert each artifact into a Zettel, and push those Zettels through the same summarization + graph persistence path used by current URL captures.

The feature must also be reachable from the profile dropdown on every page that currently has that dropdown.

---

## 2. Hard Requirements (from product direction)

1. Support account connections for YouTube, GitHub, Reddit, and Twitter/X.
2. Import relevant artifacts per provider (examples: YouTube playlist videos, GitHub repos, Reddit saved posts, Twitter saved/bookmarked posts).
3. Every imported artifact must become a Zettel in the user profile.
4. Every imported artifact must go through the existing summarization pipeline and be added to the knowledge graph as if the user submitted it manually.
5. Bulk summarization is required for import jobs.
6. Bulk summarization must use a free Gemini model with high rate limits and acceptable quality.
7. Add Nexus into profile dropdown menus where avatar dropdown exists today.
8. Create `source_ingest` inside Nexus with dedicated folders per provider.
9. If user is already signed in with Google and imports from YouTube with same account, avoid credential re-login.
10. Do not implement a provider-agnostic canonical URL orchestration layer.

---

## 3. Explicit Decisions

### 3.1 Auth and token strategy

1. Keep Supabase Auth as primary app identity/session layer.
2. Use native OAuth flows per provider for Nexus connection scopes and token lifecycle control.
3. Store provider tokens in Supabase (not Render env or local disk), encrypted at application layer.
4. Keep provider client secrets and encryption key in Render environment variables.

### 3.2 Bulk summarization model

Use `gemini-2.5-flash-lite` as the default forced model for Nexus bulk jobs (free tier, high practical throughput, sufficient quality for ingest summaries).

### 3.3 No canonical abstraction layer

No canonical provider-agnostic artifact-to-URL orchestrator will be introduced. Ingestion remains provider-specific in separate modules under `source_ingest/<provider>`.

### 3.4 YouTube no-relogin behavior

For Google/YouTube connect, use Google OAuth with account hinting and consent flow tuned to reuse active Google session (`login_hint`, incremental scopes, offline access). Users may see consent for new scopes, but not credential re-entry in normal SSO conditions.

---

## 4. Scope

### In scope (Nexus v1)

1. Provider connect/disconnect UI in a new Nexus page.
2. Provider-specific OAuth callback handling.
3. Provider-specific artifact fetch modules.
4. Bulk import job execution from selected providers.
5. Batch summarization + existing KG write path reuse.
6. Basic import history, status, and error reporting.
7. Profile dropdown entry points to Nexus from Home and My Zettels pages.

### Out of scope (Nexus v1)

1. New summarization engine redesign.
2. Cross-provider canonical normalization layer.
3. Realtime background workers or queue infra migration.
4. Full scheduling/sync automation (manual import trigger only in v1).

---

## 5. Architecture

### 5.1 High-level flow

1. User opens Nexus page and connects provider(s).
2. OAuth callback stores encrypted provider tokens in Supabase.
3. User triggers import for one provider or all connected providers.
4. Provider-specific ingest module fetches artifact payloads.
5. Artifact payloads are transformed into Nexus ingest items (provider-local model only).
6. Bulk summarizer processes items using current summarization path + `gemini-2.5-flash-lite` default model.
7. Each summary is persisted through the same KG insertion path used by `/api/summarize`.
8. UI shows per-item success/failure and imported Zettel count.

### 5.2 Component boundaries

1. `website/experimental_features/nexus/source_ingest/*`: provider OAuth + artifact fetch logic.
2. `website/experimental_features/nexus/service/*`: bulk import orchestration for Nexus only.
3. `website/api/nexus.py`: Nexus API endpoints.
4. `website/core/*` shared services: existing summarize + graph persistence reused.
5. Supabase schema extensions: provider tokens, import runs, imported artifact dedupe.

---

## 6. Planned File Structure

```text
website/experimental_features/nexus/
  index.html
  css/nexus.css
  js/nexus.js
  source_ingest/
    __init__.py
    common/
      __init__.py
      models.py
      oauth_state.py
    youtube/
      __init__.py
      oauth.py
      ingest.py
    github/
      __init__.py
      oauth.py
      ingest.py
    reddit/
      __init__.py
      oauth.py
      ingest.py
    twitter/
      __init__.py
      oauth.py
      ingest.py
  service/
    __init__.py
    token_store.py
    bulk_import.py
    persist.py

website/api/
  nexus.py

supabase/website/nexus/
  schema.sql
```

---

## 7. Data Model (Supabase)

### 7.1 `nexus_provider_accounts`

Purpose: store encrypted provider OAuth credentials per user and provider.

Columns:
1. `id uuid pk`
2. `user_id uuid not null references kg_users(id)`
3. `provider text check in ('youtube','github','reddit','twitter')`
4. `provider_user_id text`
5. `scopes text[]`
6. `access_token_enc text not null`
7. `refresh_token_enc text`
8. `expires_at timestamptz`
9. `token_type text`
10. `metadata jsonb default '{}'`
11. `created_at timestamptz default now()`
12. `updated_at timestamptz default now()`

Constraints:
1. Unique `(user_id, provider)`

### 7.2 `nexus_ingest_runs`

Purpose: import job tracking and audit.

Columns:
1. `id uuid pk`
2. `user_id uuid not null`
3. `provider text not null`
4. `status text check in ('queued','running','completed','failed','partial')`
5. `requested_count int default 0`
6. `success_count int default 0`
7. `failure_count int default 0`
8. `started_at timestamptz`
9. `finished_at timestamptz`
10. `error_summary text`
11. `metadata jsonb default '{}'`

### 7.3 `nexus_ingested_artifacts`

Purpose: per-user/provider dedupe and import provenance.

Columns:
1. `id uuid pk`
2. `user_id uuid not null`
3. `provider text not null`
4. `artifact_id text not null`
5. `artifact_url text`
6. `zettel_node_id text`
7. `imported_at timestamptz default now()`
8. `metadata jsonb default '{}'`

Constraints:
1. Unique `(user_id, provider, artifact_id)`

---

## 8. API Contract (Nexus)

Base prefix: `/api/nexus`

1. `GET /api/nexus/providers`
   - Returns provider connection states and last sync timestamps.

2. `POST /api/nexus/connect/{provider}`
   - Returns provider auth URL + state nonce.

3. `GET /api/nexus/callback/{provider}`
   - Exchanges code for tokens; stores encrypted credentials.

4. `POST /api/nexus/disconnect/{provider}`
   - Deletes stored provider credentials for the user.

5. `POST /api/nexus/import/{provider}`
   - Starts import run for one provider.
   - Body includes optional limits (for v1 safe caps).

6. `POST /api/nexus/import/all`
   - Imports from all connected providers in sequence.

7. `GET /api/nexus/runs`
   - Returns recent run status summaries.

---

## 9. Provider ingestion details

### 9.1 YouTube

Artifacts:
1. Playlist videos from user-owned playlists or selected playlist IDs.

API family:
1. YouTube Data API v3.

Scopes:
1. `https://www.googleapis.com/auth/youtube.readonly`
2. `openid email profile` (for account context only)

Notes:
1. Use refresh tokens (`access_type=offline`) and incremental consent.
2. Use current Google identity hint to minimize account friction.

### 9.2 GitHub

Artifacts:
1. User repositories (owned, optionally starred).

API family:
1. GitHub REST API v3.

Scopes:
1. `read:user`
2. `repo` or fine-grained equivalent for private repo metadata (if enabled)
3. `public_repo` for public-only mode

### 9.3 Reddit

Artifacts:
1. Saved posts/comments.

API family:
1. Reddit OAuth API (`/user/{username}/saved`).

Scopes:
1. `history`
2. `identity`

### 9.4 Twitter/X

Artifacts:
1. Bookmarks (saved posts), optionally likes in later milestone.

API family:
1. X API v2 bookmarks endpoints.

Scopes:
1. `bookmark.read`
2. `tweet.read`
3. `users.read`
4. `offline.access`

---

## 10. Summarization and KG integration

### 10.1 Reuse path

Nexus imports must reuse existing summarize + graph persistence behavior from current `/api/summarize` path. Implementation will extract this persistence behavior into a reusable service function and call it from both:
1. Existing manual summarize endpoint.
2. Nexus bulk import endpoint.

### 10.2 Bulk strategy

1. Summarize artifacts in bounded async batches (configurable concurrency, default 4).
2. Force starting model to `gemini-2.5-flash-lite` for Nexus run items.
3. Continue on per-item failure (partial success mode).
4. Return per-item status payload with reason codes.

### 10.3 Deduping

1. Skip artifacts already in `nexus_ingested_artifacts`.
2. Preserve existing URL dedupe behavior in KG repository.

---

## 11. UI/UX behavior

### 11.1 Nexus page

1. Route: `/home/nexus`.
2. Sections:
   - Provider connection cards.
   - Import controls (per provider + import all).
   - Recent run timeline.
   - Result summary stats.

### 11.2 Dropdown integration

Add `Nexus` menu item in avatar dropdowns on:
1. `website/features/user_home/index.html`
2. `website/features/user_zettels/index.html`

### 11.3 Visual constraints

1. Keep existing design language.
2. Do not introduce purple/violet accents.
3. Maintain desktop and mobile usability.

---

## 12. Security and compliance

1. Provider tokens encrypted before DB write with app key from Render env (`NEXUS_TOKEN_ENCRYPTION_KEY`).
2. OAuth `state` and PKCE required for all native provider flows.
3. Token reads/writes allowed only for authenticated owner user ID.
4. Avoid logging raw access or refresh tokens.
5. Apply reasonable rate limits on connect/callback/import endpoints.

---

## 13. Error handling

1. Provider auth failures return actionable errors and reconnect CTA.
2. Token refresh failures mark provider as `reauth_required`.
3. Import run continues for remaining artifacts on single-item failures.
4. Import run status can be `partial` with detailed counters.

---

## 14. Testing strategy

1. Unit tests for provider OAuth URL generation and callback token exchange parsing.
2. Unit tests for bulk summarization batching and partial failure handling.
3. API tests for Nexus endpoints auth/validation/rate limiting.
4. Regression tests ensuring `/api/summarize` unchanged behavior after persistence refactor.
5. Frontend smoke checks for dropdown links and Nexus page loading.

---

## 15. Rollout plan

1. Implement behind experimental route only (`/home/nexus`).
2. Keep old flows untouched.
3. Enable provider credentials in environment one provider at a time.
4. Start with low import caps to validate quality and stability.

---

## 16. Assumptions

1. Supabase project already used by web app remains the persistence backend.
2. Provider developer apps (Google, GitHub, Reddit, X) will be configured with callback URLs matching deployment.
3. Experimental feature can add new API router/module files without changing Telegram bot runtime behavior.
