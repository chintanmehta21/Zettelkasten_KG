# Mobile Website — Iteration 1a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the mobile website (`/m/*`) to UX parity with desktop for the locked 1a scope — shared mobile shell, hybrid nav chrome, OAuth sign-in modal, skeleton-typewriter loader, KG filter parity, PWA installability, and a `?desktop=1` escape from the mobile redirect — without adding net-new content pages.

**Architecture:**
- Extend the existing `_render_with_shell` pattern (string-replace `<!--ZK_HEADER-->` / `<!--ZK_FOOTER-->` in HTML files) to mobile via a new `_render_with_mobile_shell()` helper that injects mobile-specific header + bottom-tab bar + footer.
- All work is vanilla HTML / CSS / JS (no SPA framework). New mobile JS files are small (<5 KB ea.), loaded per-page; PWA assets (manifest + service worker) are static files served by Caddy.
- Auth piggybacks on the existing desktop `website/features/user_auth/js/auth.js` (same Supabase client, same `zk-auth-token` localStorage key, same PKCE flow) — mobile only adds a different trigger surface (full-screen `<dialog>` instead of header dropdown).
- KG filter parity reuses `/api/graph`'s existing tags/kastens metadata; no new server endpoint.

**Tech stack:** FastAPI + Jinja-less template fragments (string-replace), vanilla HTML/CSS/JS, Supabase JS v2 (already loaded), `3d-force-graph` (already loaded), Caddy 2 (already in front).

**Source inputs (read these first):**
- [docs/mobile-1a/audit.md](audit.md) — gap matrix, M-codes for deficiencies, §7 locked scope, §8 research queue
- Research findings from prior turn (R1 OAuth, R2 nav, R4 KG filters, R6 PWA — all in conversation history)
- A5 codebase scout (file:line refs throughout this plan)

**Locked scope reminder (audit §7 + C-clarifications):**
- Polish + auth + nav shell + PWA + `?desktop=1` escape
- 5-tab bottom bar with disabled-greyed placeholders (Capture / Notes / Chat / Graph / Profile)
- Mirror desktop OAuth (6 providers, primary-CTA layout per R1)
- Port skeleton typewriter to mobile (C3)
- Identity propagation (avatar + Sign out post-sign-in) in header — implicit-in-auth interpretation; flag at plan-approval gate

---

## 0. Research-driven design decisions (locked in this plan)

Synthesized from R1/R2/R4/R6/A5. Every decision below cites the source.

| Decision | Source | Rationale |
|---|---|---|
| Full-screen `<dialog>` for OAuth (not bottom-sheet) | R1 §5 + Apple HIG | Sign-in is "extended interaction" per HIG; full-screen is canonical |
| OAuth providers: `Google` primary CTA, `Apple` second, **`More options ▾`** disclosure for GitHub/Reddit/Facebook/Twitch | R1 §2 + R1 §5 | +107% trial-start lift evidence; respects 44pt tap targets |
| Use native `<dialog>` element (`.showModal()`) for free focus-trap + ARIA | R1 §3 | iOS 15.4+, Chrome 37+; fallback to manual focus trap not needed for our target |
| `interactive-widget=resizes-content` meta tag + `100dvh` for keyboard-safe modal | R1 §7 | iOS keyboard otherwise pushes modal off-screen |
| 5 bottom tabs — `Capture / Notes / Chat / Graph / Profile`; un-built ones at 40% opacity + tap-toast | R2 §6 + Smashing 2024 | Apple HIG hard-cap = 5; "disable, don't hide" |
| Header = 48px sticky, brand mark left + page title centered + avatar right | R2 §3 | Linear/Substack/Vercel 2025 pattern |
| Tab bar rendered as sibling of `<main>` (NOT inside scroll container) to avoid iOS standalone jitter | R2 §8 | Known 2024-2026 iOS PWA quirk |
| Bottom-tab `bottom: calc(env(safe-area-inset-bottom) + 4px)` — clears home indicator + avoids Safari bottom-tap hot zone | R2 §8 | Standalone vs Safari safe-area delta = 34px |
| Single KG bottom-sheet with mode switcher `Filters | Detail` via segmented control | R4 §2 + NN/g 2023 | Don't stack sheets; share the existing detail sheet |
| Segmented control (NOT switch, NOT tabs) for `Global ↔ Personal` view toggle | R4 §5 + Apple HIG | Switches imply enable/disable; tabs imply page nav |
| "Personal" view disabled with "Sign in to view" tooltip when anon | R4 §10 | Avoid empty-state silent-fail |
| Connection strength slider `min=0.30 max=0.85 step=0.05 value=0.30`, numeric readout above + on thumb | R4 §3 + A5 §4 | Matches desktop exactly; thumb-readout for interpreted (not aesthetic) values |
| Multi-select tags/kastens: pinned chips + "Search to add more" + 5-7 async suggestions | R4 §4 | Standard 2025 pattern for unbounded chip sets |
| Search count rendered INLINE BELOW the input (not to the right) with × clear in input | R4 §6 + Apple HIG | Standard mobile-web convention; keeps thumb typing area full-width |
| Reset-view button = floating bottom-right above chip rail, `fit-to-screen` icon (not refresh) | R4 §7 | Refresh implies data reload — wrong affordance |
| `ForceGraph3D.pauseAnimation()` when sheet at `large` detent; resume on dismiss | R4 §9 | Saves CPU + battery; canvas is obscured |
| Landscape fallback: sheet becomes right-edge side sheet at `(orientation: landscape) and (max-height: 480px)` | R4 §10 | 50vh sheet eats half of landscape canvas |
| Manifest minimum: `name, short_name, start_url=/m/, scope=/m/, display=standalone, id=/m/, theme_color, background_color, icons (192/512/512-maskable), apple-touch-icon (180×180)` | R6 §2 + R6 §3 + Chrome installability docs | Required for Chrome install; Apple ignores manifest icons |
| SW = hand-written ~50 lines (no Workbox), network-first for HTML in `/m/*`, cache-first for `/static/*`, deny-list `/api/*` + `/kg/content/*` | R6 §4 + R6 §7 | Static surface; Workbox overkill |
| Versioned cache name (`zk-shell-v1`); delete old caches in `activate`; **do NOT call `skipWaiting()` unconditionally** | R6 §8 + MDN | Avoid mid-session tab inconsistency |
| iOS install-prompt = custom "Add to Home Screen" instruction sheet (no `beforeinstallprompt` on iOS Safari) | R6 §5 | `beforeinstallprompt` never fires on iOS |
| `Service-Worker-Allowed: /` header on `/sw.js` from Caddy; short `Cache-Control` (≤5min) for `sw.js` itself | R6 §8 + A5 §7 | Otherwise SW scope restricted to file's path; stale-shell risk |
| `?desktop=1` query-param sets `zk-prefer-desktop=1` cookie (max-age 30d); cookie bypasses `_is_mobile()` regex | C1 + audit M3.2 | Cookie persists across navigation; query-param is the trigger |
| Skeleton typewriter — port the desktop `zk_skeleton_typewriter.js` directly (not the lighter mobile rotating-text) | C3 | Operator pick |
| Defer: Twitter/X chip behind feature-flag (paid-only API tier, deprecation-risk) | R1 §7 | Don't ship a chip that may break |
| Defer: Apple Sign-In SPF/sender-domain alignment work — flag in plan; do NOT enable Apple in this PR if not already validated | R1 §7 | Email-relay deliverability risk |

**Acceptance criteria (audit + research):**
- All M1.* / M2.* / M3.* deficiencies addressed (audit §7.1)
- All UI changes manually verified on iPhone 14 Pro + Pixel 7 + iPad Mini viewport emulation
- `pytest -m "not live"` green
- Caddy serves manifest + SW with correct headers (verify w/ `curl -I`)
- Lighthouse PWA score ≥ 90 (manual run in Chrome DevTools)
- No droplet RAM delta (`free -h` before / after deploy)
- Backwards-compatible: anonymous `/m/` summarize flow still works post-merge

---

## 1. File structure

### New files (15)

| Path | Responsibility |
|---|---|
| `website/mobile/templates/_shell.html` | Mobile shell wrapper: `<head>` (meta/fonts/PWA links), `<header>` (logo + page title + avatar pill), `<main>` placeholder `<!--ZK_MOBILE_CONTENT-->`, bottom-tab `<nav>`, `<footer>` |
| `website/mobile/templates/_oauth_modal.html` | Full-screen `<dialog>` with primary-CTA OAuth grid (Google, Apple, More options) |
| `website/mobile/templates/_kg_filter_sheet.html` | Bottom-sheet body with `Filters \| Detail` segmented-control header + filter form (view-toggle, slider, source chips, tags search, kastens search) |
| `website/mobile/css/components/shell.css` | Header + bottom-tab CSS, safe-area handling, disabled-tab state |
| `website/mobile/css/components/auth-modal.css` | OAuth full-screen modal styles + dvh handling |
| `website/mobile/css/components/kg-filters.css` | Bottom-sheet `Filters` mode: segmented control, slider, multi-select chips, sticky footer |
| `website/mobile/js/shell.js` | Tab active-state on route, disabled-tab toast, avatar pill click → OAuth modal trigger |
| `website/mobile/js/auth-modal.js` | OAuth modal open/close + provider button → `signInWithProvider` delegation (re-uses existing user_auth) |
| `website/mobile/js/kg-filters.js` | Sheet mode-switch, slider event, chip search, reset button, pauseAnimation hook |
| `website/static/manifest.webmanifest` | PWA manifest (name, short_name, start_url, scope, icons, theme_color) |
| `website/static/sw.js` | Service worker (~50 lines hand-written, versioned cache, allow/deny lists) |
| `website/static/icons/icon-192.png` + `icon-512.png` + `icon-maskable-512.png` + `apple-touch-icon-180.png` | PWA icon set (generate from existing favicon.svg) |
| `tests/unit/mobile/__init__.py` | Empty marker |
| `tests/unit/mobile/test_mobile_shell.py` | Shell-injection + route tests + escape-cookie tests |
| `tests/unit/mobile/test_pwa.py` | Manifest + SW serving / headers / Content-Type tests |

### Modified files (8)

| Path | Change |
|---|---|
| `website/app.py` | Add `_render_with_mobile_shell()`; route `/m/` and `/m/knowledge-graph` through it; add `/manifest.webmanifest` + `/sw.js` static handlers w/ correct headers; teach `_is_mobile()` to honor `zk-prefer-desktop` cookie; add `/m/_escape` to set cookie on `?desktop=1` |
| `website/mobile/index.html` | Strip duplicated head/footer/fonts; replace with `<!--ZK_MOBILE_CONTENT-->`-anchored body content only |
| `website/mobile/knowledge-graph.html` | Same strip; remove existing filter chip rail + add `<!--ZK_KG_FILTER_SHEET-->` (injected by `_render_with_mobile_shell` when route is the KG one) |
| `website/mobile/css/mobile.css` | Import new component CSS; trim duplicated rules; add bottom-tab + sheet variables |
| `website/mobile/js/summarizer.js` | Wire `showLoading()` to skeleton typewriter (not rotating text) |
| `website/mobile/js/graph.js` | Bind filter sheet (segmented control, slider, search, reset, pauseAnimation); add Global/Personal view fetch |
| `ops/caddy/Caddyfile` | Add header rules for `/manifest.webmanifest` (Content-Type) + `/sw.js` (Service-Worker-Allowed, short Cache-Control) |
| `tests/unit/user_home/test_mobile_ua_redirect.py` | Add tests for escape cookie behavior (existing test file extension) |

**Total LOC delta estimate:** ~1100 new lines (templates 250 + CSS 400 + JS 300 + tests 150). Existing-file mods ~80 lines net.

---

## 2. Phase plan (8 phases, sequential)

### Phase 1: Shared mobile shell + `?desktop=1` escape

**Files:**
- Create: `website/mobile/templates/_shell.html`
- Modify: `website/app.py:42-103` (`_MOBILE_RE`, `_is_mobile`), `website/app.py:68-83` (`_render_with_shell` — add sibling `_render_with_mobile_shell`), `website/app.py:406-412` (mobile routes)
- Modify: `website/mobile/index.html`, `website/mobile/knowledge-graph.html` (strip duplicated head/footer)
- Create: `tests/unit/mobile/__init__.py`, `tests/unit/mobile/test_mobile_shell.py`
- Modify: `tests/unit/user_home/test_mobile_ua_redirect.py` (add cookie tests)

- [ ] **Step 1: Read existing `_render_with_shell` and current mobile pages to confirm structure before writing the shell template**

Run: read `website/app.py:60-110`, `website/mobile/index.html`, `website/mobile/knowledge-graph.html` (only if not already in context).
Expected: confirm `_render_with_shell` does string-replace of `<!--ZK_HEADER-->` and `<!--ZK_FOOTER-->` against `header.html` + `footer.html`.

- [ ] **Step 2: Write the failing test for `_render_with_mobile_shell`**

Create `tests/unit/mobile/__init__.py` (empty file).

Create `tests/unit/mobile/test_mobile_shell.py`:

```python
"""Tests for mobile shell injection + escape cookie (iter mobile-1a Phase 1)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from website.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_mobile_index_includes_shell_header() -> None:
    """`/m/` HTML must contain the shared mobile header markup."""
    resp = _client().get("/m/")
    assert resp.status_code == 200
    html = resp.text
    # Shell injects the bottom-tab nav and the page title placeholder
    assert 'class="m-bottom-tabs"' in html
    assert 'data-tab="capture"' in html
    # No duplicated head/font preconnect should be in the page body — the shell owns it
    assert html.count('<meta charset="UTF-8">') == 1
    assert html.count('href="https://fonts.googleapis.com/css2?family=Inter') == 1


def test_mobile_kg_page_includes_shell_header() -> None:
    """`/m/knowledge-graph` also uses the shared shell."""
    resp = _client().get("/m/knowledge-graph")
    assert resp.status_code == 200
    html = resp.text
    assert 'class="m-bottom-tabs"' in html
    assert 'data-tab="graph"' in html


def test_escape_cookie_bypasses_mobile_redirect() -> None:
    """When `zk-prefer-desktop=1` cookie is set, mobile UA on /home does NOT redirect."""
    client = _client()
    iphone_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    # Without cookie: redirects
    resp = client.get("/home", headers={"User-Agent": iphone_ua}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/m/"
    # With cookie: serves the desktop page
    resp = client.get(
        "/home",
        headers={"User-Agent": iphone_ua},
        cookies={"zk-prefer-desktop": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 200  # desktop /home renders
    assert "/m/" not in resp.headers.get("location", "")


def test_query_param_sets_escape_cookie_then_serves_desktop() -> None:
    """Hitting `/?desktop=1` on mobile UA sets the cookie and serves desktop."""
    client = _client()
    iphone_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    resp = client.get("/?desktop=1", headers={"User-Agent": iphone_ua}, follow_redirects=False)
    # Sets cookie + serves desktop landing (no redirect to /m/)
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "zk-prefer-desktop=1" in set_cookie
    assert "Max-Age=2592000" in set_cookie  # 30 days
    assert "HttpOnly" not in set_cookie  # Not HttpOnly — JS-readable so the link can opt-back-in
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/unit/mobile/test_mobile_shell.py -v`
Expected: 4 failures (FAIL — `_render_with_mobile_shell` not implemented, escape cookie not implemented).

- [ ] **Step 4: Create the mobile shell template**

Create `website/mobile/templates/_shell.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, interactive-widget=resizes-content">
  <meta name="theme-color" content="#0a0b14">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="apple-touch-icon" sizes="180x180" href="/static/icons/apple-touch-icon-180.png">
  <link rel="manifest" href="/manifest.webmanifest">
  <title><!--ZK_MOBILE_TITLE--></title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/m/css/mobile.css?v=20260524a">
</head>
<body class="<!--ZK_MOBILE_BODY_CLASS-->">
  <header class="m-header" role="banner">
    <a class="m-header-brand" href="/m/" aria-label="Zettelkasten home">
      <svg class="m-header-logo" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <circle cx="12" cy="12" r="9"></circle>
        <circle cx="12" cy="12" r="3" fill="currentColor"></circle>
      </svg>
      <span class="m-header-brand-text">Zettelkasten</span>
    </a>
    <h1 class="m-header-title" id="m-page-title"><!--ZK_MOBILE_PAGE_TITLE--></h1>
    <button class="m-header-avatar" id="m-avatar-btn" type="button" aria-label="Sign in or open account menu">
      <svg class="m-header-avatar-anon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
        <circle cx="12" cy="7" r="4"></circle>
      </svg>
      <span class="m-header-avatar-image" id="m-avatar-image" hidden></span>
    </button>
  </header>

  <main class="m-main" id="m-main">
    <!--ZK_MOBILE_CONTENT-->
  </main>

  <nav class="m-bottom-tabs" role="navigation" aria-label="Primary">
    <a class="m-tab" data-tab="capture" href="/m/" aria-label="Capture">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
      <span class="m-tab-label">Capture</span>
    </a>
    <button class="m-tab m-tab-disabled" data-tab="notes" type="button" aria-disabled="true" aria-label="Notes — coming soon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>
      <span class="m-tab-label">Notes</span>
    </button>
    <button class="m-tab m-tab-disabled" data-tab="chat" type="button" aria-disabled="true" aria-label="Chat — coming soon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
      <span class="m-tab-label">Chat</span>
    </button>
    <a class="m-tab" data-tab="graph" href="/m/knowledge-graph" aria-label="Graph">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="5" r="2"></circle><circle cx="5" cy="19" r="2"></circle><circle cx="19" cy="19" r="2"></circle><line x1="12" y1="7" x2="6" y2="17"></line><line x1="12" y1="7" x2="18" y2="17"></line></svg>
      <span class="m-tab-label">Graph</span>
    </a>
    <button class="m-tab m-tab-disabled" data-tab="profile" type="button" aria-disabled="true" aria-label="Profile — coming soon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
      <span class="m-tab-label">Profile</span>
    </button>
  </nav>

  <footer class="m-footer">
    <a href="/?desktop=1">Switch to desktop site</a>
  </footer>

  <script src="/m/js/shell.js?v=20260524a"></script>
</body>
</html>
```

- [ ] **Step 5: Add `_render_with_mobile_shell` and update mobile routes in `website/app.py`**

Modify `website/app.py`. After `_render_with_shell` (~line 83), add:

```python
MOBILE_TEMPLATES_DIR = MOBILE_DIR / "templates"
_MOBILE_SHELL = MOBILE_TEMPLATES_DIR / "_shell.html"


def _render_with_mobile_shell(
    body_path: Path,
    *,
    page_title: str,
    body_class: str = "",
    extra_head: str = "",
) -> HTMLResponse:
    """Inject mobile shell around a body fragment file.

    Mobile shell owns <head> + header + bottom-tab nav + footer. Body fragment
    file is expected to contain ONLY the in-<main> content (no <html>/<head>/<body>
    wrappers).
    """
    shell = _MOBILE_SHELL.read_text(encoding="utf-8")
    body = body_path.read_text(encoding="utf-8")
    rendered = (
        shell
        .replace("<!--ZK_MOBILE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_PAGE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_BODY_CLASS-->", body_class)
        .replace("<!--ZK_MOBILE_CONTENT-->", body)
    )
    if extra_head:
        rendered = rendered.replace("</head>", f"{extra_head}\n</head>", 1)
    return HTMLResponse(content=rendered, headers={"Cache-Control": "no-store"})
```

Replace the `/m/` + `/m/knowledge-graph` route bodies (~lines 406-412):

```python
    # ── Mobile routes ──
    @app.get("/m/")
    async def mobile_index():
        return _render_with_mobile_shell(
            MOBILE_DIR / "index.html",
            page_title="Summarize",
        )

    @app.get("/m/knowledge-graph")
    async def mobile_knowledge_graph():
        return _render_with_mobile_shell(
            MOBILE_DIR / "knowledge-graph.html",
            page_title="Knowledge Graph",
            body_class="kg-body",
        )
```

- [ ] **Step 6: Strip head/footer from mobile body fragments**

Modify `website/mobile/index.html` — keep only the `<main>`-eligible content (Hero through Knowledge Graph nav link). The new file should be:

```html
<!-- Body fragment for /m/ — injected into mobile shell by _render_with_mobile_shell. -->

<!-- Hero -->
<section class="m-hero">
  <h1>Capture Knowledge</h1>
  <p>Paste any URL. Get an AI summary in seconds.</p>
</section>

<!-- Form -->
<form class="m-form" id="summarize-form" autocomplete="off">
  <div class="m-input-group">
    <input type="file" class="m-document-input" id="document-input" accept=".pdf,.txt,.md,.markdown,.docx,application/pdf,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document">
    <button type="button" class="m-document-btn" id="document-upload-btn" title="Upload document" aria-label="Upload document">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M21.4 11.6 12 21a6 6 0 0 1-8.5-8.5l9.7-9.7a4.2 4.2 0 1 1 5.9 5.9l-9.7 9.7a2.3 2.3 0 0 1-3.3-3.3l8.8-8.8 1.4 1.4-8.8 8.8a.3.3 0 0 0 .5.5l9.7-9.7a2.2 2.2 0 0 0-3.1-3.1l-9.7 9.7a4 4 0 0 0 5.7 5.7l9.4-9.4 1.4 1.4z"/>
      </svg>
    </button>
    <input type="url" class="m-input" id="url-input" placeholder="Paste a URL..." inputmode="url">
  </div>
  <select class="m-select" id="source-select">
    <option value="">Auto-detect source</option>
    <option value="youtube">YouTube</option>
    <option value="github">GitHub</option>
    <option value="reddit">Reddit</option>
    <option value="newsletter">Newsletter</option>
    <option value="web">Web page</option>
  </select>
  <button type="submit" class="m-btn" id="submit-btn">Summarize</button>
</form>

<!-- Loading (skeleton typewriter injected by Phase 4) -->
<div class="m-loading" id="loading">
  <div class="m-skeleton-card" id="skeleton-card" hidden></div>
  <div class="m-loading-text" id="loading-text">Analyzing content...</div>
</div>

<!-- Error -->
<div class="m-error" id="error"></div>

<!-- Result -->
<div class="m-result" id="result">
  <span class="m-result-badge" id="result-badge"></span>
  <h2 id="result-title"></h2>
  <p class="m-result-brief" id="result-brief"></p>
  <div class="m-result-tags" id="result-tags"></div>
  <div class="m-result-detail" id="result-detail"></div>
  <div class="m-result-actions">
    <button class="m-btn-secondary" id="copy-btn">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
      Copy
    </button>
    <a class="m-btn-secondary" id="source-link" href="#" target="_blank" rel="noopener">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      Source
    </a>
  </div>
</div>

<script src="/js/add_zettel_api.js?v=20260522a"></script>
<script src="/m/js/summarizer.js?v=20260524a"></script>
```

Modify `website/mobile/knowledge-graph.html` — strip head/body wrappers, keep only the in-`<main>` body. Use placeholder for the filter sheet (Phase 5 fills it):

```html
<!-- Body fragment for /m/knowledge-graph — injected into mobile shell. -->

<!-- KG search header strip (inside <main>, sits below the main shell header) -->
<div class="kg-m-search-strip">
  <input type="text" class="kg-m-search" id="search-input" placeholder="Search notes..." autocomplete="off">
  <span class="kg-m-search-count" id="search-count" hidden></span>
  <button class="kg-m-search-clear" id="search-clear" type="button" aria-label="Clear search" hidden>×</button>
  <button class="m-header-action" id="filter-toggle" aria-label="Open filters">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon></svg>
    <span class="kg-m-filter-count" id="filter-count" hidden>0</span>
  </button>
</div>

<!-- Stats pill -->
<div class="kg-m-stats" id="stats">Loading...</div>

<!-- Graph Container -->
<div id="graph-container"></div>

<!-- Recenter floating button -->
<button class="kg-m-recenter" id="recenter-btn" type="button" aria-label="Recenter view">
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h7v7H3z"/><path d="M14 3h7v7h-7z"/><path d="M14 14h7v7h-7z"/><path d="M3 14h7v7H3z"/></svg>
</button>

<!-- Bottom Sheet (Phase 5 expands to include Filters | Detail modes) -->
<div class="kg-m-sheet" id="sheet">
  <div class="kg-m-sheet-handle"></div>
  <div class="kg-m-sheet-content">
    <span class="kg-m-sheet-badge" id="sheet-badge">source</span>
    <h2 class="kg-m-sheet-title" id="sheet-title">Note Title</h2>
    <p class="kg-m-sheet-date" id="sheet-date"></p>
    <p class="kg-m-sheet-summary" id="sheet-summary"></p>
    <div class="kg-m-sheet-tags" id="sheet-tags"></div>
    <div class="kg-m-sheet-connections" id="sheet-connections">
      <h3>Connected Notes</h3>
      <div id="sheet-conn-list"></div>
    </div>
    <a class="kg-m-sheet-link" id="sheet-link" href="#" target="_blank" rel="noopener">
      View Original Source
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
    </a>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three-spritetext@1.10.0/dist/three-spritetext.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/3d-force-graph@1.79.1/dist/3d-force-graph.min.js"></script>
<script src="/m/js/graph.js?v=20260524a"></script>
```

Note: the old `<header class="kg-m-header">` and `<div class="kg-m-filters" id="filter-chips">` are deleted — the shell owns the top header, and the filter chips move into the bottom-sheet in Phase 5.

- [ ] **Step 7: Add `_is_mobile` cookie support + escape-cookie writer**

Modify `website/app.py` around lines 89-103. Replace `_is_mobile`:

```python
_DESKTOP_COOKIE = "zk-prefer-desktop"


def _is_mobile(request: Request) -> bool:
    # Operator escape: ?desktop=1 query OR persistent cookie set previously.
    if request.cookies.get(_DESKTOP_COOKIE) == "1":
        return False
    if request.query_params.get("desktop") == "1":
        # First-time escape. Detected here; cookie set by the route handler
        # (or by a middleware below). The redirect-decision treats this as
        # not-mobile; the route then sets the cookie before returning HTML.
        return False
    ua = request.headers.get("user-agent", "")
    return bool(_MOBILE_RE.search(ua))


def _maybe_set_desktop_cookie(request: Request, response: HTMLResponse) -> HTMLResponse:
    """If the request opted into desktop via ?desktop=1, persist a 30-day cookie."""
    if request.query_params.get("desktop") == "1" and request.cookies.get(_DESKTOP_COOKIE) != "1":
        response.set_cookie(
            key=_DESKTOP_COOKIE,
            value="1",
            max_age=60 * 60 * 24 * 30,  # 30 days
            path="/",
            samesite="lax",
            httponly=False,  # JS may read; not a security cookie
        )
    return response
```

Then wrap the desktop landing route (line ~415) and any other desktop routes that should respect the escape:

```python
    @app.get("/")
    async def index(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(STATIC_DIR / "index.html")
        return _maybe_set_desktop_cookie(request, response)
```

Apply `_maybe_set_desktop_cookie` to the other redirect-bearing desktop routes (`/home`, `/home/zettels`, `/home/kastens`, `/home/rag`, `/profile`, `/about`, `/pricing`, `/knowledge-graph`).

- [ ] **Step 8: Run the test to verify it passes**

Run: `pytest tests/unit/mobile/test_mobile_shell.py -v`
Expected: 4 PASS.

- [ ] **Step 9: Run the full mobile-affecting test suite to confirm no regression**

Run: `pytest tests/unit/user_home/test_mobile_ua_redirect.py tests/unit/mobile/ -v`
Expected: all PASS (existing tests still pass; new tests pass).

- [ ] **Step 10: Manual smoke test — start dev server and verify both mobile pages render**

Run (Git Bash, repo root): `ENV=dev python run.py &`
Wait 3s. Then `curl -sS -A "Mozilla/5.0 (iPhone) Safari" http://127.0.0.1:10000/m/ | grep -c "m-bottom-tabs"`
Expected: `1`
Run: `curl -sS -A "Mozilla/5.0 (iPhone) Safari" http://127.0.0.1:10000/m/knowledge-graph | grep -c "m-bottom-tabs"`
Expected: `1`
Kill the dev server with `kill %1`.

- [ ] **Step 11: Commit**

```bash
git add website/app.py website/mobile/templates/ website/mobile/index.html website/mobile/knowledge-graph.html tests/unit/mobile/
git commit -m "feat: shared mobile shell + desktop escape cookie"
```

---

### Phase 2: Hybrid nav chrome — CSS + JS (top header sticky, 5-tab bottom bar)

**Files:**
- Create: `website/mobile/css/components/shell.css`
- Create: `website/mobile/js/shell.js`
- Modify: `website/mobile/css/mobile.css` (`@import` the new shell CSS at top)

- [ ] **Step 1: Add shell component CSS**

Create `website/mobile/css/components/shell.css`:

```css
/* ═════════════════════════════════════════════════════════════
   Mobile shell — top header (sticky, 48px) + bottom-tab bar.
   See docs/mobile-1a/plan.md §0 for R2-derived design decisions.
   ═════════════════════════════════════════════════════════════ */

/* ── Top header ───────────────────────────────────────────── */
.m-header {
  position: sticky;
  top: 0;
  z-index: 100;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 12px;
  align-items: center;
  min-height: 48px;
  padding: 8px 12px;
  padding-top: calc(8px + var(--safe-top));
  background: hsla(224, 28%, 5%, 0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
}

.m-header-brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
  text-decoration: none;
}

.m-header-logo { color: var(--accent); }

.m-header-brand-text {
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.m-header-title {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-secondary);
  text-align: center;
  margin: 0;
  /* Hide on narrow viewports — brand + avatar always visible */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
@media (max-width: 360px) {
  .m-header-title { display: none; }
}

.m-header-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
}
.m-header-avatar:active { background: var(--bg-elevated); }
.m-header-avatar.is-authed { border-color: var(--accent); color: var(--accent); }

/* ── Main content padding so bottom-tab doesn't cover content ─ */
.m-main {
  min-height: calc(100dvh - 48px - 64px); /* header + tabs */
  padding-bottom: calc(64px + var(--safe-bottom) + 12px);
}
.kg-body .m-main {
  /* KG fills viewport — its container is fixed and overrides padding */
  padding-bottom: 0;
  min-height: 0;
}

/* ── Bottom-tab bar ───────────────────────────────────────── */
.m-bottom-tabs {
  position: fixed;
  left: 0;
  right: 0;
  bottom: calc(env(safe-area-inset-bottom, 0px) + 4px);
  z-index: 90;
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 4px;
  height: 60px;
  padding: 6px 8px;
  background: hsla(224, 28%, 5%, 0.95);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-top: 1px solid var(--border);
}

.m-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-height: 48px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-family: inherit;
  text-decoration: none;
  cursor: pointer;
  border-radius: 12px;
  padding: 4px 6px;
  -webkit-tap-highlight-color: transparent;
}
.m-tab:active { background: var(--bg-elevated); }

.m-tab-label {
  font-size: 0.65rem;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.m-tab.is-active {
  color: var(--accent);
  background: var(--accent-glow);
}
.m-tab.is-active .m-tab-label { font-weight: 600; }

.m-tab-disabled {
  opacity: 0.4;
  cursor: default;
}
.m-tab-disabled:active { background: none; }

/* ── Disabled-tab toast ───────────────────────────────────── */
.m-toast {
  position: fixed;
  left: 50%;
  bottom: calc(80px + env(safe-area-inset-bottom, 0px));
  transform: translate(-50%, 16px);
  z-index: 200;
  padding: 10px 18px;
  background: hsla(224, 28%, 10%, 0.95);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 24px;
  font-size: 0.85rem;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s var(--ease), transform 0.2s var(--ease);
}
.m-toast.is-visible {
  opacity: 1;
  transform: translate(-50%, 0);
}
```

- [ ] **Step 2: Wire the new CSS file into `mobile.css`**

Modify `website/mobile/css/mobile.css` — add at the very top (before `*, *::before, *::after { ... }`):

```css
@import url("/m/css/components/shell.css?v=20260524a");
```

Also: in the existing `mobile.css`, the old `.m-header`, `.m-header-title`, `.m-header-subtitle`, `.m-back`, `.m-header-action`, `.kg-m-header` rules are now superseded by `shell.css`. Delete the lines that conflict (the old `.m-header` block from lines ~74-127, and `.kg-m-header` lines ~452-484). Keep `.kg-m-search` and below — those are KG-specific and used by Phase 5.

- [ ] **Step 3: Add `shell.js` with tab active state + disabled toast**

Create `website/mobile/js/shell.js`:

```javascript
/* ═════════════════════════════════════════════════════════════
   Mobile shell — bottom-tab active state, disabled-tab toast,
   avatar pill click. Loaded on every /m/* page.
   ═════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── Active tab from current path ──
  var path = window.location.pathname;
  var tabFor = function () {
    if (path === '/m/' || path === '/m') return 'capture';
    if (path === '/m/knowledge-graph') return 'graph';
    return null;
  };
  var active = tabFor();
  if (active) {
    var el = document.querySelector('.m-tab[data-tab="' + active + '"]');
    if (el) el.classList.add('is-active');
  }

  // ── Disabled-tab toast ──
  var toastEl = null;
  var toastTimer = null;
  function showToast(message) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'm-toast';
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = message;
    toastEl.classList.add('is-visible');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      if (toastEl) toastEl.classList.remove('is-visible');
    }, 1800);
  }

  var disabledLabels = {
    notes: 'Notes — coming soon',
    chat: 'Chat — coming soon',
    profile: 'Profile — coming soon'
  };

  document.addEventListener('click', function (e) {
    var t = e.target.closest('.m-tab-disabled');
    if (!t) return;
    e.preventDefault();
    var name = t.dataset.tab;
    showToast(disabledLabels[name] || 'Coming soon');
  });

  // ── Avatar pill: hand off to auth-modal.js (Phase 3 wires the listener). ──
  // Anonymous => open sign-in modal. Authed => open account menu.
  // shell.js only paints the icon; auth-modal.js manages session state.

})();
```

- [ ] **Step 4: Sanity-check by curling the assets**

Run (Git Bash, repo root): `ENV=dev python run.py &`
Wait 3s.
Run: `curl -sS -o /dev/null -w "%{http_code} %{size_download}\n" http://127.0.0.1:10000/m/css/components/shell.css`
Expected: `200 <N>` where N > 1000 (bytes).
Run: `curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:10000/m/js/shell.js`
Expected: `200`.
Kill: `kill %1`.

- [ ] **Step 5: Manual viewport-emulation visual check (Claude in Chrome — operator-run or in CI)**

Open Chrome DevTools → toggle device toolbar → iPhone 14 Pro emulation. Navigate to `http://127.0.0.1:10000/m/`. Verify:
- Header is 48px tall, sticky on scroll, contains logo + page title + avatar pill
- Bottom-tab bar shows 5 tabs (Capture / Notes / Chat / Graph / Profile)
- Capture tab is highlighted teal
- Tapping Notes / Chat / Profile produces a toast "Coming soon"
- Tapping Graph navigates to `/m/knowledge-graph`
- Switch to Pixel 7 emulation; repeat
- Switch to iPad Mini emulation; verify layout (5 tabs should still fit; header is wider)

Note: this is gated to Phase 7 verification — Phase 2 commit is allowed if curls in Step 4 pass even without visual confirmation.

- [ ] **Step 6: Commit**

```bash
git add website/mobile/css/components/shell.css website/mobile/css/mobile.css website/mobile/js/shell.js
git commit -m "feat: hybrid nav scaffold mobile"
```

---

### Phase 3: OAuth modal — full-screen `<dialog>` with primary-CTA layout

**Files:**
- Create: `website/mobile/templates/_oauth_modal.html`
- Create: `website/mobile/css/components/auth-modal.css`
- Create: `website/mobile/js/auth-modal.js`
- Modify: `website/app.py` (`_render_with_mobile_shell` injects the modal at end of body)
- Modify: `website/mobile/css/mobile.css` (`@import` auth-modal CSS)

- [ ] **Step 1: Create the modal template**

Create `website/mobile/templates/_oauth_modal.html`:

```html
<!-- OAuth modal — injected at the end of <body> by _render_with_mobile_shell. -->
<dialog class="m-auth-modal" id="m-auth-modal" aria-labelledby="m-auth-title">
  <div class="m-auth-modal-inner">
    <button class="m-auth-close" id="m-auth-close" type="button" aria-label="Close sign-in">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
    </button>
    <h2 class="m-auth-title" id="m-auth-title">Sign in</h2>
    <p class="m-auth-subtitle">Save your zettels and access them anywhere.</p>

    <div class="m-auth-providers" id="m-auth-providers">
      <button class="m-auth-provider m-auth-provider-primary" data-provider="google" type="button">
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="#4285F4" d="M21.35 11.1H12.18v3.34h5.27c-.23 1.42-1.7 4.17-5.27 4.17-3.17 0-5.76-2.62-5.76-5.86s2.59-5.86 5.76-5.86c1.8 0 3.01.77 3.7 1.43l2.53-2.43C16.84 4.5 14.7 3.5 12.18 3.5 6.86 3.5 2.55 7.8 2.55 13.1s4.31 9.6 9.63 9.6c5.55 0 9.24-3.9 9.24-9.4 0-.63-.06-1.1-.07-1.2z"/>
        </svg>
        Continue with Google
      </button>
      <button class="m-auth-provider m-auth-provider-secondary" data-provider="apple" type="button">
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="currentColor" d="M16.36 1.43c-1.04.06-2.27.72-2.99 1.59-.66.78-1.21 1.93-1.05 3.07 1.13.04 2.3-.61 3-1.48.65-.84 1.13-1.97 1.04-3.18M19.7 17.3c-.5 1.14-.74 1.65-1.39 2.66-.91 1.41-2.19 3.16-3.77 3.17-1.4.02-1.76-.92-3.67-.91-1.91.02-2.31.93-3.71.91-1.58-.02-2.79-1.6-3.7-3.01-2.53-3.96-2.8-8.62-1.24-11.09 1.11-1.76 2.86-2.79 4.5-2.79 1.67 0 2.72.91 4.1.91 1.34 0 2.16-.92 4.09-.92 1.47 0 3.03.81 4.13 2.2-3.62 1.99-3.03 7.16.66 8.87z"/>
        </svg>
        Continue with Apple
      </button>
      <button class="m-auth-more" id="m-auth-more" type="button" aria-expanded="false" aria-controls="m-auth-more-options">
        More sign-in options
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </button>
      <div class="m-auth-more-options" id="m-auth-more-options" hidden>
        <button class="m-auth-provider m-auth-provider-secondary" data-provider="github" type="button">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.57.1.78-.25.78-.55v-2.16c-3.2.7-3.88-1.36-3.88-1.36-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.76 2.69 1.25 3.35.96.1-.74.4-1.25.72-1.54-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.18-3.1-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.15 1.18a10.95 10.95 0 0 1 5.74 0c2.19-1.49 3.15-1.18 3.15-1.18.62 1.58.23 2.75.11 3.04.74.81 1.18 1.84 1.18 3.1 0 4.42-2.69 5.39-5.26 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.66.79.55C20.21 21.38 23.5 17.07 23.5 12 23.5 5.65 18.35.5 12 .5z"/></svg>
          Continue with GitHub
        </button>
        <button class="m-auth-provider m-auth-provider-secondary" data-provider="twitter" type="button">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
          Continue with Twitter
        </button>
        <button class="m-auth-provider m-auth-provider-secondary" data-provider="facebook" type="button">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="#1877F2" aria-hidden="true"><path d="M24 12.07C24 5.4 18.63 0 12 0S0 5.4 0 12.07C0 18.1 4.39 23.1 10.13 24v-8.44H7.08v-3.49h3.05V9.41c0-3.02 1.79-4.69 4.53-4.69 1.31 0 2.68.24 2.68.24v2.97h-1.51c-1.49 0-1.96.93-1.96 1.89v2.26h3.33l-.53 3.49h-2.8V24C19.61 23.1 24 18.1 24 12.07"/></svg>
          Continue with Facebook
        </button>
        <button class="m-auth-provider m-auth-provider-secondary" data-provider="twitch" type="button">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="#9146FF" aria-hidden="true"><path d="M11.571 4.714h1.715v5.143h-1.715zm4.715 0h1.714v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714Z"/></svg>
          Continue with Twitch
        </button>
      </div>
    </div>

    <p class="m-auth-foot">By continuing you agree to our <a href="/about" target="_blank" rel="noopener">terms</a>.</p>
  </div>
</dialog>
```

- [ ] **Step 2: Add modal CSS**

Create `website/mobile/css/components/auth-modal.css`:

```css
/* ═════════════════════════════════════════════════════════════
   Mobile auth modal — full-screen <dialog> with primary-CTA
   OAuth grid. See plan §0 (R1) for design decisions.
   ═════════════════════════════════════════════════════════════ */

.m-auth-modal {
  border: none;
  background: var(--bg);
  color: var(--text);
  width: 100vw;
  height: 100dvh;
  max-width: 100vw;
  max-height: 100dvh;
  padding: 0;
  margin: 0;
}
.m-auth-modal::backdrop {
  background: hsla(224, 28%, 3%, 0.92);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.m-auth-modal-inner {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 480px;
  margin: 0 auto;
  padding: calc(56px + var(--safe-top)) 24px calc(40px + var(--safe-bottom));
}

.m-auth-close {
  position: absolute;
  top: calc(12px + var(--safe-top));
  right: 12px;
  width: 44px;
  height: 44px;
  border: none;
  background: none;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 50%;
}
.m-auth-close:active { background: var(--bg-elevated); }

.m-auth-title {
  font-size: 1.6rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 6px;
}
.m-auth-subtitle {
  font-size: 0.9rem;
  color: var(--text-secondary);
  margin-bottom: 28px;
}

.m-auth-providers {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.m-auth-provider {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  min-height: 48px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-card);
  color: var(--text);
  font-family: inherit;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.m-auth-provider:active { background: var(--bg-elevated); }
.m-auth-provider:disabled { opacity: 0.5; pointer-events: none; }

.m-auth-provider-primary {
  background: #fff;
  color: #111;
  border-color: #fff;
  min-height: 52px;
  font-weight: 600;
}
.m-auth-provider-primary:active { background: #eee; }

.m-auth-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  min-height: 44px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 0.9rem;
  cursor: pointer;
  margin-top: 4px;
}
.m-auth-more[aria-expanded="true"] svg { transform: rotate(180deg); }

.m-auth-more-options {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 6px;
}

.m-auth-foot {
  margin-top: auto;
  font-size: 0.75rem;
  color: var(--text-muted);
  text-align: center;
}
.m-auth-foot a { color: var(--accent); text-decoration: none; }
```

- [ ] **Step 3: Add modal-driving JS**

The existing `ZKAuth` global (defined at `website/features/user_auth/js/auth.js:458-463`) only exposes `.ready` (Promise resolving to the Supabase client), `.getClient()`, and `.__signalReady()`. We talk to Supabase directly via `client.auth.signInWithOAuth(...)`, `client.auth.getSession()`, and `client.auth.onAuthStateChange(...)`. Sign-out reuses the `window.signOut` global (defined at `auth.js:449`).

`auth.js`'s desktop-only DOM functions (`updateUI`, `applyAvatar`) are guarded with `if (!loginBtn || !userMenu) return;` (line 202) and `if (!userAvatar) return;` (line 131) — so loading auth.js on mobile is safe; they no-op when the desktop DOM is absent.

Create `website/mobile/js/auth-modal.js`:

```javascript
/* ═════════════════════════════════════════════════════════════
   Mobile auth modal — opens on header-avatar click (anonymous),
   talks to Supabase via window.ZKAuth.getClient() directly.
   ═════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var modal = document.getElementById('m-auth-modal');
  var avatar = document.getElementById('m-avatar-btn');
  var closeBtn = document.getElementById('m-auth-close');
  var moreBtn = document.getElementById('m-auth-more');
  var moreOptions = document.getElementById('m-auth-more-options');
  var providers = document.getElementById('m-auth-providers');

  if (!modal || !avatar) return;

  var _client = null;
  var _session = null;

  // ── Open / close ──
  function openModal() {
    if (typeof modal.showModal === 'function') modal.showModal();
    else modal.setAttribute('open', '');
  }
  function closeModal() {
    if (typeof modal.close === 'function') modal.close();
    else modal.removeAttribute('open');
  }

  avatar.addEventListener('click', function () {
    if (_session) openAccountMenu();
    else openModal();
  });

  closeBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', function (e) {
    // Backdrop click (clicks on the <dialog> element itself, not its inner)
    if (e.target === modal) closeModal();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal.open) closeModal();
  });

  // ── More options disclosure ──
  moreBtn.addEventListener('click', function () {
    var expanded = moreBtn.getAttribute('aria-expanded') === 'true';
    moreBtn.setAttribute('aria-expanded', String(!expanded));
    moreOptions.hidden = expanded;
  });

  // ── Provider clicks ──
  providers.addEventListener('click', function (e) {
    var btn = e.target.closest('.m-auth-provider');
    if (!btn || !btn.dataset.provider) return;
    if (!_client) {
      console.error('Supabase client not ready; sign-in unavailable');
      return;
    }
    btn.disabled = true;
    _client.auth.signInWithOAuth({
      provider: btn.dataset.provider,
      options: { redirectTo: window.location.origin + '/auth/callback' },
    }).catch(function (err) {
      console.error('OAuth sign-in failed:', err);
      btn.disabled = false;
    });
  });

  // ── Account menu (authed users) ──
  var accountMenu = null;
  function openAccountMenu() {
    if (accountMenu) return accountMenu.classList.add('is-visible');
    accountMenu = document.createElement('div');
    accountMenu.className = 'm-account-menu is-visible';
    accountMenu.innerHTML = (
      '<div class="m-account-menu-inner">' +
      '<button type="button" data-action="signout">Sign out</button>' +
      '</div>'
    );
    document.body.appendChild(accountMenu);
    accountMenu.addEventListener('click', function (e) {
      if (e.target.dataset.action === 'signout' && typeof window.signOut === 'function') {
        window.signOut();
        accountMenu.classList.remove('is-visible');
      }
    });
  }

  // ── Reflect auth state on the avatar pill ──
  function paintAvatar(session) {
    _session = session;
    avatar.classList.toggle('is-authed', Boolean(session));
  }

  // ── Bootstrap: wait for ZKAuth.ready, then bind to Supabase auth events ──
  function boot() {
    if (!window.ZKAuth || !window.ZKAuth.ready) {
      setTimeout(boot, 100);
      return;
    }
    window.ZKAuth.ready.then(function (client) {
      _client = client;
      client.auth.getSession().then(function (res) {
        paintAvatar(res && res.data ? res.data.session : null);
      });
      client.auth.onAuthStateChange(function (event, session) {
        paintAvatar(session);
        if (event === 'SIGNED_IN' && modal.open) closeModal();
      });
    });
  }
  boot();
})();
```

- [ ] **Step 4: (verified at plan-write) — confirm static mounts exist for auth.js + Supabase CDN preconnect**

Verified facts (no action needed beyond awareness):
- `app.py:267-268` mounts `/auth/css` and `/auth/js` to `website/features/user_auth/`. So `auth.js` is reachable at `/auth/js/auth.js`.
- Supabase v2 CDN is loaded via `<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>` (see `website/static/index.html:22`). The mobile shell needs to load it BEFORE `auth.js`.
- There is NO `/js/supabase-client.js` static file — Supabase loads from CDN, then `auth.js` instantiates the client itself via `supabase.createClient(...)` (auth.js:255-265).
- `/api/auth/config` exists (api/routes.py:277) — `auth.js` fetches it on init.

If the mounts ever change, this step needs updating.

- [ ] **Step 5: Inject modal HTML + load Supabase CDN + auth.js + auth-modal.js into the shell**

Modify `website/app.py:_render_with_mobile_shell`. Update the function to also inject the modal + auth scripts:

```python
_MOBILE_OAUTH_MODAL = MOBILE_TEMPLATES_DIR / "_oauth_modal.html"


def _render_with_mobile_shell(
    body_path: Path,
    *,
    page_title: str,
    body_class: str = "",
    extra_head: str = "",
) -> HTMLResponse:
    shell = _MOBILE_SHELL.read_text(encoding="utf-8")
    body = body_path.read_text(encoding="utf-8")
    oauth_modal = _MOBILE_OAUTH_MODAL.read_text(encoding="utf-8")
    rendered = (
        shell
        .replace("<!--ZK_MOBILE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_PAGE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_BODY_CLASS-->", body_class)
        .replace("<!--ZK_MOBILE_CONTENT-->", body)
    )
    if extra_head:
        rendered = rendered.replace("</head>", f"{extra_head}\n</head>", 1)
    # Append modal + auth scripts just before </body>.
    # Supabase CDN MUST load before auth.js (auth.js calls supabase.createClient).
    auth_block = (
        oauth_modal
        + '\n<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2" crossorigin></script>'
        + '\n<script src="/auth/js/auth.js?v=20260524a"></script>'
        + '\n<script src="/m/js/auth-modal.js?v=20260524a"></script>'
    )
    rendered = rendered.replace("</body>", auth_block + "\n</body>", 1)
    return HTMLResponse(content=rendered, headers={"Cache-Control": "no-store"})
```

Also: add a `preconnect` for the Supabase URL to the mobile shell `<head>` for first-paint perf. Modify `website/mobile/templates/_shell.html` — add inside `<head>` near the other preconnects:

```html
<link rel="preconnect" href="https://icmnskseuoteyirljswd.supabase.co">
<link rel="preload" href="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2" as="script" crossorigin>
```

Note: if the project's Supabase URL changes, update both the preconnect here and `website/static/index.html:19`.

- [ ] **Step 6: Wire the new CSS into mobile.css**

Modify `website/mobile/css/mobile.css` — add second `@import` after the shell one:

```css
@import url("/m/css/components/shell.css?v=20260524a");
@import url("/m/css/components/auth-modal.css?v=20260524a");
```

- [ ] **Step 7: Add a single Python test for modal injection**

Append to `tests/unit/mobile/test_mobile_shell.py`:

```python
def test_mobile_index_includes_oauth_modal() -> None:
    """/m/ HTML must include the OAuth modal (Phase 3)."""
    resp = _client().get("/m/")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="m-auth-modal"' in html
    assert 'data-provider="google"' in html
    assert 'data-provider="apple"' in html
    # More options must be hidden by default
    assert 'id="m-auth-more-options"' in html and 'hidden' in html
```

- [ ] **Step 8: Run the test**

Run: `pytest tests/unit/mobile/test_mobile_shell.py -v`
Expected: 5 PASS (including the new one).

- [ ] **Step 9: Manual smoke test**

Run: `ENV=dev python run.py &`
Wait 3s.
Open Chrome → iPhone 14 Pro emulation → `http://127.0.0.1:10000/m/`. Click avatar. Verify:
- Modal opens full-screen
- Google + Apple buttons visible above the fold
- "More sign-in options" expands to show GitHub / Twitter / Facebook / Twitch
- Close button (×) closes the modal
- Backdrop tap closes the modal
- Esc key closes the modal

Kill: `kill %1`.

- [ ] **Step 10: Commit**

```bash
git add website/mobile/templates/_oauth_modal.html website/mobile/css/components/auth-modal.css website/mobile/css/mobile.css website/mobile/js/auth-modal.js website/app.py tests/unit/mobile/test_mobile_shell.py
git commit -m "feat: OAuth modal mobile"
```

---

### Phase 4: Skeleton typewriter loader port (M1.4)

**Files:**
- Read first: `website/static/js/zk_skeleton_typewriter.js`
- Modify: `website/mobile/js/summarizer.js` (replace rotating-text with typewriter)
- Modify: `website/mobile/css/mobile.css` (add skeleton-card styles)

- [ ] **Step 1: (verified at plan-write) — typewriter API surface**

Verified facts from reading `website/static/js/zk_skeleton_typewriter.js`:
- Global: `window.ZKSkeletonTyper` (note: `Typer`, not `Typewriter`)
- API:
  - `var typer = ZKSkeletonTyper.attach(skeletonEl)` — mounts a `<span class="skeleton-typewriter">` INSIDE the passed element and starts typing
  - `typer.update({phase, elapsedMs})` — feed `add_zettel_api.js` status ticks; phases: `queued | running | long | succeeded | failed`
  - `typer.detach()` — fades out + removes the span; idempotent
- The module auto-injects its own scoped `<style>` once per document (line 72-78) — no external CSS needed for the typewriter span itself
- The typewriter expects to live INSIDE a "skeleton card" that has `.skeleton-line` shimmer children for full visual coherence (typewriter is one line BENEATH the shimmer lines)

- [ ] **Step 2: (verified at plan-write) — typewriter script is reachable on mobile**

Verified: `app.py:259` mounts `/js` → `STATIC_DIR/js`, and `zk_skeleton_typewriter.js` lives at `website/static/js/`. So `/js/zk_skeleton_typewriter.js` resolves from mobile pages. No mount change needed.

- [ ] **Step 3: Update mobile body fragment to include the typewriter script**

Modify `website/mobile/index.html` — add before the existing summarizer.js script:

```html
<script src="/js/zk_skeleton_typewriter.js?v=20260524a"></script>
<script src="/m/js/summarizer.js?v=20260524a"></script>
```

- [ ] **Step 4: Replace rotating-text logic in summarizer.js with `ZKSkeletonTyper` calls**

Modify `website/mobile/js/summarizer.js`:

1. **Delete** the `MESSAGES_QUEUED` / `MESSAGES_RUNNING` / `MESSAGES_LONG` arrays + the `msgIndex` / `msgTimer` / `currentPool` variables at the top of the IIFE (lines ~22-43).
2. **Replace** the `showLoading()` / `hideLoading()` / `handleStatusTick()` block (lines ~45-77) with:

```javascript
  var _typer = null;

  function showLoading() {
    loading.classList.add('active');
    result.classList.remove('active');
    errorEl.classList.remove('active');
    submitBtn.disabled = true;
    var skel = document.getElementById('skeleton-card');
    if (skel) {
      skel.hidden = false;
      if (window.ZKSkeletonTyper && typeof window.ZKSkeletonTyper.attach === 'function') {
        _typer = window.ZKSkeletonTyper.attach(skel);
      }
    }
  }

  function hideLoading() {
    loading.classList.remove('active');
    submitBtn.disabled = false;
    if (_typer && typeof _typer.detach === 'function') {
      _typer.detach();
      _typer = null;
    }
    var skel = document.getElementById('skeleton-card');
    if (skel) skel.hidden = true;
  }

  function handleStatusTick(tick) {
    if (_typer && typeof _typer.update === 'function') {
      _typer.update(tick);
    }
  }
```

3. **Remove** the `loadTxt` declaration at the top of the IIFE (line ~14) — no longer used since the typewriter writes into its own injected span. Also remove any references to `loadTxt` in the rest of the file.

- [ ] **Step 5: Update body fragment to use real skeleton-card structure**

Modify `website/mobile/index.html` — replace the existing `<div class="m-loading">` block with the skeleton-card structure (matches the desktop's `.home-card-skeleton` shape so the typewriter visually coheres):

```html
<!-- Loading: skeleton card with shimmer lines + ZKSkeletonTyper attaches a typing span inside -->
<div class="m-loading" id="loading">
  <div class="m-skeleton-card" id="skeleton-card" hidden>
    <div class="skeleton-line skeleton-title"></div>
    <div class="skeleton-line skeleton-body"></div>
    <div class="skeleton-line skeleton-body"></div>
    <div class="skeleton-line skeleton-meta"></div>
  </div>
</div>
```

(The `#loading-text` div is gone. The `m-spinner` is gone too — skeleton card replaces both.)

- [ ] **Step 6: Add skeleton card + shimmer CSS to mobile.css**

Modify `website/mobile/css/mobile.css` — replace the existing `.m-loading`/`.m-spinner`/`.m-loading-text` rules (lines ~258-281) with:

```css
.m-loading {
  display: none;
  padding: 24px 16px;
}
.m-loading.active { display: block; }

.m-skeleton-card {
  position: relative;
  margin: 0 auto;
  max-width: 480px;
  padding: 20px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  min-height: 180px;
  /* Pulse the shimmer lines, not the card itself — keeps the typewriter
     line fully visible (matches desktop home.css:603-611 fix). */
}

.skeleton-line {
  border-radius: 4px;
  background: hsla(172, 30%, 40%, 0.15);
  animation: skeletonPulse 1.2s ease-in-out infinite;
  margin-bottom: 8px;
}
.skeleton-title  { width: 70%; height: 16px; margin-bottom: 12px; }
.skeleton-body   { width: 100%; height: 12px; }
.skeleton-body:last-of-type { width: 80%; }
.skeleton-meta   { width: 40%; height: 10px; margin-top: 12px; }

@keyframes skeletonPulse {
  0%, 100% { opacity: 0.4; }
  50%      { opacity: 0.7; }
}
```

Renumber subsequent steps (the original Steps 6-7 become Steps 7-8).

- [ ] **Step 7: Manual smoke test**

Run: `ENV=dev python run.py &`
Wait 3s.
Open Chrome → iPhone 14 Pro emulation → `http://127.0.0.1:10000/m/`. Submit a known-fast URL (e.g. a GitHub README). Verify:
- Skeleton card appears immediately on submit
- Three shimmer lines pulse + typewriter line types/erases beneath them (matches desktop visual)
- Phase-aware vocabulary cycles when polling phase changes from queued → running → long
- Card vanishes when result arrives
- No JS errors in console

Kill: `kill %1`.

- [ ] **Step 8: Commit**

```bash
git add website/mobile/index.html website/mobile/js/summarizer.js website/mobile/css/mobile.css
git commit -m "feat: port skeleton typewriter to mobile"
```

---

### Phase 5: KG filter parity (M2.1-M2.4)

**Files:**
- Modify: `website/mobile/knowledge-graph.html` (filter sheet markup)
- Create: `website/mobile/css/components/kg-filters.css`
- Create: `website/mobile/js/kg-filters.js`
- Modify: `website/mobile/js/graph.js` (wire filter callbacks, add Global/Personal, pauseAnimation hook)
- Modify: `website/mobile/css/mobile.css` (`@import` kg-filters CSS)

- [ ] **Step 1: Add filter sheet markup to the KG body fragment**

Modify `website/mobile/knowledge-graph.html`. Replace the existing `<div class="kg-m-sheet" id="sheet">` block with the dual-mode version:

```html
<!-- Bottom Sheet: Detail mode (default) + Filters mode (toggled via segmented control) -->
<div class="kg-m-sheet" id="sheet">
  <div class="kg-m-sheet-handle"></div>
  <div class="kg-m-sheet-tabs" role="tablist">
    <button class="kg-m-sheet-tab is-active" id="sheet-tab-detail" role="tab" aria-selected="true" data-mode="detail">Detail</button>
    <button class="kg-m-sheet-tab" id="sheet-tab-filters" role="tab" aria-selected="false" data-mode="filters">Filters</button>
  </div>

  <!-- Detail mode -->
  <div class="kg-m-sheet-content" id="sheet-detail" role="tabpanel">
    <span class="kg-m-sheet-badge" id="sheet-badge">source</span>
    <h2 class="kg-m-sheet-title" id="sheet-title">Note Title</h2>
    <p class="kg-m-sheet-date" id="sheet-date"></p>
    <p class="kg-m-sheet-summary" id="sheet-summary"></p>
    <div class="kg-m-sheet-tags" id="sheet-tags"></div>
    <div class="kg-m-sheet-connections" id="sheet-connections">
      <h3>Connected Notes</h3>
      <div id="sheet-conn-list"></div>
    </div>
    <a class="kg-m-sheet-link" id="sheet-link" href="#" target="_blank" rel="noopener">
      View Original Source
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
    </a>
  </div>

  <!-- Filters mode -->
  <div class="kg-m-sheet-content" id="sheet-filters" role="tabpanel" hidden>
    <fieldset class="kg-m-filter-block">
      <legend>View</legend>
      <div class="kg-m-segmented" role="radiogroup" aria-label="Graph scope">
        <button class="kg-m-segment is-active" role="radio" aria-checked="true" data-view="global" type="button">Global</button>
        <button class="kg-m-segment" role="radio" aria-checked="false" data-view="my" type="button" aria-disabled="true" title="Sign in to view your personal graph">My zettels</button>
      </div>
    </fieldset>

    <fieldset class="kg-m-filter-block">
      <legend>Connection strength: <span id="kg-strength-readout">0.30</span></legend>
      <input type="range" class="kg-m-slider" id="kg-strength-slider" min="0.30" max="0.85" step="0.05" value="0.30" aria-label="Minimum connection strength">
    </fieldset>

    <fieldset class="kg-m-filter-block">
      <legend>Source</legend>
      <div class="kg-m-chips" id="kg-source-chips">
        <button class="kg-m-chip is-active" data-source="youtube" type="button"><span class="kg-m-chip-dot" style="background:var(--node-youtube)"></span>YouTube</button>
        <button class="kg-m-chip is-active" data-source="reddit" type="button"><span class="kg-m-chip-dot" style="background:var(--node-reddit)"></span>Reddit</button>
        <button class="kg-m-chip is-active" data-source="github" type="button"><span class="kg-m-chip-dot" style="background:var(--node-github)"></span>GitHub</button>
        <button class="kg-m-chip is-active" data-source="substack" type="button"><span class="kg-m-chip-dot" style="background:var(--node-substack)"></span>Substack</button>
        <button class="kg-m-chip is-active" data-source="medium" type="button"><span class="kg-m-chip-dot" style="background:var(--node-medium)"></span>Medium</button>
        <button class="kg-m-chip is-active" data-source="web" type="button"><span class="kg-m-chip-dot" style="background:var(--node-web)"></span>Web</button>
      </div>
    </fieldset>

    <fieldset class="kg-m-filter-block">
      <legend>Tags</legend>
      <div class="kg-m-chips kg-m-chips-selected" id="kg-tag-chips-selected"></div>
      <input type="text" class="kg-m-filter-search" id="kg-tag-search" placeholder="Search tags…" autocomplete="off">
      <div class="kg-m-suggestions" id="kg-tag-suggestions"></div>
    </fieldset>

    <fieldset class="kg-m-filter-block">
      <legend>Kastens</legend>
      <div class="kg-m-chips kg-m-chips-selected" id="kg-kasten-chips-selected"></div>
      <input type="text" class="kg-m-filter-search" id="kg-kasten-search" placeholder="Search kastens…" autocomplete="off">
      <div class="kg-m-suggestions" id="kg-kasten-suggestions"></div>
    </fieldset>

    <div class="kg-m-sheet-footer">
      <button class="kg-m-btn-secondary" id="kg-filter-reset" type="button">Reset</button>
      <button class="kg-m-btn-primary" id="kg-filter-apply" type="button">Apply (<span id="kg-filter-count-pill">0</span>)</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add KG filter CSS**

Create `website/mobile/css/components/kg-filters.css`:

```css
/* ═════════════════════════════════════════════════════════════
   KG mobile filter sheet — segmented control, slider, multi-
   select chips, sticky footer. See plan §0 (R4) for design.
   ═════════════════════════════════════════════════════════════ */

/* ── Search strip below shell header ──────────────────────── */
.kg-m-search-strip {
  position: fixed;
  top: calc(48px + var(--safe-top));
  left: 0;
  right: 0;
  z-index: 49;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: hsla(224, 28%, 5%, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
.kg-m-search { flex: 1; }
.kg-m-search-count {
  font-size: 0.7rem;
  color: var(--text-muted);
  padding: 0 6px;
}
.kg-m-search-clear {
  width: 28px;
  height: 28px;
  border: none;
  background: var(--bg-card);
  color: var(--text-secondary);
  border-radius: 50%;
  font-size: 1rem;
  cursor: pointer;
}

/* Filter badge */
.kg-m-filter-count {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 14px;
  height: 14px;
  padding: 0 4px;
  background: var(--accent);
  color: hsl(224, 28%, 5%);
  border-radius: 7px;
  font-size: 0.6rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── Recenter FAB ─────────────────────────────────────────── */
.kg-m-recenter {
  position: fixed;
  right: 14px;
  bottom: calc(80px + env(safe-area-inset-bottom));
  z-index: 80;
  width: 48px;
  height: 48px;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: var(--bg-card);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.kg-m-recenter:active { background: var(--bg-elevated); color: var(--accent); }

/* ── Sheet mode tabs (Detail | Filters) ───────────────────── */
.kg-m-sheet-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-bottom: 1px solid var(--border);
}
.kg-m-sheet-tab {
  height: 40px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  border-bottom: 2px solid transparent;
}
.kg-m-sheet-tab.is-active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

/* ── Filter blocks ────────────────────────────────────────── */
.kg-m-filter-block {
  border: none;
  margin: 0;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}
.kg-m-filter-block:last-of-type { border-bottom: none; }
.kg-m-filter-block legend {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 10px;
}

/* ── Segmented control (Global / Personal) ────────────────── */
.kg-m-segmented {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  gap: 0;
  padding: 4px;
  background: var(--bg-elevated);
  border-radius: 10px;
}
.kg-m-segment {
  height: 36px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 0.85rem;
  font-weight: 500;
  border-radius: 8px;
  cursor: pointer;
}
.kg-m-segment.is-active {
  background: var(--bg-card);
  color: var(--accent);
}
.kg-m-segment[aria-disabled="true"] {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ── Slider ───────────────────────────────────────────────── */
.kg-m-slider {
  width: 100%;
  -webkit-appearance: none;
  appearance: none;
  height: 32px;
  background: transparent;
  cursor: pointer;
}
.kg-m-slider::-webkit-slider-runnable-track {
  height: 4px;
  background: var(--border);
  border-radius: 2px;
}
.kg-m-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid var(--bg);
  margin-top: -10px;
  cursor: pointer;
}
.kg-m-slider::-moz-range-track {
  height: 4px;
  background: var(--border);
  border-radius: 2px;
}
.kg-m-slider::-moz-range-thumb {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid var(--bg);
  cursor: pointer;
}

/* ── Chip group (sources, selected tags/kastens) ──────────── */
.kg-m-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.kg-m-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-secondary);
  border-radius: 16px;
  font-family: inherit;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
}
.kg-m-chip.is-active {
  border-color: var(--accent);
  color: var(--accent);
}
.kg-m-chip-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.kg-m-chips-selected:empty {
  display: none;
}

/* ── Filter search + async suggestions ────────────────────── */
.kg-m-filter-search {
  width: 100%;
  height: 36px;
  margin-top: 8px;
  padding: 0 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-family: inherit;
  font-size: 0.85rem;
}
.kg-m-suggestions {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.kg-m-suggestions:empty { display: none; }

/* ── Sticky footer (Reset / Apply) ────────────────────────── */
.kg-m-sheet-footer {
  position: sticky;
  bottom: 0;
  display: flex;
  gap: 8px;
  padding: 12px 0;
  background: var(--bg-card);
  border-top: 1px solid var(--border);
}
.kg-m-btn-primary {
  flex: 1;
  height: 44px;
  border: none;
  border-radius: 10px;
  background: var(--accent);
  color: hsl(224, 28%, 5%);
  font-family: inherit;
  font-weight: 600;
  cursor: pointer;
}
.kg-m-btn-secondary {
  flex: 1;
  height: 44px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-elevated);
  color: var(--text);
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
}

/* ── Landscape fallback: side sheet ───────────────────────── */
@media (orientation: landscape) and (max-height: 480px) {
  .kg-m-sheet {
    top: 0;
    left: auto;
    right: 0;
    width: 360px;
    max-width: 60vw;
    max-height: 100dvh;
    border-radius: 16px 0 0 16px;
    border-left: 1px solid var(--border);
    border-top: none;
    transform: translateX(100%);
  }
  .kg-m-sheet.open { transform: translateX(0); }
}
```

- [ ] **Step 3: Add kg-filters JS for sheet mode-switch, slider, search, reset**

Create `website/mobile/js/kg-filters.js`:

```javascript
/* ═════════════════════════════════════════════════════════════
   Mobile KG filter sheet — mode switch, slider readout, chip
   search, multi-select, reset/apply. Exposes a small API for
   graph.js to consume via window.ZKMobileKGFilters.
   ═════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── DOM ──
  var sheet = document.getElementById('sheet');
  if (!sheet) return;

  var tabs = sheet.querySelectorAll('.kg-m-sheet-tab');
  var detailPanel = document.getElementById('sheet-detail');
  var filtersPanel = document.getElementById('sheet-filters');

  var slider = document.getElementById('kg-strength-slider');
  var readout = document.getElementById('kg-strength-readout');
  var sourceChips = document.getElementById('kg-source-chips');

  var segView = filtersPanel ? filtersPanel.querySelectorAll('.kg-m-segment') : [];
  var tagSearch = document.getElementById('kg-tag-search');
  var tagSelected = document.getElementById('kg-tag-chips-selected');
  var tagSuggestions = document.getElementById('kg-tag-suggestions');
  var kastenSearch = document.getElementById('kg-kasten-search');
  var kastenSelected = document.getElementById('kg-kasten-chips-selected');
  var kastenSuggestions = document.getElementById('kg-kasten-suggestions');

  var resetBtn = document.getElementById('kg-filter-reset');
  var applyBtn = document.getElementById('kg-filter-apply');
  var filterCountPill = document.getElementById('kg-filter-count-pill');
  var filterCountBadge = document.getElementById('filter-count');
  var filterToggleBtn = document.getElementById('filter-toggle');
  var recenterBtn = document.getElementById('recenter-btn');

  // ── State (mutable, exposed via getState) ──
  var state = {
    view: 'global',     // 'global' | 'my'
    strength: 0.30,
    sources: new Set(['youtube', 'reddit', 'github', 'substack', 'medium', 'web']),
    tags: new Set(),
    kastens: new Set(),
  };
  var availableTags = [];
  var availableKastens = [];

  // ── Listeners registry — graph.js subscribes ──
  var listeners = { change: [], recenter: [], view: [] };
  function emit(event) { listeners[event].forEach(function (fn) { try { fn(state); } catch (_) {} }); }

  // ── Sheet mode switch ──
  function setMode(mode) {
    tabs.forEach(function (t) {
      var on = t.dataset.mode === mode;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', String(on));
    });
    if (detailPanel) detailPanel.hidden = mode !== 'detail';
    if (filtersPanel) filtersPanel.hidden = mode !== 'filters';
  }
  tabs.forEach(function (t) { t.addEventListener('click', function () { setMode(t.dataset.mode); }); });

  // ── Sheet open/close ──
  function openSheet(mode) {
    sheet.classList.add('open');
    setMode(mode || 'detail');
  }
  function closeSheet() {
    sheet.classList.remove('open');
  }
  filterToggleBtn && filterToggleBtn.addEventListener('click', function () {
    if (sheet.classList.contains('open') && !filtersPanel.hidden) {
      closeSheet();
    } else {
      openSheet('filters');
    }
  });

  // ── Slider ──
  slider && slider.addEventListener('input', function () {
    var v = parseFloat(slider.value).toFixed(2);
    state.strength = parseFloat(v);
    if (readout) readout.textContent = v;
  });

  // ── Source chips (toggle) ──
  sourceChips && sourceChips.addEventListener('click', function (e) {
    var chip = e.target.closest('.kg-m-chip');
    if (!chip) return;
    var src = chip.dataset.source;
    chip.classList.toggle('is-active');
    if (chip.classList.contains('is-active')) state.sources.add(src);
    else state.sources.delete(src);
  });

  // ── Segmented view toggle ──
  Array.prototype.forEach.call(segView, function (seg) {
    seg.addEventListener('click', function () {
      if (seg.getAttribute('aria-disabled') === 'true') return;
      Array.prototype.forEach.call(segView, function (s) {
        s.classList.remove('is-active');
        s.setAttribute('aria-checked', 'false');
      });
      seg.classList.add('is-active');
      seg.setAttribute('aria-checked', 'true');
      state.view = seg.dataset.view;
      emit('view');
    });
  });

  // ── Multi-select chip search (tags + kastens, same logic) ──
  function bindChipSearch(searchInput, suggestionsEl, selectedEl, available, stateSet) {
    if (!searchInput) return;
    function renderSelected() {
      selectedEl.innerHTML = '';
      Array.from(stateSet).forEach(function (v) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'kg-m-chip is-active';
        chip.textContent = v + ' ×';
        chip.addEventListener('click', function () {
          stateSet.delete(v);
          renderSelected();
        });
        selectedEl.appendChild(chip);
      });
    }
    function renderSuggestions(q) {
      suggestionsEl.innerHTML = '';
      if (!q) return;
      var matches = available
        .filter(function (v) { return v.toLowerCase().indexOf(q.toLowerCase()) > -1 && !stateSet.has(v); })
        .slice(0, 7);
      matches.forEach(function (v) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'kg-m-chip';
        chip.textContent = v;
        chip.addEventListener('click', function () {
          stateSet.add(v);
          renderSelected();
          searchInput.value = '';
          suggestionsEl.innerHTML = '';
        });
        suggestionsEl.appendChild(chip);
      });
    }
    searchInput.addEventListener('input', function () { renderSuggestions(searchInput.value.trim()); });
    renderSelected();
    return { renderSelected: renderSelected, renderSuggestions: renderSuggestions };
  }
  var tagApi = bindChipSearch(tagSearch, tagSuggestions, tagSelected, availableTags, state.tags);
  var kastenApi = bindChipSearch(kastenSearch, kastenSuggestions, kastenSelected, availableKastens, state.kastens);

  // ── Reset + Apply ──
  resetBtn && resetBtn.addEventListener('click', function () {
    state.strength = 0.30;
    state.sources = new Set(['youtube', 'reddit', 'github', 'substack', 'medium', 'web']);
    state.tags = new Set();
    state.kastens = new Set();
    state.view = 'global';
    // Repaint UI
    slider.value = '0.30'; readout.textContent = '0.30';
    sourceChips.querySelectorAll('.kg-m-chip').forEach(function (c) { c.classList.add('is-active'); });
    tagApi && tagApi.renderSelected();
    kastenApi && kastenApi.renderSelected();
    Array.prototype.forEach.call(segView, function (s) {
      s.classList.toggle('is-active', s.dataset.view === 'global');
      s.setAttribute('aria-checked', String(s.dataset.view === 'global'));
    });
    updateBadges();
    emit('change');
    emit('view');
  });
  applyBtn && applyBtn.addEventListener('click', function () {
    updateBadges();
    emit('change');
    closeSheet();
  });

  // ── Recenter ──
  recenterBtn && recenterBtn.addEventListener('click', function () { emit('recenter'); });

  function activeCount() {
    var n = 0;
    if (state.strength > 0.30) n += 1;
    if (state.sources.size < 6) n += (6 - state.sources.size);
    n += state.tags.size;
    n += state.kastens.size;
    if (state.view !== 'global') n += 1;
    return n;
  }
  function updateBadges() {
    var n = activeCount();
    if (filterCountPill) filterCountPill.textContent = String(n);
    if (filterCountBadge) {
      filterCountBadge.hidden = n === 0;
      filterCountBadge.textContent = String(n);
    }
  }
  updateBadges();

  // ── Public API for graph.js ──
  window.ZKMobileKGFilters = {
    getState: function () { return state; },
    on: function (event, fn) { if (listeners[event]) listeners[event].push(fn); },
    setAvailable: function (tags, kastens) {
      availableTags.length = 0; Array.prototype.push.apply(availableTags, tags || []);
      availableKastens.length = 0; Array.prototype.push.apply(availableKastens, kastens || []);
    },
    enablePersonalView: function (enabled) {
      Array.prototype.forEach.call(segView, function (s) {
        if (s.dataset.view !== 'my') return;
        if (enabled) s.removeAttribute('aria-disabled');
        else s.setAttribute('aria-disabled', 'true');
      });
    },
    openDetail: function () { openSheet('detail'); },
    closeSheet: closeSheet,
  };
})();
```

- [ ] **Step 4: Update `mobile/js/graph.js` to use filter state + view + recenter + pauseAnimation**

Modify `website/mobile/js/graph.js`. Required changes:

1. Inside `initGraph()`, after `graph` is constructed, register filter listeners:

```javascript
    if (window.ZKMobileKGFilters) {
      // Populate available tags/kastens from fullData
      var tagSet = new Set(); var kastenSet = new Set();
      (fullData.nodes || []).forEach(function (n) {
        (n.tags || []).forEach(function (t) { tagSet.add(t); });
        (n.kastens || []).forEach(function (k) { kastenSet.add(k); });
      });
      window.ZKMobileKGFilters.setAvailable(Array.from(tagSet).sort(), Array.from(kastenSet).sort());

      window.ZKMobileKGFilters.on('change', applyMobileFilters);
      window.ZKMobileKGFilters.on('recenter', function () { graph.zoomToFit(800, 40); });
      window.ZKMobileKGFilters.on('view', reloadForView);

      // Enable Personal view only if auth helper reports a session.
      var hasSession = window.ZKAuth && window.ZKAuth.getSession && window.ZKAuth.getSession();
      window.ZKMobileKGFilters.enablePersonalView(Boolean(hasSession));
    }
```

2. Replace the existing chip listener block (the `chips.addEventListener('click', ...)` and `filterToggle.addEventListener('click', ...)` blocks near lines 495-510) — these are now owned by `kg-filters.js`.

3. Add `applyMobileFilters()`:

```javascript
  function applyMobileFilters() {
    var fs = window.ZKMobileKGFilters.getState();
    var filteredNodes = fullData.nodes.filter(function (n) {
      if (!fs.sources.has(n.group)) return false;
      if (fs.tags.size > 0) {
        var any = (n.tags || []).some(function (t) { return fs.tags.has(t); });
        if (!any) return false;
      }
      if (fs.kastens.size > 0) {
        var anyk = (n.kastens || []).some(function (k) { return fs.kastens.has(k); });
        if (!anyk) return false;
      }
      return true;
    });
    var nodeIds = new Set(filteredNodes.map(function (n) { return n.id; }));
    var filteredLinks = fullData.links.filter(function (l) {
      var s = typeof l.source === 'object' ? l.source.id : l.source;
      var t = typeof l.target === 'object' ? l.target.id : l.target;
      if (!nodeIds.has(s) || !nodeIds.has(t)) return false;
      var w = (typeof l.weight === 'number') ? l.weight : 1;
      return w >= fs.strength;
    });
    graphData = { nodes: filteredNodes, links: filteredLinks };
    nodeDegrees = computeDegrees(graphData);
    graph.graphData(graphData);
    updateStats();
    closeSheet();
    selectedNode = null;
    highlightNodes.clear();
    setTimeout(function () { graph.zoomToFit(600, 40); }, 600);
  }
```

4. Add `reloadForView()`:

```javascript
  function reloadForView() {
    var fs = window.ZKMobileKGFilters.getState();
    var url = fs.view === 'my' ? '/api/graph?view=my' : '/api/graph';
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject('api'); })
      .then(function (data) {
        fullData = data;
        fullData.nodes = (fullData.nodes || []).map(function (node) {
          node.group = normalizeGroup(node.group);
          return node;
        });
        graphData = JSON.parse(JSON.stringify(data));
        graphData.nodes = (graphData.nodes || []).map(function (node) {
          node.group = normalizeGroup(node.group);
          return node;
        });
        nodeDegrees = computeDegrees(fullData);
        graph.graphData(graphData);
        applyMobileFilters();
      })
      .catch(function () {
        statsEl.textContent = 'Failed to load ' + fs.view + ' graph';
      });
  }
```

5. Update `openSheet(node)` and `closeSheet()` to use the new filter API:

```javascript
  function openSheet(node) {
    // Same body content rendering as before — but ensure Detail mode is active.
    if (window.ZKMobileKGFilters && window.ZKMobileKGFilters.openDetail) {
      window.ZKMobileKGFilters.openDetail();
    } else {
      sheet.classList.add('open');
    }
    // ...existing body rendering (badge, title, summary, tags, connections, link)
  }
```

6. Add search count + clear support in `searchInput` listener:

```javascript
  searchInput.addEventListener('input', function () {
    var query = searchInput.value.toLowerCase().trim();
    highlightNodes.clear();
    selectedNode = null;
    var count = 0;
    if (query.length > 0) {
      graphData.nodes.forEach(function (node) {
        var match = node.name.toLowerCase().indexOf(query) > -1 ||
                    (node.tags || []).some(function (t) { return t.toLowerCase().indexOf(query) > -1; }) ||
                    (node.summary || '').toLowerCase().indexOf(query) > -1;
        if (match) { highlightNodes.add(node.id); count += 1; }
      });
    }
    var countEl = document.getElementById('search-count');
    var clearEl = document.getElementById('search-clear');
    if (countEl) {
      countEl.textContent = count + ' matches';
      countEl.hidden = query.length === 0;
    }
    if (clearEl) clearEl.hidden = query.length === 0;
    graph.nodeThreeObject(graph.nodeThreeObject());
  });

  document.getElementById('search-clear') && document.getElementById('search-clear').addEventListener('click', function () {
    searchInput.value = '';
    searchInput.dispatchEvent(new Event('input'));
  });
```

7. Add pauseAnimation when sheet is at full extent (optional optimization). Inside the existing handle/swipe handling, when `sheet.classList.add('open')` happens, after a 600ms wait (sheet animation done), call `graph.pauseAnimation()` if sheet covers canvas; on close call `graph.resumeAnimation()`.

(Implementation note: this is a polish optimization; the verifier may verify by checking that `pauseAnimation` is called.)

- [ ] **Step 5: Wire kg-filters CSS + script into the KG body fragment + mobile.css**

Modify `website/mobile/css/mobile.css` — add third `@import`:

```css
@import url("/m/css/components/shell.css?v=20260524a");
@import url("/m/css/components/auth-modal.css?v=20260524a");
@import url("/m/css/components/kg-filters.css?v=20260524a");
```

Modify `website/mobile/knowledge-graph.html` — add `kg-filters.js` BEFORE `graph.js`:

```html
<script src="/m/js/kg-filters.js?v=20260524a"></script>
<script src="/m/js/graph.js?v=20260524a"></script>
```

- [ ] **Step 6: Add a Python test for the new KG markup**

Append to `tests/unit/mobile/test_mobile_shell.py`:

```python
def test_mobile_kg_includes_filter_sheet() -> None:
    """/m/knowledge-graph includes the dual-mode filter sheet."""
    resp = _client().get("/m/knowledge-graph")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="sheet-tab-filters"' in html
    assert 'id="kg-strength-slider"' in html
    assert 'id="kg-tag-search"' in html
    assert 'id="kg-kasten-search"' in html
    assert 'id="recenter-btn"' in html
    # Personal-view button starts disabled
    assert 'data-view="my"' in html
    assert 'aria-disabled="true"' in html
```

- [ ] **Step 7: Run all mobile tests**

Run: `pytest tests/unit/mobile/ -v`
Expected: all PASS.

- [ ] **Step 8: Manual smoke test — KG filter parity**

Run: `ENV=dev python run.py &`
Wait 3s.
Open Chrome → iPhone 14 Pro → `http://127.0.0.1:10000/m/knowledge-graph`. Verify:
- Search strip below shell header; typing shows count + × clear
- Filters icon (with badge) opens bottom sheet in Filters mode
- Segmented control: Global active; Personal greyed/disabled (anon)
- Slider moves; readout updates 0.30 → 0.85
- Source chips toggle (e.g. turn off YouTube; canvas re-renders without YT)
- Tag search shows suggestions when typing
- Apply button closes sheet + canvas re-filters
- Reset button clears all filters
- Recenter floating button (bottom-right above tab bar) zooms-to-fit
- Tapping a node opens Detail mode; tab switcher swaps to Filters cleanly
- Landscape orientation: sheet slides in from the right (side-sheet fallback)

Kill: `kill %1`.

- [ ] **Step 9: Commit**

```bash
git add website/mobile/templates/_kg_filter_sheet.html website/mobile/knowledge-graph.html website/mobile/css/components/kg-filters.css website/mobile/css/mobile.css website/mobile/js/kg-filters.js website/mobile/js/graph.js tests/unit/mobile/test_mobile_shell.py
git commit -m "feat: KG filter parity mobile"
```

---

### Phase 6: PWA — manifest + service worker

**Files:**
- Create: `website/static/manifest.webmanifest`
- Create: `website/static/sw.js`
- Create: `website/static/icons/icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon-180.png` (generate from existing `website/static/favicon.svg`)
- Modify: `website/app.py` (serve manifest + sw.js with correct headers)
- Modify: `ops/caddy/Caddyfile` (Service-Worker-Allowed, Cache-Control for sw.js)
- Create: `tests/unit/mobile/test_pwa.py`

- [ ] **Step 1: Generate icons from existing favicon.svg**

Run (Git Bash, repo root): `mkdir -p website/static/icons`
Run (use ImageMagick if installed, else manual): `magick website/static/favicon.svg -background "#0a0b14" -resize 192x192 website/static/icons/icon-192.png && magick website/static/favicon.svg -background "#0a0b14" -resize 512x512 website/static/icons/icon-512.png && magick website/static/favicon.svg -background "#0a0b14" -resize 410x410 -gravity center -extent 512x512 website/static/icons/icon-maskable-512.png && magick website/static/favicon.svg -background "#0a0b14" -resize 180x180 website/static/icons/apple-touch-icon-180.png`

If ImageMagick is not available, the operator must generate these manually before commit. Document the size requirements:
- `icon-192.png` 192×192, background `#0a0b14`
- `icon-512.png` 512×512, background `#0a0b14`
- `icon-maskable-512.png` 512×512 with the icon centered in the inner 80% (410×410 safe zone)
- `apple-touch-icon-180.png` 180×180

Verify with: `ls -lh website/static/icons/`. Each should be 1-10 KB.

- [ ] **Step 2: Write the failing PWA tests**

Create `tests/unit/mobile/test_pwa.py`:

```python
"""Tests for PWA manifest + service worker (iter mobile-1a Phase 6)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from website.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_manifest_served_with_correct_content_type() -> None:
    resp = _client().get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")


def test_manifest_has_required_fields() -> None:
    resp = _client().get("/manifest.webmanifest")
    data = json.loads(resp.text)
    # Chrome installability requirements (web.dev 2024)
    assert data["name"]
    assert data["short_name"]
    assert data["start_url"] == "/m/"
    assert data["scope"] == "/m/"
    assert data["display"] == "standalone"
    assert data.get("id") == "/m/"
    assert data["theme_color"]
    assert data["background_color"]
    # Icons: at least one 192 and one 512, plus a maskable
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in data["icons"]}
    assert ("192x192", "any") in sizes
    assert ("512x512", "any") in sizes
    assert any("maskable" in s[1] for s in sizes)


def test_service_worker_served_with_correct_headers() -> None:
    resp = _client().get("/sw.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript") or \
           resp.headers["content-type"].startswith("text/javascript")
    # Must be served from root so it can claim /m/ scope
    # Cache-Control must be short (≤5min) to avoid stale-shell lockout
    cache = resp.headers.get("cache-control", "")
    assert "no-cache" in cache or "max-age=0" in cache or "max-age=300" in cache


def test_service_worker_does_not_cache_api() -> None:
    """sw.js source must NOT include /api in its cache allow-list."""
    resp = _client().get("/sw.js")
    src = resp.text
    assert "/api/" not in src or "'/api/'" not in src  # not in cache list
    # And must explicitly skip /api/ in fetch handler — look for the marker
    assert "url.pathname.startsWith('/api/')" in src or "pathname.startsWith(\"/api/\")" in src
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/unit/mobile/test_pwa.py -v`
Expected: 4 FAIL (404 on /manifest.webmanifest, 404 on /sw.js).

- [ ] **Step 4: Write the manifest**

Create `website/static/manifest.webmanifest`:

```json
{
  "name": "Zettelkasten — Capture your knowledge",
  "short_name": "Zettelkasten",
  "id": "/m/",
  "start_url": "/m/",
  "scope": "/m/",
  "display": "standalone",
  "orientation": "portrait",
  "theme_color": "#0a0b14",
  "background_color": "#0a0b14",
  "lang": "en",
  "dir": "ltr",
  "description": "Paste a URL. Get an AI summary. Build your second brain.",
  "icons": [
    { "src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
    { "src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

- [ ] **Step 5: Write the service worker**

Create `website/static/sw.js`:

```javascript
/* ═════════════════════════════════════════════════════════════
   Zettelkasten mobile — minimum-viable service worker.
   Network-first for HTML in /m/*; cache-first for /static/*;
   bypass /api/ and /kg/content/.
   Version bump invalidates old shell.
   ═════════════════════════════════════════════════════════════ */
const CACHE = 'zk-shell-v1';
const SHELL_URLS = [
  '/m/',
  '/m/knowledge-graph',
  '/m/css/mobile.css',
  '/m/css/components/shell.css',
  '/m/css/components/auth-modal.css',
  '/m/css/components/kg-filters.css',
  '/m/js/shell.js',
  '/m/js/auth-modal.js',
  '/m/js/summarizer.js',
  '/m/js/graph.js',
  '/m/js/kg-filters.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon-180.png',
  '/favicon.svg',
];

self.addEventListener('install', (event) => {
  // Pre-cache shell; do NOT skipWaiting — wait for user to refresh.
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL_URLS)));
});

self.addEventListener('activate', (event) => {
  // Delete every cache except current.
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)))
    )
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;

  // BYPASS: dynamic API + KG data + auth callback
  if (url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/kg/content/')) return;
  if (url.pathname.startsWith('/auth/')) return;

  // HTML in /m/* → network-first, fallback to cache
  if (url.pathname.startsWith('/m/') &&
      (event.request.destination === 'document' || event.request.mode === 'navigate')) {
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(event.request, copy));
          }
          return resp;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // /static/* + /m/css/* + /m/js/* + /favicon* → cache-first
  if (url.pathname.startsWith('/static/') ||
      url.pathname.startsWith('/m/css/') ||
      url.pathname.startsWith('/m/js/') ||
      url.pathname === '/favicon.svg') {
    event.respondWith(
      caches.match(event.request).then((hit) => hit || fetch(event.request).then((resp) => {
        if (resp && resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(event.request, copy));
        }
        return resp;
      }))
    );
    return;
  }

  // Everything else: passthrough
});
```

- [ ] **Step 6: Wire FastAPI handlers for manifest + sw.js with explicit headers**

Modify `website/app.py`. Add near other static-file handlers (after `/favicon.svg` if it exists, otherwise near the mobile routes):

```python
    @app.get("/manifest.webmanifest")
    async def pwa_manifest():
        path = STATIC_DIR / "manifest.webmanifest"
        return FileResponse(
            path,
            media_type="application/manifest+json",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/sw.js")
    async def pwa_service_worker():
        path = STATIC_DIR / "sw.js"
        return FileResponse(
            path,
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-cache, max-age=0",
                "Service-Worker-Allowed": "/",
            },
        )
```

Verify `FileResponse` is imported at the top of `app.py` (`from fastapi.responses import FileResponse`).

- [ ] **Step 7: Register the service worker from the mobile shell**

Modify `website/mobile/templates/_shell.html` — add inside `<body>` just before the closing tag's nearest script:

```html
<script>
  // PWA service worker registration — gated by feature detection.
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/m/' })
        .catch(function (err) { console.warn('SW register failed:', err); });
    });
  }
</script>
```

- [ ] **Step 8: Update Caddy with explicit headers for /sw.js + /manifest.webmanifest**

Modify `ops/caddy/Caddyfile`. After the existing `@static` matcher block, add:

```
@pwa {
  path /sw.js /manifest.webmanifest
}
header @pwa Cache-Control "no-cache, max-age=0"
header /sw.js Service-Worker-Allowed "/"
```

Note: this Caddy file is read by the running Caddy container. Changes require a Caddy reload. For 1a, the FastAPI handler already sets these headers; Caddy headers are a defense-in-depth layer.

- [ ] **Step 9: Run the tests**

Run: `pytest tests/unit/mobile/test_pwa.py -v`
Expected: 4 PASS.

- [ ] **Step 10: Manual install verification**

Run: `ENV=dev python run.py &`
Wait 3s.
Open Chrome → DevTools → Application tab → Manifest. Verify:
- Manifest is parsed without errors
- Icons render
- Installability checklist all green
- "Install" button is offered in the URL bar

Open Lighthouse → PWA category → run audit. Expected score: ≥ 90.

Open DevTools → Application → Service Workers. Verify `/sw.js` is registered with scope `/m/`. Refresh `/m/`. Verify cache `zk-shell-v1` contains the shell URLs.

Kill: `kill %1`.

- [ ] **Step 11: Commit**

```bash
git add website/static/manifest.webmanifest website/static/sw.js website/static/icons/ website/app.py website/mobile/templates/_shell.html ops/caddy/Caddyfile tests/unit/mobile/test_pwa.py
git commit -m "feat: PWA manifest + service worker"
```

---

### Phase 7: Verification + lint + PR ready

**Files:** none new; this is the verification gate.

- [ ] **Step 1: Run the full Python test suite (excluding live)**

Run (repo root): `pytest -m "not live"`
Expected: all pass (no regressions; new tests pass).

- [ ] **Step 2: Cross-device manual viewport check**

Run dev server. For each viewport (iPhone 14 Pro / Pixel 7 / iPad Mini), verify the full flow:

1. `/m/` — header, bottom tabs, hero, form, file-upload button, source select, submit; tap disabled tabs → toast; tap avatar → modal opens; submit a URL → skeleton typewriter → result; copy + source-link work; switch to desktop link sets cookie.
2. `/m/knowledge-graph` — search w/ count+clear, filter icon w/ badge, segmented control (Global active, Personal disabled while anon), slider, source chips, tag/kasten search w/ suggestions, reset, apply, recenter, node tap → Detail mode in sheet; landscape → side sheet.
3. Sign in via Google (if available) and verify avatar pill changes; sign out via account menu.
4. Install PWA from Chrome address bar; launch standalone; verify both pages render in standalone mode.

Document any failures inline; fix in this phase before final commit.

- [ ] **Step 3: Lighthouse PWA audit**

Open Chrome DevTools → Lighthouse → PWA → run audit. Expected score: ≥ 90.
If lower, identify failures and fix.

- [ ] **Step 4: Droplet-cost sanity check (local)**

Run dev server. In another shell: `ps aux | grep "python run.py"` → record RSS.
Open `/m/` and `/m/knowledge-graph` in 3 tabs to simulate load. After 30s, re-record RSS.
Expected: delta < 50 MB (matches existing mobile load profile; should not have grown materially).

- [ ] **Step 5: Final ruff pass**

Run: `ruff check website/ tests/unit/mobile/`
Expected: 0 errors.
If errors: `ruff check --fix website/ tests/unit/mobile/` (auto-fixable) then re-run.

- [ ] **Step 6: Verify the PR's commit log + ensure no temp files**

Run: `git log --oneline origin/master..HEAD`
Expected: ~6 commits matching the phase commit messages.

Run: `git status`
Expected: clean.

- [ ] **Step 7: Update audit doc §9 verification plan with actual results**

Edit `docs/mobile-1a/audit.md` — replace §9 content with the actual verification log (pytest results, Lighthouse score, droplet delta, viewports tested).

- [ ] **Step 8: Mark PR ready for review (remove draft status) — operator action**

Operator runs (NOT this plan): `gh pr ready 76`.

- [ ] **Step 9: Final commit (docs update)**

```bash
git add docs/mobile-1a/audit.md
git commit -m "docs: mobile 1a verification log"
git push
```

---

## 3. Cross-cutting safety guards (apply throughout)

| Guard | What to check |
|---|---|
| **No purple** | Grep every new CSS file for `hsl(2[5-9]\d`, `violet`, `purple`, `lavender`, `#[Aa]?[78]` shades — must be empty |
| **Teal only on chrome, amber only on KG** | Mobile shell + auth modal use `--accent` teal; only KG-specific files may use amber `#D4A024` (and they don't in this iteration) |
| **No infra disclosure** | Grep new mobile JS for `model`, `token`, `latency`, `score`, `query_class` — must not be surfaced in DOM |
| **Anonymous flow still works** | `/m/` summarize without sign-in must succeed end-to-end after every phase |
| **No `--no-verify` commits** | Pre-commit hooks must pass cleanly; no skips |
| **No Co-Authored-By trailers** | Commit messages stay 5-10 words, prefix tag only |
| **No `<private>` violations** | No Supabase keys, no GEMINI_API_KEY, no droplet IPs in any code, comment, or commit message |
| **Backwards-compat** | `/m/` and `/m/knowledge-graph` still respond 200 on bare requests; existing `add_zettel_api.js` flow unchanged |

---

## 4. Out-of-scope reminder (deferred to 1b+)

Do NOT implement in 1a:
- `/m/home`, `/m/zettels`, `/m/profile`, `/m/rag`, `/m/kastens`, `/m/pricing`, `/m/about`, `/m/nexus`
- Tablet-as-desktop heuristic refinement (M3.1)
- Mobile-side `/api/*` extensions
- Razorpay mobile-web checkout
- Twitter/X OAuth chip enablement (research-flagged risk; chip is in DOM but the provider may need a feature flag added in a later iteration)
- Apple Sign-In enable if SPF/sender-domain not validated yet

**Deferred deficiencies (small, low-impact, not in 1a):**
- **M1.5** — result-card action parity check ("does desktop have more actions than Copy + Source?"). Out of 1a because operator's locked scope didn't surface a specific gap; verify in 1b as part of the per-page deep-audit.
- **M1.6** — empty-state CTA after successful summarize. Current `/m/` already lets the user clear the URL field + submit again (not a dead-end). 1b can add an explicit "Add another" affordance.
- **M1.7** — source-select label parity. Mobile's `Newsletter` and desktop's wording need a side-by-side; the gap is cosmetic. 1b.

If any of these turn out to be higher-impact than estimated, the operator can pull them forward via a follow-up clarification.

---

## 5. Self-review checklist (run before handoff)

- [ ] Every M1.* / M2.* / M3.* (in-scope per §7.1) has a phase that addresses it
- [ ] Every research-derived decision in §0 maps to at least one code step
- [ ] No "TBD" / "TODO" / "fill in later" remains in the plan body
- [ ] Type/method names in later phases match earlier definitions (`ZKMobileKGFilters.getState`, `signInWithProvider`, `_render_with_mobile_shell` — used consistently)
- [ ] All commit messages obey CLAUDE.md (5-10 words, prefix tag, no `Co-Authored-By`)
- [ ] All new tests fail on first run, then pass after the implementation step
- [ ] Manual verification steps explicit (iPhone 14 Pro, Pixel 7, iPad Mini)
- [ ] Operator's locked answers from audit §7 + C1/C2/C3 honored exactly
- [ ] Open-flag at the top of this doc (M3.4 = "implicit-in-auth") visible to operator for explicit confirmation before Phase 1 starts