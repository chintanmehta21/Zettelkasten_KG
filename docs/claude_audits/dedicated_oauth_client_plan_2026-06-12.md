# Dedicated Google OAuth Client (clean project) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate native Google sign-in for zettelkasten.in using a **dedicated OAuth client in a brand-new, clean Google Cloud project** that requests only `openid email profile` — so brand verification completes in days (not the multi-week CASA security assessment the reused Nexus YouTube client would force).

**Architecture:** The native `signInWithIdToken` server-side code-exchange flow is already built + deployed **dormant** (PR #135, master). The backend resolves credentials `GOOGLE_OAUTH_CLIENT_ID/SECRET` **first**, then `NEXUS_YOUTUBE_*`. So adopting a dedicated client requires **zero code re-architecture** — only (A) repo docs/comments that stop steering toward the trap, (B) Google Cloud console setup of the new project/client, (C) Supabase Authorized Client IDs, (D) droplet env activation, (E) live verification.

**Tech Stack:** FastAPI (`website/api/routes.py`), Supabase Auth (`supabase.auth.signInWithIdToken`), Google Identity / OAuth 2.0, Docker Compose blue/green on a DigitalOcean droplet, GitHub Actions deploy.

**Why dedicated, not reuse (deep-research verdict, 2026-06-12, primary-sourced):** Google OAuth verification is administered **per Cloud project**; a project's single consent screen aggregates **all** its clients' scopes, so the Nexus project's **restricted** YouTube Data API scope taints the sign-in consent screen → mandatory CASA/App-Defense-Alliance assessment ("several weeks"). A clean project requesting only non-sensitive scopes needs **brand verification only** (name+logo, ~2-3 business days), and non-sensitive-only apps need **no scope verification at all**. Sources: [restricted-scope-verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification), [brand-verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification), [authentication-policy-compliance](https://developers.google.com/identity/verification/authentication-policy-compliance), [Supabase Login with Google](https://supabase.com/docs/guides/auth/social-login/auth-google).

---

## Prerequisites & watch-outs (confirm before starting)

- [ ] **Domain ownership for `zettelkasten.in`** is (or will be) verified in **Google Search Console under the same Google account that will own the NEW project**. Brand verification's homepage/authorized-domain check fails without it.
- [ ] **Do NOT touch the existing Nexus YouTube OAuth client / its project** — YouTube ingestion keeps working; this plan only *adds* a separate project.
- [ ] **Go live promptly** — Google's Oct-2025 policy auto-deletes OAuth clients left unused; don't create the client weeks before activating.
- [ ] The homepage requirement is already satisfied: `/about` describes the app, `/privacy` + `/terms` exist (commit `bd1c02ad`). No new pages needed.
- [ ] Until brand verification lands, the consent screen shows the **domain** (`zettelkasten.in`), not the name — that is still correct behavior, not a failure.

---

## File Structure (repo changes — Phase A only; everything else is console/ops)

| File | Responsibility | Change |
|---|---|---|
| `ops/.env.example` | Operator env template | Make dedicated `GOOGLE_OAUTH_*` the **recommended** path; demote `NEXUS_YOUTUBE_*` reuse to discouraged (trap note) |
| `docs/claude_audits/google_oauth_consent_branding_2026-05-31.md` | The activation runbook | Replace "reuse Nexus client" guidance with "dedicated clean-project client" + the verdict |
| `website/api/routes.py` | Credential resolver docstrings | Note dedicated client is preferred; Nexus reuse causes the restricted-scope trap (no behavior change) |

No source-logic or test changes: the resolver precedence (`GOOGLE_OAUTH_*` over `NEXUS_YOUTUBE_*`) and its coverage (`tests/integration/test_google_native_auth.py::TestNexusYoutubeCredentialReuse::test_dedicated_google_client_takes_precedence`) already exist and pass.

---

## Phase A — Repo docs/comments (in worktree `claude/oauth-dedicated-client`)

### Task A1: `.env.example` — recommend the dedicated client

**Files:** Modify `ops/.env.example` (the "Google native sign-in" block).

- [ ] **Step 1: Read the current block** — `Read ops/.env.example` and locate the `# ── Google native sign-in …` section so you have the exact anchor lines.

- [ ] **Step 2: Replace the credential-resolution comment** so the dedicated client is primary. New wording:

```
# Credential resolution: the backend reads GOOGLE_OAUTH_CLIENT_ID/SECRET first,
# else falls back to NEXUS_YOUTUBE_CLIENT_ID/SECRET. RECOMMENDED: a DEDICATED
# OAuth client in a NEW, clean Google Cloud project that requests only
# openid/email/profile. Do NOT reuse the Nexus YouTube client: its project also
# requests RESTRICTED YouTube scopes, and Google verifies per-project, so reuse
# drags the sign-in consent screen into a multi-week CASA security assessment.
# A clean project needs only brand verification (~2-3 business days).
```

- [ ] **Step 3: Reorder the example vars** so the dedicated pair is shown first and the Nexus reuse is marked discouraged:

```
# GOOGLE_NATIVE_SIGNIN_ENABLED=true   # master switch — OFF by default; flip LAST
# GOOGLE_OAUTH_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com       # RECOMMENDED: dedicated clean-project client
# GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxx           # RECOMMENDED: dedicated client secret
# PUBLIC_BASE_URL=https://zettelkasten.in
# (Discouraged fallback — restricted-scope trap: NEXUS_YOUTUBE_CLIENT_ID / NEXUS_YOUTUBE_CLIENT_SECRET)
```

- [ ] **Step 4: Verify the knob-drift gate still passes** — the gate only checks `^RAG_|^GUNICORN_|^GEMINI_COOLDOWN_` uncommented knobs, and all additions here are comments, so it is unaffected. Confirm by grepping: 

Run: `grep -nE '^(GOOGLE_|PUBLIC_|NEXUS_)' ops/.env.example`
Expected: no output (all lines are comments).

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/oauth-plan"
git add ops/.env.example
git commit -m "docs: recommend dedicated google oauth client over nexus reuse"
```

### Task A2: `routes.py` — resolver docstrings note the trap

**Files:** Modify `website/api/routes.py` (`_google_client_id`, `_google_client_secret`).

- [ ] **Step 1: Read** the two functions to get the exact current docstrings.

- [ ] **Step 2: Update `_google_client_id` docstring** to:

```python
def _google_client_id() -> str:
    """Public OAuth client id for native Google sign-in.

    Prefer a DEDICATED ``GOOGLE_OAUTH_CLIENT_ID`` from a clean Google Cloud
    project that requests only openid/email/profile. ``NEXUS_YOUTUBE_CLIENT_ID``
    is a fallback only — reusing the Nexus client is DISCOURAGED because Google
    verifies per-project and that project's restricted YouTube scope drags the
    consent screen into a multi-week CASA assessment. Client ids are public, so
    exposing the resolved value via /api/auth/config is safe.
    """
```

- [ ] **Step 3: Update `_google_client_secret` docstring** to:

```python
def _google_client_secret() -> str:
    """Server-only OAuth client secret (code→token exchange).

    Same precedence as :func:`_google_client_id` — prefer the dedicated
    ``GOOGLE_OAUTH_CLIENT_SECRET``; ``NEXUS_YOUTUBE_CLIENT_SECRET`` is a
    discouraged fallback.
    """
```

- [ ] **Step 4: Confirm no behavior change** — the function bodies are unchanged (precedence already `GOOGLE_OAUTH_*` → `NEXUS_YOUTUBE_*`). Run the resolver tests:

Run: `python -m pytest tests/integration/test_google_native_auth.py -q`
Expected: PASS (all, incl. `test_dedicated_google_client_takes_precedence`).

- [ ] **Step 5: Commit**

```bash
git add website/api/routes.py
git commit -m "docs: note dedicated-client preference in resolver docstrings"
```

### Task A3: Runbook — swap "reuse Nexus" for "dedicated client"

**Files:** Modify `docs/claude_audits/google_oauth_consent_branding_2026-05-31.md` (§4 selected approach, §7a client step, §7c droplet env).

- [ ] **Step 1: Read** §4 and §7 to get exact anchors.

- [ ] **Step 2: In §7a**, change the "reuse the existing Google OAuth client" recommendation to: create a **dedicated Web client in a NEW, clean Google Cloud project**, scopes only `openid email profile`, redirect URI `https://zettelkasten.in/api/auth/google/callback`. Keep one sentence noting reuse is possible but discouraged (restricted-scope trap), linking this plan.

- [ ] **Step 3: In §7c**, change the credential guidance to set `GOOGLE_OAUTH_CLIENT_ID/SECRET` (dedicated) rather than `NEXUS_YOUTUBE_*`.

- [ ] **Step 4: Add a one-line pointer** at the top of §7: "See `docs/claude_audits/dedicated_oauth_client_plan_2026-06-12.md` for the verified rationale (dedicated client, not Nexus reuse)."

- [ ] **Step 5: Commit**

```bash
git add docs/claude_audits/google_oauth_consent_branding_2026-05-31.md
git commit -m "docs: runbook adopts dedicated oauth client path"
```

### Task A4: Open PR for Phase A

- [ ] **Step 1: Push + PR**

```bash
git push -u origin claude/oauth-dedicated-client
gh pr create --base master --title "docs: adopt dedicated google oauth client (avoid restricted-scope trap)" \
  --body "Per deep-research verdict (2026-06-12): recommend a dedicated clean-project OAuth client over reusing the Nexus YouTube client. Docs/comments only — no behavior change (resolver already prefers GOOGLE_OAUTH_*). Plan: docs/claude_audits/dedicated_oauth_client_plan_2026-06-12.md"
```

- [ ] **Step 2: Rebase-merge** after CI green: `gh pr merge --rebase` (per repo merge policy).

---

## Phase B — Google Cloud Console (operator; cannot be automated)

> All steps in the **[Google Cloud Console]** for a **NEW project**. Use the project picker (top bar) to create + stay in the new project for every sub-step.

### Task B1: Create the clean project
- [ ] [Google Cloud Console] [console.cloud.google.com/projectcreate](https://console.cloud.google.com/projectcreate) → name `Zettelkasten Auth` (or similar) → **Create**. Select it in the project picker.

### Task B2: Branding
- [ ] [Branding] [console.cloud.google.com/auth/branding](https://console.cloud.google.com/auth/branding) → **App name** `Zettelkasten`; **User support email**; **App logo** (square ≥120×120, ≤1 MB).
- [ ] **Authorized domains** → add `zettelkasten.in` (must be verified in Search Console under THIS account first).
- [ ] **App domain** → Home `https://zettelkasten.in/about`; Privacy `https://zettelkasten.in/privacy`; Terms `https://zettelkasten.in/terms`. **Save.**

### Task B3: Data Access — non-sensitive scopes ONLY
- [ ] [Data Access] [console.cloud.google.com/auth/scopes](https://console.cloud.google.com/auth/scopes) → ensure ONLY `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`. **Add no YouTube / sensitive / restricted scopes.** (This is the whole point — keeps the project on the brand-only path.)

### Task B4: OAuth client
- [ ] [Clients] [console.cloud.google.com/auth/clients](https://console.cloud.google.com/auth/clients) → **Create client** → type **Web application** → name `Zettelkasten Web`.
- [ ] **Authorized redirect URIs** → add exactly `https://zettelkasten.in/api/auth/google/callback`.
- [ ] **Create** → copy the **Client ID** and **Client secret** (store the secret securely; you'll paste it on the droplet, never into chat).

### Task B5: Publish + verify branding
- [ ] [Audience] [console.cloud.google.com/auth/audience](https://console.cloud.google.com/auth/audience) → User type **External** → **Publish app** (Testing → Production).
- [ ] [Branding] → **Verify Branding** → track at [Verification Center](https://console.cloud.google.com/auth/verification). Non-sensitive-only ⇒ no scope/security review; brand check only.

---

## Phase C — Supabase

### Task C1: Trust the new client for signInWithIdToken
- [ ] [Supabase Dashboard] Auth → Providers → Google → **Authorized Client IDs** → add the **new** Client ID from Task B4. (signInWithIdToken validates the id_token `aud` against this list; without it sign-in fails.) Keep nonce handling as-is (our flow sends no nonce).

---

## Phase D — Droplet activation

### Task D1: Set env in `.env.local` + recreate the live container

- [ ] [droplet SSH] Add the vars (dedicated client; the master switch goes in LAST):

```bash
cd /opt/zettelkasten/compose
grep -E 'GOOGLE_OAUTH|GOOGLE_NATIVE|PUBLIC_BASE_URL' .env.local 2>/dev/null || echo "(none yet)"
cat >> .env.local <<'EOF'
GOOGLE_OAUTH_CLIENT_ID=<paste dedicated client id>
GOOGLE_OAUTH_CLIENT_SECRET=<paste dedicated client secret>
PUBLIC_BASE_URL=https://zettelkasten.in
GOOGLE_NATIVE_SIGNIN_ENABLED=true
EOF
```

- [ ] [droplet SSH] Recreate the active container so it reloads `.env` + `.env.local` (~few-second blip):

```bash
cd /opt/zettelkasten/compose
ACTIVE=$(cat /opt/zettelkasten/ACTIVE_COLOR)
IMAGE_TAG=$(grep '^DEPLOY_GIT_SHA=' .env | cut -d= -f2) \
  docker compose -f docker-compose.$ACTIVE.yml --env-file .env \
  up -d --force-recreate --no-deps zettelkasten-$ACTIVE
docker logs --tail 20 zettelkasten-$ACTIVE
```

- [ ] **Verify dormant→active flip via the config endpoint** (run in a browser console on zettelkasten.in, since Cloudflare blocks bare curl):

Run: `await (await fetch('/api/auth/config')).json()`
Expected: `google_client_id` is now the **dedicated** client id (non-empty), not `""`.

---

## Phase E — Verify + rollback

### Task E1: Live end-to-end (driven by the assistant)
- [ ] Assistant runs Claude-in-Chrome: click **Sign in with Google** on zettelkasten.in → consent screen reads **"to continue to zettelkasten.in"** (name "Zettelkasten" once brand verification lands) → after consent, lands on `/home` signed in.
- [ ] Assistant pulls droplet logs (**Read Recent Logs** workflow) to confirm `/api/auth/google/start` → `/api/auth/google/callback` (200) → handoff, with no errors and no secret in logs.

### Task E2: Rollback (keep handy)
- [ ] [droplet SSH] Instant revert to the legacy flow: remove the `GOOGLE_NATIVE_SIGNIN_ENABLED=true` line from `.env.local` and re-run the recreate command from Task D1. `google_client_id` returns to `""`, frontend reverts to `signInWithOAuth`.

---

## Self-Review

- **Spec coverage:** RQ#1/#4 (per-project verification, dedicated client) → Phase B1+B3+B4 + A1-A3. RQ#2/#3 (brand vs scope verification, Production+verify to show name) → B5. RQ#5 (homepage purpose) → already satisfied (prereqs). Activation/UX → C1, D1, E1. Cost (free, no custom domain) → no paid steps anywhere. ✓
- **Placeholder scan:** No "TBD"/"handle edge cases"; secret values are intentionally `<paste …>` (operator-entered, never in repo/chat) — these are inputs, not code placeholders. ✓
- **Consistency:** env names (`GOOGLE_OAUTH_CLIENT_ID/SECRET`, `GOOGLE_NATIVE_SIGNIN_ENABLED`, `PUBLIC_BASE_URL`), redirect URI (`/api/auth/google/callback`), and `.env.local` path match `routes.py` + `deploy.sh` + compose `env_file` exactly. ✓
