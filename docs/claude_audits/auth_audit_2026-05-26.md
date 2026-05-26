# Auth surface audit — 2026-05-26

End-to-end audit of the OAuth + session lifecycle triggered by two real-user
failures, then expanded into a 4-PR series of UX-only hardening shipped to
production the same day.

## 1. Incident

Two users reported `"Sign-in failed: No session established after OAuth redirect"`
on the `/auth/callback` page:

| User | Device | Timestamps (UTC) | Outcome |
|---|---|---|---|
| Vedant Barbhaya (`barbhayavedant@gmail.com`) | iPhone iOS 18.7 Safari | 19:14:08 / 19:14:25 / 20:41:39 | First 2 attempts failed → 3rd succeeded |
| Prajeet (`prajeetladad@gmail.com`) | Windows Firefox 151 | 03:40 (3 attempts in 33 s) | All failed, gave up + used app anonymously |

Forensic SQL on `auth.users` confirmed the rows were CREATED server-side
(Supabase / Google OAuth handoff succeeded) but `last_sign_in_at` was either
NULL or only set on the lucky retry — i.e. **purely a client-side bug** in the
PKCE code-for-session exchange.

## 2. Root cause

`@supabase/auth-js` `GoTrueClient` default `flowType` is **`'implicit'`**
(verified directly from the master `GoTrueClient.ts` `DEFAULT_OPTIONS`). Our
`auth-core.js` did not set it explicitly, so `signInWithOAuth(...)` never
generated or stored a PKCE `code_verifier`. The `/auth/callback` page (which
DID set `flowType: 'pkce'` explicitly) then could not find the verifier in
`localStorage['zk-auth-token-code-verifier']` and threw the generic toast.

Intermittent successful retries are explained by URL-fragment delivery quirks
in `detectSessionInUrl` (handles both `?code=` and `#access_token=`); the bug
was deterministic-feeling but not 100%.

## 3. Fix shipped (PR #104 — `fix(auth): explicit pkce flowType + SW cache + SDK pin`)

```diff
 return supabase.createClient(config.supabase_url, config.supabase_anon_key, {
   auth: {
     persistSession: true,
     autoRefreshToken: true,
     detectSessionInUrl: true,
+    flowType: 'pkce',
     storage: window.localStorage,
     storageKey: 'zk-auth-token',
   },
 });
```

Plus 7 supporting items (`callback.html` `await initialize()` + lock-deadlock
guard + diagnostic toast, SW cache invalidation fix, SDK pinned to
`@supabase/supabase-js@2.106`, regression tests).

Verified live via Claude in Chrome MCP: 8/8 stress iterations on `/`, `/pricing`,
and `/m/`, plus the `/auth/callback?code=BOGUS_TEST_CODE` error path now
surfaces the real GoTrue error code + a `[no PKCE verifier]` localStorage probe
hint instead of the generic toast.

## 4. Audit expansion — 4-PR follow-up series

Triggered an exhaustive auth-surface audit (5 parallel research subagents
covering session lifecycle, sign-in UX, token storage, account security,
logged-in UX) cross-referenced with the existing codebase. Findings:

**Already at or above industry standard:**
- JWKS-first JWT validation with 60 s leeway + structured silent-drop telemetry
  (`X-Auth-Status: jwt-dropped-to-anon` middleware)
- BroadcastChannel cross-tab sync (built into supabase-js v2)
- Single-flight refresh-and-replay on 401 with banner-not-redirect UX (zk_fetch.js)
- `/api/me` JIT provisioning + allowlist 403 + JWT-claims fallback
- account_purge.py with GDPR pseudonymization for append-only logs

**Shipped this iteration (4 PRs, all UX-only, zero UI):**

| PR | Title | Closes gap from research |
|---|---|---|
| [#105](https://github.com/chintanmehta21/Zettelkasten_KG/pull/105) | `feat(auth): idle + absolute timeout + iOS storage fallback` | R1: Supabase Pro-only idle timeout → reimplemented client-side, free; iOS Safari <15.4 BroadcastChannel gap |
| [#106](https://github.com/chintanmehta21/Zettelkasten_KG/pull/106) | `feat(auth): /api/me/export GDPR self-service data export` | R4: India DPDP (May 13, 2027 enforcement) + GDPR Art. 20 "right of access" legal prerequisite |
| [#107](https://github.com/chintanmehta21/Zettelkasten_KG/pull/107) | `feat(ops): CSP report-only header + violation collector` | R3: "strict CSP is the real XSS defense; storage choice is secondary" |
| [#108](https://github.com/chintanmehta21/Zettelkasten_KG/pull/108) | `ci: sync Caddy config to droplet + graceful reload on deploy` | Deploy-pipeline gap: `ops/caddy/Caddyfile` was never scp'd to the droplet — discovered the same day via post-deploy verification on PR #107 |

Operator independently landed [`c55271e8 ci: include ops/caddy in deploy
sparse-checkout`](https://github.com/chintanmehta21/Zettelkasten_KG/commit/c55271e8)
as a parallel fix for the same Caddyfile-deploy gap.

## 5. Knobs introduced

| File | Constant | Value | Why |
|---|---|---|---|
| `auth-core.js` | `IDLE_MS` | `7 * 24 * 60 * 60 * 1000` | Notion / Figma idle norm |
| `auth-core.js` | `ABSOLUTE_MS` | `30 * 24 * 60 * 60 * 1000` | Linear absolute session cap |
| `auth-core.js` | `ACTIVITY_THROTTLE_MS` | `60 * 1000` | Avoid `localStorage` thrash on rapid click/keydown |
| `auth-core.js` | `ACTIVITY_KEY` | `zk-auth-last-activity` | Shared multi-tab activity baseline |
| `zk_fetch.js` | `STORAGE_BROADCAST_KEY` | `zk-auth-broadcast` | iOS Safari `<15.4` storage-event fallback channel |
| `routes.py` | `_EXPORT_PAGE_SIZE` | `500` | Per-workspace zettel page size |
| `routes.py` | `_EXPORT_MAX_PER_WORKSPACE` | `10 000` | Per-workspace export cap → `truncated: true` |
| `routes.py` | `_EXPORT_RATE_LIMIT_MAX` / `_WINDOW_SECONDS` | `5` / `3600` | Per-user export rate limit |
| `routes.py` | `_CSP_REPORT_RATE_LIMIT_MAX` / `_WINDOW` | `60` / `60` | Per-IP CSP report rate limit (first-week dense burst) |
| `routes.py` | `_CSP_REPORT_MAX_BYTES` | `8 * 1024` | Body cap to prevent OOM |
| `Caddyfile` | `Content-Security-Policy-Report-Only` | full directive set | XSS root-cause defense |

## 6. Verified post-deploy (live)

```bash
# CSP header present
curl -sD - -o /dev/null https://zettelkasten.in/ | grep -i 'content-security-policy-report-only'

# Collector accepts both formats, never 5xx on malformed
curl -sX POST https://zettelkasten.in/api/csp-report \
  -H 'Content-Type: application/csp-report' \
  -d '{"csp-report":{"violated-directive":"t","blocked-uri":"t"}}' -w '%{http_code}\n'
# → 204

# Data export endpoint live (anon → 401)
curl -s -o /dev/null -w '%{http_code}\n' https://zettelkasten.in/api/me/export
# → 401

# Idle timeout + PKCE constants live in served JS
curl -s https://zettelkasten.in/auth/js/auth-core.js | grep -E "IDLE_MS|flowType"
```

Also verified end-to-end via Claude in Chrome MCP: 5 sequential
`signInWithOAuth` calls on `/pricing` each generated a 114-char PKCE verifier
with `code_challenge_method=s256`; cross-tab `_broadcast('downgraded')` from
tab A surfaced the banner in tab B via BroadcastChannel + storage-event
fallback simultaneously.

## 7. Out of scope — deferred

| Item | Why deferred | Trigger to revisit |
|---|---|---|
| Hybrid storage (access in memory + refresh in HttpOnly cookie) — auth-audit PR #4 | R3 high-impact security upgrade but touches every authenticated page-load; feature-flag rollout needs a fuller test pass | Next iteration; ship behind `COOKIE_AUTH_ENABLED=false` |
| Email magic link as second sign-in method | UI required (operator: zero UI without approval); +8.5% conversion lift per MojoAuth 2026 | Operator UI approval |
| Account deletion UI + 7-day soft delete | UI required; legal must-have by India DPDP enforcement 2027-05-13 | Operator UI approval; before May 2027 |
| Avatar dropdown reorganization | UI required; pure layout reshuffle to match shadcn / Linear convention | Operator UI approval |
| Waitlist UX on allowlist denial | UI required; replaces hard 403 with Notion-style "you're on the list" screen | Operator UI approval |
| Soft re-auth modal preserving form state | UI required | Operator UI approval |
| `Trusted-Types: require-trusted-types-for 'script'` | Chrome-only; would log every `.innerHTML` use — needs Trusted-Types refactor first | After enforcing CSP |
| Flip CSP from `-Report-Only` to enforcing | Need ≥1 week of clean violation logs first | When violation log is quiet |
| Replace `'unsafe-inline'` with per-request nonce/hash | Requires template refactor (callback.html, static/index.html, etc.) | Required before CSP enforcement |
| Google Web Risk URL safety check (defends against malicious user-submitted URLs hitting our fetcher) | Out of auth scope; ~80 LOC + ~3 hours; VirusTotal API ToS-blocked for commercial use, Web Risk is the cleanest alternative | Standalone PR |
| Active-sessions UI + "log out everywhere" button | R4: defer until 1k+ users | 1k DAU |
| App-layer TOTP MFA via Supabase factors API | R4: defer until first compliance trigger (B2B contract, PCI-adjacent) | Compliance trigger |
| Passkeys | R4: Supabase still gates this behind `auth.experimental.passkey` flag | Supabase moves out of experimental |

## 8. Lessons captured

- **`flowType: 'pkce'` MUST be explicit** in every `createClient` call when the
  cross-page handoff uses PKCE. Default is `'implicit'` and is silent — server
  creates the user row, client never gets a session, generic toast hides the
  real cause.
- **`'unsafe-inline'` in CSP is a glass ceiling** — every inline `<script>` in
  our templates must be migrated to nonce/hash before we can flip CSP from
  report-only to enforcing. Track which templates still have inline scripts
  via the report stream.
- **Deploy-pipeline scope is silent** — `ops/caddy/Caddyfile` edits would not
  have reached production without the sparse-checkout / scp-action fix. Every
  new file path in `ops/` that production reads needs to be in the deploy
  workflow's sync list explicitly.
- **`getSession()` does NOT replay `_initialize` errors** in supabase-js v2 —
  always `await sb.auth.initialize()` first on the callback page to surface
  the real GoTrue error code instead of silently returning `{session: null}`.
- **VirusTotal Public API ToS prohibits commercial use** — even free SaaS
  count. Use Google Web Risk for URL safety checks.

## 9. Test additions

| File | Tests |
|---|---|
| `tests/unit/website/test_auth_core_flow_type.py` | 4 (`flowType: 'pkce'`, storageKey, storage adapter, file existence) |
| `tests/unit/website/test_auth_core_idle_timeout.py` | 8 (IDLE_MS / ABSOLUTE_MS constants, throttle, listener registration, first-run baseline, RESTORE-time check, signOut clears key, etc.) |
| `tests/unit/website/test_zk_fetch_storage_fallback.py` | 5 (storage broadcast key, storage listener, set→remove ordering, BroadcastChannel preservation, key filter) |
| `tests/unit/website/test_me_export.py` | 10 (401/503/404/200 status codes, wire shape, attachment header, pagination, truncation, rate limit, per-user isolation) |
| `tests/unit/website/test_csp_report_only.py` | 10 (Caddyfile pin, directive coverage, Reporting-Endpoints, report-only guard, legacy/modern format, malformed body, empty body, rate-limit silent drop, body-size cap) |

Total **+37 regression tests**. All pass on broader sweep
(`tests/unit/website/` + `tests/unit/api/` + `tests/unit/user_auth/`).

## 10. Files touched

```
ops/caddy/Caddyfile                                       # CSP header + Reporting-Endpoints
.github/workflows/deploy-droplet.yml                      # scp Caddy config + caddy reload
website/api/auth.py                                       # (untouched; verified strong)
website/api/routes.py                                     # /api/me/export, /api/csp-report
website/app.py                                            # cache-buster bumps
website/features/header/header.html                       # zk_fetch.js cache-buster
website/features/user_auth/js/auth-core.js                # flowType:'pkce', idle/absolute timeout
website/features/user_auth/callback.html                  # initialize() + lock guard + diag toast
website/footer/pricing/index.html                         # supabase-js@2.106 pin
website/mobile/templates/_shell.html                      # supabase-js@2.106 pin
website/static/index.html                                 # supabase-js@2.106 pin
website/static/js/zk_fetch.js                             # iOS Safari storage fallback
website/static/sw.js                                      # cache strategy fix (drop ignoreSearch)
+ 8 HTML templates                                        # supabase-js@2.106 pin
```
