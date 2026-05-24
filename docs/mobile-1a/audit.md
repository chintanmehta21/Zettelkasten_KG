# Mobile Website — Iteration 1a Audit

**Branch:** `exec/mobile-website-verification--1a`
**PR:** [Zettelkasten_KG#76](https://github.com/chintanmehta21/Zettelkasten_KG/pull/76)
**Audit date:** 2026-05-24
**Author:** assistant (Claude Opus 4.7)
**Scope of this doc:** read-only audit + gap matrix. Implementation plan is a separate doc once scope is locked with operator.

---

## 1. Headline

| Metric | Desktop | Mobile | Δ |
|---|---|---|---|
| User-facing surfaces | 10 (+2 internal) | 2 | **−8** |
| Auth UI on first-load | yes (modal + OAuth grid) | **none** | full gap |
| Knowledge browsing (zettels) | full CRUD + filters | none | full gap |
| RAG chat | yes | none | full gap |
| Kastens | yes | none | full gap |
| KG viz | full filters (source / tags / kastens / strength / personal-vs-global) | source chips only | partial |
| Profile + trash recovery | yes | none | full gap |
| Pricing / Razorpay | yes | none | full gap |
| About | yes | none | full gap |
| Nexus (experimental) | yes (flag-gated) | none | full gap |

Mobile users today land on `/m/` (URL summarizer) → can summarize anonymously and view the 3D KG. Every other desktop route (`/home`, `/home/zettels`, `/home/rag`, `/home/kastens`, `/profile`, `/pricing`, `/about`, `/home/nexus`) issues a 302 to `/m/` — dead-end for mobile.

---

## 2. Desktop UX surface inventory (canonical)

Built from `website/app.py` route table + per-feature `index.html`.

| # | Route | Template | Mobile redirect | Top UX elements | Primary flow |
|---|---|---|---|---|---|
| 1 | `/` | `website/static/index.html` | → `/m/` | URL+document input, source select, OAuth provider grid, login modal, skeleton typewriter, result card | Capture URL → summary |
| 2 | `/home` | `features/user_home/index.html` | → `/m/` | Avatar dropdown, welcome banner, "latest 3 zettels" grid, KG sidebar preview | Logged-in landing |
| 3 | `/home/zettels` | `features/user_zettels/index.html` | → `/m/` | Add-zettel pill (URL + upload), stats cards, search, filter dropdown (source + tags), zettel grid, edit/delete actions | Browse + manage zettels |
| 4 | `/home/rag` | `features/user_rag/index.html` | → `/m/` | Chat title + hint, "manage kastens" link, transcript live region, composer, advanced filters (quality + tag scope + source grid) | Chat with knowledge base |
| 5 | `/home/kastens` | `features/user_kastens/index.html` | → `/m/` | Create-kasten pill, stats, kasten grid, quality-radio modal | Create / manage kastens |
| 6 | `/knowledge-graph` | `features/knowledge_graph/index.html` | → `/m/knowledge-graph` | Back, view toggle (Global/Personal), search w/ count + clear, All-Filters dropdown (source + tags + kastens + connection-strength slider), reset, ForceGraph3D | Interactive KG |
| 7 | `/profile` | `features/user_profile/index.html` | → `/m/` | Avatar picker, account info, KG stats grid, trash recovery list | Account + restore deleted |
| 8 | `/home/nexus` | `experimental_features/nexus/index.html` | → `/m/` (flag-gated) | Import-all, provider grid, recent-runs panel | Connect source accounts |
| 9 | `/pricing` | `footer/pricing/index.html` | → `/m/` | Login modal, phone-capture modal, plan cards, Razorpay checkout | Buy a plan |
| 10 | `/about` | `footer/about/index.html` | → `/m/` | Hero + pill highlights, story grid, image carousel | Marketing |
| 11 | `/auth/callback` | `features/user_auth/callback.html` | — | OAuth spinner + status | Post-OAuth landing |
| 12 | `/summarization-engine` | `features/summarization_engine/ui/index.html` | — | Batch URL textarea | Admin/internal |

---

## 3. Current mobile surfaces — UX deficiencies

### 3.1 `/m/` (mobile summarizer) — `website/mobile/index.html`

| # | Deficiency | Desktop equivalent | Severity |
|---|---|---|---|
| M1.1 | No auth UI / no sign-in surface at all | Login modal + OAuth provider grid | **blocker for parity** |
| M1.2 | No identity indication — anon user has no signal whether their zettel persisted to their account or to Zoro/anonymous bucket | Header avatar + dropdown when authed | high |
| M1.3 | No navigation to anything except KG (single link at bottom) | Header includes links to /home, /home/zettels, /home/rag, /home/kastens, /profile, /pricing, /about | **blocker for parity** |
| M1.4 | Loader uses rotating-text only; desktop uses skeleton typewriter w/ phase-aware (queued/running/long) | `zk_skeleton_typewriter.js` in static/js | medium (good enough for v1) |
| M1.5 | Result actions = copy + source link only. Desktop result card may have edit/delete/share (verify post-scope-lock) | Result card actions | medium |
| M1.6 | No empty-state CTA — once result renders, no path forward unless user clears & retries | Desktop /home dashboards | medium |
| M1.7 | Source select wording inconsistent with desktop labels (e.g. "Newsletter" vs "Substack") | static/index.html source options | low |
| M1.8 | Anchor `<a href="/">` in footer says "Desktop version" but `/` 302-redirects mobile right back — broken affordance | n/a | low |

### 3.2 `/m/knowledge-graph` — `website/mobile/knowledge-graph.html`

| # | Deficiency | Desktop equivalent | Severity |
|---|---|---|---|
| M2.1 | No Global vs Personal view toggle | View-toggle pills above search | **high** (changes meaning of viz) |
| M2.2 | Filter chips only cover source; no tags / kastens / connection-strength filters | `All Filters` dropdown w/ submenus + slider | high |
| M2.3 | No search count / clear-button affordance | Search shows "X matches" + clear | medium |
| M2.4 | No reset-view button | Reset to initial zoom button | medium |
| M2.5 | Bottom sheet `Connected Notes` clickable, but no swipe-to-detail / no edit / no delete-from-KG | Desktop sidebar w/ delete + jump-to-zettel | medium |
| M2.6 | Auto-rotate orbit is enabled by default and only stopped on first touch — can disorient on first paint | Desktop has same pattern; acceptable | low |
| M2.7 | Hard-coded `'/api/graph'` fetch with no auth header → only ever sees public/anonymous graph; matches M2.1 → effectively global-only | Uses fetch w/ same auth context | high |
| M2.8 | No infra-cost concern (3D viz already heavy; ForceGraph3D bundle is ~250KB gz); but `linkDirectionalParticles(1)` and `warmupTicks(80)` are mobile-conservative — keep | n/a | none |

### 3.3 Cross-cutting (shell, app.py routing)

| # | Deficiency | Severity |
|---|---|---|
| M3.1 | `_is_mobile()` UA regex (line 90 `website/app.py`) is broad but doesn't allow user to **opt-out** of the mobile redirect — once on mobile UA, all desktop routes are locked away. Tablet users may want desktop. | medium |
| M3.2 | The "Desktop version" link in mobile footer doesn't bypass `_is_mobile()`, so it's a no-op | low (visual lie) |
| M3.3 | No shared mobile shell / header — both `/m/` and `/m/knowledge-graph` repeat full HTML doc + font preconnects + viewport meta. Future mobile pages will fork the boilerplate. | medium (now); high if we add 5+ pages |
| M3.4 | No mobile auth state propagation — `add_zettel_api.js` is shared with desktop but `/m/` doesn't surface signed-in / signed-out state in DOM | high (blocks M1.1 / M1.2) |
| M3.5 | No mobile bottom-tab / hamburger nav — once we add a 3rd page, navigation discoverability becomes a UX problem | will be high once we add `/m/home` etc. |
| M3.6 | No PWA manifest / install prompt — mobile site has `apple-mobile-web-app-capable` meta but no `manifest.json`, missing offline / home-screen capability that's standard for 2025 mobile-first PWAs | medium |
| M3.7 | No mobile analytics surface to distinguish iOS Safari / Android Chrome / TWA usage (impacts what we test). Verify with `read_recent_logs`. | low (not in 1a) |

---

## 4. Missing-page tiering (proposed)

This is a **proposal**, not a commitment — final tiering is decided with operator before any implementation.

| Tier | Surfaces | Rationale |
|---|---|---|
| **1 (foundation, 1a candidate)** | `/m/` auth + shell + bottom-nav scaffold, `/m/home` (logged-in landing), `/m/knowledge-graph` filters/view-toggle parity | Without auth + nav, every other tier is blocked. Without `/m/home`, a logged-in user has nowhere to land after sign-in. |
| **2 (knowledge surfaces)** | `/m/zettels` (browse + search + filter), `/m/profile` (avatar + stats + trash recovery) | Once authed, user needs to see their corpus and manage account. |
| **3 (knowledge actions)** | `/m/rag` (chat with KB), `/m/kastens` (create + manage) | Higher-complexity surfaces. Chat composer + transcript on mobile is its own UX problem. |
| **4 (commercial + marketing)** | `/m/pricing` (mobile-friendly Razorpay), `/m/about` | Important for conversion but lowest user-flow priority. |
| **5 (experimental)** | `/m/nexus` | Flag-gated even on desktop. |

---

## 5. Constraints to honor (from CLAUDE.md + memory)

- Teal accent only on mobile (mobile.css `--accent: hsl(172,66%,50%)` ✓ already correct)
- Amber/gold reserved for `/knowledge-graph` only ✓ already correct
- Never purple ✓
- No infra disclosure in user-facing UI (no model name, tokens, latency, scores) — applies to any new mobile surface, especially RAG composer
- Production change discipline: every mobile addition must be backward-compatible; redirect behavior changes need explicit operator approval
- Pricing flow: never pre-prompt for phone — Razorpay hosted checkout collects contact itself
- DigitalOcean droplet is 2 GB RAM / 1 vCPU; each new mobile route is an additional template render. Cost negligible vs existing surfaces, but any added JS payload should be measured (currently `/m/` is ~7 KB JS + 0 vendor, `/m/knowledge-graph` is ~12 KB JS + ~600 KB vendor for three+ForceGraph3D)
- Cross-tenant denial / RLS / auth gates must extend to mobile-specific endpoints if any are added; reuse existing `/api/*` endpoints whenever possible

---

## 6. Open questions for operator (locked in §7 once answered)

1. **Iteration 1a scope** — accept the Tier-1 proposal (auth + shell + `/m/home` + `/m/knowledge-graph` parity)? Or different cut?
2. **Mobile navigation pattern** — bottom-tab bar (iOS/Android standard 2025), hamburger menu, or hybrid (top header + bottom tabs)?
3. **Auth surface** — mirror desktop's OAuth provider grid in a full-screen mobile modal, or use a dedicated `/m/sign-in` page? (Affects routing + share-ability.)
4. **PWA** — in scope for 1a, deferred to 1b, or out-of-scope entirely?
5. **`_is_mobile()` opt-out** — add a "Desktop version" cookie/query-param escape that actually bypasses the redirect? (M3.1 + M3.2.)
6. **Existing-page fixes** — fix the M1.* and M2.* deficiencies in 1a, or defer all UX polish to a 1b and treat 1a as new-pages-only?

---

## 7. Locked scope (operator answer 2026-05-24)

**Q1 = B (Polish + auth + nav shell).** No net-new content pages this PR.
**Q2 = C (Hybrid: top header + bottom-tab bar).**
**Q3 = A (Mirror desktop modal — full-screen mobile OAuth grid).**
**Q4 = PWA manifest + service-worker only.** "Request Desktop Site" escape (M3.2) and explicit identity-propagation backfill (M3.4) deferred. Identity propagation is treated as implicit-in-auth (header avatar + sign-out must appear post-sign-in for auth to be meaningful) — flagged for explicit confirmation in next turn.

### 7.1 In-scope items

**Existing-page polish (mobile-only):**
- M1.4 loader parity — port skeleton typewriter or stay rotating text → **C3 clarification**
- M1.5 result actions — verify desktop has only Copy + Source → if more, port (post-scout)
- M1.6 empty-state CTA on `/m/` after successful summarize
- M1.7 source-select label parity ("Newsletter" → keep label but align value with desktop)
- M1.8 broken "Desktop version" footer link — hide or relabel until 1b adds escape → **C1 clarification**
- M2.1 add Global ↔ Personal view toggle to `/m/knowledge-graph`
- M2.2 add tags + kastens + connection-strength filters (mobile-adapted layout) — design depends on R4
- M2.3 add search count + clear button to `/m/kg`
- M2.4 add reset-view button to `/m/kg`
- M3.3 extract shared mobile shell (header + footer + meta + viewport) — required because we're adding bottom-tab bar across both pages

**Auth UI:**
- OAuth provider grid mirroring desktop (Google / GitHub / Apple / Twitter / Facebook / Twitch — verify final list post-scout)
- Full-screen mobile modal triggered from header (avatar pill when out, avatar+menu when in)
- Signed-in state surfaces in header (avatar + dropdown w/ Sign out) — implicit-in-auth per operator's Q1=B
- Sign-out flow + post-sign-out redirect

**Nav shell (hybrid):**
- Top header: logo + page title + auth pill/avatar
- Bottom-tab bar: 4-5 tabs — exact tab list depends on R2 + **C2 clarification** (do unbuilt tabs show as disabled, hidden, or are we limiting to 2-3 working tabs in 1a?)

**PWA:**
- `manifest.json` (icons, theme color, display mode, start URL, scope)
- Minimal service worker (cache shell + static assets; do NOT cache `/api/*` in 1a)
- Install-prompt UX (banner pattern TBD by R6)
- Droplet cost: SW adds nothing server-side; manifest is a static file

### 7.2 Explicitly out-of-scope (deferred to 1b+)

- `/m/home`, `/m/zettels`, `/m/profile`, `/m/rag`, `/m/kastens`, `/m/pricing`, `/m/about`, `/m/nexus`
- "Request Desktop Site" escape (M3.2)
- Tablet-as-desktop heuristic (M3.1 / iPadOS 13+ false-positives)
- Mobile-side `/api/*` extensions
- Razorpay mobile flow
- RAG composer UX

### 7.3 Open clarifications before plan-write

- **C1**: M1.8 — hide "Desktop version" link or relabel to "Coming in 1b"?
- **C2**: Bottom-tab list for 1a — 5-tab placeholder (Capture / Notes / Chat / Graph / Profile, disabled-where-empty), 2-tab working cut (Capture / Graph), or other?
- **C3**: M1.4 loader — port desktop skeleton typewriter to mobile in 1a, or stay with current rotating-text?

---

## 8. Research questions (queued for parallel web-search subagents post-scope-lock)

Per operator-supplied research methodology: industry-standard + <5yr articles + our use case + infra-safety verification. Will be dispatched only after §7 is locked.

Probable batch (subject to scope):

- R1. Mobile-web auth UX 2025 — OAuth modal vs dedicated page, social-provider grid on mobile, accessibility constraints (44pt tap targets, screen-reader flow), Google's "One Tap" applicability.
- R2. Mobile navigation 2025 — bottom-tab vs hamburger vs hybrid; recent research on discoverability + ergonomics; what major news/SaaS PWAs do (Substack, Reddit mobile-web, Notion mobile).
- R3. Mobile RAG chat composer patterns — text-area sizing on iOS Safari w/ keyboard open, auto-grow vs fixed, suggested-questions chips, attachment affordance.
- R4. Mobile KG / network-viz interactions — touch panning + pinch-zoom on ForceGraph3D, fallback to 2D on low-end devices, accessibility (labels for screen readers).
- R5. Razorpay mobile-web checkout 2025 — hosted-checkout iframe vs Razorpay Standard Checkout SDK on small viewports, autofill of contact, returning-customer flow.
- R6. PWA cost-benefit 2025 — manifest + service-worker overhead on a 2 GB / 1 vCPU droplet; offline KG view feasibility.
- R7. Mobile UA detection regression risks — false-positives on iPad-as-desktop (iPadOS 13+), foldables, and the meaningful escape hatches modern sites use (Apple Safari "Request Desktop Site").

---

## 9. Verification plan (post-implementation)

Will be expanded per 1a scope. Default outline:

- Local pytest (`pytest -m "not live"`) — must remain green
- Lint pass at end of plan only (per memory: "Batch ruff at end of plan")
- Manual: Claude in Chrome viewport-emulation pass on each new/touched mobile page (iPhone 14 Pro, Pixel 7, iPad Mini)
- Manual: real-device test on operator's device before merge
- Production parity: confirm anonymous user flow on `/m/` still works post-merge (do not break the unauthed summarize path)
- Verify no new RAM-hotspot on droplet (`free -h` before/after deploy)
