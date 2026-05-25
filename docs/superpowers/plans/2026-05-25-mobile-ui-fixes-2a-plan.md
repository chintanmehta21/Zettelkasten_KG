# Mobile UI Fixes 2a — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the mobile UI overhaul described in [`docs/superpowers/specs/2026-05-25-mobile-ui-fixes-2a-design.md`](../specs/2026-05-25-mobile-ui-fixes-2a-design.md): rebuilt header, glass bottom nav, hamburger source picker, three new mobile pages (Zettels, Kastens, Profile), PWA install affordances, mobile footer, and a cross-cutting avatar system that replaces the Google-photo fallback on both mobile and desktop.

**Architecture:** Server-rendered FastAPI templates injected via `_render_with_mobile_shell()`; vanilla-JS modules per surface; Supabase `user_metadata.avatar_url` is the source of truth for avatars; 60 SVG avatars served from `website/artifacts/avatars/` with year-long immutable cache; auth-gating done inline in route handlers (no decorator) matching the existing `FunctionalGates` idiom; glassmorphism scoped to `.m-bottom-tabs` only.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic / uvicorn / Supabase / pytest / pytest-asyncio / vanilla JS (no framework) / CSS3 with backdrop-filter / Service-Worker (existing).

**PR:** [Zettelkasten_KG#96](https://github.com/chintanmehta21/Zettelkasten_KG/pull/96) — branch `mobile-ui-fixes-2a`.

---

## Conventions used by this plan

- **Run commands**: PowerShell on the working laptop, `pytest` from the repo root.
- **TDD**: every test step writes the test first, runs it (expect FAIL), then implements minimal code, then re-runs (expect PASS), then commits. Pure-JS state machines that cannot be unit-tested in pytest are covered by a **manual verification playbook** at the end of each affected task — those tasks are flagged.
- **Commit prefix**: per CLAUDE.md — `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `ops:`. 5–10 word subject. No `Co-Authored-By`. Append `(#96)` to subjects when relevant.
- **Dev server**: keep `ENV=dev python run.py` running on port 10000. Most tasks include a smoke step that curls `http://localhost:10000/...` to confirm the change rendered.
- **Lint**: per memory `feedback_batch_ruff_at_end` — DO NOT run ruff/black per task. One batched pass in Task 15.
- **No `_render_with_mobile_shell` changes mid-stream**: if a task needs new placeholder support in the shell renderer, extend it at the start of that task and keep all later edits backward-compatible.

---

## File structure (created vs modified)

### Created

| Path | Responsibility |
|---|---|
| `supabase/website/_v2/53_user_default_avatar.sql` | Trigger + backfill + pin Zoro/Naruto |
| `website/features/user_profile/__init__.py` | Package marker |
| `website/features/user_profile/models.py` | `UserProfile` Pydantic DTO + `AvatarUrl` validated string |
| `website/features/user_profile/repository.py` | Supabase admin updates of `auth.users.raw_user_meta_data` |
| `website/features/user_profile/routes.py` | `GET /api/profile`, `PATCH /api/profile` |
| `website/mobile/zettels.html` | Lean mobile zettels page body |
| `website/mobile/kastens.html` | Lean mobile kastens page body |
| `website/mobile/profile.html` | Mobile profile page body (auth + unauth states) |
| `website/mobile/js/avatar.js` | Shared avatar renderer (mobile + desktop) |
| `website/mobile/js/install-prompt.js` | PWA install state machine + banner + header icon |
| `website/mobile/js/hamburger-sheet.js` | Reusable bottom-sheet primitive |
| `website/mobile/js/zettels.js` | Mobile-zettels list/filter/detail |
| `website/mobile/js/kastens.js` | Mobile-kastens grid + Create FAB |
| `website/mobile/js/profile.js` | Mobile-profile avatar picker + sign-out |
| `website/mobile/css/components/glass-nav.css` | Glassmorphism for `.m-bottom-tabs` |
| `website/mobile/css/components/install-banner.css` | Install banner + header icon styling |
| `website/mobile/css/components/hamburger-sheet.css` | Bottom-sheet styling |
| `website/mobile/css/components/avatar-picker.css` | Profile picker grid |
| `website/mobile/css/components/footer.css` | Mobile-sized footer variant |
| `website/mobile/css/pages/zettels.css` | Zettels page styling |
| `website/mobile/css/pages/kastens.css` | Kastens page styling |
| `website/mobile/css/pages/profile.css` | Profile page styling |
| `tests/unit/website/test_avatar_url_validation.py` | Avatar URL regex unit tests |
| `tests/unit/website/test_profile_routes.py` | `/api/profile` unit tests |
| `tests/unit/website/test_mobile_routes.py` | Mobile route auth-gate + redirect tests |
| `tests/integration/v2/test_avatar_assignment.py` | DB trigger + backfill integration test |
| `tests/integration/v2/test_profile_e2e.py` | End-to-end profile PATCH + read |

### Modified

| Path | Change |
|---|---|
| `website/app.py` | 3 new mobile routes (Zettels/Kastens/Profile); avatars static mount; profile router wiring |
| `website/mobile/index.html` | Header redesign; capture-form hamburger; remove inline summary |
| `website/mobile/templates/_shell.html` | Bottom nav: enable tabs, renames, glass class |
| `website/mobile/css/mobile.css` | Import new component CSS; drop title styles |
| `website/mobile/js/auth-modal.js` | Drop Google photo fallback; use `avatar.js` |
| `website/mobile/js/summarizer.js` | Remove inline-result rendering; redirect on success |
| `website/features/user_home/js/home.js` | Use `avatar.js`; drop Google photo fallback |
| `website/features/header/js/header.js` (if present) | Same desktop avatar swap |

---

## Task 1: Database migration — default-avatar trigger + backfill

**Files:**
- Create: `supabase/website/_v2/53_user_default_avatar.sql`
- Create: `tests/integration/v2/test_avatar_assignment.py`

- [ ] **Step 1.1: Write the failing live integration test**

Create `tests/integration/v2/test_avatar_assignment.py`:

```python
"""Tests for the default-avatar trigger and backfill (migration 53)."""
from __future__ import annotations

import re
import uuid

import pytest

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

AVATAR_PATTERN = re.compile(r"^/artifacts/avatars/avatar_(0[0-9]|[1-5][0-9])\.svg$")
ZORO_USER_ID = uuid.UUID("a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e")
NARUTO_USER_ID = uuid.UUID("f2105544-b73d-4946-8329-096d82f070d3")


async def test_new_user_gets_random_avatar(asyncpg_pool, mint_user):
    """A freshly minted user must have a valid /artifacts/avatars/avatar_NN.svg in user_metadata."""
    user = await mint_user(email_prefix="avatar_trigger")
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT raw_user_meta_data->>'avatar_url' AS url FROM auth.users WHERE id = $1",
            user["id"],
        )
    assert row is not None
    assert AVATAR_PATTERN.match(row["url"] or ""), f"Bad avatar_url: {row['url']!r}"


async def test_zoro_pinned_to_avatar_00(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        url = await conn.fetchval(
            "SELECT raw_user_meta_data->>'avatar_url' FROM auth.users WHERE id = $1",
            ZORO_USER_ID,
        )
    assert url == "/artifacts/avatars/avatar_00.svg"


async def test_naruto_pinned_to_avatar_01(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        url = await conn.fetchval(
            "SELECT raw_user_meta_data->>'avatar_url' FROM auth.users WHERE id = $1",
            NARUTO_USER_ID,
        )
    assert url == "/artifacts/avatars/avatar_01.svg"


async def test_no_google_or_gravatar_remains(asyncpg_pool):
    """After backfill, no user should retain a third-party-hosted avatar URL."""
    async with asyncpg_pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM auth.users
            WHERE raw_user_meta_data->>'avatar_url' LIKE '%googleusercontent.com%'
               OR raw_user_meta_data->>'avatar_url' LIKE '%gravatar.com%'
            """
        )
    assert count == 0
```

- [ ] **Step 1.2: Run the test — expect FAIL (migration not applied yet)**

```
pytest tests/integration/v2/test_avatar_assignment.py -v --live
```

Expected: 4 failures (NULL or 3rd-party avatar URLs).

- [ ] **Step 1.3: Write the migration**

Create `supabase/website/_v2/53_user_default_avatar.sql`:

```sql
-- ── 53_user_default_avatar.sql ────────────────────────────────────────────
-- Auto-assign random Zettelkasten avatar at signup; backfill existing users.
-- Avatars served from /artifacts/avatars/avatar_NN.svg (NN = 00..59).
-- Removes any third-party (Google/Gravatar) avatar URL so the front-end
-- avatar.js renders the curated set instead.
-- ──────────────────────────────────────────────────────────────────────────

BEGIN;

CREATE OR REPLACE FUNCTION public.assign_default_avatar()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_idx text;
BEGIN
  IF (NEW.raw_user_meta_data->>'avatar_url') IS NULL THEN
    v_idx := lpad((floor(random() * 60))::text, 2, '0');
    NEW.raw_user_meta_data := COALESCE(NEW.raw_user_meta_data, '{}'::jsonb)
      || jsonb_build_object('avatar_url', '/artifacts/avatars/avatar_' || v_idx || '.svg');
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created_assign_avatar ON auth.users;
CREATE TRIGGER on_auth_user_created_assign_avatar
  BEFORE INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.assign_default_avatar();

-- Backfill NULL + Google + Gravatar rows
UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
  || jsonb_build_object(
       'avatar_url',
       '/artifacts/avatars/avatar_' || lpad((floor(random() * 60))::text, 2, '0') || '.svg'
     )
WHERE (raw_user_meta_data->>'avatar_url') IS NULL
   OR (raw_user_meta_data->>'avatar_url') LIKE '%googleusercontent.com%'
   OR (raw_user_meta_data->>'avatar_url') LIKE '%gravatar.com%';

-- Pin canonical users
UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
  || jsonb_build_object('avatar_url', '/artifacts/avatars/avatar_00.svg')
WHERE id = 'a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e';  -- Zoro

UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
  || jsonb_build_object('avatar_url', '/artifacts/avatars/avatar_01.svg')
WHERE id = 'f2105544-b73d-4946-8329-096d82f070d3';  -- Naruto

GRANT EXECUTE ON FUNCTION public.assign_default_avatar() TO service_role;
GRANT EXECUTE ON FUNCTION public.assign_default_avatar() TO authenticated;

COMMIT;
```

- [ ] **Step 1.4: Apply on staging Supabase**

```
psql "$STAGING_SUPABASE_PG_URL" -f supabase/website/_v2/53_user_default_avatar.sql
```

Expected: `COMMIT` with no errors.

- [ ] **Step 1.5: Run the integration test on staging — expect PASS**

```
SUPABASE_URL=$STAGING_SUPABASE_URL pytest tests/integration/v2/test_avatar_assignment.py -v --live
```

Expected: 4 PASS.

- [ ] **Step 1.6: Operator approval gate for prod-apply**

Print this checklist to chat and wait for explicit operator approval:

```
PRE-APPLY CHECKLIST FOR migration 53:
  [ ] Staging run is green (Step 1.5)
  [ ] Backfill row count on prod measured:
      SELECT COUNT(*) FROM auth.users
       WHERE raw_user_meta_data->>'avatar_url' IS NULL
          OR raw_user_meta_data->>'avatar_url' LIKE '%googleusercontent.com%'
          OR raw_user_meta_data->>'avatar_url' LIKE '%gravatar.com%';
      Recorded count: _____
  [ ] Zoro + Naruto rows exist on prod:
      SELECT id, email FROM auth.users WHERE id IN ('a57e1f2f-...', 'f2105544-...');
      Recorded: _____
  [ ] Operator approves: YES / NO
```

DO NOT proceed to Step 1.7 without an affirmative response in chat.

- [ ] **Step 1.7: Apply on prod Supabase (operator-driven)**

Operator runs:

```
psql "$PROD_SUPABASE_PG_URL" -f supabase/website/_v2/53_user_default_avatar.sql
```

- [ ] **Step 1.8: Commit**

```
git add supabase/website/_v2/53_user_default_avatar.sql tests/integration/v2/test_avatar_assignment.py
git commit -m "feat(db): default-avatar trigger + backfill (#96)"
```

---

## Task 2: Profile backend — `/api/profile` GET + PATCH

**Files:**
- Create: `website/features/user_profile/__init__.py`
- Create: `website/features/user_profile/models.py`
- Create: `website/features/user_profile/repository.py`
- Create: `website/features/user_profile/routes.py`
- Create: `tests/unit/website/test_avatar_url_validation.py`
- Create: `tests/unit/website/test_profile_routes.py`
- Modify: `website/app.py` (mount router + avatars StaticFiles)

- [ ] **Step 2.1: Write the avatar-URL validation test (unit)**

Create `tests/unit/website/test_avatar_url_validation.py`:

```python
"""Tests for the avatar URL validation regex."""
from __future__ import annotations

import pytest


def test_valid_indices_pass():
    from website.features.user_profile.models import is_valid_avatar_url
    for n in (0, 1, 7, 22, 58, 59):
        url = f"/artifacts/avatars/avatar_{n:02d}.svg"
        assert is_valid_avatar_url(url), f"expected pass for {url}"


def test_out_of_range_fails():
    from website.features.user_profile.models import is_valid_avatar_url
    assert not is_valid_avatar_url("/artifacts/avatars/avatar_60.svg")
    assert not is_valid_avatar_url("/artifacts/avatars/avatar_99.svg")


def test_path_traversal_rejected():
    from website.features.user_profile.models import is_valid_avatar_url
    assert not is_valid_avatar_url("/artifacts/avatars/../../etc/passwd")
    assert not is_valid_avatar_url("/artifacts/avatars/avatar_00.svg/../bad")


def test_external_url_rejected():
    from website.features.user_profile.models import is_valid_avatar_url
    assert not is_valid_avatar_url("https://lh3.googleusercontent.com/x/y.jpg")
    assert not is_valid_avatar_url("//evil.example.com/avatar.svg")


def test_wrong_extension_rejected():
    from website.features.user_profile.models import is_valid_avatar_url
    assert not is_valid_avatar_url("/artifacts/avatars/avatar_07.png")
    assert not is_valid_avatar_url("/artifacts/avatars/avatar_07.svg.exe")


def test_empty_and_none_rejected():
    from website.features.user_profile.models import is_valid_avatar_url
    assert not is_valid_avatar_url("")
    assert not is_valid_avatar_url(None)
```

- [ ] **Step 2.2: Run — expect FAIL (module missing)**

```
pytest tests/unit/website/test_avatar_url_validation.py -v
```

Expected: `ModuleNotFoundError: No module named 'website.features.user_profile'`.

- [ ] **Step 2.3: Create the package + models**

Create `website/features/user_profile/__init__.py`:

```python
"""User profile feature — avatar + email + sign-out."""
from website.features.user_profile.routes import router

__all__ = ["router"]
```

Create `website/features/user_profile/models.py`:

```python
"""Pydantic models + avatar-URL validation."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

_AVATAR_URL_RE = re.compile(r"^/artifacts/avatars/avatar_(0[0-9]|[1-5][0-9])\.svg$")


def is_valid_avatar_url(url: Optional[str]) -> bool:
    if not url or not isinstance(url, str):
        return False
    return bool(_AVATAR_URL_RE.match(url))


class UserProfile(BaseModel):
    user_id: str
    email: Optional[str] = None
    avatar_url: str
    display_name: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    avatar_url: str = Field(..., description="One of /artifacts/avatars/avatar_NN.svg")

    @field_validator("avatar_url")
    @classmethod
    def _check(cls, v: str) -> str:
        if not is_valid_avatar_url(v):
            raise ValueError("avatar_url must be /artifacts/avatars/avatar_NN.svg with NN in 00..59")
        return v
```

- [ ] **Step 2.4: Run — expect PASS**

```
pytest tests/unit/website/test_avatar_url_validation.py -v
```

Expected: 6 PASS.

- [ ] **Step 2.5: Write the routes test (unit, with mocked Supabase)**

Create `tests/unit/website/test_profile_routes.py`:

```python
"""/api/profile route tests with mocked Supabase repository."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_get_profile_unauth_returns_401(client):
    r = client.get("/api/profile")
    assert r.status_code == 401


def test_patch_profile_unauth_returns_401(client):
    r = client.patch("/api/profile", json={"avatar_url": "/artifacts/avatars/avatar_07.svg"})
    assert r.status_code == 401


@patch("website.features.user_profile.routes._require_user")
@patch("website.features.user_profile.routes.repository.update_avatar", new_callable=AsyncMock)
def test_patch_profile_success(mock_update, mock_user, client):
    mock_user.return_value = {"id": "user-1", "email": "x@y.z", "avatar_url": "/artifacts/avatars/avatar_00.svg"}
    mock_update.return_value = {"id": "user-1", "email": "x@y.z", "avatar_url": "/artifacts/avatars/avatar_22.svg"}
    r = client.patch(
        "/api/profile",
        json={"avatar_url": "/artifacts/avatars/avatar_22.svg"},
        cookies={"sb-access-token": "fake"},
    )
    assert r.status_code == 200
    assert r.json()["avatar_url"] == "/artifacts/avatars/avatar_22.svg"


@patch("website.features.user_profile.routes._require_user")
def test_patch_profile_invalid_url_returns_422(mock_user, client):
    mock_user.return_value = {"id": "u", "email": "x", "avatar_url": "/artifacts/avatars/avatar_00.svg"}
    r = client.patch(
        "/api/profile",
        json={"avatar_url": "/artifacts/avatars/avatar_60.svg"},
        cookies={"sb-access-token": "fake"},
    )
    assert r.status_code == 422


@patch("website.features.user_profile.routes._require_user")
def test_patch_profile_path_traversal_returns_422(mock_user, client):
    mock_user.return_value = {"id": "u", "email": "x", "avatar_url": "/artifacts/avatars/avatar_00.svg"}
    r = client.patch(
        "/api/profile",
        json={"avatar_url": "/artifacts/avatars/../../etc/passwd"},
        cookies={"sb-access-token": "fake"},
    )
    assert r.status_code == 422
```

- [ ] **Step 2.6: Run — expect FAIL (routes don't exist)**

```
pytest tests/unit/website/test_profile_routes.py -v
```

Expected: ImportError or 404 on `/api/profile`.

- [ ] **Step 2.7: Write the repository**

Create `website/features/user_profile/repository.py`:

```python
"""Supabase-backed reads/writes of user_metadata.avatar_url."""
from __future__ import annotations

import logging
from typing import Any

from website.core.supabase_v2.client import get_v2_client

logger = logging.getLogger("website.user_profile.repository")


async def update_avatar(user_id: str, avatar_url: str) -> dict[str, Any]:
    """Patch raw_user_meta_data.avatar_url for the given user.

    Uses the service-role client (server-only). Returns the new profile dict
    with at least {id, email, avatar_url}.
    """
    sb = get_v2_client()
    res = await sb.auth.admin.update_user_by_id(  # type: ignore[attr-defined]
        user_id,
        {"user_metadata": {"avatar_url": avatar_url}},
    )
    user = res.user
    meta = (user.user_metadata or {}) if user else {}
    return {
        "id": user.id if user else user_id,
        "email": user.email if user else None,
        "avatar_url": meta.get("avatar_url", avatar_url),
        "display_name": meta.get("full_name") or meta.get("name"),
    }
```

- [ ] **Step 2.8: Write the routes**

Create `website/features/user_profile/routes.py`:

```python
"""GET /api/profile, PATCH /api/profile."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from website.features.user_profile import repository
from website.features.user_profile.models import UpdateProfileRequest, UserProfile

logger = logging.getLogger("website.user_profile.routes")

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _require_user(request: Request) -> dict[str, Any]:
    """Resolve the calling Supabase user from a session cookie OR Bearer header.

    The codebase's primary auth path is `Authorization: Bearer <jwt>` via
    `get_current_user` in website/api/auth.py. We also accept a cookie-based
    fallback so server-rendered mobile pages can render personalised content
    on first paint without an extra round-trip.
    """
    from website.api.auth import _decode_token  # reuses existing JWKS/HS256 verification

    # 1) Try Authorization header
    auth_h = request.headers.get("authorization") or ""
    token = None
    if auth_h.lower().startswith("bearer "):
        token = auth_h.split(None, 1)[1].strip()

    # 2) Fall back to Supabase cookie. The exact name varies by project; check
    # both the legacy `sb-access-token` and the modern `sb-<ref>-auth-token`.
    if not token:
        for k, v in request.cookies.items():
            if k == "sb-access-token" or (k.startswith("sb-") and k.endswith("-auth-token")):
                token = v
                break

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no session")

    try:
        claims = _decode_token(token)
    except Exception as exc:
        logger.debug("profile auth: token decode failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")

    return {
        "id": claims.get("sub"),
        "email": claims.get("email"),
        "avatar_url": (claims.get("user_metadata") or {}).get("avatar_url"),
        "display_name": (claims.get("user_metadata") or {}).get("full_name"),
    }


@router.get("", response_model=UserProfile)
async def get_profile(user: dict = Depends(_require_user)) -> UserProfile:
    return UserProfile(
        user_id=user["id"],
        email=user.get("email"),
        avatar_url=user.get("avatar_url") or "/artifacts/avatars/avatar_00.svg",
        display_name=user.get("display_name"),
    )


@router.patch("", response_model=UserProfile)
async def patch_profile(
    body: UpdateProfileRequest,
    user: dict = Depends(_require_user),
) -> UserProfile:
    updated = await repository.update_avatar(user["id"], body.avatar_url)
    return UserProfile(
        user_id=updated["id"],
        email=updated.get("email"),
        avatar_url=updated["avatar_url"],
        display_name=updated.get("display_name"),
    )
```

- [ ] **Step 2.9: Wire the router in `website/app.py`**

Find the existing router-include block (search for `app.include_router(zettels_router)`) and add the profile router import + include.

Add to imports at top of `website/app.py`:

```python
from website.features.user_profile import router as profile_router
```

Add the include alongside others (line near `app.include_router(pricing_router)`):

```python
    app.include_router(profile_router)
```

- [ ] **Step 2.10: Add the avatars static mount**

In `website/app.py`, find the existing static mounts (look for `app.mount("/m/css", ...`). Add:

```python
    # Avatars — long-cache immutable static files
    AVATARS_DIR = Path(__file__).parent / "artifacts" / "avatars"

    class _ImmutableStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope):  # type: ignore[override]
            resp = await super().get_response(path, scope)
            if resp.status_code == 200:
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp

    app.mount("/artifacts/avatars", _ImmutableStaticFiles(directory=str(AVATARS_DIR)), name="avatars")
```

- [ ] **Step 2.11: Run profile-route tests — expect PASS**

```
pytest tests/unit/website/test_profile_routes.py tests/unit/website/test_avatar_url_validation.py -v
```

Expected: All PASS.

- [ ] **Step 2.12: Smoke test the static mount with the dev server**

```
curl -I http://localhost:10000/artifacts/avatars/avatar_07.svg
```

Expected: HTTP 200 with `Cache-Control: public, max-age=31536000, immutable` and `Content-Type: image/svg+xml`.

- [ ] **Step 2.13: Commit**

```
git add website/features/user_profile/ website/app.py tests/unit/website/test_avatar_url_validation.py tests/unit/website/test_profile_routes.py
git commit -m "feat(profile): GET/PATCH /api/profile + avatars mount (#96)"
```

---

## Task 3: Shared avatar renderer (`avatar.js`)

**Files:**
- Create: `website/mobile/js/avatar.js`
- Modify: `website/app.py` (server-side preload `<link>` injection in `_render_with_mobile_shell`)

- [ ] **Step 3.1: Write `avatar.js`**

Create `website/mobile/js/avatar.js`:

```javascript
// avatar.js — shared avatar renderer for mobile + desktop.
// Reads /api/profile (logged-in) or falls back to the anon Zoro avatar.
// Exposes window.ZK.renderAvatar(target, opts).

(function () {
  "use strict";

  const ZORO_AVATAR = "/artifacts/avatars/avatar_00.svg";
  const ALL_AVATARS = Array.from({ length: 60 }, (_, i) =>
    `/artifacts/avatars/avatar_${String(i).padStart(2, "0")}.svg`
  );

  async function fetchProfile() {
    try {
      const r = await fetch("/api/profile", { credentials: "include" });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  /**
   * @param {HTMLElement} target — element to receive the rendered avatar
   * @param {{ size?: number, anon?: boolean }} opts
   */
  async function renderAvatar(target, opts = {}) {
    if (!target) return;
    const size = opts.size || 38;
    let url = ZORO_AVATAR;
    if (!opts.anon) {
      const prof = await fetchProfile();
      if (prof && prof.avatar_url) url = prof.avatar_url;
    }
    target.innerHTML =
      `<img class="zk-avatar-img" src="${url}" width="${size}" height="${size}" alt="" loading="lazy">`;
  }

  function avatarUrls() {
    return ALL_AVATARS.slice();
  }

  window.ZK = window.ZK || {};
  window.ZK.renderAvatar = renderAvatar;
  window.ZK.avatarUrls = avatarUrls;
})();
```

- [ ] **Step 3.2: Add server-side `<link rel="preload">` injection**

Modify `website/app.py` — find `_render_with_mobile_shell` (around line 99). Add preload tag injection after shell injection:

```python
def _render_with_mobile_shell(
    body_path: Path,
    *,
    page_title: str,
    body_class: str = "",
    request: Optional[Request] = None,
) -> HTMLResponse:
    body = body_path.read_text(encoding="utf-8")
    shell = _MOBILE_SHELL.read_text(encoding="utf-8")
    html = (
        shell
        .replace("<!--ZK_MOBILE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_PAGE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_BODY_CLASS-->", body_class)
        .replace("<!--ZK_MOBILE_CONTENT-->", body)
    )

    # Server-side avatar preload — improves first-paint for the user's own avatar.
    avatar_url = _avatar_url_from_request(request) if request else None
    preload = (
        f'<link rel="preload" as="image" type="image/svg+xml" href="{avatar_url}">'
        if avatar_url else ""
    )
    html = html.replace("<!--ZK_MOBILE_PRELOAD-->", preload)

    oauth_modal = _MOBILE_OAUTH_MODAL.read_text(encoding="utf-8")
    html = (
        html
        + "\n" + oauth_modal
        + '\n<script src="/m/js/auth-modal.js?v=20260524a"></script>'
        + '\n<script src="/m/js/avatar.js?v=20260525a"></script>'
    )
    return HTMLResponse(content=html, headers=_HTML_CACHE_HEADERS)


def _avatar_url_from_request(request: Request) -> Optional[str]:
    """Best-effort cookie decode; returns None if unauth or decode fails.

    Used for first-paint avatar preload only — never as an auth source.
    Reuses the same JWT decoder as the API auth path.
    """
    from website.api.auth import _decode_token

    token = None
    for k, v in request.cookies.items():
        if k == "sb-access-token" or (k.startswith("sb-") and k.endswith("-auth-token")):
            token = v
            break
    if not token:
        return None
    try:
        claims = _decode_token(token)
        return (claims.get("user_metadata") or {}).get("avatar_url")
    except Exception:
        return None
```

Update existing route call-sites (`/m/`, `/m/knowledge-graph`) to pass `request=request` to `_render_with_mobile_shell`.

- [ ] **Step 3.3: Add `<!--ZK_MOBILE_PRELOAD-->` placeholder to the shell**

Modify `website/mobile/templates/_shell.html` — find the `<head>` block and insert before `</head>`:

```html
  <!--ZK_MOBILE_PRELOAD-->
```

- [ ] **Step 3.4: Smoke test — preload tag present for logged-in users**

```
curl -s -A "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0)" http://localhost:10000/m/ | grep -E "rel=.preload" || echo "no preload (anon)"
```

Expected for anon: "no preload (anon)". For logged in (set cookie): the preload link appears in output.

- [ ] **Step 3.5: Commit**

```
git add website/mobile/js/avatar.js website/app.py website/mobile/templates/_shell.html
git commit -m "feat(avatar): shared renderer + server-side preload (#96)"
```

---

## Task 4: Desktop adopts `avatar.js` and drops Google fallback

**Files:**
- Modify: `website/features/user_home/js/home.js`
- Modify: `website/features/header/js/header.js` (if it exists and has its own avatar render)
- Modify: `website/mobile/js/auth-modal.js`

- [ ] **Step 4.1: Locate the desktop avatar-render call sites**

Run:

```
grep -nE "avatar_url|meta\.picture|user_metadata\.avatar" website/features/user_home/js/home.js website/features/header/js/header.js 2>/dev/null
```

Note each line number for the edits below.

- [ ] **Step 4.2: Update `home.js` — replace Google fallback chain**

In `website/features/user_home/js/home.js`, find the avatar-URL extraction (`meta.avatar_url || meta.picture || ''`) and replace with:

```javascript
// avatar.js owns the avatar URL chain; fall back to Zoro only.
const avatarUrl = meta.avatar_url || '/artifacts/avatars/avatar_00.svg';
```

If the file renders an `<img>` directly, swap to:

```javascript
if (window.ZK && window.ZK.renderAvatar) {
  window.ZK.renderAvatar(avatarSlotEl);
} else {
  avatarSlotEl.innerHTML = `<img src="${avatarUrl}" width="34" height="34" alt="">`;
}
```

Include `<script src="/m/js/avatar.js?v=20260525a"></script>` in the desktop shell (`website/features/header/header.html` or wherever desktop scripts load). If desktop has its own bundle, replicate the snippet inline (DRY note: desktop and mobile both load the same file from `/m/js/avatar.js` — the path is shared even though it lives under `/m/js/`).

- [ ] **Step 4.3: Update `auth-modal.js` to delegate avatar rendering**

In `website/mobile/js/auth-modal.js`, find the existing avatar-load code (search for `picture` or `avatar_url`) and replace with:

```javascript
function refreshHeaderAvatar() {
  const btn = document.getElementById('m-avatar-btn');
  if (!btn || !window.ZK || !window.ZK.renderAvatar) return;
  const slot = btn.querySelector('#m-avatar-image');
  if (slot) {
    slot.hidden = false;
    window.ZK.renderAvatar(slot, { size: 38 });
  }
}
```

Call `refreshHeaderAvatar()` after successful sign-in and on initial load.

- [ ] **Step 4.4: Manual verification (no automated test for visual swap)**

Restart dev server. Open http://localhost:10000/m/ on a real or emulated iPhone.

Checklist:
- [ ] Logged-out: header avatar shows Zoro avatar (`avatar_00.svg`).
- [ ] After Google sign-in (or any provider): header swaps to user's `avatar_url` (curated SVG), NOT their Google profile photo.
- [ ] Desktop home page (`http://localhost:10000/`): same avatar shows in top-right.

- [ ] **Step 4.5: Commit**

```
git add website/features/user_home/js/home.js website/features/header/js/header.js website/mobile/js/auth-modal.js
git commit -m "refactor(avatar): adopt shared renderer, drop google fallback (#96)"
```

---

## Task 5: Mobile header redesign (logo, drop title, install slot, avatar)

**Files:**
- Modify: `website/mobile/templates/_shell.html`
- Modify: `website/mobile/css/mobile.css` (header section)
- Modify: `website/mobile/js/auth-modal.js` (only if header IDs change — they should not)

- [ ] **Step 5.0: Define shared CSS variables (used by Tasks 9-13)**

In `website/mobile/css/mobile.css`, at the top under `:root { ... }` add (or merge into the existing block):

```css
:root {
  --m-header-h: 56px;
  --m-bottomnav-h: 64px;
  --m-bg: #0a0b14;
  --m-header-btn-size: 38px;
  --m-teal: #14b8a6;
  --m-amber: #D4A024;
}
```

If a `:root` block already exists, merge new vars in without replacing existing ones.

- [ ] **Step 5.1: Update the header markup**

In `website/mobile/templates/_shell.html`, replace the existing `<header class="m-header">` block (lines ~21–37) with:

```html
<header class="m-header" role="banner">
  <a class="m-header-brand" href="/m/" aria-label="Zettelkasten home">
    <img class="m-header-logo" src="/artifacts/company_logo.svg" width="22" height="22" alt="">
    <span class="m-header-brand-text">Zettelkasten</span>
  </a>
  <!-- Middle slot intentionally empty (page title removed in iter-2a) -->
  <span class="m-header-spacer" aria-hidden="true"></span>
  <button class="m-header-install" id="m-install-btn" type="button" aria-label="Install app" hidden>
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <path d="M12 3v12"></path>
      <path d="M7 10l5 5 5-5"></path>
      <rect x="4" y="17" width="16" height="4" rx="1"></rect>
    </svg>
  </button>
  <button class="m-header-avatar" id="m-avatar-btn" type="button" aria-label="Sign in or open account menu">
    <span class="m-header-avatar-anon" id="m-avatar-anon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
        <circle cx="12" cy="7" r="4"></circle>
      </svg>
    </span>
    <span class="m-header-avatar-image" id="m-avatar-image" hidden></span>
  </button>
</header>
```

- [ ] **Step 5.2: Update header CSS**

In `website/mobile/css/mobile.css`, find the `.m-header` block. Replace its `display` and grid:

```css
.m-header {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  align-items: center;
  gap: 8px;
  /* keep existing height, padding, background unchanged */
}

.m-header-title { display: none; }  /* removed per iter-2a */

.m-header-install,
.m-header-avatar {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.04);
  color: #14b8a6;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.m-header-install:hover,
.m-header-avatar:hover { background: rgba(20,184,166,0.12); }

.zk-avatar-img { border-radius: 50%; display: block; }
```

- [ ] **Step 5.3: Smoke check the header**

```
curl -s -A "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0)" http://localhost:10000/m/ | grep -E "m-header-(install|avatar|brand|title)"
```

Expected: `m-header-brand`, `m-header-install`, `m-header-avatar` present. No `m-header-title` content.

- [ ] **Step 5.4: Visual smoke (manual)**

Open `/m/` on iPhone emulation. Expected:
- [ ] Brand: company logo + "Zettelkasten" text on left.
- [ ] Middle: empty.
- [ ] Right: install icon (hidden initially) + avatar.
- [ ] No "Summarize" or page title text in the header.

- [ ] **Step 5.5: Commit**

```
git add website/mobile/templates/_shell.html website/mobile/css/mobile.css
git commit -m "feat(mobile): header redesign with install slot (#96)"
```

---

## Task 6: Bottom nav — enable tabs, renames, glass CSS, route gating

**Files:**
- Modify: `website/mobile/templates/_shell.html` (bottom nav block)
- Modify: `website/mobile/js/shell.js` (drop disabled-tab toast)
- Create: `website/mobile/css/components/glass-nav.css`
- Modify: `website/mobile/css/mobile.css` (`@import` glass-nav.css)
- Modify: `website/app.py` (3 new gated routes)
- Create: `tests/unit/website/test_mobile_routes.py`

- [ ] **Step 6.1: Write the mobile-route tests**

Create `tests/unit/website/test_mobile_routes.py`:

```python
"""Auth-gate + redirect tests for /m/zettels, /m/kastens, /m/profile."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_zettels_unauth_redirects_to_profile(client):
    r = client.get("/m/zettels", follow_redirects=False, headers={"User-Agent": "iPhone"})
    assert r.status_code == 302
    assert r.headers["location"] == "/m/profile"


def test_kastens_unauth_redirects_to_profile(client):
    r = client.get("/m/kastens", follow_redirects=False, headers={"User-Agent": "iPhone"})
    assert r.status_code == 302
    assert r.headers["location"] == "/m/profile"


def test_profile_always_200(client):
    r = client.get("/m/profile", headers={"User-Agent": "iPhone"})
    assert r.status_code == 200


def test_zettels_just_captured_anon_allowed(client):
    """Anon Summarize redirects to /m/zettels?just_captured=<id>; do NOT bounce."""
    r = client.get(
        "/m/zettels?just_captured=abc-123",
        follow_redirects=False,
        headers={"User-Agent": "iPhone"},
    )
    assert r.status_code == 200


@patch("website.app._has_supabase_session", return_value=True)
def test_zettels_auth_renders(mock_sess, client):
    r = client.get("/m/zettels", headers={"User-Agent": "iPhone"})
    assert r.status_code == 200


@patch("website.app._has_supabase_session", return_value=True)
def test_kastens_auth_renders(mock_sess, client):
    r = client.get("/m/kastens", headers={"User-Agent": "iPhone"})
    assert r.status_code == 200
```

- [ ] **Step 6.2: Run — expect FAIL (routes don't exist)**

```
pytest tests/unit/website/test_mobile_routes.py -v
```

Expected: 404s on /m/zettels, /m/kastens, /m/profile.

- [ ] **Step 6.3: Add the routes + auth gate to `website/app.py`**

Add helper near other helpers in `website/app.py`:

```python
def _has_supabase_session(request: Request) -> bool:
    """Best-effort check for a Supabase session cookie.

    Covers both the legacy `sb-access-token` and the modern
    `sb-<project-ref>-auth-token` cookie naming conventions.
    """
    if request.cookies.get("sb-access-token") or request.cookies.get("sb-refresh-token"):
        return True
    for k in request.cookies:
        if k.startswith("sb-") and (k.endswith("-auth-token") or k.endswith("-refresh-token")):
            return True
    return False
```

Add three new routes alongside `mobile_index` / `mobile_knowledge_graph`:

```python
    @app.get("/m/zettels")
    async def mobile_zettels(request: Request):
        if not _has_supabase_session(request) and "just_captured" not in request.query_params:
            return RedirectResponse("/m/profile", status_code=302)
        return _render_with_mobile_shell(
            MOBILE_DIR / "zettels.html",
            page_title="Zettels",
            body_class="m-zettels",
            request=request,
        )

    @app.get("/m/kastens")
    async def mobile_kastens(request: Request):
        if not _has_supabase_session(request):
            return RedirectResponse("/m/profile", status_code=302)
        return _render_with_mobile_shell(
            MOBILE_DIR / "kastens.html",
            page_title="Kastens",
            body_class="m-kastens",
            request=request,
        )

    @app.get("/m/profile")
    async def mobile_profile(request: Request):
        return _render_with_mobile_shell(
            MOBILE_DIR / "profile.html",
            page_title="Profile",
            body_class="m-profile",
            request=request,
        )
```

- [ ] **Step 6.4: Create the three placeholder body files**

Create `website/mobile/zettels.html`:

```html
<!-- Body fragment for /m/zettels — will be filled in Task 9. -->
<section class="m-zettels-shell"></section>
```

Create `website/mobile/kastens.html`:

```html
<!-- Body fragment for /m/kastens — will be filled in Task 10. -->
<section class="m-kastens-shell"></section>
```

Create `website/mobile/profile.html`:

```html
<!-- Body fragment for /m/profile — will be filled in Task 11. -->
<section class="m-profile-shell"></section>
```

- [ ] **Step 6.5: Run mobile-route tests — expect PASS**

```
pytest tests/unit/website/test_mobile_routes.py -v
```

Expected: 6 PASS.

- [ ] **Step 6.6: Update the bottom nav markup**

In `website/mobile/templates/_shell.html`, find the `.m-bottom-tabs` block (lines ~43–64) and replace with:

```html
<nav class="m-bottom-tabs glass-nav" role="navigation" aria-label="Primary">
  <a class="m-tab" data-tab="capture" href="/m/">
    <svg class="m-tab-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
    <span class="m-tab-label">Capture</span>
  </a>
  <a class="m-tab" data-tab="zettels" href="/m/zettels">
    <svg class="m-tab-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="3" width="16" height="18" rx="2"/></svg>
    <span class="m-tab-label">Zettels</span>
  </a>
  <a class="m-tab" data-tab="kastens" href="/m/kastens">
    <svg class="m-tab-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
    <span class="m-tab-label">Kastens</span>
  </a>
  <a class="m-tab" data-tab="graph" href="/m/knowledge-graph">
    <svg class="m-tab-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><line x1="6" y1="6" x2="12" y2="18"/><line x1="18" y1="6" x2="12" y2="18"/></svg>
    <span class="m-tab-label">Graph</span>
  </a>
  <a class="m-tab" data-tab="profile" href="/m/profile">
    <svg class="m-tab-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="7" r="4"/><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/></svg>
    <span class="m-tab-label">Profile</span>
  </a>
</nav>
```

- [ ] **Step 6.7: Drop the disabled-tab toast from `shell.js`**

In `website/mobile/js/shell.js`, find the `disabled` tab click handler (around lines 24–51) and delete the block — all tabs are now real `<a>` links.

- [ ] **Step 6.8: Create the glass-nav CSS**

Create `website/mobile/css/components/glass-nav.css`:

```css
/* glass-nav.css — backdrop-filter recipe scoped to .m-bottom-tabs. */

.m-bottom-tabs.glass-nav {
  position: fixed;
  bottom: 0; left: 0; right: 0;
  background: rgba(10, 11, 20, 0.68);
  -webkit-backdrop-filter: blur(16px) saturate(170%);
          backdrop-filter: blur(16px) saturate(170%);
  border-top: 1px solid rgba(20, 184, 166, 0.14);
  box-shadow: 0 -6px 20px rgba(0, 0, 0, 0.32);
  padding-bottom: env(safe-area-inset-bottom, 0px);
  will-change: backdrop-filter;
  contain: layout paint;
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .m-bottom-tabs.glass-nav { background: rgba(10, 11, 20, 0.94); }
}

.m-bottom-tabs.glass-nav .m-tab.is-active .m-tab-icon { color: #14b8a6; }
.m-bottom-tabs.glass-nav .m-tab.is-active .m-tab-label { color: #14b8a6; font-weight: 600; }
```

- [ ] **Step 6.9: Import glass-nav.css**

In `website/mobile/css/mobile.css`, add to the imports near the top:

```css
@import url("./components/glass-nav.css");
```

- [ ] **Step 6.10: Manual visual check**

Restart dev server. Open `/m/`, `/m/zettels` (logged in), `/m/knowledge-graph` on iPhone emulation.
- [ ] Bottom nav shows 5 tabs: Capture / Zettels / Kastens / Graph / Profile.
- [ ] Glass blur visible over scrolled content.
- [ ] Active tab highlighted teal.

- [ ] **Step 6.11: Commit**

```
git add website/mobile/templates/_shell.html website/mobile/js/shell.js website/mobile/css/components/glass-nav.css website/mobile/css/mobile.css website/app.py website/mobile/zettels.html website/mobile/kastens.html website/mobile/profile.html tests/unit/website/test_mobile_routes.py
git commit -m "feat(mobile): bottom nav renames, glass, gated routes (#96)"
```

---

## Task 7: Hamburger sheet primitive

**Files:**
- Create: `website/mobile/js/hamburger-sheet.js`
- Create: `website/mobile/css/components/hamburger-sheet.css`
- Modify: `website/mobile/css/mobile.css` (`@import`)

This is a pure JS+CSS component with no Python backend, so unit tests live in a separate `tests/unit/mobile/` folder using a tiny DOM stub. **If pytest-playwright is not available, this task uses a manual verification playbook instead — flagged explicitly below.**

- [ ] **Step 7.1: Write the sheet primitive**

Create `website/mobile/js/hamburger-sheet.js`:

```javascript
// hamburger-sheet.js — bottom-sheet primitive (single-instance at a time).
// Usage:
//   ZK.openSheet({
//     title: 'Pick source',
//     options: [{ value: 'auto', label: 'Auto-detect', selected: true }, ...],
//     onSelect: (value) => { ... },
//   });

(function () {
  "use strict";

  let activeRoot = null;

  function ensureRoot() {
    if (activeRoot) return activeRoot;
    const root = document.createElement('div');
    root.className = 'zk-sheet-root';
    root.innerHTML =
      '<div class="zk-sheet-backdrop" data-close="1"></div>' +
      '<div class="zk-sheet" role="dialog" aria-modal="true">' +
        '<div class="zk-sheet-handle"></div>' +
        '<div class="zk-sheet-title"></div>' +
        '<div class="zk-sheet-list"></div>' +
      '</div>';
    document.body.appendChild(root);
    root.addEventListener('click', (e) => {
      if (e.target instanceof HTMLElement && e.target.dataset.close === '1') closeSheet();
    });
    activeRoot = root;
    return root;
  }

  function openSheet(spec) {
    const root = ensureRoot();
    root.querySelector('.zk-sheet-title').textContent = spec.title || '';
    const list = root.querySelector('.zk-sheet-list');
    list.innerHTML = '';
    spec.options.forEach((opt) => {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'zk-sheet-cell' + (opt.selected ? ' is-selected' : '');
      cell.dataset.value = opt.value;
      cell.innerHTML = (opt.icon || '') + '<span class="zk-sheet-cell-label">' + opt.label + '</span>';
      cell.addEventListener('click', () => {
        spec.onSelect && spec.onSelect(opt.value);
        closeSheet();
      });
      list.appendChild(cell);
    });
    requestAnimationFrame(() => root.classList.add('is-open'));
  }

  function closeSheet() {
    if (!activeRoot) return;
    activeRoot.classList.remove('is-open');
    setTimeout(() => {
      if (activeRoot) { activeRoot.remove(); activeRoot = null; }
    }, 250);
  }

  window.ZK = window.ZK || {};
  window.ZK.openSheet = openSheet;
  window.ZK.closeSheet = closeSheet;
})();
```

- [ ] **Step 7.2: Style the sheet**

Create `website/mobile/css/components/hamburger-sheet.css`:

```css
/* hamburger-sheet.css — bottom-sheet styling. */

.zk-sheet-root {
  position: fixed; inset: 0; z-index: 70;
  pointer-events: none;
}
.zk-sheet-backdrop {
  position: absolute; inset: 0;
  background: rgba(0,0,0,0.45);
  opacity: 0;
  transition: opacity 200ms ease;
  pointer-events: auto;
}
.zk-sheet {
  position: absolute; left: 0; right: 0; bottom: 0;
  background: #11131c;
  border-top: 1px solid rgba(20,184,166,0.16);
  border-radius: 18px 18px 0 0;
  padding: 8px 16px calc(env(safe-area-inset-bottom, 0px) + 16px);
  transform: translateY(100%);
  transition: transform 240ms cubic-bezier(.32,.72,0,1);
  pointer-events: auto;
}
.zk-sheet-root.is-open .zk-sheet-backdrop { opacity: 1; }
.zk-sheet-root.is-open .zk-sheet { transform: translateY(0); }

.zk-sheet-handle {
  width: 36px; height: 4px;
  background: rgba(255,255,255,0.16);
  border-radius: 2px;
  margin: 8px auto 12px;
}
.zk-sheet-title {
  font-size: 14px; color: rgba(255,255,255,0.7);
  margin-bottom: 8px; padding: 0 4px;
  text-transform: uppercase; letter-spacing: 0.06em;
}
.zk-sheet-list { display: flex; flex-direction: column; }
.zk-sheet-cell {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 8px;
  background: transparent; border: 0;
  color: #e6e6e6; text-align: left;
  border-radius: 10px;
}
.zk-sheet-cell.is-selected { background: rgba(20,184,166,0.14); color: #14b8a6; }
.zk-sheet-cell:active { background: rgba(255,255,255,0.06); }
.zk-sheet-cell-label { flex: 1; font-size: 16px; }
```

- [ ] **Step 7.3: Import the CSS**

In `website/mobile/css/mobile.css`:

```css
@import url("./components/hamburger-sheet.css");
```

- [ ] **Step 7.4: Wire the script in the shell**

In `website/mobile/templates/_shell.html`, add before `</body>`:

```html
<script src="/m/js/hamburger-sheet.js?v=20260525a"></script>
```

- [ ] **Step 7.5: Manual verification playbook**

Restart dev server. Open `/m/`. In DevTools console:

```javascript
ZK.openSheet({
  title: 'Test',
  options: [
    { value: 'a', label: 'Alpha', selected: true },
    { value: 'b', label: 'Bravo' },
  ],
  onSelect: (v) => console.log('picked', v),
});
```

- [ ] Sheet slides up from bottom with backdrop dim.
- [ ] Tap "Bravo" → console logs `picked b`, sheet closes.
- [ ] Tap backdrop → sheet closes.
- [ ] No errors in console.

- [ ] **Step 7.6: Commit**

```
git add website/mobile/js/hamburger-sheet.js website/mobile/css/components/hamburger-sheet.css website/mobile/css/mobile.css website/mobile/templates/_shell.html
git commit -m "feat(mobile): hamburger bottom-sheet primitive (#96)"
```

---

## Task 8: Capture page — hamburger source picker + remove inline summary + redirect

**Files:**
- Modify: `website/mobile/index.html`
- Modify: `website/mobile/js/summarizer.js`
- Modify: `website/mobile/css/mobile.css` (`.m-form` updates)

- [ ] **Step 8.1: Update the form markup**

In `website/mobile/index.html`, find the `#summarize-form` block. Replace with:

```html
<form class="m-form" id="summarize-form" autocomplete="off" data-source="auto">
  <div class="m-input-group m-input-group--hamburger">
    <button type="button" class="m-form-doc" id="document-upload-btn" aria-label="Upload document">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
    </button>
    <input type="file" id="document-input" accept=".pdf,.txt,.md,.docx" hidden>
    <input type="url" id="url-input" name="url" class="m-input" placeholder="Paste a URL…" required>
    <button type="button" class="m-form-hamburger" id="source-picker-btn" aria-label="Source override">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
    </button>
  </div>
  <button type="submit" id="submit-btn" class="m-btn m-btn-primary">Summarize</button>
</form>

<!-- Remove the #m-result element entirely. -->
```

- [ ] **Step 8.2: Update the form CSS**

In `website/mobile/css/mobile.css`, add after the existing `.m-input-group` rules:

```css
.m-input-group.m-input-group--hamburger { position: relative; }
.m-form-hamburger {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  width: 32px; height: 32px;
  display: inline-flex; align-items: center; justify-content: center;
  background: rgba(20,184,166,0.08);
  border: 1px solid rgba(20,184,166,0.2);
  border-radius: 8px;
  color: #14b8a6;
}
.m-form-hamburger:active { background: rgba(20,184,166,0.2); }
.m-input-group--hamburger .m-input { padding-right: 48px; }
```

- [ ] **Step 8.3: Rewrite `summarizer.js` to use sheet + redirect**

Replace `website/mobile/js/summarizer.js` contents:

```javascript
// summarizer.js — capture-form handler.
// Opens source-picker sheet, submits to /api/zettels/add, redirects to /m/zettels.

(function () {
  "use strict";

  const SOURCES = [
    { value: 'auto',       label: 'Auto-detect',   selected: true  },
    { value: 'youtube',    label: 'YouTube'                       },
    { value: 'github',     label: 'GitHub'                        },
    { value: 'reddit',     label: 'Reddit'                        },
    { value: 'newsletter', label: 'Newsletter'                    },
    { value: 'web',        label: 'Web'                           },
  ];

  function attach() {
    const form = document.getElementById('summarize-form');
    const picker = document.getElementById('source-picker-btn');
    if (!form || !picker) return;

    picker.addEventListener('click', () => {
      const current = form.dataset.source || 'auto';
      window.ZK.openSheet({
        title: 'Source',
        options: SOURCES.map(s => ({ ...s, selected: s.value === current })),
        onSelect: (v) => { form.dataset.source = v; },
      });
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const url = document.getElementById('url-input').value.trim();
      if (!url) return;
      const submitBtn = document.getElementById('submit-btn');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Summarizing…';

      try {
        const r = await fetch('/api/zettels/add', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url,
            source_override: form.dataset.source || 'auto',
            surface: 'mobile',
          }),
        });
        if (!r.ok) throw new Error('summarize failed: ' + r.status);
        const data = await r.json();
        const id = data.id || data.zettel_id || '';
        window.location.assign('/m/zettels' + (id ? '?just_captured=' + encodeURIComponent(id) : ''));
      } catch (err) {
        console.error(err);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Summarize';
        alert('Could not summarize. Please try again.');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }
})();
```

- [ ] **Step 8.4: Manual verification**

Restart dev server. Open `/m/`.
- [ ] Hamburger button visible inside URL input on the right.
- [ ] Tap hamburger → sheet opens with 6 sources, Auto-detect highlighted.
- [ ] Pick "GitHub" → sheet closes; `form.dataset.source === 'github'`.
- [ ] Paste a GitHub URL, tap Summarize → button disables; after success, URL changes to `/m/zettels?just_captured=<id>`.

- [ ] **Step 8.5: Commit**

```
git add website/mobile/index.html website/mobile/js/summarizer.js website/mobile/css/mobile.css
git commit -m "feat(mobile): capture-form hamburger + redirect on submit (#96)"
```

---

## Task 9: Mobile Zettels page — search + filter sheet + list + detail modal

**Files:**
- Modify: `website/mobile/zettels.html`
- Create: `website/mobile/js/zettels.js`
- Create: `website/mobile/css/pages/zettels.css`
- Modify: `website/mobile/css/mobile.css` (`@import`)

- [ ] **Step 9.1: Build the page markup**

Replace `website/mobile/zettels.html` placeholder with:

```html
<!-- Mobile Zettels — lean port of desktop user_zettels. -->
<section class="m-zettels-page">
  <div class="m-zettels-toolbar">
    <input type="search" class="m-zettels-search" id="zettels-search" placeholder="Search your zettels…">
    <button type="button" class="m-zettels-filter-btn" id="zettels-filter-btn" aria-label="Filter">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
    </button>
  </div>

  <div class="m-zettels-anon-banner" id="zettels-anon-banner" hidden>
    <p>Sign in to keep your collection.</p>
    <button type="button" class="m-btn m-btn-primary" id="zettels-anon-signin">Sign in</button>
  </div>

  <ul class="m-zettels-list" id="zettels-list" role="list"></ul>

  <div class="m-zettels-empty" id="zettels-empty" hidden>
    <p>No zettels yet.</p>
  </div>

  <div class="m-zettels-detail" id="zettels-detail" role="dialog" aria-modal="true" hidden>
    <button type="button" class="m-zettels-detail-close" id="zettels-detail-close" aria-label="Close">×</button>
    <div class="m-zettels-detail-content" id="zettels-detail-content"></div>
  </div>
</section>

<script src="/m/js/zettels.js?v=20260525a"></script>
```

- [ ] **Step 9.2: Build `zettels.js`**

Create `website/mobile/js/zettels.js`:

```javascript
// zettels.js — mobile zettels list + filter + detail-modal.

(function () {
  "use strict";

  const state = {
    items: [],
    filtered: [],
    search: '',
    source: 'all',
    tag: '',
    range: 'all',
    sort: 'newest',
    justCapturedId: null,
  };

  function qs(sel) { return document.querySelector(sel); }

  async function loadZettels() {
    const params = new URLSearchParams();
    if (state.justCapturedId) params.set('id', state.justCapturedId);
    const r = await fetch('/api/zettels?' + params.toString(), { credentials: 'include' });
    if (!r.ok) { renderEmpty(); return; }
    const data = await r.json();
    state.items = data.items || data || [];
    applyFiltersAndRender();
  }

  function applyFiltersAndRender() {
    let out = state.items.slice();

    if (state.search) {
      const q = state.search.toLowerCase();
      out = out.filter(z => (z.title || '').toLowerCase().includes(q) || (z.summary || '').toLowerCase().includes(q));
    }
    if (state.source !== 'all') out = out.filter(z => (z.source || '').toLowerCase() === state.source);
    if (state.tag) out = out.filter(z => Array.isArray(z.tags) && z.tags.includes(state.tag));
    if (state.range !== 'all') {
      const days = { today: 1, '7d': 7, '30d': 30 }[state.range] || 0;
      if (days > 0) {
        const cutoff = Date.now() - days * 86400000;
        out = out.filter(z => new Date(z.created_at || 0).getTime() >= cutoff);
      }
    }
    const sorters = {
      newest: (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0),
      oldest: (a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0),
      'a-z':  (a, b) => (a.title || '').localeCompare(b.title || ''),
      source: (a, b) => (a.source || '').localeCompare(b.source || ''),
    };
    out.sort(sorters[state.sort] || sorters.newest);

    state.filtered = out;
    renderList();
  }

  function renderList() {
    const list = qs('#zettels-list');
    const empty = qs('#zettels-empty');
    list.innerHTML = '';
    if (state.filtered.length === 0) { empty.hidden = false; return; }
    empty.hidden = true;
    state.filtered.forEach(z => {
      const li = document.createElement('li');
      li.className = 'm-zettel-card';
      li.dataset.id = z.id;
      li.innerHTML =
        '<div class="m-zettel-card-title">' + (z.title || 'Untitled') + '</div>' +
        '<div class="m-zettel-card-meta">' +
          '<span class="m-zettel-card-source">' + (z.source || '—') + '</span>' +
          '<span class="m-zettel-card-time">' + relativeTime(z.created_at) + '</span>' +
        '</div>';
      li.addEventListener('click', () => openDetail(z));
      list.appendChild(li);
    });
  }

  function renderEmpty() {
    qs('#zettels-list').innerHTML = '';
    qs('#zettels-empty').hidden = false;
  }

  function relativeTime(iso) {
    if (!iso) return '';
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return new Date(iso).toLocaleDateString();
  }

  function openDetail(z) {
    const detail = qs('#zettels-detail');
    qs('#zettels-detail-content').innerHTML =
      '<h2>' + (z.title || 'Untitled') + '</h2>' +
      '<a class="m-zettel-detail-link" href="' + (z.url || '#') + '" target="_blank" rel="noopener noreferrer">Open source</a>' +
      '<div class="m-zettel-detail-summary">' + (z.summary_html || z.summary || '') + '</div>';
    detail.hidden = false;
    history.pushState({ detail: z.id }, '');
  }
  function closeDetail() {
    qs('#zettels-detail').hidden = true;
    if (history.state && history.state.detail) history.back();
  }

  // Filter sheet — supports source / tag / date-range / sort sections (spec D8).
  function openFilterSheet() {
    const root = document.createElement('div');
    root.className = 'zk-sheet-root zk-filter-sheet';
    root.innerHTML =
      '<div class="zk-sheet-backdrop" data-close="1"></div>' +
      '<div class="zk-sheet" role="dialog" aria-modal="true">' +
        '<div class="zk-sheet-handle"></div>' +
        '<div class="zk-sheet-title">Filter</div>' +

        '<div class="zk-filter-section"><div class="zk-filter-section-h">Source</div>' +
          '<div class="zk-filter-chips" data-group="source">' +
            chip('all', 'All', state.source === 'all') +
            chip('youtube', 'YouTube', state.source === 'youtube') +
            chip('github',  'GitHub',  state.source === 'github')  +
            chip('reddit',  'Reddit',  state.source === 'reddit')  +
            chip('newsletter', 'Newsletter', state.source === 'newsletter') +
            chip('web',     'Web',     state.source === 'web') +
          '</div>' +
        '</div>' +

        '<div class="zk-filter-section"><div class="zk-filter-section-h">Tag</div>' +
          '<input type="search" class="zk-filter-tag-input" placeholder="Filter by tag…" value="' + (state.tag || '') + '">' +
        '</div>' +

        '<div class="zk-filter-section"><div class="zk-filter-section-h">Date range</div>' +
          '<div class="zk-filter-chips" data-group="range">' +
            chip('all',   'All',     state.range === 'all')   +
            chip('today', 'Today',   state.range === 'today') +
            chip('7d',    'Last 7d', state.range === '7d')    +
            chip('30d',   'Last 30d',state.range === '30d')   +
          '</div>' +
        '</div>' +

        '<div class="zk-filter-section"><div class="zk-filter-section-h">Sort</div>' +
          '<div class="zk-filter-chips" data-group="sort">' +
            chip('newest', 'Newest', state.sort === 'newest') +
            chip('oldest', 'Oldest', state.sort === 'oldest') +
            chip('a-z',    'A → Z',  state.sort === 'a-z')    +
            chip('source', 'Source', state.sort === 'source') +
          '</div>' +
        '</div>' +

        '<button type="button" class="m-btn m-btn-primary zk-filter-apply">Apply</button>' +
      '</div>';

    document.body.appendChild(root);
    requestAnimationFrame(() => root.classList.add('is-open'));

    root.addEventListener('click', (e) => {
      const target = e.target;
      if (target instanceof HTMLElement && target.dataset.close === '1') {
        closeFilterSheet(root);
        return;
      }
      const chipEl = target.closest && target.closest('[data-value]');
      if (chipEl) {
        const group = chipEl.parentElement.dataset.group;
        chipEl.parentElement.querySelectorAll('[data-value]').forEach(el => el.classList.remove('is-selected'));
        chipEl.classList.add('is-selected');
        if (group === 'source') state.source = chipEl.dataset.value;
        if (group === 'range')  state.range  = chipEl.dataset.value;
        if (group === 'sort')   state.sort   = chipEl.dataset.value;
      }
      if (target.classList && target.classList.contains('zk-filter-apply')) {
        const tagInput = root.querySelector('.zk-filter-tag-input');
        state.tag = (tagInput && tagInput.value || '').trim();
        applyFiltersAndRender();
        closeFilterSheet(root);
      }
    });
  }

  function chip(value, label, selected) {
    return '<button type="button" class="zk-filter-chip' + (selected ? ' is-selected' : '') +
           '" data-value="' + value + '">' + label + '</button>';
  }

  function closeFilterSheet(root) {
    root.classList.remove('is-open');
    setTimeout(() => root.remove(), 240);
  }

  function init() {
    const qp = new URLSearchParams(location.search);
    state.justCapturedId = qp.get('just_captured');
    if (state.justCapturedId && !document.cookie.includes('sb-access-token')) {
      qs('#zettels-anon-banner').hidden = false;
    }
    qs('#zettels-search').addEventListener('input', (e) => {
      state.search = e.target.value;
      applyFiltersAndRender();
    });
    qs('#zettels-filter-btn').addEventListener('click', openFilterSheet);
    qs('#zettels-detail-close').addEventListener('click', closeDetail);
    qs('#zettels-anon-signin').addEventListener('click', () => location.assign('/m/profile'));
    window.addEventListener('popstate', () => { qs('#zettels-detail').hidden = true; });

    loadZettels();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

- [ ] **Step 9.3: Style the page**

Create `website/mobile/css/pages/zettels.css`:

```css
/* zettels.css — mobile Zettels list + detail modal. */

.m-zettels-page { padding: 16px 16px calc(var(--m-bottomnav-h, 64px) + 24px); }

.m-zettels-toolbar {
  position: sticky; top: var(--m-header-h, 56px); z-index: 5;
  display: flex; gap: 8px;
  padding: 8px 0;
  background: var(--m-bg, #0a0b14);
}
.m-zettels-search {
  flex: 1;
  padding: 10px 14px;
  border-radius: 10px;
  background: #11131c;
  border: 1px solid rgba(255,255,255,0.06);
  color: #e6e6e6;
}
.m-zettels-filter-btn {
  width: 40px; height: 40px;
  border-radius: 10px;
  background: rgba(20,184,166,0.10);
  border: 1px solid rgba(20,184,166,0.18);
  color: #14b8a6;
  display: inline-flex; align-items: center; justify-content: center;
}

.m-zettels-anon-banner {
  margin: 12px 0;
  padding: 12px 14px;
  background: rgba(20,184,166,0.10);
  border: 1px solid rgba(20,184,166,0.22);
  border-radius: 12px;
  display: flex; gap: 12px; align-items: center; justify-content: space-between;
}

.m-zettels-list { list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 10px; }
.m-zettel-card {
  background: #11131c;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 12px 14px;
}
.m-zettel-card-title { color: #e6e6e6; font-weight: 600; margin-bottom: 6px; }
.m-zettel-card-meta {
  display: flex; justify-content: space-between;
  color: rgba(255,255,255,0.6); font-size: 13px;
}

.m-zettels-empty { text-align: center; color: rgba(255,255,255,0.6); padding: 40px 0; }

.m-zettels-detail {
  position: fixed; inset: 0;
  background: #0a0b14;
  z-index: 80;
  overflow-y: auto;
  padding: 16px 18px calc(var(--m-bottomnav-h, 64px) + 24px);
}
.m-zettels-detail-close {
  position: sticky; top: 0; right: 8px; margin-left: auto;
  display: block;
  width: 36px; height: 36px;
  background: rgba(255,255,255,0.06); border: 0; color: #fff;
  font-size: 24px; line-height: 1; border-radius: 50%;
}

/* Multi-section filter sheet (D8). */
.zk-filter-sheet .zk-sheet { padding-bottom: calc(env(safe-area-inset-bottom, 0px) + 24px); }
.zk-filter-section { margin: 14px 0 6px; }
.zk-filter-section-h {
  font-size: 12px; color: rgba(255,255,255,0.6);
  text-transform: uppercase; letter-spacing: 0.06em;
  margin-bottom: 8px;
}
.zk-filter-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.zk-filter-chip {
  padding: 6px 12px; border-radius: 999px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  color: #e6e6e6; font-size: 13px;
}
.zk-filter-chip.is-selected {
  background: rgba(20,184,166,0.18);
  border-color: rgba(20,184,166,0.4);
  color: #14b8a6;
}
.zk-filter-tag-input {
  width: 100%;
  padding: 10px 12px;
  background: #11131c;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px;
  color: #e6e6e6;
}
.zk-filter-apply { width: 100%; margin-top: 14px; }
```

- [ ] **Step 9.4: Import the page CSS**

In `website/mobile/css/mobile.css`:

```css
@import url("./pages/zettels.css");
```

- [ ] **Step 9.5: Manual verification**

Sign in. Open `/m/zettels`.
- [ ] Search input + filter icon visible.
- [ ] Existing zettels render as cards.
- [ ] Tap a card → fullscreen detail modal opens.
- [ ] Filter button opens sort sheet; picking "A → Z" re-orders.
- [ ] Sign out + visit `/m/zettels?just_captured=<id>` → renders only that zettel + anon banner.

- [ ] **Step 9.6: Commit**

```
git add website/mobile/zettels.html website/mobile/js/zettels.js website/mobile/css/pages/zettels.css website/mobile/css/mobile.css
git commit -m "feat(mobile): zettels list + filter + detail (#96)"
```

---

## Task 10: Mobile Kastens page — grid + Create FAB + desktop-redirect on tap

**Files:**
- Modify: `website/mobile/kastens.html`
- Create: `website/mobile/js/kastens.js`
- Create: `website/mobile/css/pages/kastens.css`
- Modify: `website/mobile/css/mobile.css` (`@import`)

- [ ] **Step 10.1: Build the page markup**

Replace `website/mobile/kastens.html` placeholder with:

```html
<section class="m-kastens-page">
  <div class="m-kastens-grid" id="kastens-grid" role="list"></div>
  <div class="m-kastens-empty" id="kastens-empty" hidden>
    <p>No Kastens yet. Tap + to create one.</p>
  </div>
  <button type="button" class="m-kastens-fab" id="kastens-create-fab" aria-label="Create Kasten">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
  </button>
</section>
<script src="/m/js/kastens.js?v=20260525a"></script>
```

- [ ] **Step 10.2: Build `kastens.js`**

Create `website/mobile/js/kastens.js`:

```javascript
// kastens.js — mobile Kasten grid + Create FAB.
// Tap on a Kasten opens the desktop view (per design D7 for iter-2a).

(function () {
  "use strict";

  async function load() {
    const r = await fetch('/api/kastens', { credentials: 'include' });
    if (!r.ok) return [];
    const data = await r.json();
    return data.items || data || [];
  }

  function render(items) {
    const grid = document.getElementById('kastens-grid');
    const empty = document.getElementById('kastens-empty');
    grid.innerHTML = '';
    if (!items.length) { empty.hidden = false; return; }
    empty.hidden = true;
    items.forEach(k => {
      const card = document.createElement('a');
      card.className = 'm-kasten-card';
      card.href = '/u/kastens/' + k.id + '?desktop=1';   // per design D7: open desktop view
      card.setAttribute('role', 'listitem');
      card.innerHTML =
        '<div class="m-kasten-card-name">' + (k.name || 'Untitled') + '</div>' +
        '<div class="m-kasten-card-meta">' +
          '<span class="m-kasten-card-badge m-kasten-card-badge--' + (k.quality || 'fast') + '">' + (k.quality || 'fast') + '</span>' +
          '<span class="m-kasten-card-count">' + (k.zettel_count || 0) + ' zettels</span>' +
        '</div>';
      grid.appendChild(card);
    });
  }

  function openCreateModal() {
    // Reuse desktop create-modal HTML — load fragment into a fullscreen overlay.
    location.assign('/u/kastens?desktop=1&open_create=1');
  }

  async function init() {
    document.getElementById('kastens-create-fab').addEventListener('click', openCreateModal);
    const items = await load();
    render(items);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

- [ ] **Step 10.3: Style the page**

Create `website/mobile/css/pages/kastens.css`:

```css
/* kastens.css — mobile Kasten grid + FAB. */

.m-kastens-page {
  padding: 16px 16px calc(var(--m-bottomnav-h, 64px) + 24px);
}
.m-kastens-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.m-kasten-card {
  background: #11131c;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 14px;
  color: #e6e6e6;
  text-decoration: none;
  min-height: 100px;
  display: flex; flex-direction: column; justify-content: space-between;
}
.m-kasten-card-name { font-weight: 600; font-size: 15px; }
.m-kasten-card-meta { display: flex; gap: 8px; align-items: center; font-size: 12px; }
.m-kasten-card-badge {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(20,184,166,0.16);
  color: #14b8a6;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.m-kasten-card-badge--strong { background: rgba(212,160,36,0.18); color: #D4A024; }

.m-kastens-empty { text-align: center; color: rgba(255,255,255,0.6); padding: 60px 0; }

.m-kastens-fab {
  position: fixed;
  right: 18px;
  bottom: calc(var(--m-bottomnav-h, 64px) + env(safe-area-inset-bottom, 0px) + 18px);
  width: 56px; height: 56px;
  border-radius: 50%;
  background: #14b8a6;
  border: 0;
  color: #0a0b14;
  display: inline-flex; align-items: center; justify-content: center;
  box-shadow: 0 8px 20px rgba(20,184,166,0.35);
  z-index: 20;
}
```

- [ ] **Step 10.4: Import the page CSS**

In `website/mobile/css/mobile.css`:

```css
@import url("./pages/kastens.css");
```

- [ ] **Step 10.5: Manual verification**

Sign in. Open `/m/kastens`.
- [ ] Grid of existing Kastens renders (2-col).
- [ ] Quality badge teal (Fast) or amber (Strong).
- [ ] Tap a card → desktop view loads with `?desktop=1`.
- [ ] Tap FAB → navigates to `/u/kastens?desktop=1&open_create=1`.

- [ ] **Step 10.6: Commit**

```
git add website/mobile/kastens.html website/mobile/js/kastens.js website/mobile/css/pages/kastens.css website/mobile/css/mobile.css
git commit -m "feat(mobile): kastens grid + create FAB (#96)"
```

---

## Task 11: Mobile Profile page — auth + unauth + avatar picker

**Files:**
- Modify: `website/mobile/profile.html`
- Create: `website/mobile/js/profile.js`
- Create: `website/mobile/css/pages/profile.css`
- Create: `website/mobile/css/components/avatar-picker.css`
- Modify: `website/mobile/css/mobile.css` (`@import` × 2)

- [ ] **Step 11.0: Audit auth-modal.js for sign-in / sign-out helpers**

`profile.js` (next step) calls `window.zkAuthLogin(provider)` and `window.zkAuthSignOut()`. Verify they're exposed by `website/mobile/js/auth-modal.js`:

```
grep -nE "window\.(zkAuthLogin|zkAuthSignOut)" website/mobile/js/auth-modal.js
```

If either is missing, add it at the bottom of `auth-modal.js`:

```javascript
// Public helpers consumed by /m/profile inline OAuth + sign-out.
window.zkAuthLogin = async function (provider) {
  // Reuse the existing modal's provider-button click handler if available.
  const btn = document.querySelector(`#m-oauth-modal [data-provider="${provider}"]`);
  if (btn) { btn.click(); return; }
  console.warn('No OAuth button for provider', provider);
};

window.zkAuthSignOut = async function () {
  const sb = window._supabase || (window.supabase && window.supabase.auth && window.supabase);
  if (sb && sb.auth && sb.auth.signOut) await sb.auth.signOut();
  // Clear any leftover sb-* cookies as a defensive measure.
  document.cookie.split(';').forEach(c => {
    const name = c.split('=')[0].trim();
    if (name.startsWith('sb-')) document.cookie = `${name}=; Path=/; Max-Age=0`;
  });
};
```

- [ ] **Step 11.1: Build the page markup**

Replace `website/mobile/profile.html` placeholder with:

```html
<section class="m-profile-page">

  <!-- Unauth state: shown via JS when no session. -->
  <div class="m-profile-unauth" id="profile-unauth" hidden>
    <h2 class="m-profile-title">Sign in to Zettelkasten</h2>
    <p class="m-profile-sub">Keep your captures across devices.</p>
    <div class="m-profile-oauth" id="profile-oauth-inline"></div>
  </div>

  <!-- Auth state: shown via JS when signed in. -->
  <div class="m-profile-auth" id="profile-auth" hidden>
    <div class="m-profile-card">
      <span class="m-profile-avatar" id="profile-avatar"></span>
      <div class="m-profile-meta">
        <div class="m-profile-email" id="profile-email"></div>
        <button type="button" class="m-profile-signout" id="profile-signout">Sign out</button>
      </div>
    </div>

    <h3 class="m-profile-section-title">Change avatar</h3>
    <div class="m-avatar-picker" id="avatar-picker"></div>
  </div>
</section>
<script src="/m/js/profile.js?v=20260525a"></script>
```

- [ ] **Step 11.2: Build `profile.js`**

Create `website/mobile/js/profile.js`:

```javascript
// profile.js — auth/unauth states + avatar picker.

(function () {
  "use strict";

  function hasSession() {
    return document.cookie.split(';').some(c => c.trim().startsWith('sb-access-token=')
                                            || c.trim().startsWith('sb-refresh-token='));
  }

  async function loadProfile() {
    const r = await fetch('/api/profile', { credentials: 'include' });
    if (!r.ok) return null;
    return await r.json();
  }

  async function patchProfile(avatar_url) {
    const r = await fetch('/api/profile', {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ avatar_url }),
    });
    if (!r.ok) throw new Error('patch failed: ' + r.status);
    return await r.json();
  }

  function renderUnauth() {
    document.getElementById('profile-unauth').hidden = false;
    document.getElementById('profile-auth').hidden = true;
    // The shared #oauth-modal is already in the DOM from _render_with_mobile_shell;
    // clone its inner buttons into the inline slot.
    const modal = document.getElementById('m-oauth-modal');
    const slot = document.getElementById('profile-oauth-inline');
    if (modal && slot) {
      const buttons = modal.querySelectorAll('.m-oauth-btn, .m-oauth-more');
      buttons.forEach(b => slot.appendChild(b.cloneNode(true)));
      slot.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-provider]');
        if (btn && window.zkAuthLogin) window.zkAuthLogin(btn.dataset.provider);
      });
    }
  }

  function renderAuth(profile) {
    document.getElementById('profile-unauth').hidden = true;
    document.getElementById('profile-auth').hidden = false;
    document.getElementById('profile-email').textContent = profile.email || '';

    const avatarSlot = document.getElementById('profile-avatar');
    avatarSlot.innerHTML =
      `<img src="${profile.avatar_url}" width="72" height="72" alt="" class="zk-avatar-img">`;

    renderPicker(profile.avatar_url);
  }

  function renderPicker(currentUrl) {
    const picker = document.getElementById('avatar-picker');
    const urls = window.ZK.avatarUrls();
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          const img = e.target.querySelector('img');
          if (img && !img.src) img.src = img.dataset.src;
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: '80px' });
    urls.forEach(url => {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'm-avatar-cell' + (url === currentUrl ? ' is-selected' : '');
      cell.dataset.url = url;
      cell.innerHTML = `<img data-src="${url}" width="56" height="56" alt="">`;
      cell.addEventListener('click', () => selectAvatar(url, cell));
      picker.appendChild(cell);
      io.observe(cell);
    });
  }

  async function selectAvatar(url, cellEl) {
    const prev = document.querySelector('.m-avatar-cell.is-selected');
    if (prev) prev.classList.remove('is-selected');
    cellEl.classList.add('is-selected');
    const avatarSlot = document.getElementById('profile-avatar');
    avatarSlot.innerHTML = `<img src="${url}" width="72" height="72" alt="" class="zk-avatar-img">`;
    try {
      await patchProfile(url);
      // Broadcast so header avatar updates without reload
      document.dispatchEvent(new CustomEvent('zk:avatar-changed', { detail: { url } }));
    } catch (err) {
      console.error(err);
      if (prev) prev.classList.add('is-selected');
      cellEl.classList.remove('is-selected');
      alert('Could not save avatar.');
    }
  }

  async function signOut() {
    if (window.zkAuthSignOut) {
      await window.zkAuthSignOut();
      location.assign('/m/profile');
    }
  }

  async function init() {
    if (!hasSession()) { renderUnauth(); return; }
    const p = await loadProfile();
    if (!p) { renderUnauth(); return; }
    renderAuth(p);
    document.getElementById('profile-signout').addEventListener('click', signOut);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

- [ ] **Step 11.3: Style the page**

Create `website/mobile/css/pages/profile.css`:

```css
/* profile.css — mobile profile page (auth + unauth). */

.m-profile-page {
  padding: 16px 16px calc(var(--m-bottomnav-h, 64px) + 24px);
}

.m-profile-title { color: #e6e6e6; font-size: 22px; margin: 16px 0 4px; }
.m-profile-sub  { color: rgba(255,255,255,0.6); margin: 0 0 16px; }

.m-profile-oauth { display: flex; flex-direction: column; gap: 8px; }

.m-profile-card {
  display: flex; align-items: center; gap: 14px;
  background: #11131c;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 14px;
}
.m-profile-meta { display: flex; flex-direction: column; gap: 6px; }
.m-profile-email { color: #e6e6e6; }
.m-profile-signout {
  align-self: flex-start;
  padding: 6px 12px;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.08);
  color: #e6e6e6;
  border-radius: 8px;
  font-size: 13px;
}
.m-profile-section-title { color: rgba(255,255,255,0.7); font-size: 14px; margin: 20px 0 10px; text-transform: uppercase; letter-spacing: 0.06em; }
```

Create `website/mobile/css/components/avatar-picker.css`:

```css
/* avatar-picker.css — 4-col grid of 60 avatars on /m/profile. */

.m-avatar-picker {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.m-avatar-cell {
  background: transparent;
  border: 2px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 4px;
  display: inline-flex; align-items: center; justify-content: center;
}
.m-avatar-cell img {
  width: 100%; height: auto; border-radius: 50%; display: block;
}
.m-avatar-cell.is-selected { border-color: #14b8a6; box-shadow: 0 0 0 2px rgba(20,184,166,0.18); }
```

- [ ] **Step 11.4: Import both new CSS files**

In `website/mobile/css/mobile.css`:

```css
@import url("./components/avatar-picker.css");
@import url("./pages/profile.css");
```

- [ ] **Step 11.5: Update the header-avatar broadcast listener in `auth-modal.js`**

In `website/mobile/js/auth-modal.js`, near the bottom add:

```javascript
document.addEventListener('zk:avatar-changed', refreshHeaderAvatar);
```

- [ ] **Step 11.6: Manual verification**

- [ ] Logged out: `/m/profile` shows "Sign in to Zettelkasten" + OAuth buttons.
- [ ] After login: page shows email + sign-out + 4-col picker grid; the user's current avatar has a teal ring.
- [ ] Tap a different avatar → teal ring jumps, large avatar swaps, header avatar updates (no reload), PATCH /api/profile returns 200.
- [ ] Network-disconnect simulation: tap an avatar → reverts + alert.

- [ ] **Step 11.7: Commit**

```
git add website/mobile/profile.html website/mobile/js/profile.js website/mobile/js/auth-modal.js website/mobile/css/pages/profile.css website/mobile/css/components/avatar-picker.css website/mobile/css/mobile.css
git commit -m "feat(mobile): profile page + avatar picker (#96)"
```

---

## Task 12: PWA install — banner + iOS sheet + header icon

**Files:**
- Create: `website/mobile/js/install-prompt.js`
- Create: `website/mobile/css/components/install-banner.css`
- Modify: `website/mobile/index.html` (banner placeholder)
- Modify: `website/mobile/templates/_shell.html` (script tag)
- Modify: `website/mobile/css/mobile.css` (`@import`)

**This is a pure-JS state machine; uses a manual verification playbook.**

- [ ] **Step 12.1: Add the banner placeholder to the capture page**

In `website/mobile/index.html`, just above `<section class="m-hero">` add:

```html
<div class="m-install-banner" id="install-banner" hidden>
  <div class="m-install-banner-body">
    <span class="m-install-banner-icon" aria-hidden="true">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><rect x="4" y="17" width="16" height="4" rx="1"/></svg>
    </span>
    <div class="m-install-banner-text">
      <div class="m-install-banner-title">Install Zettelkasten</div>
      <div class="m-install-banner-sub" id="install-banner-sub">Add to your home screen for faster access.</div>
    </div>
    <button type="button" class="m-install-banner-cta" id="install-banner-cta">Install</button>
    <button type="button" class="m-install-banner-close" id="install-banner-close" aria-label="Dismiss">×</button>
  </div>
</div>

<div class="m-ios-install-sheet" id="ios-install-sheet" hidden>
  <div class="m-ios-install-sheet-card">
    <h3>Install on iOS</h3>
    <ol>
      <li>Tap the Share icon <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg> below.</li>
      <li>Choose <strong>Add to Home Screen</strong>.</li>
      <li>Tap <strong>Add</strong>.</li>
    </ol>
    <button type="button" class="m-btn" id="ios-install-close">Got it</button>
  </div>
</div>
```

- [ ] **Step 12.2: Write the install state machine**

Create `website/mobile/js/install-prompt.js`:

```javascript
// install-prompt.js — PWA install banner + header icon + iOS instructional sheet.
// Persists dismissal in localStorage for 30 days.

(function () {
  "use strict";

  const DISMISS_KEY  = 'pwa_install_dismissed_at';
  const DISMISS_DAYS = 30;
  const DAY_MS = 86400000;

  let deferredPrompt = null;
  let isIOS = false;
  let isInstalled = false;

  function detectInstalled() {
    return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
      || ('standalone' in window.navigator && window.navigator.standalone === true);
  }

  function detectIOS() {
    const ua = navigator.userAgent || '';
    return /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  }

  function recentlyDismissed() {
    const v = localStorage.getItem(DISMISS_KEY);
    if (!v) return false;
    const at = Number(v);
    if (!Number.isFinite(at)) return false;
    return (Date.now() - at) < DISMISS_DAYS * DAY_MS;
  }

  function rememberDismissal() {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
  }

  function showBanner() {
    const banner = document.getElementById('install-banner');
    if (!banner) return;
    if (isIOS) {
      document.getElementById('install-banner-sub').textContent = 'Tap Install for setup steps.';
    }
    banner.hidden = false;
  }
  function hideBanner() {
    const banner = document.getElementById('install-banner');
    if (banner) banner.hidden = true;
  }
  function showHeaderIcon() {
    const btn = document.getElementById('m-install-btn');
    if (btn) btn.hidden = false;
  }
  function hideHeaderIcon() {
    const btn = document.getElementById('m-install-btn');
    if (btn) btn.hidden = true;
  }
  function showIOSSheet() {
    const sheet = document.getElementById('ios-install-sheet');
    if (sheet) sheet.hidden = false;
  }
  function hideIOSSheet() {
    const sheet = document.getElementById('ios-install-sheet');
    if (sheet) sheet.hidden = true;
  }

  async function triggerInstall() {
    if (isIOS) { showIOSSheet(); return; }
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const result = await deferredPrompt.userChoice;
      console.log('[pwa] userChoice:', result.outcome);
      deferredPrompt = null;
      hideBanner();
      hideHeaderIcon();
      if (result.outcome === 'dismissed') rememberDismissal();
    }
  }

  function init() {
    isInstalled = detectInstalled();
    isIOS = detectIOS();

    if (isInstalled) { hideBanner(); hideHeaderIcon(); return; }

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      if (!recentlyDismissed()) showBanner(); else showHeaderIcon();
    });

    window.addEventListener('appinstalled', () => {
      isInstalled = true;
      hideBanner();
      hideHeaderIcon();
    });

    // iOS path — no beforeinstallprompt; show banner unless already standalone or recently dismissed.
    if (isIOS && !recentlyDismissed()) showBanner();
    if (isIOS && recentlyDismissed()) showHeaderIcon();

    const cta   = document.getElementById('install-banner-cta');
    const close = document.getElementById('install-banner-close');
    const head  = document.getElementById('m-install-btn');
    const iosClose = document.getElementById('ios-install-close');
    if (cta)   cta.addEventListener('click', triggerInstall);
    if (close) close.addEventListener('click', () => { rememberDismissal(); hideBanner(); showHeaderIcon(); });
    if (head)  head.addEventListener('click', triggerInstall);
    if (iosClose) iosClose.addEventListener('click', hideIOSSheet);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

- [ ] **Step 12.3: Style the banner + iOS sheet**

Create `website/mobile/css/components/install-banner.css`:

```css
/* install-banner.css — banner + header icon + iOS sheet styling. */

.m-install-banner {
  margin: 12px 16px;
  padding: 10px 12px;
  background: rgba(20,184,166,0.12);
  border: 1px solid rgba(20,184,166,0.28);
  border-radius: 12px;
}
.m-install-banner-body {
  display: flex; align-items: center; gap: 10px;
}
.m-install-banner-icon {
  color: #14b8a6;
  display: inline-flex; align-items: center; justify-content: center;
}
.m-install-banner-text { flex: 1; min-width: 0; }
.m-install-banner-title { color: #e6e6e6; font-weight: 600; font-size: 14px; }
.m-install-banner-sub   { color: rgba(255,255,255,0.7); font-size: 12px; }
.m-install-banner-cta   {
  background: #14b8a6; color: #0a0b14;
  border: 0; border-radius: 8px;
  padding: 6px 14px; font-weight: 600;
}
.m-install-banner-close {
  width: 28px; height: 28px;
  background: transparent; border: 0; color: rgba(255,255,255,0.7);
  font-size: 20px; line-height: 1;
}

.m-ios-install-sheet {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.55);
  z-index: 70;
  display: flex; align-items: flex-end; justify-content: center;
}
.m-ios-install-sheet-card {
  width: 100%; max-width: 480px;
  background: #11131c;
  border-top-left-radius: 18px;
  border-top-right-radius: 18px;
  padding: 18px 18px calc(env(safe-area-inset-bottom, 0px) + 18px);
}
.m-ios-install-sheet-card ol { padding-left: 22px; color: rgba(255,255,255,0.85); }
.m-ios-install-sheet-card li { margin: 8px 0; line-height: 1.4; }
```

- [ ] **Step 12.4: Import + script**

In `website/mobile/css/mobile.css`:

```css
@import url("./components/install-banner.css");
```

In `website/mobile/templates/_shell.html`, add before `</body>`:

```html
<script src="/m/js/install-prompt.js?v=20260525a"></script>
```

- [ ] **Step 12.5: Manual verification playbook**

Chrome desktop with iPhone emulation (or real device).

A. **Already installed path**:
- Set DevTools → Application → Manifest → "Add to homescreen" (simulates).
- Open `/m/`. Banner + header icon hidden.

B. **Android Chrome path**:
- Use Chrome desktop; DevTools console:
  ```
  localStorage.removeItem('pwa_install_dismissed_at');
  ```
- Open `/m/`. Banner visible.
- Tap "Install" → Chrome prompts; choose Cancel → banner hides, header icon appears, dismissal timestamp written.
- Reload: header icon visible, banner hidden.
- Console: `localStorage.removeItem('pwa_install_dismissed_at')` → reload → banner returns.

C. **iOS path**:
- Use Safari iOS or `navigator.userAgent` override to iPhone Safari.
- Open `/m/`. Banner visible with "Tap Install for setup steps."
- Tap Install → iOS instructional sheet appears with 3 numbered steps.
- Tap "Got it" → sheet closes.

D. **localStorage 30-day suppression**:
- Set `localStorage.pwa_install_dismissed_at = (Date.now() - 29 * 86400000).toString()` → reload → header icon only.
- Set to `Date.now() - 31 * 86400000` → reload → banner returns.

- [ ] **Step 12.6: Commit**

```
git add website/mobile/js/install-prompt.js website/mobile/css/components/install-banner.css website/mobile/index.html website/mobile/templates/_shell.html website/mobile/css/mobile.css
git commit -m "feat(pwa): install banner + ios sheet + header icon (#96)"
```

---

## Task 13: Mobile footer

**Files:**
- Create: `website/mobile/css/components/footer.css`
- Modify: `website/mobile/templates/_shell.html` (footer inclusion)
- Modify: `website/mobile/css/mobile.css` (`@import`)

- [ ] **Step 13.1: Insert the footer markup**

In `website/mobile/templates/_shell.html`, add just before the bottom-nav `<nav class="m-bottom-tabs">` block:

```html
<footer class="m-footer" role="contentinfo">
  <a class="m-footer-icon" href="https://github.com/chintanmehta21/Zettelkasten_KG" target="_blank" rel="noopener" aria-label="GitHub">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.57.1.78-.25.78-.55v-2.16c-3.2.7-3.88-1.36-3.88-1.36-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.68 1.25 3.34.96.1-.74.4-1.25.72-1.54-2.55-.29-5.23-1.27-5.23-5.66 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.45.11-3.02 0 0 .97-.31 3.18 1.17a11.04 11.04 0 0 1 5.79 0c2.21-1.48 3.17-1.17 3.17-1.17.63 1.57.24 2.73.12 3.02.74.8 1.18 1.82 1.18 3.07 0 4.4-2.69 5.36-5.25 5.64.41.36.78 1.06.78 2.13v3.16c0 .31.21.66.79.55C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z"/></svg>
  </a>
  <a class="m-footer-icon" href="/about" aria-label="About">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
  </a>
  <a class="m-footer-icon" href="/pricing" aria-label="Pricing">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polygon points="6 3 18 3 22 9 12 21 2 9"/></svg>
  </a>
  <a class="m-footer-icon" href="https://buymeacoffee.com/zettelkasten" target="_blank" rel="noopener" aria-label="Buy me a coffee">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>
  </a>
</footer>
```

- [ ] **Step 13.2: Style it**

Create `website/mobile/css/components/footer.css`:

```css
/* footer.css — mobile footer with mini icons. */

.m-footer {
  display: flex; justify-content: center; gap: 18px;
  padding: 20px 0;
  margin-bottom: calc(var(--m-bottomnav-h, 64px) + env(safe-area-inset-bottom, 0px) + 12px);
}
.m-footer-icon {
  width: 36px; height: 36px;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%;
  color: rgba(255,255,255,0.55);
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
}
.m-footer-icon:hover { color: #14b8a6; background: rgba(20,184,166,0.1); }
```

- [ ] **Step 13.3: Import the CSS**

In `website/mobile/css/mobile.css`:

```css
@import url("./components/footer.css");
```

- [ ] **Step 13.4: Manual verification**

Open `/m/`, `/m/zettels`, `/m/kastens`, `/m/profile`, `/m/knowledge-graph`.
- [ ] Footer shows 4 icons centered above bottom nav, with a comfortable gap.
- [ ] Last bit of scroll content not covered by the bottom nav.

- [ ] **Step 13.5: Commit**

```
git add website/mobile/templates/_shell.html website/mobile/css/components/footer.css website/mobile/css/mobile.css
git commit -m "feat(mobile): footer with mini icons (#96)"
```

---

## Task 14: Manual screenshot pass + acceptance

- [ ] **Step 14.1: Restart dev server cleanly**

```
# Kill any running uvicorn first
ENV=dev SERVER_PORT=10000 python run.py > /tmp/zk-dev.log 2>&1 &
```

- [ ] **Step 14.2: Open Chrome → DevTools → iPhone 14 Pro emulation. Capture each:**

| # | Route | State | Screenshot file |
|---|---|---|---|
| 1 | `/m/` | logged out | `01_capture_anon.png` |
| 2 | `/m/` | logged in | `02_capture_auth.png` |
| 3 | `/m/` | install banner visible | `03_capture_install_banner.png` |
| 4 | `/m/` | banner dismissed → header icon | `04_capture_header_icon.png` |
| 5 | `/m/` | iOS install sheet open | `05_capture_ios_sheet.png` |
| 6 | `/m/` | source-picker sheet open | `06_capture_source_sheet.png` |
| 7 | `/m/zettels` | logged in with N zettels | `07_zettels_auth.png` |
| 8 | `/m/zettels` | logged in detail modal open | `08_zettels_detail.png` |
| 9 | `/m/zettels?just_captured=…` | anon | `09_zettels_anon.png` |
| 10 | `/m/kastens` | logged in | `10_kastens_auth.png` |
| 11 | `/m/profile` | logged out | `11_profile_unauth.png` |
| 12 | `/m/profile` | logged in (picker visible) | `12_profile_auth.png` |
| 13 | `/m/knowledge-graph` | any | `13_kg_glass.png` |
| 14 | Desktop `/` | logged in (avatar SVG, no Google photo) | `14_desktop_avatar.png` |

- [ ] **Step 14.3: Compare each screenshot against the spec acceptance criteria in §11**

For each: write PASS or FAIL with a one-line note in PR comment.

- [ ] **Step 14.4: Run the full test suite**

```
pytest --maxfail=5 -v
```

Expected: all green; any unrelated flakes documented per `feedback_iter12_handoff` discipline.

- [ ] **Step 14.5: Lighthouse PWA score**

DevTools → Lighthouse → run "Progressive Web App" audit on `http://localhost:10000/m/`.

Expected: PWA score ≥ 90.

- [ ] **Step 14.6: Commit the screenshots (under `docs/screenshots/iter-2a/`)**

```
mkdir -p docs/screenshots/iter-2a
# move PNG files in
git add docs/screenshots/iter-2a/
git commit -m "docs: iter-2a manual screenshot pass (#96)"
```

---

## Task 15: Batched lint pass + final polish

- [ ] **Step 15.1: Run ruff on everything we touched**

```
ruff check website/features/user_profile/ tests/unit/website/test_avatar_url_validation.py tests/unit/website/test_profile_routes.py tests/unit/website/test_mobile_routes.py tests/integration/v2/test_avatar_assignment.py website/app.py
```

- [ ] **Step 15.2: Fix anything ruff reports**

Common: long-line, unused imports. Apply fixes inline; do NOT use `# noqa` unless the rule conflicts with the spec.

- [ ] **Step 15.3: Re-run ruff — expect clean**

```
ruff check website/features/user_profile/ tests/ website/app.py
```

- [ ] **Step 15.4: Format**

```
ruff format website/features/user_profile/ tests/unit/website/ tests/integration/v2/test_avatar_assignment.py
```

- [ ] **Step 15.5: Run full pytest one last time**

```
pytest --maxfail=5 -q
```

- [ ] **Step 15.6: Commit lint pass**

```
git add -A
git commit -m "chore: batched ruff format + lint fix (#96)"
```

- [ ] **Step 15.7: Push & flag PR ready for review**

```
git push
gh pr ready 96 2>/dev/null || true   # noop if already not-draft
gh pr edit 96 --body "$(cat docs/superpowers/specs/2026-05-25-mobile-ui-fixes-2a-design.md | head -60)"
```

---

## Sequencing notes

- Tasks 1, 2, 6, 7 are **independent** of each other; Tasks 3-5, 8-13 chain on top.
- DB migration (Task 1) **must** apply on staging before Task 2 lands on the dev server, so the trigger fires when the test fixture mints users.
- Tasks 9 and 10 each depend only on Tasks 3 + 6 having landed.
- Task 12 (PWA install) depends on Task 5 (header slot exists).
- Task 14 acceptance pass is final; do not skip even if tests are green — visual regressions are not test-detectable here.

## Out-of-scope reminders

If during execution you discover that a task expands the scope (e.g., the desktop avatar swap turns out to touch a third file), **STOP** and surface to the operator per `feedback_anything_beyond_plan_needs_approval`. Do not silently expand.
