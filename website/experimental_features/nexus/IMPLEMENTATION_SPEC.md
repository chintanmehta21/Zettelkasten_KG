# Nexus Plumbing Implementation Spec

## Scope

This spec covers only:

- `supabase/website/nexus/schema.sql`
- `ops/requirements.txt`
- `website/experimental_features/nexus/js/nexus.js`
- This Nexus docs folder

## Runtime Contracts To Match

### Backend write behavior (already in app code)

- Ingest runs write statuses: `running`, `completed`, `failed`, `partial_success`.
- Artifacts are upserted with per-item fields:
  - `run_id`
  - `status` (`imported` / `skipped` / `failed`)
  - `error_message` (when failed)
  - `node_id` (when imported)
- Nexus persistence resolves a KG-local UUID user scope, then uses that UUID as `user_id` in Nexus tables.

### API behavior consumed by frontend

- Connect endpoint: `POST /api/nexus/connect/{provider}` returns a redirect URL, canonically `authorization_url` (with legacy aliases still possible).
- Disconnect endpoint: `POST /api/nexus/disconnect/{provider}` returns `{ provider, disconnected }`.

## Required Data Model

### `nexus_provider_accounts`

- `user_id` FK must target `public.kg_users(id)` (not `auth.users(id)`).
- Keep unique `(user_id, provider)`.

### `nexus_ingest_runs`

- `status` must allow: `pending`, `running`, `completed`, `partial_success`, `failed`, `cancelled`.
- Keep aggregate counters (`total_artifacts`, `imported_count`, `skipped_count`, `failed_count`) and `error_message`.
- `user_id` FK must target `public.kg_users(id)`.

### `nexus_ingested_artifacts`

- Must support per-artifact execution state:
  - `status` in `pending|imported|skipped|failed`
  - `error_message` nullable
  - `node_id` nullable
  - `run_id` FK to `nexus_ingest_runs(id)`
- Keep legacy `ingest_run_id` nullable for compatibility during parallel backend work.
- `user_id` FK must target `public.kg_users(id)`.

## Migration Strategy

Schema SQL must be idempotent and safe on existing environments:

1. `CREATE TABLE IF NOT EXISTS` for clean installs.
2. `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for runtime-missing columns.
3. Backfill `run_id` from legacy `ingest_run_id` when present.
4. Replace outdated FK/check constraints with current runtime-compatible ones.
5. Keep old `ingest_run_id` as compatibility alias while `run_id` is canonical.

## Dependency Contract

- `cryptography` must be present in `ops/requirements.txt` because Nexus token storage uses `cryptography.fernet.Fernet`.

## Frontend Contract

### Connect flow

- Redirect URL extraction must recognize:
  - `authorization_url`, `authorizationUrl`
  - Existing aliases: `redirect_url`, `redirectUrl`, `auth_url`, `authUrl`, `url`

### Disconnect flow

- Disconnect button performs real API call to `/api/nexus/disconnect/{provider}`.
- On success, refresh providers/runs and show clear success feedback.
- On error, surface API error via toast.

## Non-goals

- No changes to non-Nexus product features.
- No replacement of the existing summarization pipeline (Nexus must reuse current Zettel summarization behavior).
