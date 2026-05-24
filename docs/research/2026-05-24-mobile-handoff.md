# Mobile-Latency Handoff — Self-Contained Brief

**Date:** 2026-05-24
**Audience:** A separate agent (no prior conversation context) tasked with reviewing + implementing mobile-side latency improvements.
**Parent docs (read for full context):**
- [2026-05-24-cloudflare-10x-plan.md](./2026-05-24-cloudflare-10x-plan.md) — the full 10x latency plan for the whole site
- [2026-05-24-cloudflare-render-blocking-fix.md](./2026-05-24-cloudflare-render-blocking-fix.md) — frontend render-blocking JS fix (covers both desktop + mobile templates)

**This doc's scope:** every mobile-affecting item, extracted from both parent docs, plus mobile-only opportunities not covered there. Self-contained so you don't need the conversation history.

---

## 1. Mobile surface area in the codebase (factual context)

| Asset | Path | Notes |
|---|---|---|
| Mobile-only landing template | [website/mobile/index.html](website/mobile/index.html) | URL summarizer, mobile UI |
| Mobile-only KG template | [website/mobile/knowledge-graph.html](website/mobile/knowledge-graph.html) | Loads same three.js + 3d-force-graph CDN stack as desktop |
| Mobile CSS | `website/mobile/css/mobile.css` | Served at `/m/css/mobile.css` |
| Mobile JS — summarizer | `website/mobile/js/summarizer.js` | Served at `/m/js/summarizer.js?v=20260518b` |
| Mobile JS — graph | `website/mobile/js/graph.js` | Served at `/m/js/graph.js`; reads `window.ForceGraph3D` + `window.THREE` |
| Mobile UA detection + auto-redirect | [website/app.py:89-103, 405-417](website/app.py:89) | Regex `Android\|webOS\|iPhone\|iPad\|iPod\|BlackBerry\|IEMobile\|Opera Mini\|Mobile\|mobile`; desktop routes redirect to `/m/*` when matched |
| Mobile static mounts | [website/app.py:253-261](website/app.py:253) | `/m/css`, `/m/js` mounted as StaticFiles |

**PWA-ish meta tags already in place** on both mobile templates: `apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style`, `theme-color`, `viewport-fit=cover`. Google Fonts preconnect also already in place.

---

## 2. Mobile-affecting items from the render-blocking-fix doc

(Lift verbatim from parent doc §2c–2d.)

### 2.1 `website/mobile/index.html` (lines 100-101)
Currently:
```html
<script src="/js/add_zettel_api.js?v=20260522a"></script>
<script src="/m/js/summarizer.js?v=20260518b"></script>
```
Change to:
```html
<script defer src="/js/add_zettel_api.js?v=20260522a"></script>
<script defer fetchpriority="high" src="/m/js/summarizer.js?v=20260518b"></script>
```
No jsdelivr preconnect needed (this page doesn't hit jsdelivr).

### 2.2 `website/mobile/knowledge-graph.html` (lines 81-84)
Currently:
```html
<script src="https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three-spritetext@1.10.0/dist/three-spritetext.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/3d-force-graph@1.79.1/dist/3d-force-graph.min.js"></script>
<script src="/m/js/graph.js"></script>
```
Change to:
```html
<!-- in <head> -->
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>

<!-- at end of <body> -->
<script defer fetchpriority="high" src="https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/three-spritetext@1.10.0/dist/three-spritetext.min.js"></script>
<script defer fetchpriority="high" src="https://cdn.jsdelivr.net/npm/3d-force-graph@1.79.1/dist/3d-force-graph.min.js"></script>
<script defer src="/m/js/graph.js"></script>
```

**Critical to verify in `/m/js/graph.js`:** any top-level code reading `window.ForceGraph3D` or `window.THREE` is safe with `defer` (deferred scripts run in document order before `DOMContentLoaded`). If the file wraps init in `DOMContentLoaded`, that also works. If it reads `window.X` in a non-deferred inline `<script>` block, that block needs to be moved into a deferred external file OR wrapped in `document.addEventListener('DOMContentLoaded', () => {...})`. Audit before shipping.

### 2.3 No inline-init scripts in mobile templates
Confirmed via Grep: `website/mobile/*.html` contain ZERO inline `<script>` blocks reading deferred-lib globals. (The one inline-init in the entire repo is in `website/features/user_auth/callback.html` — not a mobile page.)

---

## 3. Mobile-affecting items from the 10x-plan doc

(Lift from parent doc §3.D + §1 network table.)

### 3.1 Protocol-layer wins (Phase D in parent doc) — DISPROPORTIONATELY benefit mobile

| Setting | Mobile-specific win | How |
|---|---|---|
| **0-RTT TLS resumption** | ~100-200ms saved per warm GET on India mobile networks | Dashboard → Speed → Optimization → Protocol Optimization → enable. Cloudflare auto-blocks 0-RTT on POST (RFC 8470), so anti-replay is handled. |
| **HTTP/3 + QUIC** | Catchpoint Jul 2025 measured **41.8% median TTFB reduction** on India mobile vs HTTP/2; lossy-network resilience (Wi-Fi → cellular handoff); avoids TCP head-of-line blocking | Should be on by default; **verify** in Dashboard → Network → HTTP/3. |
| **RFC 9218 priorities on SSE** | Mobile users on lossy networks benefit most from incremental SSE delivery | Set `Priority: u=1, i` response header on SSE endpoints (already covered in 10x plan §C.1 for `/api/rag/sessions/{id}/messages` + `/api/rag/adhoc`). |
| **Smart Tiered Cache** | Verify Smart, not Generic — single-region origin in BLR | Dashboard → Caching → Tiered Cache. |
| **TLS 1.3 min** | Mobile devices benefit from 1-RTT vs 2-RTT handshake | Dashboard → SSL/TLS → Edge Certificates. |

### 3.2 SSE unbreak (Phase C in parent doc) — CRITICAL for mobile users
Mobile users disproportionately hit the Cloudflare SSE issues because:
- Handset radios sleep aggressively → idle timer on Cloudflare's 100s buffer fires more often
- Bandwidth fluctuations → 100KB buffer threshold takes longer to accumulate
- Phone screen lock → TCP RST on handover

**Apply the entire SSE unbreak stack** from parent doc §C (response headers + Configuration Rule `response_body_buffering: none` + Compression Rule disabling br/zstd on `text/event-stream` + first-token padding). This is not mobile-specific code, but the user-perceived first-token improvement is largest on mobile.

### 3.3 India routing (parent doc §1, network row)
**Cloudflare Free plan routes Jio/Airtel traffic to Singapore (159-207ms)** instead of Mumbai (44-66ms). Cloudflare Business plan ($200/mo) buys India routing parity. **Deferred decision** — only worth the cost when India MAU justifies it. Cite from `punits.dev/blog/cloudflare-latency-india/` Jan 2025.

### 3.4 Edge caching (Phase A in parent doc) — mobile-perceived wins are amplified
Mobile CPUs parse JSON 2-4x slower than desktop CPUs. An edge cache HIT (50ms vs 400ms origin) on `/api/graph` or `/api/zettels` translates to MORE perceived improvement on mobile than desktop because the network savings dominate the total request time.

**Apply Phase A unchanged.** No mobile-specific Cache Rules needed.

---

## 4. Mobile-only opportunities NOT in either parent doc

### 4.1 Image optimization (Cloudflare Polish / Images)
| Feature | Plan | Mobile win | Recommendation |
|---|---|---|---|
| **Polish** (auto WebP/AVIF + lossy/lossless conversion) | Pro+ ($25/mo) | Mobile-bandwidth + battery savings; 20-40% image-size reduction typical | **Defer.** Our site has very few raster images (favicon SVG, KaTeX fonts). Not worth Pro upgrade for image optimization alone. |
| **Cloudflare Images** (resize + transform on-demand, $5/mo + per-image) | Any plan | Per-device-class image variants | **Defer.** Same reason — limited raster surface. Revisit if user-uploaded avatars/attachments ship. |

### 4.2 Edge mobile-UA detection (replace FastAPI redirect)
Currently `_is_mobile()` regex runs in FastAPI middleware (origin-side, after edge → origin RTT). Could move to:
- **Cloudflare Snippets** (Pro plan only; $25/mo) — single-file edge JavaScript, ~5ms. Removes 1 origin round-trip for every mobile-browser desktop-URL visit (which is currently a 301 → 200 chain).
- **Cloudflare Worker** (Free plan: 100k req/day) — same thing, more flexibility. Worker reads `User-Agent`, issues 301 to `/m/...` directly at edge. Removes 1 RTT (~50-150ms India mobile) on every desktop-URL-typed mobile-browser visit.

**Recommendation:** Defer until Phase A/B numbers prove origin RTT is a top user-perceived bottleneck on this specific path. Most users are likely already on `/m/*` URLs (bookmarked, share-routed). Measure first.

### 4.3 INP (Interaction to Next Paint) — mobile Core Web Vitals
- Mobile Lighthouse weighs INP very heavily (target ≤200ms).
- Our `summarizer.js` and `graph.js` are likely the INP hot spots (button taps + KG node taps).
- **Out-of-scope for this Cloudflare-focused plan**; flag for a separate INP-focused audit using DevTools Performance panel on a real mid-tier Android device.

### 4.4 Service Worker / PWA install banner
- The mobile templates have `apple-mobile-web-app-capable` + `theme-color` already — partially PWA-ready.
- Missing: `manifest.json`, registered Service Worker, install-prompt UX.
- **Out-of-scope** for this Cloudflare plan. Flag as a separate product decision (PWA install rate, offline support tradeoffs).

### 4.5 Mobile-specific cache splitting (`Vary: User-Agent`)
- Generally **anti-recommended** in 2024-2026 because `Vary: User-Agent` explodes cache fragmentation (every UA string = a new cache entry).
- **Skip.** Our mobile templates are served from a separate URL (`/m/*`), not via UA-based content negotiation, so cache splitting isn't needed.

### 4.6 `prefers-reduced-motion` / battery API
- Out-of-scope for Cloudflare layer; flag for design-side accessibility pass.

---

## 5. Phased mobile execution plan (for the receiving agent)

Each phase is independently shippable + revertible.

### M1 — Apply render-blocking-fix to mobile templates
- Edit `website/mobile/index.html` per §2.1 above.
- Edit `website/mobile/knowledge-graph.html` per §2.2 above (including preconnect).
- Audit `website/mobile/js/graph.js` for top-level `window.X` reads or inline-script equivalents — migrate to `DOMContentLoaded` wrapper if found.
- Manual smoke test on a real mobile device (or Chrome DevTools mobile emulation):
  - `/m/` loads, summarizer form submits, summary renders.
  - `/m/knowledge-graph` loads, 3D graph mounts within 3s, search filters work, KG node taps respond.
- Verify with Lighthouse mobile preset on both pages: "Render-blocking requests" warning reduced or gone; Performance score uplifted.
- One commit per page (so each is revertible).

### M2 — Verify protocol-layer settings benefit mobile
- These are zone-wide settings, owned by parent doc Phase D. Coordinate with parent-plan executor — do NOT duplicate-toggle.
- Specifically for mobile: **measure** before/after `/m/knowledge-graph` and `/m/` from a real India-mobile network (or a remote BLR-region monitor) for TTFB + LCP improvements after parent Phase D is on.

### M3 — Defer mobile-only opportunities (Polish, Edge UA detection)
- Do NOT implement these without operator sign-off — they require Pro plan ($25/mo) and the cost/benefit analysis is in §4.1 + §4.2 above.

### M4 — Hand back to operator for Cloudflare Business plan decision
- The India-routing parity lever ($200/mo, parent doc §1 + §3.3 here) is the largest mobile-specific win remaining after M1–M3.
- This is an operator-only decision based on India MAU growth. Do NOT recommend/upgrade without explicit operator approval.

---

## 6. Mobile-specific verification checklist

After M1:
- [ ] Lighthouse mobile preset on `/m/` and `/m/knowledge-graph` — Performance score ≥ baseline (record numbers before/after).
- [ ] "Render-blocking requests" warning reduced or eliminated.
- [ ] No new JS errors in mobile Chrome DevTools console (Chrome remote debugging on a real Android device, NOT desktop emulation — emulation hides too many real-network issues).
- [ ] `/m/knowledge-graph` 3D graph mounts within 3s on a mid-tier Android over 4G.
- [ ] No new bfcache disqualification warnings (Chrome DevTools → Application → Back/forward cache).
- [ ] Phase 1B.4 SSE heartbeat still firing on `/m/` chat path (if any — currently chat is desktop-only, but verify mobile RAG chat works after parent doc Phase C ships).
- [ ] Touch responsiveness unchanged (subjective; no obvious INP regression).

After M2 (parent doc Phase D shipped):
- [ ] India synthetic probe records TTFB improvement on `/m/*` paths.
- [ ] Real-device test on Jio/Airtel/BSNL shows perceived improvement on warm GETs (post-0-RTT enable).

---

## 7. Risks (mobile-specific)

| # | Risk | Mitigation |
|---|---|---|
| MR1 | `/m/js/graph.js` reads `window.X` synchronously at top level — adding `defer` to upstream causes "ForceGraph3D is not defined" on init | Audit FIRST, before any deploy. Test on staging with real mobile device. |
| MR2 | Mobile Safari iOS HTTP/3 quirks (some carrier Wi-Fi blocks UDP/443) | Cloudflare auto-falls back to HTTP/2 — no action needed; monitor for any iOS-specific bug reports. |
| MR3 | INP regression from any new JS additions | Out-of-scope for this plan; flag if observed. |
| MR4 | Edge UA detection (if ever implemented) over-redirects desktop tablets to /m/ | Keep FastAPI fallback regex active in parallel during any Worker rollout; canary first. |
| MR5 | Cloudflare's `Vary` handling fragments cache for mobile-vs-desktop GETs | We do NOT use `Vary: User-Agent`; mobile and desktop live at different URLs. Safe. |
| MR6 | Apple Web Push / iOS service-worker quirks if PWA is ever added | Out-of-scope. |

---

## 8. Hand-off checklist — receiving agent should confirm before acting

1. [ ] Read parent docs (`2026-05-24-cloudflare-10x-plan.md`, `2026-05-24-cloudflare-render-blocking-fix.md`) — this brief assumes you have done so.
2. [ ] Confirm with operator which phases (M1, M2, M3, M4) are in scope for your session.
3. [ ] If touching `website/mobile/js/graph.js`, audit it first (no edits without audit).
4. [ ] Coordinate with parent-plan executor to avoid duplicating Cloudflare dashboard toggles (Phase D items).
5. [ ] Test on a REAL mobile device (Chrome DevTools desktop emulation is NOT sufficient verification per CLAUDE.md Production Change Discipline).
6. [ ] Use dashboard mode for multi-step execution per CLAUDE.md (`feedback_dashboard_format_spec.md`).
7. [ ] Commit messages: short ≤10 words, prefixed (`feat:`, `fix:`, `perf:`, `chore:`) per CLAUDE.md commit conventions.
8. [ ] No purple in UI. Teal main, amber/gold only on `/knowledge-graph`. No infra/model/token info exposed in mobile UI strings.
9. [ ] Do NOT touch protected knobs (Gunicorn workers, `--preload`, FP32 verifier, semaphore, SSE heartbeat module cadence, Caddy upstream timeouts, schema-drift gate, `kg_users` allowlist gate).
10. [ ] When in doubt → ask operator, don't silently expand scope (CLAUDE.md `feedback_anything_beyond_plan_needs_approval.md`).

---

## 9. Out of scope (do NOT attempt under this brief)

- AI Gateway / Gemini routing changes (parent doc Phase B; separate research in flight).
- Backend FastAPI middleware (parent doc Phase A; not mobile-specific).
- SSE Configuration / Compression Rules (parent doc Phase C; not mobile-specific).
- Cloudflare Workers for `/api/graph` (parent doc Phase E; deferred).
- Pricing / billing / plan upgrades (operator decision).
- PWA install / Service Worker (separate product decision).
- INP audit (separate performance audit).
- Mobile UI design changes (separate design decision).

---

## 10. Estimated effort

- **M1** (render-blocking fixes to 2 templates + audit of graph.js): 1-2 hours including real-device verification.
- **M2** (coordinate with parent Phase D + India measurement): 1 hour of measurement work after parent Phase D ships.
- **M3 / M4**: operator decisions; zero engineering work in this brief.

Total mobile-scoped work: ~2-3 hours.
