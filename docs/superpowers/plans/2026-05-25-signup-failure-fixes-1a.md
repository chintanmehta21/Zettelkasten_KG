# Signup failure fixes — 1a

**Branch:** `signup-failure-fixes-1a`
**Created:** 2026-05-25
**Driver:** subagent-driven-development inside this PR

## Problem

After Google sign-up + redirect, the user briefly sees a failure note; refresh resolves it. Forensic investigation (see commit history + audit doc `docs/claude_audits/prajeet_grant_and_failure_audit_2026-05-25.md`) identified three concurrent failure surfaces:

- **Visible UI failure** — `callback.html` calls `exchangeCodeForSession` after `detectSessionInUrl: true` already consumed the PKCE verifier. Result: red "Sign-in failed:" text.
- **Silent identity collapse to Zoro** — `get_optional_user` drops bad JWTs to anon; backend instrumentation landed in commit 5468fde3 but the frontend never reads `X-Auth-Status` and never reacts.
- **JWT claim staleness** — gotrue OAuth path mints the JWT BEFORE our `AFTER INSERT` triggers run (`auth/internal/api/external.go` ordering bug, confirmed in upstream issues supabase/auth#1280 and auth-js#670), so `app_metadata.workspace_ids` is empty in the first JWT.

## Approach

Research synthesis (see prior chat) chose canonical 2024-2026 patterns for each:

1. **Drop redundant PKCE exchange** in `callback.html` — match Supabase docs verbatim.
2. **`zkFetch` wrapper** (not a `window.fetch` monkey-patch — PWA SW conflict) reacts to `X-Auth-Status` + does single-flight `refreshSession` retry on 401, distinguishing Cloudflare-issued errors via `cf-error-type`.
3. **Supabase Custom Access Token Hook** — PL/pgSQL function that injects `workspace_ids` at JWT mint time. Same shape as Auth0 Post-Login Actions and AWS Cognito Pre-Token Generation Lambda.
4. **Single-flight refresh-and-retry** + non-blocking banner — no auto-redirect, no destroyed mid-flow state.
5. **JWKS pre-warm** in FastAPI lifespan with soft-fail to protect blue/green flips.

Plus standards hardening:
- `WWW-Authenticate: Bearer error="invalid_token"` alongside `X-Auth-Status` (RFC 6750 compliance).
- `Cache-Control: private, no-store` on any route emitting `X-Auth-Status` (Cloudflare cache-poisoning mitigation per CF cache-security docs).
- `ensure_provisioned()` idempotent RPC as belt-and-braces for trigger-failure cases.

## Task breakdown

| Task | Scope | Migration? | Tests |
|---|---|---|---|
| **A** | Branch + draft PR scaffold | no | n/a (this commit) |
| **B** | `54_custom_access_token_hook.sql` + `55_ensure_provisioned.sql` | yes | pytest --live (Supabase project) |
| **C** | `app.py` middleware: `WWW-Authenticate` + `Cache-Control: private, no-store` + JWKS lifespan pre-warm | no | extend `tests/unit/website/test_auth_jwt_drop_observability.py`; new pre-warm test with `respx` + `asgi-lifespan` |
| **D** | `routes.py` `/api/me`: call `core.ensure_provisioned` when v2 profile lookup returns None | no | unit test with `respx` mocking the RPC |
| **E** | `callback.html`: drop explicit `exchangeCodeForSession`, add `flowType: 'pkce'`, confirm via `getSession()` | no | pytest regex: at most one `exchangeCodeForSession(` in rendered page |
| **F** | `website/static/js/zk_fetch.js` + base template banner + listener | no | playwright (Task H) |
| **G** | Mechanical `fetch(` → `zkFetch(` across `website/features/**/*.js` for Authorization-bearing calls | no | grep audit + playwright |
| **H** | `pytest-playwright` + `respx` + `asgi-lifespan` dev deps; `tests/e2e/conftest.py`; browser tests for #1/#2/#4; CI cache for `~/.cache/ms-playwright/` | no | the tests themselves |
| **I** | Final code review + push PR ready | no | full pytest suite passes |

## Hard guardrails

Touches **NO** protected knob from CLAUDE.md "Critical Infra Decision Guardrails":
- `GUNICORN_WORKERS`, `--preload`, FP32_VERIFY_ENABLED, `GUNICORN_TIMEOUT`, rerank semaphore, SSE heartbeat, Caddy timeouts, schema-drift gate, `kg_users` allowlist gate, color rules — all untouched.

Approval status: per chat 2026-05-25, all 5 fixes pre-approved by operator. Task A commit is this plan doc; remaining tasks each end in one commit. PR stays in **draft** until Task I; then transitions to ready-for-review.

## Migration strategy

Both new SQL files use the project's versioned `_v2/NN_*.sql` convention (next free numbers: `54`, `55`). They include the `GRANT EXECUTE ... TO supabase_auth_admin` + `REVOKE EXECUTE ... FROM public` pattern per [feedback_v2_table_grants.md] and SECURITY DEFINER + `SET search_path = ''` per `53_set_search_path_v2_functions.sql`. CI migration manifest gets regenerated.

Dashboard registration of the Custom Access Token Hook (Supabase Dashboard → Authentication → Hooks) is an operator action **outside** this PR — the PR delivers the function; the operator wires the hook.

## Out of scope

- Server-side PKCE exchange (would require a Python equivalent of `@supabase/ssr`; deferred to a future iteration).
- Mobile shell `auth-modal.js` migration to `zkFetch` (this PR is desktop-first; mobile gets a follow-up).
- Multi-tab sign-in lock (concurrent-tab sign-in race is documented but rare).
