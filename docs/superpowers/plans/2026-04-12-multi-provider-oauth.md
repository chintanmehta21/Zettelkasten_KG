# Plan: Multi-Provider OAuth Login (GitHub + Twitter)

**Date:** 2026-04-12  
**Status:** Ready to execute  
**Scope:** Enable GitHub and Twitter sign-in via Supabase OAuth. Reuse NEXUS_GITHUB and NEXUS_TWITTER keys from `new_envs.txt`. Clean up the header dropdown to reflect which providers are actually active.

---

## Phase 0: Documentation Discovery — DONE

### Key Facts

**`signInWithProvider(provider)` already handles any Supabase provider:**
- File: `website/features/user_auth/js/auth.js:358-374`
- Calls `_supabaseClient.auth.signInWithOAuth({ provider, options: { redirectTo: origin + '/auth/callback' } })`
- No JS code changes needed to support new providers — just enable them in Supabase Dashboard

**Provider strings Supabase expects:**
- Google → `'google'` ✓ (working)
- GitHub → `'github'`
- Twitter/X → `'twitter'` (Supabase uses `'twitter'`, not `'x'`)

**Backend is provider-agnostic:**
- `website/api/auth.py` validates JWTs via JWKS from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
- Works identically for any Supabase-issued token regardless of provider
- Zero backend changes needed

**DB trigger handles all providers:**
- `supabase/website/user_auth/schema.sql:11-43`
- Auto-provisions `kg_users` row on first sign-up, pulls `full_name` + `avatar_url`/`picture` from OAuth metadata
- Zero SQL changes needed

**Available credentials (from `new_envs.txt`):**
| Provider | Variable | Status |
|----------|----------|--------|
| Google   | Already in Supabase | ✓ Live |
| GitHub   | `NEXUS_GITHUB_CLIENT_ID` + `NEXUS_GITHUB_CLIENT_SECRET` | Ready |
| Twitter  | `NEXUS_TWITTER_CLIENT_ID` + `NEXUS_TWITTER_CLIENT_SECRET` | Ready |
| Apple    | None in `new_envs.txt` | Skip → disable in grid |
| Facebook | None in `new_envs.txt` | Skip → disable in grid |
| Twitch   | None in `new_envs.txt` | Skip → disable in grid |

**Supabase OAuth callback URL (same for all providers):**
- `https://<project-ref>.supabase.co/auth/v1/callback`
- Find the project ref in `supabase/.env` → `SUPABASE_URL`

**Files that need code changes (Phase 3 only):**
- `website/static/index.html` — add GitHub + Twitter buttons to modal; disable Apple/Facebook/Twitch in grid
- `website/features/user_auth/css/auth.css` — add multi-button modal layout if needed

---

## Phase 1: GitHub OAuth — Manual Dashboard Steps

> **Environment:** Browser (GitHub + Supabase dashboards)  
> No code changes in this phase.

### Step 1a — Update the GitHub OAuth App's callback URL

The `NEXUS_GITHUB_CLIENT_ID` app was created for the Nexus feature. Its callback URL must include the Supabase auth callback so Supabase can complete the OAuth flow.

1. Go to: `https://github.com/settings/developers` → **OAuth Apps**
2. Click the app whose Client ID matches `NEXUS_GITHUB_CLIENT_ID` (value in `new_envs.txt`)
3. Under **Authorization callback URL**, ensure it includes:
   ```
   https://<supabase-project-ref>.supabase.co/auth/v1/callback
   ```
   (If the app already had a Nexus-specific callback, GitHub only allows ONE callback URL per OAuth App. Add the Supabase URL — if Nexus needed its own, separate apps are needed. For now, replace with the Supabase one since Nexus login flow is not in use.)
4. Save changes

### Step 1b — Enable GitHub provider in Supabase Dashboard

1. Go to: Supabase Dashboard → **Authentication** → **Providers** → **GitHub**
2. Toggle **Enable GitHub provider** → ON
3. Enter:
   - **Client ID:** value of `NEXUS_GITHUB_CLIENT_ID` from `new_envs.txt`
   - **Client Secret:** value of `NEXUS_GITHUB_CLIENT_SECRET` from `new_envs.txt`
4. **Callback URL shown by Supabase** — copy this and verify it matches what you set in Step 1a
5. Click **Save**

### Verification — Phase 1

- Open the app in a browser, click the dropdown arrow next to Login
- Click **GitHub** in the provider grid
- Should redirect to GitHub → authorize → redirect back to `/auth/callback` → redirect to `/home`
- Check Supabase Dashboard → **Authentication** → **Users** — new user row with GitHub provider metadata should appear
- `grep` check: confirm no new JS was needed — `signInWithProvider('github')` in `auth.js:358` was already present

---

## Phase 2: Twitter OAuth — Manual Dashboard Steps

> **Environment:** Browser (Twitter Developer Portal + Supabase dashboard)  
> No code changes in this phase.

### Step 2a — Verify Twitter app uses OAuth 2.0

Supabase's Twitter provider requires **OAuth 2.0** (not OAuth 1.0a).

1. Go to: `https://developer.twitter.com/en/portal/projects-and-apps`
2. Find the app whose Client ID matches `NEXUS_TWITTER_CLIENT_ID` (value in `new_envs.txt`)
3. Under **User authentication settings**, ensure:
   - **OAuth 2.0** is enabled (not just OAuth 1.0a)
   - **Type of App**: Web App
   - **Callback URI / Redirect URL** includes:
     ```
     https://<supabase-project-ref>.supabase.co/auth/v1/callback
     ```
4. Save settings

### Step 2b — Enable Twitter provider in Supabase Dashboard

1. Go to: Supabase Dashboard → **Authentication** → **Providers** → **Twitter**
2. Toggle **Enable Twitter provider** → ON
3. Enter:
   - **API Key (Client ID):** value of `NEXUS_TWITTER_CLIENT_ID` from `new_envs.txt`
   - **API Secret (Client Secret):** value of `NEXUS_TWITTER_CLIENT_SECRET` from `new_envs.txt`
4. **Callback URL shown by Supabase** — copy and verify it matches Step 2a
5. Click **Save**

### Verification — Phase 2

- Click **Twitter** in the header dropdown
- Should redirect to Twitter/X → authorize → redirect back to `/auth/callback` → `/home`
- Check Supabase → **Authentication** → **Users** — new row with Twitter provider

---

## Phase 3: UI Code Changes

> **Environment:** Git Bash (code editor)  
> This phase has the only code changes.

### 3a — Add GitHub and Twitter buttons to the login modal

**File:** `website/static/index.html`  
**Location:** After the existing Google button at line 99-102

Replace:
```html
<button class="modal-oauth-btn" id="oauth-google">
    <svg viewBox="0 0 48 48">...</svg>
    Sign in with Google
</button>
```

With a social login row containing Google + GitHub + Twitter:
```html
<div class="modal-social-row">
    <button class="modal-oauth-btn" id="oauth-google" title="Sign in with Google">
        <svg viewBox="0 0 48 48"><!-- existing Google SVG --></svg>
        Google
    </button>
    <button class="modal-oauth-btn modal-oauth-github" id="oauth-github" title="Sign in with GitHub">
        <svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>
        GitHub
    </button>
    <button class="modal-oauth-btn modal-oauth-twitter" id="oauth-twitter" title="Sign in with Twitter">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
        Twitter
    </button>
</div>
```

### 3b — Wire GitHub and Twitter buttons in auth.js

**File:** `website/features/user_auth/js/auth.js`  
**Two locations to update:**

**resolveDOM() function (around line 23-39)** — add two new element refs:
```javascript
oauthGithub = document.getElementById('oauth-github');
oauthTwitter = document.getElementById('oauth-twitter');
```
(Also declare `var oauthGithub, oauthTwitter;` at top of module with the other vars)

**Event wiring section (around line 318-325)** — add after the Google handler:
```javascript
if (oauthGithub) {
    oauthGithub.addEventListener('click', function () {
        signInWithProvider('github');
    });
}
if (oauthTwitter) {
    oauthTwitter.addEventListener('click', function () {
        signInWithProvider('twitter');
    });
}
```

### 3c — Disable uncredentialed providers in the header grid

**File:** `website/static/index.html`  
**Lines 49-64** — add `data-disabled="true"` and `title` to Apple, Facebook, Twitch items:
```html
<div class="provider-item provider-disabled" data-provider="apple" title="Coming soon">
    ...Apple SVG + name...
</div>
<div class="provider-item provider-disabled" data-provider="facebook" title="Coming soon">
    ...Facebook SVG + name...
</div>
<div class="provider-item provider-disabled" data-provider="twitch" title="Coming soon">
    ...Twitch SVG + name...
</div>
```

**File:** `website/features/user_auth/css/auth.css`  
Add after the `.provider-item` hover rules:
```css
.provider-item.provider-disabled {
    opacity: 0.35;
    cursor: not-allowed;
    pointer-events: none;
}
```

### 3d — Add modal social row CSS

**File:** `website/features/user_auth/css/auth.css`  
Find the existing `.modal-oauth-btn` rules and add a container:
```css
.modal-social-row {
    display: flex;
    gap: 0.5rem;
}

.modal-social-row .modal-oauth-btn {
    flex: 1;
    justify-content: center;
    font-size: 0.82rem;
    padding: 0.6rem 0.5rem;
}

.modal-oauth-github {
    color: #e6edf3;
}

.modal-oauth-twitter {
    color: #e6edf3;
}
```

### Verification — Phase 3

```bash
# Git Bash — project root
grep -n "oauth-github\|oauth-twitter" website/static/index.html
grep -n "oauth-github\|oauth-twitter\|oauthGithub\|oauthTwitter" website/features/user_auth/js/auth.js
grep -n "provider-disabled\|modal-social-row" website/features/user_auth/css/auth.css
```

Expected: each grep returns at least 2 hits.

---

## Phase 4: End-to-End Verification

> **Environment:** Browser (app running locally or on droplet)

### Checklist

- [ ] **Google login** still works (regression check)
- [ ] **GitHub login**: dropdown → GitHub → GitHub OAuth page → callback → `/home` → user avatar shown
- [ ] **Twitter login**: dropdown → Twitter → Twitter OAuth page → callback → `/home` → user avatar shown
- [ ] **Modal buttons**: click Login button → modal shows 3 side-by-side buttons (Google, GitHub, Twitter)
- [ ] **Modal GitHub**: click GitHub button in modal → same OAuth flow works
- [ ] **Modal Twitter**: click Twitter button in modal → same OAuth flow works
- [ ] **Disabled grid items**: Apple/Facebook/Twitch in dropdown are greyed out and unclickable
- [ ] **Supabase Users table**: shows separate rows for Google, GitHub, and Twitter test accounts
- [ ] **Email login**: still works (no regression)
- [ ] **Logout**: clears session across all providers correctly

### Anti-pattern checks

```bash
# Git Bash
# Ensure no purple crept in
grep -rn "purple\|violet\|lavender\|#A78BFA\|hsl(2[5-9][0-9]\|hsl(28[0-9]" website/features/user_auth/css/auth.css

# Ensure provider name is lowercase string (Supabase is case-sensitive)
grep -n "signInWithProvider" website/features/user_auth/js/auth.js
# Confirm values are: 'google', 'github', 'twitter' — not 'Google', 'GitHub', 'Twitter', 'x'

# Ensure no hardcoded client IDs in JS (they come from Supabase-managed config)
grep -n "NEXUS_" website/features/user_auth/js/auth.js
# Should return 0 hits
```

---

## Sequencing & Dependencies

```
Phase 1 (manual: GitHub Supabase setup)
    ↓
Phase 2 (manual: Twitter Supabase setup)
    ↓  [can start Phase 3 in parallel with Phase 1+2]
Phase 3 (code: modal UI + grid cleanup)
    ↓
Phase 4 (verify all providers end-to-end)
```

Phase 3 can be coded before Phases 1 and 2 are complete (the buttons will just redirect and fail until the providers are enabled). Safer to do the Supabase setup first so you can immediately test each button as you add it.

---

## Notes

- **No `.env` changes needed** — provider credentials go into Supabase Dashboard directly; the frontend only needs `SUPABASE_URL` + `SUPABASE_ANON_KEY` which are already set.
- **Twitter OAuth 2.0**: The NEXUS Twitter app must have OAuth 2.0 enabled. If it was only OAuth 1.0a (older Nexus design), you'll need to enable OAuth 2.0 in the Twitter Developer Portal for that app.
- **GitHub callback URL limit**: GitHub OAuth Apps allow only one callback URL (unlike Google). Supabase's callback URL replaces any Nexus-specific one unless you create a separate GitHub OAuth App for Supabase.
- **No new test files needed** — the auth flow is end-to-end browser tested; unit tests for `signInWithProvider` already stub `_supabaseClient`.
