# Auth Provider Registry (Web)

## Summary
Centralize the web auth provider list in client-side JavaScript while keeping the UI and flows exactly the same. Add minimal tests that lock the provider list in HTML and JS so they cannot drift.

## Goals
- Keep the end-user login experience identical.
- Single source of truth for provider list in `auth.js`.
- Preserve existing email/password modal and provider dropdown.
- Add low-friction tests to prevent drift.

## Non-Goals
- No UI/UX changes, layout changes, or provider re-ordering.
- No backend registry or API changes.
- No changes to auth callback flow or storage behavior.

## Current State
- The header dropdown already lists Google, GitHub, Apple, Twitter, Facebook, Twitch.
- The modal is email/password and includes a Google button.
- OAuth calls are provider-agnostic (`signInWithOAuth(provider)`).
- `/auth/callback` exists and handles OAuth exchange.

## Proposed Changes
1. Add a provider registry array to `website/features/user_auth/js/auth.js`.
2. Bind provider click handlers using the registry (no changes to HTML or CSS).
3. Add tests to confirm:
   - The HTML dropdown contains the full provider list.
   - The JS registry contains the same provider list.

## Data Flow
- User clicks a provider in header dropdown.
- Handler looks up `data-provider`, validates against registry, calls OAuth.
- Callback and session restore unchanged.

## Test Plan
- Add a unit test that parses `website/static/index.html` and checks all expected `data-provider` values are present.
- Add a unit test that parses `website/features/user_auth/js/auth.js` and checks the registry list.
- Run `python -m pytest tests/test_auth.py -v` plus new test file.

## Local/Dev URL Assumption
- OAuth redirect URL for local dev: `http://localhost:8443/auth/callback`.
  - This aligns with webhook mode default port `8443`.

## Risks and Mitigations
- Risk: Provider list changes without updates in HTML/JS.
  - Mitigation: new tests to keep them in sync.

## Rollout
- Safe to deploy without user-visible changes.
- Providers still require Supabase dashboard enablement to work.
