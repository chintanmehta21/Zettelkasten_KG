# Mobile iter-1a — Button & API Timing Verification

**Date:** 2026-05-24  
**Branch:** claude/vigorous-clarke-1b0f10  
**Scope:** `/m/` and `/m/knowledge-graph` interactive elements + API endpoint health + local vs production timing

---

## 1. Button Inventory (Phase A)

Sources verified: `_shell.html`, `_oauth_modal.html`, `index.html`, `knowledge-graph.html`, `shell.js`, `auth-modal.js`, `summarizer.js`, `kg-filters.js`, `graph.js`

### `/m/` page

| # | Page | Element | Trigger | Handler (file:line) | Action | Status | Notes |
|---|------|---------|---------|---------------------|--------|--------|-------|
| 1 | `/m/` | `.m-header-brand` (anchor) | click | `_shell.html:22` — native `<a>` | Navigate to `/m/` | ✅ | Plain anchor, no JS needed |
| 2 | `/m/` | `#m-avatar-btn` (button) | click | `auth-modal.js:126-132` | Anon → `openModal()`; Authed → `openAccountMenu()` | ✅ | State-gated on `_session` |
| 3 | `/m/` | `[data-tab="capture"]` (anchor) | click | `_shell.html:44` — native `<a>` | Navigate to `/m/` | ✅ | Active class set by `shell.js:17` |
| 4 | `/m/` | `[data-tab="notes"]` (button, disabled) | click | `shell.js:46-51` — `document.addEventListener('click')` | `showToast('Notes — coming soon')` | ✅ | `e.preventDefault()` prevents navigation |
| 5 | `/m/` | `[data-tab="chat"]` (button, disabled) | click | `shell.js:46-51` | `showToast('Chat — coming soon')` | ✅ | Same disabled-tab handler |
| 6 | `/m/` | `[data-tab="graph"]` (anchor) | click | `_shell.html:56` — native `<a>` | Navigate to `/m/knowledge-graph` | ✅ | Active class set by `shell.js:12` |
| 7 | `/m/` | `[data-tab="profile"]` (button, disabled) | click | `shell.js:46-51` | `showToast('Profile — coming soon')` | ✅ | Same disabled-tab handler |
| 8 | `/m/` | Footer "Switch to desktop site" (anchor) | click | `_shell.html:67` — native `<a>` | Navigate to `/?desktop=1` | ✅ | Plain anchor |
| 9 | `/m/` | `#document-upload-btn` (button) | click | `summarizer.js:173` | `documentInput.click()` — opens file picker | ✅ | Wired to hidden `#document-input` |
| 10 | `/m/` | `#url-input` (input[type=url]) | input | `summarizer.js:187-191` | Clears selected document if URL typed | ✅ | Mutual-exclusion with file upload |
| 11 | `/m/` | `#source-select` (select) | change | No explicit listener | Value read at form submit: `srcSel.value` | ✅ | Not event-driven; consumed at submit time |
| 12a | `/m/` | `#submit-btn` (submit) | submit | `summarizer.js:194` — `form.addEventListener('submit')` | URL path → `window.ZKAddZettel.add({...})` → POST `/api/zettels/add` | ✅ | |
| 12b | `/m/` | `#submit-btn` (submit) | submit | `summarizer.js:215-220` — same handler | Document path → `window.ZKAddZettel.uploadDocument({...})` | ✅ | Multipart, not JSON |
| 13 | `/m/` | `#copy-btn` (button) | click | `summarizer.js:162` | `navigator.clipboard.writeText(rawSummary)` | ✅ | No-ops if `rawSummary` empty |
| 14 | `/m/` | `#source-link` (anchor) | click | `summarizer.js:147-155` — `showResult()` sets `href` | Opens `data.source_url` in new tab; `aria-disabled` when document | ✅ | `target="_blank" rel="noopener"` |
| 15 | `/m/` | `#m-auth-close` (button) | click | `auth-modal.js:135-137` | `closeModal()` — `modal.close()` + restore `body.overflow` | ✅ | |
| 16 | `/m/` | `[data-provider="google"]` (button) | click | `auth-modal.js:165-177` — provider click delegation | `_client.auth.signInWithOAuth({provider:'google', options:{redirectTo:...}})` | ✅ | Disabled during in-flight call |
| 17 | `/m/` | `[data-provider="apple"]` (button, `hidden`) | click | Same provider handler | `_client.auth.signInWithOAuth({provider:'apple',...})` | ⚠️ | `hidden` attribute set; intentionally deferred per plan §0 (SPF/sender-domain) |
| 18 | `/m/` | `#m-auth-more` (button) | click | `auth-modal.js:152-161` | Toggles `aria-expanded` + removes/restores `hidden` on `#m-auth-more-options` | ✅ | |
| 19 | `/m/` | `[data-provider="github"]` (button, inside more-options) | click | `auth-modal.js:165-177` | `_client.auth.signInWithOAuth({provider:'github',...})` | ✅ | Visible after more-options expand |
| 20 | `/m/` | `[data-provider="twitter"]` (button, `hidden`, inside more-options) | click | Same provider handler | `_client.auth.signInWithOAuth({provider:'twitter',...})` | ⚠️ | `hidden` attribute set; intentionally deferred per plan §0 (API tier deprecation) |
| 21 | `/m/` | `[data-provider="facebook"]` (button, inside more-options) | click | `auth-modal.js:165-177` | `_client.auth.signInWithOAuth({provider:'facebook',...})` | ✅ | |
| 22 | `/m/` | `[data-provider="twitch"]` (button, inside more-options) | click | `auth-modal.js:165-177` | `_client.auth.signInWithOAuth({provider:'twitch',...})` | ✅ | |
| 23 | `/m/` | `#m-signout-btn` (dynamically created button) | click | `auth-modal.js:63-66` — `openAccountMenu()` | `window.signOut()` (from `auth.js`) | ✅ | Only present when authed; menu auto-closes on outside tap |
| 24 | `/m/` | Modal backdrop (`<dialog>` element itself) | click | `auth-modal.js:140-142` | `closeModal()` when `e.target === modal` | ✅ | Also fires on `Escape` via `cancel` event at line 144-147 |

### Auto-fired on page load — `/m/`

| # | Page | Element/Fetch | Trigger | Handler (file:line) | Action | Status | Notes |
|---|------|--------------|---------|---------------------|--------|--------|-------|
| L1 | `/m/` | SW register | `window load` | `_shell.html:71-77` | `navigator.serviceWorker.register('/sw.js', {scope:'/m/'})` | ✅ | Registers with scope `/m/` |
| L2 | `/m/` | `/api/auth/config` fetch | implicit via `auth.js` boot | `auth.js` init | GET `/api/auth/config` → 200 JSON (verified) | ✅ | Returns Supabase anon key + URL for client init |

### `/m/knowledge-graph` page (additional elements)

| # | Page | Element | Trigger | Handler (file:line) | Action | Status | Notes |
|---|------|---------|---------|---------------------|--------|--------|-------|
| 25 | `/m/kg` | `#search-input` (text input) | input | `graph.js:508-528` | Local node highlight by name/tags/summary; updates count badge + clear button visibility | ✅ | Pure client-side, no API call |
| 26 | `/m/kg` | `#search-clear` (button) | click | `graph.js:531-535` | Clears `#search-input` value + dispatches `InputEvent('input')` to reset highlights | ✅ | |
| 27 | `/m/kg` | `#filter-toggle` (button) | click | `kg-filters.js:73-79` | Opens sheet in filters mode; if sheet already open in filters mode → `closeSheet()` | ✅ | Toggle semantics correctly implemented |
| 28 | `/m/kg` | `#recenter-btn` (button) | click | `kg-filters.js:186` → `graph.js:365` via event | `emit('recenter')` → `graph.zoomToFit(800, 40)` | ✅ | Indirect via `ZKMobileKGFilters.on('recenter')` |
| 29 | `/m/kg` | `#sheet-tab-detail` (button, role=tab) | click | `kg-filters.js:61` — `tabs.forEach` listener | `setMode('detail')` — shows detail panel, hides filters panel | ✅ | `aria-selected` updated correctly |
| 30 | `/m/kg` | `#sheet-tab-filters` (button, role=tab) | click | `kg-filters.js:61` | `setMode('filters')` — shows filters panel, hides detail panel | ✅ | |
| 31 | `/m/kg` | `[data-view="global"]` (segmented button) | click | `kg-filters.js:99-111` | Sets `state.view = 'global'`; `emit('view')` → `reloadForView()` fetches `/api/graph` | ✅ | Default active state |
| 32 | `/m/kg` | `[data-view="my"]` (segmented button) | click | `kg-filters.js:99-111` | If `aria-disabled !== 'true'`: sets `state.view = 'my'`; `emit('view')` → `reloadForView()` fetches `/api/graph?view=my` | ✅ | Gated: `aria-disabled="true"` when anon; enabled by `ZKMobileKGFilters.enablePersonalView()` via auth state |
| 33 | `/m/kg` | `#kg-strength-slider` (range input) | input | `kg-filters.js:82-86` | Updates `state.strength`; updates readout text `#kg-strength-readout` | ✅ | Range: 0.30–0.85, step 0.05 |
| 34 | `/m/kg` | Source chips — 6 × `[data-source="*"]` | click | `kg-filters.js:89-96` — event delegation on `#kg-source-chips` | Toggle chip `is-active`; adds/removes source from `state.sources` Set | ✅ | Sources: youtube, reddit, github, substack, medium, web |
| 35 | `/m/kg` | `#kg-tag-search` (text input) | input | `kg-filters.js:150` — `bindChipSearch()` | Filters `availableTags` by query; renders up to 7 suggestions in `#kg-tag-suggestions` | ✅ | Suggestions only populated after graph loads and `setAvailable()` is called |
| 36 | `/m/kg` | Tag suggestion chips (dynamic) | click | `kg-filters.js:140-146` | Adds tag to `state.tags`; re-renders selected chips; clears search input | ✅ | |
| 37 | `/m/kg` | `#kg-kasten-search` (text input) | input | `kg-filters.js:155` — `bindChipSearch()` | Filters `availableKastens`; renders suggestions | ✅ | Same logic as tag search |
| 38 | `/m/kg` | Kasten suggestion chips (dynamic) | click | `kg-filters.js:140-146` | Adds kasten to `state.kastens` | ✅ | |
| 39 | `/m/kg` | `#kg-filter-reset` (button) | click | `kg-filters.js:158-178` | Resets `state` to defaults; repaints all filter UI; `emit('change')` + `emit('view')` if view changed | ✅ | Also reverts view to global |
| 40 | `/m/kg` | `#kg-filter-apply` (button) | click | `kg-filters.js:179-183` | `updateBadges()`; `emit('change')` → `applyMobileFilters()`; `closeSheet()` | ✅ | |
| 41 | `/m/kg` | Node click on graph | click | `graph.js:264-265` — `.onNodeClick(handleNodeClick)` | Camera fly to node; `openSheet(node)` after 600ms delay | ✅ | 3D ForceGraph3D event |
| 42 | `/m/kg` | Background click on graph | click | `graph.js:265` — `.onBackgroundClick(handleBackgroundClick)` | Clears selection; `closeSheet()`; clears `highlightNodes` | ✅ | |
| 43 | `/m/kg` | Sheet swipe-down (`.kg-m-sheet-handle` area) | touchend | `graph.js:500-505` | If `changedTouches[0].clientY - sheetTouchY > 60` → `closeSheet()` | ✅ | Registered with `{passive:true}` |
| 44 | `/m/kg` | `#sheet-link` (anchor in detail panel) | click | `graph.js:473` — `openSheet()` sets `href` | Opens `node.url` in new tab (`target="_blank"`) | ✅ | `href` set from node data at open time |
| 45 | `/m/kg` | Connection items in sheet (dynamic) | click | `graph.js:465-468` | `handleNodeClick(other)` — fly to connected node + open its sheet | ✅ | |

### Auto-fired on page load — `/m/knowledge-graph`

| # | Page | Fetch | Trigger | Handler (file:line) | Action | Status | Notes |
|---|------|-------|---------|---------------------|--------|--------|-------|
| L3 | `/m/kg` | `/api/graph` (with fallback to `/kg/content/graph.json`) | DOMContentLoaded | `graph.js:137-157` | Fetches graph data; falls back to static JSON on error; initializes 3D graph | ✅ | Fallback chain verified |
| L4 | `/m/kg` | `/api/graph?view=my` | on `[data-view="my"]` click (authed) | `graph.js:576-577` — `reloadForView()` | Re-fetches personal graph; recomputes tag/kasten vocabulary | ✅ | |
| L5 | `/m/kg` | SW register | `window load` | `_shell.html:71-77` (injected via shell) | Same SW as `/m/` — scope `/m/` | ✅ | |

---

## 2. API Endpoint Status (TestClient probes)

Probed with `fastapi.testclient.TestClient` against `create_app()` with stub env vars.  
`POST /api/zettels/add` with empty body returns 422 (Unprocessable Entity) — correct FastAPI validation behavior, not a 404.

| Endpoint | Method | Status | Content-Type |
|----------|--------|--------|--------------|
| `/api/auth/config` | GET | **200** | `application/json` |
| `/api/graph` | GET | **200** | `application/json` |
| `/api/graph?view=my` | GET | **200** | `application/json` |
| `/manifest.webmanifest` | GET | **200** | `application/manifest+json` |
| `/sw.js` | GET | **200** | `application/javascript` |
| `/kg/content/graph.json` | GET | **200** | `application/json` |
| `POST /api/zettels/add` (empty body) | POST | **422** | — (expected: schema validation) |

All 7 probed paths respond correctly. No 404s.

---

## 3. Local Timing per Endpoint

Server: in-process uvicorn on `127.0.0.1:18765`, `ENV=dev`. All runs warm (server started 3s before first request). Timings measured with `time.perf_counter()` wrapping `urllib.request.urlopen + read()`. 5 runs each.

| Endpoint | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | **Median** | p95 | Note |
|----------|-------|-------|-------|-------|-------|-----------|-----|------|
| `/api/auth/config` | 0.308 | 0.334 | 0.380 | 0.385 | 0.414 | **0.380s** | 0.414s | Warm; stable |
| `/api/graph` | 0.443 | 0.503 | 0.554 | 0.694 | 1.226 | **0.554s** | 1.226s | File I/O; p95 spike on first JSON load |
| `/api/graph?view=my` | 0.404 | 0.406 | 0.407 | 0.413 | 0.510 | **0.407s** | 0.510s | Anon user returns global graph; consistent |
| `/manifest.webmanifest` | 0.288 | 0.322 | 0.331 | 0.355 | 0.485 | **0.331s** | 0.485s | Static file serve |
| `/sw.js` | 0.273 | 0.287 | 0.297 | 0.297 | 0.303 | **0.297s** | 0.303s | Fastest; smallest response |
| `/kg/content/graph.json` | 0.316 | 0.360 | 0.381 | 0.438 | 0.882 | **0.381s** | 0.882s | File I/O; occasional large-graph parse spike |

> Note: local times include Python HTTP overhead (no persistent connection). Production times use HTTP/2 + Brotli compression through Caddy, which adds TLS and proxy overhead but gains HTTP/2 multiplexing. Direct comparison should focus on order-of-magnitude, not raw delta.

---

## 4. Production Timing per Endpoint

**Retrieval method:** `gh workflow run "Read Recent Logs"` triggered (run `26357442191`); Caddy access log parsed from SSH stdout. Log covers the last 500 access log entries from the live DigitalOcean droplet (blue container, 2026-05-24).

| Endpoint | N hits (last 500 lines) | Median (s) | Min (s) | Max (s) | Status codes |
|----------|------------------------|------------|---------|---------|-------------|
| `/api/auth/config` | 2 | **0.1734s** | 0.1728 | 0.1734 | 200 ×2 |
| `/api/graph` | 15 | **0.2124s** | 0.1876 | 1.3096 | 200 ×15 |
| `/api/zettels/add` | 1 | **0.3390s** | 0.3390 | 0.3390 | 202 ×1 |
| `/kg/content/graph.json` | 0 | n/a | — | — | — (no hits in window) |
| `/manifest.webmanifest` | 0 | n/a | — | — | — (new in this PR; not yet deployed) |
| `/sw.js` | 0 | n/a | — | — | — (new in this PR; not yet deployed) |

> `/manifest.webmanifest` and `/sw.js` have zero production hits as expected — they are new routes introduced in this PR (mobile-1a) and have not yet been deployed to production.

---

## 5. Local vs Production Comparison

| Endpoint | Local Median | Prod Median | Ratio (prod/local) | Flag |
|----------|-------------|-------------|---------------------|------|
| `/api/auth/config` | 0.380s | 0.173s | 0.46× | — Prod faster (HTTP/2 + Brotli + warm cache) |
| `/api/graph` | 0.554s | 0.212s | 0.38× | — Prod faster (pre-warmed worker, Brotli compression) |
| `/api/zettels/add` | n/a (POST) | 0.339s | — | 202 Accepted — async poll; expected |
| `/kg/content/graph.json` | 0.381s | n/a | — | No prod hits in window |
| `/manifest.webmanifest` | 0.331s | n/a | — | New; no prod data yet |
| `/sw.js` | 0.297s | n/a | — | New; no prod data yet |

Production is consistently faster than local on all measured endpoints. This is expected:
- Production uses HTTP/2 with Brotli content encoding through Caddy, reducing transfer size of JSON responses significantly.
- Local measurements include Python HTTP overhead without keep-alive.
- No regressions observed; no endpoint is slower in production than local.
- `/api/graph` prod max of 1.31s (cold or large graph): within acceptable bounds; no timeout risk.

---

## 6. Issues Found

| # | Severity | Description |
|---|----------|-------------|
| I-1 | ⚠️ INFO | `[data-provider="apple"]` and `[data-provider="twitter"]` buttons are present in DOM with `hidden` attribute. This is intentional per plan §0 deferrals (Apple: SPF/sender-domain; Twitter: API tier deprecation). No functional breakage — the provider click handler will fire correctly if `hidden` is removed. |
| I-2 | ⚠️ INFO | `auth.js` (`/auth/js/auth.js`) is the desktop auth module, served to mobile pages. `auth-modal.js` depends on `window.ZKAuth` which is set by `auth.js`. The desktop `auth.js` looks up desktop-specific DOM IDs (e.g. `#login-btn`, `#user-menu`) which will not exist on mobile — those `getElementById` calls return `null` and are no-ops. `window.ZKAuth` and `window.signOut` are still exported correctly. Risk: low, but desktop `auth.js` is loading unnecessary DOM resolution code on every mobile page. |
| I-3 | ⚠️ INFO | `#source-select` has no `change` event listener in `summarizer.js`. Its value is read at submit time. This is correct behavior — the select is a passive input, not an interactive trigger. No issue. |
| I-4 | ⚠️ INFO | `ZKSkeletonTyper` (`/js/zk_skeleton_typewriter.js`) is loaded from `/js/` not `/m/js/`. It is not listed in the SW `SHELL_URLS` precache. On offline load of `/m/`, the typewriter animation will fail silently (guarded by `if (window.ZKSkeletonTyper && ...)` check in `summarizer.js:29`). No functional breakage; SW already bypasses API calls anyway. |
| I-5 | ⚠️ INFO | `add_zettel_api.js` is loaded from `/js/add_zettel_api.js` (shared static), not from `/m/js/`. It is not in SW `SHELL_URLS`. Same offline caveat as I-4 — if SW is serving a cached `/m/` page offline, the submit handler will show "Add Zettel API helper failed to load" error. Acceptable for offline — no network, no summarize anyway. |
| I-6 | ℹ️ NOTE | The `#kg-tag-search` and `#kg-kasten-search` suggestion systems depend on `ZKMobileKGFilters.setAvailable()` being called after graph data loads. If the graph fetch fails entirely, `availableTags` and `availableKastens` remain empty arrays — inputs work but show no suggestions. This is correct graceful degradation. |

---

## 7. Operator Action Items

| # | Priority | Item |
|---|----------|------|
| A-1 | Medium | After mobile-1a is deployed to production, re-run `gh workflow run "Read Recent Logs"` and verify that `/manifest.webmanifest` and `/sw.js` appear in the Caddy access log with 200 status codes. |
| A-2 | Low | Consider adding `/js/add_zettel_api.js` and `/js/zk_skeleton_typewriter.js` to the SW `SHELL_URLS` precache list (`website/static/sw.js`) in a follow-up to improve offline experience completeness (I-4, I-5). |
| A-3 | Low | Consider extracting a minimal mobile-specific `auth-init.js` that only exports `window.ZKAuth` and `window.signOut` without desktop DOM resolution, to replace the desktop `auth.js` on mobile pages (I-2). Not urgent — current behavior is correct and silent. |
| A-4 | Info | Apple and Twitter OAuth providers (I-1): re-enable by removing `hidden` attribute once SPF/sender-domain is validated (Apple) and API tier is confirmed (Twitter). No code change needed beyond the `hidden` removal. |
