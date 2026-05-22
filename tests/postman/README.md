# Zettelkasten Postman Suite

This module tests the summarization API paths described in `docs/research/postman_init1.md` and `docs/research/postman_init2.md`.

## What It Covers

- P1: `/api/zettels/add` from landing, home, and My Zettels surfaces.
- P1: `202 + Location + Retry-After` operation contract and bounded polling.
- P1: authenticated `/api/zettels` list shape, duplicate checks, and user scoping.
- P1: Supabase verification for `content.workspace_zettels` and `content.canonical_zettels`.
- P1: validation failures for invalid URLs, SSRF/private URL candidates, and unauthenticated list access.
- P2: `/api/v2/summarize`, `/api/v2/batch`, `/api/v2/batch/stream`.
- P2: document-upload failure handling.
- P3: Newman JSON and timing-summary reporting.

## Run Locally

Install Newman without changing repo dependencies:

```bash
npm install --no-save newman
```

Dry validation:

```bash
node tests/postman/scripts/validate-postman-files.mjs
```

Live run:

```bash
RUN_LIVE_REQUESTS=true \
COLLECTION=tests/postman/collections/zettelkasten-summarization.postman_collection.json \
ENVIRONMENT=tests/postman/environments/zettelkasten.local.template.postman_environment.json \
REPORT_DIR=tests/postman/reports \
bash tests/postman/ci/run-newman.sh
```

On Windows:

```powershell
.\tests\postman\ci\run-newman.ps1
```

## GitHub Actions

Use the manual `Postman summarization API` workflow. It writes a dated result tree:

```text
docs/postman_results/YYYY-MM-DD/HHMMSS-run-<run_id>/
```

The same tree is uploaded as a GitHub Actions artifact named `postman-results-...`. Runtime environment files that contain secrets stay in the runner temp directory; only sanitized environment metadata is uploaded.

Recommended operating model:

- Before deploy: run dry validation on the PR branch. This catches broken collection JSON and script errors with no droplet load.
- Right after deploy cutover and health check: run the live Postman workflow manually against the public URL. This is the best smoke gate because it tests the real Caddy -> app -> Supabase path after the new image is serving.
- After a user-visible incident or schema change: run with `persist_live_writes=true` and Supabase secrets to verify writes and tenant scoping.
- Avoid running slow YouTube paths on every deploy unless investigating that class of issue. Set `allow_slow_live_paths=true` only for targeted checks to minimize droplet and API overhead.

## Required Secrets For Full Live Coverage

- `POSTMAN_AUTH_TOKEN_USER_A`: Supabase access token for a test user.
- `POSTMAN_AUTH_TOKEN_USER_B`: Supabase access token for a second test user.
- `SUPABASE_URL`: Supabase project URL.
- `SUPABASE_SERVICE_ROLE_KEY`: service-role key for direct verification queries.

Without those secrets, auth and Supabase verification requests are skipped by pre-request guards.

## Report Mapping

See `coverage-map.md` for every report requirement, its priority, and the Postman request that covers it.
