# Google OAuth Consent-Screen Branding Fix — Plan & Operator Runbook

**Date:** 2026-05-31
**Branch:** `feat/google-native-signin`
**Goal:** Stop the Google account-chooser / consent screen from showing `ic…supabase.co`. Make it read **"Sign in to Zettelkasten · to continue to zettelkasten.in"**.

> Status: **Option B selected** (operator, 2026-06-01), refined to a server-side full-page
> **redirect** flow (most faithful to the current UX, most browser-robust). Backend routes +
> frontend wiring + tests **implemented** in PR #135 (commits `f2737017`, `6c32cd23`). Teal button
> unchanged. Remaining = the manual Google Cloud + Supabase console steps in §7, then set the env vars.

---

## 1. Problem

On the Google account-selection page, the company/app is shown as the Supabase project host
(`<project-ref>.supabase.co`) instead of "Zettelkasten". Google brand verification was attempted and the
app "did not meet the criteria" (homepage / authorized-domain rules — Google support answer 13807376).

## 2. Root cause (verified from code)

The site uses Supabase's **hosted OAuth redirect flow**:

- `website/features/user_auth/js/auth.js:254` and `website/mobile/js/auth-modal.js:176` both call
  `client.auth.signInWithOAuth({ provider, options: { redirectTo: origin + '/auth/callback' } })`.
- That flow round-trips through `https://<project-ref>.supabase.co/auth/v1/callback`.
- Google's consent screen always shows the **host of the redirect URI**. Since that host is a third-party
  domain we cannot verify in Search Console, both the branding line is wrong AND brand verification is hard
  to pass (the authorized domain on our consent screen can't be the supabase.co host).

Backend user resolution (`website/api/auth.py::get_current_user`, JWKS-first JWT decode) is **flow-agnostic**:
it validates whatever Supabase session JWT results. Switching the Google handshake does not change it.

## 3. The fix — native ID-token flow (Supabase `signInWithIdToken`)

With Google Identity Services (GIS), the browser talks to Google **directly from `zettelkasten.in`**, gets a
Google **ID token**, and hands it to Supabase via `supabase.auth.signInWithIdToken({ provider: 'google', token, nonce })`.
`supabase.co` is **never** in the OAuth round-trip, so:

- The consent screen shows **zettelkasten.in** + our brand.
- Google brand verification only ever inspects `zettelkasten.in` (which we own and can verify) — the
  third-party-domain blocker disappears.

### Verified GIS constraints (Google docs, 2026 — these shape the decision in §4)

- **You cannot attach the ID-token flow to a fully custom (e.g. teal) button.** The `google.accounts.id`
  library only supports `renderButton` (Google's own button) or One-Tap `prompt()`. `prompt()` is **not** a
  click handler.
- **`renderButton` colors are fixed**: `outline` / `filled_blue` / `filled_black`. **Teal is not possible.**
- The other five providers (github, apple, twitter, facebook, twitch) have **no** native ID-token path here
  and **must stay on the hosted redirect flow**. Only Google is rerouted.

## 4. DECISION PENDING — button approach

| Option | UX | Robustness | Code | Notes |
|---|---|---|---|---|
| **A. Google rendered button** (recommended) | Google's standard button replaces the teal "Sign in with Google" in the modal; optional One-Tap card | High — fully supported | Low (frontend + 1 config field) | Google button is not teal; other providers stay teal |
| **B. Backend-mediated OAuth** | Keep the **teal** button; it opens a Google popup on our domain | High | Medium-High (new FastAPI route + `GOOGLE_CLIENT_SECRET` + token exchange) | Preserves teal; more attack surface + secret to manage |
| **C. Invisible-overlay hack** (rejected) | Teal visible, Google button transparent on top | Low — pixel-fragile, breaks on resize/locale/zoom | Low | Violates "no knowingly-fragile state" — not for a prod auth path |

**SELECTED: Option B** (operator, 2026-06-01) — implemented as a server-side full-page **redirect**
(not a popup): identical UX to the current login, robust on every browser (pure redirects — no popups,
no 3rd-party cookies, no GIS JS), and it sidesteps the popup `redirect_uri='postmessage'` footgun.
CSRF via a one-time SameSite=Lax `state` cookie; no OIDC nonce (confidential-client code exchange +
state already block replay). One-Tap stays a separate opt-in. Env: `GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_OAUTH_CLIENT_SECRET`, `PUBLIC_BASE_URL`. Routes: `GET /api/auth/google/start` +
`GET /api/auth/google/callback`; handoff page `website/features/user_auth/google_handoff.html`.

## 5. Design common to A & B (backward-compatible, zero-risk to merge)

- **Feature flag via config presence.** `/api/auth/config` (`website/api/routes.py:397`) gains a
  `google_client_id` field sourced from env `GOOGLE_OAUTH_CLIENT_ID`.
  - Empty / unset → frontend **keeps the current hosted redirect flow** (no behavior change at all).
  - Non-empty → native Google flow activates.
  - ⇒ This PR is **safe to merge and deploy before** any console work is done. Nothing changes for users
    until the env var is set. Rollback = unset the env var.
- **Nonce.** Generate a random raw nonce; send SHA-256 hex to Google, raw to `signInWithIdToken`
  (per Supabase docs). Alternative: Supabase "Skip Nonce Check" toggle.
- **Scope of frontend change.** Only the Google branch is rerouted; the generic `signInWithProvider` path for
  the other providers is untouched.
- **One-Tap auto-prompt** defaults **OFF** (button/click-triggered only). Flippable later.

## 6. Code touch points (current `origin/master`, to re-confirm at implementation)

- `website/api/routes.py:397` — `/auth/config`: add `google_client_id`.
- `website/core/settings.py` — surface/validate `GOOGLE_OAUTH_CLIENT_ID` if the route reads via settings
  (route currently reads `os.environ` directly for supabase keys — match that pattern).
- `website/features/user_auth/js/auth-core.js` — add the native Google helper (GIS load + nonce + hashing +
  `signInWithIdToken`) with fallback to `signInWithOAuth`. NOTE: this file (~464 lines) has a PKCE /
  `signInWithOAuth` override at ~line 134 — re-read fully before editing.
- `website/features/user_auth/js/auth.js:254` — route `provider === 'google'` through the helper.
- `website/mobile/js/auth-modal.js:176` — same for mobile.
- Login templates — desktop `website/static/index.html`, `website/footer/pricing/index.html`,
  mobile `website/mobile/templates/_oauth_modal.html`: Option A mounts the rendered button; Option B keeps
  the teal button.
- Asset cache-bust: bump the `?v=` query on the `auth-core.js` / `auth.js` / `auth-modal.js` includes
  (pattern: `?v=20260524a`).
- Tests: `tests/test_auth.py`, `tests/test_auth_providers.py`, `tests/integration/test_auth_callback.py`,
  `tests/unit/user_auth/`.

## 7. Operator runbook (manual — cannot be done in code)

### 7a. Google Cloud Console
1. **Branding** — `console.cloud.google.com/auth/branding`: App name = `Zettelkasten`, square logo (≥120px),
   App home = `https://zettelkasten.in`, privacy + ToS URLs, **Authorized domain = `zettelkasten.in`**.
2. **Audience** — `console.cloud.google.com/auth/audience`: publish (Testing → Production / External).
3. **Data Access** — `console.cloud.google.com/auth/scopes`: only `openid`, `userinfo.email`,
   `userinfo.profile` (non-sensitive → no Google app review, only brand review).
4. **Clients** — `console.cloud.google.com/auth/clients`:
   - **Option A:** create a Web client with **Authorized JavaScript origins** = `https://zettelkasten.in`
     (+ `http://localhost:8000` for dev). **No redirect URI** needed for the ID-token flow. Keep the existing
     supabase.co-redirect client for the other providers + hosted fallback.
   - **Option B (selected):** add **Authorized redirect URI** =
     `https://zettelkasten.in/api/auth/google/callback` (note the `/api` prefix); download the
     **client secret**. JS origins are not required for the server-side redirect flow.
5. **Verify `zettelkasten.in`** in Google Search Console (`search.google.com/search-console`).

### 7b. Supabase Dashboard
- Auth → Providers → Google → add the new client ID to **Authorized Client IDs** (this is what makes Supabase
  trust `signInWithIdToken` tokens). Set nonce handling (or enable Skip Nonce Check).

### 7c. Droplet env
- Set `GOOGLE_OAUTH_CLIENT_ID=<client id>`, `GOOGLE_OAUTH_CLIENT_SECRET=<secret>`, and
  `PUBLIC_BASE_URL=https://zettelkasten.in` in the container env / `/etc/secrets/api_env`.
  `PUBLIC_BASE_URL` must equal the origin of the registered redirect URI (else `redirect_uri_mismatch`).
  See `ops/.env.example` → "Google native sign-in".

### 7d. Deploy ordering (critical)
1. Merge this PR — **no behavior change** while the env var is unset.
2. Do 7a + 7b.
3. Set `GOOGLE_OAUTH_CLIENT_ID` → deploy → native flow activates.
4. Verify in an incognito window: consent reads **"Sign in to Zettelkasten · to continue to zettelkasten.in"**
   (logo can take ~24h to propagate).
- **Rollback:** unset `GOOGLE_OAUTH_CLIENT_ID` → instant revert to the hosted redirect flow.

## 8. Optional, separate, non-code (paid) — Supabase Custom Domain

Setting a Supabase Custom Domain (`auth.zettelkasten.in`, Pro plan + $10/mo add-on) removes `supabase.co`
from the URL even in the **hosted** flow. Independent of this PR; documented for completeness, not required
once the native flow ships.

## 9. Known edge cases

- **Brave (Shields up) / Safari ITP / Firefox strict:** One-Tap is suppressed (3rd-party cookies). The
  button-click path is unaffected. No code change required for compatibility.
- **Popup blocked:** GIS surfaces a re-prompt; the user clicks again.
- **Captcha:** if Supabase captcha is enabled, `signInWithIdToken` requires a captcha token (supabase/auth#1172) —
  confirm captcha is off for this project or wire the token.
