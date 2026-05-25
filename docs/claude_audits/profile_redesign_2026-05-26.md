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

## Plan (subject to research-informed refinement)

1. Land this scope doc → open PR for monitoring. *(this commit)*
2. Land research synthesis → second commit.
3. Brainstorm with operator on direction (1-2 sharp design questions, max).
4. Implement redesign (HTML + dark-theme CSS rewrite + minor JS additions if needed).
5. Verify in browser (DigitalOcean prod is the only env; do not deploy until rebase-merge approval).
6. Request rebase-merge approval.
