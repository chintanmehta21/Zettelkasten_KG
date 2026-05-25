# Mobile UI Fixes — Iteration 2a — Design Spec

| Field | Value |
|---|---|
| Date | 2026-05-25 |
| Iteration | 2a |
| Branch | `mobile-ui-fixes-2a` |
| Tracking PR | [Zettelkasten_KG#96](https://github.com/chintanmehta21/Zettelkasten_KG/pull/96) |
| Status | Design approved 2026-05-25; awaiting written-spec review before plan handoff |
| Scope | Mobile (`/m/*`) UI overhaul + cross-cutting avatar system (mobile + desktop) |
| Out of scope | Mobile Kasten chat/detail view (defers to dedicated PR); push notifications; bottom-sheet animation polish |

---

## 1. Locked decisions

| # | Decision | Source |
|---|---|---|
| D1 | PWA install: dismissible banner on `/m/` above the capture form **+** persistent header icon as fallback after first banner dismissal | Q1 |
| D2 | Hamburger button inside URL textbox opens a bottom sheet with the 6 source-override options (Auto / YouTube / GitHub / Reddit / Newsletter / Web); replaces the removed `Auto-detect source` dropdown | Q2 |
| D3 | Anonymous user clicks Summarize → `/m/zettels?just_captured=<id>` showing **only** the freshly captured zettel + sticky sign-in nudge overlay | Q3 |
| D4 | Avatar system is cross-cutting: Supabase-stored `avatar_url` pointing at one of 60 self-hosted SVGs in `website/artifacts/avatars/`. Auto-random assignment at signup. User-changeable on Profile. Applies to mobile AND desktop. Google `picture` fallback removed | Q4 |
| D5 | Avatar source = existing folder `website/artifacts/avatars/` (60 SVGs, ~616 KB total) — no third-party service, no DiceBear | Q5 |
| D6 | Mobile Zettels = lean port: search + filter-sheet + list + fullscreen detail modal. No hero, no stats, no Add-Zettel form | Q6 |
| D7 | Mobile Kastens = lean port: grid + Create FAB. No hero, no stats. Tap-a-Kasten in 2a opens the existing desktop view in the same tab | Q7 + open-item 1 |
| D8 | Mobile Zettels filter sheet exposes: source, tag, date-range, sort (parity with desktop) | Open-item 2 |
| D9 | Glassmorphism applied **only** to the bottom navbar (per CLAUDE.md teal/amber rule; nowhere else) | User spec |
| D10 | Bottom-nav glass recipe = `rgba(10,11,20,0.68)` + `blur(16px) saturate(170%)` + teal 14% hairline + opaque fallback (research-derived) | Research |

---

## 2. Files created / modified

### Created

```
website/mobile/
  zettels.html
  kastens.html
  profile.html
  js/
    install-prompt.js       PWA install banner + header icon controller
    hamburger-sheet.js      Reusable bottom-sheet primitive (source picker, filter picker)
    zettels.js              List + detail-modal + ?just_captured handling
    kastens.js              Grid + Create-FAB
    profile.js              Avatar picker + sign-out
    avatar.js               Shared avatar renderer (mobile + desktop)
  css/
    components/
      glass-nav.css
      install-banner.css
      hamburger-sheet.css
      avatar-picker.css
      footer.css            Mobile-sized variant of desktop footer
    pages/
      zettels.css
      kastens.css
      profile.css

website/features/user_profile/        NEW backend feature
  __init__.py
  routes.py                            GET /api/profile, PATCH /api/profile
  models.py                            UserProfile DTO (Pydantic)
  repository.py                        Supabase calls (avatar_url upsert in raw_user_meta_data)

website/features/user_auth/
  signup_hook.py                       Optional defensive backstop if Supabase trigger ever misfires

supabase/website/_v2/
  53_user_default_avatar.sql           Trigger + backfill + Zoro pin + GRANTs

docs/superpowers/specs/
  2026-05-25-mobile-ui-fixes-2a-design.md   This file
```

### Modified

```
website/app.py                          Add 3 routes (/m/zettels, /m/kastens, /m/profile); add /artifacts/avatars/ mount with immutable cache headers
website/mobile/index.html               Header markup (logo, drop title, install icon, avatar); capture-form hamburger; remove inline summary; redirect-after-submit
website/mobile/templates/_shell.html    Bottom-nav HTML (renames, enable disabled tabs, glass class)
website/mobile/css/mobile.css           Import new component CSS; drop old title styles
website/mobile/js/auth-modal.js         Switch to avatar.js for rendering; drop Google `picture` fallback
website/mobile/js/summarizer.js         Remove inline-result rendering; redirect on success
website/features/user_home/js/home.js   Use avatar.js; drop Google `picture` fallback
website/features/user_zettels/...       Desktop unchanged in this PR EXCEPT desktop avatar render path (single switch in home.js + header.js)
```

---

## 3. Architecture

### 3.1 Routing & auth-gating

Three new mobile routes added inline to `website/app.py`. Gate pattern follows existing `FunctionalGates` style — inline guard in route handler, no decorator/middleware (matches the codebase's idiom).

```python
def _has_supabase_session(request: Request) -> bool:
    return bool(request.cookies.get("sb-access-token") or request.cookies.get("sb-refresh-token"))

@app.get("/m/zettels")
async def mobile_zettels(request: Request):
    if not _has_supabase_session(request):
        return RedirectResponse("/m/profile", status_code=302)
    return _render_with_mobile_shell(MOBILE_DIR / "zettels.html", page_title="Zettels", body_class="m-zettels")

@app.get("/m/kastens")
async def mobile_kastens(request: Request):
    if not _has_supabase_session(request):
        return RedirectResponse("/m/profile", status_code=302)
    return _render_with_mobile_shell(MOBILE_DIR / "kastens.html", page_title="Kastens", body_class="m-kastens")

@app.get("/m/profile")
async def mobile_profile(request: Request):
    return _render_with_mobile_shell(MOBILE_DIR / "profile.html", page_title="Profile", body_class="m-profile")
```

Anonymous Summarize → `/m/zettels?just_captured=<id>` bypasses the redirect because the request is unauth but carries an in-session capture; resolved by an exception in the gate:

```python
async def mobile_zettels(request: Request):
    if not _has_supabase_session(request) and "just_captured" not in request.query_params:
        return RedirectResponse("/m/profile", status_code=302)
    ...
```

### 3.2 Avatar serving

- New static mount in `website/app.py`:
  ```python
  app.mount("/artifacts/avatars", StaticFiles(directory=str(Path(__file__).parent / "artifacts" / "avatars")), name="avatars")
  ```
- Custom middleware (or response header on the mount via a custom `StaticFiles` subclass) sets `Cache-Control: public, max-age=31536000, immutable`.
- HTML shell injects `<link rel="preload" as="image" type="image/svg+xml" href="{user_avatar_url}">` server-side when the request has a session.
- Profile picker uses `IntersectionObserver` to lazy-render `<img>` tags for the 60 avatars (4-col mobile, 6-col desktop).
- Service-worker precache (existing `/sw.js`) updated to optionally cache the user's own avatar (not all 60 — would inflate first-visit cost).

### 3.3 Data flow

```
Page load (signed-in)
  └─> Server renders HTML with <link rel="preload" href="/artifacts/avatars/avatar_07.svg">
  └─> avatar.js reads window.__USER__.avatar_url, swaps in the <img>

Avatar change (Profile picker)
  └─> User taps avatar_22 in picker
  └─> Optimistic UI swap (teal ring → avatar_22 large preview)
  └─> PATCH /api/profile {avatar_url: "/artifacts/avatars/avatar_22.svg"}
       └─> repository.py: supabase.auth.admin.update_user_by_id(user_id, {user_metadata: {avatar_url: ...}})
       └─> Returns updated metadata
  └─> On 200, broadcast event so header avatar updates without reload
  └─> On error, revert and toast

Anonymous Summarize
  └─> POST /api/zettels/add (existing endpoint, anon goes to Zoro)
  └─> Client receives {id, ...}
  └─> window.location.assign("/m/zettels?just_captured=" + id)
       └─> /m/zettels route renders ONLY that zettel
       └─> Sticky bottom overlay: "Sign in to keep your collection"

Signed-in Summarize
  └─> Same flow, but no overlay; zettel persists under their account
```

### 3.4 Install prompt state machine

```
init
  ├─ display-mode: standalone  → hide all install affordances (terminal)
  ├─ appinstalled event         → set localStorage.pwa_installed=true, hide (terminal)
  └─ default → arm beforeinstallprompt listener (Chromium)
              + run UA-sniff for iOS+!standalone (Safari)

armed
  ├─ beforeinstallprompt fired → preventDefault, cache event, show banner
  ├─ iOS detected + !dismissed → show banner (Apple-share-glyph icon)
  ├─ dismissed within 30d      → hide banner, show header icon only
  └─ dismissed >30d ago        → re-show banner

banner click
  ├─ Chromium: prompt(), await userChoice, telemetry → hide banner
  └─ iOS:  open instructional sheet (Tap Share → Add to Home Screen)

banner dismiss (X)
  └─ localStorage.pwa_install_dismissed_at = now() → hide banner, show header icon
```

### 3.5 Auth modal vs Profile page

- Existing `_oauth_modal.html` + `auth-modal.js` continues to serve the avatar-click modal on `/m/` and `/m/knowledge-graph`.
- The new `/m/profile` page renders the **same fragment** inline (full-page, no overlay chrome) when unauth. DRY: `profile.html` `<!--ZK_OAUTH_INLINE-->` placeholder filled from `_oauth_modal.html` content by `_render_with_mobile_shell`.

---

## 4. Surface-by-surface spec

### 4.1 Header (mobile)

| Slot | Spec |
|---|---|
| Left | Brand: `<a href="/m/">` with `<img src="/artifacts/company_logo.svg" alt="Zettelkasten" width="22" height="22">` + brand text "Zettelkasten" |
| Center | **EMPTY**. Page title (`Summarize`, `Knowledge Graph`) removed. |
| Right slot 1 | Install icon button (`.m-header-install`). Dimensions match `.m-header-avatar` exactly (currently 38×38, CSS variable `--m-header-btn-size`). Hidden until first banner dismissal. Tap → invokes install state machine §3.4 |
| Right slot 2 | Avatar button (existing `#m-avatar-btn`). Same dimensions. Avatar SVG sourced via `avatar.js` from Supabase `user_metadata.avatar_url`. Unauth → Zoro's deterministic avatar |

CSS: `.m-header` becomes `display: grid; grid-template-columns: auto 1fr auto auto;` to support two right-side buttons with a flexible middle gap.

### 4.2 Capture (`/m/`)

| Block | Spec |
|---|---|
| Install banner | `#m-install-banner.m-install-banner`. Sits between header and hero. Hidden by default; install-prompt.js reveals when state allows. Dismiss X button. |
| Hero | `<h1>Capture Knowledge</h1><p>Paste any URL. Get an AI summary in seconds.</p>` — unchanged |
| Form | `#summarize-form.m-form` — URL input with hamburger inside (right side, ~36×36 square, ~80% input height). Hamburger tap → bottom sheet with 6 source options. No dropdown row below the input. |
| Submit | `#submit-btn.m-btn` — unchanged styling |
| Result area | **REMOVED**. Element `#m-result` deleted from DOM. JS handler redirects on success. |

### 4.3 Hamburger sheet (source picker)

Modal pattern: full-width bottom sheet, slides up, backdrop dim. Cells with icon + label:

```
Auto-detect (default, teal ring when selected)
YouTube
GitHub
Reddit
Newsletter
Web
```

Tap = set `data-source` attribute on `#summarize-form`, close sheet. Form submit reads that attribute and includes `source_override` in the request body. (Backwards-compatible: server already accepts `source_override`.)

### 4.4 Mobile Zettels (`/m/zettels`)

```
[Search input]  [Filter icon]      ← top sticky bar inside content
[Zettel card 1]
[Zettel card 2]
…
```

Zettel card:
```
[favicon] [title]                  [time-ago]
          [source]  [tag chips×3 max]
```

Filter icon → opens a bottom sheet (reuses hamburger-sheet.js) with:
- **Source** — multi-select chips (YouTube/GitHub/Reddit/Newsletter/Web)
- **Tag** — text search → chip list of matching tags, multi-select
- **Date range** — Today / 7d / 30d / All (Custom range deferred to a future PR)
- **Sort** — Newest / Oldest / A-Z / Source

State persisted in URL query params for shareability.

Detail modal — fullscreen overlay, includes summary content, source link, tags, "Download .md", "Refresh summary", close. Reuses desktop summary-overlay markup, mobile-styled.

`?just_captured=<id>` → on load, open detail modal for that zettel. If unauth + this query param present, render only that one zettel in the list.

### 4.5 Mobile Kastens (`/m/kastens`)

```
[Kasten card]  [Kasten card]
[Kasten card]  [Kasten card]
…
                          [+ Create FAB]   ← floating, bottom-right, above bottom nav
```

Kasten card:
```
[Name]                          [Fast/Strong badge]
[N zettels included]            [age]
```

Tap a Kasten card → `window.location.assign('/u/kastens/<id>?desktop=1')` (existing desktop URL with desktop override). Per D7 + open-item 1 confirmation. To be replaced in a future PR by a dedicated mobile Kasten chat view.

Create FAB → opens existing create-modal mobile-styled (name + Fast/Strong radio + scope radio + cancel/create).

### 4.6 Profile (`/m/profile`)

#### Unauth state

Full-page rendering of the OAuth modal content:
- "Sign in to Zettelkasten" title
- Google button (primary)
- "More sign-in options" reveal → Apple / GitHub / Facebook / Twitch
- "By signing in you agree to…" small print

#### Auth state

```
[Large avatar — current]
[Email]
[Sign out button]
─────────────────────────
Change avatar
[4×15 grid of 60 SVGs]   ← IntersectionObserver lazy-load
```

Selected avatar = teal ring. Tap = optimistic swap + PATCH. On 500/network error: revert + toast "Could not save avatar".

### 4.7 Footer (mobile)

Reuse `website/footer/footer.html` content but mobile-CSS-styled:
- Icons sized 18×18 (vs desktop 22×22)
- Spacing tighter (~12px gap)
- Background transparent
- Sits at end of scroll content with `margin-bottom: calc(var(--m-bottomnav-h) + env(safe-area-inset-bottom) + 16px)` so the last footer line doesn't get covered by the glass bottom nav

### 4.8 Bottom nav

```
Capture | Zettels | Kastens | Graph | Profile
```

- All tabs are `<a>` (no more `<button disabled>`).
- Active tab gets `.is-active` (teal underline + icon fill).
- Clicking a gated tab → browser navigates → server 302 → `/m/profile` (clean URL change). No client-side guard needed.
- Glass CSS per §1 D10.

---

## 5. DB migration

File: `supabase/website/_v2/53_user_default_avatar.sql`

```sql
-- ── 53_user_default_avatar.sql ────────────────────────────────────────────
-- Auto-assign random Zettelkasten avatar to new users; backfill existing.
-- Avatars served as static SVG under /artifacts/avatars/avatar_NN.svg (NN = 00..59).
-- Companion: removes any prior Google/Gravatar avatar_url so the front-end
-- avatar.js renders the curated set instead of third-party profile photos.

BEGIN;

-- Step 1: trigger function
CREATE OR REPLACE FUNCTION public.assign_default_avatar()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_idx text;
BEGIN
  IF (NEW.raw_user_meta_data->>'avatar_url') IS NULL THEN
    v_idx := lpad((floor(random() * 60))::text, 2, '0');
    NEW.raw_user_meta_data := COALESCE(NEW.raw_user_meta_data, '{}'::jsonb)
      || jsonb_build_object('avatar_url', '/artifacts/avatars/avatar_' || v_idx || '.svg');
  END IF;
  RETURN NEW;
END;
$$;

-- Step 2: BEFORE INSERT trigger on auth.users
DROP TRIGGER IF EXISTS on_auth_user_created_assign_avatar ON auth.users;
CREATE TRIGGER on_auth_user_created_assign_avatar
  BEFORE INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.assign_default_avatar();

-- Step 3: backfill existing users with NULL OR Google/Gravatar avatars
UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
  || jsonb_build_object(
       'avatar_url',
       '/artifacts/avatars/avatar_' || lpad((floor(random() * 60))::text, 2, '0') || '.svg'
     )
WHERE (raw_user_meta_data->>'avatar_url') IS NULL
   OR (raw_user_meta_data->>'avatar_url') LIKE '%googleusercontent.com%'
   OR (raw_user_meta_data->>'avatar_url') LIKE '%gravatar.com%';

-- Step 4: pin the canonical anon (Zoro) user to a deterministic avatar.
-- UUID resolved from ops/deploy/expected_users.json::_canonical_zoro.
-- Naruto (the canonical authenticated test user) also pinned for parity.
UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
  || jsonb_build_object('avatar_url', '/artifacts/avatars/avatar_00.svg')
WHERE id = 'a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e';  -- Zoro

UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
  || jsonb_build_object('avatar_url', '/artifacts/avatars/avatar_01.svg')
WHERE id = 'f2105544-b73d-4946-8329-096d82f070d3';  -- Naruto

-- Step 5: grants
GRANT EXECUTE ON FUNCTION public.assign_default_avatar() TO service_role;
GRANT EXECUTE ON FUNCTION public.assign_default_avatar() TO authenticated;

COMMIT;
```

**Pre-apply checklist (operator-gated per CLAUDE.md migration discipline):**
1. Run on staging Supabase first; verify trigger fires on a test signup.
2. Verify backfill row count BEFORE commit:
   ```sql
   SELECT COUNT(*) FROM auth.users
   WHERE raw_user_meta_data->>'avatar_url' IS NULL
      OR raw_user_meta_data->>'avatar_url' LIKE '%googleusercontent.com%'
      OR raw_user_meta_data->>'avatar_url' LIKE '%gravatar.com%';
   ```
3. Verify Zoro + Naruto rows exist before pinning (sanity guard against UUID drift):
   ```sql
   SELECT id, email FROM auth.users WHERE id IN ('a57e1f2f-...zoro...', 'f2105544-...naruto...');
   ```
4. Operator confirms before prod-apply.

---

## 6. API surface

### 6.1 `GET /api/profile`

Returns the current user's profile.

```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "avatar_url": "/artifacts/avatars/avatar_07.svg",
  "display_name": "Optional"
}
```

401 if no session.

### 6.2 `PATCH /api/profile`

Updates the user's profile metadata.

Request:
```json
{ "avatar_url": "/artifacts/avatars/avatar_22.svg" }
```

Response: 200 with updated profile (same shape as GET). 422 if `avatar_url` is not in the allowed set (`/artifacts/avatars/avatar_(00|01|...|59).svg`).

Server-side validation regex: `^/artifacts/avatars/avatar_(0[0-9]|[1-5][0-9])\.svg$`. Anything else → 422.

### 6.3 No new public endpoints beyond those two.

---

## 7. Test plan

| Layer | Coverage |
|---|---|
| Unit — `tests/unit/website/test_profile_routes.py` | Avatar-URL validation regex (boundary indices 00, 59, 60→reject); PATCH happy path; PATCH with expired access-token cookie → 401; PATCH 422 on invalid path; PATCH 422 on path-traversal attempt (`../../etc/passwd`) |
| Unit — `tests/unit/website/test_install_prompt_state.py` | localStorage dismissal parse (no entry / valid date / expired); 30-day suppression; display-mode detection; iOS UA detection |
| Unit — `tests/unit/website/test_mobile_routes.py` | `/m/zettels` 302 when unauth, 200 when auth, 200 when `just_captured` query present (anon-allowed); `/m/kastens` 302; `/m/profile` always 200 |
| Integration — `tests/integration/v2/test_avatar_assignment.py` | Mint a fresh test user; assert `avatar_url` in `raw_user_meta_data` matches regex; assert PATCH works end-to-end with Supabase |
| Live (`--live`) — `tests/integration/v2/test_avatar_migration.py` | Apply 53_user_default_avatar.sql on a staging copy; assert Zoro is pinned to avatar_00; assert no NULL/google avatars remain |
| Concurrency — `tests/integration/v2/test_profile_concurrency.py` | Two simultaneous PATCH calls from the same user → last-write-wins, no corruption |
| Screenshots (manual checklist in PR) | 5 mobile routes × 2 auth states = 10 + install-banner-shown + install-banner-dismissed + iOS-instruction-sheet + Profile-picker-grid + bottom-nav-glass-over-light-content + bottom-nav-glass-over-dark-content |

---

## 8. Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Migration overwrites a legitimate user-uploaded `avatar_url` that doesn't match google/gravatar patterns | Low | Medium | Backfill targets ONLY NULL + known third-party domains. Pre-apply checklist records count of rows touched. |
| R2 | Backfill is destructive (loses prior Google profile photos) | Cert. (intentional) | Low | Per D4: explicitly authorized — Google photos are being removed by design |
| R3 | `backdrop-filter` perf on low-end Android | Low | Medium | Blur capped at 16px; `will-change` + `contain`; opaque fallback for unsupported browsers |
| R4 | Install banner fires `beforeinstallprompt` only once per session/browser-state — losing the deferred event breaks the flow | Medium | Low | Module-level cache for the event; re-arm on `appinstalled` and on `localStorage` clear |
| R5 | iOS Safari shows install button with no underlying install action | Low | Medium | UA branch + `!navigator.standalone` gate; iOS path opens instructional sheet, never tries `prompt()` |
| R6 | `/m/zettels?just_captured=<id>` could be exploited to render arbitrary zettels to anon viewers | Low | Medium | Server-side validates `just_captured` against the just-created zettel's id from the anon Zoro user (read-only via session cookie OR a short-lived signed query param) |
| R7 | Glass nav reduces icon contrast over bright content (knowledge-graph 3D viz background varies) | Low | Low | Per research, 68% opacity tint maintains WCAG 3:1 in dark theme; manually verify on KG page during screenshot pass |
| R8 | Static `/artifacts/avatars/` mount could expose unintended files if directory is mis-scoped | Very low | High | Explicitly mount only `…/avatars`, not `…/artifacts`. Verify no sensitive files in that folder pre-merge. |
| R9 | Service-worker precache conflict between 60-avatar set and existing precache budget | Low | Low | Don't precache all 60; only the user's own + the company logo + critical CSS |
| R10 | Cross-cutting desktop avatar change ships with mobile work — could regress desktop UX | Low | Medium | Desktop visual change is small (drops Google photo for curated avatar); covered by manual screenshot pass on desktop home page |

---

## 9. Sequencing & PR strategy

This is a single PR (`mobile-ui-fixes-2a`, #96). Suggested implementation order to keep each commit deployable:

1. **DB migration** `53_user_default_avatar.sql` — apply to staging, verify, then prod (operator-gated)
2. **Avatar serving** — static mount + cache headers + `avatar.js` shared lib + backend `/api/profile` GET/PATCH
3. **Desktop avatar swap** — `home.js`, `header.js` adopt `avatar.js`, drop Google fallback
4. **Mobile header redesign** — logo, drop title, avatar via `avatar.js`, leave install slot empty for now
5. **Mobile bottom nav** — rename tabs, enable as links, apply glass CSS
6. **Hamburger sheet primitive** — `hamburger-sheet.js` + CSS
7. **Capture-form hamburger + remove inline summary + redirect-after-submit**
8. **Mobile Zettels route + page**
9. **Mobile Kastens route + page**
10. **Mobile Profile route + page** (auth state + unauth state + avatar picker)
11. **PWA install banner + iOS sheet + header-icon fallback**
12. **Mobile footer fragment**
13. **Tests landed alongside each block per CLAUDE.md "no partial follow-ups" rule**
14. **Manual screenshot pass + PR review request**

Per CLAUDE.md "Approval Threshold": phase transitions proceed autonomously. DB migration prod-apply is the one operator-gated step.

---

## 10. Out of scope (explicit deferrals — require operator approval per "Deferral Is A Decision")

| Deferred item | Why deferred | Tracked for |
|---|---|---|
| Mobile Kasten chat / detail view (currently redirects to desktop view) | Substantial feature on its own; would balloon 2a scope | Future PR — "mobile UI fixes 2b" or "mobile Kasten chat" |
| Mobile Zettel detail "Refresh summary" deep flow (button shows but uses existing endpoint) | Behavior identical to desktop; no mobile-specific tuning needed in 2a | If post-launch UX feedback requires |
| Bottom-sheet swipe-to-dismiss + spring animations | Polish; defaults to tap-backdrop dismiss only | Polish PR |
| Push notifications / web-push for capture-complete | Adjacent feature, not requested | Separate iteration |
| Profile features beyond avatar + email + sign-out (display name editing, etc.) | Not in user spec | Future Profile iteration |

If any of these should be folded into 2a instead, surface BEFORE plan execution.

---

## 11. Acceptance criteria

PR is mergeable when:
- All 10 manual screenshots pass visual review against this spec
- All unit + integration tests pass in CI
- Migration applied on staging without errors; backfill row count operator-confirmed
- Lighthouse PWA score on `/m/` ≥ 90 (install banner visible, manifest reachable, SW active)
- Bottom-nav glass renders correctly on iPhone (real device or BrowserStack iOS 17+) and Pixel emulator
- No regressions in desktop home avatar flow (manual smoke)
- All 14 commits in the sequence land green
