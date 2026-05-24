# Cloudflare "Render Blocking Requests" — Action Plan

**Date:** 2026-05-24
**Trigger:** Cloudflare Speed dashboard recommended enabling Rocket Loader to fix Lighthouse "Render blocking requests" finding.
**Status:** Research complete. Implementation deferred — execute in a separate session.
**Verdict:** **Do NOT enable Rocket Loader.** Use native `defer` + `fetchpriority` + Cloudflare Speed Brain + Early Hints.

---

## 1. Research findings (4 parallel agents, all converged)

| Agent | Verdict | Key evidence |
|---|---|---|
| **Industry state 2024–2026** | `LEGACY — USE MODERN ALT` | Cloudflare stopped first-party promotion of Rocket Loader post-2022; injects an `unload` handler which **disqualifies pages from bfcache** → net-negative for Core Web Vitals on Chrome. Auto Minify deprecated Aug 2024 — Cloudflare exiting client-side rewriting. Speed Brain (GA Sep 25 2024) + Early Hints are the promoted modern alternatives. |
| **Modern alternatives** | Native `defer` + `fetchpriority="high"` + Speed Brain + Early Hints | HTTP Archive 2024: only 13% of scripts use `defer`, 49.5% use `async` — "render-blocking" remains the #1 Lighthouse flag for that exact reason. `fetchpriority` browser support 93% in 2024-2026 (Chrome 102+, Safari 17.2+, Firefox 132+); Chrome auto-demotes deferred scripts to Low priority and `fetchpriority="high"` re-promotes them. |
| **Known breakage modes** | `HIGH` risk for our stack | Three documented compounding patterns we'd hit: (a) UMD CDN libs + inline `window.X` init (Outline #5718 / XenForo 2.3 / Bricks Builder canvas-blank), (b) `defer`+`onload` libs (KaTeX) when Auto Minify also on (dev.to 2021, still reproducible), (c) third-party payment SDKs (Razorpay; Mediavine officially says "disable RL"). `data-cfasync="false"` is undocumented for inline `<script>` tags and frequently fails. |
| **Per-library compat** | `GO-WITH-EXCLUSIONS` (safer: zone-wide OFF) | three.js: MED breakage confidence (Bricks canvas-blank pattern); 3d-force-graph: **HIGH** (textbook UMD + inline init pattern, GitHub #69/#495); three-spritetext: MED; KaTeX: MED (DOMContentLoaded suppression); Razorpay: **HIGH** (vendor docs require untouched loading); supabase-js: UNKNOWN/LOW. |

**Consensus:** All four agents independently reached the same conclusion using different evidence streams. The Lighthouse audit is correct that we have render-blocking JS, but Cloudflare's recommended remediation (Rocket Loader) is the wrong tool for our stack.

---

## 2. Stack audit (Phase 0 — already done, read-only)

### 2a. At-risk inline init scripts (MUST migrate before adding `defer`)

| File | Line | Pattern | Migration |
|---|---|---|---|
| `website/features/user_auth/callback.html` | 55–119 | Inline `<script>` async IIFE reads `supabase.createClient` at line 74 | Wrap entire IIFE body in `document.addEventListener('DOMContentLoaded', () => { ... })`. Deferred scripts execute before DOMContentLoaded, so `window.supabase` will be defined by then. |

That is the **only** inline initializer reading a deferred-lib global in the entire `website/` tree. Confirmed via Grep across all 17 templates.

### 2b. Scripts to verify (external app.js files — may read globals at top level)

| File | Reads | Risk if defer added to upstream lib | Fix if needed |
|---|---|---|---|
| `website/features/knowledge_graph/kg/js/app.js` | `window.ForceGraph3D`, `window.THREE` | **LOW** — defer preserves document order, so if app.js is also deferred it runs after the three.js stack | Audit during execution; wrap top-level access in `DOMContentLoaded` if needed |
| `website/features/user_home/home/js/home.js` | possibly `window.supabase` | LOW (same reason) | Audit during execution |
| `website/features/user_zettels/home/zettels/js/user_zettels.js` | possibly `window.supabase` | LOW (same reason) | Audit during execution |
| `website/features/user_rag/home/rag/js/user_rag.js` | possibly `window.supabase` | LOW (same reason) | Audit during execution |
| `website/features/user_kastens/home/kastens/js/user_kastens.js` | possibly `window.supabase` | LOW (same reason) | Audit during execution |
| `website/features/user_profile/profile/js/user_profile.js` | already `type="module"` → already deferred | NONE | No change |
| `website/mobile/m/js/graph.js` | `window.ForceGraph3D`, `window.THREE` | LOW (same as KG) | Audit during execution |

### 2c. Templates needing `defer` + `fetchpriority` additions

| Template | Scripts to defer | Add `fetchpriority="high"` on |
|---|---|---|
| `website/features/knowledge_graph/index.html` | lines 272–279 (7 scripts) | three.js + 3d-force-graph (critical for LCP) |
| `website/features/user_home/index.html` | lines 15, 350–360 (9 scripts; katex already deferred) | supabase-js + home.js |
| `website/features/user_rag/index.html` | lines 15, 134–139 (6 scripts) | supabase-js + user_rag.js |
| `website/features/user_zettels/index.html` | lines 15, 178–188 (7 scripts) | supabase-js + user_zettels.js |
| `website/features/user_kastens/index.html` | lines 14, 150–154 (5 scripts) | supabase-js + user_kastens.js |
| `website/features/user_profile/index.html` | line 14 (supabase-js) — `type="module"` script already deferred | supabase-js |
| `website/features/summarization_engine/ui/index.html` | line 23 (1 script) | dashboard.js |
| `website/features/user_auth/callback.html` | line 11–12 (2 scripts) — **also migrate IIFE per §2a** | supabase-js |
| `website/footer/pricing/index.html` | lines 21, 108–112 (6 scripts) | supabase-js + pricing.js |
| `website/footer/about/index.html` | line 235 (1 script) | — |
| `website/experimental_features/nexus/index.html` | lines 14, 66–67 (3 scripts) | supabase-js |
| `website/mobile/index.html` | lines 100–101 (2 scripts) | summarizer.js |
| `website/mobile/knowledge-graph.html` | lines 81–84 (4 scripts) | three.js + 3d-force-graph |
| `website/static/index.html` | lines 22, 232–235 (5 scripts) | supabase-js + app.js |

**Total: 14 templates touched, ~62 script tags modified.**

### 2d. Preconnect hints to add (where not already present)

Every template that loads from `cdn.jsdelivr.net` should have, in `<head>`:
```html
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
```
That's all templates except `summarization_engine/ui/index.html`, `footer/about/index.html`, `mobile/index.html` (no jsdelivr).

---

## 3. Recommended diff pattern (canonical example: knowledge_graph)

**Before** (`website/features/knowledge_graph/index.html:272-279`):
```html
<script src="https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three-spritetext@1.10.0/dist/three-spritetext.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/3d-force-graph@1.79.1/dist/3d-force-graph.min.js"></script>
<script src="/user-pricing/js/purchase_launcher.js?v=20260517d"></script>
<script src="/functional-gates/js/quota_gate.js?v=20260517d"></script>
<script src="/kg/js/kasten_modal.js?v=20260523a"></script>
<script src="/kg/js/app.js?v=20260523a"></script>
```

**After:**
```html
<!-- in <head> -->
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>

<!-- at end of <body> -->
<script defer fetchpriority="high" src="https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/three-spritetext@1.10.0/dist/three-spritetext.min.js"></script>
<script defer fetchpriority="high" src="https://cdn.jsdelivr.net/npm/3d-force-graph@1.79.1/dist/3d-force-graph.min.js"></script>
<script defer src="/user-pricing/js/purchase_launcher.js?v=20260517d"></script>
<script defer src="/functional-gates/js/quota_gate.js?v=20260517d"></script>
<script defer src="/kg/js/kasten_modal.js?v=20260523a"></script>
<script defer src="/kg/js/app.js?v=20260523a"></script>
```

**Why `defer` (not `async`):** order matters — `app.js` reads `window.ForceGraph3D` (created by `3d-force-graph` which reads `window.THREE` from `three.min.js`). `defer` preserves document order; `async` would race.

**Why `fetchpriority="high"` only on three.js + 3d-force-graph:** Chrome auto-demotes deferred scripts to Low priority. The KG render is gated on three.js + the graph lib — re-promoting those two to High gets us back the LCP that `defer` alone gives up.

---

## 4. Callback page migration (the one inline-init case)

**Before** (`website/features/user_auth/callback.html:11, 55-119`):
```html
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
...
<script>
(async function() {
    var statusEl = document.getElementById('status');
    ...
    var createClient = supabase.createClient;  // line 74 — reads window.supabase
    ...
})();
</script>
```

**After:**
```html
<script defer src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
...
<script>
document.addEventListener('DOMContentLoaded', function() {
  (async function() {
    var statusEl = document.getElementById('status');
    ...
    var createClient = supabase.createClient;  // safe — defer fired by now
    ...
  })();
});
</script>
```

**Why this is safe:** the HTML spec guarantees deferred external scripts finish executing before `DOMContentLoaded` fires. The IIFE inside the listener will see a defined `window.supabase`.

---

## 5. FastAPI Early Hints middleware (one-time, ~15 LOC)

Cloudflare's [Early Hints](https://developers.cloudflare.com/cache/advanced-configuration/early-hints/) works by parsing `Link:` headers from the origin response, caching them, and emitting an HTTP 103 with those `Link:` headers on subsequent requests — before the origin even responds. The headers tell the browser to start preconnect/preload immediately.

**Implementation** — add to `website/app.py` (location TBD during execution):

```python
from starlette.middleware.base import BaseHTTPMiddleware

# Per-route Link: headers for Cloudflare Early Hints.
# Map: pathname → list of (url, rel, as_type)
_EARLY_HINTS = {
    "/knowledge-graph": [
        ("https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.min.js", "preload", "script"),
        ("https://cdn.jsdelivr.net/npm/3d-force-graph@1.79.1/dist/3d-force-graph.min.js", "preload", "script"),
    ],
    "/home": [
        ("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2", "preload", "script"),
    ],
    # add others as needed
}

class EarlyHintsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        hints = _EARLY_HINTS.get(request.url.path)
        if hints:
            link_value = ", ".join(f'<{u}>; rel={r}; as={a}' for (u, r, a) in hints)
            response.headers["Link"] = link_value
        return response

app.add_middleware(EarlyHintsMiddleware)
```

**Infra overhead per request:** ~50µs to look up the path and set one header. No new dependency. No worker model change. No Caddy reload required (Caddy forwards origin headers through to Cloudflare unchanged).

**Verification that Cloudflare emits 103s:** after deploying, run `curl -I --http2 -v https://zettelkasten.in/knowledge-graph 2>&1 | grep -i '^< HTTP'` from outside Cloudflare and look for `HTTP/2 103` before `HTTP/2 200`.

---

## 6. Cloudflare dashboard actions (manual — operator-only)

| Setting | Action | Rationale |
|---|---|---|
| Speed → Optimization → **Rocket Loader** | OFF (or confirm OFF) | Per all 4 agents — legacy, bfcache-disqualifying |
| Speed → Optimization → **Speed Brain** | ON (default-on for Free since Sep 2024 — verify) | 45% p50 LCP gain on subsequent navigations via Speculation Rules API |
| Caching → Configuration → **Early Hints** | ON | Enables 103 responses; requires the FastAPI middleware to emit `Link:` headers from origin |
| Speed → Optimization → **Auto Minify** | leave OFF (deprecated Aug 2024 anyway) | — |
| Speed → Optimization → **Brotli** | ON (verify) | Standard compression |

---

## 7. Phased execution plan (when ready to ship)

| Phase | Scope | Verification gate | Rollback |
|---|---|---|---|
| **P1** | callback.html IIFE → wrap in DOMContentLoaded + add `defer` to its 2 scripts | manual login flow works end-to-end in dev + staging | git revert single commit |
| **P2** | knowledge_graph + mobile knowledge-graph: defer + fetchpriority on three.js stack; verify `/kg/js/app.js` + `/m/js/graph.js` top-level globals access pattern | KG page renders 3D graph in dev + staging | git revert |
| **P3** | user_home + user_rag + user_zettels + user_kastens + user_profile + summarization_engine: defer + fetchpriority on supabase + local app scripts; spot-audit each app.js for top-level `window.supabase` access | each page boots + renders in dev + staging | git revert |
| **P4** | footer/pricing + footer/about + experimental_features/nexus + static + mobile/index: defer + fetchpriority | each page renders in dev + staging | git revert |
| **P5** | FastAPI EarlyHintsMiddleware + per-route `Link:` map for 5-7 high-traffic routes | `curl -I` shows `Link:` header; Cloudflare Speed panel shows Early Hints "active" within 24h | remove middleware (one commit) |
| **P6** | Operator (chintan): toggle Cloudflare dashboard settings per §6 | Lighthouse re-audit confirms "Render-blocking requests" warning is downgraded | toggle settings back |

**Each phase = one self-contained commit/PR** so any can be reverted independently.

---

## 8. Verification checklist (per page after each phase)

- [ ] Page renders without JS errors in Chrome DevTools console
- [ ] All UI interactions still work (login, add zettel, navigate KG, etc.)
- [ ] Lighthouse score on the touched page: Performance ≥ baseline, "Render-blocking requests" warning reduced or gone
- [ ] No new bfcache warnings in Chrome DevTools → Application → Back/forward cache panel
- [ ] No new errors in droplet logs after 30 min of canary traffic
- [ ] For KG page specifically: `window.ForceGraph3D` defined and graph mounts within 3s
- [ ] For callback page: full OAuth round-trip succeeds in a fresh incognito window

---

## 9. Infra-overhead audit (CLAUDE.md production change discipline)

| Concern | Impact | Verdict |
|---|---|---|
| Droplet RAM | +0 MB (no new dep, no worker change) | safe |
| Gunicorn worker count | Untouched (protected per CLAUDE.md guardrail) | safe — no protected knob touched |
| Cold start | Unchanged | safe |
| Caddy config | Untouched | safe |
| Per-request latency | ~50µs to set `Link:` header in middleware | negligible |
| bfcache | **Improves** vs. current Cloudflare-recommended path | net positive |
| SSE/WebSocket paths | Not affected (Speed Brain prefetches GET only; Early Hints is header-only) | safe |
| Risk to existing UI/UX | callback.html IIFE migration is the one real risk; everything else is mechanical | manageable with phased rollout |

---

## 10. Sources (cited by the 4 research agents, 2022-2026)

### Cloudflare official
- [Rocket Loader · Cloudflare Speed docs](https://developers.cloudflare.com/speed/optimization/content/rocket-loader/)
- [Ignore JavaScripts in Rocket Loader](https://developers.cloudflare.com/speed/optimization/content/rocket-loader/ignore-javascripts/)
- [Cloudflare Early Hints docs](https://developers.cloudflare.com/cache/advanced-configuration/early-hints/)
- [Introducing Speed Brain](https://blog.cloudflare.com/introducing-speed-brain/) — 2024-09-25
- [Deprecating Auto Minify](https://community.cloudflare.com/t/deprecating-auto-minify/655677) — 2024-08
- [Too Old To Rocket Load, Too Young To Die](https://blog.cloudflare.com/too-old-to-rocket-load-too-young-to-die/) — 2018-07-04 (still canonical RL behavior)

### Web performance authorities
- [Optimize LCP](https://web.dev/articles/optimize-lcp) — web.dev — 2024
- [Fetch Priority API](https://web.dev/articles/fetch-priority) — web.dev — 2024
- [Async vs Defer](https://www.debugbear.com/blog/async-vs-defer) — DebugBear — 2024
- [JavaScript — Web Almanac 2024](https://almanac.httparchive.org/en/2024/javascript) — HTTP Archive
- [Cloudflare Speed Brain: What You Need to Know](https://www.debugbear.com/blog/cloudflare-speed-brain) — 2024-09-26 (updated 2025-10-21)
- [Configure Cloudflare for Core Web Vitals](https://www.corewebvitals.io/pagespeed/configure-cloudflare-for-passing-the-core-web-vitals)
- [Ideal Cloudflare Settings For WordPress \[2025\]](https://onlinemediamasters.com/cloudflare-settings-wordpress/)

### Concrete breakage evidence
- [Outline #5718 — App does not work with Cloudflare Rocket Loader](https://github.com/outline/outline/issues/5718)
- [XenForo 2.3 broken by Rocket Loader](https://xenforo.com/community/threads/xf-2-3-is-broken-when-cloudflares-rocket-loader-is-enabled.226168/) — 2024-07-23
- [Cloudflare Community #736209 — RL breaks mobile JS in WordPress 6.7](https://community.cloudflare.com/t/rocket-loader-breaks-mobile-js-in-wordpress-6-7/736209) — 2024-11
- [Bricks Builder Forum — canvas empty error with Rocket Loader](https://forum.bricksbuilder.io/t/solved-canvas-empty-error-with-rocket-loader-js-cloudflare-no-problem-with-litespeed/4294) — 2022-07
- [Cloudflare Community #588715 — RL breaks script even with Page Rules disabled](https://community.cloudflare.com/t/rocket-loader-breaks-a-script-even-when-i-disable-it-under-page-rules-and-configuration/588715)
- [dev.to — DOMContentLoaded skipped when RL + Auto Minify](https://dev.to/hollowman6/solution-to-missing-domcontentloaded-event-when-enabling-both-html-auto-minify-and-rocket-loader-in-cloudflare-5ch8) — 2021-10-19
- [3d-force-graph #69 — ForceGraph3D not defined](https://github.com/vasturiano/3d-force-graph/issues/69)
- [3d-force-graph #495 — ForceGraph3D not defined recurring](https://github.com/vasturiano/3d-force-graph/issues/495)
- [Mediavine — Cloudflare Rocket Loader Conflict](https://help.mediavine.com/) — "very aggressive, beta product, can often break JavaScript"
- [Razorpay Payment Page Speed Checklist](https://razorpay.com/blog/payment-page-speed-checklist-faster-checkout)

---

## 11. Why we are deferring implementation

This plan exists as a deliverable; implementation is **out of scope for this session** per operator instruction. To execute, open a fresh worktree/iteration and step through phases P1→P6 sequentially with verification gates between each.

Risk-adjusted estimate: P1–P5 ≈ 1–2 hours of focused work (mechanical edits + per-page smoke tests); P6 ≈ 5 minutes of dashboard clicks by the operator.
