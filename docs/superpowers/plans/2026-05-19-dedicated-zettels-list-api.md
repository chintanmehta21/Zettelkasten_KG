# Dedicated Zettels-list API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GET /api/zettels` (dedicated, paginated, per-user Zettel list reusing the verified v2 read path) and switch `user_zettels.js` + `home.js` list/badge fetches to it; `/api/graph?view=my` stays for the 3D viz only.

**Architecture:** New route in `website/api/zettels_routes.py` reuses `get_supabase_v2_scope_for_read` + `ContentRepository.list_workspace_zettels` (no new query logic). DTO `id` = `workspace_zettel` UUID (matches `DELETE/PATCH /api/zettels/{id}`; incidentally fixes the pre-existing slug-400 delete bug). Clean snake_case DTO; `added_at` (workspace `created_at`) drives sort + "Latest Capture". No `_v2_assemble_graph` refactor.

**Tech Stack:** FastAPI, Pydantic, pytest; vanilla JS frontend; branch `feat/dedicated-zettels-api`.

---

### Task 1: Response models + `GET /api/zettels` endpoint (TDD)

**Files:**
- Modify: `website/api/zettels_routes.py` (add imports, models, route — append route after the existing `operation_status` route ~line 563+)
- Test: `tests/unit/website/test_zettels_list_api.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/website/test_zettels_list_api.py`:

```python
from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from website.app import create_app

_WS = str(uuid4())
_CANON = str(uuid4())
_WZID = str(uuid4())


def _row(wzid=_WZID, canon=_CANON, title="Hello World", st="youtube"):
    return {
        "id": wzid,
        "canonical_zettel_id": canon,
        "ai_summary": json.dumps(
            {"brief_summary": "brief here", "detailed_summary": "## H\n- d"}
        ),
        "user_tags": ["ai", "ml"],
        "created_at": "2026-05-18T10:00:00+00:00",
        "canonical": {
            "id": canon,
            "normalized_url": "https://www.youtube.com/watch?v=abc",
            "title": title,
            "source_type": st,
            "publication_date": "2024-01-02",
        },
    }


class _Repo:
    def __init__(self, rows):
        self._rows = rows

    def list_workspace_zettels(self, ws_id, *, limit=5000, offset=0):
        return list(self._rows)[offset : offset + limit]


def _client():
    return TestClient(create_app())


def test_zettels_list_unauthenticated_returns_401():
    c = _client()
    r = c.get("/api/zettels")
    assert r.status_code == 401


def test_zettels_list_returns_dto_for_authed_user():
    c = _client()
    scope = (_Repo([_row()]), uuid4(), [uuid4()])
    with patch(
        "website.api.zettels_routes.get_optional_user",
        return_value={"sub": str(uuid4())},
    ), patch(
        "website.api.zettels_routes.get_supabase_v2_scope_for_read",
        return_value=scope,
    ):
        r = c.get("/api/zettels", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["limit"] == 5000 and body["offset"] == 0
    z = body["zettels"][0]
    assert z["id"] == _WZID  # workspace_zettel UUID (delete/patch contract)
    assert z["title"] == "Hello World"
    assert z["brief_summary"] == "brief here"
    assert z["detailed_summary"].startswith("## H")
    assert z["tags"] == ["ai", "ml"]
    assert z["source_type"] == "youtube"
    assert z["source_url"] == "https://www.youtube.com/watch?v=abc"
    assert z["added_at"].startswith("2026-05-18")
    assert z["published_at"] == "2024-01-02"


def test_zettels_list_no_scope_returns_empty_200():
    c = _client()
    with patch(
        "website.api.zettels_routes.get_optional_user",
        return_value={"sub": str(uuid4())},
    ), patch(
        "website.api.zettels_routes.get_supabase_v2_scope_for_read",
        return_value=None,
    ):
        r = c.get("/api/zettels", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"zettels": [], "total": 0, "limit": 5000, "offset": 0}


def test_zettels_list_dedupes_canonical_across_workspaces():
    c = _client()
    dup = _row(wzid=str(uuid4()))  # same _CANON, different wz id
    scope = (_Repo([_row(), dup]), uuid4(), [uuid4(), uuid4()])
    with patch(
        "website.api.zettels_routes.get_optional_user",
        return_value={"sub": str(uuid4())},
    ), patch(
        "website.api.zettels_routes.get_supabase_v2_scope_for_read",
        return_value=scope,
    ):
        r = c.get("/api/zettels", headers={"Authorization": "Bearer x"})
    # one workspace iter is enough; canonical dedupe keeps first occurrence
    ids = [z["id"] for z in r.json()["zettels"]]
    assert ids == [_WZID]


def test_zettels_list_clamps_limit_and_offset():
    c = _client()
    scope = (_Repo([_row()]), uuid4(), [uuid4()])
    with patch(
        "website.api.zettels_routes.get_optional_user",
        return_value={"sub": str(uuid4())},
    ), patch(
        "website.api.zettels_routes.get_supabase_v2_scope_for_read",
        return_value=scope,
    ):
        r = c.get(
            "/api/zettels?limit=999999&offset=-5",
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    assert r.json()["limit"] == 10000 and r.json()["offset"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/website/test_zettels_list_api.py -q`
Expected: FAIL (route `/api/zettels` does not exist → 404/405; import patch targets missing).

- [ ] **Step 3: Add imports to `website/api/zettels_routes.py`**

Find the existing import block. Add (near the other `from website.core...` imports):

```python
from website.core.persist import (
    extract_summary_parts,
    get_supabase_v2_scope_for_read,
)
```

(If `from website.api.auth import get_optional_user` is already present — it is, line ~19 — leave it. Do NOT add a second import.)

- [ ] **Step 4: Add response models + route**

Append to `website/api/zettels_routes.py` (after the `operation_status` route, end of file region):

```python
class ZettelListItem(BaseModel):
    id: str
    title: str
    brief_summary: str
    detailed_summary: str
    tags: list[str]
    source_type: str
    source_url: str
    added_at: str
    published_at: str


class ZettelListResponse(BaseModel):
    zettels: list[ZettelListItem]
    total: int
    limit: int
    offset: int


@router.get("/zettels", response_model=ZettelListResponse)
async def list_zettels(
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
    limit: int = 5000,
    offset: int = 0,
):
    """Dedicated per-user Zettel list (v2). Distinct from /api/graph?view=my
    (the 3D knowledge-graph). ``id`` is the workspace_zettel UUID so the
    existing DELETE/PATCH /api/zettels/{id} contract works directly.
    """
    if user is None:
        return _problem(
            status_code=401,
            title="Authentication required",
            detail="Sign in to view your Zettels.",
            operation_id="",
            type_slug="unauthenticated",
        )

    limit = max(1, min(int(limit), 10000))
    offset = max(0, int(offset))

    scope = get_supabase_v2_scope_for_read(user.get("sub"))
    if scope is None:
        return JSONResponse(
            {"zettels": [], "total": 0, "limit": limit, "offset": offset}
        )
    content_repo, _profile_id, workspace_ids = scope

    items: list[dict] = []
    seen_canonical: set[str] = set()
    try:
        for ws_id in workspace_ids:
            rows = content_repo.list_workspace_zettels(
                ws_id, limit=limit, offset=offset
            )
            for row in rows:
                canonical = row.get("canonical") or {}
                canonical_id = str(
                    canonical.get("id") or row.get("canonical_zettel_id") or ""
                )
                if not canonical_id or canonical_id in seen_canonical:
                    continue
                seen_canonical.add(canonical_id)
                brief, detailed = extract_summary_parts(
                    row.get("ai_summary"), None
                )
                items.append(
                    {
                        "id": str(row.get("id") or ""),
                        "title": str(canonical.get("title") or "Untitled"),
                        "brief_summary": brief or "",
                        "detailed_summary": detailed or "",
                        "tags": list(row.get("user_tags") or []),
                        "source_type": str(
                            canonical.get("source_type") or "web"
                        ).lower(),
                        "source_url": str(
                            canonical.get("normalized_url") or ""
                        ),
                        "added_at": str(row.get("created_at") or ""),
                        "published_at": str(
                            canonical.get("publication_date") or ""
                        ),
                    }
                )
    except Exception:
        logger.exception("list_zettels failed; returning empty list")
        return JSONResponse(
            {"zettels": [], "total": 0, "limit": limit, "offset": offset}
        )

    return JSONResponse(
        {
            "zettels": items,
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }
    )
```

(`BaseModel`, `Annotated`, `Depends`, `JSONResponse`, `_problem`, `router`, `logger` are already imported/defined in this module — verified. Do not re-import.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/website/test_zettels_list_api.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add website/api/zettels_routes.py tests/unit/website/test_zettels_list_api.py
git commit -m "feat: add dedicated GET /api/zettels list endpoint"
```

---

### Task 2: Switch `user_zettels.js` to `/api/zettels`

**Files:**
- Modify: `website/features/user_zettels/js/user_zettels.js` (`loadZettels` ~232-248, `normalizeNode` ~250-284)
- Test: `tests/unit/frontend/test_add_zettel_shared_helper.py` (add a guard test)

- [ ] **Step 1: Write the failing guard test**

Append to `tests/unit/frontend/test_add_zettel_shared_helper.py`:

```python
def test_list_pages_use_dedicated_zettels_endpoint_not_graph():
    uz = (ROOT / "website" / "features" / "user_zettels" / "js" / "user_zettels.js").read_text(encoding="utf-8")
    assert "/api/zettels'" in uz or '"/api/zettels"' in uz, "user_zettels must call /api/zettels"
    assert "/api/graph?view=my" not in uz, "user_zettels must not use the graph endpoint for the list"
    home = (ROOT / "website" / "features" / "user_home" / "js" / "home.js").read_text(encoding="utf-8")
    assert "/api/graph?view=my" not in home, "home.js must not use the graph endpoint for list/badge"
    kg = (ROOT / "website" / "features" / "knowledge_graph" / "js" / "app.js").read_text(encoding="utf-8")
    assert "/api/graph" in kg, "the 3D /knowledge-graph viz must still use /api/graph"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/frontend/test_add_zettel_shared_helper.py::test_list_pages_use_dedicated_zettels_endpoint_not_graph -q`
Expected: FAIL (user_zettels.js still uses `/api/graph?view=my`).

- [ ] **Step 3: Rewrite `loadZettels` in `website/features/user_zettels/js/user_zettels.js`**

Replace the existing `loadZettels` function body (the one fetching `/api/graph?view=my`, ~lines 232-248) with:

```javascript
  async function loadZettels() {
    try {
      var resp = await fetch('/api/zettels', {
        headers: { Authorization: 'Bearer ' + _token }
      });
      var data = await resp.json();
      var zettels = Array.isArray(data.zettels) ? data.zettels : [];
      _allNodes = zettels.map(normalizeNode);
    } catch (err) {
      console.error('[user_zettels] Failed to load zettels:', err);
      _allNodes = [];
    }

    rebuildFilterMenus();
    updateStats(_allNodes);
    applyFilters();
  }
```

- [ ] **Step 4: Rewrite `normalizeNode` to consume the DTO**

Replace the existing `normalizeNode` function (~lines 250-284) with:

```javascript
  function normalizeNode(z) {
    var source = normalizeSource(z.source_type || 'web');
    var cleanTags = (Array.isArray(z.tags) ? z.tags : [])
      .map(normalizeTag)
      .filter(Boolean);
    var brief = z.brief_summary || '';
    var detailed = z.detailed_summary || brief;
    return {
      id: z.id || createLocalNodeId(z.title || 'zettel'),
      title: (z.title || 'Untitled').trim(),
      summary: brief,
      briefSummary: brief,
      detailedSummary: detailed,
      detailedStructured: null,
      tags: uniqueStrings(cleanTags),
      normalizedTags: uniqueStrings(cleanTags.map(function (t) { return t.toLowerCase(); })),
      url: (z.source_url || '').trim(),
      date: normalizeCaptureDate(z.added_at || ''),
      source: source,
      sourceLabel: sourceLabel(source),
      summaryLength: detailed.length || brief.length
    };
  }
```

(Sort "newest" and "Latest Capture" already read the `date` field; it now maps to `added_at` — the approved capture-time semantic. `extractSummaryParts` is no longer used by `normalizeNode`; leave the function defined if referenced elsewhere, otherwise the guard test in Task 2 still passes.)

- [ ] **Step 5: Run the guard test + the existing user_zettels frontend tests**

Run: `python -m pytest tests/unit/frontend/ -q`
Expected: PASS (new guard test passes; no other frontend test regresses).

- [ ] **Step 6: Commit**

```bash
git add website/features/user_zettels/js/user_zettels.js tests/unit/frontend/test_add_zettel_shared_helper.py
git commit -m "feat: My Zettels list uses dedicated /api/zettels endpoint"
```

---

### Task 3: Switch `home.js` badge/chooser to `/api/zettels`

**Files:**
- Modify: `website/features/user_home/js/home.js` (3 fetch sites: ~line 291, ~595, ~1405 — all `'/api/graph?view=my'`)

- [ ] **Step 1: Inspect the three call sites**

Run: `grep -n "/api/graph?view=my" website/features/user_home/js/home.js`
Expected: 3 fetch lines (~291, ~595, ~1405) plus 2 comment lines. Only the `fetch('/api/graph?view=my'...)` calls change.

- [ ] **Step 2: Replace each fetch URL + response unwrap**

For EACH of the 3 `fetch('/api/graph?view=my', { headers: { Authorization: 'Bearer ' + _token } })` sites in `website/features/user_home/js/home.js`:
- change the URL string `'/api/graph?view=my'` → `'/api/zettels'`
- where the code then reads `graph.nodes` (array) for count/list, read `data.zettels` instead, and where it used `graph.nodes.length` use `data.total`.

Concretely, each site currently looks like:

```javascript
      var resp = await fetch('/api/graph?view=my', {
        headers: { Authorization: 'Bearer ' + _token }
      });
      var graph = await resp.json();
      var nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
```

Replace with:

```javascript
      var resp = await fetch('/api/zettels', {
        headers: { Authorization: 'Bearer ' + _token }
      });
      var data = await resp.json();
      var nodes = Array.isArray(data.zettels) ? data.zettels : [];
```

(Keep the downstream variable name `nodes` so the rest of each block — count, chooser mapping — is untouched. If a site uses `graph.nodes.length` for the badge, `nodes.length` now equals `data.total`.)

- [ ] **Step 3: Verify no graph?view=my fetch remains**

Run: `grep -n "fetch('/api/graph?view=my'" website/features/user_home/js/home.js`
Expected: no output (0 matches).

- [ ] **Step 4: Run frontend guard test**

Run: `python -m pytest tests/unit/frontend/test_add_zettel_shared_helper.py::test_list_pages_use_dedicated_zettels_endpoint_not_graph -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/user_home/js/home.js
git commit -m "feat: home badge/chooser use /api/zettels not graph"
```

---

### Task 4: Cache-buster bump + asset-version pin

**Files:**
- Modify: `website/features/user_zettels/index.html`, `website/features/user_home/index.html`
- Modify: `tests/unit/frontend/test_add_zettel_shared_helper.py` (the `ADD_ZETTEL_ASSET_VERSION` constant + the per-asset assertions for `user_zettels.js` / `home.js`)

- [ ] **Step 1: Find current version**

Run: `grep -n "ADD_ZETTEL_ASSET_VERSION =" tests/unit/frontend/test_add_zettel_shared_helper.py`
Expected: one line, e.g. `ADD_ZETTEL_ASSET_VERSION = "20260518b"`.

- [ ] **Step 2: Bump the changed JS cache-busters**

In `website/features/user_zettels/index.html`: change `user_zettels.js?v=20260518b` → `user_zettels.js?v=20260519a`.
In `website/features/user_home/index.html`: change `home.js?v=20260518b` → `home.js?v=20260519a`.
(Use the actual current version found in Step 1 as the old value; new value = `20260519a`. Do NOT touch `add_zettel_api.js` / css versions — unchanged files.)

- [ ] **Step 3: Update the version-pin test**

In `tests/unit/frontend/test_add_zettel_shared_helper.py`: the assertions that pin `home.js`/`user_zettels.js` to the old version must move to `?v=20260519a`. Change the two lines asserting `/home/js/home.js?v=<old>` and `/home/zettels/js/user_zettels.js?v=<old>` to `?v=20260519a`. Leave `ADD_ZETTEL_ASSET_VERSION` and the `add_zettel_api.js`/css assertions unchanged (those files did not change).

- [ ] **Step 4: Run the frontend test file**

Run: `python -m pytest tests/unit/frontend/test_add_zettel_shared_helper.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add website/features/user_zettels/index.html website/features/user_home/index.html tests/unit/frontend/test_add_zettel_shared_helper.py
git commit -m "chore: bump user_zettels/home cache-buster to 20260519a"
```

---

### Task 5: Full regression + PR

**Files:** none (verification only)

- [ ] **Step 1: Targeted suites**

Run: `python -m pytest tests/unit/website/test_zettels_list_api.py tests/unit/frontend tests/unit/website/test_url_utils.py -q`
Expected: PASS.

- [ ] **Step 2: One batched ruff pass over touched files**

Run: `python -m ruff check website tests`
Expected: `All checks passed!` (fix any reported issue in-place without behavior change, then re-run).

- [ ] **Step 3: Full suite**

Run: `python -m pytest -q --no-header -p no:cacheprovider 2>&1 | tail -15`
Expected: pass count consistent with baseline; 0 unrelated regressions. (Known pre-existing Windows asyncio integration flake — confirm in isolation if it appears, do not treat as a regression.)

- [ ] **Step 4: Push + open PR**

```bash
git push -u origin feat/dedicated-zettels-api
gh pr create --title "feat: dedicated GET /api/zettels list endpoint" --body "Implements docs/superpowers/specs/2026-05-19-dedicated-zettels-list-api-design.md. Separates the My Zettels/home list+badge from the 3D graph endpoint; DTO id = workspace_zettel UUID (also fixes the pre-existing slug-400 delete/PATCH-from-list bug). /knowledge-graph 3D viz still uses /api/graph."
```

- [ ] **Step 5: Watch CI; STOP at green for operator merge decision**

Run: `gh pr checks <PR#> --watch`
Expected: all green. Do NOT merge autonomously — hand off for operator Rebase-&-Merge decision.

---

## Notes for the implementer

- **Do not** refactor `_v2_assemble_graph` or add a slug-id helper — the corrected design uses the workspace_zettel UUID directly.
- **Do not** change `/api/graph` or the `/knowledge-graph` viz.
- The DTO `id` MUST be `row["id"]` (workspace_zettel UUID) — this is what `DELETE/PATCH /api/zettels/{id}` require; getting this wrong reintroduces the slug-400 bug.
- Per-workspace `limit/offset` parity with the existing graph assembler is acceptable (YAGNI: cross-workspace exact pagination is out of scope; typical user has one personal workspace).
- Keep this PR independent of #25/#28 (already merged) — branch off current `master`.
