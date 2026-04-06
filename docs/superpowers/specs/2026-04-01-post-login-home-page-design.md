# Post-Login Home Page — Design Spec

**Date**: 2026-04-01
**Status**: Draft
**Approach**: Standalone feature page (Approach A)

---

## Overview

A new post-login home page at `/home` that serves as the authenticated user's dashboard. The existing landing page (`/`) remains unchanged for unauthenticated visitors. The home page follows the self-contained feature pattern used throughout the codebase (`website/features/user_home/`).

## File Structure

```
website/features/user_home/
├── index.html              # Home page HTML
├── css/
│   └── home.css            # Home-specific styles
└── js/
    └── home.js             # Home page logic

website/artifacts/avatars/
├── avatar_00.svg           # DiceBear SVGs (30 total)
├── avatar_01.svg
├── ...
└── avatar_29.svg

ops/scripts/generate_avatars.py   # One-time DiceBear download script
```

## Routing

### New Routes (app.py)

| Route | Method | Behavior |
|-------|--------|----------|
| `/home` | GET | Serve `features/user_home/index.html`; redirect mobile to `/m/home`; redirect unauthenticated to `/` |
| `/home/css` | mount | Static: `features/user_home/css/` |
| `/home/js` | mount | Static: `features/user_home/js/` |

The `/artifacts` mount already serves `website/artifacts/`, so `website/artifacts/avatars/` is automatically available at `/artifacts/avatars/`.

### Auth Guard

The `/home` route checks for a Supabase session client-side. `home.js` calls `GET /api/me` on load — if it returns 401, redirect to `/`. No server-side session validation needed (consistent with existing auth pattern where all auth is client-side via Supabase JS SDK).

### Auth Redirect

Modify `auth.js`:
- On `SIGNED_IN` event, set `window.location.href = '/home'`
- Update `callback.html`'s default `auth_return_to` fallback from `/` to `/home`

## Page Layout

### Header

Identical to landing page header positioning:
- Centered branding: logo icon (34x34 SVG) + "Zettelkasten" text + tagline
- Top-right: user avatar (32px circle) replacing login button area

### Avatar + Dropdown

- Circular avatar image (32px) from `/artifacts/avatars/avatar_XX.svg`
- Click toggles dropdown menu (4 items):
  1. **My Profile** — scrolls to profile section (future expansion)
  2. **My Zettels** — scrolls to vault section
  3. **Settings** — placeholder (future expansion)
  4. **About** — navigates to about section
- Dropdown styled like existing provider grid: dark `--bg-card`, `--border`, `--shadow-lg`
- Outside click closes dropdown
- Includes "Sign out" at bottom of dropdown, separated by divider

### My Zettels Vault

- Full-width section with vault-inspired header
- Decorative arch-shaped accent at the top of the section (CSS border-radius + gradient)
- Title: "My Zettels" with node count badge (teal)
- "Add Zettel" split button (teal accent):
  - Left: "Add Zettel" text
  - Right: chevron (toggles URL input dropdown)
  - Dropdown contains: source type selector + URL input + "Add" submit button
  - Reuses existing source type options: YouTube, GitHub, Reddit, Newsletter, Web
  - Submits to `POST /api/summarize` with Bearer token
  - On success: re-fetches graph, new card animates in
  - On error: inline error message in dropdown
- Card grid (CSS Grid, `auto-fill`, `minmax(240px, 1fr)`):
  - Each card: source badge (color-coded), title (truncated 2 lines), summary (3 lines), tags (max 3), date
  - Card styling: `--bg-card`, `--border`, `--radius-lg`, hover elevation
  - Click opens source URL in new tab
- Empty state: centered message + arrow pointing to Add Zettel button
- Cards sorted by date (newest first)

### My Knowledge Graph Button

- Full-width card-button below the vault section
- Layout: KG logo icon (left) + "My Knowledge Graph" title + "Explore connections between your zettels" subtitle + arrow (right)
- Background: subtle teal gradient accent (consistent with KG CTA on landing page but larger)
- Hover: teal glow, slight scale transform
- Links to `/knowledge-graph` (existing)

### Footer

- Same as landing page: centered GitHub icon link

## Avatar System

### Pre-Generation

`ops/scripts/generate_avatars.py`:
- Downloads 30 SVGs from DiceBear API v9
- Styles cycle: adventurer, bottts, fun-emoji, notionists, thumbs, big-ears, lorelei (7 styles, ~4-5 each)
- Seeds: `zettel_avatar_0` through `zettel_avatar_29` (deterministic)
- Saves to `website/artifacts/avatars/avatar_00.svg` through `avatar_29.svg`
- Run once; files committed to repo

### Assignment

- On first authenticated page load, if `avatar_url` from `/api/me` is empty/null:
  - `home.js` picks `avatar_{random(0-29)}.svg`
  - Calls `PUT /api/me/avatar` to persist
- Subsequent loads use the stored `avatar_url`
- Fallback if avatar SVG fails to load: CSS circle with first letter of user's name

### Avatar Editing

- Profile dropdown menu item leads to an avatar picker modal
- Grid of all 30 avatars with current selection highlighted
- Click to select → calls `PUT /api/me/avatar` → updates display immediately

## API Changes

### New Endpoint

```
PUT /api/me/avatar
Authorization: Bearer <JWT>
Body: {"avatar_id": 15}
Response: {"avatar_url": "/artifacts/avatars/avatar_15.svg"}
```

Updates `kg_users.avatar_url` in Supabase for the authenticated user.

### Modified Endpoints

**`GET /api/me`** — already returns `avatar_url`. No changes needed.

**`POST /api/summarize`** — already supports authenticated requests. No changes needed.

**`GET /api/graph?view=my`** — already returns user-scoped graph. No changes needed.

## CSS Design

### Theme Consistency

`home.css` loads the shared `:root` variables via `<link rel="stylesheet" href="/css/style.css">` in the HTML head. All colors, fonts, radii, and shadows use existing tokens.

### Namespacing

All home-specific classes prefixed with `.home-*`:
- `.home-vault` — vault section container
- `.home-vault-header` — arch-shaped header area
- `.home-card-grid` — responsive card grid
- `.home-card` — individual zettel card
- `.home-kg-btn` — knowledge graph button
- `.home-avatar` — avatar circle
- `.home-dropdown` — avatar dropdown menu
- `.home-add-zettel` — add zettel button + dropdown

### Vault Visual

The vault section uses a subtle arch-shaped decorative element:
- Top border with large `border-radius` on top corners (48px)
- Gradient overlay: `linear-gradient(to bottom, var(--accent-subtle), transparent)` at top
- Inner shadow for depth: `inset 0 1px 0 var(--border-light)`

### Animations

- Page load: staggered fade-in for sections (vault, KG button)
- Card appearance: slide-up with fade (`@keyframes cardIn`)
- Dropdown open/close: opacity + translateY transition
- Avatar hover: subtle scale + ring glow

## Data Flow

```
                         ┌──────────┐
                         │  /home   │
                         └────┬─────┘
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
        GET /api/me    GET /api/graph   Static assets
        (profile)      (?view=my)       (CSS, JS, avatars)
               │              │
               ▼              ▼
        Avatar + Name    Card Grid
               │
    ┌──────────┴──────────┐
    ▼                     ▼
No avatar?          PUT /api/me/avatar
Assign random       (user changes avatar)
    │
    ▼
PUT /api/me/avatar
(persist random pick)


Add Zettel:
    URL input → POST /api/summarize (Bearer token)
             → Re-fetch GET /api/graph?view=my
             → New card in grid
```

## Error States

| Scenario | Behavior |
|----------|----------|
| `/api/me` returns 401 | Redirect to `/` |
| `/api/graph?view=my` fails | Show empty state with retry button |
| `POST /api/summarize` fails | Show error message in Add Zettel dropdown |
| Avatar SVG 404 | Show initials fallback (CSS circle + first letter) |
| No zettels yet | Empty state: "No zettels yet" + prompt to add first |

## Scope Boundaries

**In scope:**
- Home page HTML/CSS/JS
- Avatar generation script + 30 SVG files
- `PUT /api/me/avatar` endpoint
- Auth redirect to `/home` after login
- `GET /home` route in `app.py`
- Avatar picker modal

**Out of scope:**
- Mobile home page (`/m/home`) — can be added in a follow-up iteration
- Profile page — placeholder link in dropdown
- Settings page — placeholder link in dropdown
- About page — links to existing content


