# P1 Fix Research — Industry-Standard Solutions (6 of 7 P1 issues; excludes #2 model-tier leak)

**Date:** 2026-06-01 · **Method:** web-fetch of vetted sources (OWASP, Material 3, Tailwind, Stripe/Slack/GitHub eng, SWR/TanStack) + grounding against our actual codebase · **Stack:** async FastAPI + Supabase/Postgres · no-framework vanilla-JS frontend (`zk_fetch.js` wrapper) · single 2 GB/1 vCPU DigitalOcean droplet, Caddy + Cloudflare, Docker blue/green · 10k+/user scale target.

Per issue: **Industry standard → Recommended fix (our stack) → Avoid (deprecated) → Trade-offs → Side-effects/regression risk → Citations.**

---

## PRF-1 — Profile "Danger Zone" leaks internal source path + build status

**Where:** `website/features/user_profile/index.html` lines 213–218 — a help `<p>` prints *"Account deletion is staged in `website/core/account_purge.py` but no production endpoint is wired yet,"* plus a `title` attr narrating build status. The button is **dead UI** (no handler in `user_profile/js/user_profile.js`, no route). `account_purge.py` is a real helper deliberately unwired.

**Industry standard:** OWASP is unambiguous — clients get neutral copy; all internal detail (file paths, directory structure, build/impl status) stays server-side. *Improper Error Handling* names "the site's directory structure" as reconnaissance-aiding disclosure; *A05:2021 Security Misconfiguration* Scenario #3 + Error-Handling Cheat Sheet treat a leaked path (`D:\app\index_new.php`) as the canonical worst case. For unbuilt features, major products (LaunchDarkly, GitHub, Stripe) **feature-flag the entry point so it doesn't render** until shipped (Fowler: a Release Toggle "hides the button," kept short-lived). Deliberate "coming soon" teasers use benefit copy with zero system language (Emplifi empty-state UX).

**Recommended fix (smallest correct):** Delete the path-disclosing help `<p>` (215–217) **and** the inert `#profile-delete-account` button + status `title` (213) from `index.html` — a "Keystone Interface" (build everything except the UI entry point). Keep "Sign out" (real). *If* a teaser is wanted: neutral copy only — `<button … disabled aria-disabled="true" title="Account deletion is coming soon.">Delete account</button>` + optional "Permanent account deletion is coming soon." When the real feature lands, gate it with a **server-authoritative** flag matching your existing `experimental_features` convention (`settings.py:32`): add `account_deletion_enabled: bool = False`, render the control only when true, and the eventual `POST /api/account/delete` route **must re-check flag + auth server-side** before `account_purge` → `auth.admin.delete_user` (hiding the button is never the security boundary). **Regression net:** a unit test in `tests/unit/website/` asserting the served profile HTML contains neither `"account_purge"` nor `"website/core/"`.

**Avoid:** hard-coding impl status / "not wired yet" / file-path breadcrumbs in templates (OWASP A05 #3, CWE-756); leaving permanently-disabled dead controls with internal copy instead of a flag.

**Trade-offs:** Removal = zero-leak, lowest-risk, but no "planned" signal; neutral teaser keeps the signal at the cost of one element to maintain. A flag now is mild over-engineering for one button but is cheap and becomes the kill switch + server gate later — or just delete the markup today and add the flag in the PR that builds the endpoint.

**Side-effects (tiny, contained):** Static-template edit only — touches **none** of the protected infra (no `zk_fetch.js`, no endpoint, no Supabase query, no graph refetch, no Gunicorn/Caddy knobs). Cloudflare may serve the old leaking HTML briefly → purge the profile page or rely on HTML cache TTL. Blue/green: change is in the image, goes live atomically. If flag-gating: must **fail closed** (missing/false → hidden + route 403/404).

**Citations:** [OWASP Improper Error Handling](https://owasp.org/www-community/Improper_Error_Handling) · [OWASP A05:2021](https://owasp.org/Top10/2021/A05_2021-Security_Misconfiguration/) · [OWASP Error Handling Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html) · [Fowler — Feature Toggles](https://martinfowler.com/articles/feature-toggles.html) · [Unleash best practices](https://docs.getunleash.io/guides/feature-flag-best-practices) · [Emplifi empty-states UX](https://soul.emplifi.io/latest/content/ux-writing-patterns/empty-states-JArDj65M) · [LaunchDarkly Flags 101](https://launchdarkly.com/blog/what-are-feature-flags/)

---

## V-1 + V-4 — No design-token scale → inconsistent radius (48/48/16/16 cards) + 2–3× whitespace drift

**Root cause:** no single token scale, so radius/spacing are hand-typed per component and drift. (V-1 cards 48px-top/16px-bottom, applied inconsistently; V-4 header→content gap 50px best vs 117px worst.) Both are token-governance failures — fixing literals without a scale + linter lets drift recur.

**Industry standard:** every major system ships a small **fixed, named** scale and forbids raw literals. Material 3 radius: 0/4/8/12/16/28 dp; **all M3 card types use the medium token = 12dp, symmetric** — there is **no asymmetric-corner default card** (asymmetry is reserved for deliberate directional shapes). Tailwind: `--radius-xs..4xl` (2→32px) + spacing base `--spacing:4px`. Spacing standard = **8px grid** (8/16/24/32/48/64…), 4px only for tight intra-component gaps. Bootstrap/Primer/Carbon/Polaris all do the same.

**Recommended fix:** (1) One token file `website/static/css/tokens.css` on `:root` — `--radius-sm..2xl` (4→24) + `--space-1..16` (8px grid) + **`--space-section:48px`** (the canonical header→content gap). (2) **V-1:** replace the card's `border-radius:48px 48px 16px 16px` with **`border-radius:var(--radius-xl)`** (16px, symmetric); if a directional card is truly wanted, make it one documented `.card--directional`. (3) **V-4:** set the first content wrapper of every page template to `margin-top:var(--space-section)` and **delete the per-page literals** → identical rhythm everywhere. (4) **Enforce** with off-the-shelf [`stylelint-declaration-strict-value`](https://github.com/AndyOGo/stylelint-declaration-strict-value) (forces `var()` on `border-radius`,`/^margin/`,`/^padding/`,`gap`; `ignoreValues:[0,auto,inherit]`, `expandShorthand:true`) as a CI step next to pytest. Pure static CSS — no Python/FastAPI/Supabase touched.

**Avoid:** Sass/Less `$vars` (superseded by native CSS custom properties — no build step, ideal for no-framework); hand-typed per-component px; asymmetric corners on generic cards; 5/10/15px off-grid spacing; relying on a global reset alone (only a shared variable stops per-template drift).

**Trade-offs:** one scale kills both bugs + prevents recurrence at zero runtime cost; **but** every existing radius/margin/padding/gap literal must migrate to a `var()` or the new lint rule fails CI on first run (land token migration + stylelint config in the **same PR**). Picking the canonical numbers (16px radius, 48px gap) is a one-time design call.

**Side-effects:** Visual-only, no backend. QA `/home`, `/knowledge-graph`, **`/m/`** mobile templates (a global gap var shifts several pages at once — that's the fix; confirm nothing relied on the old large gap for absolute positioning). **Do not** sweep a color literal during the card refactor — `/knowledge-graph` stays amber, Kasten/chat stay teal. Fingerprint/version the CSS asset (or purge CF) so blue/green doesn't mix new HTML classes with a stale cached stylesheet. Stylelint lints `.css` only → grep templates for inline `style="border-radius…"` stragglers. Zero scaling impact.

**Citations:** [M3 corner-radius scale](https://m3.material.io/styles/shape/corner-radius-scale) · [M3 Cards specs (12dp symmetric)](https://m3.material.io/components/cards/specs) · [Tailwind theme tokens](https://tailwindcss.com/docs/theme) · [8px grid](https://www.thehangline.com/8px-grid-spacing-system-explained-for-web-designers/) · [stylelint-declaration-strict-value](https://github.com/AndyOGo/stylelint-declaration-strict-value) · [RhythmGuard stylelint plugin](https://dev.to/petrilahdelma/enforcing-your-spacing-standards-with-rhythmguard-a-custom-stylelint-plugin-1ojj)

---

## V-2 — Footer native `<button>` shows browser-default chrome (missing reset)

**Root cause:** a footer icon is a real `<button>` (correct — actions fire on Enter **and** Space) but inherits no styling, so the UA paints grey fill + outset bevel + Firefox `::-moz-focus-inner`. Sibling `<a>` icons never had native chrome. Keep the `<button>`; add a reset.

**Industry standard:** keep native `<button>`, strip chrome with a small reset class, name it via `aria-label`, mark the SVG decorative, give a `:focus-visible` ring. Sara Soueidan's canonical pattern: `<button>` + `svg[aria-hidden][focusable=false]` + the accessible name **on the button, not the SVG**. GitHub Primer (`IconButton`), Material icon button, Bootstrap reset all "use a real button, then reset it" — never a `<div>` or `<a>` faking a button.

**Recommended fix:** one reusable class in the **shared global sheet** (same one styling the `<a>` icons):
```css
.icon-btn{ appearance:none; -webkit-appearance:none; background:transparent; border:0; margin:0;
  padding:.35rem; color:inherit; font:inherit; line-height:0; cursor:pointer;
  display:inline-flex; align-items:center; justify-content:center; }
.icon-btn::-moz-focus-inner{ border:0; padding:0; }
.icon-btn svg{ width:1.25rem; height:1.25rem; fill:currentColor; display:block; }
.icon-btn:focus-visible{ outline:2px solid currentColor; outline-offset:2px; border-radius:4px; }
@supports not selector(:focus-visible){ .icon-btn:focus{ outline:2px solid currentColor; outline-offset:2px; } }
```
Apply `class="footer-icon icon-btn"` (keep existing sizing class) + `type="button"` + `aria-label="…"`; SVG gets `aria-hidden="true" focusable="false"`. Use the **teal** site accent for the outline (not amber). All Baseline-since-2022, safe unprefixed behind the CDN.

**Avoid:** `outline:none`/blanket `:focus` removal (WCAG fail); `appearance:none` behind only vendor prefixes; `aria-label` on the `<svg>` (fails in some SR combos); `all:unset` (also kills the focus ring + button type — needs `outline:revert` to fix).

**Trade-offs:** one class fixes the footer button + all future icon buttons and keeps `<button>` semantics. Must remember to add the class on new icon buttons (or scope a footer-level selector). Verify outline ≥3:1 contrast vs footer bg (WCAG 1.4.11).

**Side-effects:** Front-end only. **Selector-collision risk** — grep for existing `.icon-btn`/bare `button{}` rules so the new class doesn't restyle other buttons (prefer the explicit class over a bare-element reset). Ensure a non-empty accessible name post-reset (else unlabeled-button a11y regression). `line-height:0` is icon-only — never put it on a text-button reset. CF CSS cache: ship fingerprinted/version-busted.

**Citations:** [Sara Soueidan — Accessible Icon Buttons](https://www.sarasoueidan.com/blog/accessible-icon-buttons/) · [MDN appearance](https://developer.mozilla.org/en-US/docs/Web/CSS/appearance) · [MoOx button reset gist](https://gist.github.com/MoOx/9137295) · [ModernCSS button guide](https://moderncss.dev/css-button-styling-guide/) · [MDN :focus-visible](https://developer.mozilla.org/en-US/docs/Web/CSS/:focus-visible) · [ModernCSS icon-button guide](https://moderncss.dev/icon-button-css-styling-guide/)

---

## H-1 — Home over-fetches the full zettel list to show 3 cards + a count

**Where:** `zettels_routes.py::list_zettels` (line 1467) defaults `limit=5000` and builds a heavy `ZettelListItem` (both summaries, tags, URLs, dates) per row. `home.js::loadZettels` (387) downloads it all → `slice(0,3)`; `home.js::refreshMyZettelsBadge` (1092) fetches the **same full endpoint again** just for `.length`. So the full corpus is pulled **twice** to render 3 cards + a number (~15 MB ×2 at 10k, JSON-serialized on a 2 GB droplet). `detailed_summary` dominates bytes and is never rendered on `/home`.

**Industry standard:** "few recent + a count" = three cheap separate concerns, never one fat list. **Stripe:** `limit` (def 10/max 100) + `starting_after`/`ending_before` object-id cursors, `{data, has_more, url}`, **no total count**. **Slack:** opaque base64 cursors over an indexed key; abandoned `LIMIT/OFFSET` (reads offset+count rows; skips/dupes under concurrent writes); dropped totals. **GitHub:** `per_page` + `Link` header, no total. **Field selection / sparse fieldsets:** `?fields=…` allowlist → `SELECT col,col` pushdown.

**Recommended fix (3 additive parts):** (1) **`GET /api/zettels/recent?limit=3`** returning preview fields only — `id,title,title_ready,source_type,source_url,added_at` (drop summaries/tags). Reuse `content_repo.list_workspace_zettels(ws_id, limit=limit+1)` (already `ORDER BY created_at DESC, id DESC`), fetch `limit+1` for `has_more`, base64 `(created_at,id)` `next_cursor` (future "load more"). Tighten the repo `.select(...)` to preview columns (or a `…_preview()` sibling) so heavy summary columns never leave Postgres. (2) **`GET /api/zettels/count`** → `{count}` via PostgREST `select("id", count="exact").limit(0)` (head request) + `Cache-Control: private, max-age=30`. (3) **`home.js`**: `loadZettels` → `/recent` (drop client `.sort()`), `refreshMyZettelsBadge` + `kg-node-count` → `/count`; coalesce the count call via `zk_fetch.js` (see PR-1/KG-1). **Keep `GET /api/zettels` untouched** for `/home/zettels` (back-compat).

**Avoid:** page-number + total-count pagination (`?page=N` + `total`) on hot paths — forces `COUNT(*)` + deep `OFFSET` (≈17× slower at 1M rows, drifts under inserts); exposing a precise grand-total on a hot path (compute lazily/approx via `pg_class.reltuples`, or drop). Keyset = "next page"; exact count is a separate, rare query — never couple them.

**Trade-offs:** home load drops from ~2× full-corpus to a `LIMIT 4` read + cached count (MB → <1 KB at 10k; serialization spike gone). Cost: 2 new endpoints + repo method + tests (additive). Exact count cheap when index-only + cached + rare; downgrade to approximate if it ever gets hot. Keyset = forward "load more" only (fine for a feed; full vault keeps offset).

**Side-effects:** **Count staleness** — 30s TTL can lag a just-added zettel; today's code refetches on add-success/visibility → bust/skip cache there. Cache **must be `private`** (per-user), never shared at CF edge (same rule as `_terminal_cache_headers`). The graph's legitimate Global/Personal refetch is a **different** endpoint — don't route it through preview/count (graph needs full node sets). `refreshMyZettelsBadge` now reads `{count}` not `data.zettels.length` — update shape handling or it silently shows 0. Same `get_optional_user` path → 401/empty-scope returns empty `{items:[]}`/`{count:0}`, never 500. Blue/green: additive endpoints + JS, old containers keep serving `/api/zettels` — mid-deploy color mix is safe. Update fakes in `test_zettels_list_api.py` + `test_kg_payload.py`.

**Citations:** [Stripe pagination](https://docs.stripe.com/api/pagination) · [Slack — Evolving API Pagination](https://slack.engineering/evolving-api-pagination-at-slack/) · [API responses 40× larger](https://dev.to/polliog/your-api-responses-are-40x-larger-than-they-need-to-be-5p4) · [Sparse fieldsets (OneUptime)](https://oneuptime.com/blog/post/2026-01-30-api-field-selection/view) · [GitHub REST pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api) · [Keyset pagination (OneUptime)](https://oneuptime.com/blog/post/2026-02-02-keyset-pagination/view)

---

## PR-1 + KG-1 — Duplicate concurrent GETs (`/api/me` ×4-5, `subscriptions/me` ×2, `/api/graph` ×2)

**Root cause:** no-framework → each per-feature `.js` calls `zkFetch()` independently, no shared cache (the auto-dedup SWR/React-Query give for free is absent). `zk_fetch.js` currently coalesces **only** the auth refresh (`refreshInFlight`, lines 231-235), not data GETs. Two sub-problems: (a) truly concurrent identical GETs → in-flight Promise coalescing; (b) near-concurrent repeats + double-mount → short-TTL cache + a mount guard.

**Industry standard:** an **in-flight Promise cache** (Map keyed by method+url): first call stores the promise, later callers get the same promise, key deleted in `finally`. OneUptime `RequestCoalescer` is exactly this; `fetch-dedupe` productizes it (reads the one-shot Response body once, shares parsed data). SWR dedups same-key calls within `dedupingInterval` (**default 2000ms** — only the first mounted hook fires); TanStack shares promises by query key. Auth angle = single-flight refresh (one module `tokenPromise`, reset in `.finally()`) — **already** the `refreshInFlight` idiom in `zk_fetch.js`.

**Recommended fix (inside `zk_fetch.js`, ~40 lines):**
1. **Coalescing map** — make `zkFetch` a front door over `zkFetchUncoalesced`; for `GET` only, key on `method+url`; if in-flight, return the shared promise **`.then(r => r.clone())`** (a Response body is a one-shot stream — `clone()` per consumer is the #1 correctness gotcha); delete the key in `finally` (self-empties, no TTL, no memory growth). Collapses ×4-5 `/api/me` and ×2 `/api/graph` to **one** call each when same-tick.
2. **Opt-in short-TTL cache** for hot idempotent GETs: `zkFetch('/api/me', { zkCacheTtlMs: 2000 })` (mirror SWR's 2s; clone on hit). For `/api/me` the durable layer is already `ZKStatsCache` (etag) — this TTL is just the in-page burst collapser.
3. **Graph mount guard** (in the graph initializer, **not** `zk_fetch.js`): `let graphLoadInFlight=null; loadGraph({force=false})` reuses the in-flight promise on mount but **`loadGraph({force:true})`** on the Global/Personal button — the explicit bypass is essential (SWR #532: `revalidate()` intentionally ignores dedup) so the legitimate refetch still works.

**Avoid:** a boolean `isLoading` flag to "prevent double fetch" (races, drops the 2nd caller's result — store the **promise**, not a flag); long-lived client GET caches without invalidation (keep the window short, let etag/304 — `functional_gates/etag.py`, PR #133 — handle durable caching); reading a shared Response body without `clone()` ("body stream already read"); keying on URL alone (must include method so a POST never merges with a GET).

**Trade-offs:** coalescing = near-zero cost, self-cleaning, invisible to single-caller pages (only price = the mandatory `clone()`). TTL cache = opt-in, bounded blast radius (1.5-3s staleness for rarely-changing `/api/me`/`subscriptions`). Mount guard = a few lines + thread a `force` flag. **Rejected alternative:** a client cache library (pulls a framework into a deliberately no-framework FE for what ~40 lines solve) and a backend fix (the dupes originate client-side).

**Side-effects:** Coalesce strictly at the **GET front door** so the existing 401→single-flight-refresh→replay (lines 221-260) still runs per logical request; never coalesce when `init.zkNoDedupe` is set (use for GETs whose `Authorization` differs per caller). TTL: only tag read-only bootstrap GETs; **never cache `/api/payments/*` across a checkout** (clear/skip after any payment mutation); TTL ≤3s. Graph: verify the toggle still issues a fresh `/api/graph` after the fix (the documented SWR #532 failure is dedup swallowing an intentional refetch). `clone()` buffers the body until read → ensure **every** coalesced consumer calls `.json()` (unread clones linger in client memory; matters for the large `/api/graph` payload). **POST/mutation safety:** the `method!=='GET'` guard guarantees Add-Zettel + payment POSTs are never coalesced/cached. CF edge + blue/green: unaffected (pure client-side JS, idempotent via the `if(window.zkFetch) return` guard at line 33).

**Citations:** [Request Coalescing (OneUptime)](https://oneuptime.com/blog/post/2026-01-30-request-coalescing/view) · [fetch-dedupe (npm)](https://www.npmjs.com/package/fetch-dedupe) · [Single-flight token refresh](https://dev.to/graciesharma/youre-probably-refreshing-auth-tokens-wrong-heres-a-40-line-fix-11f6) · [SWR dedup explained](https://dev.to/andykao1213/how-to-understand-the-request-deduplication-in-swr-28bb) · [SWR #532 — force bypass](https://github.com/vercel/swr/discussions/532) · [SWR vs TanStack (LogRocket)](https://blog.logrocket.com/swr-vs-tanstack-query-react/) · [TanStack defaults](https://tanstack.com/query/v4/docs/framework/react/guides/important-defaults)

---

## Cross-cutting notes

- **3 of 6 fixes are pure static front-end** (PRF-1 template edit, V-1/V-4 tokens, V-2 reset) — no Python/API/DB, no protected-infra knobs, ship in the image on blue/green. Common gotcha: **fingerprint/version CSS+HTML assets (or purge Cloudflare)** so the edge doesn't serve stale.
- **H-1 + PR-1/KG-1 share the `zk_fetch.js` coalescing change** — do them together; the coalescing map also de-dupes H-1's new count call. All endpoint work is **additive/back-compatible** (keeps `/api/zettels`, no contract break → blue/green safe).
- **Recurring non-negotiable:** client-side hiding/dedup is presentation only — server-side auth/flag enforcement (PRF-1 delete route) and per-user `private` caching (H-1 count, never CF-edge-shared) remain the real boundaries.

_Sourcing originally surfaced by the deep-research harness (fetch step failed there); re-fetched + verified + codebase-grounded via a custom workflow. All claims tied to a fetched source above._
