# Theory Test Report - 2026-03-31

## Review Summary
- Critical Issues: 1
- Important Issues: 4
- Minor Issues: 5

---

## Critical Issues (MUST FIX)

### CRIT-1: Open Redirect in callback.html — `auth_return_to`

**File:** `website/features/user_auth/callback.html`, line 76–78

**Description:**
The post-login redirect uses `sessionStorage.getItem('auth_return_to')` without validation:

```js
var returnTo = sessionStorage.getItem('auth_return_to') || '/';
window.location.href = returnTo;
```

`sessionStorage` is same-origin and cannot be set cross-origin by a third party, so the risk vector here is lower than a URL-parameter-based open redirect. However, if any other JS on the page (e.g., a future CDN script compromise or XSS) writes an arbitrary value to `auth_return_to`, a user would be silently redirected to an attacker-controlled URL after OAuth completion.

The fix is a one-liner validation before using the value:

```js
var returnTo = sessionStorage.getItem('auth_return_to') || '/';
sessionStorage.removeItem('auth_return_to');
// Validate: only allow same-origin relative paths
if (!returnTo.startsWith('/') || returnTo.startsWith('//')) {
  returnTo = '/';
}
window.location.href = returnTo;
```

**Severity rationale:** Classified Critical because auth callback pages are high-value XSS targets and the fix is trivial — no reason to leave it open.

---

## Important Issues (SHOULD FIX)

### IMP-1: `_get_supabase()` global state is not thread-safe under authenticated calls

**File:** `website/api/routes.py`, lines 26–51

**Description:**
The function uses two module-level globals (`_supabase_repo`, `_supabase_user_id`). The original code was single-path: init once and reuse. The new `user_id_override` branch calls `get_or_create_user(user_id_override)` on every authenticated request but does NOT cache the result — it re-queries Supabase on every single summarize or graph call for authenticated users. Meanwhile the `_supabase_user_id` path is only reached when `user_id_override` is falsy, so an authenticated user never populates the cache.

There is no threading bug per se (FastAPI is async and GIL-protected here), but the lack of per-user caching means each authenticated request makes a synchronous Supabase RPC in a blocking call chain. This is an unnecessary latency hit on every authenticated API request.

**Suggestion:** Cache per-user UUIDs in a small `dict[str, str]` (`_user_id_cache`) keyed by the JWT `sub` claim, with an upper bound (e.g., LRU of 100 entries) to avoid unbounded growth in a multi-user scenario.

### IMP-2: `logoutBtn` is retrieved but never used in `auth.js`

**File:** `website/features/user_auth/js/auth.js`, lines 19 and 102

**Description:**
`logoutBtn` is fetched from the DOM in both the early-binding block (line 19) and the DOMContentLoaded block (line 102), but is never referenced again in the module. The logout button's `onclick="signOut()"` in `index.html` (line 32) calls the global `window.signOut` directly. The `logoutBtn` variable is dead code.

While harmless today, it is confusing to future maintainers and adds unnecessary DOM lookups. The `logoutBtn` assignments on both lines 19 and 102 should be removed.

### IMP-3: No `<noscript>` fallback for the login button

**File:** `website/static/index.html`

**Description:**
The login button is rendered by JavaScript (`auth.js` sets `style.display`). If JS fails (blocked CDN, network error, or browser with JS disabled), users see neither the Login button nor an explanation. The button starts visible in HTML (`display: flex` via CSS class), which is good, but the CDN `supabase-js` script is loaded unconditionally before `auth.js` — a CDN failure causes `supabase.createClient` to be undefined, making `auth.js` init throw silently. The button remains visible but clicking it calls `signInWithGoogle()` which checks `if (!_supabaseClient)` and just logs an error — giving the user no feedback.

**Suggestion:** In `signInWithGoogle()`, surface an error to the user (e.g., a brief alert or inline message) when `_supabaseClient` is null rather than silently failing.

### IMP-4: `/api/auth/config` exposes `SUPABASE_ANON_KEY` without rate limiting

**File:** `website/api/routes.py`, lines 98–104

**Description:**
The `/api/auth/config` endpoint returns `SUPABASE_ANON_KEY` without going through `_check_rate_limit`. The anon key is by design public (it is embedded in the client-side JS in all Supabase projects), so this is not a secret leak. However, the endpoint could be called in a tight loop by a scraper to enumerate configuration or drive up Supabase API quotas.

Applying the existing IP rate limiter to this endpoint (or adding cache-control headers like `Cache-Control: public, max-age=3600`) would be a minimal hardening step. The deferred caching suggestion from the execution team is reasonable; at minimum, add `Cache-Control`.

---

## Minor Issues (OPTIONAL)

### MIN-1: Hardcoded Supabase project hostname in `index.html`

**File:** `website/static/index.html`, line 12

```html
<link rel="preconnect" href="https://wcgqmjcxlutrmbnijzyz.supabase.co">
```

The Supabase project ID (`wcgqmjcxlutrmbnijzyz`) is hardcoded in the HTML. If the project is migrated or a new environment is used, this will be stale. Since the actual client init URL is fetched from `/api/auth/config` at runtime, the preconnect hint cannot easily be made dynamic without JavaScript. This is acceptable as a performance hint, but the team should be aware it is project-specific.

### MIN-2: `user-avatar` image has no `loading="lazy"` attribute

**File:** `website/static/index.html`, line 30

The lead review flagged this. The `<img class="user-avatar" id="user-avatar" src="" alt="User" />` starts with an empty `src`, which means no request is made until `auth.js` populates it. Adding `loading="lazy"` is still a good defensive practice and the lead specifically called it out.

### MIN-3: No responsive CSS for `.header-auth` at mobile breakpoint

**File:** `website/static/css/style.css`, lines 124–145

The `@media (max-width: 640px)` block does not include a rule for `.header-auth`. The header uses `flex-wrap: wrap`, which means the auth button will wrap below the logo on narrow viewports, but `.header-auth { margin-left: auto }` combined with `flex-wrap: wrap` can produce unexpected alignment on very narrow screens (the button takes a full-width row). A `@media` override such as `width: 100%; text-align: right` for `.header-auth` on mobile would make the layout explicit.

Note: Desktop users are redirected to the desktop site and mobile browsers are redirected to `/m/` (which does not load `auth.js` or show the login button), so this is low-impact in practice.

### MIN-4: `_decode_token` error message leaks internal exception details to HTTP response

**File:** `website/api/auth.py`, line 58–59

```python
except (pyjwt.InvalidTokenError, ValueError) as exc:
    raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
```

The exception message from PyJWT (e.g., `"Signature verification failed"`, `"Invalid audience"`) is forwarded to the HTTP response body. This is minor information leakage — it tells an attacker which specific validation step failed. Industry practice is to return a generic `"Invalid token"` message to clients. Logging the detailed error server-side (already done implicitly via the `logger` module being imported) is sufficient.

### MIN-5: `get_optional_user` silently swallows all exceptions

**File:** `website/api/auth.py`, lines 74–79

```python
try:
    return _decode_token(credentials.credentials)
except Exception:
    return None
```

The bare `except Exception` catches even `ValueError` from a missing JWT secret (configuration error), masking misconfiguration silently. Consider catching only `pyjwt.InvalidTokenError` broadly and re-raising or logging `ValueError` so misconfigured deployments surface the error rather than silently treating all requests as unauthenticated.

---

## Lead Review Concerns Validated

| Concern | Status |
|---|---|
| Login button renders top-right | CONFIRMED in HTML structure: `.header-auth { margin-left: auto }` pushes it right. Verified in diff. |
| `/api/me` returns 401 without token | CONFIRMED by test `test_unauthenticated_returns_401` and by `get_current_user` raising `HTTPException(401)` when credentials are None. |
| Regression: mobile header flex layout | PARTIALLY VALIDATED. Desktop header is now flexbox but mobile is redirected to `/m/` which does not load this header. No breakage to mobile flow. MIN-3 notes missing responsive CSS as a cosmetic gap. |
| Auth flow requires real OAuth credentials | CONFIRMED — the implementation correctly defers to runtime config and does not hardcode credentials. |
| No hardcoded secrets | CONFIRMED. `SUPABASE_JWT_SECRET` is read via `os.environ.get()` in `auth.py`. `SUPABASE_ANON_KEY` is runtime-fetched. No secrets in source files. |

---

## Code Quality Score

**PASS WITH WARNINGS**

The implementation is architecturally sound and backwards compatible. No regressions in the 482-test suite. Security fundamentals are correct — JWT validation uses HS256 with audience enforcement, the auth module is single-responsibility, and there are no hardcoded secrets.

The one Critical issue (open redirect in callback.html) is a 3-line fix. The four Important issues are refinements rather than blockers, but IMP-1 (per-call Supabase RPC on every authenticated request) will become a latency problem at any meaningful user volume.

---

## Recommendations

1. **Fix CRIT-1 now:** Add the 3-line origin validation to `callback.html` before the feature goes live. This is zero risk to change.

2. **Fix IMP-1 before load testing:** Add a `_user_id_cache: dict[str, str] = {}` in `routes.py` to avoid a synchronous Supabase roundtrip on every authenticated API call.

3. **Fix IMP-2 as cleanup:** Remove the two dead `logoutBtn` variable assignments from `auth.js`.

4. **Fix IMP-3 for user trust:** When `signInWithGoogle()` is called but `_supabaseClient` is null (CDN failure), show an inline error message rather than the current silent `console.error`.

5. **Address MIN-4 before production:** Change the 401 detail to a static `"Invalid token"` string and log the full exception server-side only.

6. **Address MIN-5 as a follow-up:** Narrow the `except Exception` in `get_optional_user` to only catch `pyjwt.InvalidTokenError | pyjwt.ExpiredSignatureError`, and log or re-raise `ValueError` (missing JWT secret).
