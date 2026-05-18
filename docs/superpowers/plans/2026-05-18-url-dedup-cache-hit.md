# URL Dedup → Cache-Hit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A known URL never re-runs the summarization engine; cross-user adds link the existing canonical (quota charged, user unaware); same-user re-add is a no-op with no charge.

**Architecture:** ONE reusable URL-dedup gate in `website/features/functional_gates/` (mirrors the existing `FunctionalGates` pattern: typed result, singleton, FastAPI-free). Keyed on `normalize_url(resolve_redirects(url))`. Every Add-Zettel surface (`run_add_zettel_pipeline`, and `/api/v2/summarize` by delegating to that runner) calls the one gate — no per-route duplication, a change propagates everywhere. Schema moves to `UNIQUE(content.canonical_zettels.normalized_url)`. Pricing untouched — existing `require_entitlement` called only on fresh + cross-user branches.

**Tech Stack:** Python 3.12, FastAPI, Supabase v2 (Postgres, psycopg/RPC), pytest.

**Spec:** `docs/superpowers/specs/2026-05-18-url-dedup-cache-hit-design.md` (commit 92b5492). Branch `codex/exec-summarization-pipeline-final-fix` (PR #25).

**Worktree (run all commands here):** `C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.worktrees/exec-summarization-pipeline-final-fix`

---

## File Structure

- Modify `supabase/website/_v2/17_content_rpcs.sql` — RPC conflict target → `(normalized_url)`.
- Create `supabase/website/_v2/45_url_dedup.sql` — collapse dup canonicals, swap UNIQUE constraint.
- Modify `website/core/supabase_v2/repositories/content_repository.py` — add `find_canonical_by_url`, `link_existing_canonical`.
- Create `website/features/functional_gates/dedup_gate.py` — the ONE reusable URL-dedup gate (`UrlDedupGate` + `get_url_dedup_gate()` singleton).
- Modify `website/features/functional_gates/models.py` — add `DedupDecision`.
- Modify `website/features/functional_gates/__init__.py` — export gate + unify `reset_for_tests`.
- Modify `website/api/module_runners/summarization.py` — call the gate; act per branch.
- Modify `website/features/summarization_engine/api/routes.py` — delegate `/api/v2/summarize` to `run_add_zettel_pipeline` (same gate, zero duplication).
- Create `tests/unit/summarization_engine/test_dedup_gate.py` — gate + pipeline branch tests.
- Modify `tests/unit/website/test_url_utils.py` — P2 normalize_url cases.
- Create `tests/unit/ops_scripts/test_url_dedup_migration.py` — migration collapse SQL logic test (pure-Python harness against the dedup-collapse query shape).

---

## Task 1: Schema migration — collapse dup canonicals + swap UNIQUE

**Files:**
- Create: `supabase/website/_v2/45_url_dedup.sql`
- Modify: `supabase/website/_v2/17_content_rpcs.sql:29`
- Test: `tests/unit/ops_scripts/test_url_dedup_migration.py`

- [ ] **Step 1: Write the failing test** (asserts the migration file exists, is idempotent-guarded, collapses by newest, and ends with the new constraint)

Create `tests/unit/ops_scripts/test_url_dedup_migration.py`:

```python
from pathlib import Path

MIG = Path("supabase/website/_v2/45_url_dedup.sql")


def test_migration_exists_and_is_well_formed():
    sql = MIG.read_text(encoding="utf-8")
    # Collapse keeps the newest canonical per duplicated normalized_url.
    assert "ORDER BY created_at DESC" in sql
    # Children re-pointed before the loser is deleted.
    assert "UPDATE content.workspace_zettels" in sql
    assert "UPDATE content.canonical_chunks" in sql
    assert "DELETE FROM content.canonical_zettels" in sql
    # Old composite constraint dropped, URL-only constraint added.
    assert "content_hash" in sql  # referenced in the DROP of the old key
    assert "ADD CONSTRAINT canonical_zettels_normalized_url_key UNIQUE (normalized_url)" in sql
    # Idempotent guards.
    assert "IF EXISTS" in sql and "IF NOT EXISTS" in sql


def test_rpc_conflict_target_is_url_only():
    rpc = Path("supabase/website/_v2/17_content_rpcs.sql").read_text(encoding="utf-8")
    assert "ON CONFLICT (normalized_url)\n" in rpc
    assert "ON CONFLICT (normalized_url, content_hash)" not in rpc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/ops_scripts/test_url_dedup_migration.py -v`
Expected: FAIL (file `45_url_dedup.sql` does not exist).

- [ ] **Step 3: Create the migration**

Create `supabase/website/_v2/45_url_dedup.sql`:

```sql
-- 45_url_dedup.sql — URL-identity dedup.
-- Collapse duplicate canonicals (keep newest per normalized_url), re-point
-- children, then make normalized_url the sole uniqueness key.
-- Idempotent: safe to re-apply.

BEGIN;

-- 1. For each normalized_url with >1 canonical, keep the newest; re-point
--    workspace_zettels + canonical_chunks at the keeper; delete the losers.
WITH ranked AS (
    SELECT id, normalized_url,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn,
           first_value(id) OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS keeper_id
    FROM content.canonical_zettels
),
losers AS (
    SELECT id AS loser_id, keeper_id FROM ranked WHERE rn > 1
)
UPDATE content.workspace_zettels wz
SET canonical_zettel_id = l.keeper_id
FROM losers l
WHERE wz.canonical_zettel_id = l.loser_id
  AND NOT EXISTS (  -- avoid violating UNIQUE(workspace_id, canonical_zettel_id)
      SELECT 1 FROM content.workspace_zettels x
      WHERE x.workspace_id = wz.workspace_id AND x.canonical_zettel_id = l.keeper_id
  );

WITH ranked AS (
    SELECT id, normalized_url,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn,
           first_value(id) OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS keeper_id
    FROM content.canonical_zettels
),
losers AS (
    SELECT id AS loser_id, keeper_id FROM ranked WHERE rn > 1
)
UPDATE content.canonical_chunks cc
SET canonical_zettel_id = l.keeper_id
FROM losers l
WHERE cc.canonical_zettel_id = l.loser_id
  AND NOT EXISTS (
      SELECT 1 FROM content.canonical_chunks x
      WHERE x.canonical_zettel_id = l.keeper_id AND x.chunk_idx = cc.chunk_idx
  );

-- Drop any workspace_zettels / chunks still pointing at a loser (true dup rows
-- where the keeper link already existed) so the canonical delete is unblocked.
WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn
    FROM content.canonical_zettels
),
losers AS (SELECT id FROM ranked WHERE rn > 1)
DELETE FROM content.workspace_zettels wz USING losers l WHERE wz.canonical_zettel_id = l.id;

WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn
    FROM content.canonical_zettels
),
losers AS (SELECT id FROM ranked WHERE rn > 1)
DELETE FROM content.canonical_chunks cc USING losers l WHERE cc.canonical_zettel_id = l.id;

WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY normalized_url ORDER BY created_at DESC) AS rn
    FROM content.canonical_zettels
)
DELETE FROM content.canonical_zettels c USING ranked r
WHERE c.id = r.id AND r.rn > 1;

-- 2. Swap the uniqueness key: drop the old composite, add URL-only.
ALTER TABLE content.canonical_zettels
    DROP CONSTRAINT IF EXISTS canonical_zettels_normalized_url_content_hash_key;
ALTER TABLE content.canonical_zettels
    ADD CONSTRAINT canonical_zettels_normalized_url_key UNIQUE (normalized_url);

COMMIT;

NOTIFY pgrst, 'reload schema';
```

> The old constraint auto-name from `UNIQUE (normalized_url, content_hash)` in
> `02_content_schema.sql` is `canonical_zettels_normalized_url_content_hash_key`
> (Postgres default). `DROP CONSTRAINT IF EXISTS` makes it safe if it differs.

- [ ] **Step 4: Update the RPC conflict target**

In `supabase/website/_v2/17_content_rpcs.sql`, change line 29 from:

```sql
        ON CONFLICT (normalized_url, content_hash)
```
to:
```sql
        ON CONFLICT (normalized_url)
```

(Leave the `DO UPDATE SET normalized_url = EXCLUDED.normalized_url` and `(xmax = 0)` was-new logic unchanged.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/ops_scripts/test_url_dedup_migration.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add supabase/website/_v2/45_url_dedup.sql supabase/website/_v2/17_content_rpcs.sql tests/unit/ops_scripts/test_url_dedup_migration.py
git commit -m "feat: url-identity dedup schema migration"
```

> **Production apply is operator-gated** (migration-CI + manual apply per migration-discipline). Do NOT apply to prod in this plan.

---

## Task 2: Repository — find_canonical_by_url

**Files:**
- Modify: `website/core/supabase_v2/repositories/content_repository.py`
- Test: `tests/unit/summarization_engine/test_dedup_gate.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/summarization_engine/test_dedup_gate.py`:

```python
from uuid import uuid4

from website.core.supabase_v2.repositories.content_repository import ContentRepository


class _FakeQuery:
    def __init__(self, rows): self._rows = rows
    def schema(self, *_a, **_k): return self
    def table(self, *_a, **_k): return self
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def is_(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def execute(self):
        class R: pass
        r = R(); r.data = self._rows; return r


def test_find_canonical_by_url_returns_none_when_absent():
    repo = ContentRepository(client=_FakeQuery([]))
    assert repo.find_canonical_by_url("https://example.com/x") is None


def test_find_canonical_by_url_returns_canonical_and_summary():
    cid = str(uuid4())
    repo = ContentRepository(client=_FakeQuery([
        {"id": cid, "source_type": "web", "title": "T",
         "ai_summary": '{"brief_summary":"b","detailed_summary":"d"}',
         "ai_summary_engine_version": "", "user_tags": ["t1"]},
    ]))
    found = repo.find_canonical_by_url("https://example.com/x")
    assert found is not None
    assert str(found.canonical_zettel_id) == cid
    assert found.ai_summary == '{"brief_summary":"b","detailed_summary":"d"}'
    assert found.source_type == "web"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/summarization_engine/test_dedup_gate.py -v`
Expected: FAIL (`ContentRepository` has no `find_canonical_by_url`; model missing).

- [ ] **Step 3: Add the model**

In `website/core/supabase_v2/models.py`, after `class CanonicalUpsertResult` (line ~48), add:

```python
class CanonicalLookupResult(BaseModel):
    canonical_zettel_id: UUID
    source_type: str
    title: str | None = None
    ai_summary: str | None = None
    ai_summary_engine_version: str | None = None
    user_tags: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add `find_canonical_by_url`**

In `content_repository.py`, add `CanonicalLookupResult` to the model import block (lines 10-16), then add this method to `ContentRepository` (after `upsert_canonical_zettel`, before `upsert_chunks`):

```python
    def find_canonical_by_url(self, normalized_url: str) -> "CanonicalLookupResult | None":
        """Return the canonical for ``normalized_url`` plus one existing
        ai_summary envelope (any workspace's — engine output is identical),
        or None. Read-only; backed by UNIQUE(normalized_url)."""
        cz = (
            self._client.schema("content")
            .table("canonical_zettels")
            .select("id, source_type, title")
            .eq("normalized_url", normalized_url)
            .limit(1)
            .execute()
        )
        row = _first(cz.data)
        if not row:
            return None
        canonical_id = UUID(str(row["id"]))
        wz = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select("ai_summary, ai_summary_engine_version, user_tags")
            .eq("canonical_zettel_id", str(canonical_id))
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        wrow = _first(wz.data) or {}
        return CanonicalLookupResult(
            canonical_zettel_id=canonical_id,
            source_type=str(row.get("source_type") or "web"),
            title=row.get("title"),
            ai_summary=wrow.get("ai_summary"),
            ai_summary_engine_version=wrow.get("ai_summary_engine_version") or "",
            user_tags=list(wrow.get("user_tags") or []),
        )
```

> `_first` already exists in this module (used by `upsert_canonical_zettel`).

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/summarization_engine/test_dedup_gate.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add website/core/supabase_v2/models.py website/core/supabase_v2/repositories/content_repository.py tests/unit/summarization_engine/test_dedup_gate.py
git commit -m "feat: ContentRepository.find_canonical_by_url"
```

---

## Task 3: Repository — link_existing_canonical + same-user detection

**Files:**
- Modify: `website/core/supabase_v2/repositories/content_repository.py`
- Test: `tests/unit/summarization_engine/test_dedup_gate.py`

- [ ] **Step 1: Write the failing test** (append to `test_dedup_gate.py`)

```python
def test_workspace_already_links_canonical_detects_same_user():
    wid, cid = str(uuid4()), str(uuid4())
    repo = ContentRepository(client=_FakeQuery([{"id": "wz1"}]))
    assert repo.workspace_links_canonical(wid, cid) is True

    repo_absent = ContentRepository(client=_FakeQuery([]))
    assert repo_absent.workspace_links_canonical(wid, cid) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/summarization_engine/test_dedup_gate.py::test_workspace_already_links_canonical_detects_same_user -v`
Expected: FAIL (`workspace_links_canonical` not defined).

- [ ] **Step 3: Add `workspace_links_canonical` + `link_existing_canonical`**

Add to `ContentRepository` (after `find_canonical_by_url`):

```python
    def workspace_links_canonical(self, workspace_id, canonical_zettel_id) -> bool:
        """True if this workspace already has a live row for this canonical
        (the same-user no-op case)."""
        resp = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select("id")
            .eq("workspace_id", str(workspace_id))
            .eq("canonical_zettel_id", str(canonical_zettel_id))
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        return bool(_first(resp.data))

    def link_existing_canonical(self, canonical_zettel_id, workspace) -> UUID:
        """Idempotently attach an existing canonical to a workspace (cross-user
        cache-hit). Reuses upsert_workspace_zettel, which conflicts on
        UNIQUE(workspace_id, canonical_zettel_id) — concurrent/retry safe."""
        return self.upsert_workspace_zettel(canonical_zettel_id, workspace)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/summarization_engine/test_dedup_gate.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add website/core/supabase_v2/repositories/content_repository.py tests/unit/summarization_engine/test_dedup_gate.py
git commit -m "feat: link_existing_canonical + same-user link detection"
```

---

## Task 4: Reusable URL-dedup functional gate (website/features/functional_gates/)

> Per operator: the dedup decision lives in `website/features/functional_gates/`
> as ONE reusable gate (mirrors the existing `FunctionalGates` pattern: typed
> result model, singleton accessor, NO FastAPI/HTTPException imports). Every
> endpoint calls this one gate — no per-route duplication.

**Files:**
- Create: `website/features/functional_gates/dedup_gate.py`
- Modify: `website/features/functional_gates/models.py` (add `DedupDecision`)
- Modify: `website/features/functional_gates/__init__.py` (export)
- Test: `tests/unit/summarization_engine/test_dedup_gate.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/summarization_engine/test_dedup_gate.py`)

```python
from unittest.mock import MagicMock
from uuid import uuid4

from website.features.functional_gates.dedup_gate import get_url_dedup_gate
from website.features.functional_gates import reset_for_tests as _reset_fg


def _repo(found, links):
    r = MagicMock()
    r.find_canonical_by_url.return_value = found
    r.workspace_links_canonical.return_value = links
    return r


def _found():
    return MagicMock(canonical_zettel_id=uuid4(),
                     ai_summary='{"brief_summary":"b","detailed_summary":"d"}',
                     source_type="web", title="T", user_tags=[])


def test_gate_fresh_when_no_canonical():
    _reset_fg()
    d = get_url_dedup_gate().decide(repo=_repo(None, False),
                                    normalized_url="https://x", workspace_id=uuid4())
    assert d.branch == "fresh"
    assert d.found is None


def test_gate_same_user_noop_when_workspace_already_links():
    f = _found()
    d = get_url_dedup_gate().decide(repo=_repo(f, True),
                                    normalized_url="https://x", workspace_id=uuid4())
    assert d.branch == "same_user_noop"
    assert d.found is f


def test_gate_cross_user_hit_when_canonical_exists_unlinked():
    f = _found()
    d = get_url_dedup_gate().decide(repo=_repo(f, False),
                                    normalized_url="https://x", workspace_id=uuid4())
    assert d.branch == "cross_user_hit"
    assert d.found is f


def test_gate_singleton_is_reused():
    assert get_url_dedup_gate() is get_url_dedup_gate()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/summarization_engine/test_dedup_gate.py -k gate -v`
Expected: FAIL (`website.features.functional_gates.dedup_gate` does not exist).

- [ ] **Step 3: Add the `DedupDecision` model**

In `website/features/functional_gates/models.py`, after the `GateSource` line add `DedupBranch`, and after `class QuotaSnapshot` add the dataclass:

```python
DedupBranch = Literal["fresh", "same_user_noop", "cross_user_hit"]
```

```python
@dataclass(frozen=True)
class DedupDecision:
    """URL-dedup gate outcome. ``found`` is the existing canonical lookup
    (None on fresh). The gate decides the branch only — entitlement + engine
    are the caller's responsibility per branch (keeps this module FastAPI-free
    and side-effect-free, matching the FunctionalGates principle)."""
    branch: "DedupBranch"
    found: object | None = None
```

(Confirm `Literal` and `dataclass`/`field` are already imported at the top of `models.py`; they are — used by existing models. Do not duplicate imports.)

- [ ] **Step 4: Create the gate**

Create `website/features/functional_gates/dedup_gate.py`:

```python
"""URL-dedup functional gate — the ONE place that decides whether an
Add-Zettel request is a fresh ingest, a same-user no-op, or a cross-user
cache-hit. Reused by every endpoint (website Add Zettel + /api/v2/summarize)
so a change here reflects everywhere. Intentionally free of FastAPI /
engine / entitlement imports: it returns a decision; callers act on it.
"""
from __future__ import annotations

import logging

from website.features.functional_gates.models import DedupDecision

logger = logging.getLogger("website.features.functional_gates.dedup")


class UrlDedupGate:
    """Stateless. ``decide`` does two indexed reads via the provided repo
    (which must expose ``find_canonical_by_url`` and
    ``workspace_links_canonical``) and classifies the request."""

    def decide(self, *, repo, normalized_url: str, workspace_id) -> DedupDecision:
        found = repo.find_canonical_by_url(normalized_url)
        if found is None:
            logger.info("add_zettel dedup branch=fresh")
            return DedupDecision(branch="fresh", found=None)
        if repo.workspace_links_canonical(workspace_id, found.canonical_zettel_id):
            logger.info(
                "add_zettel dedup branch=same_user_noop source_type=%s",
                getattr(found, "source_type", "?"),
            )
            return DedupDecision(branch="same_user_noop", found=found)
        logger.info(
            "add_zettel dedup branch=cross_user_cache_hit source_type=%s",
            getattr(found, "source_type", "?"),
        )
        return DedupDecision(branch="cross_user_hit", found=found)


_singleton: UrlDedupGate | None = None


def get_url_dedup_gate() -> UrlDedupGate:
    """Process-wide singleton (mirrors get_functional_gates())."""
    global _singleton
    if _singleton is None:
        _singleton = UrlDedupGate()
    return _singleton


def _reset_url_dedup_gate_for_tests() -> None:
    global _singleton
    _singleton = None
```

- [ ] **Step 5: Export from the package**

In `website/features/functional_gates/__init__.py`: add to the imports and `__all__` the names `DedupDecision`, `UrlDedupGate`, `get_url_dedup_gate`. Extend the existing `reset_for_tests` so it ALSO resets the dedup-gate singleton (so one reset clears all gate singletons):

```python
from website.features.functional_gates.dedup_gate import (
    DedupDecision,
    UrlDedupGate,
    get_url_dedup_gate,
    _reset_url_dedup_gate_for_tests,
)
```

and inside the existing `reset_for_tests` body (re-exported from `gates.py`): the package `__init__` should define a wrapper that calls both. Concretely, replace the `reset_for_tests` re-export with:

```python
from website.features.functional_gates.gates import reset_for_tests as _reset_gates

def reset_for_tests() -> None:
    _reset_gates()
    _reset_url_dedup_gate_for_tests()
```

Add `DedupDecision`, `UrlDedupGate`, `get_url_dedup_gate` to `__all__`.

- [ ] **Step 6: Run tests + ruff**

Run: `python -m pytest tests/unit/summarization_engine/test_dedup_gate.py -v`
Expected: all pass (Task 2/3 repo tests + the 4 new gate tests).
Run: `python -m ruff check website tests`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add website/features/functional_gates/dedup_gate.py website/features/functional_gates/models.py website/features/functional_gates/__init__.py tests/unit/summarization_engine/test_dedup_gate.py
git commit -m "feat: reusable url-dedup functional gate"
```

---

## Task 5: Wire BOTH endpoints to the one gate (no duplication)

> `run_add_zettel_pipeline` is the shared runner for the website Add-Zettel
> surfaces; `/api/v2/summarize` must delegate to it (or the same gate) so the
> branch logic exists exactly once.

**Files:**
- Modify: `website/api/module_runners/summarization.py:119-165`
- Modify: `website/features/summarization_engine/api/routes.py` (`summarize_v2`)
- Test: `tests/unit/summarization_engine/test_dedup_gate.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
import pytest
from unittest.mock import AsyncMock, patch
from website.api.module_runners import summarization as S


def _stub_bundle():
    from types import SimpleNamespace
    md = SimpleNamespace(model_dump=lambda **k: {}, engine_version="2.0.0")
    res = SimpleNamespace(metadata=md, brief_summary="b", detailed_summary=[],
                          model_dump=lambda **k: {})
    return SimpleNamespace(summary_result=res, ingest_result=SimpleNamespace(metadata={}))


def _scope(found, links):
    r = MagicMock()
    r.find_canonical_by_url.return_value = found
    r.workspace_links_canonical.return_value = links
    r.link_existing_canonical.return_value = uuid4()
    return (r, uuid4(), uuid4())  # (content_repo, profile_id, workspace_id)


@pytest.mark.asyncio
async def test_pipeline_fresh_charges_once_runs_engine():
    with patch("website.core.persist.get_supabase_v2_scope", return_value=_scope(None, False)), \
         patch.object(S, "require_entitlement", new=AsyncMock()) as ent, \
         patch.object(S, "resolve_redirects", new=AsyncMock(return_value="https://r/x")), \
         patch.object(S, "summarize_url_bundle", new=AsyncMock(return_value=_stub_bundle())) as eng, \
         patch.object(S, "persist_summarized_result", new=AsyncMock()):
        await S.run_add_zettel_pipeline(url="https://x", client_action_id="a",
            persist=True, user={"sub": str(uuid4())}, effective_user_id=uuid4())
    assert ent.await_count == 1 and eng.await_count == 1


@pytest.mark.asyncio
async def test_pipeline_same_user_noop_no_charge_no_engine():
    f = _found()
    with patch("website.core.persist.get_supabase_v2_scope", return_value=_scope(f, True)), \
         patch.object(S, "require_entitlement", new=AsyncMock()) as ent, \
         patch.object(S, "resolve_redirects", new=AsyncMock(return_value="https://r/x")), \
         patch.object(S, "summarize_url_bundle", new=AsyncMock()) as eng:
        out = await S.run_add_zettel_pipeline(url="https://x", client_action_id="a",
            persist=True, user={"sub": str(uuid4())}, effective_user_id=uuid4())
    assert ent.await_count == 0 and eng.await_count == 0
    assert out["status"] == "succeeded"


@pytest.mark.asyncio
async def test_pipeline_cross_user_links_charges_once_no_engine():
    f = _found()
    sc = _scope(f, False)
    with patch("website.core.persist.get_supabase_v2_scope", return_value=sc), \
         patch.object(S, "require_entitlement", new=AsyncMock()) as ent, \
         patch.object(S, "resolve_redirects", new=AsyncMock(return_value="https://r/x")), \
         patch.object(S, "summarize_url_bundle", new=AsyncMock()) as eng:
        out = await S.run_add_zettel_pipeline(url="https://x", client_action_id="a",
            persist=True, user={"sub": str(uuid4())}, effective_user_id=uuid4())
    assert ent.await_count == 1 and eng.await_count == 0
    sc[0].link_existing_canonical.assert_called_once()
    assert out["status"] == "succeeded"


def test_v2_summarize_delegates_to_shared_runner_or_gate():
    import website.features.summarization_engine.api.routes as R
    text = open(R.__file__, encoding="utf-8").read()
    assert ("run_add_zettel_pipeline" in text) or ("get_url_dedup_gate" in text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/summarization_engine/test_dedup_gate.py -k "pipeline or v2_summarize" -v`
Expected: FAIL (pipeline not yet wired to the gate).

- [ ] **Step 3: Wire `run_add_zettel_pipeline`**

In `website/api/module_runners/summarization.py`, near the lazy helpers (after `normalize_url`, ~line 117) add:

```python
import logging as _logging

_dedup_log = _logging.getLogger("website.api.add_zettel.dedup")
```

> Reuse the existing `website.core.persist.get_supabase_v2_scope(user_sub)`
> (persist.py:108) → `(content_repo, profile_id, workspace_id)`, resolved
> exactly as the write path. Returns `None` for anonymous/non-UUID subjects →
> gate skipped, FRESH path runs (correct). The returned `content_repo` carries
> `find_canonical_by_url` / `workspace_links_canonical` /
> `link_existing_canonical` from Tasks 2-3.

Replace the body of `run_add_zettel_pipeline` from `user_sub =` through the `persist` block (lines 128-153) with:

```python
    user_sub = str(effective_user_id)
    resolved = await resolve_redirects(url)
    normalized = normalize_url(resolved)

    from website.core.persist import get_supabase_v2_scope
    from website.features.functional_gates import get_url_dedup_gate
    from website.core.supabase_v2.models import WorkspaceZettelCreate

    _scope = get_supabase_v2_scope(user_sub)
    if _scope is not None:
        repo, _profile_id, workspace_id = _scope
        decision = get_url_dedup_gate().decide(
            repo=repo, normalized_url=normalized, workspace_id=workspace_id,
        )
        if decision.branch == "same_user_noop":
            return _cache_hit_output(decision.found, client_action_id, persist)
        if decision.branch == "cross_user_hit":
            await require_entitlement(Meter.ZETTEL, user, action_id=client_action_id)
            repo.link_existing_canonical(
                decision.found.canonical_zettel_id,
                WorkspaceZettelCreate(
                    workspace_id=workspace_id,
                    ai_summary=decision.found.ai_summary,
                    ai_summary_engine_version=decision.found.ai_summary_engine_version,
                    user_tags=decision.found.user_tags,
                    added_via="website",
                ),
            )
            return _cache_hit_output(decision.found, client_action_id, persist)

    # FRESH: charge, then engine, then persist (unchanged behavior).
    await require_entitlement(Meter.ZETTEL, user, action_id=client_action_id)
    async with _SUMMARIZE_SEMAPHORE:
        bundle = await summarize_url_bundle(
            normalized,
            user_id=effective_user_id,
            gemini_client=gemini_client_factory(),
        )

    summary = summary_dto(bundle)
    quality = quality_dto(bundle)
    outcome: PersistenceOutcome | None = None
    if persist:
        outcome = await persist_summarized_result(
            summary.model_dump(mode="json"),
            user_sub=user_sub,
        )

    return AddZettelPipelineOutput(
        status="succeeded",
        operation_id=client_action_id,
        summary=summary,
        persistence=persistence_dto(persist, outcome),
        quality=quality,
        node_id=outcome.file_node_id if outcome else None,
        workspace_zettel_id=outcome.supabase_node_id if outcome else None,
    ).model_dump(mode="json")
```

Add the cache-hit DTO builder module-level (after `quality_dto`):

```python
def _cache_hit_output(found, client_action_id: str, persist: bool) -> dict[str, Any]:
    """Same wire shape as a fresh add, rebuilt from the existing canonical's
    stored summary. No 'cached' indicator (no-infra-disclosure)."""
    from website.core.persist import extract_summary_parts
    brief, detailed = extract_summary_parts(found.ai_summary, None)
    summary = SummaryDTO(
        title=found.title or "",
        summary=detailed or brief,
        brief_summary=brief,
        detailed_summary=detailed or brief,
        tags=list(found.user_tags),
        source_type=found.source_type,
        source_url="",
        one_line_summary=brief,
        tokens_used=0,
        latency_ms=0,
        metadata={},
    )
    return AddZettelPipelineOutput(
        status="succeeded",
        operation_id=client_action_id,
        summary=summary,
        persistence=persistence_dto(persist, None),
        quality=QualityDTO(confidence="succeeded"),
        node_id=None,
        workspace_zettel_id=str(found.canonical_zettel_id),
    ).model_dump(mode="json")
```

> Confirm `SummaryDTO`, `QualityDTO`, `AddZettelPipelineOutput`,
> `persistence_dto`, `Meter`, `PersistenceOutcome` are already imported/defined
> in this module (they are — used by the existing body). `extract_summary_parts`
> is exported from `website/core/persist.py:357`.

- [ ] **Step 4: Route `/api/v2/summarize` through the SAME runner**

In `website/features/summarization_engine/api/routes.py`, in the `summarize_v2` handler (`@router.post("/summarize")`): replace its direct `require_entitlement` + `summarize_url_bundle` URL path with a call to `run_add_zettel_pipeline` imported from `website.api.module_runners.summarization`, preserving its existing persistence flag and `UnsupportedVideoError`→422 handling. Do NOT re-implement any branch logic here — delegate so the one gate governs every surface. (Implementer: read the current `summarize_v2` body, match its persist/response contract; map the pipeline output dict back to `SummarizeV2Response` fields it already returns.)

- [ ] **Step 5: Run tests + ruff**

Run: `python -m pytest tests/unit/summarization_engine/ -k "pipeline or v2_summarize or dedup or gate or route" -v`
Expected: all pass.
Run: `python -m ruff check website tests`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add website/api/module_runners/summarization.py website/features/summarization_engine/api/routes.py tests/unit/summarization_engine/test_dedup_gate.py
git commit -m "feat: route all add-zettel surfaces through dedup gate"
```

---
## Task 6: P2 — extend normalize_url tests

**Files:**
- Modify: `tests/unit/website/test_url_utils.py`

- [ ] **Step 1: Add dedup-critical cases**

Append to `tests/unit/website/test_url_utils.py`:

```python
import pytest
from website.core.url_utils import normalize_url


@pytest.mark.parametrize("a,b", [
    ("https://Example.com/Path", "https://example.com/Path"),          # host case
    ("https://example.com:443/p", "https://example.com/p"),            # default port
    ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),# query order
    ("https://example.com/p?utm_source=x&a=1", "https://example.com/p?a=1"),  # tracking strip
])
def test_normalize_url_collapses_equivalent_forms(a, b):
    assert normalize_url(a) == normalize_url(b)


def test_normalize_url_keeps_distinct_query_meaning():
    # Zoro's two iana example-domains rows differ by query → must stay distinct.
    assert normalize_url("https://www.iana.org/help/example-domains?zk_verif=1") \
        != normalize_url("https://www.iana.org/help/example-domains?api_verif=1")
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/unit/website/test_url_utils.py -v`
Expected: PASS. If any case fails, that is a real `normalize_url` gap — STOP and surface it (do not weaken the test); it affects dedup correctness.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/website/test_url_utils.py
git commit -m "test: dedup-critical normalize_url cases"
```

---

## Task 7: Full regression

- [ ] **Step 1: Lint**

Run: `python -m ruff check website tests`
Expected: `All checks passed!`

- [ ] **Step 2: Full suite**

Run: `python -m pytest -q --no-header -p no:cacheprovider`
Expected: all pass (prior baseline: 3069 passed + new tests; 0 failed). Diagnose+fix any regression before proceeding.

- [ ] **Step 3: Push + verify CI**

```bash
git push origin codex/exec-summarization-pipeline-final-fix
gh pr checks 25
```
Expected: `pytest (mocked)`, `unit-tests`, `scan`, `grep` all pass.

- [ ] **Step 4: Operator-gated migration apply**

Do NOT apply `45_url_dedup.sql` to production autonomously. Surface to the operator: dry-run via migration-CI, then operator runs the prod apply per migration-discipline. The 32 live rows + 2 dup-canonical URLs are collapsed by the migration; a backup of `content.canonical_zettels` + `content.workspace_zettels` is taken before apply (operator step).

---

## Self-Review

- **Spec coverage:** P1 reorder (Task 4) ✓; dedup key `normalize_url(resolve_redirects(url))` (Task 4 Step 3) ✓; ON CONFLICT→re-query+link via existing upsert conflict (Task 3 `link_existing_canonical`) ✓; same-user no-op no-charge (Task 4) ✓; cross-user link+charge+unaware (Task 4 `_cache_hit_output`) ✓; pricing untouched (only `require_entitlement` reused, no consume_entitlement edits) ✓; schema migration keep-newest + re-point + UNIQUE swap + RPC (Task 1) ✓; mirror /api/v2/summarize (Task 5) ✓; P2 counters (Task 4 `_dedup_log` branch lines, logs-only, no DTO) ✓; P2 url tests (Task 6) ✓; declined P3 not built ✓; regression+operator-gated apply (Task 7) ✓.
- **Placeholder scan:** Two implementer-discretion notes (workspace-id resolver reuse in Task 4; v2 persistence-parity in Task 5) are explicit "verify existing pattern and reuse" instructions, not blanks — acceptable because the exact existing helper must be located in-codebase; all code steps show full code.
- **Type consistency:** `CanonicalLookupResult` defined Task 2, used Tasks 3-4; `find_canonical_by_url`/`workspace_links_canonical`/`link_existing_canonical`/`_dedup_repo`/`_cache_hit_output` names consistent across tasks; `WorkspaceZettelCreate` fields match `models.py:35-42`.
