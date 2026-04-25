# KG UI Production Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift the 3D Knowledge Graph at `/knowledge-graph` from "works" to "production-grade UI" in one bundled change covering 26 user-confirmed items (12 user-requested + 13 Chrome-inspection-found + 1 missing-coverage gap).

**Architecture:** Three layers — (1) tiny backend wiring change so the KG page receives the shared header/auth-modal shell; (2) zero-schema-change client-side join of `/api/rag/sandboxes` membership data into the existing `/api/graph` payload; (3) major front-end restructure of `website/features/knowledge_graph/` (HTML, CSS, JS) plus a new add-to-Kasten modal. Verified end-to-end via Claude in Chrome with up-to-3 iteration loops.

**Tech Stack:** Python 3.12 + FastAPI (route layer), vanilla JS / Three.js / 3d-force-graph 1.79.1 (frontend), pytest (Python tests), Claude in Chrome (visual verification).

**Spec:** [docs/superpowers/specs/2026-04-25-kg-ui-production-pass-design.md](../specs/2026-04-25-kg-ui-production-pass-design.md)

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `website/app.py` | modify | Switch `/knowledge-graph` route from `FileResponse` to `_render_with_shell` so the shared header (with login modal) is injected |
| `website/features/knowledge_graph/index.html` | rewrite | New header structure (toggle + search + filter + reset), new side-panel structure (date pill + badge + 2 circular icon buttons + close), header shell placeholder, add-to-kasten modal placeholder, loading/empty/error overlay placeholders |
| `website/features/knowledge_graph/css/style.css` | rewrite | Header dead-band fix, segmented toggle pill, restyled search w/ count+clear, multi-section filter dropdown, restyled side panel (badge match, icon buttons), modal styles, overlays, focus rings |
| `website/features/knowledge_graph/js/app.js` | rewrite | Hardened brief extractor; smart label truncation; dynamic source list from data; multi-section filter incl. Kastens; toggle persistence + greyed-Personal-opens-login; restyled search w/ count + clear + auto-frame; reset view; spotlight ring → billboarded mesh + scale reset; auto-rotate off; loading + empty + error states; connection-click panel refresh; drop legend; Esc closes filter |
| `website/features/knowledge_graph/js/kasten_modal.js` | create | Self-contained add-to-Kasten modal logic: list user kastens, "+ create new" inline expand, add-membership POST, success toast |
| `tests/website/test_kg_route_shell.py` | create | Asserts `/knowledge-graph` HTML body contains the rendered header partial (i.e., `_render_with_shell` ran), so login modal DOM is present |
| `tests/website/test_kg_extract_brief.py` | create | Pure-JS-logic-equivalent unit tests in Python don't apply; instead add Python test that the `/api/graph` endpoint returns the JSON-stringified `summary` field shape the new client extractor expects, so contract drift is caught |
| `docs/research/kg_ui_pass/` | create | Per-iteration screenshots from Claude in Chrome for each of the 26 changes |

**No backend schema changes.** No new endpoints. No changes to `/api/graph`, `/api/rag/sandboxes`, `/api/rag/sandboxes/{id}/members`, or `/api/me`.

---

## Phase 0: Documentation Discovery

Before any implementation, verify every external assumption used in the spec.

### Task 0: Verify external assumptions

**Files:** read-only

- [ ] **Step 1: Confirm `_render_with_shell` injection**

Read `website/app.py:50-69`. Confirm `_render_with_shell(path: Path) -> HTMLResponse` reads the file, replaces `<!--ZK_HEADER-->` with `header.html` contents, returns HTMLResponse. Confirm `/home`, `/`, `/home/zettels`, `/home/kastens` all use it.

- [ ] **Step 2: Confirm header partial owns the login modal**

Read `website/features/header/header.html`. Grep for `id="login-modal"`. Confirm the modal node is inside this partial and that `header.js` (loaded via `<script src="/header/js/header.js">` inside that partial) initialises `auth.js`.

Run: `grep -n "login-modal" website/features/header/header.html` — expect at least one hit.

- [ ] **Step 3: Confirm `auth.js` exposes a way to open the modal externally**

Read `website/features/user_auth/js/auth.js:357-362`. Currently `openModal()` is internal (closure-scoped). Decide: either expose it via `window.openLoginModal = openModal;` (small change in auth.js) **or** trigger it by clicking the existing login button in the injected header partial (DOM-driven, no JS change to auth.js). **Choose the DOM-driven approach for zero coupling**: query `document.querySelector('.home-login-btn, [data-open-login]')?.click()`. Confirm a login button exists in `header.html` with a stable selector.

Run: `grep -n "login-btn\|home-login\|data-open-login" website/features/header/header.html`. Note the selector for the implementation phase.

- [ ] **Step 4: Confirm sandbox API contracts**

Read `website/api/sandbox_routes.py:94-105` (`_serialize_sandbox`), `:183-190` (list endpoint), `:251-262` (members endpoint), `:298-322` (POST members).

Confirm:
- `GET /api/rag/sandboxes` → `{"sandboxes": [{id, name, description, icon, color, default_quality, member_count, last_used_at, created_at, updated_at}, ...]}`. **Member node IDs are NOT included** — must fetch separately.
- `GET /api/rag/sandboxes/{id}/members` → `{"members": [{node_id, name, ...}, ...]}`.
- `POST /api/rag/sandboxes/{id}/members` body `{"node_ids": ["yt-foo", ...]}` → adds and returns updated `{members: [...]}`.
- `POST /api/rag/sandboxes` body `{"name": "...", "description": "..."}` → creates and returns `{sandbox: {...}}`.

Note: All endpoints require Supabase JWT in `Authorization: Bearer <token>` header (extract from `localStorage` keys starting with `sb-` and ending with `-auth-token`, same pattern as existing `getStoredAuthToken()` in `app.js`).

- [ ] **Step 5: Confirm 3d-force-graph 1.79.1 RingGeometry / billboard support**

Inspect `https://github.com/vasturiano/3d-force-graph/blob/v1.79.1/example/spiderweb-graph/index.html` and Three.js docs for `RingGeometry(innerRadius, outerRadius, thetaSegments)` and `mesh.lookAt(camera.position)`. Confirm `THREE.RingGeometry` is available in the loaded `three@0.160.1` build (it is).

- [ ] **Step 6: Run existing test suite — baseline green**

Run: `pytest tests/website/ -q`
Expected: PASS, current count baseline noted.

- [ ] **Step 7: Commit discovery notes**

Append a short discovery summary block (under 30 lines) to the bottom of the spec file `docs/superpowers/specs/2026-04-25-kg-ui-production-pass-design.md` under a new `## 9 — Phase-0 discovery findings` heading: confirmed shell helper, confirmed login button selector chosen, confirmed sandbox API shapes, confirmed Three.js APIs available, baseline test count.

```bash
git add docs/superpowers/specs/2026-04-25-kg-ui-production-pass-design.md
git commit -m "docs: KG spec phase-0 discovery findings"
```

---

## Phase 1: Route shell + login-modal availability + cache-bust

Foundation: make the KG page a first-class shell-rendered page so the login modal is in the DOM. Add cache-busting query string so future redeploys cannot serve stale JS.

### Task 1.1: Switch `/knowledge-graph` to `_render_with_shell`

**Files:**
- Modify: `website/app.py:248-252`
- Modify: `website/features/knowledge_graph/index.html` (add `<!--ZK_HEADER-->` placeholder)
- Test: `tests/website/test_kg_route_shell.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/website/test_kg_route_shell.py`:

```python
"""KG route must render via shell so the global header (with login modal) is injected."""
from fastapi.testclient import TestClient

from website.app import create_app


def test_knowledge_graph_route_includes_shared_header():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/knowledge-graph", headers={"User-Agent": "Mozilla/5.0 (desktop)"})
    assert resp.status_code == 200
    body = resp.text
    # Shell injection happened: placeholder is gone and header DOM is present.
    assert "<!--ZK_HEADER-->" not in body, "Shell placeholder was not replaced"
    assert 'id="login-modal"' in body, "Header partial (with login modal) was not injected"
    # KG content still present.
    assert 'id="graph-container"' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/website/test_kg_route_shell.py -v`
Expected: FAIL with assertion `Shell placeholder was not replaced` (or similar — current route uses `FileResponse` which doesn't process placeholders, and `index.html` has no placeholder yet).

- [ ] **Step 3: Add placeholder to KG `index.html`**

Modify `website/features/knowledge_graph/index.html`. Insert immediately after the opening `<body>` tag (line 12), before the `<a class="skip-link" ...>`:

```html
<body>
  <!--ZK_HEADER-->
  <a class="skip-link" href="#graph-container">Skip to graph</a>
```

- [ ] **Step 4: Switch route handler to `_render_with_shell`**

Modify `website/app.py:248-252`:

```python
    @app.get("/knowledge-graph")
    async def knowledge_graph(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/knowledge-graph", status_code=302)
        return _render_with_shell(KG_DIR / "index.html")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/website/test_kg_route_shell.py -v`
Expected: PASS.

- [ ] **Step 6: Run full suite to confirm no regression**

Run: `pytest tests/website/ -q`
Expected: PASS, count unchanged from baseline + 1.

- [ ] **Step 7: Commit**

```bash
git add tests/website/test_kg_route_shell.py website/app.py website/features/knowledge_graph/index.html
git commit -m "feat: render KG page through shared shell for login modal access"
```

### Task 1.2: Cache-bust the KG static assets

**Files:**
- Modify: `website/features/knowledge_graph/index.html` (script + stylesheet tags)

- [ ] **Step 1: Append build-version query string to JS and CSS tags**

Edit `website/features/knowledge_graph/index.html`. Replace:

```html
  <link rel="stylesheet" href="/kg/css/style.css">
```

with:

```html
  <link rel="stylesheet" href="/kg/css/style.css?v=20260425a">
```

And replace:

```html
  <script src="/kg/js/app.js"></script>
```

with:

```html
  <script src="/kg/js/app.js?v=20260425a"></script>
```

The `v=` token is bumped on every deploy of this feature. After Phase 13 verification, an automated SHA-based bump can replace this manual scheme — out of scope for now.

- [ ] **Step 2: Confirm browsers will fetch the new versions**

No test needed; Chrome/Caddy treats different query strings as different cache keys.

- [ ] **Step 3: Commit**

```bash
git add website/features/knowledge_graph/index.html
git commit -m "fix: cache-bust KG css/js so deploys cannot serve stale assets"
```

---

## Phase 2: Hardened brief-summary extractor (P0 #2)

The current `extractBriefFromSummary()` in local source already exists (lines 44–56 of `app.js`) but production is on an older build that never deployed it. We harden the local function so it can NEVER return raw JSON, regardless of input shape.

### Task 2.1: Replace `extractBriefFromSummary` with hardened version

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js:44-56`

- [ ] **Step 1: Replace the function**

Find the existing function block (lines 44–56). Replace with:

```javascript
  // Defensive brief-summary extractor.
  //
  // Production data ships `node.summary` as a JSON-stringified envelope:
  //   { "mini_title": "", "brief_summary": "…", "detailed_summary": [...], "closing_remarks": "…" }
  // but several legacy rows ship plain strings, and a small fraction of the
  // envelope is malformed. This function NEVER returns a value that starts
  // with "{" — it always degrades to a human-readable string.
  function extractBriefFromSummary(raw) {
    const text = String(raw == null ? '' : raw).trim();
    if (!text) return '';

    // Plain string (legacy) — return as-is, capped to 800 chars to keep panel tidy.
    if (text.charAt(0) !== '{') {
      return text.length > 800 ? text.slice(0, 800).trimEnd() + '…' : text;
    }

    // Try to parse the envelope. If it fails OR yields no usable text,
    // fall back to a stripped-of-braces best-effort excerpt.
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object') {
        const candidates = [
          parsed.brief_summary,
          parsed.briefSummary,
          parsed.summary,
        ];
        for (const c of candidates) {
          if (typeof c === 'string' && c.trim()) return c.trim();
        }
        // Try first non-empty bullet of detailed_summary[0].bullets.
        const detailed = Array.isArray(parsed.detailed_summary) ? parsed.detailed_summary : [];
        for (const section of detailed) {
          const bullets = Array.isArray(section?.bullets) ? section.bullets : [];
          for (const b of bullets) {
            if (typeof b === 'string' && b.trim()) return b.trim();
          }
        }
        // Last resort: closing_remarks.
        if (typeof parsed.closing_remarks === 'string' && parsed.closing_remarks.trim()) {
          return parsed.closing_remarks.trim();
        }
      }
    } catch (_err) { /* fall through */ }

    // Could not parse and could not find a clean field — strip braces+keys
    // from the raw text and return the first 240 chars so the user sees
    // SOMETHING readable instead of a JSON dump.
    const stripped = text
      .replace(/[{}\[\]"]/g, ' ')
      .replace(/\b\w+_summary\b\s*:?/g, ' ')
      .replace(/\bmini_title\b\s*:?/g, ' ')
      .replace(/\bdetailed_summary\b\s*:?/g, ' ')
      .replace(/\bclosing_remarks\b\s*:?/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    return stripped.length > 240 ? stripped.slice(0, 240).trimEnd() + '…' : stripped;
  }
```

- [ ] **Step 2: Smoke-test in browser console**

After redeploy in Phase 13, run in browser DevTools at `https://zettelkasten.in/knowledge-graph`:

```javascript
// Should return a clean sentence, never `{"...`:
fetch('/api/graph').then(r=>r.json()).then(d => {
  const samples = d.nodes.slice(0,5).map(n => extractBriefFromSummary(n.summary));
  console.table(samples.map(s => ({first50: s.slice(0,50), startsWithBrace: s.startsWith('{')})));
});
```
Expected: every row `startsWithBrace === false`.

- [ ] **Step 3: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "fix: harden KG brief-summary extractor to never return raw JSON"
```

### Task 2.2: API contract test (drift guard)

**Files:**
- Test: `tests/website/test_kg_extract_brief.py` (create)

- [ ] **Step 1: Write the contract test**

Create `tests/website/test_kg_extract_brief.py`:

```python
"""Guard against /api/graph drifting away from the shape the KG client expects.

The KG client has a defensive brief extractor (extractBriefFromSummary in
website/features/knowledge_graph/js/app.js). This test asserts the contract
holds: nodes ship a `summary` field that is either a plain string OR a
JSON-stringified object containing at least one of the keys the extractor
walks (brief_summary, summary, detailed_summary, closing_remarks).
"""
import json

from fastapi.testclient import TestClient

from website.app import create_app


_EXTRACTOR_KEYS = {"brief_summary", "briefSummary", "summary", "detailed_summary", "closing_remarks"}


def test_graph_summary_field_is_extractor_compatible():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/graph")
    assert resp.status_code == 200
    payload = resp.json()
    nodes = payload.get("nodes") or []
    if not nodes:
        # Empty graph in CI — contract trivially holds.
        return

    bad = []
    for n in nodes:
        s = n.get("summary")
        if s is None or s == "":
            continue  # extractor handles empty.
        if not isinstance(s, str):
            bad.append((n.get("id"), "non-string summary"))
            continue
        if s.lstrip().startswith("{"):
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError:
                bad.append((n.get("id"), "summary starts with { but is not valid JSON"))
                continue
            if not isinstance(parsed, dict):
                bad.append((n.get("id"), "JSON summary is not an object"))
                continue
            if not (set(parsed.keys()) & _EXTRACTOR_KEYS):
                bad.append((n.get("id"), f"JSON summary has none of the extractor keys ({sorted(_EXTRACTOR_KEYS)})"))

    assert not bad, f"Nodes with extractor-incompatible summary: {bad[:5]}"
```

- [ ] **Step 2: Run test**

Run: `pytest tests/website/test_kg_extract_brief.py -v`
Expected: PASS (current data is compatible).

- [ ] **Step 3: Commit**

```bash
git add tests/website/test_kg_extract_brief.py
git commit -m "test: contract guard for KG /api/graph summary shape"
```

---

## Phase 3: Header restructure — scaffold the new layout (CSS+HTML only)

We add the new structural elements (toggle container, reset button) and adjust the header CSS so the dead-band is gone. JS wiring follows in later phases.

### Task 3.1: Update header HTML

**Files:**
- Modify: `website/features/knowledge_graph/index.html` (header block, lines 14–62)

- [ ] **Step 1: Replace the header block**

Replace lines 14–62 with:

```html
  <!-- Header -->
  <header class="kg-header">
    <div class="kg-header-left">
      <a href="/" class="kg-back" title="Back to Summarizer" aria-label="Back to Summarizer">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="19" y1="12" x2="5" y2="12"></line>
          <polyline points="12 19 5 12 12 5"></polyline>
        </svg>
      </a>
      <svg class="kg-logo-icon" width="26" height="26" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <line x1="16" y1="5" x2="6" y2="16" stroke="#D4A024" stroke-width="1.2" opacity="0.35"/>
        <line x1="16" y1="5" x2="26" y2="16" stroke="#D4A024" stroke-width="1.2" opacity="0.35"/>
        <line x1="6" y1="16" x2="16" y2="27" stroke="#D4A024" stroke-width="1.2" opacity="0.3"/>
        <line x1="26" y1="16" x2="16" y2="27" stroke="#D4A024" stroke-width="1.2" opacity="0.3"/>
        <line x1="6" y1="16" x2="26" y2="16" stroke="#D4A024" stroke-width="1.2" opacity="0.2"/>
        <line x1="16" y1="5" x2="16" y2="27" stroke="#D4A024" stroke-width="1.2" opacity="0.2"/>
        <circle cx="16" cy="5" r="3" fill="#D4A024"/>
        <circle cx="6" cy="16" r="2.5" fill="#D4A024" opacity="0.8"/>
        <circle cx="26" cy="16" r="2.5" fill="#D4A024" opacity="0.8"/>
        <circle cx="16" cy="27" r="2.5" fill="#D4A024" opacity="0.65"/>
        <circle cx="16" cy="16" r="2" fill="#D4A024" opacity="0.5"/>
      </svg>
      <div class="kg-title-group">
        <h1 class="kg-title">Knowledge Graph</h1>
        <span class="kg-subtitle" id="graph-stats">Loading...</span>
      </div>
    </div>
    <div class="kg-header-right">
      <!-- View toggle: always visible. Personal segment greys out when logged out. -->
      <div class="kg-view-toggle" id="view-toggle" role="tablist" aria-label="Graph scope">
        <button class="kg-view-btn active" data-view="global" type="button" role="tab" aria-selected="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="2" y1="12" x2="22" y2="12"></line>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
          </svg>
          <span>Global</span>
        </button>
        <button class="kg-view-btn" data-view="my" type="button" role="tab" aria-selected="false" aria-disabled="true" title="Sign in to switch to Personal">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
          <span>Personal</span>
        </button>
      </div>
      <div class="kg-search-wrapper">
        <svg class="kg-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <input type="text" class="kg-search" id="search-input" placeholder="Search notes..." autocomplete="off" aria-label="Search notes">
        <span class="kg-search-count hidden" id="search-count" aria-live="polite"></span>
        <button class="kg-search-clear hidden" id="search-clear" type="button" aria-label="Clear search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
      <button class="kg-filter-btn" id="filter-btn" type="button" title="Filter notes" aria-label="Filter notes">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
        </svg>
      </button>
      <button class="kg-reset-btn" id="reset-view-btn" type="button" title="Reset view" aria-label="Reset view">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 3 21 3 21 9"></polyline>
          <polyline points="9 21 3 21 3 15"></polyline>
          <line x1="21" y1="3" x2="14" y2="10"></line>
          <line x1="3" y1="21" x2="10" y2="14"></line>
        </svg>
      </button>
    </div>
  </header>
```

- [ ] **Step 2: Replace the filter dropdown HTML (will be JS-rendered now, leave only the empty container)**

Replace lines 64–96 with:

```html
  <!-- Filter dropdown — rendered dynamically by app.js -->
  <div class="kg-filter-dropdown hidden" id="filter-dropdown" role="dialog" aria-label="Filters">
    <section class="kg-filter-section" data-section="source">
      <header class="kg-filter-section-header">
        <span>Source</span>
        <svg class="kg-filter-section-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </header>
      <div class="kg-filter-section-body" id="filter-source-body"></div>
    </section>
    <section class="kg-filter-section" data-section="kastens">
      <header class="kg-filter-section-header">
        <span>Kastens</span>
        <svg class="kg-filter-section-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </header>
      <div class="kg-filter-section-body" id="filter-kastens-body">
        <p class="kg-filter-empty" id="filter-kastens-empty">Loading…</p>
      </div>
    </section>
  </div>
```

- [ ] **Step 3: Replace the side-panel HTML with new structure**

Replace lines 101–136 with:

```html
  <!-- Side panel -->
  <aside class="kg-panel hidden" id="side-panel" data-node-id="" aria-label="Note details">
    <div class="kg-panel-content" id="panel-content">
      <header class="kg-panel-meta-row">
        <span class="kg-panel-date hidden" id="panel-date"></span>
        <span class="kg-panel-badge" id="panel-badge">source</span>
        <a class="kg-panel-icon-btn" id="panel-link" href="#" target="_blank" rel="noopener" title="View original source" aria-label="View original source">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
            <polyline points="15 3 21 3 21 9"></polyline>
            <line x1="10" y1="14" x2="21" y2="3"></line>
          </svg>
        </a>
        <button class="kg-panel-icon-btn" id="panel-add-kasten" type="button" title="Add to a Kasten" aria-label="Add to a Kasten">
          <span class="kg-panel-icon-mask" style="--mask-url: url(/artifacts/logo-kastens.svg)"></span>
        </button>
        <button class="kg-panel-close" id="panel-close" type="button" title="Close" aria-label="Close details panel">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </header>
      <h2 class="kg-panel-title" id="panel-title">Note Title</h2>
      <p class="kg-panel-summary" id="panel-summary">Summary goes here...</p>
      <div class="kg-panel-tags" id="panel-tags"></div>
      <div class="kg-panel-section">
        <h3 class="kg-panel-section-title">Connected Notes</h3>
        <div class="kg-panel-connections" id="panel-connections"></div>
      </div>
    </div>
  </aside>
```

- [ ] **Step 4: Drop the legend (P2 #23) and add overlays**

Replace lines 138–146 (`<div class="kg-legend">…`) with:

```html
  <!-- Loading / empty / error overlays -->
  <div class="kg-overlay hidden" id="overlay-loading" aria-live="polite">
    <div class="kg-overlay-skeleton">
      <span></span><span></span><span></span>
    </div>
    <p class="kg-overlay-text">Loading graph…</p>
  </div>
  <div class="kg-overlay hidden" id="overlay-empty" aria-live="polite">
    <p class="kg-overlay-text">No notes match these filters.</p>
    <button class="kg-overlay-btn" id="overlay-empty-reset" type="button">Reset filters</button>
  </div>
  <div class="kg-overlay hidden" id="overlay-error" aria-live="assertive">
    <p class="kg-overlay-text" id="overlay-error-text">Could not load graph data.</p>
    <button class="kg-overlay-btn" id="overlay-error-retry" type="button">Retry</button>
  </div>
```

- [ ] **Step 5: Add Add-to-Kasten modal placeholder**

Insert before the `<script>` tags at the bottom of `<body>`:

```html
  <!-- Add to Kasten modal -->
  <div class="kg-kasten-modal hidden" id="kasten-modal" role="dialog" aria-modal="true" aria-labelledby="kasten-modal-title">
    <div class="kg-kasten-modal-backdrop" id="kasten-modal-backdrop"></div>
    <div class="kg-kasten-modal-card">
      <header class="kg-kasten-modal-header">
        <h2 id="kasten-modal-title">Add to a Kasten</h2>
        <button class="kg-kasten-modal-close" id="kasten-modal-close" type="button" aria-label="Close">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </header>
      <p class="kg-kasten-modal-subtitle" id="kasten-modal-note-name"></p>
      <ul class="kg-kasten-modal-list" id="kasten-modal-list" role="listbox" aria-label="Your kastens"></ul>
      <div class="kg-kasten-modal-error hidden" id="kasten-modal-error"></div>
      <footer class="kg-kasten-modal-footer">
        <button class="kg-kasten-modal-cancel" id="kasten-modal-cancel" type="button">Cancel</button>
        <button class="kg-kasten-modal-add" id="kasten-modal-add" type="button" disabled>Add</button>
      </footer>
    </div>
  </div>
```

Also load the new modal script just before `app.js`:

```html
  <script src="/kg/js/kasten_modal.js?v=20260425a"></script>
  <script src="/kg/js/app.js?v=20260425a"></script>
```

- [ ] **Step 6: Sanity check — page should still load (raw)**

Run a quick local check (in any shell):

```bash
python -c "from pathlib import Path; t = Path('website/features/knowledge_graph/index.html').read_text(); print('placeholder:', '<!--ZK_HEADER-->' in t); print('toggle:', 'view-toggle' in t); print('reset:', 'reset-view-btn' in t); print('overlay:', 'overlay-loading' in t); print('kasten-modal:', 'kasten-modal' in t)"
```
Expected: all True.

- [ ] **Step 7: Commit**

```bash
git add website/features/knowledge_graph/index.html
git commit -m "feat: KG header + side panel structural rewrite (no behaviour yet)"
```

### Task 3.2: Header CSS — restyle + dead-band fix

**Files:**
- Modify: `website/features/knowledge_graph/css/style.css`

- [ ] **Step 1: Replace existing `.kg-header` rules**

Find the existing header rules (search for `.kg-header {`). Replace the whole header section through `.kg-filter-btn` (everything that styles header items) with the block below. Keep colour/font tokens identical to current ones; only structural and feedback changes.

```css
/* ============================================
   Header
   ============================================ */
.kg-header {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: rgba(8, 12, 24, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  z-index: 100;
}
.kg-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.kg-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.kg-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px; height: 36px;
  color: rgba(220, 228, 240, 0.7);
  border-radius: 10px;
  transition: background 0.15s, color 0.15s;
}
.kg-back:hover { background: rgba(255,255,255,0.05); color: #fff; }
.kg-logo-icon { flex-shrink: 0; }
.kg-title-group { display: flex; flex-direction: column; line-height: 1.1; }
.kg-title { margin: 0; font-size: 1.05rem; font-weight: 600; color: #fff; letter-spacing: -0.01em; }
.kg-subtitle { font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; color: rgba(180, 192, 210, 0.6); margin-top: 2px; }

/* Segmented Personal/Global toggle */
.kg-view-toggle {
  display: inline-flex;
  align-items: center;
  height: 36px;
  padding: 4px;
  background: rgba(8, 12, 24, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  gap: 2px;
}
.kg-view-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 9px;
  color: rgba(180, 192, 210, 0.6);
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.kg-view-btn svg { width: 14px; height: 14px; flex-shrink: 0; }
.kg-view-btn:hover:not(.active):not([aria-disabled="true"]) { color: #fff; background: rgba(255,255,255,0.04); }
.kg-view-btn.active {
  background: #0B0F1A;
  border-color: rgba(255,255,255,0.12);
  color: #fff;
}
.kg-view-btn[aria-disabled="true"] {
  cursor: pointer; /* still clickable — opens login modal */
  color: rgba(180, 192, 210, 0.35);
}
.kg-view-btn[aria-disabled="true"]:hover { color: rgba(180, 192, 210, 0.55); }

/* Search */
.kg-search-wrapper {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 280px;
}
.kg-search-icon {
  position: absolute;
  left: 11px; /* was 14px — moved 3px left per spec */
  color: rgba(180, 192, 210, 0.55);
  pointer-events: none;
}
.kg-search {
  width: 100%;
  height: 36px;
  padding: 0 64px 0 33px; /* left was 36; -3px to match icon shift. right reserved for count+clear */
  background: rgba(8, 12, 24, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  color: #fff;
  font-size: 0.85rem;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.kg-search::placeholder { color: rgba(180, 192, 210, 0.4); }
.kg-search:focus { border-color: rgba(20, 184, 166, 0.55); box-shadow: 0 0 0 3px rgba(20, 184, 166, 0.12); }
.kg-search-count {
  position: absolute;
  right: 36px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: rgba(180, 192, 210, 0.6);
  pointer-events: none;
}
.kg-search-clear {
  position: absolute;
  right: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px; height: 24px;
  background: transparent;
  border: 0;
  border-radius: 6px;
  color: rgba(180, 192, 210, 0.6);
  cursor: pointer;
}
.kg-search-clear:hover { background: rgba(255,255,255,0.06); color: #fff; }

/* Filter + reset buttons (icon-only round) */
.kg-filter-btn,
.kg-reset-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px; height: 36px;
  background: rgba(8, 12, 24, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  color: rgba(180, 192, 210, 0.7);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.kg-filter-btn:hover,
.kg-reset-btn:hover { background: rgba(20,184,166,0.08); border-color: rgba(20,184,166,0.35); color: #fff; }
.kg-filter-btn.active { background: rgba(20,184,166,0.12); border-color: rgba(20,184,166,0.5); color: #2dd4bf; }

/* Focus rings (a11y) */
.kg-back:focus-visible,
.kg-search:focus-visible,
.kg-search-clear:focus-visible,
.kg-filter-btn:focus-visible,
.kg-reset-btn:focus-visible,
.kg-view-btn:focus-visible,
.kg-panel-icon-btn:focus-visible,
.kg-panel-close:focus-visible {
  outline: 2px solid rgba(20, 184, 166, 0.55);
  outline-offset: 2px;
}
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/css/style.css
git commit -m "style: KG header restyle + dead-band fix + a11y focus rings"
```

### Task 3.3: Filter-dropdown CSS (multi-section)

**Files:**
- Modify: `website/features/knowledge_graph/css/style.css`

- [ ] **Step 1: Replace existing `.kg-filter-dropdown` block with the new multi-section styles**

Find the current `.kg-filter-dropdown` rules and replace with:

```css
/* Filter dropdown — multi-section */
.kg-filter-dropdown {
  position: fixed;
  top: 70px;
  right: 80px;
  width: 240px;
  background: rgba(12, 16, 28, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 8px;
  z-index: 200;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: calc(100vh - 100px);
  overflow-y: auto;
}
.kg-filter-section { display: flex; flex-direction: column; }
.kg-filter-section + .kg-filter-section { border-top: 1px solid rgba(255,255,255,0.05); margin-top: 4px; padding-top: 6px; }
.kg-filter-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(180,192,210,0.55);
  cursor: pointer;
  user-select: none;
}
.kg-filter-section-chevron { transition: transform 0.18s; }
.kg-filter-section.collapsed .kg-filter-section-chevron { transform: rotate(-90deg); }
.kg-filter-section.collapsed .kg-filter-section-body { display: none; }
.kg-filter-section-body { display: flex; flex-direction: column; padding: 2px 4px; gap: 2px; }

.kg-filter-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 0.85rem;
  color: rgba(220, 228, 240, 0.9);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, opacity 0.15s;
}
.kg-filter-item:hover { background: rgba(255,255,255,0.04); }
.kg-filter-item input[type="checkbox"] { display: none; }
.kg-filter-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; transition: opacity 0.15s; }

/* Bolder unchecked feedback (P2 #21) */
.kg-filter-item.unchecked { color: rgba(180,192,210,0.45); text-decoration: line-through; }
.kg-filter-item.unchecked .kg-filter-dot { opacity: 0.25; }

.kg-filter-empty {
  padding: 10px;
  font-size: 0.8rem;
  color: rgba(180,192,210,0.5);
  text-align: center;
  margin: 0;
}
.kg-filter-cta-link {
  display: block;
  padding: 8px 10px;
  font-size: 0.82rem;
  color: #2dd4bf;
  text-align: center;
  cursor: pointer;
}
.kg-filter-cta-link:hover { text-decoration: underline; }

/* Section greyed out when current view scope cannot use this filter. */
.kg-filter-section.disabled-scope .kg-filter-section-header { color: rgba(180,192,210,0.3); }
.kg-filter-section.disabled-scope .kg-filter-cta-link { color: rgba(180,192,210,0.55); }
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/css/style.css
git commit -m "style: KG multi-section filter dropdown w/ bolder unchecked state"
```

---

## Phase 4: Personal/Global toggle behaviour (P1 #7)

### Task 4.1: Wire up the toggle

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js` (replace existing `viewToggle` block, lines 121-148)

- [ ] **Step 1: Replace the toggle block with login-aware version**

Find the existing `// ---- View toggle (shown only when logged in) ----` block. Replace through end of that block with:

```javascript
  // ---- View toggle (always visible; Personal greys out when logged out) ----
  const viewToggle = document.getElementById('view-toggle');
  const STORAGE_KEY_VIEW = 'kg.view';

  function setViewBtns(view) {
    if (!viewToggle) return;
    viewToggle.querySelectorAll('.kg-view-btn').forEach(b => {
      const isActive = b.dataset.view === view;
      b.classList.toggle('active', isActive);
      b.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
  }

  function setPersonalEnabled(enabled) {
    const personalBtn = viewToggle?.querySelector('[data-view="my"]');
    if (!personalBtn) return;
    if (enabled) {
      personalBtn.removeAttribute('aria-disabled');
      personalBtn.removeAttribute('title');
    } else {
      personalBtn.setAttribute('aria-disabled', 'true');
      personalBtn.setAttribute('title', 'Sign in to switch to Personal');
    }
  }

  function openLoginModalFromKG() {
    // The header partial owns the login button; clicking it opens the modal.
    const btn = document.querySelector('.home-login-btn, [data-open-login], #header-login-btn');
    if (btn) { btn.click(); return; }
    // Fallback: directly mutate the modal class if the button can't be found.
    const modal = document.getElementById('login-modal');
    if (modal) modal.classList.add('open');
  }

  // Restore persisted view (only auto-restore "my" if we end up confirming login).
  const savedView = localStorage.getItem(STORAGE_KEY_VIEW);
  if (savedView === 'my' || savedView === 'global') {
    currentView = savedView === 'my' ? 'global' : savedView; // tentatively global; flip after login confirm
  }
  setViewBtns(currentView);

  // Check auth status via API.
  authToken = getStoredAuthToken();
  if (authToken) {
    fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + authToken } })
      .then(r => r.ok ? r.json() : Promise.reject('not logged in'))
      .then(() => {
        isLoggedIn = true;
        setPersonalEnabled(true);
        if (savedView === 'my') {
          currentView = 'my';
          setViewBtns('my');
          loadGraphData();
        }
      })
      .catch(() => { isLoggedIn = false; authToken = null; setPersonalEnabled(false); });
  } else {
    setPersonalEnabled(false);
  }

  if (viewToggle) {
    viewToggle.addEventListener('click', (e) => {
      const btn = e.target.closest('.kg-view-btn');
      if (!btn) return;
      const newView = btn.dataset.view;
      // Greyed Personal → open login modal.
      if (newView === 'my' && !isLoggedIn) {
        openLoginModalFromKG();
        return;
      }
      if (newView === currentView) return;
      currentView = newView;
      localStorage.setItem(STORAGE_KEY_VIEW, newView);
      setViewBtns(newView);
      // Clear any kasten selections when leaving Personal — they no longer make sense in Global.
      if (newView === 'global') {
        activeKastens.clear();
      }
      renderKastensSection();
      loadGraphData();
    });
  }
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat: KG view toggle is always visible; greyed Personal opens login modal"
```

---

## Phase 5: Search UX — 3px shift + count + clear + auto-frame (P2 #19, #20, #22)

CSS shift was already applied in Task 3.2. Now wire the JS.

### Task 5.1: Replace the search input handler

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js` (search block, lines 686–706)

- [ ] **Step 1: Replace the existing `if (searchInput)` block with**

```javascript
  // ---- Search ----
  const searchClear = document.getElementById('search-clear');
  const searchCount = document.getElementById('search-count');
  let _searchDebounce = null;

  function _applySearch(query) {
    highlightNodes.clear();
    selectedNode = null;
    let matchCount = 0;
    if (query.length > 0) {
      graphData.nodes.forEach(node => {
        const nodeTags = Array.isArray(node.tags) ? node.tags : [];
        const nodeSummary = extractBriefFromSummary(node.summary);
        const match = (node.name || '').toLowerCase().includes(query) ||
                      nodeTags.some(t => String(t).toLowerCase().includes(query)) ||
                      nodeSummary.toLowerCase().includes(query);
        if (match) { highlightNodes.add(node.id); matchCount++; }
      });
    }
    // Count badge.
    if (searchCount) {
      if (query.length === 0) {
        searchCount.classList.add('hidden');
        searchCount.textContent = '';
      } else {
        searchCount.classList.remove('hidden');
        searchCount.textContent = matchCount === 0 ? '0' : String(matchCount);
      }
    }
    // Clear button.
    if (searchClear) {
      searchClear.classList.toggle('hidden', query.length === 0);
    }
    _refreshAllNodeVisuals();
    // Auto-frame matched nodes.
    if (matchCount === 1) {
      const only = graphData.nodes.find(n => highlightNodes.has(n.id));
      if (only) {
        const cam = graph.camera();
        const nx = only.x || 0, ny = only.y || 0, nz = only.z || 0;
        const dx = cam.position.x - nx, dy = cam.position.y - ny, dz = cam.position.z - nz;
        const len = Math.sqrt(dx*dx + dy*dy + dz*dz) || 1;
        const targetDist = 100;
        graph.cameraPosition({
          x: nx + (dx/len)*targetDist,
          y: ny + (dy/len)*targetDist,
          z: nz + (dz/len)*targetDist
        }, only, 800);
      }
    } else if (matchCount > 1) {
      graph.zoomToFit(800, 80, n => highlightNodes.has(n.id));
    }
  }

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      const query = e.target.value.toLowerCase().trim();
      if (_searchDebounce) clearTimeout(_searchDebounce);
      _searchDebounce = setTimeout(() => _applySearch(query), 250);
    });
  }
  if (searchClear) {
    searchClear.addEventListener('click', () => {
      if (!searchInput) return;
      searchInput.value = '';
      _applySearch('');
      searchInput.focus();
    });
  }
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat: KG search count + clear + auto-frame on match"
```

---

## Phase 6: Reset view button (P2 #18)

### Task 6.1: Wire the reset button

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js` (append after existing handlers, near the end)

- [ ] **Step 1: Append handler**

Inside the IIFE, after the search wiring, add:

```javascript
  // ---- Reset view ----
  const resetViewBtn = document.getElementById('reset-view-btn');
  if (resetViewBtn) {
    resetViewBtn.addEventListener('click', () => {
      if (!graph) return;
      // Clear highlights so all nodes are visible during the fit.
      if (searchInput) searchInput.value = '';
      _applySearch('');
      selectedNode = null;
      highlightNodes.clear();
      _refreshAllNodeVisuals();
      closePanel();
      graph.zoomToFit(800, 60);
    });
  }
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat: KG reset view button"
```

---

## Phase 7: Multi-filter dropdown — Source (dynamic) + Kastens

This is the largest single feature in the plan. Split into two tasks: Source section first (no auth required, regression-safe), then Kastens section.

### Task 7.1: Source section — render from data, AND/OR semantics

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js` (multiple blocks: COLORS, normalizeGroup, filter init/handler, applyFilters)

- [ ] **Step 1: Add newsletter colour and rename the COLORS source-of-truth**

Replace the `COLORS` and `COLORS_INT` blocks at the top of the IIFE with:

```javascript
  // ---- Node colours by source. Adding a new source = add one row here. ----
  const COLORS = {
    youtube:    '#E05565',
    reddit:     '#E09040',
    github:     '#56C8D8',
    substack:   '#60A5FA',
    newsletter: '#60A5FA',  // matches .zettels-source-badge.newsletter HSL(205,40,68)
    medium:     '#4ADE80',
    web:        '#94A3B8'
  };
  const COLORS_INT = {
    youtube:    0xE05565,
    reddit:     0xE09040,
    github:     0x56C8D8,
    substack:   0x60A5FA,
    newsletter: 0x60A5FA,
    medium:     0x4ADE80,
    web:        0x94A3B8
  };
  const SOURCE_LABEL = {
    youtube: 'YouTube',
    reddit: 'Reddit',
    github: 'GitHub',
    substack: 'Substack',
    newsletter: 'Newsletter',
    medium: 'Medium',
    web: 'Web'
  };
```

Replace `normalizeGroup`:

```javascript
  function normalizeGroup(group) {
    var normalized = (group || '').toString().trim().toLowerCase();
    if (normalized === 'generic') return 'web';
    return normalized || 'web';
  }
```

(no longer collapsing newsletter to anything; it's a first-class source.)

- [ ] **Step 2: Replace `activeFilters` initial state with a dynamic build**

Replace the line `let activeFilters = new Set([...]);` with:

```javascript
  let activeSources = new Set();      // populated after first /api/graph response
  let activeKastens = new Set();      // populated when user picks any
  let kastenMembership = new Map();   // sandboxId -> Set<nodeId>; lazy-loaded
  let kastenList = [];                // [{id, name, member_count}, ...]
  let knownSources = new Set();       // union of COLORS keys + groups present in data
```

- [ ] **Step 3: Render the source section dynamically**

Replace the existing `if (filterDropdown) { filterDropdown.querySelectorAll('input[type="checkbox"]')…` block with:

```javascript
  function renderSourceSection() {
    const body = document.getElementById('filter-source-body');
    if (!body) return;
    body.innerHTML = '';
    [...knownSources].sort().forEach(src => {
      const id = 'flt-src-' + src;
      const lbl = document.createElement('label');
      lbl.className = 'kg-filter-item';
      const checked = activeSources.has(src);
      if (!checked) lbl.classList.add('unchecked');
      lbl.innerHTML =
        '<input type="checkbox" id="' + id + '" value="' + src + '"' + (checked ? ' checked' : '') + '>' +
        '<span class="kg-filter-dot" style="background:' + (COLORS[src] || '#888') + '"></span>' +
        '<span>' + (SOURCE_LABEL[src] || src) + '</span>';
      lbl.addEventListener('click', (e) => {
        // Click anywhere on the label toggles the checkbox; we manage state ourselves.
        e.preventDefault();
        if (activeSources.has(src)) activeSources.delete(src); else activeSources.add(src);
        lbl.classList.toggle('unchecked', !activeSources.has(src));
        const cb = lbl.querySelector('input');
        if (cb) cb.checked = activeSources.has(src);
        applyFilters();
      });
      body.appendChild(lbl);
    });
  }
```

- [ ] **Step 4: Wire collapsible section headers**

Append:

```javascript
  document.querySelectorAll('.kg-filter-section-header').forEach(h => {
    h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed'));
  });
```

- [ ] **Step 5: Replace `applyFilters` with two-axis filtering**

Replace the existing `applyFilters` function:

```javascript
  function applyFilters() {
    // Build the set of node IDs allowed by the Kastens axis.
    let kastenAllowedIds = null; // null = no kasten filter active = allow all
    if (activeKastens.size > 0) {
      kastenAllowedIds = new Set();
      activeKastens.forEach(kid => {
        const memb = kastenMembership.get(kid);
        if (memb) memb.forEach(nid => kastenAllowedIds.add(nid));
      });
    }
    const filteredNodes = fullData.nodes.filter(n => {
      const src = normalizeGroup(n.group);
      if (!activeSources.has(src)) return false;
      if (kastenAllowedIds && !kastenAllowedIds.has(n.id)) return false;
      return true;
    });
    const nodeIds = new Set(filteredNodes.map(n => n.id));
    const filteredLinks = fullData.links.filter(l => {
      const src = typeof l.source === 'object' ? l.source.id : l.source;
      const tgt = typeof l.target === 'object' ? l.target.id : l.target;
      return nodeIds.has(src) && nodeIds.has(tgt);
    });
    graphData = { nodes: filteredNodes, links: filteredLinks };
    nodeDegrees = computeDegrees(graphData);
    if (graph) graph.graphData(graphData);
    updateStats();
    closePanel();
    selectedNode = null;
    highlightNodes.clear();

    // Empty-state overlay (P1 #14).
    const emptyOverlay = document.getElementById('overlay-empty');
    if (emptyOverlay) emptyOverlay.classList.toggle('hidden', filteredNodes.length > 0);

    if (filteredNodes.length > 0) setTimeout(() => graph && graph.zoomToFit(800, 60), 800);
  }
```

- [ ] **Step 6: Update `loadGraphData` to seed `knownSources` and `activeSources` from data**

Inside the `.then(data => { ... })` block in `loadGraphData`, after the `fullData = data;` and group-normalisation, before `if (graph) { applyFilters(); } else { initGraph(); updateStats(); }`, insert:

```javascript
        // Seed source filter from union of known + observed groups.
        const observed = new Set((fullData.nodes || []).map(n => normalizeGroup(n.group)));
        knownSources = new Set([...Object.keys(COLORS), ...observed]);
        // First load: enable all sources by default.
        if (activeSources.size === 0) {
          knownSources.forEach(s => activeSources.add(s));
        }
        renderSourceSection();
```

- [ ] **Step 7: Empty-overlay reset button wiring**

Append at the end of the IIFE (with other handlers):

```javascript
  const overlayEmptyReset = document.getElementById('overlay-empty-reset');
  if (overlayEmptyReset) {
    overlayEmptyReset.addEventListener('click', () => {
      activeSources = new Set([...knownSources]);
      activeKastens.clear();
      renderSourceSection();
      renderKastensSection(); // safe — defined in Task 7.2; defaults to empty if not yet loaded
      applyFilters();
    });
  }
```

- [ ] **Step 8: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat: KG source filter rendered from data; newsletter is first-class"
```

### Task 7.2: Kastens section — list + lazy membership fetch

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js` (add Kastens render + fetch logic)

- [ ] **Step 1: Add render + fetch helpers**

Append to the IIFE:

```javascript
  // ---- Kastens filter section ----
  function renderKastensSection() {
    const body = document.getElementById('filter-kastens-body');
    if (!body) return;
    body.innerHTML = '';
    const sectionEl = body.closest('.kg-filter-section');
    // Greyed when view is Global (Kastens are personal scope).
    if (currentView === 'global') {
      if (sectionEl) sectionEl.classList.add('disabled-scope');
      const link = document.createElement('a');
      link.className = 'kg-filter-cta-link';
      link.textContent = 'Switch to Personal to filter by Kasten';
      link.href = '#';
      link.addEventListener('click', (e) => {
        e.preventDefault();
        if (!isLoggedIn) { openLoginModalFromKG(); return; }
        // Programmatic toggle to Personal.
        currentView = 'my';
        localStorage.setItem(STORAGE_KEY_VIEW, 'my');
        setViewBtns('my');
        loadGraphData();
        // Re-render so the section unlocks.
        setTimeout(renderKastensSection, 0);
      });
      body.appendChild(link);
      return;
    }
    if (sectionEl) sectionEl.classList.remove('disabled-scope');
    if (!isLoggedIn) {
      const link = document.createElement('a');
      link.className = 'kg-filter-cta-link';
      link.textContent = 'Sign in to filter by Kasten';
      link.href = '#';
      link.addEventListener('click', (e) => { e.preventDefault(); openLoginModalFromKG(); });
      body.appendChild(link);
      return;
    }
    if (kastenList.length === 0) {
      const link = document.createElement('a');
      link.className = 'kg-filter-cta-link';
      link.textContent = 'No Kastens yet — Create one →';
      link.href = '/home/kastens';
      body.appendChild(link);
      return;
    }
    kastenList.forEach(k => {
      const id = 'flt-kst-' + k.id;
      const lbl = document.createElement('label');
      lbl.className = 'kg-filter-item';
      const checked = activeKastens.has(k.id);
      if (!checked) lbl.classList.add('unchecked');
      lbl.innerHTML =
        '<input type="checkbox" id="' + id + '" value="' + k.id + '"' + (checked ? ' checked' : '') + '>' +
        '<span class="kg-filter-dot" style="background:' + (k.color || '#14b8a6') + '"></span>' +
        '<span>' + escapeHtml(k.name) + '</span>';
      lbl.addEventListener('click', async (e) => {
        e.preventDefault();
        if (activeKastens.has(k.id)) {
          activeKastens.delete(k.id);
        } else {
          activeKastens.add(k.id);
          // Lazy-load membership on first selection.
          if (!kastenMembership.has(k.id)) {
            try {
              const resp = await fetch('/api/rag/sandboxes/' + encodeURIComponent(k.id) + '/members?limit=1000', { headers: authHeaders() });
              if (resp.ok) {
                const data = await resp.json();
                const ids = new Set((data.members || []).map(m => m.node_id));
                kastenMembership.set(k.id, ids);
              } else {
                kastenMembership.set(k.id, new Set());
              }
            } catch (_e) {
              kastenMembership.set(k.id, new Set());
            }
          }
        }
        lbl.classList.toggle('unchecked', !activeKastens.has(k.id));
        const cb = lbl.querySelector('input');
        if (cb) cb.checked = activeKastens.has(k.id);
        applyFilters();
      });
      body.appendChild(lbl);
    });
  }

  function loadKastens() {
    if (!isLoggedIn) { renderKastensSection(); return; }
    fetch('/api/rag/sandboxes', { headers: authHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject('not ok'))
      .then(data => {
        kastenList = (data.sandboxes || []).map(s => ({ id: s.id, name: s.name, color: s.color, member_count: s.member_count }));
        renderKastensSection();
      })
      .catch(() => {
        kastenList = [];
        renderKastensSection();
      });
  }
```

- [ ] **Step 2: Trigger `loadKastens()` after auth confirmation**

In the existing auth check (Task 4.1), inside the `.then(() => { ... })` after `setPersonalEnabled(true);`, add:

```javascript
        loadKastens();
```

Also call `renderKastensSection();` once at startup so the section shows the "Sign in to filter" CTA for logged-out users.

Add at the bottom of the IIFE (initial render):

```javascript
  renderKastensSection();
```

- [ ] **Step 3: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat: KG Kastens filter section w/ lazy membership fetch + login CTA"
```

---

## Phase 8: Side panel — meta row + width + scroll + connection-click refresh

### Task 8.1: Update CSS for the new panel structure

**Files:**
- Modify: `website/features/knowledge_graph/css/style.css` (panel block)

- [ ] **Step 1: Replace existing `.kg-panel` rules**

Find the existing `.kg-panel` block. Replace through the bottom of the side-panel-related rules with:

```css
/* ============================================
   Side panel
   ============================================ */
.kg-panel {
  position: fixed;
  top: 80px;
  right: 16px;
  width: min(420px, 38vw);
  max-height: calc(100vh - 100px);
  background: rgba(12, 16, 28, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
  z-index: 150;
  transform: translateX(20px);
  opacity: 0;
  transition: opacity 0.3s ease, transform 0.3s ease;
  display: flex;
  flex-direction: column;
}
.kg-panel.visible { opacity: 1; transform: translateX(0); }
.kg-panel-content {
  padding: 18px 20px 22px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1 1 auto;
  min-height: 0;
}

/* Meta row: date pill + source badge + view-original + add-to-kasten + close */
.kg-panel-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  margin: 0;
}

/* Date pill (matches .zettels-summary-date / .home-card-date HSL token style) */
.kg-panel-date {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  background: rgba(8,12,24,0.5);
  color: rgba(180, 192, 210, 0.7);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.kg-panel-date.hidden { display: none; }

/* Source badge — pixel-match .zettels-source-badge.<group> */
.kg-panel-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  border: 1px solid;
  border-radius: 999px;
  background: transparent;
  white-space: nowrap;
}
.kg-panel-badge.youtube    { color: hsl(355, 45%, 68%); border-color: hsla(355, 45%, 68%, 0.25); background: hsla(355, 45%, 68%, 0.1); }
.kg-panel-badge.github     { color: hsl(192, 35%, 62%); border-color: hsla(192, 35%, 62%, 0.25); background: hsla(192, 35%, 62%, 0.1); }
.kg-panel-badge.reddit     { color: hsl(28, 45%, 68%);  border-color: hsla(28, 45%, 68%, 0.25);  background: hsla(28, 45%, 68%, 0.1); }
.kg-panel-badge.newsletter { color: hsl(205, 40%, 68%); border-color: hsla(205, 40%, 68%, 0.25); background: hsla(205, 40%, 68%, 0.1); }
.kg-panel-badge.substack   { color: hsl(205, 40%, 68%); border-color: hsla(205, 40%, 68%, 0.25); background: hsla(205, 40%, 68%, 0.1); }
.kg-panel-badge.medium     { color: hsl(142, 40%, 62%); border-color: hsla(142, 40%, 62%, 0.25); background: hsla(142, 40%, 62%, 0.1); }
.kg-panel-badge.web        { color: hsl(220, 14%, 62%); border-color: hsla(220, 14%, 62%, 0.25); background: hsla(220, 14%, 62%, 0.1); }

/* Circular icon buttons (view original, add to kasten) */
.kg-panel-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px; height: 32px;
  background: rgba(8,12,24,0.6);
  border: 1px solid rgba(20, 184, 166, 0.4);
  border-radius: 50%;
  color: rgba(180, 192, 210, 0.85);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s, box-shadow 0.15s;
  flex-shrink: 0;
}
.kg-panel-icon-btn:hover { color: #2dd4bf; border-color: rgba(20,184,166,0.7); background: rgba(20,184,166,0.08); box-shadow: 0 0 0 4px rgba(20,184,166,0.08); }
.kg-panel-icon-btn[aria-disabled="true"] { opacity: 0.4; cursor: not-allowed; }
.kg-panel-icon-mask {
  width: 16px; height: 16px;
  background: currentColor;
  -webkit-mask: var(--mask-url) center/contain no-repeat;
          mask: var(--mask-url) center/contain no-repeat;
  display: inline-block;
}

/* Close button anchored right via auto-margin on the meta row */
.kg-panel-close {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px; height: 32px;
  background: transparent;
  border: 0;
  border-radius: 8px;
  color: rgba(180, 192, 210, 0.6);
  cursor: pointer;
}
.kg-panel-close:hover { background: rgba(255,255,255,0.06); color: #fff; }

.kg-panel-title { margin: 0; font-size: 1.18rem; font-weight: 600; color: #fff; line-height: 1.35; text-wrap: balance; }
.kg-panel-summary { margin: 0; color: rgba(220, 228, 240, 0.75); line-height: 1.65; font-size: 0.87rem; }
.kg-panel-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.kg-tag {
  display: inline-block;
  padding: 3px 9px;
  background: rgba(20,184,166,0.08);
  border: 1px solid rgba(20,184,166,0.2);
  border-radius: 999px;
  color: rgba(180, 230, 220, 0.85);
  font-size: 0.7rem;
}
.kg-panel-section { display: flex; flex-direction: column; gap: 8px; }
.kg-panel-section-title {
  margin: 0;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(180,192,210,0.55);
}
.kg-panel-connections { display: flex; flex-direction: column; gap: 4px; }
.kg-connection {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s;
}
.kg-connection:hover { background: rgba(255,255,255,0.05); }
.kg-connection-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.kg-connection-name { flex: 1 1 auto; color: rgba(220,228,240,0.85); font-size: 0.84rem; }
.kg-connection-relation { color: rgba(180,192,210,0.5); font-size: 0.72rem; }
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/css/style.css
git commit -m "style: KG side panel new structure (meta row, scroll, badge HSL match)"
```

### Task 8.2: Update `openPanel()` to use new structure + handle empty date

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js` (`openPanel` function, ~line 615)

- [ ] **Step 1: Replace `openPanel`**

Replace the `openPanel` function with:

```javascript
  let _currentPanelNodeId = null;

  function openPanel(node) {
    const badge = document.getElementById('panel-badge');
    const title = document.getElementById('panel-title');
    const date = document.getElementById('panel-date');
    const summary = document.getElementById('panel-summary');
    const tags = document.getElementById('panel-tags');
    const connections = document.getElementById('panel-connections');
    const link = document.getElementById('panel-link');
    const addBtn = document.getElementById('panel-add-kasten');

    const nodeGroup = normalizeGroup(node.group);
    badge.textContent = (SOURCE_LABEL[nodeGroup] || nodeGroup).toUpperCase();
    badge.className = 'kg-panel-badge ' + nodeGroup;
    title.textContent = node.name || '';

    // Empty-date hide (P0 #3).
    const formatted = formatDate(node.date);
    if (formatted && formatted !== 'Invalid Date' && formatted !== '') {
      date.textContent = formatted;
      date.classList.remove('hidden');
    } else {
      date.textContent = '';
      date.classList.add('hidden');
    }

    summary.textContent = extractBriefFromSummary(node.summary);

    const safeLink = toSafeHttpUrl(node.url);
    if (safeLink) {
      link.href = safeLink;
      link.removeAttribute('aria-disabled');
      link.tabIndex = 0;
      link.rel = 'noopener noreferrer';
      link.target = '_blank';
    } else {
      link.href = '#';
      link.setAttribute('aria-disabled', 'true');
      link.tabIndex = -1;
      link.rel = '';
      link.target = '';
    }

    // Add-to-Kasten button — open modal (or login if logged out).
    if (addBtn) {
      addBtn.onclick = () => {
        if (!isLoggedIn) { openLoginModalFromKG(); return; }
        if (window.kgKastenModal) {
          window.kgKastenModal.open(node, kastenList, authHeaders, () => loadKastens());
        }
      };
    }

    tags.innerHTML = (Array.isArray(node.tags) ? node.tags : []).map(
      t => '<span class="kg-tag">' + escapeHtml(t) + '</span>'
    ).join('');

    const nodeLinks = graphData.links.filter(
      l => l.source === node || l.target === node ||
           l.source?.id === node.id || l.target?.id === node.id
    );
    const connectedNodes = nodeLinks.map(l => {
      const other = (l.source === node || l.source?.id === node.id) ? l.target : l.source;
      return { node: other, relation: l.relation };
    });

    connections.innerHTML = connectedNodes.map(c => `
      <div class="kg-connection" data-id="${escapeHtml(c.node.id || c.node)}">
        <span class="kg-connection-dot" style="background: ${COLORS[c.node.group] || '#888'}"></span>
        <span class="kg-connection-name">${escapeHtml(c.node.name || c.node)}</span>
        <span class="kg-connection-relation">${escapeHtml(c.relation || '')}</span>
      </div>
    `).join('');
    connections.querySelectorAll('.kg-connection').forEach(el => {
      el.addEventListener('click', () => {
        const targetId = el.dataset.id;
        const targetNode = graphData.nodes.find(n => n.id === targetId);
        if (targetNode && targetNode.id !== _currentPanelNodeId) handleNodeClick(targetNode);
      });
    });

    _currentPanelNodeId = node.id;
    sidePanel.dataset.nodeId = node.id;

    if (panelHideTimer) { clearTimeout(panelHideTimer); panelHideTimer = null; }
    sidePanel.classList.remove('hidden');
    requestAnimationFrame(() => sidePanel.classList.add('visible'));
  }
```

- [ ] **Step 2: Update `handleNodeClick` for instant connection-click panel refresh (P2 #25)**

Replace the existing `handleNodeClick` with:

```javascript
  function handleNodeClick(node) {
    const prevSelected = selectedNode;
    selectedNode = node;
    graph.controls().autoRotate = false;
    if (prevSelected && prevSelected !== node) _updateNodeVisual(prevSelected);
    _updateNodeVisual(node);

    if (_panelOpenTimer) { clearTimeout(_panelOpenTimer); _panelOpenTimer = null; }

    // If panel is already open, swap content INSTANTLY so connection-clicks feel snappy.
    const panelAlreadyOpen = sidePanel.classList.contains('visible');
    if (panelAlreadyOpen) openPanel(node);

    // Fly camera.
    const cam = graph.camera();
    const nx = node.x || 0, ny = node.y || 0, nz = node.z || 0;
    const dx = cam.position.x - nx;
    const dy = cam.position.y - ny;
    const dz = cam.position.z - nz;
    const len = Math.sqrt(dx*dx + dy*dy + dz*dz) || 1;
    const targetDist = 90;
    graph.cameraPosition({
      x: nx + (dx/len)*targetDist,
      y: ny + (dy/len)*targetDist,
      z: nz + (dz/len)*targetDist
    }, node, 1000);

    // Open panel after camera centres (only if not already open).
    if (!panelAlreadyOpen) {
      _panelOpenTimer = setTimeout(() => { openPanel(node); _panelOpenTimer = null; }, 700);
    }
  }
```

- [ ] **Step 3: Reset `_currentPanelNodeId` on close**

Inside `closePanel()`, just before the `setTimeout`:

```javascript
    _currentPanelNodeId = null;
    sidePanel.dataset.nodeId = '';
```

- [ ] **Step 4: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat: KG side panel uses new meta row; instant refresh on connection-click; empty-date hide"
```

---

## Phase 9: Add-to-Kasten modal (P1 #8)

### Task 9.1: Modal CSS

**Files:**
- Modify: `website/features/knowledge_graph/css/style.css`

- [ ] **Step 1: Append modal styles**

Append to `style.css`:

```css
/* ============================================
   Add-to-Kasten modal
   ============================================ */
.kg-kasten-modal {
  position: fixed;
  inset: 0;
  z-index: 400;
  display: flex;
  align-items: center;
  justify-content: center;
}
.kg-kasten-modal.hidden { display: none; }
.kg-kasten-modal-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
}
.kg-kasten-modal-card {
  position: relative;
  width: min(420px, 92vw);
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  background: rgba(12, 16, 28, 0.98);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 16px;
  box-shadow: 0 30px 70px rgba(0,0,0,0.6);
  padding: 22px 24px 18px;
  gap: 14px;
}
.kg-kasten-modal-header { display: flex; align-items: center; justify-content: space-between; }
.kg-kasten-modal-header h2 { margin: 0; font-size: 1.05rem; font-weight: 600; color: #fff; }
.kg-kasten-modal-close {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px;
  background: transparent; border: 0; border-radius: 8px;
  color: rgba(180,192,210,0.6); cursor: pointer;
}
.kg-kasten-modal-close:hover { background: rgba(255,255,255,0.06); color: #fff; }
.kg-kasten-modal-subtitle {
  margin: 0;
  font-size: 0.82rem;
  color: rgba(180,192,210,0.6);
  font-style: italic;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kg-kasten-modal-list {
  list-style: none;
  margin: 0; padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 340px;
  overflow-y: auto;
  background: rgba(8,12,24,0.5);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 10px;
}
.kg-kasten-modal-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.88rem;
  color: rgba(220,228,240,0.85);
}
.kg-kasten-modal-item:hover { background: rgba(255,255,255,0.04); }
.kg-kasten-modal-item.selected { background: rgba(20,184,166,0.1); color: #fff; }
.kg-kasten-modal-item-create {
  font-weight: 600;
  color: #2dd4bf;
}
.kg-kasten-modal-create-form {
  display: flex;
  gap: 6px;
  padding: 8px 10px;
}
.kg-kasten-modal-create-input {
  flex: 1;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  padding: 6px 8px;
  color: #fff;
  font-size: 0.85rem;
  outline: none;
}
.kg-kasten-modal-create-input:focus { border-color: rgba(20,184,166,0.55); }
.kg-kasten-modal-create-go {
  background: rgba(20,184,166,0.15);
  border: 1px solid rgba(20,184,166,0.4);
  border-radius: 6px;
  color: #2dd4bf;
  padding: 0 10px;
  cursor: pointer;
  font-size: 0.8rem;
}
.kg-kasten-modal-error {
  color: #f87171;
  font-size: 0.8rem;
  padding: 6px 10px;
  background: rgba(248,113,113,0.08);
  border-radius: 6px;
}
.kg-kasten-modal-footer { display: flex; justify-content: flex-end; gap: 8px; }
.kg-kasten-modal-cancel,
.kg-kasten-modal-add {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.84rem;
  cursor: pointer;
  border: 1px solid;
}
.kg-kasten-modal-cancel { background: transparent; border-color: rgba(255,255,255,0.1); color: rgba(220,228,240,0.7); }
.kg-kasten-modal-cancel:hover { background: rgba(255,255,255,0.04); color: #fff; }
.kg-kasten-modal-add { background: rgba(20,184,166,0.18); border-color: rgba(20,184,166,0.5); color: #2dd4bf; }
.kg-kasten-modal-add:hover:not(:disabled) { background: rgba(20,184,166,0.28); }
.kg-kasten-modal-add:disabled { opacity: 0.4; cursor: not-allowed; }

/* Toast (success after add) */
.kg-toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%) translateY(20px);
  padding: 10px 20px;
  background: rgba(12,16,28,0.96);
  border: 1px solid rgba(20,184,166,0.4);
  border-radius: 10px;
  color: #2dd4bf;
  font-size: 0.85rem;
  z-index: 500;
  opacity: 0;
  transition: opacity 0.25s, transform 0.25s;
  pointer-events: none;
}
.kg-toast.visible { opacity: 1; transform: translateX(-50%) translateY(0); }
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/css/style.css
git commit -m "style: KG add-to-Kasten modal + success toast"
```

### Task 9.2: Modal JS — self-contained module

**Files:**
- Create: `website/features/knowledge_graph/js/kasten_modal.js`

- [ ] **Step 1: Create the modal module**

Create `website/features/knowledge_graph/js/kasten_modal.js`:

```javascript
/* eslint-disable */
// Self-contained Add-to-Kasten modal. Exposed as window.kgKastenModal.
(function () {
  'use strict';

  const modal       = document.getElementById('kasten-modal');
  if (!modal) return; // KG page not present.
  const backdrop    = document.getElementById('kasten-modal-backdrop');
  const closeBtn    = document.getElementById('kasten-modal-close');
  const subtitle    = document.getElementById('kasten-modal-note-name');
  const listEl      = document.getElementById('kasten-modal-list');
  const errorEl     = document.getElementById('kasten-modal-error');
  const cancelBtn   = document.getElementById('kasten-modal-cancel');
  const addBtn      = document.getElementById('kasten-modal-add');

  let state = { node: null, kastens: [], selectedId: null, headersFn: null, refresh: null };

  function escapeHtml(s) {
    const el = document.createElement('span'); el.textContent = String(s == null ? '' : s); return el.innerHTML;
  }

  function showError(msg) {
    if (!errorEl) return;
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
  }
  function clearError() { if (errorEl) { errorEl.textContent = ''; errorEl.classList.add('hidden'); } }

  function showToast(text) {
    let t = document.querySelector('.kg-toast');
    if (!t) { t = document.createElement('div'); t.className = 'kg-toast'; document.body.appendChild(t); }
    t.textContent = text;
    requestAnimationFrame(() => t.classList.add('visible'));
    setTimeout(() => t.classList.remove('visible'), 2200);
    setTimeout(() => t.remove(), 2700);
  }

  function render() {
    if (!listEl) return;
    listEl.innerHTML = '';
    // Create-new row.
    const createRow = document.createElement('li');
    createRow.className = 'kg-kasten-modal-item kg-kasten-modal-item-create';
    createRow.textContent = '+ Create new Kasten';
    createRow.addEventListener('click', () => renderCreateForm(createRow));
    listEl.appendChild(createRow);
    // Existing kastens.
    state.kastens.forEach(k => {
      const li = document.createElement('li');
      li.className = 'kg-kasten-modal-item' + (state.selectedId === k.id ? ' selected' : '');
      li.dataset.id = k.id;
      li.innerHTML =
        '<span class="kg-filter-dot" style="background:' + escapeHtml(k.color || '#14b8a6') + '"></span>' +
        '<span>' + escapeHtml(k.name) + '</span>';
      li.addEventListener('click', () => {
        state.selectedId = k.id;
        render();
        if (addBtn) addBtn.disabled = false;
      });
      listEl.appendChild(li);
    });
  }

  function renderCreateForm(replaceRow) {
    const form = document.createElement('div');
    form.className = 'kg-kasten-modal-create-form';
    form.innerHTML =
      '<input type="text" class="kg-kasten-modal-create-input" placeholder="Kasten name" maxlength="80" />' +
      '<button type="button" class="kg-kasten-modal-create-go">Create</button>';
    replaceRow.replaceWith(form);
    const input = form.querySelector('input');
    const go = form.querySelector('button');
    input.focus();
    const submit = async () => {
      const name = (input.value || '').trim();
      if (!name) { input.focus(); return; }
      go.disabled = true;
      clearError();
      try {
        const resp = await fetch('/api/rag/sandboxes', {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, state.headersFn()),
          body: JSON.stringify({ name })
        });
        if (!resp.ok) throw new Error('Could not create Kasten (' + resp.status + ')');
        const data = await resp.json();
        const created = data.sandbox || data;
        state.kastens.unshift({ id: created.id, name: created.name, color: created.color });
        state.selectedId = created.id;
        render();
        if (addBtn) addBtn.disabled = false;
        if (state.refresh) state.refresh();
      } catch (e) {
        showError(e.message || 'Could not create Kasten');
        go.disabled = false;
      }
    };
    go.addEventListener('click', submit);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  }

  async function performAdd() {
    if (!state.node || !state.selectedId) return;
    addBtn.disabled = true;
    clearError();
    try {
      const resp = await fetch('/api/rag/sandboxes/' + encodeURIComponent(state.selectedId) + '/members', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, state.headersFn()),
        body: JSON.stringify({ node_ids: [state.node.id] })
      });
      if (!resp.ok) throw new Error('Could not add to Kasten (' + resp.status + ')');
      const target = state.kastens.find(k => k.id === state.selectedId);
      showToast('Added to ' + (target?.name || 'Kasten'));
      close();
    } catch (e) {
      showError(e.message || 'Could not add to Kasten');
      addBtn.disabled = false;
    }
  }

  function open(node, kastens, headersFn, refresh) {
    state.node = node;
    state.kastens = (kastens || []).slice();
    state.selectedId = null;
    state.headersFn = headersFn || (() => ({}));
    state.refresh = refresh || null;
    if (subtitle) subtitle.textContent = 'Note: "' + (node.name || node.id) + '"';
    if (addBtn) addBtn.disabled = true;
    clearError();
    render();
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function close() {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
  }

  if (closeBtn)  closeBtn.addEventListener('click', close);
  if (cancelBtn) cancelBtn.addEventListener('click', close);
  if (backdrop)  backdrop.addEventListener('click', close);
  if (addBtn)    addBtn.addEventListener('click', performAdd);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) close();
  });

  window.kgKastenModal = { open, close };
})();
```

- [ ] **Step 2: Smoke-test in production after deploy**

Open the KG page logged in. Click any node → click the Kasten icon button in the panel → modal opens with your kastens. Select one → Add → toast appears, modal closes. Refresh KG, expand the Kastens filter section → the same kasten now contains the added node.

- [ ] **Step 3: Commit**

```bash
git add website/features/knowledge_graph/js/kasten_modal.js
git commit -m "feat: KG add-to-Kasten modal w/ create-new flow"
```

---

## Phase 10: 3D fixes — spotlight ring, scale reset, smart truncation, autorotate off

### Task 10.1: Smart label truncation (P1 #12)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js` (`getShortLabel` and `_truncate`)

- [ ] **Step 1: Replace `_truncate` with char-based version**

Replace `_truncate` with:

```javascript
  function _smartTruncate(str, maxChars) {
    const s = (str || '').trim();
    if (s.length <= maxChars) return s;
    // Strip leading filler.
    const words = s.split(/\s+/);
    while (words.length > 1 && LEAD_FILLER.has(words[0].toLowerCase())) words.shift();
    // Build word-by-word until we'd exceed maxChars.
    let out = '';
    for (const w of words) {
      if ((out + ' ' + w).trim().length > maxChars) break;
      out = (out + ' ' + w).trim();
    }
    if (!out) out = words[0].slice(0, Math.max(8, maxChars - 1));
    // Drop trailing filler.
    const parts = out.split(' ');
    while (parts.length > 1 && TAIL_FILLER.has(parts[parts.length - 1].toLowerCase())) parts.pop();
    return parts.join(' ') + (parts.join(' ').length < s.length ? '…' : '');
  }
```

- [ ] **Step 2: Update `getShortLabel` to use the char-based truncate**

Replace `getShortLabel` with:

```javascript
  function getShortLabel(node) {
    const name = node.name || '';
    const sepIdx = name.indexOf(SEP);
    if (node.group === 'github') {
      return sepIdx > -1 ? name.slice(0, sepIdx) : _smartTruncate(name, 28);
    }
    if ((node.group === 'reddit' || node.group === 'substack' || node.group === 'medium' || node.group === 'newsletter') && sepIdx > -1) {
      return _smartTruncate(name.slice(sepIdx + SEP.length), 28);
    }
    const topicPart = sepIdx > -1 ? name.slice(0, sepIdx) : name;
    return _smartTruncate(topicPart, 28);
  }
```

- [ ] **Step 3: Hover/select label = full title, wrap at first space past 32 chars**

In `_updateNodeVisual` and the `nodeThreeObject` factory, replace `const label = isActive ? node.name : getShortLabel(node);` with:

```javascript
        const label = isActive ? _wrapTitle(node.name || '', 32) : getShortLabel(node);
```

Add helper above `getShortLabel`:

```javascript
  function _wrapTitle(name, softMax) {
    if (name.length <= softMax) return name;
    const breakAt = name.indexOf(' ', softMax);
    if (breakAt === -1) return name;
    return name.slice(0, breakAt) + '\n' + name.slice(breakAt + 1);
  }
```

- [ ] **Step 4: Bump idle font weight to 600**

Inside `_updateNodeVisual` and `nodeThreeObject` where `sprite.fontWeight = '500'`, change to `'600'`.

- [ ] **Step 5: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat: KG smart label truncation (char-based, never mid-word) + 2-line hover labels"
```

### Task 10.2: Spotlight ring → billboarded mesh + scale reset (P0 #5)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js`

- [ ] **Step 1: Replace the ring-sprite block in `nodeThreeObject`**

Find the `if (isSpotlight) { ... ring sprite ... }` block. Replace with:

```javascript
        if (isSpotlight) {
          const ringMat = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: 0.5,
            depthWrite: false,
            side: THREE.DoubleSide
          });
          const ring = new THREE.Mesh(new THREE.RingGeometry(radius * 1.4, radius * 1.7, 48), ringMat);
          ring.__isRing = true;
          ring.__nodeRadius = radius;
          group.add(ring);
        }
```

- [ ] **Step 2: Per-frame `lookAt(camera)` for rings**

Inside the existing `clampLabelScales()` requestAnimationFrame loop (which already iterates all nodes), add inside the per-child loop:

```javascript
          if (child.__isRing) {
            child.lookAt(cam.position);
          }
```

- [ ] **Step 3: Scale-reset every frame for non-active nodes (defensive)**

Add a tracker and reset logic right after `let nodeDegrees = {};`:

```javascript
  const _activeNodeIds = new Set();
```

Modify `handleNodeClick` (right at the start) to maintain the set:

```javascript
    _activeNodeIds.clear();
    if (node) _activeNodeIds.add(node.id);
```

Modify the hover handler in `initGraph` (`.onNodeHover(node => { ... })`) similarly:

```javascript
      .onNodeHover(node => {
        const prevHover = hoverNode;
        hoverNode = node || null;
        container.style.cursor = node ? 'pointer' : 'default';
        if (prevHover && prevHover !== node) _updateNodeVisual(prevHover);
        if (node) {
          _activeNodeIds.add(node.id);
          _updateNodeVisual(node);
        } else if (prevHover) {
          _activeNodeIds.delete(prevHover.id);
        }
      })
```

Inside `_updateNodeVisual`, ensure `radius` recalculation always uses the canonical baseRadius when not active (fixes the lingering-bump bug):

The existing `const radius = isActive ? baseRadius + 1 : (isSpotlight ? baseRadius + 0.5 : baseRadius);` line is correct; the bug is that some nodes were never reaching this line. To guarantee, add a safety call near the end of `handleNodeClick` and the hover handler:

In the `handleBackgroundClick`:

```javascript
  function handleBackgroundClick() {
    if (_panelOpenTimer) { clearTimeout(_panelOpenTimer); _panelOpenTimer = null; }
    closePanel();
    selectedNode = null;
    _activeNodeIds.clear();
    highlightNodes.clear();
    _refreshAllNodeVisuals();
  }
```

- [ ] **Step 4: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "fix: KG spotlight ring billboarded; node scale always resets cleanly"
```

### Task 10.3: Auto-rotate off by default (P2 #17)

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js` (controls block in `initGraph`)

- [ ] **Step 1: Set `autoRotate = false`**

Inside `initGraph`, change:

```javascript
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.3;
```

to:

```javascript
    controls.autoRotate = false;
    controls.autoRotateSpeed = 0.1;
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "fix: KG auto-rotate off by default (less disorienting)"
```

---

## Phase 11: Loading + empty + error overlays (P1 #14, #15) + drop legend (P2 #23)

CSS overlay classes were already injected in Task 3.1 step 4; legend HTML was already removed there. Now we need overlay CSS and JS wiring.

### Task 11.1: Overlay CSS

**Files:**
- Modify: `website/features/knowledge_graph/css/style.css`

- [ ] **Step 1: Append**

```css
/* ============================================
   Overlays — loading / empty / error
   ============================================ */
.kg-overlay {
  position: fixed;
  inset: 64px 0 0 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  background: transparent;
  pointer-events: none;
  z-index: 50;
}
.kg-overlay.hidden { display: none; }
.kg-overlay-text { color: rgba(220, 228, 240, 0.65); font-size: 0.92rem; margin: 0; }
.kg-overlay-btn {
  pointer-events: auto;
  padding: 8px 16px;
  background: rgba(20,184,166,0.15);
  border: 1px solid rgba(20,184,166,0.45);
  border-radius: 10px;
  color: #2dd4bf;
  font-size: 0.85rem;
  cursor: pointer;
}
.kg-overlay-btn:hover { background: rgba(20,184,166,0.25); }
.kg-overlay-skeleton {
  display: flex; gap: 12px; align-items: center;
}
.kg-overlay-skeleton span {
  width: 14px; height: 14px; border-radius: 50%;
  background: rgba(20,184,166,0.4);
  animation: kgPulse 1.2s infinite ease-in-out both;
}
.kg-overlay-skeleton span:nth-child(2) { animation-delay: 0.15s; }
.kg-overlay-skeleton span:nth-child(3) { animation-delay: 0.30s; }
@keyframes kgPulse {
  0%, 80%, 100% { opacity: 0.25; transform: scale(0.7); }
  40%           { opacity: 1;    transform: scale(1.1); }
}
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/css/style.css
git commit -m "style: KG loading + empty + error overlays"
```

### Task 11.2: Overlay JS wiring

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js`

- [ ] **Step 1: Add helpers near the top of the IIFE**

```javascript
  function showOverlay(id, text) {
    const o = document.getElementById(id);
    if (!o) return;
    if (text) {
      const t = o.querySelector('.kg-overlay-text');
      if (t) t.textContent = text;
    }
    o.classList.remove('hidden');
  }
  function hideOverlay(id) { const o = document.getElementById(id); if (o) o.classList.add('hidden'); }
```

- [ ] **Step 2: Show loading at start of `loadGraphData`**

At the top of `loadGraphData()`:

```javascript
    showOverlay('overlay-loading');
    hideOverlay('overlay-empty');
    hideOverlay('overlay-error');
```

- [ ] **Step 3: Hide loading on success / show error on failure**

Modify the `.then(data => { ... })`: at the end of the `.then` block (inside the `if (graph) { applyFilters(); } else { initGraph(); updateStats(); }`), append:

```javascript
        hideOverlay('overlay-loading');
```

Modify the `.catch(err => { ... })`:

```javascript
      .catch(err => {
        console.error('Failed to load graph data:', err);
        hideOverlay('overlay-loading');
        showOverlay('overlay-error', 'Could not load graph data.');
        if (statsEl) statsEl.textContent = 'Failed to load data';
      });
```

- [ ] **Step 4: Wire retry button**

Append:

```javascript
  const overlayRetry = document.getElementById('overlay-error-retry');
  if (overlayRetry) overlayRetry.addEventListener('click', loadGraphData);
```

- [ ] **Step 5: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat: KG loading/empty/error overlays wired"
```

---

## Phase 12: A11y polish — Esc closes filter dropdown, aria-labels (P2 #24)

### Task 12.1: Esc closes filter dropdown

**Files:**
- Modify: `website/features/knowledge_graph/js/app.js`

- [ ] **Step 1: Update the existing `keydown` Escape handler**

Replace the existing `document.addEventListener('keydown', e => { if (e.key === 'Escape') { ... }})` block with:

```javascript
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    // 1) Close kasten modal first if open.
    const km = document.getElementById('kasten-modal');
    if (km && !km.classList.contains('hidden')) {
      window.kgKastenModal && window.kgKastenModal.close();
      return;
    }
    // 2) Close filter dropdown if open.
    if (filterDropdown && !filterDropdown.classList.contains('hidden')) {
      filterDropdown.classList.add('hidden');
      filterBtn && filterBtn.classList.remove('active');
      return;
    }
    // 3) Otherwise close panel + clear search/highlights (existing behaviour).
    if (_panelOpenTimer) { clearTimeout(_panelOpenTimer); _panelOpenTimer = null; }
    closePanel();
    selectedNode = null;
    _activeNodeIds.clear();
    highlightNodes.clear();
    hoverNode = null;
    if (searchInput) { searchInput.value = ''; _applySearch(''); }
    _refreshAllNodeVisuals();
  });
```

- [ ] **Step 2: Commit**

```bash
git add website/features/knowledge_graph/js/app.js
git commit -m "feat: KG Esc closes kasten modal then filter dropdown then panel"
```

---

## Phase 13: Deploy + Chrome verification loop

This phase runs after every commit phase above is complete on the working branch and tests are green.

### Task 13.1: Final test run and push

**Files:** (none)

- [ ] **Step 1: Run full Python test suite**

Run: `pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 2: Lint smoke-check the JS structurally**

Run: `python -c "import re, pathlib; t=pathlib.Path('website/features/knowledge_graph/js/app.js').read_text(); print('paren_balance:', t.count('(')-t.count(')')); print('brace_balance:', t.count('{')-t.count('}')); print('lines:', t.count(chr(10))+1)"`
Expected: paren_balance=0, brace_balance=0, lines roughly 1100-1300 depending on additions.

- [ ] **Step 3: Push to master (auto-deploys)**

```bash
git push origin master
```

- [ ] **Step 4: Watch GitHub Actions**

Run: `gh run list --branch master --workflow "Deploy to DigitalOcean Droplet" --limit 1 --json databaseId,status,conclusion`

Wait until `status: completed` and `conclusion: success`.

- [ ] **Step 5: Confirm deploy actually shipped the new JS**

Run: `curl -s "https://zettelkasten.in/kg/js/app.js?v=20260425a" | grep -c "extractBriefFromSummary"`
Expected: `1` (or higher).

Run: `curl -s "https://zettelkasten.in/kg/js/kasten_modal.js?v=20260425a" | grep -c "kgKastenModal"`
Expected: `1` or higher.

If either returns 0, **STOP** — investigate Caddy or build cache. Do not proceed to verification.

### Task 13.2: Manual Chrome verification per item (iteration 1)

**Files:**
- Create per-item screenshots under `docs/research/kg_ui_pass/iter1/`

- [ ] **Step 1: Open the KG via Claude in Chrome**

Use `mcp__Claude_in_Chrome__navigate` to `https://zettelkasten.in/knowledge-graph`.

- [ ] **Step 2: Verify each of the 26 items, screenshot evidence**

For each row in the table below, take a screenshot, save to disk, and tick the box. If any item fails, **do NOT** mark this iteration done — list failures and proceed to Task 13.3.

- [ ] P0 #1 — `curl` shows new JS
- [ ] P0 #2 — Click any node; panel summary starts with a letter, not `{`
- [ ] P0 #3 — Inspect `yt-petrodollar-...` (known empty date); date pill is hidden, badge sits flush
- [ ] P0 #4 — Open filter dropdown; "Newsletter" appears as a checkbox row with the substack-blue colour; select-only-Newsletter shows the 1 newsletter node
- [ ] P0 #5 — Hover any node, drag camera away, ensure node returns to base size; spotlight ring (if present) faces camera at every angle
- [ ] P1 #6 — Filter dropdown shows two collapsible sections; pick Source=YouTube + Kasten=AnyKasten; only YouTube nodes that are members of that kasten remain
- [ ] P1 #7 — Logged out: Personal segment greyed; click → login modal opens. Logged in: click Personal → graph reloads with `?view=my`; reload page → choice persists
- [ ] P1 #8 — Click Add-to-Kasten icon; modal opens; "+ Create new" works; Add → toast appears
- [ ] P1 #9 — Side panel date pill + badge match `.zettels-summary-meta-row` styling pixel-for-pixel (compare side-by-side with `/home/zettels`)
- [ ] P1 #10 — View-original button is the new circular teal-bordered icon button; hover glow visible
- [ ] P1 #11 — "Ask About This Note" button absent from panel
- [ ] P1 #12 — Idle labels never end mid-word; hover/select shows full title (up to 2 lines)
- [ ] P1 #13 — Side panel: tags + connections + buttons all reachable via panel-content scroll on small viewports
- [ ] P1 #14 — Uncheck every Source filter → "No notes match these filters" overlay + Reset button
- [ ] P1 #15 — Hard-reload; loading skeleton briefly visible before nodes appear
- [ ] P2 #16 — Header has no 540px dead band; toggle, search, filter, reset evenly distributed
- [ ] P2 #17 — Camera no longer auto-rotates after first paint
- [ ] P2 #18 — Reset-view button: drag camera away, click → returns to fit-all
- [ ] P2 #19 — Search "chess": camera flies to single match
- [ ] P2 #20 — Search shows result count badge on the right; clear (×) appears when input non-empty
- [ ] P2 #21 — Uncheck a source: dot opacity drops to 0.25, label strikethrough is unmistakable
- [ ] P2 #22 — Search placeholder + icon are visibly closer to the left edge than before (compare to baseline screenshot)
- [ ] P2 #23 — No legend at the bottom-left
- [ ] P2 #24 — Tab through header: back → Global → Personal → Search → Filter → Reset, each gets a teal focus ring; Esc closes filter dropdown if open
- [ ] P2 #25 — Open panel for node A; click a connected note B in the panel; panel content swaps to B INSTANTLY (no 700 ms gap)
- [ ] Note 1 — Action buttons live on the meta row beside date+badge, not at the bottom of the panel
- [ ] Note 2 — Toggle order: `Toggle | Search | Filter | Reset`
- [ ] Q3 — Logged-out greyed Personal click opens the login modal (same modal you'd get from the global Login button)
- [ ] Note 3 — On Global view, the Kastens filter section is greyed and shows "Switch to Personal to filter by Kasten"; clicking it switches view to Personal (logged in) or opens login (logged out); switching back to Global clears any kasten selections

Artifacts saved as `docs/research/kg_ui_pass/iter1/<P0-1>.png` etc.

- [ ] **Step 3: If all 28 boxes pass, declare iteration 1 complete**

Skip to Task 13.5.

### Task 13.3: Iteration 2 (if any fails in iter 1)

- [ ] **Step 1: For each failure, write a focused fix commit**

Each failure → smallest possible commit on master with a `fix(kg):` prefix and an `iter2` keyword in the body.

- [ ] **Step 2: Re-run Phase 13 Task 1 (push + deploy)**

- [ ] **Step 3: Re-run Phase 13 Task 2 (Chrome verification, save under `iter2/`)**

- [ ] **Step 4: If all pass, skip to Task 13.5; otherwise Task 13.4**

### Task 13.4: Iteration 3 (final loop iteration)

Same as Task 13.3 but artifacts go under `iter3/`. **This is the last loop iteration per spec.** If any item still fails after iter 3, document the failures in `docs/research/kg_ui_pass/iter3/REMAINING_GAPS.md` and surface to the user; do not loop further.

### Task 13.5: Final commit + observation

- [ ] **Step 1: Tidy any temp files**

Run: `git status` — if any uncommitted artifacts, decide per-file whether to commit (screenshots yes, scratch files no).

- [ ] **Step 2: Save a `decision` observation via mem-vault**

Per CLAUDE.md memory tagging rules, the choice to render KG as shell + use client-side join for Kasten membership are decisions worth recording.

Use `mcp__plugin_mem-vault_mem-vault__save_observation` with type=`decision`, content="KG UI production pass: switched /knowledge-graph route to _render_with_shell (so login modal becomes available); Kasten membership joined client-side (no schema change). Rationale: minimum-blast-radius approach for a feature-rich UI pass over a live page."

- [ ] **Step 3: Done.**

---

## Self-review

**Spec coverage check (against §3 of spec):**

| Spec section | Plan task |
|---|---|
| §3.1 Header | Task 3.1, 3.2 |
| §3.1.1 Toggle | Task 3.1 (HTML), 3.2 (CSS), 4.1 (JS) |
| §3.1.2 Search | Task 3.1 (HTML), 3.2 (CSS), 5.1 (JS) |
| §3.1.3 Filter dropdown | Task 3.1 (HTML), 3.3 (CSS), 7.1+7.2 (JS) |
| §3.1.4 Reset view | Task 3.1 (HTML), 3.2 (CSS), 6.1 (JS) |
| §3.2 Side panel | Task 3.1 (HTML), 8.1 (CSS), 8.2 (JS) |
| §3.3 Add-to-Kasten modal | Task 3.1 (placeholder), 9.1 (CSS), 9.2 (JS module) |
| §3.4 Empty/loading/error states | Task 3.1 (HTML), 11.1 (CSS), 11.2 (JS) |
| §3.5 Node visuals & 3D fixes | Task 10.1 (truncation), 10.2 (ring + scale), 10.3 (autorotate) |
| §3.6 Drop legend | Task 3.1 step 4 |
| §3.7 A11y | Task 3.2 (focus rings), 12.1 (Esc), 3.1 (aria) |
| §3.8 Connection-click panel refresh | Task 8.2 step 2 |
| §4 Data layer | Task 7.2 (lazy fetch), Task 9.2 (POST members) |
| §5 Tests | Task 1.1, 2.2 |
| §5.3 Deploy verification | Task 13.1 step 5 (curl), 13.2 (Chrome) |

All 26 active items from the priority table are mapped. No "TBD" / "TODO" / "implement later" markers in the plan body. All code blocks contain complete code, not pseudocode. Type signatures and IDs are consistent across phases (`#kasten-modal`, `kgKastenModal`, `_currentPanelNodeId`, `activeSources`, `activeKastens`, `kastenMembership`, `kastenList`, `knownSources`, `_activeNodeIds`).

**Risks acknowledged:**
- If `/api/rag/sandboxes/{id}/members` returns >1000 members for a single Kasten, the `?limit=1000` cap in Task 7.2 misses the rest. Acceptable for current data volumes; revisit when any user crosses 1000 zettels in a single Kasten.
- The DOM-driven login modal trigger (`document.querySelector('.home-login-btn, [data-open-login], #header-login-btn')?.click()`) depends on the header partial exposing a stable selector. Phase 0 step 3 is the gate that confirms or amends this selector list.
