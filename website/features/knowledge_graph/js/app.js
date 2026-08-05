/* ============================================
   Knowledge Graph — Lightweight 3D Viewer
   ============================================
   Performance targets:
   - < 2s full load (graph visible + interactive)
   - Single shared SphereGeometry for all nodes
   - MeshBasicMaterial (no lighting = flat circle at every angle)
   - Cached materials to avoid GC churn
   - Minimal draw calls: 1 mesh + 1 sprite per node
   ============================================ */

/* test-exports:start */
// Pure helpers — extracted so vitest can exercise them without booting
// THREE / 3d-force-graph (CDN globals not available under jsdom). The
// fence markers are load-bearing — `tests/js/knowledge_graph/*.test.js`
// regex-extracts everything between them. Edit with care.
//
// WAVE-C 1c locked decisions (mem-vault VCS_HUtQLKTHzh71InGIU87I):
//   D-KG-3  Default render threshold ≥ 0.7 (Strong-only) on first load.
//   D-KG-4  Buckets: Strong ≥ 0.70, Medium 0.50–0.70, Weak 0.30–0.50.
//           Slider: 0.30–0.85 step 0.05, 250 ms debounce, re-warm at α=0.3.
//   D-KG-VIS Encode connection_strength as line OPACITY + line WIDTH only.
//            Color stays amber/gold; community modulates HUE within 30–55.
const STRENGTH_BUCKETS = {
  strong: { min: 0.7, label: 'Strong' },
  medium: { min: 0.5, label: 'Medium' },
  weak:   { min: 0.3, label: 'Weak'   }
};
// LD-1: default min strength equals SLIDER_MIN so first paint is maximally
// permissive. Was 0.7 under the deprecated D-KG-3 strong-only-first rule.
const DEFAULT_MIN_STRENGTH = 0.30;
const SLIDER_MIN = 0.3;
const SLIDER_MAX = 0.85;
const SLIDER_STEP = 0.05;
const SLIDER_DEBOUNCE_MS = 250;
const AMBER_HUE_MIN = 30;
const AMBER_HUE_MAX = 55;

function snapToBucket(name) {
  const b = STRENGTH_BUCKETS[name];
  return b ? b.min : DEFAULT_MIN_STRENGTH;
}
function bucketForStrength(s) {
  const v = Number(s);
  if (!Number.isFinite(v) || v < STRENGTH_BUCKETS.weak.min) return null;
  if (v >= STRENGTH_BUCKETS.strong.min) return 'strong';
  if (v >= STRENGTH_BUCKETS.medium.min) return 'medium';
  return 'weak';
}
function tierForStrength(s) {
  // LD-5: tier is computed client-side from connection_strength. Backend no
  // longer ships `tier` on the wire — keeps per-workspace cross-scope
  // consistency (B2 fix) and removes a stale-on-rescore field. Boundaries
  // match D-KG-4 buckets so a tier and its visual band always agree.
  const v = Number(s);
  if (!Number.isFinite(v)) return 'weak';
  if (v >= 0.7) return 'strong';
  if (v >= 0.5) return 'medium';
  return 'weak';
}
function cullLinksByStrength(links, threshold) {
  if (!Array.isArray(links)) return [];
  const t = Number(threshold) || 0;
  if (t <= 0) return links.slice();
  return links.filter(function (l) {
    // LD-2: null/undefined/absent connection_strength is "unscored, visible by
    // default". Only numeric strengths below the threshold are culled.
    const raw = l && l.connection_strength;
    if (raw === null || raw === undefined) return true;
    const s = Number(raw);
    if (!Number.isFinite(s)) return false;
    return s >= t;
  });
}
function debounce(fn, ms) {
  let h = null;
  return function () {
    const args = arguments, self = this;
    if (h) clearTimeout(h);
    h = setTimeout(function () { h = null; fn.apply(self, args); }, ms);
  };
}
function _clamp(x, lo, hi) { return x < lo ? lo : (x > hi ? hi : x); }
function edgeOpacityFor(s) {
  const v = _clamp(Number(s) || 0, 0, 1);
  return 0.2 + 0.8 * v;
}
function edgeWidthFor(s) {
  const v = _clamp(Number(s) || 0, 0, 1);
  return 0.5 + 2.5 * v;
}
function getCommunityHue(communityId) {
  // Spread integer ids deterministically across the amber band [30..55] so
  // distinct communities are visually distinguishable while keeping the
  // CLAUDE.md "no purple, amber on /knowledge-graph" rule intact.
  if (communityId === null || communityId === undefined) {
    return (AMBER_HUE_MIN + AMBER_HUE_MAX) / 2;
  }
  const span = AMBER_HUE_MAX - AMBER_HUE_MIN;
  const idx = Math.abs(parseInt(communityId, 10) || 0);
  return AMBER_HUE_MIN + (idx * 7 % (span + 1));
}

// Settle tuning (audit 2026-06-04): tier the off-screen pre-settle by node
// count so the FIRST painted frame is near-final (no chaotic churn), capped so
// first paint is never delayed on big graphs / low-end devices. The visible
// drift-to-rest is governed by GRAPH_COOLDOWN_MS (down from the old 2500ms) —
// keeps the "alive" feel but reads as "ready" not "loading".
const GRAPH_COOLDOWN_MS = 1100;
function warmupTicksForNodeCount(n) {
  const count = Number(n) || 0;
  return Math.min(250, Math.max(60, Math.round(count * 0.6)));
}

// Observability (audit 2026-06-04, flip-metric #1): one console line per graph
// load — decoded payload size + wall time + node count. Watched to decide when
// LOD/progressive-reveal trips (payload measured client-side, post-CDN).
function formatGraphLoadMetric(stats) {
  const kb = Math.round((Number(stats && stats.bytes) || 0) / 1024);
  const ms = Math.round(Number(stats && stats.ms) || 0);
  const nodes = Number(stats && stats.nodes) || 0;
  return '[kg] graph loaded: ' + nodes + ' nodes, ' + kb + ' KB, ' + ms + ' ms';
}
// A3 root-cause fix (2026-06-15): always send an EXPLICIT view. Omitting it
// let the server infer the view from auth (authed -> 'my'), so an authed
// user's "Global" toggle silently returned their personal graph. currentView
// is binary ('global' | 'my'); anything not 'my' is treated as global.
function buildGraphApiUrl(view, minStrength) {
  const params = new URLSearchParams();
  params.set('view', view === 'my' ? 'my' : 'global');
  params.set('min_strength', String(minStrength));
  return '/api/graph?' + params.toString();
}
// Part B Phase 1: view=global is a PUBLIC, edge-cached response. Sending
// Authorization on it makes Cloudflare BYPASS the cache (and risks keying a
// private response as public). currentView is binary: 'my' keeps auth,
// anything else (global) sends NO Authorization header.
function headersForView(view, authHeadersFn) {
  if (view === 'my') return authHeadersFn();
  return {};
}
// Part B Phase 1 — pure privacy-UX helpers (DOM wiring lives outside the fence).
// Opt-OUT model: zettels are public by default; the action toggles privacy.
function privacyToggleLabel(isPrivate) {
  return isPrivate ? 'Make public' : 'Make private';
}
// Persistent "Private" badge spec, shown ONLY on hidden zettels. TEAL only
// (amber is reserved for the /knowledge-graph 3D viz; never purple). Returns a
// spec the DOM layer applies.
function privacyBadge(isPrivate) {
  if (!isPrivate) return { visible: false, text: '', className: '' };
  return { visible: true, text: 'Private', className: 'kg-private-badge' };
}
// Undo toast copy after a toggle (NN/G: reversible action over a blocking modal).
function undoToastText(nowPrivate) {
  return nowPrivate ? 'Marked private. Undo?' : 'Made public. Undo?';
}
// Part B Phase 1 (2026-06-16): community empty-state decision. Only the GLOBAL
// view shows "No community zettels yet"; Personal keeps its Part A empty state.
// With the file-store retired this is the only empty-global path. Pure decision.
function communityEmptyState(view, nodeCount) {
  if (view === 'global' && (Number(nodeCount) || 0) === 0) {
    return { show: true, text: 'No community zettels yet' };
  }
  return { show: false, text: '' };
}
// A4 (2026-06-15): pure decision for live auth-state changes. Returns null
// for no-op events (e.g. a session-less REPLAY/RESTORE at boot) so the
// subscriber does nothing. On SIGNED_OUT while viewing Personal we switch
// back to Global so the user never stares at a stale empty personal graph;
// the teal reauth banner (zk_fetch.js / auth-core.js) prompts re-sign-in.
function authChangeDecision(event, hasSession, currentView) {
  if (hasSession) {
    return { isLoggedIn: true, personalEnabled: true, switchToGlobal: false };
  }
  if (event === 'SIGNED_OUT') {
    return { isLoggedIn: false, personalEnabled: false, switchToGlobal: currentView === 'my' };
  }
  return null;
}
/* test-exports:end */

(function () {
  'use strict';

  var zkFetch = window.zkFetch || window.fetch;  // signup-failure-fixes-1a: fall back if wrapper not loaded

  // ---- Node colours by source. ----
  // Phase 4 / Task 4.1 (D1+D2+D3): registry now lives in
  // `website/core/source_registry.py`; this file fetches the canonical data
  // at boot via /api/meta/source-types. The constants below seed defensive
  // defaults so the graph still renders if the fetch fails (e.g., offline
  // or 5xx) — overwritten on the first successful response.
  let COLORS = {
    youtube:    '#E05565',
    reddit:     '#E09040',
    github:     '#56C8D8',
    substack:   '#60A5FA',
    newsletter: '#60A5FA',
    medium:     '#4ADE80',
    twitter:    '#1DA1F2',
    web:        '#94A3B8'
  };
  let COLORS_INT = {
    youtube:    0xE05565,
    reddit:     0xE09040,
    github:     0x56C8D8,
    substack:   0x60A5FA,
    newsletter: 0x60A5FA,
    medium:     0x4ADE80,
    twitter:    0x1DA1F2,
    web:        0x94A3B8
  };
  let SOURCE_LABEL = {
    youtube: 'YouTube',
    reddit: 'Reddit',
    github: 'GitHub',
    substack: 'Substack',
    newsletter: 'Newsletter',
    medium: 'Medium',
    twitter: 'Twitter',
    web: 'Web'
  };

  async function _loadSourceRegistry() {
    try {
      const r = await zkFetch('/api/meta/source-types', { cache: 'force-cache' });
      if (!r.ok) throw new Error('source-types fetch failed: ' + r.status);
      const data = await r.json();
      for (const [key, meta] of Object.entries(data)) {
        if (meta && typeof meta === 'object') {
          if (typeof meta.color_hex === 'string') COLORS[key] = meta.color_hex;
          if (typeof meta.color_int === 'number') COLORS_INT[key] = meta.color_int;
          if (typeof meta.label === 'string') SOURCE_LABEL[key] = meta.label;
        }
      }
    } catch (e) {
      console.warn('source registry pickup failed; using defaults', e);
    }
  }
  const _registryReady = _loadSourceRegistry();

  function escapeHtml(str) {
    const el = document.createElement('span');
    el.textContent = str;
    return el.innerHTML;
  }

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

  // Defensive brief-summary extractor.
  //
  // F6: WeakMap-memoized lookup of the parsed brief per node. Holding the
  // memo on the node object (vs a Map keyed by id) lets GC reclaim entries
  // when a node leaves graphData. extractBriefFromSummary is JSON.parse-heavy
  // and gets called per-keystroke from _applySearch on every node — the
  // memo turns a typical 100ms search-step into <1ms.
  const _briefMemo = new WeakMap();
  function getBrief(node) {
    if (!node || typeof node !== 'object') return '';
    let brief = _briefMemo.get(node);
    if (brief === undefined) {
      brief = extractBriefFromSummary(node.summary);
      _briefMemo.set(node, brief);
    }
    return brief;
  }

  // Production data ships `node.summary` as a JSON-stringified envelope:
  //   { "mini_title": "", "brief_summary": "…", "detailed_summary": [...], "closing_remarks": "…" }
  // but several legacy rows ship plain strings, and a small fraction of the
  // envelope is malformed. This function NEVER returns a value that starts
  // with "{" — it always degrades to a human-readable string.
  function extractBriefFromSummary(raw) {
    // S3 (T4.15): the server now parses the envelope at the wire boundary and
    // returns { brief, detailed, closing }. Fast-path the common case so we
    // don't redo JSON.parse on every panel open. Legacy file-store rows
    // still ship strings — they fall through to the original path below.
    if (raw && typeof raw === 'object' && typeof raw.brief === 'string') {
      const b = raw.brief.trim();
      if (b) return b.length > 800 ? b.slice(0, 800).trimEnd() + '…' : b;
    }
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

  function toSafeHttpUrl(rawUrl) {
    const value = String(rawUrl || '').trim();
    if (!value) return '';
    try {
      const parsed = new URL(value, window.location.origin);
      const protocol = parsed.protocol.toLowerCase();
      if (protocol !== 'http:' && protocol !== 'https:') return '';
      return parsed.href;
    } catch (err) {
      void err;
      return '';
    }
  }

  // Map a KG graph node onto the canonical shape consumed by ZKSummary.open().
  // KG payloads carry `name` + `group`; user_zettels uses `title` + `source`.
  // The popup module reads either set, but we set both so the meta-row picks
  // the right pill colour (group → source) and renderDualSummary parses the
  // raw envelope on `node.summary` exactly like /home does.
  function buildSummaryNode(node) {
    if (!node) return null;
    const sourceKey = String(node.group || node.source || 'web').toLowerCase();
    const label = (SOURCE_LABEL && SOURCE_LABEL[sourceKey]) || sourceKey;
    return {
      id: node.id,
      title: node.name || node.title || 'Untitled',
      source: sourceKey,
      group: sourceKey,
      sourceLabel: label,
      date: node.date || null,
      url: toSafeHttpUrl(node.url) || node.url || '',
      tags: Array.isArray(node.tags) ? node.tags : [],
      summary: node.summary || '',
      description: node.description || ''
    };
  }

  // ---- DOM refs ----
  const container = document.getElementById('graph-container');
  const searchInput = document.getElementById('search-input');
  const filterBtn = document.getElementById('filter-btn');
  const filterDropdown = document.getElementById('filter-dropdown');
  const sidePanel = document.getElementById('side-panel');
  const panelClose = document.getElementById('panel-close');
  const statsEl = document.getElementById('graph-stats');

  // ---- URL params ----
  const urlParams = new URLSearchParams(window.location.search);
  const spotlightId = urlParams.get('node'); // e.g. ?node=yt-attention

  // ---- State ----
  let graphData = { nodes: [], links: [] };
  let fullData = { nodes: [], links: [] };
  let graph = null;
  let selectedNode = null;
  let panelHideTimer = null;
  let highlightNodes = new Set();
  let hoverNode = null;
  let activeSources = new Set();      // populated after first /api/graph response
  let activeKastens = new Set();      // populated when user picks any
  let activeTags = new Set();         // populated when user picks any tag
  let kastenMembership = new Map();   // sandboxId -> Set<nodeId>; lazy-loaded
  let kastenList = [];                // [{id, name, member_count}, ...]
  let knownSources = new Set();       // union of COLORS keys + groups present in data
  let userOwnedIds = new Set();       // node IDs owned by logged-in user (Personal scope)
  // F7: precomputed Set of node IDs that share at least one link with a
  // user-owned node. Rebuilt on `userOwnedIds` change OR `fullData` change.
  // Per-click computeAddBtnState becomes O(1) instead of O(links).
  let _addableInGlobal = new Set();
  let currentView = 'global'; // 'global' or 'my'
  let isLoggedIn = false;
  let authToken = null;
  // LD-1: default min strength = 0.30 (slider minimum, weak bucket).
  let minStrength = DEFAULT_MIN_STRENGTH;
  let activeBucket = 'weak'; // LD-1: default permissive bucket
  // X6: deep-link `?node=<id>` consumed by graph.onEngineStop once the
  // force layout settles. `_didDeepLinkFocus` debounces so a second
  // engine-stop (e.g. after slider-driven reheat) doesn't re-focus.
  let _pendingFocusId = null;
  let _didDeepLinkFocus = false;

  // Module-level handle so the top-level click / background-click handlers
  // (which sit outside initGraph's closure) can sync-paint the title
  // overlay without waiting a frame for the rAF loop. initGraph rebinds
  // this once the real _updateActiveLabel is defined inside its scope.
  let _syncTitleOverlay = function () {};
  const longDateFormatter = new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  });

  // ---- Auth helpers ----
  // Y2 (T4.8): scope the sb-*-auth-token discovery to the CURRENT Supabase
  // project ref so a stale token from a different project (e.g. left over from
  // a tenant migration) never gets sent. Resolved from /api/auth/config; until
  // it loads, only the explicit `zk-auth-token` key is honoured.
  let _expectedProjectRef = null;
  async function _loadExpectedProjectRef() {
    try {
      const r = await zkFetch('/api/auth/config');
      if (!r.ok) return;
      const { supabase_url } = await r.json();
      if (!supabase_url) return;
      const m = String(supabase_url).match(/^https?:\/\/([^.]+)\.supabase\.co/);
      if (m) _expectedProjectRef = m[1];
    } catch (e) { /* ignore */ }
  }

  function getStoredAuthToken() {
    // Production stores the JWT under `zk-auth-token` (set by user_auth feature).
    // The Supabase-style `sb-<projectRef>-auth-token` is a fallback, but is now
    // SCOPED to the current project ref (Y2): no broad sb-*-auth-token scan.
    try {
      const direct = localStorage.getItem('zk-auth-token');
      if (direct) {
        const parsed = JSON.parse(direct);
        if (parsed && parsed.access_token) return parsed.access_token;
      }
    } catch (e) { /* ignore */ }
    if (_expectedProjectRef) {
      try {
        const key = 'sb-' + _expectedProjectRef + '-auth-token';
        const raw = localStorage.getItem(key);
        if (raw) {
          const data = JSON.parse(raw);
          if (data && data.access_token) return data.access_token;
        }
      } catch (e) { /* ignore */ }
    }
    return null;
  }

  function authHeaders() {
    const token = getStoredAuthToken();
    return token ? { 'Authorization': 'Bearer ' + token } : {};
  }

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
    // Direct modal toggle if it's already in the DOM.
    const modal = document.getElementById('login-modal');
    if (modal) { modal.classList.add('open'); return; }
    // Last-resort: bounce to landing page (where the modal lives) with a
    // return-to so the user lands back on KG after sign-in. The KG header
    // partial does NOT carry the login modal, so without this fallback the
    // greyed Personal/Kastens click would silently no-op.
    const ret = encodeURIComponent(location.pathname + location.search + location.hash);
    location.href = '/?auth=login&return=' + ret;
  }

  // X3 (T4.11): explicit two-stage view state machine.
  //   pendingView = what localStorage says the user wanted last session
  //   currentView = what we render right now (always 'global' on boot so the
  //                 page is never broken for an anon user)
  // We transition to 'my' ONLY after /api/me confirms login. The previous
  // single-variable dance ("tentatively global; flip after login confirm")
  // was the source of subtle restore bugs (a flicker of 'my' before the
  // auth resolver rejected, leaving the UI in a half-state).
  const pendingView = localStorage.getItem(STORAGE_KEY_VIEW);
  setViewBtns(currentView);

  authToken = getStoredAuthToken();
  if (authToken) {
    zkFetch('/api/me', { headers: { 'Authorization': 'Bearer ' + authToken } })
      .then(r => r.ok ? r.json() : Promise.reject('not logged in'))
      .then(profile => {
        // Y3 (T4.9): jwt_fallback means the v2 core.profiles lookup failed; the
        // display fields come from JWT claims, not the DB row, so avatar/name
        // edits may not round-trip. Console-only — no UI banner, by spec.
        if (profile && profile.profile_source === 'jwt_fallback') {
          console.warn('Y3: profile loaded from JWT fallback; v2 lookup failed');
        }
        isLoggedIn = true;
        setPersonalEnabled(true);
        loadKastens();
        loadUserOwnedIds();
        refreshOpenPanelAddBtn();
        if (pendingView === 'my') {
          currentView = 'my';
          setViewBtns('my');
          // M2 (Phase 4 / X3 follow-up): the anon load that ran first may
          // have already consumed a `?node=<id>` deep-link spotlight,
          // leaving _didDeepLinkFocus=true, selectedNode pointing at an
          // anon-graph node object, and _activeNodeIds populated with that
          // id. The personal-view load returns a DIFFERENT node set
          // (workspace-scoped), so all of those references go stale.
          // Reset before re-fetching so onEngineStop re-runs the
          // settle-focus path against the new graph and stale node refs
          // can be GC'd. Preserves the spotlight id in _pendingFocusId so
          // the focus actually re-applies to the personal graph if the
          // canonical id is present there.
          _didDeepLinkFocus = false;
          if (spotlightId) _pendingFocusId = spotlightId;
          selectedNode = null;
          _activeNodeIds.clear();
          loadGraphData();
        }
      })
      .catch(() => { isLoggedIn = false; authToken = null; setPersonalEnabled(false); });
  } else {
    setPersonalEnabled(false);
  }

  // Fetch the set of node IDs the user owns (their Personal scope).
  // Used in Global view to gate the Add-to-Kasten button: a node is only
  // addable when it itself is user-owned OR shares a link with a user-owned
  // node — i.e. the user has earned visibility into it through their graph.
  function loadUserOwnedIds() {
    // Part B hard-401: view=my now returns 401 for unauthenticated users
    // (not the old 200-empty). A 401 here means the user is logged out
    // (never-authenticated path); a genuinely-expired session fires the
    // zk_fetch 401->refresh->banner pipeline first and may retry.
    // Either way, on any non-OK (including 401), degrade to an empty set
    // without breaking the page. The Personal toggle is already greyed for
    // logged-out users so userOwnedIds=empty is the correct steady state.
    zkFetch('/api/graph?view=my', { headers: authHeaders() })
      .then(r => {
        if (r.status === 401) return null;  // logged-out: empty set, no throw
        return r.ok ? r.json() : Promise.reject('user-graph');
      })
      .then(data => {
        if (!data) return;  // 401 degraded path: leave userOwnedIds empty
        userOwnedIds = new Set((data.nodes || []).map(n => n.id));
        _rebuildAddableSet();
        refreshOpenPanelAddBtn();
      })
      .catch(() => { /* leave empty; gating will treat all nodes as not-addable */ });
  }

  // F7: precompute the addable-neighbor set in O(links) once per
  // userOwnedIds-change or fullData-change. Then computeAddBtnState is O(1).
  function _rebuildAddableSet() {
    _addableInGlobal = new Set();
    if (!isLoggedIn || userOwnedIds.size === 0) return;
    const links = (fullData && fullData.links) ? fullData.links : [];
    for (let i = 0; i < links.length; i++) {
      const l = links[i];
      const s = typeof l.source === 'object' ? l.source.id : l.source;
      const t = typeof l.target === 'object' ? l.target.id : l.target;
      if (userOwnedIds.has(s)) _addableInGlobal.add(t);
      if (userOwnedIds.has(t)) _addableInGlobal.add(s);
    }
  }

  // Decide whether the Add-to-Kasten button is enabled / disabled / login.
  // Called from openPanel() each time a node is selected.
  function computeAddBtnState(node) {
    if (!isLoggedIn) return 'login';
    if (currentView === 'my') return 'enabled';
    if (userOwnedIds.has(node.id)) return 'enabled';
    // F7: O(1) lookup against precomputed addable set (was O(links) scan).
    return _addableInGlobal.has(node.id) ? 'enabled' : 'unlinked';
  }

  // Apply Add-to-Kasten button state for the currently-open panel node.
  // Extracted so it can be re-run when isLoggedIn / userOwnedIds change
  // asynchronously after the panel is already open (avoids a race where the
  // panel was opened before /api/me resolved and stays in 'login' state).
  function _applyAddBtnState(node) {
    const addBtn = document.getElementById('panel-add-kasten');
    if (!addBtn || !node) return;
    const state = computeAddBtnState(node);
    addBtn.classList.toggle('disabled-soft', state !== 'enabled');
    if (state === 'login') {
      addBtn.setAttribute('aria-disabled', 'true');
      addBtn.title = 'Sign in to add to a Kasten';
    } else if (state === 'unlinked') {
      addBtn.setAttribute('aria-disabled', 'true');
      addBtn.title = 'Connect this to one of your zettels to add it to a Kasten';
    } else {
      addBtn.removeAttribute('aria-disabled');
      addBtn.title = 'Add to a Kasten';
    }
    addBtn.onclick = () => {
      const liveState = computeAddBtnState(node); // recompute at click time
      if (liveState === 'login') { openLoginModalFromKG(); return; }
      if (liveState === 'unlinked') { showToast(addBtn.title); return; }
      if (window.kgKastenModal) {
        window.kgKastenModal.open(node, kastenList, authHeaders, () => loadKastens());
      }
    };
  }

  // If the panel is currently open, re-apply its Add-to-Kasten state. Called
  // after auth confirms or userOwnedIds populates so the button flips from
  // "Sign in" → enabled / unlinked the moment the data lands.
  function refreshOpenPanelAddBtn() {
    if (!_currentPanelNodeId) return;
    const node = (graphData.nodes || []).find(n => n.id === _currentPanelNodeId);
    if (node) _applyAddBtnState(node);
  }

  // Lightweight transient toast — used for the "Connect this to your zettels"
  // hint when Add-to-Kasten is blocked by the connection gate. Mirrors the
  // toast shape kasten_modal.js uses on success so styling is consistent.
  function showToast(text) {
    let t = document.querySelector('.kg-toast');
    if (!t) { t = document.createElement('div'); t.className = 'kg-toast'; document.body.appendChild(t); }
    t.textContent = text;
    requestAnimationFrame(() => t.classList.add('visible'));
    setTimeout(() => t.classList.remove('visible'), 2400);
    setTimeout(() => { if (t.parentNode) t.parentNode.removeChild(t); }, 2900);
  }

  // Part B Phase 1: undo toast for the Make-private / Make-public toggle.
  // Extends showToast with an "Undo?" clickable action link. Teal, never purple.
  // onUndo is called when the user clicks "Undo?"; the toast auto-hides either
  // way after 4 s. Creates a fresh element so multiple rapid toggles each get
  // their own toast (no race with the simple kg-toast singleton).
  function showPrivacyUndoToast(text, onUndo) {
    var t = document.createElement('div');
    t.className = 'kg-toast';
    t.style.cssText = 'display:flex;align-items:center;gap:0.5em;';
    var msg = document.createElement('span');
    msg.textContent = text.replace('Undo?', '').trim();
    var undo = document.createElement('button');
    undo.textContent = 'Undo';
    undo.style.cssText = 'background:none;border:none;color:#14b8a6;cursor:pointer;font:inherit;padding:0;text-decoration:underline;';
    var _dismissed = false;
    undo.addEventListener('click', function () {
      if (_dismissed) return;
      _dismissed = true;
      t.classList.remove('visible');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 450);
      if (typeof onUndo === 'function') onUndo();
    });
    t.appendChild(msg);
    t.appendChild(undo);
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('visible'); });
    setTimeout(function () { t.classList.remove('visible'); }, 4000);
    setTimeout(function () { _dismissed = true; if (t.parentNode) t.parentNode.removeChild(t); }, 4500);
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

  // A4: keep the Personal toggle + isLoggedIn in sync with live auth state.
  // SYNCHRONOUS callback only — no await inside onAuthStateChange (Navigator
  // Locks deadlock, supabase-js #2013). The reauth banner itself is owned by
  // zk_fetch.js / auth-core.js; this only fixes the toggle + empty-graph UX.
  if (window.ZKAuth && typeof window.ZKAuth.onAuthStateChange === 'function') {
    window.ZKAuth.onAuthStateChange(function (event, session) {
      const decision = authChangeDecision(event, !!(session && session.user), currentView);
      if (!decision) return;
      isLoggedIn = decision.isLoggedIn;
      // Boot-state bookkeeping only: per-request fetches re-read the token via
      // authHeaders()/getStoredAuthToken(); kept honest for any future reader.
      authToken = decision.isLoggedIn ? getStoredAuthToken() : null;
      setPersonalEnabled(decision.personalEnabled);
      if (decision.switchToGlobal) {
        currentView = 'global';
        localStorage.setItem(STORAGE_KEY_VIEW, 'global');
        setViewBtns('global');
        loadGraphData();
      }
    });
  }

  // ---- Smart label shortening ----
  const SEP = ' \u2014 '; // " — "
  const LEAD_FILLER = new Set(['the', 'a', 'an', 'my', 'why', 'how', 'what']);
  const TAIL_FILLER = new Set([
    'of', 'at', 'is', 'for', 'in', 'the', 'a', 'an', 'that', 'with',
    'and', 'or', 'to', 'by', 'on', 'as', 'after', 'before', 'from'
  ]);

  function _wrapTitle(name, softMax) {
    if (name.length <= softMax) return name;
    // Prefer breaking at the LAST whitespace BEFORE softMax (avoids overlong first line).
    const beforeIdx = name.lastIndexOf(' ', softMax);
    if (beforeIdx > 0) {
      return name.slice(0, beforeIdx) + '\n' + name.slice(beforeIdx + 1);
    }
    // Fallback: first whitespace AFTER softMax — never break mid-word.
    const afterIdx = name.indexOf(' ', softMax);
    if (afterIdx === -1) return name;
    return name.slice(0, afterIdx) + '\n' + name.slice(afterIdx + 1);
  }

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

  // ---- Node degree (connection count) for sizing ----
  function computeDegrees(data) {
    const deg = {};
    data.nodes.forEach(n => { deg[n.id] = 0; });
    data.links.forEach(l => {
      const s = typeof l.source === 'object' ? l.source.id : l.source;
      const t = typeof l.target === 'object' ? l.target.id : l.target;
      deg[s] = (deg[s] || 0) + 1;
      deg[t] = (deg[t] || 0) + 1;
    });
    return deg;
  }

  // ---- Shared geometry — ONE allocation for every node ----
  const _sphereGeo = new THREE.SphereGeometry(1, 48, 48);
  const _matCache = {};

  // Ring sprite texture (billboard — always faces camera)
  (function () {
    var s = 256, c = document.createElement('canvas');
    c.width = s; c.height = s;
    var ctx = c.getContext('2d'), h = s / 2;
    ctx.clearRect(0, 0, s, s);
    ctx.beginPath();
    ctx.arc(h, h, h * 0.94, 0, Math.PI * 2);
    ctx.arc(h, h, h * 0.76, 0, Math.PI * 2, true);
    ctx.closePath();
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    _matCache['_ringTex'] = new THREE.CanvasTexture(c);
  })();

  function getSphereMat(hexColor, dim) {
    const key = hexColor + (dim ? '_d' : '');
    if (!_matCache[key]) {
      _matCache[key] = new THREE.MeshBasicMaterial({
        color: hexColor,
        transparent: dim,
        opacity: dim ? 0.12 : 1.0,
        depthWrite: !dim
      });
    }
    return _matCache[key];
  }

  let nodeDegrees = {};
  const _activeNodeIds = new Set();
  let _maxPagerank = 0;
  // O(1) id → node lookup. Used by .linkDirectionalParticleColor so we
  // can colour each flowing particle by its SOURCE node's group even
  // when the link's `.source` field is still a string ID (the case at
  // particle-creation time before d3-force resolves it to the node
  // object). Refreshed every time fullData/graphData is rebuilt.
  let _nodeById = new Map();

  // ---- Load data ----
  function loadGraphData() {
    const _kgLoadT0 = (window.performance && performance.now) ? performance.now() : Date.now();
    showOverlay('overlay-loading');
    hideOverlay('overlay-empty');
    hideOverlay('overlay-error');
    // Build /api/graph URL with `view` and `min_strength` (D-KG-6: the
    // server uses min_strength as part of its 30s cache key, so passing it
    // pre-filters payload AND keeps cache-key alignment with the client cull).
    const apiUrl = buildGraphApiUrl(currentView, minStrength);
    zkFetch(apiUrl, { headers: headersForView(currentView, authHeaders) })
      .then(function (r) { return r.ok ? r.json() : Promise.reject('api'); })
      .catch(function () { return fetch('/kg/content/graph.json').then(function (r) { return r.json(); }); })
      .then(data => {
        // F1: clear the slider's is-loading state as soon as the server response lands.
        const sliderWrap = document.querySelector('.kg-strength-slider-wrap');
        if (sliderWrap) sliderWrap.classList.remove('is-loading');
        fullData = data;
        try {
          const _ms = ((window.performance && performance.now) ? performance.now() : Date.now()) - _kgLoadT0;
          let _bytes;
          try { _bytes = new Blob([JSON.stringify(data)]).size; }
          catch (_e) { _bytes = JSON.stringify(data).length; }
          console.log(formatGraphLoadMetric({ bytes: _bytes, ms: _ms, nodes: (data.nodes || []).length }));
        } catch (_e) { /* metric must never break the load path */ }
        fullData.nodes = (fullData.nodes || []).map(node => {
          node.group = normalizeGroup(node.group);
          // I1: seed the in-memory privacy flag the make-private toggle reads
          // from the API's is_private field (Personal-view nodes now carry it).
          node._isPrivate = !!node.is_private;
          return node;
        });
        // F8: shallow-clone instead of JSON round-trip. ForceGraph mutates
        // node.x/y/z/vx/vy/vz on its OWN objects, so a per-element spread is
        // enough isolation. Saves ~10MB GC churn on 5k-node fetches and
        // halves the .then() latency on the cold-load path.
        graphData = {
          nodes: (data.nodes || []).map(n => ({ ...n })),
          links: (data.links || []).map(l => ({ ...l })),
        };
        graphData.nodes = (graphData.nodes || []).map(node => {
          node.group = normalizeGroup(node.group);
          // I1: same privacy-flag seed on the ForceGraph-rendered node objects
          // (these are the ones handleNodeClick -> panel toggle receives).
          node._isPrivate = !!node.is_private;
          return node;
        });
        nodeDegrees = computeDegrees(fullData);
        // Rebuild the id-keyed lookup every time fullData changes — the
        // particle colour accessor reads from this Map to colour each
        // flowing dot by its source node's group regardless of whether
        // d3-force has resolved link.source from string to object yet.
        _nodeById = new Map((fullData.nodes || []).map(n => [n.id, n]));
        // F7: refresh the addable-neighbor set when fullData changes.
        _rebuildAddableSet();
        // A2: surface analytics degradation as a teal banner.
        try {
          const banner = document.getElementById('kg-analytics-banner');
          const louvainFallback = data && data.meta && data.meta.louvain_fallback;
          const analyticsFailed = data && data.meta && data.meta.analytics_status === 'failed';
          if (banner) {
            if (analyticsFailed) {
              banner.textContent = 'Community detection unavailable — coloring by source.';
              banner.classList.remove('hidden');
            } else if (louvainFallback) {
              banner.textContent = 'Community detection degraded — using fallback hue.';
              banner.classList.remove('hidden');
            } else {
              banner.classList.add('hidden');
            }
          }
        } catch (_e) { /* non-fatal */ }
        _maxPagerank = Math.max(...(fullData.nodes || []).map(n => n.pagerank || 0), 0.001);
        // Seed source filter from union of known + observed groups.
        const observed = new Set((fullData.nodes || []).map(n => normalizeGroup(n.group)));
        knownSources = new Set([...Object.keys(COLORS), ...observed]);
        // First load: enable all sources by default.
        if (activeSources.size === 0) {
          knownSources.forEach(s => activeSources.add(s));
        }
        renderSourceSection();
        renderTagsSection();
        if (graph) {
          // Re-apply active filters
          applyFilters();
        } else {
          initGraph();
          updateStats();
        }
        // Part B 1.6: empty-community overlay (global + 0 server nodes). Applied
        // AFTER applyFilters/initGraph so the filter empty-state can't overwrite
        // it; only the global view triggers it (communityEmptyState gates on view).
        var _ce = communityEmptyState(currentView, (data.nodes || []).length);
        if (_ce.show) showOverlay('overlay-empty', _ce.text);
        hideOverlay('overlay-loading');
        // X6: deep-link `?node=<id>` is now wired through `graph.onEngineStop`
        // (inside initGraph) so the focus fires precisely when the force
        // layout settles — instead of the previous 1200 ms blind setTimeout
        // that fired regardless of whether layout had actually converged.
        try {
          const params = new URLSearchParams(window.location.search);
          const focusId = params.get('node');
          if (focusId) {
            _pendingFocusId = focusId;
          }
        } catch (e) { /* non-fatal */ }
      })
      .catch(err => {
        // F1: clear is-loading on error too, so the slider doesn't stay greyed out.
        const sliderWrap = document.querySelector('.kg-strength-slider-wrap');
        if (sliderWrap) sliderWrap.classList.remove('is-loading');
        console.error('Failed to load graph data:', err);
        hideOverlay('overlay-loading');
        showOverlay('overlay-error', 'Could not load graph data.');
        if (statsEl) statsEl.textContent = 'Failed to load data';
      });
  }

  // Initial load — gated on both the source-type registry and the expected
  // Supabase project ref being resolved (Phase 4 / Tasks 4.1 + 4.8). Both
  // promises swallow errors internally, so a network failure on either does
  // NOT block the load — defaults (seeded maps) and direct-key auth still
  // work without /api/auth/config.
  Promise.all([_loadExpectedProjectRef(), _registryReady]).then(() => loadGraphData());

  // ---- In-place node visual update (avoids full rebuild flicker) ----
  function _updateNodeVisual(node) {
    const obj = node.__threeObj;
    if (!obj || !obj.children) return;

    const color = COLORS_INT[node.group] || 0x888888;
    const isSelected = selectedNode && selectedNode.id === node.id;
    const isHovered = hoverNode && hoverNode.id === node.id;
    const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
    const isActive = isSelected || isHovered;
    const dim = !isHighlighted;

    const deg = nodeDegrees[node.id] || 1;
    const isSpotlight = spotlightId && spotlightId === node.id;
    let baseRadius;
    if (node.pagerank !== undefined && _maxPagerank > 0) {
      baseRadius = 2 + (node.pagerank / _maxPagerank) * 4;
    } else {
      baseRadius = Math.min(2 + deg * 0.3, 5);
    }
    const radius = isActive ? baseRadius + 1 : (isSpotlight ? baseRadius + 0.5 : baseRadius);

    for (let i = 0; i < obj.children.length; i++) {
      const child = obj.children[i];

      // Update sphere mesh scale + material
      if (child.isMesh) {
        child.scale.setScalar(radius);
        child.material = getSphereMat(color, dim);
      }

      // Update text label
      if (child.__isLabel) {
        // CRITICAL: re-assert sprite.visible against the CURRENT winner
        // state. onBeforeRender (set in nodeThreeObject) flips
        // sprite.visible = !nodeIsWinner every render frame — BUT once
        // sprite.visible goes false, Three.js culls the sprite and stops
        // calling its onBeforeRender entirely. So a sprite that became
        // hidden because its node was hovered NEVER re-emerges when the
        // node un-hovers, because there's no callback left to flip it
        // back. The symptom: hover a node → move cursor away → that
        // node's title is gone forever (until reset). Fix: re-set
        // .visible HERE on every _updateNodeVisual call, which fires
        // from both hover-in AND hover-out paths.
        const _winnerForVis = hoverNode || selectedNode;
        const _isWinnerForVis = _winnerForVis && _winnerForVis.id === node.id;
        child.visible = !_isWinnerForVis;

        const label = isActive ? _wrapTitle(node.name || '', 32) : getShortLabel(node);
        if (child.text !== label) child.text = label;
        // Offset 5 (was 3) keeps the title clearly below the sphere bottom
        // edge even when the sphere grows under hover/PageRank boost. The 3
        // unit gap was tight enough that the sphere edge cut into the top
        // of the text glyphs at certain camera angles.
        child.position.set(0, -(radius + 5), 0);

        if (isActive) {
          child.color = '#ffffff';
          child.fontWeight = '700';
          child.fontSize = 120;
          child.textHeight = 2.4;
          child.backgroundColor = 'rgba(8, 12, 24, 0.92)';
          child.strokeColor = 'rgba(0, 0, 0, 0.6)';
          child.strokeWidth = 0.04;
          child.padding = 1.4;
          child.borderWidth = 0.08;
          child.borderColor = 'rgba(255, 255, 255, 0.18)';
          child.borderRadius = 0.8;
        } else {
          // Reset EVERY active-state property to its default — earlier
          // versions skipped fontSize / textHeight / borderColor, leaving
          // the sprite stuck at the bigger 120 px / textHeight 2.4 / 18 %
          // border even after the node de-activated. That manifested as a
          // ghostly "big title in dim color" stuck below previously-clicked
          // nodes. Reset matches the construction-time defaults in
          // nodeThreeObject.
          child.color = isHighlighted ? 'rgba(210, 216, 228, 0.78)' : 'rgba(200, 208, 220, 0.35)';
          child.fontWeight = '600';
          child.fontSize = 90;
          child.textHeight = 1.8;
          child.backgroundColor = false;
          child.strokeColor = '';
          child.strokeWidth = 0;
          child.padding = 0;
          child.borderWidth = 0;
          child.borderColor = '';
        }
      }
    }
  }

  // Batch update all visible nodes (used for search/filter highlight changes)
  function _refreshAllNodeVisuals() {
    graphData.nodes.forEach(n => _updateNodeVisual(n));
  }

  // ---- 3D Graph ----
  function initGraph() {
    // useWebWorker:true offloads the d3 force layout to a Web Worker so the
    // main thread stays free for camera + label updates. ~3× smoother on
    // large graphs (>500 nodes).
    graph = new ForceGraph3D(container, { useWebWorker: true })
      .graphData(graphData)
      .backgroundColor('#06060f')
      .showNavInfo(false)

      // ---- Node: degree-scaled sphere + short text label ----
      .nodeThreeObject(node => {
        const group = new THREE.Group();
        const color = COLORS_INT[node.group] || 0x888888;

        const isSelected = selectedNode && selectedNode.id === node.id;
        const isHovered = hoverNode && hoverNode.id === node.id;
        const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
        const isActive = isSelected || isHovered;
        const dim = !isHighlighted;

        // PageRank-based radius (if available), fallback to degree-based
        const deg = nodeDegrees[node.id] || 1;
        const isSpotlight = spotlightId && spotlightId === node.id;
        let baseRadius;
        if (node.pagerank !== undefined && _maxPagerank > 0) {
          baseRadius = 2 + (node.pagerank / _maxPagerank) * 4;
        } else {
          baseRadius = Math.min(2 + deg * 0.3, 5);
        }
        const radius = isActive ? baseRadius + 1 : (isSpotlight ? baseRadius + 0.5 : baseRadius);
        const mesh = new THREE.Mesh(_sphereGeo, getSphereMat(color, dim));
        mesh.scale.setScalar(radius);
        group.add(mesh);

        // Spotlight ring — restored to the original sprite-based glow
        // (operator pref: "elegant" version). Sprite billboards for free
        // against the camera, ring texture pre-rendered into _matCache as
        // '_ringTex' near the top of the IIFE. Color is darkened 35% so it
        // reads as an outer halo, not a copy of the node.
        if (isSpotlight) {
          const ringKey = 'ringSpr_' + color;
          if (!_matCache[ringKey]) {
            _matCache[ringKey] = new THREE.SpriteMaterial({
              map: _matCache['_ringTex'],
              color: new THREE.Color(color).multiplyScalar(0.65),
              transparent: true,
              opacity: 0.8,
              depthWrite: false
            });
          }
          const ring = new THREE.Sprite(_matCache[ringKey]);
          ring.scale.set(radius * 3, radius * 3, 1);
          ring.__isRing = true;
          ring.__nodeRadius = radius;
          group.add(ring);
        }

        // Text label — high-DPI canvas (fontSize 120 px) scaled down to
        // textHeight world-units gives crisp edges at any zoom. strokeWidth
        // is a fraction of fontSize in SpriteText — keep it ≤ 0.06 or
        // adjacent letters' strokes merge and the title looks garbled.
        const label = isActive ? _wrapTitle(node.name || '', 32) : getShortLabel(node);
        const sprite = new SpriteText(label);
        sprite.fontFace = 'Inter, -apple-system, sans-serif';
        sprite.fontWeight = '600';
        sprite.fontSize = isActive ? 120 : 90;
        sprite.textHeight = isActive ? 2.4 : 1.8;
        sprite.__isLabel = true;

        if (isActive) {
          sprite.color = '#ffffff';
          sprite.fontWeight = '700';
          sprite.backgroundColor = 'rgba(8, 12, 24, 0.92)';
          sprite.strokeColor = 'rgba(0, 0, 0, 0.6)';
          sprite.strokeWidth = 0.04;
          sprite.padding = 1.4;
          sprite.borderWidth = 0.08;
          sprite.borderColor = 'rgba(255, 255, 255, 0.18)';
          sprite.borderRadius = 0.8;
        } else {
          sprite.color = isHighlighted ? 'rgba(210, 216, 228, 0.78)' : 'rgba(200, 208, 220, 0.35)';
          sprite.backgroundColor = false;
          sprite.padding = 0;
        }
        sprite.position.set(0, -(radius + 5), 0);
        // Always render the title sprite on top of the sphere, regardless
        // of camera angle. Without these the sphere geometry occluded the
        // top of the text glyphs whenever the camera dipped or the node
        // grew under hover. depthTest=false + renderOrder bump = sprite
        // always wins the z-fight. Visual cost is minimal because spheres
        // are small relative to the canvas and rarely overlap a sprite's
        // narrow column.
        if (sprite.material) {
          sprite.material.depthTest = false;
          sprite.material.depthWrite = false;
        }
        sprite.renderOrder = 1;
        group.add(sprite);

        // F4: per-sprite onBeforeRender clamps scale only when the sprite is
        // about to render. Replaces the 60Hz O(N) rAF loop that scanned every
        // node every frame. The renderer calls this with the active camera,
        // so we get correct frustum-culled behavior for free.
        sprite.onBeforeRender = function (renderer, scene, cam) {
          if (!cam) return;
          if (sprite.__origSy === undefined) {
            sprite.__origSy = sprite.scale.y;
            sprite.__origSx = sprite.scale.x;
          }
          // Title-overlay precedence: hover wins over selection (operator
          // approved). The HTML overlay shows the WINNER's big title — so
          // ONLY the winner's sprite is hidden. The losing-selected node
          // falls back to its small sprite label until the cursor leaves.
          var winner = hoverNode || selectedNode;
          var nodeIsWinner = winner && winner.id === node.id;
          sprite.visible = !nodeIsWinner;
          var worldPos = new THREE.Vector3();
          sprite.getWorldPosition(worldPos);
          var dist = cam.position.distanceTo(worldPos);
          var maxH = dist * 0.025;  // matches old MAX_LABEL_FRAC
          if (sprite.__origSy > maxH && maxH > 0) {
            var r = maxH / sprite.__origSy;
            sprite.scale.set(sprite.__origSx * r, sprite.__origSy * r, 1);
          } else {
            sprite.scale.set(sprite.__origSx, sprite.__origSy, 1);
          }
        };

        return group;
      })
      .nodeThreeObjectExtend(false)

      // ---- Link rendering: blue base — operator-pref UI revert (matches mobile/js/graph.js). ----
      .linkColor(link => {
        const src = typeof link.source === 'object' ? link.source : null;
        if (src && hoverNode && (src.id === hoverNode.id || (typeof link.target === 'object' && link.target.id === hoverNode.id))) {
          return COLORS[src.group] || 'rgba(160, 180, 240, 0.8)';
        }
        return 'rgba(100, 130, 200, 0.25)';
      })
      // linkWidth / linkOpacity — restored to the original UNIFORM values
      // from 56701d69 (the elegant baseline). Connection-strength encoding
      // via per-link width / opacity made edges look inconsistent and
      // "sloppy" on a dark background; uniform thin lines with a hover
      // boost is what shipped on day-one and what the operator wants back.
      .linkWidth(link => {
        const src = typeof link.source === 'object' ? link.source : null;
        const tgt = typeof link.target === 'object' ? link.target : null;
        if (hoverNode && ((src && src.id === hoverNode.id) || (tgt && tgt.id === hoverNode.id))) {
          return 1.8;
        }
        return 0.5;
      })
      .linkOpacity(0.6)
      // d3AlphaMin: stop the simulation when α drops below 0.01 (default
      // 0.001). 3× faster settle, no visible quality loss after initial
      // layout. Keeps web-worker idle sooner.
      .d3AlphaMin(0.01)
      .linkCurvature(0.15)
      .linkCurveRotation(0.4)
      // Particles — 1 per link, always flowing. Operator pref: the elegant
      // "alive graph" feel before F5 made them hover-only. Cost is real (1
      // cylinder per link per frame) but visually load-bearing on
      // /knowledge-graph.
      .linkDirectionalParticles(1)
      .linkDirectionalParticleWidth(1.0)
      .linkDirectionalParticleSpeed(0.008)
      .linkDirectionalParticleColor(link => {
        // Resolve source to a node object — d3-force eventually swaps the
        // string id for the actual node, but the particle is created
        // BEFORE that swap and 3d-force-graph bakes the colour into the
        // particle material at creation. So at first call source is a
        // string and we have to look it up. _nodeById is rebuilt on every
        // fullData load.
        let src = link.source;
        if (typeof src !== 'object' || src === null) {
          src = _nodeById.get(src);
        }
        return src && src.group ? (COLORS[src.group] || '#4466aa') : '#4466aa';
      })

      // ---- Interactions ----
      .nodeLabel(() => '')  // disable default HTML tooltip (prevents double-text)
      .onNodeClick(handleNodeClick)
      .onBackgroundClick(handleBackgroundClick)
      .onNodeHover(node => {
        const prevHover = hoverNode;
        const newHover = node || null;
        // Same-state noop: force-graph fires spurious enter/leave events
        // as the sphere moves a sub-pixel under a stationary cursor while
        // the force layout settles or the camera tweens. Without this
        // guard, every wiggle triggers _updateNodeVisual + overlay
        // repaint twice — that thrash is what made the title flicker
        // when the cursor sat on a selected node.
        if (newHover === prevHover) return;
        hoverNode = newHover;
        container.style.cursor = node ? 'pointer' : 'default';
        if (prevHover && prevHover !== node) _updateNodeVisual(prevHover);
        if (node) {
          _activeNodeIds.add(node.id);
          _updateNodeVisual(node);
        } else if (prevHover) {
          _activeNodeIds.delete(prevHover.id);
        }
        // Sync-paint the HTML overlay BEFORE returning to the renderer.
        // Otherwise the next rAF tick is the earliest the overlay can
        // re-project to the new hover target — that 1-frame lag shows up
        // as the old title sticking visibly behind the previous node for
        // ~16 ms when the user moves between nodes quickly.
        _updateActiveLabel();
        // M4 (Phase 4 / KG-UI follow-up): graph.refresh() was removed when
        // particles became always-on (no longer an accessor that needed
        // re-eval). BUT linkWidth IS still an accessor — it returns 1.8
        // for hover-incident links vs 0.5 otherwise — and force-graph-3d
        // caches the per-link Line2 geometry from the previous render.
        // Without refresh() the operator's intended "hover boost on
        // incident edges" is dead. The original flicker concern (full
        // repaint on every wiggle) is now solved by the same-state noop
        // above, so refresh() only fires on real hover transitions.
        graph.refresh();
      })

      // ---- Physics — fast convergence ----
      .d3AlphaDecay(0.025)
      .d3VelocityDecay(0.35)
      .warmupTicks(warmupTicksForNodeCount(graphData.nodes.length))
      .cooldownTime(GRAPH_COOLDOWN_MS)
      // X6: settle-driven deep-link focus replaces the 1200 ms setTimeout.
      // The callback runs the moment the force layout converges, so the
      // camera fly-to has a real layout to aim at — slower graphs no
      // longer fly to half-baked positions, and faster ones don't sit idle.
      .onEngineStop(function () {
        if (_didDeepLinkFocus || !_pendingFocusId) return;
        try {
          const target = (graphData.nodes || []).find(n => n.id === _pendingFocusId);
          if (target) handleNodeClick(target);
        } catch (e) { /* non-fatal */ }
        _didDeepLinkFocus = true;
      });

    // ---- HiDPI sharpness ----
    graph.renderer().setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // ---- Minimal scene — no fog, no starfield, no point lights ----
    // F9: AmbientLight removed. MeshBasicMaterial / SpriteText do not respond
    // to scene lights, so the AmbientLight was a no-op cluttering the scene
    // graph (cost: one extra render-list traversal per frame).

    // Force layout — wider spread, collision avoidance
    graph.d3Force('charge').strength(-200).distanceMax(400);
    graph.d3Force('link').distance(90);

    const d3 = window.d3 || null;
    if (d3 && d3.forceCenter) {
      graph.d3Force('center', d3.forceCenter(0, 0, 0).strength(0.05));
    }

    // ---- Camera ----
    const controls = graph.controls();
    controls.autoRotate = false;
    controls.autoRotateSpeed = 0.1;
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 80;
    controls.maxDistance = 600;

    const stopOrbit = () => { controls.autoRotate = false; };
    container.addEventListener('mousedown', stopOrbit);
    container.addEventListener('touchstart', stopOrbit);

    // Spotlight (?node=<id>) handling. Operator-approved behaviour:
    // treat the URL spotlight as a "pre-selection" — the big HTML title
    // overlay must appear as soon as the data is in, NOT after the 2.2s
    // camera-fly timer. So:
    //   1. Set selectedNode immediately (rAF overlay picks it up next frame).
    //   2. Repaint the node's sphere via _updateNodeVisual so the active
    //      radius + sprite-hidden state apply right away.
    //   3. Keep the 2.2s defer for the actual camera fly + panel open —
    //      gives the force layout time to settle before the camera moves.
    if (spotlightId) {
      const sNode = graphData.nodes.find(n => n.id === spotlightId);
      if (sNode) {
        selectedNode = sNode;
        _activeNodeIds.add(sNode.id);
        _updateNodeVisual(sNode);
        _syncTitleOverlay();
      }
      setTimeout(() => {
        const stillThere = graphData.nodes.find(n => n.id === spotlightId);
        if (stillThere) {
          handleNodeClick(stillThere);
        } else {
          graph.zoomToFit(1200, 50);
        }
      }, 2200);
    } else {
      setTimeout(() => graph.zoomToFit(1200, 50), 1800);
    }

    window.addEventListener('resize', () => {
      graph.width(window.innerWidth).height(window.innerHeight);
    });

    // F4: per-frame label clamping moved INSIDE the Sprite's onBeforeRender
    // callback (set in nodeThreeObject). Ring billboard-toward-camera also
    // moves to a per-ring onBeforeRender below. The old 60Hz rAF loop that
    // touched every node every frame is gone (replaces the O(N) per-frame
    // scan with O(rendered-visible)).
    //
    // The HTML active-label overlay still needs a rAF, but ONLY when there's
    // a node to update (gated below) — typical idle frames cost nothing.

    // HTML title overlay for selected / hovered node — projects world coords
    // to screen each frame and parks the label just below the node.
    var _activeLabelEl = document.getElementById('kg-active-label');
    var _lastActiveLabelText = '';
    function _updateActiveLabel() {
      if (!_activeLabelEl) return;
      // Hover wins over selection (operator approved). Lets the user
      // preview another node's title without losing the current selection.
      var active = hoverNode || selectedNode;
      if (!active || active.x === undefined) {
        if (!_activeLabelEl.classList.contains('hidden')) {
          _activeLabelEl.classList.add('hidden');
        }
        return;
      }
      var deg = nodeDegrees[active.id] || 1;
      var baseRadius = (active.pagerank !== undefined && _maxPagerank > 0)
        ? 2 + (active.pagerank / _maxPagerank) * 4
        : Math.min(2 + deg * 0.3, 5);
      var anchor = new THREE.Vector3(active.x || 0, (active.y || 0) - (baseRadius + 4.5), active.z || 0);
      var screen = anchor.clone().project(graph.camera());
      // Behind camera → hide.
      if (screen.z > 1) {
        if (!_activeLabelEl.classList.contains('hidden')) {
          _activeLabelEl.classList.add('hidden');
        }
        return;
      }
      var rect = container.getBoundingClientRect();
      var x = (screen.x * 0.5 + 0.5) * rect.width + rect.left;
      var y = (-screen.y * 0.5 + 0.5) * rect.height + rect.top;
      // Sub-pixel smooth (operator approved): toFixed(2) keeps a stable
      // string repr without the 1-pixel snap-jitter Math.round caused
      // during slow diagonal camera motion. translate3d still gives the
      // GPU layer promotion needed for crisp text.
      _activeLabelEl.style.transform =
        'translate(-50%, 0) translate3d(' + x.toFixed(2) + 'px, ' + y.toFixed(2) + 'px, 0)';
      var name = active.name || '';
      if (name !== _lastActiveLabelText) {
        _activeLabelEl.textContent = name;
        _lastActiveLabelText = name;
      }
      if (_activeLabelEl.classList.contains('hidden')) {
        _activeLabelEl.classList.remove('hidden');
      }
    }
    // Expose to module scope so handleNodeClick / handleBackgroundClick
    // can fire the same sync-paint path. Defined LAST so the assignment
    // captures the function declaration above.
    _syncTitleOverlay = _updateActiveLabel;

    // F4: gated active-label rAF — only paints when an active node exists.
    function _updateActiveLabelLoop() {
      requestAnimationFrame(_updateActiveLabelLoop);
      if (!selectedNode && !hoverNode) return;
      _updateActiveLabel();
    }
    requestAnimationFrame(_updateActiveLabelLoop);
  }

  // ---- Node click → centre node, fly to it, then open panel ----
  let _panelOpenTimer = null;

  function handleNodeClick(node) {
    _activeNodeIds.clear();
    if (node) _activeNodeIds.add(node.id);
    const prevSelected = selectedNode;
    selectedNode = node;
    graph.controls().autoRotate = false;
    if (prevSelected && prevSelected !== node) _updateNodeVisual(prevSelected);
    _updateNodeVisual(node);
    // Sync-paint overlay so the title switches on the same frame as the
    // click — without this, the previous selection's overlay lingers
    // for ~16 ms until the next rAF tick.
    _syncTitleOverlay();
    // M4 (Phase 4 / KG-UI follow-up): mirror the onNodeHover refresh().
    // linkWidth's hover-incident branch reads closure-captured `hoverNode`
    // but is also relevant on click (selectedNode shares spotlight intent).
    // Without refresh() the link-mesh widths stay at the previous render.
    // The click path is rate-limited by user input so refresh-on-click is
    // a single repaint per click — no flicker risk.
    graph.refresh();

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

    // Defensive OrbitControls re-enable. 3d-force-graph's cameraPosition
    // tween can leave controls.enabled = false if a SECOND call interrupts
    // an in-flight tween before its onComplete fires (which is what
    // restores .enabled). Symptom: drag-rotate / right-pan / wheel-zoom
    // all dead after the user clicks two nodes back-to-back. We force-
    // restore enabled (a) immediately and (b) at tween-end + 50 ms in
    // case the library disables it again during the new tween.
    const _restoreCtrls = () => {
      const ctrls = graph && typeof graph.controls === 'function' ? graph.controls() : null;
      if (ctrls && ctrls.enabled === false) ctrls.enabled = true;
    };
    _restoreCtrls();
    setTimeout(_restoreCtrls, 1050);

    // Open panel after camera centres (only if not already open).
    if (!panelAlreadyOpen) {
      _panelOpenTimer = setTimeout(() => { openPanel(node); _panelOpenTimer = null; }, 700);
    }
  }

  function handleBackgroundClick() {
    if (_panelOpenTimer) { clearTimeout(_panelOpenTimer); _panelOpenTimer = null; }
    closePanel();
    const prevSelected = selectedNode;
    selectedNode = null;
    _activeNodeIds.clear();
    // Sync-paint the overlay so it disappears the same frame the user
    // clicks empty space — no half-frame lingering title.
    if (prevSelected) _updateNodeVisual(prevSelected);
    _syncTitleOverlay();
    highlightNodes.clear();
    _refreshAllNodeVisuals();
  }

  // ---- Side Panel ----
  let _currentPanelNodeId = null;

  function openPanel(node) {
    const badge = document.getElementById('panel-badge');
    const title = document.getElementById('panel-title');
    const date = document.getElementById('panel-date');
    const summary = document.getElementById('panel-summary');
    const tags = document.getElementById('panel-tags');
    const connections = document.getElementById('panel-connections');
    const summaryBtn = document.getElementById('panel-summary-btn');
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

    summary.textContent = getBrief(node);  // F6: memoized

    // Summary button: opens the shared zk_summary_popup modal with the
    // node payload. Disabled state when ZKSummary isn't loaded yet (defensive).
    if (summaryBtn) {
      if (window.ZKSummary && typeof window.ZKSummary.open === 'function') {
        summaryBtn.removeAttribute('aria-disabled');
        summaryBtn.tabIndex = 0;
        summaryBtn.onclick = function (event) {
          event.preventDefault();
          window.ZKSummary.open(buildSummaryNode(node));
        };
      } else {
        summaryBtn.setAttribute('aria-disabled', 'true');
        summaryBtn.tabIndex = -1;
        summaryBtn.onclick = null;
      }
    }

    // Add-to-Kasten button — three states:
    //   1. Logged out → greyed; click opens login modal directly.
    //   2. Logged in + node addable → enabled; click opens Kasten modal.
    //   3. Logged in + node NOT addable (Global scope, no link to any
    //      user-owned node) → greyed; click shows a transient hint toast.
    //
    // "Addable" means: the user owns the node OR at least one link of the
    // node connects to a node the user owns. This implements the rule
    // "If a single Node connected to their own Zettel, then the user can
    // add that particular Kasten from Global to their own Kasten."
    if (addBtn) {
      _applyAddBtnState(node);
    }

    // Part B Phase 1 — Make-private / Make-public toggle.
    // Only show the button when the selected node is user-owned (reuse
    // userOwnedIds so BOLA is enforced at both the UI gate and the endpoint).
    // No consent modal — the signup notice (Task 1.8) is the consent surface.
    // The endpoint itself enforces ownership; the button is a UX gate only.
    var privacyBtn = document.getElementById('panel-privacy');
    var privateBadge = document.getElementById('panel-private-badge');
    if (privacyBtn) {
      var _isOwned = userOwnedIds.has(node.id);
      if (_isOwned) {
        var _isPrivate = !!(node._isPrivate);  // in-memory state; falsy = public (default)
        var _badge = privacyBadge(_isPrivate);
        // Apply badge visibility.
        if (privateBadge) {
          if (_badge.visible) {
            privateBadge.textContent = _badge.text;
            privateBadge.classList.remove('hidden');
          } else {
            privateBadge.classList.add('hidden');
          }
        }
        // Apply button label + aria-pressed state.
        privacyBtn.setAttribute('aria-pressed', String(_isPrivate));
        privacyBtn.title = privacyToggleLabel(_isPrivate);
        privacyBtn.setAttribute('aria-label', privacyToggleLabel(_isPrivate));
        privacyBtn.classList.remove('hidden');
        // Wire the click handler fresh each time the panel opens so it always
        // closes over the current node reference.
        privacyBtn.onclick = function () {
          var _nowPrivate = !!(node._isPrivate);
          var _endpoint = '/api/zettels/' + node.workspace_zettel_id + (_nowPrivate ? '/public' : '/private');
          // workspace_zettel_id is the per-user overlay id (NOT canonical).
          // The endpoint derives ownership from the Bearer JWT; never trust client sub.
          if (!node.workspace_zettel_id) {
            showToast('Privacy toggle unavailable for this zettel');
            return;
          }
          zkFetch(_endpoint, { method: 'POST', headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (typeof data.is_private !== 'boolean') throw new Error('unexpected');
              // Flip in-memory state on the node.
              node._isPrivate = data.is_private;
              // Update badge.
              var _newBadge = privacyBadge(node._isPrivate);
              if (privateBadge) {
                if (_newBadge.visible) {
                  privateBadge.textContent = _newBadge.text;
                  privateBadge.classList.remove('hidden');
                } else {
                  privateBadge.classList.add('hidden');
                }
              }
              // Update button label + state.
              privacyBtn.setAttribute('aria-pressed', String(node._isPrivate));
              privacyBtn.title = privacyToggleLabel(node._isPrivate);
              privacyBtn.setAttribute('aria-label', privacyToggleLabel(node._isPrivate));
              // Show undo toast — clicking Undo fires the inverse endpoint.
              showPrivacyUndoToast(undoToastText(node._isPrivate), function () {
                var _undoEndpoint = '/api/zettels/' + node.workspace_zettel_id + (node._isPrivate ? '/public' : '/private');
                zkFetch(_undoEndpoint, { method: 'POST', headers: authHeaders() })
                  .then(function (r) { return r.json(); })
                  .then(function (d) {
                    if (typeof d.is_private !== 'boolean') return;
                    node._isPrivate = d.is_private;
                    var _undoBadge = privacyBadge(node._isPrivate);
                    if (privateBadge) {
                      if (_undoBadge.visible) {
                        privateBadge.textContent = _undoBadge.text;
                        privateBadge.classList.remove('hidden');
                      } else { privateBadge.classList.add('hidden'); }
                    }
                    privacyBtn.setAttribute('aria-pressed', String(node._isPrivate));
                    privacyBtn.title = privacyToggleLabel(node._isPrivate);
                    privacyBtn.setAttribute('aria-label', privacyToggleLabel(node._isPrivate));
                    // Refresh the graph so the global view reflects the change.
                    if (currentView === 'global') loadGraphData();
                  })
                  .catch(function (e) { showToast('Undo failed'); });
              });
              // Refresh global view so the change is immediately visible.
              if (currentView === 'global') loadGraphData();
            })
            .catch(function () { showToast('Privacy toggle failed'); });
        };
      } else {
        // Not user-owned — hide button and badge.
        privacyBtn.classList.add('hidden');
        privacyBtn.onclick = null;
        if (privateBadge) privateBadge.classList.add('hidden');
      }
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

    // Connected-notes row: source-coloured dot + title only. The
    // edge.relation chip (rag / embeddings / etc.) is dropped — it
    // duplicated tag noise and crowded the row. Title alone reads
    // cleanly and is what the user actually clicks through to.
    connections.innerHTML = connectedNodes.map(c => `
      <div class="kg-connection" data-id="${escapeHtml(c.node.id || c.node)}">
        <span class="kg-connection-dot" style="background: ${COLORS[c.node.group] || '#888'}"></span>
        <span class="kg-connection-name">${escapeHtml(c.node.name || c.node)}</span>
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

  function closePanel() {
    sidePanel.classList.remove('visible');
    if (panelHideTimer) clearTimeout(panelHideTimer);
    _currentPanelNodeId = null;
    sidePanel.dataset.nodeId = '';
    panelHideTimer = setTimeout(() => { sidePanel.classList.add('hidden'); panelHideTimer = null; }, 350);
  }

  function formatDate(dateStr) {
    const d = new Date(dateStr);
    return Number.isNaN(d.getTime()) ? String(dateStr || '') : longDateFormatter.format(d);
  }

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
        const nodeSummary = getBrief(node);  // F6: memoized
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

  // ---- Reset view ----
  // Restoring to "fresh page load" state: NO selection, NO hover, NO
  // pending camera tween blocking controls, NO stale HTML overlay. The
  // earlier version cleared selectedNode but left hoverNode, _activeNodeIds,
  // and the overlay text in place — and the zoomToFit tween disabled
  // OrbitControls without anyone restoring them (same root cause as the
  // 2nd-click-freezes-controls bug). Net result: view reset, but no
  // further interaction worked. This version drains every state slot and
  // re-asserts controls.enabled.
  const resetViewBtn = document.getElementById('reset-view-btn');
  if (resetViewBtn) {
    resetViewBtn.addEventListener('click', () => {
      if (!graph) return;
      if (_panelOpenTimer) { clearTimeout(_panelOpenTimer); _panelOpenTimer = null; }
      // Clear highlights so all nodes are visible during the fit.
      if (searchInput) searchInput.value = '';
      _applySearch('');
      // Drain ALL active state — selection, hover, the active-ids set.
      const prevSelected = selectedNode;
      const prevHover = hoverNode;
      selectedNode = null;
      hoverNode = null;
      _activeNodeIds.clear();
      highlightNodes.clear();
      // Repaint the two formerly-active spheres (sprite back to small,
      // sphere back to base radius) before the bulk refresh so they don't
      // briefly show stale active styling.
      if (prevSelected) _updateNodeVisual(prevSelected);
      if (prevHover && prevHover !== prevSelected) _updateNodeVisual(prevHover);
      _refreshAllNodeVisuals();
      // Hide the HTML title overlay synchronously — without this, the
      // overlay text lingered for ~16 ms before the rAF loop noticed
      // (selectedNode || hoverNode) had gone null.
      _syncTitleOverlay();
      closePanel();
      // Defensive OrbitControls re-enable, same pattern as handleNodeClick:
      // zoomToFit's 800 ms tween disables controls and only restores them
      // on its own onComplete. If anything interrupts the tween, .enabled
      // stays false and the KG goes dead. Force it back twice — now and
      // at tween-end + 50 ms.
      graph.zoomToFit(800, 60);
      const _restoreCtrls = () => {
        const ctrls = graph && typeof graph.controls === 'function' ? graph.controls() : null;
        if (ctrls && ctrls.enabled === false) ctrls.enabled = true;
      };
      _restoreCtrls();
      setTimeout(_restoreCtrls, 850);
    });
  }

  // ---- Filter (nested "All Filters" menu — mirrors My Zettels) ----
  // Parent rows reveal exclusive flyout submenus; opening the menu shows
  // the Source submenu by default (same as user_zettels.js openSubmenu).
  const filterParents = filterDropdown
    ? filterDropdown.querySelectorAll('.kg-filter-parent[data-submenu]')
    : [];
  const filterClearBtn = document.getElementById('kg-filter-clear');

  function closeFilterSubmenus() {
    if (!filterDropdown) return;
    filterDropdown.querySelectorAll('.kg-filter-submenu').forEach(s => s.classList.remove('open'));
    filterParents.forEach(p => p.classList.remove('active'));
  }

  function openFilterSubmenu(name) {
    if (!filterDropdown) return;
    closeFilterSubmenus();
    const sub = filterDropdown.querySelector('.kg-filter-submenu[data-section="' + name + '"]');
    if (sub) sub.classList.add('open');
    filterParents.forEach(p => {
      if (p.dataset.submenu === name) p.classList.add('active');
    });
  }

  function openFilterMenu() {
    if (!filterDropdown || !filterBtn) return;
    filterDropdown.classList.remove('hidden');
    filterBtn.classList.add('active');
    filterBtn.setAttribute('aria-expanded', 'true');
    openFilterSubmenu('source');
  }

  function closeFilterMenu() {
    if (!filterDropdown || !filterBtn) return;
    filterDropdown.classList.add('hidden');
    filterBtn.classList.remove('active');
    filterBtn.setAttribute('aria-expanded', 'false');
    closeFilterSubmenus();
  }

  if (filterBtn && filterDropdown) {
    filterBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (filterDropdown.classList.contains('hidden')) openFilterMenu();
      else closeFilterMenu();
    });
  }

  filterParents.forEach(parent => {
    const name = parent.dataset.submenu;
    const reveal = () => openFilterSubmenu(name);
    parent.addEventListener('mouseenter', reveal);
    parent.addEventListener('focus', reveal);
    parent.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      reveal();
    });
  });

  if (filterClearBtn) {
    filterClearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      // F10: reset Source (all on), Tags + Kastens (none), and slider to
      // LD-1 weak default (0.30). One fetch + one apply, not two.
      activeSources = new Set([...knownSources]);
      activeTags.clear();
      if (typeof activeKastens !== 'undefined' && activeKastens) activeKastens.clear();
      activeBucket = bucketForStrength(DEFAULT_MIN_STRENGTH) || 'weak';
      minStrength = DEFAULT_MIN_STRENGTH;
      renderSourceSection();
      renderTagsSection();
      renderKastensSection();
      _syncStrengthUI();
      loadGraphData();
    });
  }

  document.addEventListener('click', (e) => {
    if (filterDropdown && filterBtn && !filterDropdown.classList.contains('hidden') &&
        !filterDropdown.contains(e.target) && e.target !== filterBtn && !filterBtn.contains(e.target)) {
      closeFilterMenu();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && filterDropdown && !filterDropdown.classList.contains('hidden')) {
      closeFilterMenu();
    }
  });

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
        _debouncedApplyFilters();
      });
      body.appendChild(lbl);
    });
  }

  // X4 (T4.12): base64url-encode the chip id so the HTML id is collision-free
  // even for tags that differ only by punctuation/whitespace. Encodes via UTF-8
  // (btoa needs latin1) and strips `=` padding to keep the id selector-safe.
  function _tagFilterId(tag) {
    const b64 = btoa(unescape(encodeURIComponent(String(tag))));
    return 'flt-tag-' + b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  }

  // X5 (T4.13): NFKC + lowercase + strip — mirror of website.core.text_polish
  // normalize_tag(). All Set membership for activeTags goes through this
  // helper so visually-identical tags from disparate Unicode forms hash to
  // the same bucket. Defence-in-depth — the server-side write path also
  // normalises before persisting.
  function _normalizeTag(t) {
    return (t == null ? '' : String(t)).normalize('NFKC').trim().toLowerCase();
  }

  function renderTagsSection() {
    const body = document.getElementById('filter-tags-body');
    if (!body) return;
    body.innerHTML = '';
    const allTags = new Set();
    (fullData.nodes || []).forEach(n => {
      (Array.isArray(n.tags) ? n.tags : []).forEach(t => {
        if (t && typeof t === 'string') {
          // X5 (T4.13): normalize on insert so pre-backfill graphs surface a
          // single canonical chip per logical tag (server backfill catches up
          // on the next ingest cycle).
          const norm = _normalizeTag(t);
          if (norm) allTags.add(norm);
        }
      });
    });
    const tags = [...allTags].sort((a, b) => a.localeCompare(b));
    if (tags.length === 0) {
      const p = document.createElement('p');
      p.className = 'kg-filter-empty';
      p.textContent = 'No tags available.';
      body.appendChild(p);
      return;
    }
    tags.forEach(tag => {
      // X4 (T4.12): round-trippable base64url-encoded id avoids the "foo bar"
      // vs "foo_bar" collision the old `[^a-z0-9_-]` sanitizer produced (both
      // mapped to `flt-tag-foo_bar`, so the second chip silently aliased the
      // first checkbox state on toggle).
      const id = _tagFilterId(tag);
      const lbl = document.createElement('label');
      lbl.className = 'kg-filter-item';
      const checked = activeTags.has(tag);
      // Default = no tag filter (size 0). Visual treatment: when activeTags is empty,
      // every tag is "in scope" so don't strikethrough; once user picks any, the
      // unselected ones get the line-through-when-unchecked treatment.
      if (activeTags.size > 0 && !checked) lbl.classList.add('unchecked');
      lbl.innerHTML =
        '<input type="checkbox" id="' + id + '" value="' + escapeHtml(tag) + '"' + (checked ? ' checked' : '') + '>' +
        '<span class="kg-filter-dot" style="background:#14b8a6"></span>' +
        '<span>' + escapeHtml(tag) + '</span>';
      lbl.addEventListener('click', (e) => {
        e.preventDefault();
        if (activeTags.has(tag)) activeTags.delete(tag); else activeTags.add(tag);
        // In-place update of the clicked row only — the global "any tag
        // active" line-through treatment was removed last round, so the
        // sibling re-render is no longer needed. Avoids the O(tags) DOM
        // rebuild that was making the menu feel laggy with many tags.
        const cb = lbl.querySelector('input');
        if (cb) cb.checked = activeTags.has(tag);
        lbl.classList.toggle('unchecked', activeTags.size > 0 && !activeTags.has(tag));
        _debouncedApplyFilters();
      });
      body.appendChild(lbl);
    });
  }

  // Source-type legend — bottom-left "i" popup. Swatches use the real
  // per-source COLORS{} values (the same map the 3D nodes render with);
  // colours are read here, never mutated.
  (function wireLegendPopup() {
    const legendBtn = document.getElementById('kg-legend-btn');
    const legendPopup = document.getElementById('kg-legend-popup');
    const legendList = document.getElementById('kg-legend-list');
    if (!legendBtn || !legendPopup || !legendList) return;

    // De-dupe colours (substack/newsletter share #60A5FA) so the legend
    // lists one row per source label.
    legendList.innerHTML = '';
    Object.keys(SOURCE_LABEL).forEach(src => {
      const row = document.createElement('div');
      row.className = 'kg-legend-row';
      const sw = document.createElement('span');
      sw.className = 'kg-legend-swatch';
      sw.style.background = COLORS[src] || '#888';
      const lbl = document.createElement('span');
      lbl.className = 'kg-legend-label';
      lbl.textContent = SOURCE_LABEL[src] || src;
      row.appendChild(sw);
      row.appendChild(lbl);
      legendList.appendChild(row);
    });

    function openLegend() {
      legendPopup.classList.remove('hidden');
      legendBtn.classList.add('active');
      legendBtn.setAttribute('aria-expanded', 'true');
    }
    function closeLegend() {
      legendPopup.classList.add('hidden');
      legendBtn.classList.remove('active');
      legendBtn.setAttribute('aria-expanded', 'false');
    }
    legendBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (legendPopup.classList.contains('hidden')) openLegend();
      else closeLegend();
    });
    document.addEventListener('click', (e) => {
      if (!legendPopup.classList.contains('hidden') &&
          !legendPopup.contains(e.target) && e.target !== legendBtn && !legendBtn.contains(e.target)) {
        closeLegend();
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !legendPopup.classList.contains('hidden')) closeLegend();
    });
  })();

  // ---- Side-panel collapsible sections (Summary / Tags / Connected Notes) ----
  (function wirePanelSections() {
    const STORAGE_PREFIX = 'kg.panel.collapsed.';
    document.querySelectorAll('.kg-panel-section[data-panel-section]').forEach(section => {
      const key = section.dataset.panelSection;
      const header = section.querySelector('.kg-panel-section-header');
      if (!header) return;
      const storageKey = STORAGE_PREFIX + key;
      // Restore persisted state (default expanded).
      try {
        if (localStorage.getItem(storageKey) === '1') {
          section.classList.add('collapsed');
          header.setAttribute('aria-expanded', 'false');
        } else {
          header.setAttribute('aria-expanded', 'true');
        }
      } catch (_e) {
        header.setAttribute('aria-expanded', 'true');
      }
      const toggle = () => {
        section.classList.toggle('collapsed');
        const collapsed = section.classList.contains('collapsed');
        header.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        try { localStorage.setItem(storageKey, collapsed ? '1' : '0'); } catch (_e) { /* ignore */ }
      };
      header.addEventListener('click', toggle);
      header.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggle();
        }
      });
    });
  })();

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
      if (activeTags.size > 0) {
        const tags = Array.isArray(n.tags) ? n.tags : [];
        // X5 (T4.13): defence-in-depth normalize at lookup so pre-backfill
        // node tags (un-normalised in the wire payload) still match the
        // (now-normalised) chips in activeTags.
        const hit = tags.some(t => activeTags.has(_normalizeTag(t)));
        if (!hit) return false;
      }
      return true;
    });
    const nodeIds = new Set(filteredNodes.map(n => n.id));
    let filteredLinks = fullData.links.filter(l => {
      const src = typeof l.source === 'object' ? l.source.id : l.source;
      const tgt = typeof l.target === 'object' ? l.target.id : l.target;
      return nodeIds.has(src) && nodeIds.has(tgt);
    });
    // Client-side strength cull (D-KG-3/4). The server pre-filters using
    // ?min_strength= for the same threshold so this is normally a no-op,
    // but it guards against stale payloads after a slider change while
    // the next /api/graph fetch is in flight.
    filteredLinks = cullLinksByStrength(filteredLinks, minStrength);
    graphData = { nodes: filteredNodes, links: filteredLinks };
    nodeDegrees = computeDegrees(graphData);
    if (graph) {
      graph.graphData(graphData);
      // Re-warm at α=0.3 (NOT resetSimulation — that would re-trigger
      // warmupTicks and burn worker CPU). 0.3 is enough kinetic energy
      // for the layout to absorb new/removed links without restarting.
      if (typeof graph.d3ReheatSimulation === 'function') {
        graph.d3ReheatSimulation();
      }
      // Re-apply the particle colour accessor so existing particle
      // materials get rebuilt against the fresh _nodeById map. 3d-force-
      // graph bakes the particle colour into each particle's material at
      // CREATION time — without re-setting the accessor here, every
      // particle from the initial render keeps the grey-blue fallback
      // (the colour it received when its link.source was still a string
      // id, before d3-force swapped it for the node object). One-time
      // re-apply per data load only — does NOT run on hover/click so it
      // can't reintroduce the F5-era flicker.
      if (typeof graph.linkDirectionalParticleColor === 'function') {
        graph.linkDirectionalParticleColor(graph.linkDirectionalParticleColor());
      }
    }
    updateStats();
    // Preserve user context across filter changes: keep panel + selection
    // + highlights ONLY if the selected/hovered/highlighted node survived
    // the filter. Pre-change behaviour wiped all three unconditionally on
    // every checkbox toggle — disruptive when curating filters around a
    // node you have in focus. Same predicate for hover so a leaked-hover
    // doesn't keep the title overlay on a node that's no longer rendered.
    if (selectedNode && !nodeIds.has(selectedNode.id)) {
      selectedNode = null;
      closePanel();
    }
    if (hoverNode && !nodeIds.has(hoverNode.id)) {
      hoverNode = null;
    }
    if (highlightNodes.size > 0) {
      // Prune highlights to surviving nodes only.
      const surviving = new Set();
      highlightNodes.forEach(id => { if (nodeIds.has(id)) surviving.add(id); });
      highlightNodes.clear();
      surviving.forEach(id => highlightNodes.add(id));
    }
    // Sync-paint the overlay after the filter change so a leaked hover/
    // selection doesn't leave a stale title visible for a frame.
    _syncTitleOverlay();

    // F2: empty-state covers two scenarios:
    //   (a) no nodes match filters → "No notes match these filters" + Reset.
    //   (b) nodes present but zero links → "No connections at this strength" +
    //       Reset (which now also lowers the strength slider, see Task 1.6).
    const emptyOverlay = document.getElementById('overlay-empty');
    const emptyText = document.getElementById('overlay-empty-text');
    if (emptyOverlay && emptyText) {
      if (filteredNodes.length === 0) {
        emptyText.textContent = 'No notes match these filters.';
        emptyOverlay.classList.remove('hidden');
      } else if (filteredLinks.length === 0) {
        emptyText.textContent = 'Nodes loaded, but no connections match this strength. Lower the threshold to see weaker links.';
        emptyOverlay.classList.remove('hidden');
      } else {
        emptyOverlay.classList.add('hidden');
      }
    }

    // No auto-zoomToFit on filter changes. Earlier the function queued a
    // 800 ms-delayed zoomToFit on EVERY applyFilters call without ever
    // cancelling pending timers — rapid checkbox toggles stacked multiple
    // camera tweens, producing "the camera jumps three times after I
    // stopped clicking" behaviour. Operator pref: filters narrow the view
    // in place; user pans/zooms manually if needed.
  }

  // Debounced applyFilters so rapid checkbox toggles don't run the full
  // filter pipeline N times. 80 ms is short enough to feel instant on a
  // single click but long enough to coalesce a multi-click curation pass.
  const _debouncedApplyFilters = debounce(applyFilters, 80);

  // ---- Stats ----
  function updateStats() {
    const n = graphData.nodes.length;
    const l = graphData.links.length;
    statsEl.textContent = `${n} notes \u00B7 ${l} connections`;
  }

  // ---- Close panel button ----
  if (panelClose) {
    panelClose.addEventListener('click', () => {
      if (_panelOpenTimer) { clearTimeout(_panelOpenTimer); _panelOpenTimer = null; }
      closePanel();
      selectedNode = null;
      highlightNodes.clear();
      _refreshAllNodeVisuals();
    });
  }

  // ---- Keyboard: Escape ----
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

  function normalizeGroup(group) {
    var normalized = (group || '').toString().trim().toLowerCase();
    if (normalized === 'generic') return 'web';
    return normalized || 'web';
  }

  // ---- Kastens filter section ----
  function renderKastensSection() {
    const body = document.getElementById('filter-kastens-body');
    if (!body) return;
    body.innerHTML = '';
    // Nested-menu structure: the "section" is the Kastens parent row +
    // its flyout submenu. Grey both so the disabled-scope affordance
    // still reads as one unit (mirrors the greyed Personal segment).
    const sectionEl = body.closest('.kg-filter-submenu');
    const parentEl = document.getElementById('kg-filter-parent-kastens');
    const scopeEls = [sectionEl, parentEl].filter(Boolean);
    if (currentView === 'global') {
      scopeEls.forEach(el => {
        el.classList.add('disabled-scope');
        el.setAttribute('title', 'Sign in to switch');
        el.setAttribute('aria-disabled', 'true');
      });
      if (sectionEl) {
        // Capture-phase click handler: any click anywhere in the section
        // opens login (logged-out) or switches view to Personal (logged-in).
        sectionEl.onclick = (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (!isLoggedIn) { openLoginModalFromKG(); return; }
          currentView = 'my';
          localStorage.setItem(STORAGE_KEY_VIEW, 'my');
          setViewBtns('my');
          loadGraphData();
          setTimeout(renderKastensSection, 0);
        };
      }
      // Body content: a single non-interactive hint (the section's onclick
      // captures the gesture for both logged-in and logged-out users).
      const hint = document.createElement('p');
      hint.className = 'kg-filter-empty';
      hint.textContent = 'Sign in to switch';
      body.appendChild(hint);
      return;
    }
    scopeEls.forEach(el => {
      el.classList.remove('disabled-scope');
      el.removeAttribute('title');
      el.removeAttribute('aria-disabled');
    });
    if (sectionEl) sectionEl.onclick = null;
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
              const resp = await zkFetch('/api/rag/sandboxes/' + encodeURIComponent(k.id) + '/members?limit=1000', { headers: authHeaders() });
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
        _debouncedApplyFilters();
      });
      body.appendChild(lbl);
    });
  }

  function loadKastens() {
    if (!isLoggedIn) { renderKastensSection(); return; }
    zkFetch('/api/rag/sandboxes', { headers: authHeaders() })
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

  const overlayEmptyReset = document.getElementById('overlay-empty-reset');
  if (overlayEmptyReset) {
    overlayEmptyReset.addEventListener('click', () => {
      activeSources = new Set([...knownSources]);
      activeKastens.clear();
      activeTags.clear();
      // F10: Reset MUST include the strength slider, otherwise users land in
      // the same empty state they reset away from.
      minStrength = DEFAULT_MIN_STRENGTH;  // LD-1: 0.30
      activeBucket = bucketForStrength(DEFAULT_MIN_STRENGTH) || 'weak';
      _syncStrengthUI();
      renderSourceSection();
      renderTagsSection();
      renderKastensSection();
      applyFilters();
    });
  }

  renderKastensSection();

  // ---- Strength bucket / slider wiring (WAVE-C 1c) ----
  // Buckets are exclusive — clicking one snaps the slider + threshold to
  // that bucket's lower bound. Slider gives fine control inside [0.30,0.85].
  // Both paths re-fetch /api/graph (cache-key-aligned) AND re-cull client-
  // side immediately for snappy UX.
  const strengthSlider = document.getElementById('strength-slider');
  const strengthValue = document.getElementById('strength-value');
  const strengthControls = document.getElementById('strength-controls');

  function _syncStrengthUI() {
    if (strengthSlider) strengthSlider.value = String(minStrength);
    if (strengthValue) strengthValue.textContent = minStrength.toFixed(2);
    if (strengthControls) {
      strengthControls.querySelectorAll('[data-bucket]').forEach(b => {
        b.classList.toggle('active', b.dataset.bucket === activeBucket);
        b.setAttribute('aria-pressed', b.dataset.bucket === activeBucket ? 'true' : 'false');
      });
    }
  }

  function _onStrengthChange(opts) {
    opts = opts || {};
    // F1 fix: do NOT call applyFilters() over stale fullData. Optimistically
    // cull EXISTING graphData.links to give instant slider feedback without
    // touching the node set (no layout jitter), then let loadGraphData()
    // atomically swap fullData when the server response lands. The server
    // response is the source of truth; the optimistic cull is a UX bridge.
    if (graph && graphData && Array.isArray(graphData.links)) {
      const survivingLinks = cullLinksByStrength(graphData.links, minStrength);
      graphData = { nodes: graphData.nodes, links: survivingLinks };
      graph.graphData(graphData);
      updateStats();
    }
    // Visually mark the slider as "loading" so users know a fresh fetch is in flight.
    const sliderWrap = document.querySelector('.kg-strength-slider-wrap');
    if (sliderWrap) sliderWrap.classList.add('is-loading');
    loadGraphData();
    if (opts.snapBucket) activeBucket = bucketForStrength(minStrength) || activeBucket;
    _syncStrengthUI();
  }

  const _debouncedStrengthChange = debounce(function () {
    _onStrengthChange({ snapBucket: true });
  }, SLIDER_DEBOUNCE_MS);

  if (strengthSlider) {
    strengthSlider.min = String(SLIDER_MIN);
    strengthSlider.max = String(SLIDER_MAX);
    strengthSlider.step = String(SLIDER_STEP);
    strengthSlider.value = String(minStrength);
    strengthSlider.addEventListener('input', function (e) {
      const v = parseFloat(e.target.value);
      if (Number.isFinite(v)) {
        minStrength = v;
        if (strengthValue) strengthValue.textContent = v.toFixed(2);
        _debouncedStrengthChange();
      }
    });
  }

  if (strengthControls) {
    // Debounce bucket clicks at the same 250 ms as the slider so a rapid
    // Weak → Medium → Strong sequence fires ONE /api/graph fetch at the
    // end of the gesture, not three back-to-back round-trips. The UI
    // (active pill + slider thumb) still snaps instantly via
    // _syncStrengthUI; only the network round-trip is deferred.
    const _debouncedBucketChange = debounce(function () {
      _onStrengthChange({ snapBucket: false });
    }, SLIDER_DEBOUNCE_MS);
    strengthControls.querySelectorAll('[data-bucket]').forEach(btn => {
      btn.addEventListener('click', function () {
        const b = btn.dataset.bucket;
        if (!STRENGTH_BUCKETS[b]) return;
        activeBucket = b;
        minStrength = snapToBucket(b);
        _syncStrengthUI();
        _debouncedBucketChange();
      });
    });
  }

  _syncStrengthUI();

  const overlayRetry = document.getElementById('overlay-error-retry');
  if (overlayRetry) overlayRetry.addEventListener('click', loadGraphData);

})();
