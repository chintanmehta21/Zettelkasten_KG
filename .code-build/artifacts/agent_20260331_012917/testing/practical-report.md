# Practical Test Report — User Auth

## Test Environment
- Local dev server: http://127.0.0.1:8765
- Browser: Playwright Chromium
- Date: 2026-03-31

## Test Results

### 1. Homepage — Login Button Placement
**Status: PASS**
- Login button visible at top-right of header
- Google icon SVG renders correctly alongside "Login" text
- Teal accent border, dark theme — consistent with design system
- Logo ("Zettelkasten") on the left, login button on the right
- Tagline ("AI-powered link summarizer") centered below
- No purple colors anywhere
- Screenshot: `homepage-screenshot.png`

### 2. Auth Callback Page
**Status: PASS**
- Route `/auth/callback` serves the callback HTML
- Without a code parameter, shows error: "Sign-in failed: invalid request: both auth code and code verifier should be non-empty"
- Error displayed in red text with teal "Back to home" link
- Spinner hidden on error — correct behavior
- Screenshot: `callback-screenshot.png`

### 3. Auth Config Endpoint
**Status: PASS**
- `GET /api/auth/config` returns JSON with correct Supabase project URL and anon key
- Response: `{"supabase_url":"https://wcgqmjcxlutrmbnijzyz.supabase.co","supabase_anon_key":"sb_publishable_..."}`

### 4. Protected Endpoint (/api/me)
**Status: PASS**
- `GET /api/me` without Authorization header returns `{"detail":"Not authenticated"}` (401)

### 5. Supabase Schema
**Status: PASS**
- `handle_new_user()` trigger function applied successfully via Supabase MCP
- `on_auth_user_created` trigger attached to `auth.users`

### 6. Backwards Compatibility
**Status: PASS**
- Homepage renders correctly with all existing features
- Summarize form, Knowledge Graph CTA, footer — all intact
- No visual regressions

## Overall: PASS
All 6 checks passed. The Login button is correctly placed, auth endpoints work, and the Supabase schema is deployed.
