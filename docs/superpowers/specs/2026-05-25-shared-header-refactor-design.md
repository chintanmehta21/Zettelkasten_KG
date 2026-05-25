# Shared Header Refactor — Design Spec

**Date:** 2026-05-25
**Status:** Brainstorm approved (Chunks 1-3) — awaiting spec review → writing-plans
**Author session:** thirsty-bell-f6a7c3
**Related code:** `website/features/header/`, `website/features/user_home/`, `website/features/knowledge_graph/`, `website/footer/pricing/`, `website/app.py`

---

## 1. Summary

Rebuild the shared website header so that:

1. **Seven pages** share one canonical header fragment (`header.html`) — `/home`, `/home/zettels`, `/home/kastens`, `/home/rag`, `/home/nexus`, `/profile`, `/pricing`. A change to the fragment reflects everywhere automatically.
2. **`/knowledge-graph` is carved out** of the shared header and keeps its dedicated `kg-header` only (today both render stacked — that bug gets fixed by this carve-out).
3. **Dropdown items are per-page dynamic.** The current page is removed; on `/home` only, Zettels/Kastens/KG are also removed because they're already primary on-screen buttons. "Dashboard" is renamed to "Home". A new "Store" item links to `/pricing`.
4. **Anon users on `/pricing`** see a random avatar (fresh every page-load, no localStorage cache); clicking the avatar opens the existing `#login-modal` directly rather than a dropdown.
5. **Single source of truth** for menu items: one Python config (`website/config/page_menus.py`) consumed by FastAPI's existing `_render_with_shell` substitution.
6. **Dedupe** the historical inline `/home` header and the `home-`-prefixed ID workaround in `header.js`.

## 2. Background — current state (verified end-to-end this session)

| Area | Today |
|---|---|
| Header injection | `_render_with_shell` ([app.py:69-88](../../website/app.py#L69-L88)) replaces `<!--ZK_HEADER-->` placeholder with `header.html` body. Falls back to raw page if no placeholder. |
| Dropdown rendering | **Static HTML** in `header.html` (lines 28-75). No JS render, no template — per-page customisation impossible without architectural change. |
| `header.js` | Wires *behaviour only* (avatar load, dropdown open/close, sign-out). Bound by IDs `avatar-*`. **Forked** at lines 28-32 to also accept `home-avatar-*` IDs for `/home`'s private duplicate header. |
| `/home` | Hand-rolled inline `<header class="header">` at `user_home/index.html:20-64` with `home-`-prefixed IDs to dodge collisions. Functionally narrower: no back-button, only Profile/Nexus/Sign-out in dropdown. `home.js:137-158` binds the duplicate IDs independently. |
| `/knowledge-graph` | ⚠ **Renders BOTH headers today**: `<!--ZK_HEADER-->` at line 15 *and* its own `<header class="kg-header">` at lines 18-93. Two headers stack on top of each other. |
| `/pricing` | Publicly accessible (anon users can land via marketing links). Has its own inline `#login-modal` for the buy-CTA 401 flow. Currently shows the authed dropdown to anon users — they see items they can't access. |

## 3. Goals · non-goals

**Goals:**
- One canonical `header.html` for the 7 pages; one edit propagates everywhere
- Per-page dropdown items declared in one Python file, server-rendered at request time
- Fix the KG stacked-headers bug by removing the shared header from KG
- Delete the inline-`/home`-header / ID-fork debt
- WCAG 2.2 / WAI-ARIA 1.2 compliant menu-button (kept from current header.js)

**Non-goals (explicitly deferred per "Deferral Is A Decision"):**
- KG sign-out access from within `/knowledge-graph` (today an accidental side-effect of the stacked headers; carve-out removes it. Acknowledged.)
- Mobile parity (mobile uses separate `mobile/templates/_shell.html` — out of scope)
- Visual regression tooling (Playwright snapshot / Percy / Chromatic — add later if drift appears)
- Cmd-K command palette (industry standard pattern; not in this iteration)
- Adding RAG to the menu (not in user spec; current header also omits it — no change)

## 4. Architecture

```
┌──────────────────────────┐
│  Route (FastAPI)         │   passes page_key="zettels"
│  /home/zettels           │──────────────┐
└──────────────────────────┘              │
                                          ▼
┌──────────────────────────────────────────────────────┐
│  _render_with_shell(page_html, page_key)             │
│   1. Look up PAGE_MENUS[page_key] → PageMenu         │
│   2. Render items into <!--HEADER_DROPDOWN--> slot   │
│   3. Render/skip back-button into <!--BACK_BTN-->    │
│   4. Substitute <!--ZK_HEADER--> in page_html        │
└──────────────────────────────────────────────────────┘
                                          │
                                          ▼
                  HTML response — pre-styled, no client render needed
```

Server-side substitution is the architecture winner for our FastAPI + vanilla-JS stack per research (zero flicker, single source of truth, plain `<a>` semantics, Pydantic-validatable, no new runtime dep). Rejected alternatives (with reasons): JS registry (flicker/drift), slot-based HTML (copy-paste drift), Web Components (FOUC + dep), HTMX/Alpine (new runtime dep). See §15 for sources.

## 5. Per-page menu config

### 5.1 Config shape

```python
# website/config/page_menus.py
from typing import Literal, TypedDict

class MenuItem(TypedDict):
    key: str             # canonical id (home, zettels, kastens, kg, nexus, profile, store, signout)
    label: str
    href: str            # blank for signout (button)
    icon: str            # inline SVG markup or mask-url asset path
    labs: bool           # optional "Experimental" pill; default False

class PageMenu(TypedDict):
    authed: list[MenuItem]
    anon: list[MenuItem] | None             # only /pricing populates this
    anon_avatar_action: Literal["open-login-modal", "none"] | None
    show_back_button: bool                  # True everywhere except /home

PAGE_MENUS: dict[str, PageMenu] = { ... }
```

### 5.2 Item canonical registry (one definition, referenced by key)

| key | label | href | icon | labs |
|---|---|---|---|---|
| `home` | Home | `/home` | inline home glyph | — |
| `zettels` | My Zettels | `/home/zettels` | `--mask-url:url(/artifacts/logo-zettelkasten.svg)` | — |
| `kastens` | My Kastens | `/home/kastens` | `--mask-url:url(/artifacts/logo-kastens.svg)` | — |
| `kg` | Knowledge Graph | `/knowledge-graph` | `--mask-url:url(/artifacts/logo-knowledge-graph.svg)` | — |
| `nexus` | Nexus | `/home/nexus` | inline atom glyph | ✓ |
| `profile` | My Profile | `/profile` | inline user glyph | — |
| `store` | Store | `/pricing` | **inline SVG bag/tag glyph (new)** | — |
| `signout` | Sign out | (button) | inline logout glyph | — |

### 5.3 Per-page matrix

| `page_key` | Authed items (in order) | Anon items | `show_back_button` |
|---|---|---|---|
| `home` | Nexus · My Profile · Store · Sign Out | — | **False** |
| `zettels` | Home · My Kastens · Knowledge Graph · Nexus · My Profile · Store · Sign Out | — | True |
| `kastens` | Home · My Zettels · Knowledge Graph · Nexus · My Profile · Store · Sign Out | — | True |
| `rag` | Home · My Zettels · My Kastens · Knowledge Graph · Nexus · My Profile · Store · Sign Out | — | True |
| `nexus` | Home · My Zettels · My Kastens · Knowledge Graph · My Profile · Store · Sign Out | — | True |
| `profile` | Home · My Zettels · My Kastens · Knowledge Graph · Nexus · Store · Sign Out | — | True |
| `pricing` | Home · My Zettels · My Kastens · Knowledge Graph · Nexus · My Profile · Sign Out | **(no dropdown; avatar opens login modal)** | True |

Rule: drop the current page's own item; on `/home` only, also drop Zettels/Kastens/KG (already primary on-screen buttons).

## 6. KG carve-out

| Step | File | Change |
|---|---|---|
| 1 | `website/features/knowledge_graph/index.html` | Delete line 15 (`<!--ZK_HEADER-->`). Keep dedicated `<header class="kg-header">` at lines 18-93 unchanged. |
| 2 | `website/app.py` line 556 | Replace `_render_with_shell(KG_DIR / "index.html")` with `_html_file_response(KG_DIR / "index.html")` (same shape as `/auth/callback`) |
| 3 | None | No CSS / JS changes — `kg-header` styling self-contained |

**Acknowledged side-effect:** today's KG users can sign out via the accidentally-stacked shared header. After this PR they need to navigate back to `/` first. Out of scope per "keep `kg-header` as-is" instruction.

## 7. `/home` migration

| Step | File | Change |
|---|---|---|
| 1 | `website/features/user_home/index.html` lines 19-64 | Delete inline `<header class="header">…</header>`. Replace with `<!--ZK_HEADER-->`. |
| 2 | `website/features/user_home/index.html` line 12 | Keep `<link href="/header/css/header.css">` — still the source of header styling |
| 3 | `website/features/user_home/js/home.js` lines 137-158 | Delete `home-`-prefixed DOM resolution (avatarBtn/avatarImg/avatarFallback/avatarDropdown/avatarWrap/menuProfile/menuNexus/menuSignout locals). Owned by shared `ZKHeader` now. |
| 4 | `website/features/user_home/js/home.js` init flow | Replace direct sign-out wiring with `window.ZKHeader.onSignOut(supabaseSignOutHandler)` |
| 5 | `website/features/header/js/header.js` lines 28-32 | De-fork: remove `|| document.getElementById('home-avatar-*')` fallbacks |
| 6 | `website/features/header/css/header.css` lines 54-115 | Audit (`grep -rn 'home-avatar-' website/`) → if zero non-CSS consumers, delete the `.home-avatar-*` block |
| 7 | `website/features/user_home/css/home.css` lines 40-41 | Update comment now the duplicate is gone |

## 8. Anon flow on `/pricing`

**Server-side:** identical rendering for anon and authed (server doesn't know auth state — Supabase JWT lives in localStorage, not cookies). Render the authed dropdown markup unconditionally, plus a `zk-anon-no-dropdown-default` CSS class on the dropdown wrap that hides it via `visibility: hidden` until JS clears it.

**Client-side, `/pricing` only:**

```
header.js boots
  └─ checks Supabase session
       ├─ AUTHED  → ① remove the hidden class
       │            ② normal dropdown behaviour
       │            ③ avatar URL: cached per existing logic
       └─ ANON    → ① keep dropdown hidden (CSS class stays)
                    ② avatar src = fresh random pick, NEVER read/write
                       localStorage cache (skip cacheKey for null profileId)
                    ③ swap avatar click handler: instead of toggling dropdown,
                       open #login-modal (already on /pricing, used by buy-CTA
                       401 flow)
```

**Concrete code changes in `header.js`:**
- `resolveAvatarUrl()` — when `profileId === null`, skip `readCached` AND `writeCached` (always fresh random)
- `ZKHeader.boot()` — new option `options.anonAction: 'open-login-modal' | 'none'` (default `'none'`)
- `bindAvatarDropdown()` — for anon with `anonAction === 'open-login-modal'`, swap the click handler to open `#login-modal`; do not remove the `zk-anon-no-dropdown-default` class

**Pre-JS race window mitigation:** the dropdown wrap is `visibility: hidden` in the rendered HTML. Authed JS removes the class; anon JS leaves it. A click on the avatar within the boot window has no visible dropdown to open.

## 9. Back-button conditional render

`header.html` will use a `<!--BACK_BTN_SLOT-->` placeholder where the back-button currently lives. `_render_with_shell` substitutes either the full back-button markup (when `show_back_button=True`) or an empty string. Only `/home` sets `show_back_button=False`.

## 10. Tests

| Test | Type | Coverage |
|---|---|---|
| `test_page_menus_config.py` | unit | Schema valid; every `page_key` has non-empty `authed`; only `pricing` has `anon`; no duplicate items per page; all icon keys valid; all hrefs match canonical registry |
| `test_render_with_shell.py` | unit | For each page_key, rendered HTML contains all expected `<a>` items in order; `<!--HEADER_DROPDOWN-->` and `<!--ZK_HEADER-->` substituted (no raw placeholder leftover); `<!--BACK_BTN_SLOT-->` substituted |
| `test_route_page_keys.py` | unit | Every shared-header route passes a `page_key` matching PAGE_MENUS; `/knowledge-graph` route uses `_html_file_response` (no page_key) |
| `test_home_shell.py` | unit | GET `/home` includes `<header class="header zk-header" data-zk-header>`; only Nexus/Profile/Store/Sign-out items; no back-button; no `id="home-avatar-btn"` (collision-free) |
| `test_kg_carve_out.py` | unit | GET `/knowledge-graph` does NOT contain `class="zk-header"` or raw `<!--ZK_HEADER-->`; DOES contain `class="kg-header"` |
| `test_pricing_anon.py` | unit | GET `/pricing` includes `class="zk-anon-no-dropdown-default"` on dropdown wrap; includes `#login-modal` |
| `test_back_button_per_page.py` | unit | `/home` rendered HTML has no `[data-zk-back]`; `/home/zettels` does |
| Playwright keyboard smoke | functional | Single test on `/home/zettels`: Tab → avatar → Enter opens, focus on first item, Down arrow moves, Escape closes + focus returns to button. Covers shared dropdown for all pages. |
| `scripts/check_html_unique_ids.py` | CI lint | Parse each shared-header page; assert no duplicate `id` attributes (regression guard for ID-collision class) |

## 11. PR strategy — TWO PRs

### 11.1 PR1 — Infrastructure + KG carve-out (zero UX change for the 6 currently-served pages)

**Scope:**
- Add `website/config/page_menus.py` with the **full schema from §5.1** (`PageMenu` TypedDict including `authed`, `anon`, `anon_avatar_action`, `show_back_button`)
- Add `PAGE_MENUS` entries for the 6 currently-served pages (`zettels`, `kastens`, `rag`, `nexus`, `profile`, `pricing`), each with **CURRENT static items** (Dashboard, My Zettels, My Kastens, Nexus, My Knowledge Graph, My Profile, Sign-out), `anon=None`, `anon_avatar_action=None`, `show_back_button=True`. **No `/home` entry yet.**
- Add `<!--HEADER_DROPDOWN-->` slot + `<!--BACK_BTN_SLOT-->` slot to `header.html`; remove static `<a>` items and the inline back-button (both now render via the slots)
- Modify `_render_with_shell(html, page_key)` to look up `PAGE_MENUS[page_key]`, render items into `<!--HEADER_DROPDOWN-->`, render back-button (or empty string) into `<!--BACK_BTN_SLOT-->`, then substitute `<!--ZK_HEADER-->` in page_html
- Update routes for the 6 pages to pass `page_key` (matching the 6 entries added above)
- KG carve-out: remove `<!--ZK_HEADER-->` from `kg/index.html` line 15; switch KG route to `_html_file_response(KG_DIR / "index.html")`
- Tests in PR1: 1 (schema valid + non-empty `authed` per entry — does **not** assert "only pricing has anon" yet because no entry has anon), 2 (render substitution), 3 (route page_keys), 5 (KG carve-out)
- Cache-bust: bump header.html version-query

**Visible change:** KG no longer stacks (only `kg-header` renders). Other 6 pages render identical HTML to today.

### 11.2 PR2 — New UX + `/home` migration + anon `/pricing` + dedupe

**Scope:**
- Add the **Store** item icon (inline SVG bag/tag glyph) to the icon registry
- Add a new `home` entry to `PAGE_MENUS` with `show_back_button=False` and the 4-item list (Nexus · My Profile · Store · Sign Out)
- Update the existing 6 entries to the new per-§5.3 lists (rename Dashboard → Home, add Store, drop the current-page item per page)
- Populate `anon=[Home, Sign In]` and `anon_avatar_action="open-login-modal"` on the `pricing` entry
- Add `/home` route to pass `page_key="home"` through `_render_with_shell`
- `/home` migration per §7 (replace inline `<header>` with `<!--ZK_HEADER-->`, strip duplicate avatar/dropdown wiring from `home.js`, wire sign-out via `ZKHeader.onSignOut`, de-fork `header.js`, audit + delete CSS `.home-avatar-*` block)
- Anon flow on `/pricing` per §8 (in `header.js`: skip avatar cache when `profileId === null`; new `boot()` option `anonAction`; for anon + `anonAction === 'open-login-modal'`, swap avatar click handler to open `#login-modal` and leave `zk-anon-no-dropdown-default` class in place)
- Add `zk-anon-no-dropdown-default { visibility: hidden }` to `header.css`; authed-path JS removes the class
- Tests in PR2: update test 1 to assert "only `pricing` has `anon`" + "only `home` has `show_back_button=False`"; add tests 4 (home shell), 6 (pricing anon attribute), 7 (back-button per-page), 8 (Playwright keyboard smoke), 9 (CI duplicate-ID lint)
- Cache-bust: bump header.html, header.js, header.css version-queries

**Visible change:** new dropdown items per spec; `/home` rebuilt around the shared fragment; `/pricing` anon avatar opens login modal.

## 12. Per-PR verification gate (mandatory, applies to BOTH PRs in order)

| # | Step | Action |
|---|---|---|
| 1 | Pre-merge verification | Invoke `superpowers:verification-before-completion` — run verification commands, confirm output, no claims without evidence |
| 2 | Self-review | Invoke `code-review-excellence` — apply review standards to own diff |
| 3 | External review | Invoke `superpowers:requesting-code-review` — independent code-reviewer agent on the PR diff; address every finding |
| 4 | Conflict + CI | `git fetch origin master && git rebase origin/master`; resolve any CI red |
| 5 | Merge | `gh pr merge --rebase --delete-branch <PR#>` (per standing "Always Rebase & Merge" rule) |
| 6 | Deploy | Auto via `.github/workflows/deploy-droplet.yml` → droplet blue/green |
| 7 | Verify deploy | Wait for `deploy.sh` to settle on new color; if regressions, loop back to step 1 |
| 8 | Log audit | `gh workflow run read_recent_logs.yml`; fetch Caddy access log; manually hit every touched page in prod and confirm: dropdown items, sign-in/out flow, anon `/pricing` flow, KG carve-out (PR1), `/home` shell (PR2) |
| 9 | Zero gaps | Any single gap → loop back to step 1. Never claim done with logs unread. |

## 13. Risks

| # | Risk | Mitigation | Severity |
|---|---|---|---|
| 1 | KG users lose sign-out access | Acknowledged (§6 side-effect); explicit out-of-scope | Low (one extra click via back→/) |
| 2 | `/home` back-button removed | By design (§9); test asserts absence | None — intended |
| 3 | Pre-JS race on `/pricing` anon dropdown flashes open | `zk-anon-no-dropdown-default` CSS class hides by default; JS reveals only for authed | Low (50-150 ms window, invisible to humans) |
| 4 | Bookmark / extension targeting `#home-avatar-btn` breaks | Document in PR2 description | Very low |
| 5 | Service-worker / proxy cache serves stale header.html | Version-query bump on header.html / .js / .css; existing `Cache-Control: no-cache` on HTML | Low |
| 6 | Drift between PR1's static items and PR2's spec items | PR2 sequenced immediately after PR1 merge + deploy | Low (planned sequencing) |

## 14. Out of scope (explicit deferrals)

- KG avatar / sign-out (potential follow-up if user requests)
- Mobile shell (`mobile/templates/_shell.html`) — separate codepath, not touched
- Cmd-K command palette (industry pattern, not in this iteration)
- Visual regression infra (Playwright snapshot / Percy / Chromatic)
- Adding RAG to the menu (not in spec)

## 15. References

**Industry research (Agent 1):**
- [NN/g — Menu Design](https://www.nngroup.com/articles/menu-design/), [Navigation You Are Here](https://www.nngroup.com/articles/navigation-you-are-here/), [Contextual Menus Guidelines](https://www.nngroup.com/articles/contextual-menus-guidelines/)
- [Lollypop — SaaS Navigation Menu Design (Dec 2025)](https://lollypop.design/blog/2025/december/saas-navigation-menu-design/)
- [Edana — SaaS Navigation (Apr 2026)](https://edana.ch/en/2026/04/26/saas-navigation-how-to-design-a-menu-that-accelerates-adoption-reduces-friction-and-supports-product-growth/)
- [Vercel Account Menu](https://vercel.com/docs/accounts); [Primer (GitHub)](https://primer.style/components/)

**Architecture research (Agent 2):**
- [FastAPI Templates](https://fastapi.tiangolo.com/advanced/templates/); [Jinja2 SSR](https://realpython.com/fastapi-jinja2-template/)
- [Smashing — Web Components: Shadow DOM (Jul 2025)](https://www.smashingmagazine.com/2025/07/web-components-working-with-shadow-dom/)
- [Eliminating FOUC (2025)](https://medium.com/the-fullstack-interface/eliminating-fouc-how-to-fix-the-flash-of-unstyled-content-thats-wrecking-your-ux-e10273e1739c)
- [Zach Leatherman — The Good, The Bad, The Web Components](https://www.zachleat.com/web/good-bad-web-components/)

**Anti-patterns + WCAG (Agent 3):**
- [W3C APG — Menu Button Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/menu-button/); [Disclosure Navigation Example](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/examples/disclosure-navigation/)
- [WCAG 2.5.8 Target Size (Minimum) — AA](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- [WordPress Gutenberg PR #45779 — duplicate nav consolidation](https://github.com/WordPress/gutenberg/pull/45779)
- [Zalando Eng — Postmortem analysis Sep 2025 (action drift)](https://engineering.zalando.com/posts/2025/09/dead-ends-or-data-goldmines-ai-powered-postmortem-analysis.html)
- [figr.design — Figma Design System Drift](https://figr.design/blog/figma-design-system-drift)

## 16. Open items at end of spec

None — all decisions taken in brainstorm:
- ✅ Python dict over YAML
- ✅ Per-page matrix locked
- ✅ Store icon: inline SVG bag/tag glyph
- ✅ Anon flow on `/pricing`: random avatar (fresh each load, no cache) + click opens `#login-modal`
- ✅ Back-button per-page config (`/home` hides it)
- ✅ Two-PR split
- ✅ 9-step per-PR verification gate

Ready for spec review → writing-plans skill.
