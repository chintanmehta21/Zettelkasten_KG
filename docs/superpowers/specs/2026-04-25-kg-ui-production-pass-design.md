# Knowledge Graph UI — Production Pass (Design)

**Status:** approved-pending-review
**Date:** 2026-04-25
**Owner:** chintanmehta21
**Scope:** `website/features/knowledge_graph/` (HTML/CSS/JS), `website/app.py` (route shell wiring), small additions in `website/api/`

## 0 — Goal

Lift the 3D Knowledge Graph from "works" to "production-grade UI" in one bundled change. Resolve every issue raised by the user (12 numbered items) plus 13 additional defects and gaps surfaced during a Chrome-driven live inspection of the deployed app at `https://zettelkasten.in/knowledge-graph`. Match visual primitives from the My Zettels page so the product feels consistent across pages.

This is a **production change** under the rules in `CLAUDE.md`: no partial work, no broken intermediate states, all tests pass, defensive handling of every data-quality edge already observed in production.

---

## 1 — Inspection summary (what's broken now)

Captured live on 2026-04-25 from `https://zettelkasten.in/knowledge-graph` against current data (24 nodes, 19 links, 5 distinct groups: youtube, reddit, newsletter, github, substack).

| Severity | Defect | Evidence |
|---|---|---|
| P0 | Side panel renders raw JSON for summary | Production `/kg/js/app.js` line `summary.textContent = node.summary || ''` — missing `extractBriefFromSummary` from local source. Stale deploy. |
| P0 | 9 of 24 nodes (37%) have `date=""` → empty `<p>` rendered | `/api/graph` payload sample. |
| P0 | `newsletter` group exists in data but is absent from filter dropdown, COLORS map, and legend → 1 node uncolored & unfilterable. `medium` and `web` shown in filter UI but have zero matching data. | Filter list is hardcoded; data has drifted. |
| P0 | Spotlight ring sprite + selected/hover scale do not always reset cleanly when state ends → "shape malforms" on drag away from a previously-hovered node. | User screenshot + code path: `_updateNodeVisual` rebuilds material/scale only on hover transitions; ring sprite added in `nodeThreeObject` is not auto-billboard-corrected on every camera frame. |
| P1 | Side panel content (tags, connections, action buttons) falls below fold on small viewports; container has `overflow-y: visible`. | Computed style check. |
| P1 | After filter selection that yields 0 nodes, canvas is silently blank. | `applyFilters()` does not show empty state. |
| P1 | No loading affordance during initial `/api/graph` fetch — first paint is plain dark canvas. | First-paint UX gap. |
| P1 | Header has ~540px dead band when logged out (view-toggle hidden, search anchored to right). | DOM measurement. |
| P2 | Auto-rotate at speed 0.3 is faster than typical knowledge-graph viewers; disorienting on first paint. | Subjective; matches reference KG that uses 0 by default. |
| P2 | Search has no result-count indicator and no clear (×) button. | DOM check. |
| P2 | When search finds matches, camera does not refocus — match may be off-screen. | Behavioural. |
| P2 | Filter checkbox visual feedback is real (strikethrough + dim) but very subtle — easy to miss. | Visual inspection. |
| P2 | Bottom-left legend duplicates the always-accessible filter dropdown. | Redundancy. |
| P2 | No "reset view" affordance when user gets lost in 3D space. | UX gap. |
| P2 | No focus-visible outlines on header buttons; Esc closes panel but not filter dropdown. | A11y gap. |
| P3 | Console: "Multiple instances of Three.js being imported" — the page loads `three.min.js` directly **and** the bundled copy inside `3d-force-graph.min.js`. | Console warning, no functional impact. |

---

## 2 — Architecture (where things change)

```
website/
  app.py
    └ /knowledge-graph route → switch from FileResponse to _render_with_shell
      so the shared header (with login modal) is injected into KG page.
  features/
    knowledge_graph/
      index.html       ← header restructure, side-panel restructure, login-modal placeholder, kasten modal
      css/style.css    ← restyle of all panels, filter dropdown, toggle, modal, badge
      js/app.js        ← brief extraction hardening, multi-filter, kasten-aware data join,
                          view toggle, ring/scale fixes, search UX, empty/loading states
      content/         ← unchanged
    user_kastens/
      js/user_kastens.js ← extracted helper for "list user kastens" reused by KG
  api/
    routes.py          ← optional: /api/graph already supports view=my; no schema change
                          (kasten membership joined client-side)
  artifacts/
    logo-kastens.svg   ← reused for "Add to Kasten" icon button
```

**No backend schema changes.** All Kasten data is fetched via existing `/api/rag/sandboxes` and `/api/rag/nodes` endpoints and joined client-side.

---

## 3 — Component-level design

### 3.1 Header (top bar)

Two clusters:

```
LEFT  : [ ← back ] [ kg-logo ] [ Knowledge Graph / N notes · M connections ]
RIGHT : [ Toggle ]   [ Search ]   [ Filter ]   [ Reset view ]
```

- Left cluster unchanged structurally; logo and stats stay.
- Right cluster order is fixed: `Toggle → Search → Filter → Reset view`.
- When **logged out**, Toggle is shown but the Personal segment is greyed and clicking it opens the global login modal (same UX as clicking "Login" in the main header). When **logged in**, Toggle is fully active.
- Header background gains a subtle dark-translucent backing (`rgba(8,12,24,0.55)` + 6px backdrop blur) so it sits cleanly over the canvas at any zoom.
- **Header dead-band fix**: keeping the toggle visible in both logged-in and logged-out states (with greyed Personal in the latter) eliminates the ~540 px empty band today's logged-out header has between title and search. No further conditional widening of the search bar is needed — the four right-cluster controls (~520 px combined) plus the left cluster fully populate the bar at all viewport widths ≥ 1024 px.

#### 3.1.1 Personal/Global toggle (segmented pill)

Visual contract is the **Preview/Code pill** from the user-supplied reference image:

- Outer container: dark pill, 1px border `rgba(255,255,255,0.08)`, height 36px, padding 4px, radius 12px.
- Active segment: filled `#0B0F1A`, 1px subtle border, white text, radius 9px.
- Inactive segment: transparent, muted text `var(--text-muted)`, no border.
- Each segment: 24px lucide icon + label.
  - **Global** segment: lucide `globe` icon + "Global"
  - **Personal** segment: lucide `user` icon + "Personal"
- Active state persisted to `localStorage["kg.view"]` so reload restores the choice.
- Width approx 200px (auto from content).
- When Personal is greyed (logged out), the segment renders inactive style + `tabindex=0` and `aria-disabled="true"`. Click handler routes to `openLoginModal()`. A native `title` tooltip reads "Sign in to switch to Personal".
- Login modal availability: switch `/knowledge-graph` route from `FileResponse` → `_render_with_shell(KG_DIR / "index.html")` so the header partial (which owns `#login-modal`) is inlined. Add `<!--ZK_HEADER-->` placeholder to KG `index.html`. Existing `auth.js` modal API is reused as-is. Its CSS continues to live with the header partial.

#### 3.1.2 Search input (issue #9, Chrome J/K)

- Move placeholder + icon 3px left (decrease icon `left` from current to current-3px, decrease input `padding-left` to match).
- Add inline result-count badge inside the input on right side: `1` / `12` / `0` matches. Hidden when input empty.
- Add ✕ clear button right of count when input non-empty. Clears input + triggers `input` event.
- On match >= 1, after 250ms debounce, call `graph.zoomToFit(800, 80, n => highlightNodes.has(n.id))` so matches are visible. Single match: fly camera using `handleNodeClick(matchedNode)` style (without opening panel).

#### 3.1.3 Filter button + multi-filter dropdown (issue #8, Chrome G/H)

Filter button unchanged structurally. Dropdown becomes two collapsible sections:

```
┌───────────────────────────────────┐
│ Source                          ▾ │
│   ● YouTube      ● Reddit         │
│   ● GitHub       ● Substack       │
│   ● Newsletter   ● Medium         │  ← rendered from data, never hardcoded
│   ● Web                           │
├───────────────────────────────────┤
│ Kastens                         ▾ │
│   ☐ Climate                       │  ← from /api/rag/sandboxes (logged-in)
│   ☐ AI Safety                     │
│   ─────────────────────────────   │
│   (logged-out: "Sign in to filter │
│    by Kasten" link → openLogin)   │
│   (zero kastens: "No Kastens yet  │
│    — Create one →" link)          │
└───────────────────────────────────┘
```

- Both sections start expanded; arrow rotates to collapse.
- Filter checkbox visual upgrade: unchecked items get **strikethrough + dot opacity 0.25 + label opacity 0.45**. Currently dot stays full opacity → bumping the contrast makes off-state unmistakable.
- Combine semantics: **AND between sections, OR within**. SQL-equivalent:
  - `node.group IN selectedSources AND (selectedKastens IS EMPTY OR node.id IN any(selectedKastens.members))`
- Source list rendered from `Object.keys(COLORS_BY_GROUP)` derived from the union of (built-in groups) + (groups present in fetched data) — so `newsletter` auto-appears.
- Color of `newsletter` group: HSL `205 40 68` (matches `.zettels-source-badge.newsletter` in `user_zettels.css`).

#### 3.1.4 Reset view button

Small icon-only button (16px lucide `maximize-2`), 36x36px circular like the toggle segments. Fires `graph.zoomToFit(800, 60)` and resets camera autorotate to user's last-saved preference.

### 3.2 Side panel

Width: `min(420px, 38vw)`. Container becomes `display: flex; flex-direction: column;` and `.kg-panel-content` becomes `overflow-y: auto`. Close (`✕`) is absolutely positioned in the top-right corner with `z-index: 2`.

**New top row** (Note 1 from user, single line, left-aligned):

```
[Apr 24, 2026] [YOUTUBE]  [↗]  [⊞ Kasten]                                  [✕]
```

- **Date pill** + **Source badge** = exact copy of `.zettels-summary-meta-row` + `.zettels-source-badge.<group>` styles. Pulled in via shared CSS or duplicated tokens.
- **View original** = circular icon button, 36px, 1px teal border (`rgba(20,184,166,0.4)`), lucide `external-link`. Click → opens `node.url` in new tab (passes through `toSafeHttpUrl` so non-http(s) URLs are blocked, just like today).
- **Add to Kasten** = identical-sized circular button, masked SVG of `/artifacts/logo-kastens.svg`. Click → opens Kasten modal (3.3).
- Both buttons reuse exact same dimensions as the existing zettels go-to button on the My Zettels page.
- Spacing: 8px gap between elements; auto margin pushes ✕ to the far right.
- When `node.date` is empty/invalid: hide date pill entirely (do not render empty pill). Source badge always present.
- When `node.url` is missing or fails `toSafeHttpUrl`: View-original button is `aria-disabled="true"`, opacity 0.4, no click handler.

**Below top row:**

```
Title (H2)  ← already present, keep
Brief summary (paragraph)  ← rewrites with hardened extractor
[#tags row]
─────────────────────
CONNECTED NOTES (n)
  ● Note A — relation
  ● Note B — relation
```

- Removed: "Ask About This Note" link (issue #11). Removed: Bottom action row (its buttons moved to top row).
- Brief extractor (`extractBriefFromSummary`) is hardened: try `brief_summary` → `briefSummary` → `summary` → first non-empty bullet of `detailed_summary[0].bullets` → fallback to first 240 chars of stripped raw string. Never returns a string starting with `{`.

### 3.3 Add-to-Kasten modal

Lightweight `<dialog>`-style modal injected into KG page (independent of the auth modal). One file's worth of CSS, no router change.

```
┌─ Add to a Kasten ─────────────────[✕]
│ Note: "Effective Public Speaking…"
│
│ Select a Kasten
│ ┌──────────────────────────────────┐
│ │ + Create new Kasten              │
│ │ ────────────────────────────     │
│ │ ◯ Climate                        │
│ │ ◯ AI Safety                      │
│ └──────────────────────────────────┘
│
│      [ Cancel ]    [ Add ]
└────────────────────────────────────
```

- "Create new Kasten" expands inline to show a name input + Create button. On create, `POST /api/rag/sandboxes`, then add membership via `POST /api/rag/sandboxes/{id}/members`.
- "Add" disabled until a selection exists. Fires `POST /api/rag/sandboxes/{id}/members { node_id: <id> }`.
- Logged-out user: instead of opening Kasten modal, click on Add-to-Kasten button opens the global login modal (same flow as Personal segment).
- Success: toast "Added to {kastenName}" bottom-center; modal closes.
- Error: inline error message inside modal; no toast.

### 3.4 Empty / loading / error states

- **Loading**: Centered subtle pulsing skeleton (3 faint linked dots) shown while `/api/graph` and `/api/rag/sandboxes` are in flight. Hidden as soon as `graphData.nodes.length > 0`.
- **Empty filter result**: Centered text overlay "No notes match these filters" + ghost "Reset filters" button. Triggers when `applyFilters()` produces 0 nodes.
- **API error**: Centered text "Could not load graph data" + small retry button (re-fires `loadGraphData()`).

### 3.5 Node visuals & 3D fixes

#### Spotlight ring + scale-reset (issue #7)

- Replace spotlight `Sprite` with billboarded `THREE.Mesh` using `RingGeometry(rIn, rOut, 48)` + `MeshBasicMaterial({transparent, opacity, color, depthWrite:false})`. The mesh is rotated each frame inside the existing `requestAnimationFrame(clampLabelScales)` loop with `mesh.lookAt(camera.position)`.
- `_updateNodeVisual` updates the radius **for every node** when `selectedNode` or `hoverNode` transitions away — including resetting the previously-active node back to base radius. Currently the function only fires for the new and the previous; a stale third node that was scaled by an interrupted hover can get stuck. Fix: keep an explicit `_activeNodes = Set<id>` and clear scale on every node not in the set on hover/select changes.

#### Idle label clarity (issue #1)

- `_truncate(str, maxWords=2)` → replace with `_smartTruncate(str, maxChars=28, prefer="word")` that keeps full words, never breaks mid-word, drops trailing fillers (`of`, `the`, `for`, …). Min length 8 chars.
- Hover/select labels: keep full title but cap to 2 lines via spritetext `text` newlining (split at the first whitespace past 32 chars).
- Font weight idle: 500 → 600 for slightly better readability against dark canvas.

#### Auto-rotate (Chrome E)

- `controls.autoRotate = false` by default.
- `controls.autoRotateSpeed = 0.1` if user opts in (no UI toggle in this pass — just slow it down to a humane default for a future opt-in).
- On any `mousedown` / `touchstart` on canvas, autorotate stops (already true).

### 3.6 Drop legend

Bottom-left `#legend` removed. Filter dropdown is the sole source of truth for source colors. Reduces visual clutter and avoids the "two places to remember to update" maintenance burden that already caused the `newsletter` mismatch.

### 3.7 A11y polish

- Header buttons (`.kg-back`, `.kg-search`, `.kg-filter-btn`, `.kg-view-btn`, `.kg-reset-btn`) gain visible focus rings: `outline: 2px solid rgba(20,184,166,0.55); outline-offset: 2px;`.
- `Esc` keypress while filter dropdown is open → closes it (in addition to existing panel-close).
- All icon-only buttons have `aria-label`.
- **Tab order** through header is left-to-right, top-to-bottom: back → logo (skipped, non-interactive) → toggle (Global, then Personal) → search → filter → reset-view → side-panel close (when open). Each receives focus once. No `tabindex` higher than `0`. Verified by manual Tab-walk on each iteration of the verification loop.

### 3.8 Side-panel "Connected Notes" click → refresh panel (was missing)

Issue: clicking a row in the panel's Connected Notes list calls `handleNodeClick(targetNode)`, which flies the camera to the new node, but `openPanel()` is **only** called on a delay inside `handleNodeClick`. Verified via inspection: the panel does eventually re-populate for the clicked connection, BUT only after the 700 ms `_panelOpenTimer`. During the 700 ms window the panel still shows the previous node's content, which feels broken.

Fix:
- Inside `handleNodeClick`, when the panel is already open (`sidePanel.classList.contains('visible')`), call `openPanel(node)` synchronously **before** the camera fly so content swaps instantly. The camera animation continues independently.
- When the panel is closed, keep the existing 700 ms delay (lets camera centre first, then panel slides in).
- Add a `data-node-id` attribute to `.kg-panel` and update it inside `openPanel(node)`. Each connected-note click handler short-circuits if `targetNode.id === currentPanelNodeId` (no flicker).

---

## 4 — Data layer

No new endpoints. Client-side joins:

1. On page load: `Promise.all([fetch('/api/graph'+viewParam, …), fetch('/api/rag/sandboxes', …)])`.
2. Build `kastenMembership: Map<nodeId, Set<kastenId>>` from the sandboxes response (each sandbox has a `members: [{node_id}]` list — verify against current API; if absent, fall back to a per-sandbox membership fetch lazily on Kasten-section expansion).
3. `applyFilters()` consults both the Source set and the Kastens set when computing the visible node list.
4. The View toggle still uses `?view=my` on `/api/graph`, unchanged.

---

## 5 — Tests & verification

### 5.1 Tests added

- `tests/website/test_kg_api_kastens.py`: confirms `/api/graph` and `/api/rag/sandboxes` return shapes the client expects (smoke test).
- `tests/website/test_kg_route_shell.py`: confirms `/knowledge-graph` HTML now includes the `<!--ZK_HEADER-->` shell expansion (so login modal is present in the DOM).
- No existing tests removed.

### 5.2 Manual verification (Claude in Chrome)

After deploy, take a screenshot for each of the 26 numbered changes and diff against this spec. Re-iterate up to 3 times if any miss (per user's `/loop` requirement). Each iteration commits + redeploys; verification artifacts saved under `docs/research/kg_ui_pass/`.

### 5.3 Deploy + cache verification (P0 #1 root cause)

Before declaring the brief-summary fix done, the verification loop must explicitly confirm the new `app.js` is what the browser is actually executing. Procedure:

1. After GitHub Actions completes, hit `https://zettelkasten.in/kg/js/app.js` directly via `curl -s | grep -c "extractBriefFromSummary"` and confirm count > 0.
2. If the live JS still lacks the function, investigate cache (Caddy, CDN if any) — do NOT mark the bug fixed.
3. In Chrome, hard-reload (`Ctrl+Shift+R`) and re-verify panel content for a known-bad node (`yt-infinite-complexity-chess`). Panel summary must start with a letter, not `{`.
4. The `<script src="/kg/js/app.js?v=…">` tag in `index.html` should append a build-sha cache-bust query string so future deploys cannot serve stale JS even if a cache-control header is misconfigured. Add this in the same change.

---

## 6 — Out of scope (deferred)

- Three.js multi-instance console warning (P3): worth fixing later by switching `3d-force-graph` import to the ESM bundle that doesn't re-export Three.js. Not blocking this pass.
- Bottom-corner controls hint text (`Left-click: rotate · Scroll: zoom · Right-click: pan`): explicitly **dropped** per user side-note. Native controls stay; no overlay.
- Mobile KG (`/m/knowledge-graph`) — separate page, not touched in this pass.
- Backend changes for kasten membership endpoint shape: only addressed if step 4.2 reveals current shape can't support client-side join.

---

## 7 — Risks

- **Kasten membership shape unknown**: if `/api/rag/sandboxes` doesn't already include member node_ids, we either add a per-sandbox lazy fetch or extend the response. Will verify in implementation Phase 0 (Documentation Discovery) before building the Kasten filter section. Fallback: ship Kasten filter as "logged-in only, fetched on first open" with the lazy approach.
- **Header partial coupling**: switching `/knowledge-graph` to `_render_with_shell` pulls the full header CSS into the KG page. Confirm no class-name collisions (`kg-` prefix already isolates KG styles; header uses non-prefixed `home-*`).
- **Auto-rotate-off**: some users may have come to expect the gentle rotation. Acceptable trade for the disorientation reports; revisit if requested.
- **Stale-deploy root cause**: redeploy alone fixes the visible JSON bug, but we want belt+suspenders — the hardened brief extractor never returns raw JSON regardless of input shape.

---

## 8 — Approval gate

This spec captures user-confirmed decisions:
- ✅ All 12 original requested changes
- ✅ All 13 Chrome-inspection bugs/gaps
- ✅ Single filter button with two collapsible sections (Source + Kastens)
- ✅ AND between filter sections, OR within
- ✅ "Ask About This Note" removed entirely
- ✅ Action buttons (View original, Add to Kasten) circular icon-buttons in top row beside date/badge
- ✅ Toggle order: `[Toggle] [Search] [Filter]`
- ✅ Greyed Personal segment opens login modal (same UX as global Login)
- ✅ Controls hint overlay text: NOT adopted
