# Supabase Auth Research Report

## Recommended Architecture

### Flow: PKCE (Proof Key for Code Exchange) — BEST FOR THIS PROJECT
- Browser generates code_verifier, hashes to code_challenge
- Google redirects back with authorization code (not tokens)
- Code exchanged for session via supabase-js `exchangeCodeForSession()`
- More secure than implicit flow; works with server-side validation

### Client-Side: supabase-js via CDN (vanilla JS, no npm)
```html
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
```

Key APIs:
- `supabase.auth.signInWithOAuth({ provider: 'google' })` — triggers redirect
- `supabase.auth.onAuthStateChange(callback)` — session listener
- `supabase.auth.getSession()` — reads from localStorage (fast, no network call)
- `supabase.auth.signOut()` — clears session

### Server-Side: JWT Validation in FastAPI
Two approaches ranked:
1. **JWKS (RS256)** — Best practice. Uses `PyJWKClient` to fetch public keys from Supabase
2. **HS256 with JWT Secret** — Simpler but less secure. Uses `SUPABASE_JWT_SECRET`

Recommended: Start with HS256 (project likely uses it), plan migration to JWKS.

### Database Linking: auth.users → kg_users
Two paths:
- **Path A (minimal)**: Reuse `render_user_id` TEXT column to store Supabase auth UUID. Zero schema change.
- **Path B (clean)**: Database trigger on `auth.users` INSERT to auto-create `kg_users` row with UUID FK.

Recommendation: Path B with trigger — cleaner, RLS policies work directly with `auth.uid()`.

### Session Management
- Sessions stored in localStorage (supabase-js default for non-SSR)
- Access token: 1hr default, auto-refreshed by supabase-js
- Refresh token: never expires, single-use, rotated on refresh
- `getSession()` is synchronous from localStorage (~0ms)

### Performance Optimizations for <5s Flow
1. Preload supabase-js CDN with `<link rel="preload">`
2. Preconnect to Supabase and Google domains
3. Initialize client in `<head>` before user interaction
4. Use redirect flow (simpler than popup, more reliable)
5. Local JWT validation (not auth.getUser() which is 200-600ms)
6. Optimistic UI from localStorage

### Google OAuth Setup Requirements
1. Google Cloud Console: Create OAuth client, set redirect URI to `https://<PROJECT-REF>.supabase.co/auth/v1/callback`
2. Supabase Dashboard: Enable Google provider, paste client ID/secret
3. Supabase URL Config: Add redirect URLs for `/auth/callback` and `/knowledge-graph`

### Environment Variables Needed
- `SUPABASE_URL` — already have
- `SUPABASE_ANON_KEY` — already have (safe for browser)
- `SUPABASE_SERVICE_ROLE_KEY` — already have (server-only)
- `SUPABASE_JWT_SECRET` — need from dashboard (Settings > API)
- `GOOGLE_OAUTH_CLIENT_ID` — user must create in Google Cloud Console
- `GOOGLE_OAUTH_CLIENT_SECRET` — user must create in Google Cloud Console

### Supabase Project Details
- URL: https://wcgqmjcxlutrmbnijzyz.supabase.co
- Reference ID: wcgqmjcxlutrmbnijzyz
- Access Token: Available in supabase/.env
