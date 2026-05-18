# Dedicated Zettels-list API — design

**Date:** 2026-05-19
**Status:** Approved (brainstorming) — pending spec review → writing-plans
**Scope:** Single PR, independent of PR #25 (URL-dedup) and PR #28 (migration-drift). Orthogonal to the "Naruto not visible" root cause (that was the failed deploy, fixed by #28).

## Problem

The website's *My Zettels* page (`user_zettels.js`) and the *home* page's My-Zettels badge/chooser (`home.js`) fetch `GET /api/graph?view=my` — the 3D **knowledge-graph** endpoint — purely to render a flat list. That endpoint computes links, runs analytics enrichment, and applies `min_strength` graph trimming, none of which a list needs. It is the wrong tool: coupling the list UI to the graph contract, over-fetching, and conflating two concerns.

## Goal

A dedicated `GET /api/zettels` that returns a clean, paginated list of the authenticated user's Zettels, reusing the already-verified read path. `/api/graph?view=my` stays unchanged and continues to serve the actual `/knowledge-graph` 3D visualisation.

## Architecture

- New route `GET /api/zettels` in `website/api/zettels_routes.py` (existing router, prefix `/api`), `Depends(get_optional_user)`.
- Reuses the verified path (no new query logic): `get_supabase_v2_scope_for_read(user["sub"])` → `(content_repo, profile_id, workspace_ids)`; for each `ws_id`, `content_repo.list_workspace_zettels(ws_id, limit=limit, offset=offset)`; dedupe by `canonical_zettel_id` (same dedupe the graph assembler does).
- **`id` = `workspace_zettel.id` (UUID), corrected design.** Investigation found `_v2_assemble_graph` emits a slug id `f"{prefix}-{slug}-{canonical8}"`, but `DELETE`/`PATCH /api/zettels/{node_id}` (`routes.py:627/688`) require a **`workspace_zettel` UUID** (`_is_supabase_uuid` gate). The My Zettels page passes the slug to delete → it currently 400s: **delete/tag-edit from the list is a pre-existing production bug.** The dedicated endpoint therefore returns `id = row["id"]` (the workspace_zettel UUID already in every `list_workspace_zettels` row), which is exactly what delete/PATCH require. Switching the list page to this endpoint **fixes the broken delete/PATCH** with no extra code. No shared slug helper and **no `_v2_assemble_graph` refactor** — the 3D graph keeps its slug ids (it never deletes).
- v2-only and per-user isolation:
  - Unauthenticated / non-UUID subject → `401` problem response (the list pages already redirect to `/` when unauthenticated; 401 is the clean contract).
  - Authenticated but `use_supabase_v2()` false, no v2 scope, or zero zettels → `200` with `{"zettels": [], "total": 0, ...}`. No file-store fallback — a personal list has no anonymous/global concept (unlike the graph).

## Contract

```
GET /api/zettels?limit=5000&offset=0
  limit:  default 5000, clamped 1..10000   (parity with current graph-list cap)
  offset: default 0, clamped >= 0

200 OK
{
  "zettels": [
    {
      "id":               "<workspace_zettel UUID>",  // == DELETE/PATCH /api/zettels/{id} contract
      "title":            "string",
      "brief_summary":    "string",   // extract_summary_parts(ai_summary)[0]
      "detailed_summary": "string",   // extract_summary_parts(ai_summary)[1]
      "tags":             ["string"],
      "source_type":      "string",
      "source_url":       "string",   // canonical normalized_url
      "added_at":         "ISO-8601", // workspace_zettels.created_at (true capture time)
      "published_at":     "ISO-8601 | ''" // canonical.publication_date (nullable)
    }
  ],
  "total":  N,   // items in this response (post-dedupe, this page)
  "limit":  L,
  "offset": O
}

401 → structured problem (unauthenticated)
```

Notes:
- brief/detailed are split server-side with the same `extract_summary_parts` used elsewhere — the client stops re-deriving them.
- **Capture-date semantics (approved improvement):** the list's sort ("Newest") and "Latest Capture" stat switch from canonical `publication_date` to `added_at` (when the user actually captured it). `published_at` is still returned for display if wanted. This intentionally changes ordering/date output vs today and is the correct semantic.

## Frontend migration (the controlled risk)

- `user_zettels.js`: replace `fetch('/api/graph?view=my')` + `graph.nodes` derivation with `fetch('/api/zettels')` + `data.zettels`; map to the new explicit fields; delete the unused links/analytics handling. Keep all search/filter/sort/render logic; sort "newest" + "Latest Capture" now key off `added_at`.
- `home.js`: My-Zettels badge count + the add/chooser sourcing that used `/api/graph?view=my` → `/api/zettels` (use `total` / `zettels.length`). The `/knowledge-graph` 3D viz path is untouched and keeps `/api/graph`.
- Bump the changed JS cache-busters (`?v=…`) and update the asset-version pin in `tests/unit/frontend/test_add_zettel_shared_helper.py` (same pattern already used twice this cycle).

## Error handling

- Repository/Supabase exception → log + `200` empty list (never 5xx a list page; mirrors the graph path's defensive fallthrough philosophy, minus the file-store).
- `limit`/`offset` out of range → clamped, not rejected.
- Soft-deleted overlays already filtered server-side by `list_workspace_zettels`.

## Testing (TDD)

- Endpoint unit tests: authed user with N zettels → `len==N`, field correctness, `total`==N; unauthenticated → 401; v2-off / no scope → 200 empty; pagination (limit/offset clamping + slicing); per-user isolation (user A never sees user B's rows).
- **Delete/PATCH-after-switch regression test:** with the list page on `/api/zettels`, the `id` it surfaces is a `workspace_zettel` UUID that `DELETE`/`PATCH /api/zettels/{id}` accept (asserts the pre-existing slug-400 bug is fixed, not reintroduced).
- Frontend guard test: list pages reference `/api/zettels` and no longer `/api/graph?view=my`; `/knowledge-graph` still uses `/api/graph`.
- Full `pytest` + `ruff` green; post-deploy live verification: `/api/zettels` as `naruto@zettelkasten.local` returns the 27.

## Out of scope (YAGNI)

- No removal of other `/api/graph?view=my` callers beyond the list pages (sandbox chooser etc. — separate follow-up if ever).
- No new caching layer (the 30s per-user graph cache is graph-only; the list is a single indexed read, cheap on the droplet).
- No sort/filter moved server-side — stays client-side as today.
