# Profile Page Redesign — Iteration 1a

**Branch:** `exec/build-profile-page-1a`
**Date:** 2026-05-26
**Scope:** Redesign `/profile` (`website/features/user_profile/`) to match the rest of the dark-theme Zettelkasten site and modernize the layout based on cross-industry profile-page research.

## Current state (what we have today)

`website/features/user_profile/index.html` mounts the shared header (`<!--ZK_HEADER-->`) and renders:

| Section | Content | Source |
|---|---|---|
| Hero | "My Profile" + one-line subtitle | static |
| Avatar | 60-icon SVG grid radio-picker (`/artifacts/avatars/avatar_NN.svg`) | `ZKHeader.setAvatarById` |
| Account | name / email / joined date (read-only) | `/api/me` + Supabase session |
| Statistics | 4 cards: Zettels + Kastens + KG (nodes/links) + Plan tier | `/api/zettels`, `/api/rag/sandboxes`, `/api/graph`, `/api/pricing/billing-profile` |
| Trash | Soft-deleted zettels with Restore + Delete-forever (2-click confirm) | `/api/zettels/trash` + `/api/zettels/{id}/restore` + `/api/zettels/{id}/forever` |
| Danger zone | Sign out + Delete account (disabled stub) | client + `account_purge.py` (unwired) |

## Visual mismatch (the bug we're fixing)

Site uses **dark theme** (`--bg-primary: hsl(224, 28%, 5%)`, teal `hsl(172, 66%, 50%)` accent, Inter + JetBrains Mono), but `user_profile.css` was authored against light-mode tokens (`#fdfdfd` surface, `#e6ebef` border, `#5b6c7e` muted text). The page renders as a near-white island against the rest of the dark site.

## Constraints (HARD)

- Must reuse `<!--ZK_HEADER-->` shared header (already mounted).
- Teal-only accent (no purple, amber lives only on `/knowledge-graph`).
- Cannot remove or break: avatar picker hook into `ZKHeader.setAvatarById`, trash recovery 2-click confirm, sign-out flow.
- All current API contracts stay (`/api/me`, `/api/zettels/trash`, `/api/zettels/{id}/restore`, `/api/zettels/{id}/forever`, `/api/zettels`, `/api/rag/sandboxes`, `/api/graph`, `/api/pricing/billing-profile`).
- No infra disclosure (model name, latency, tokens, etc. — none of those are on this page today, keep it that way).
- Account deletion stays disabled until backend endpoint is wired.

## Research dispatched (results land in commit 2)

1. Popular brand profile pages (Twitter, GitHub, LinkedIn, Notion, Spotify, Stripe, Vercel, Discord, Slack, Instagram).
2. Indie design-forward (Linear, Raycast, Vercel, Pitch, Figma, Framer, Posthog, Cron, Arc, Cursor, Superhuman, Fey, Things 3).
3. PKM/second-brain profile pages (Obsidian, Logseq, Notion, Mem, Reflect, Roam, Capacities, Tana, Heptabase, Anytype, RemNote).
4. 2026 UX best practice + WCAG 2.2 + dark-theme craft.

## Plan

1. Land this scope doc → open PR for monitoring. ✅
2. Land research synthesis → ✅ *(this commit)*
3. Implement redesign (HTML + dark-theme CSS rewrite + minor JS additions).
4. Verify in browser.
5. Request rebase-merge approval.

---

## Research synthesis (4 subagents, completed 2026-05-26)

### Top-brand profile pages (Twitter, Instagram, GitHub, LinkedIn, Spotify, Stripe, Vercel, Notion, Discord, Slack)

**Common patterns** (4+ products share):
- Left-rail nav for grouped categories (GitHub, Stripe, Vercel, Discord, Notion, Slack)
- Identity block pinned top (avatar + name + handle/email, edit-on-hover)
- Inline metric trio/quartet near identity (Instagram, GitHub, LinkedIn, Spotify)
- Plan/billing as DEDICATED subpage with current-plan card + usage meters + upgrade CTA
- Destructive actions in red-bordered "Danger Zone" at bottom with typed confirmation

**Distinctive moves worth stealing**:
1. **GitHub-style contribution heatmap** — activity history as identity artifact (highest impact)
2. **Wrapped-style full-bleed stat card** with bold gradient (Spotify) — turns numbers into moments
3. **Account-ID / immutable identifier always visible with copy button** (Stripe) — trust + competence
4. **Namespace switcher as primary IA** (Vercel/Notion) — separates "me" from "this space"
5. **Settings-as-modal** (Notion/Slack/Discord) — keeps user in flow; viable only when section count is small

### Indie design-forward (Linear, Raycast, Vercel, Plausible, Pitch, Figma, Framer, Posthog, Cron, Arc, Cursor, Superhuman, Things 3, Tella, Fey)

**Standout craft**:
- **Tabular numerals on every count** (Vercel Geist Mono) — stats never jitter
- **Elevation by luminance, not shadow** (Superhuman) — cards lighten as they "approach"
- **Hairline borders > drop shadows** (Vercel/Linear) — shadows look cheap in dark mode
- **Section headers as 11–12px uppercase + hairline** (Vercel/Linear) — grouping without card overload
- **Hover ring transitions border-color, not transform** (Linear) — feels instant, no layout shift
- **Danger zone = same surface, red button only** (Linear/Superhuman/GitLab Pajamas) — restraint is the warning

**Dark-theme palette winners**: Superhuman's "5-shade gray ladder with elevation by luminance" is the most copyable; tertiary border ~`hsl(215, 14%, 22%)`. Avoid pure `#000` unless committing fully to Geist hairline rigor.

### PKM / second brain (Obsidian, Logseq, Notion, Mem, Reflect, Roam, Capacities, Tana, Heptabase, Anytype, RemNote, Workflowy, Saga, Supernotes, Bear)

**Knowledge-as-identity patterns**:
- GitHub-style activity heatmap (Roam native, Obsidian via popular plugin)
- Note/card count as primary status metric
- Profile-as-Object inside your own graph (Anytype)
- Visual personalisation as Pro perk (Bear themes, Heptabase whiteboard styling)

**Trash/recovery patterns**:
- 30-day soft delete window is universal (we already match)
- Restore + Delete Forever as paired buttons (we already match)
- Tiered backup (Trash + Version History, Heptabase / Saga) — out of scope here, we have no version history yet

**Plan/quota patterns**:
- Linear progress bar + "what's using it" CTA (Obsidian Sync, cleanest)
- Plan card + renewal date + plain-text consumption (Tana / Mem / Heptabase)
- Always-visible credit counter in top chrome (Tana) — out of scope for v1, would be a global chrome change

### 2026 UX best practices

**Hard rules**:
- WCAG 2.5.8: touch targets 24×24 CSS px minimum (44×44 for primary mobile)
- Type-to-confirm for irreversible destruction; default focus on Cancel
- Focus indicators visible under sticky headers (WCAG 2.4.11)
- Form labels persistent (not placeholder-only); errors via `aria-describedby` + `aria-live`
- Skeletons mirror final layout; never on inputs/buttons/toggles

**Dark-theme gotchas**:
- Never pure black/white surfaces
- Hairlines at `rgba(255,255,255,0.06–0.10)`
- Validate contrast for every state (hover, disabled, focus), not just default
- Disabled at 38% opacity often fails AA on dark
- Desaturate teal ~15% to prevent vibration

---

## Design decisions (operator-overridable mid-stream)

Single-page long-scroll with hairline-separated sections — fits our 4–5 sections, matches `/home`'s dashboard rhythm, no over-engineered left-rail.

| # | Section | Approach |
|---|---|---|
| 1 | **Identity block** | Avatar (large, click→jump-to-picker), Display name, Email, Joined date, **User-ID with copy button** (Stripe trust signal). Single row desktop, stacked mobile. Subtle teal-glow accent at top (echoes `/home` panel signature). |
| 2 | **Activity heatmap** ⭐ | **GitHub-style 26-week zettel-creation heatmap**, computed client-side from existing `/api/zettels` (NO new API). The signature distinctive moment. Title "Last 6 months of building", legend "Less / More" in teal scale. |
| 3 | **Stat cards** | 4 cards (Zettels, Kastens, Knowledge Graph, Plan), tabular nums (JetBrains Mono), hairline borders, elevation-by-luminance on hover. ONE question per card. |
| 4 | **Avatar picker** | Refined grid (8/row desktop, 5 mobile) with hover ring + selected-fill animation. Section open by default; not collapsed (low surprise). |
| 5 | **Trash** | Keep existing trash list logic; restyle for dark theme. Tabular nums on "removed N d ago". |
| 6 | **Danger zone** | Same surface as other sections; **red button only** (Linear restraint). Sign-out commits immediately. Delete-account stays disabled with "coming soon" copy + scaffolds the type-username-to-confirm pattern for when backend lands. |

**Visual tokens**:
- Borrow all from `style.css`: `--bg-card`, `--border`, `--accent`, `--text-primary`, `--text-secondary`, `--font-mono`
- Card radius **16px** (`--radius-lg`), NOT 48px (reserved for `/home` panel signature)
- Hairline 1px borders only; no drop shadows in dark mode
- Page-load fade-in stagger reuses `fadeIn` keyframes from `home.css`

**Creative twists** (Zettelkasten-specific):
1. Identity card has subtle teal glow at top (`linear-gradient(--accent-subtle → transparent)`) — echoes `/home` vault panel.
2. Heatmap squares pulse softly on first render (CSS-only stagger), then static — feels alive without noise.
3. Stat card values use `--accent` color + tabular-nums (consistent with home-vault-count badge).
4. Plan card has teal "Manage" CTA with sliding arrow on hover (matches `home-view-all-btn` pattern).
5. Skeleton states for stat values during async load — `—` becomes 12px teal pulse.

**Out of scope (deferred)**:
- Per-workspace settings (single-workspace product today)
- Account-ID copy needs the user UUID exposed via `/api/me` — verify it's present before adding the copy button; if not, ship without it and flag for a follow-up.
- Activity heatmap below 26 weeks shows zero state (new user) — handled with empty-state copy.
