# User Statistics Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `/api/profile/stats` endpoint + Statistics tab on `/profile`, surfacing 28 user stats across 7 sections, served by a single SECURITY DEFINER RPC under hard safety guardrails.

**Architecture:** One per-user aggregation RPC (`core.profile_stats_v1`) + tiny ETag-probe RPC returning a single JSONB payload → FastAPI route wrapped by per-worker semaphore + in-process LRU + server ETag + kill-switch env flag → Statistics tab on `/profile` (desktop only; mobile `/m/` untouched) renders **cache-first from persistent localStorage** if available, then runs an **abortable fetch** in a separate loading-box (typewriter via `ZKSkeletonTyper`, progress bar 0→80→90→100 with stop button), and **hot-swaps cached → fresh** with a slide transition on success. NO materialized views in v1 (deferred to v2 per architecture audit ship sequence). Live queries only, gated by `stats_reader` Postgres role with 45s `statement_timeout`.

**Tech Stack:** Postgres 15 (Supabase v2 schemas: `core, content, kg, rag, billing`), FastAPI + Pydantic, vanilla JS + dark-theme CSS (no framework), `pytest` + `asyncio_mode=auto`, DigitalOcean droplet (2 GB / 1 vCPU, blue/green Docker Compose).

**Reference docs (read before starting):**
- `docs/claude_audits/user_stats_research_2026-05-26.md` — 100-stat catalog (the WHAT)
- `docs/claude_audits/user_stats_architecture_research_2026-05-26.md` — load architecture (the HOW)
- `CLAUDE.md` — production change discipline, infra guardrails, pricing module authority

---

## Spec — exact stats to ship (28 stats, locked)

| § | Section (UI tab) | Stats |
|---|------------------|-------|
| 1 | **Main Board** | 1.1 26-week GitHub-style activity heatmap · 1.2 Total Zettels (pie: used vs available) · 1.3 Total Kastens (pie: used vs available IF quota exists; else plain count + post-merge flag) |
| 2 | **General Overview** | 2.1 Member Since (days in vault) · 2.2 Zettels Last 30 Days + delta · 2.3 KG Size (nodes · edges) · 2.4 Source Diversity (X / 13) · 2.5 Plan tier + quota |
| 3 | **Zettel-level** | 3.1 Top source (single) + Latest zettel pair · 3.2 Avg summary length (chars + min/max) · 3.3 Avg user tags per zettel · 3.4 Tagged Coverage % |
| 4 | **Kasten-level** | 4.1 Largest Kasten + stats around it · 4.2 Avg conversation depth *(rag.chat_messages)* · 4.3 Most-cited source type *(chat_messages.citations)* · 4.4 Question streak current+longest *(chat_messages, role=user)* |
| 5 | **Domain / Topic-level** | 5.1 Topic concentration (HHI) · 5.2 Top 5 Emerging topics (last 30d) · 5.3 Top 5 Declining topics |
| 6 | **Activity** | 6.1 Current streak · 6.2 Longest streak · 6.3 This week vs last week · 6.4 Chat-vs-Capture mix |
| 7 | **Knowledge Graph** | 7.1 Mean degree (avg connections/node) · 7.2 Top 10 hub nodes · 7.3 Personal vs Global tag coverage · 7.4 Relation type mix |

**Locked decisions (per AskUserQuestion answers 2026-05-27):**
- Section 4 keeps the "Kasten-level" UI label even though stats 4.2/4.3/4.4 are technically retrieval stats. Data source documented in this plan.
- Kasten quota: assumed to exist. Implementer verifies in `docs/research/pricing1.md` + `billing.pricing_subscriptions` schema. If absent → render plain count + add explicit follow-up flag to plan output (Phase 7) so operator can spec the Kasten quota next.

---

## File Structure

**Backend (new):**
- `website/features/user_stats/__init__.py` — package marker
- `website/features/user_stats/router.py` — FastAPI APIRouter, single route `GET /api/profile/stats`
- `website/features/user_stats/repository.py` — calls `core.profile_stats_v1` RPC, applies cache
- `website/features/user_stats/models.py` — Pydantic response models (StatsResponse + 7 section models)
- `website/features/user_stats/semaphore.py` — per-worker bounded queue, 503 backpressure
- `website/features/user_stats/cache.py` — in-process LRU keyed by (workspace_id, etag)

**Backend (modified):**
- `website/app.py` — register the new router

**SQL migrations (new):**
- `supabase/website/_v2/79_stats_reader_role.sql` + `.down.sql` — read-only role + timeouts
- `supabase/website/_v2/80_chat_messages_user_partial_idx.sql` + `.down.sql` — partial index for chat stats
- `supabase/website/_v2/81_profile_stats_v1_rpc.sql` + `.down.sql` — the SECURITY DEFINER aggregation RPC

**Frontend (new):**
- `website/static/js/zk_stats_cache.js` — persistent per-workspace localStorage cache (SWR substrate)

**Frontend (modified):**
- `website/features/user_profile/index.html` — add loading-box + 7 tabs (default = Main Board); script tags for typewriter + cache modules. **No mobile changes — `/m/` profile surface untouched.**
- `website/features/user_profile/css/user_profile.css` — tab UI, stats grid, skeletons, pies, heatmap, loading-box (progress bar + stop button + collapse transition), reduced-motion fallback
- `website/features/user_profile/js/user_profile.js` — cache-first init, AbortController, progress simulator (0→80 linear, 80→90 slow, 90→100 burst), `ZKSkeletonTyper` integration, swap-in transition, tab switch, section renderers
- Asset version bumps (`?v=20260527a`)

**Reused, NOT modified:**
- `website/static/js/zk_skeleton_typewriter.js` — existing shared typewriter (`ZKSkeletonTyper.attach/update/detach`); loaded as-is

**Ops (new):**
- `ops/scripts/droplet_add_swapfile.sh` — idempotent 1 GB swap creation (run via SSH, operator authorizes)

**Tests (new):**
- `tests/unit/website/user_stats/__init__.py`
- `tests/unit/website/user_stats/test_models.py` — Pydantic shape validation
- `tests/unit/website/user_stats/test_semaphore.py` — concurrent calls + 503 path
- `tests/unit/website/user_stats/test_cache.py` — LRU hit/miss + ETag invalidation
- `tests/integration/v2/test_profile_stats_rpc.py` — RPC returns correct shape per section
- `tests/integration/v2/test_profile_stats_endpoint.py` — full HTTP request → cached response

---

## Phase 0 — Documentation Discovery (read before writing any code)

No code changes in this phase. Goal: every implementer reads these so later tasks don't re-discover.

### Task 0.1: Map existing v2 RPC patterns

**Files:**
- Read: `supabase/website/_v2/13_v2_kasten_rpcs.sql` — canonical SECURITY DEFINER + scope-by-workspace pattern
- Read: `supabase/website/_v2/35_retrieval_signal_views.sql` — MV pattern (for v2 reference only, not used in v1)
- Read: `supabase/website/_v2/36_signal_views_pgcron.sql` — pg_cron usage pattern
- Read: `supabase/website/_v2/02_content_schema.sql` — workspace_zettels columns + partial indexes
- Read: `supabase/website/_v2/04_rag_schema.sql` — kastens, kasten_zettels, chat_sessions, chat_messages
- Read: `supabase/website/_v2/03_kg_schema.sql` — kg_nodes, kg_edges
- Read: `supabase/website/_v2/06_billing_schema.sql` — pricing_subscriptions
- Read: `supabase/website/_v2/72_workspace_zettels_derived_tags.sql` — `user_tags` vs `derived_tags` split (CRITICAL: never expose derived_tags)
- Read: `supabase/website/_v2/73_normalize_user_tags.sql` — tag normalization

- [ ] **Step 1: Read every file above end-to-end. No code changes.**

Expected outcome: implementer can name the canonical `core.workspace_members.profile_id` scope, the `wz.deleted_at IS NULL` filter, and the `user_tags` (not `derived_tags`) rule from memory.

### Task 0.2: Map existing API patterns

**Files:**
- Read: `website/api/zettels_routes.py` — DTO + idempotency + structured problem pattern
- Read: `website/api/routes.py` — health + KG graph routes
- Read: `website/app.py` — router registration + middleware order
- Read: `website/core/settings.py` — Settings singleton + `get_settings()`
- Read: `website/features/functional_gates/` (if exists; check first) — reusable gate pattern
- Read: `website/features/rag_pipeline/router.py` — semaphore pattern (rerank uses one — find it)

- [ ] **Step 1: Read every file above end-to-end. No code changes.**

Expected outcome: implementer knows where to register a router, how settings are accessed, and the existing semaphore prior-art.

### Task 0.3: Read pricing module + verify Kasten quota existence

**Files:**
- Read: `docs/research/pricing1.md`
- Read: `supabase/website/_v2/06_billing_schema.sql` (re-read with quota lens)

- [ ] **Step 1: Identify the exact column(s) on `billing.pricing_subscriptions` (or the RPC `billing.pricing_consume_entitlement`) that surface the per-period Zettel quota.**

- [ ] **Step 2: Determine whether a Kasten quota exists. Record finding in the plan output:**

```
ZETTEL QUOTA: <column or RPC name> · period: <daily|weekly|monthly>
KASTEN QUOTA: <column or RPC name | NOT FOUND>
```

If `KASTEN QUOTA: NOT FOUND`, mark Task 7.4 (post-merge follow-up flag) as REQUIRED. If found, mark it OPTIONAL.

- [ ] **Step 3: No code changes. Commit nothing.**

### Task 0.4: Read frontend patterns

**Files:**
- Read: `website/features/user_profile/index.html` — existing structure, shared header placeholder
- Read: `website/features/user_profile/css/user_profile.css` — design tokens, dark theme, no purple
- Read: `website/features/user_profile/js/user_profile.js` — existing heatmap rendering, fetch patterns
- Read: `website/static/css/style.css` (header section) — token names, accent variables

- [ ] **Step 1: Note exact CSS token names (`--bg-card`, `--accent`, etc.) so we don't invent new ones.**

- [ ] **Step 2: Note the existing 26-week heatmap implementation so we know whether to port it server-side or reuse client-side.**

- [ ] **Step 3: Read `website/static/js/zk_skeleton_typewriter.js` end-to-end.** This is the canonical reusable typewriter. Public API:
  - `var typer = ZKSkeletonTyper.attach(el, options?)` — injects scoped style + caret + starts cycling
  - `typer.update({phase, elapsedMs})` — drives stage vocabulary (`queued|running|long|succeeded|failed`)
  - `typer.detach()` — fade out + cancel timers
  The stats loading box (Task 5.1) will use this verbatim — DO NOT reimplement.

- [ ] **Step 4: Confirm mobile scope.** `website/app.py` UA-redirects mobile to `/m/`. The Statistics tab is part of the desktop `/profile` page only. **NO mobile changes in this plan.** The `/m/` profile surface is untouched.

Expected outcome: implementer can extend the CSS without violating the teal-only / no-purple rule, knows the existing heatmap data flow, knows the typewriter API, and knows mobile is out of scope.

---

## Phase 1 — Safety Prerequisites (NON-NEGOTIABLE per architecture audit)

### Task 1.1: Create stats_reader Postgres role + grants

**Files:**
- Create: `supabase/website/_v2/79_stats_reader_role.sql`
- Create: `supabase/website/_v2/79_stats_reader_role.down.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 79_stats_reader_role.sql
-- Read-only role for the user statistics module. Hard timeouts to prevent
-- runaway aggregations from starving OLTP / OOM-killing the 2GB droplet.
-- Architecture audit reference: docs/claude_audits/user_stats_architecture_research_2026-05-26.md

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'stats_reader') THEN
    CREATE ROLE stats_reader NOLOGIN;
  END IF;
END $$;

-- Hard guardrails (per architecture audit §4):
ALTER ROLE stats_reader SET statement_timeout = '45s';
ALTER ROLE stats_reader SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE stats_reader SET lock_timeout = '5s';
ALTER ROLE stats_reader SET work_mem = '32MB';

-- Read-only grants (least privilege)
GRANT USAGE ON SCHEMA core, content, kg, rag, billing TO stats_reader;

GRANT SELECT ON
  core.profiles,
  core.workspaces,
  core.workspace_members,
  core.usage_events,
  content.canonical_zettels,
  content.workspace_zettels,
  content.canonical_chunks,
  content.workspace_chunk_membership,
  rag.kastens,
  rag.kasten_zettels,
  rag.kasten_members,
  rag.chat_sessions,
  rag.chat_messages,
  rag.retrieval_feedback_events,
  kg.kg_nodes,
  kg.kg_edges,
  kg.chunk_node_mentions,
  billing.pricing_subscriptions
TO stats_reader;

-- Allow execution of the stats RPC (defined in migration 81)
-- GRANT EXECUTE here is deferred to migration 81 where the function is created.
```

- [ ] **Step 2: Write the down migration**

```sql
-- 79_stats_reader_role.down.sql
REVOKE SELECT ON
  core.profiles,
  core.workspaces,
  core.workspace_members,
  core.usage_events,
  content.canonical_zettels,
  content.workspace_zettels,
  content.canonical_chunks,
  content.workspace_chunk_membership,
  rag.kastens,
  rag.kasten_zettels,
  rag.kasten_members,
  rag.chat_sessions,
  rag.chat_messages,
  rag.retrieval_feedback_events,
  kg.kg_nodes,
  kg.kg_edges,
  kg.chunk_node_mentions,
  billing.pricing_subscriptions
FROM stats_reader;

REVOKE USAGE ON SCHEMA core, content, kg, rag, billing FROM stats_reader;

DROP ROLE IF EXISTS stats_reader;
```

- [ ] **Step 3: Apply migration in staging**

```bash
psql "$STAGING_DATABASE_URL" -f supabase/website/_v2/79_stats_reader_role.sql
```

Expected: `CREATE ROLE` then `ALTER ROLE` then `GRANT` × N, no errors.

- [ ] **Step 4: Verify role exists with correct settings**

```bash
psql "$STAGING_DATABASE_URL" -c "SELECT rolname, rolconfig FROM pg_roles WHERE rolname='stats_reader';"
```

Expected: `stats_reader | {statement_timeout=45s,idle_in_transaction_session_timeout=60s,lock_timeout=5s,work_mem=32MB}`

- [ ] **Step 5: Commit**

```bash
git add supabase/website/_v2/79_stats_reader_role.sql supabase/website/_v2/79_stats_reader_role.down.sql
git commit -m "feat: add stats_reader role with hard timeouts"
```

### Task 1.2: Author droplet swapfile script

**Files:**
- Create: `ops/scripts/droplet_add_swapfile.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# ops/scripts/droplet_add_swapfile.sh
# Idempotent. Adds 1 GB swap to the production droplet.
# Per architecture audit: single most cost-effective OOM prevention for
# the 2 GB droplet, required BEFORE enabling the stats endpoint.
# Run via: ssh root@<droplet> 'bash -s' < ops/scripts/droplet_add_swapfile.sh

set -euo pipefail

SWAPFILE=/swapfile
SIZE_MB=1024

if [ -f "$SWAPFILE" ]; then
  echo "Swapfile already exists at $SWAPFILE"
  swapon --show
  exit 0
fi

echo "Creating ${SIZE_MB}MB swapfile at $SWAPFILE..."
fallocate -l ${SIZE_MB}M "$SWAPFILE"
chmod 600 "$SWAPFILE"
mkswap "$SWAPFILE"
swapon "$SWAPFILE"

# Persist across reboots
if ! grep -q "^${SWAPFILE} " /etc/fstab; then
  echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
fi

# Tune swap aggressiveness (lower = prefer RAM)
sysctl vm.swappiness=10
if ! grep -q "^vm.swappiness" /etc/sysctl.conf; then
  echo "vm.swappiness=10" >> /etc/sysctl.conf
fi

echo "Done. Verification:"
free -h
swapon --show
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ops/scripts/droplet_add_swapfile.sh
```

- [ ] **Step 3: Commit**

```bash
git add ops/scripts/droplet_add_swapfile.sh
git commit -m "ops: add idempotent 1GB swapfile script for droplet"
```

- [ ] **Step 4: HUMAN CHECKPOINT — request operator authorization to apply on production droplet**

Per CLAUDE.md "Audit/Verify ≠ Authorization": do NOT SSH into the droplet without explicit user approval. The script lands in the repo; application is a separate authorized step.

Output for operator:

```
PHASE 1 CHECKPOINT: Apply swapfile to droplet?

Command (run from your shell — NOT auto-executed):
  ssh root@<droplet-ip> 'bash -s' < ops/scripts/droplet_add_swapfile.sh

Expected:
  - free -h shows Swap: 1.0G total / 0B used post-script
  - /etc/fstab contains /swapfile entry
  - sysctl vm.swappiness = 10

Authorize? (y/n)
```

### Task 1.3: Implement semaphore module + tests

**Files:**
- Create: `website/features/user_stats/__init__.py` (empty)
- Create: `website/features/user_stats/semaphore.py`
- Create: `tests/unit/website/user_stats/__init__.py` (empty)
- Create: `tests/unit/website/user_stats/test_semaphore.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/website/user_stats/test_semaphore.py
import asyncio
import pytest
from website.features.user_stats.semaphore import StatsSemaphore, SemaphoreFullError


@pytest.mark.asyncio
async def test_semaphore_allows_max_concurrent():
    """Permit count = 1; one concurrent acquire succeeds."""
    sem = StatsSemaphore(max_concurrent=1, max_queued=2)
    async with sem.acquire():
        pass  # should not raise


@pytest.mark.asyncio
async def test_semaphore_rejects_when_queue_full():
    """When max_concurrent + max_queued slots are taken, raise SemaphoreFullError."""
    sem = StatsSemaphore(max_concurrent=1, max_queued=1)
    held = asyncio.Event()
    released = asyncio.Event()

    async def hold():
        async with sem.acquire():
            held.set()
            await released.wait()

    async def queue():
        async with sem.acquire():
            pass

    # Hold the only permit
    holder_task = asyncio.create_task(hold())
    await held.wait()
    # Queue one (within max_queued)
    queued_task = asyncio.create_task(queue())
    await asyncio.sleep(0.05)
    # Third should reject
    with pytest.raises(SemaphoreFullError):
        async with sem.acquire():
            pass
    released.set()
    await holder_task
    await queued_task


@pytest.mark.asyncio
async def test_semaphore_releases_on_exception():
    """If body raises, the permit must still be released."""
    sem = StatsSemaphore(max_concurrent=1, max_queued=0)
    with pytest.raises(ValueError):
        async with sem.acquire():
            raise ValueError("boom")
    # Should be reacquirable
    async with sem.acquire():
        pass
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/unit/website/user_stats/test_semaphore.py -v
```

Expected: ImportError / ModuleNotFoundError for `StatsSemaphore`.

- [ ] **Step 3: Implement the module**

```python
# website/features/user_stats/semaphore.py
"""Per-worker bounded queue for the stats endpoint.

Architecture audit §4: max 1 concurrent stats request per gunicorn worker,
queue depth 2, 503 backpressure above. With 2 workers = 2 concurrent total,
4 queued at most. Prevents OLTP starvation on 2GB / 1vCPU droplet.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class SemaphoreFullError(RuntimeError):
    """Raised when both active permits and queue are exhausted."""


class StatsSemaphore:
    def __init__(self, *, max_concurrent: int = 1, max_queued: int = 2) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if max_queued < 0:
            raise ValueError("max_queued must be >= 0")
        self._max_concurrent = max_concurrent
        self._max_queued = max_queued
        self._sem = asyncio.Semaphore(max_concurrent)
        self._in_flight = 0
        self._waiting = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        async with self._lock:
            total = self._in_flight + self._waiting
            if total >= self._max_concurrent + self._max_queued:
                raise SemaphoreFullError(
                    f"stats endpoint at capacity ({total}/{self._max_concurrent + self._max_queued})"
                )
            self._waiting += 1
        try:
            await self._sem.acquire()
            async with self._lock:
                self._waiting -= 1
                self._in_flight += 1
            try:
                yield
            finally:
                async with self._lock:
                    self._in_flight -= 1
                self._sem.release()
        except SemaphoreFullError:
            async with self._lock:
                self._waiting -= 1
            raise
```

- [ ] **Step 4: Run to verify pass**

```bash
python -m pytest tests/unit/website/user_stats/test_semaphore.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/user_stats/__init__.py website/features/user_stats/semaphore.py tests/unit/website/user_stats/__init__.py tests/unit/website/user_stats/test_semaphore.py
git commit -m "feat: stats endpoint per-worker semaphore"
```

---

## Phase 2 — Schema Additions (single index, no MV)

### Task 2.1: Partial index on chat_messages for retrieval stats

**Files:**
- Create: `supabase/website/_v2/80_chat_messages_user_partial_idx.sql`
- Create: `supabase/website/_v2/80_chat_messages_user_partial_idx.down.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 80_chat_messages_user_partial_idx.sql
-- Per Retrieval-section research: existing idx_chat_messages_session is
-- session-keyed. Stats 4.2/4.3/4.4 all filter on (workspace_id, role='user', created_at).
-- This partial index keeps stats endpoint latency under 50ms even at 10k+ messages
-- per workspace. CREATE INDEX CONCURRENTLY to avoid blocking writes.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_messages_workspace_user_created
  ON rag.chat_messages (workspace_id, created_at DESC)
  WHERE role = 'user';

ANALYZE rag.chat_messages;
```

- [ ] **Step 2: Write down migration**

```sql
-- 80_chat_messages_user_partial_idx.down.sql
DROP INDEX CONCURRENTLY IF EXISTS rag.idx_chat_messages_workspace_user_created;
```

- [ ] **Step 3: Apply in staging**

```bash
psql "$STAGING_DATABASE_URL" -f supabase/website/_v2/80_chat_messages_user_partial_idx.sql
```

Expected: `CREATE INDEX`, then `ANALYZE`, no errors.

NOTE: `CREATE INDEX CONCURRENTLY` cannot run inside a transaction. If your migration runner wraps in BEGIN/COMMIT, split this into a pre-runner step or use a tool that supports CONCURRENTLY (e.g., apply directly with psql).

- [ ] **Step 4: Verify index exists**

```bash
psql "$STAGING_DATABASE_URL" -c "\d rag.chat_messages" | grep idx_chat_messages_workspace_user_created
```

Expected: one match line.

- [ ] **Step 5: Commit**

```bash
git add supabase/website/_v2/80_chat_messages_user_partial_idx.sql supabase/website/_v2/80_chat_messages_user_partial_idx.down.sql
git commit -m "feat: partial idx on chat_messages for stats endpoint"
```

---

## Phase 3 — Backend RPC (single SECURITY DEFINER returning all 7 sections)

The RPC is built incrementally — each section gets its own task with a test that asserts the section shape. The migration file is rewritten in-place each task; in real history, only the final SQL lands per the migration runner.

### Task 3.0: Scaffold the RPC + integration test fixture

**Files:**
- Create: `supabase/website/_v2/81_profile_stats_v1_rpc.sql`
- Create: `supabase/website/_v2/81_profile_stats_v1_rpc.down.sql`
- Create: `tests/integration/v2/test_profile_stats_rpc.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/v2/test_profile_stats_rpc.py
import pytest

pytestmark = pytest.mark.asyncio


async def test_rpc_returns_skeleton_for_empty_workspace(asyncpg_pool, mint_user):
    """RPC must return all 7 sections even for a brand-new empty workspace."""
    user = await mint_user(email="empty@test.local")
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT core.profile_stats_v1($1) AS payload",
            user["workspace_id"],
        )
    payload = row["payload"]
    assert "meta" in payload
    assert "main_board" in payload
    assert "general" in payload
    assert "zettel" in payload
    assert "kasten" in payload
    assert "domain" in payload
    assert "activity" in payload
    assert "graph" in payload
    assert payload["meta"]["workspace_id"] == str(user["workspace_id"])
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/integration/v2/test_profile_stats_rpc.py::test_rpc_returns_skeleton_for_empty_workspace -v
```

Expected: `function core.profile_stats_v1(uuid) does not exist`.

- [ ] **Step 3: Write the RPC scaffold migration**

```sql
-- 81_profile_stats_v1_rpc.sql
-- Single per-workspace stats aggregation. SECURITY DEFINER so it can read
-- across schemas without granting the caller direct table access.
-- All sections build a JSONB payload that the BFF returns verbatim.
--
-- Safety: SET LOCAL statement_timeout at top so even mis-routed callers
-- inherit the 45s ceiling. SET LOCAL work_mem caps memory per session.
--
-- Reference: docs/superpowers/plans/2026-05-27-user-statistics-module.md

CREATE OR REPLACE FUNCTION core.profile_stats_v1(p_workspace_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_payload jsonb;
BEGIN
  -- Per-call safety net (independent of role-level settings)
  SET LOCAL statement_timeout = '45s';
  SET LOCAL work_mem = '32MB';

  -- Scope check: caller's auth context must include this workspace
  IF NOT EXISTS (
    SELECT 1 FROM core.workspace_members wm
     WHERE wm.workspace_id = p_workspace_id
       AND wm.profile_id = auth.uid()
  ) THEN
    RAISE EXCEPTION 'workspace not accessible' USING ERRCODE = '42501';
  END IF;

  v_payload := jsonb_build_object(
    'meta', jsonb_build_object(
      'workspace_id', p_workspace_id::text,
      'profile_id', auth.uid()::text,
      'computed_at', now(),
      'schema_version', 1
    ),
    'main_board', '{}'::jsonb,
    'general', '{}'::jsonb,
    'zettel', '{}'::jsonb,
    'kasten', '{}'::jsonb,
    'domain', '{}'::jsonb,
    'activity', '{}'::jsonb,
    'graph', '{}'::jsonb
  );

  RETURN v_payload;
END;
$$;

REVOKE ALL ON FUNCTION core.profile_stats_v1(uuid) FROM public;
GRANT EXECUTE ON FUNCTION core.profile_stats_v1(uuid) TO authenticated, stats_reader, service_role;
```

- [ ] **Step 4: Write down migration**

```sql
-- 81_profile_stats_v1_rpc.down.sql
DROP FUNCTION IF EXISTS core.profile_stats_v1(uuid);
```

- [ ] **Step 5: Apply migration in staging**

```bash
psql "$STAGING_DATABASE_URL" -f supabase/website/_v2/81_profile_stats_v1_rpc.sql
```

- [ ] **Step 6: Run test, verify pass**

```bash
python -m pytest tests/integration/v2/test_profile_stats_rpc.py::test_rpc_returns_skeleton_for_empty_workspace -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add supabase/website/_v2/81_profile_stats_v1_rpc.sql supabase/website/_v2/81_profile_stats_v1_rpc.down.sql tests/integration/v2/test_profile_stats_rpc.py
git commit -m "feat: scaffold profile_stats_v1 RPC + skeleton test"
```

### Task 3.1: Main Board section (heatmap + zettels pie + kastens pie/count)

**Files:**
- Modify: `supabase/website/_v2/81_profile_stats_v1_rpc.sql` (replace function body)
- Modify: `tests/integration/v2/test_profile_stats_rpc.py` (add section test)

- [ ] **Step 1: Add the failing test**

```python
# tests/integration/v2/test_profile_stats_rpc.py — append:

async def test_main_board_section(asyncpg_pool, mint_user, seed_zettels, seed_kastens):
    """Main Board returns heatmap (26 weeks), zettels pie, kastens count or pie."""
    user = await mint_user(email="mb@test.local")
    await seed_zettels(user["workspace_id"], count=15)
    await seed_kastens(user["workspace_id"], count=3)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT core.profile_stats_v1($1) AS payload",
            user["workspace_id"],
        )
    mb = row["payload"]["main_board"]
    assert isinstance(mb["heatmap"], list)
    # 26 weeks * 7 days = 182 cells max; many may be zero
    assert len(mb["heatmap"]) <= 182
    assert mb["zettels_quota"]["used"] >= 0
    assert mb["zettels_quota"]["available"] >= 0
    # Kastens: either pie shape OR plain count
    assert "kastens" in mb
    assert isinstance(mb["kastens"], dict)
    assert "total" in mb["kastens"]
```

- [ ] **Step 2: Add fixtures `seed_zettels`, `seed_kastens` to `tests/integration/v2/conftest.py`**

```python
# tests/integration/v2/conftest.py — append (preserve existing fixtures):

@pytest.fixture
def seed_zettels(asyncpg_pool):
    async def _seed(workspace_id, count: int):
        async with asyncpg_pool.acquire() as conn:
            for i in range(count):
                cz_id = await conn.fetchval(
                    """
                    INSERT INTO content.canonical_zettels (id, normalized_url, content_hash, source_type, title, created_at)
                    VALUES (gen_random_uuid(), 'https://example.com/' || gen_random_uuid()::text,
                            md5(random()::text), 'web', 'seed-' || $1, now() - ($1 || ' days')::interval)
                    RETURNING id
                    """,
                    i,
                )
                await conn.execute(
                    """
                    INSERT INTO content.workspace_zettels (workspace_id, canonical_zettel_id, ai_summary, user_tags, added_via, created_at)
                    VALUES ($1, $2, 'summary ' || $3, ARRAY['tag1','tag2']::text[], 'website', now() - ($3 || ' days')::interval)
                    """,
                    workspace_id, cz_id, i,
                )
    return _seed


@pytest.fixture
def seed_kastens(asyncpg_pool):
    async def _seed(workspace_id, count: int):
        async with asyncpg_pool.acquire() as conn:
            for i in range(count):
                await conn.execute(
                    """
                    INSERT INTO rag.kastens (id, workspace_id, name, created_at)
                    VALUES (gen_random_uuid(), $1, 'kasten-' || $2, now() - ($2 || ' days')::interval)
                    """,
                    workspace_id, i,
                )
    return _seed
```

- [ ] **Step 3: Run, verify fail**

```bash
python -m pytest tests/integration/v2/test_profile_stats_rpc.py::test_main_board_section -v
```

Expected: KeyError on `heatmap` / `zettels_quota` / `kastens`.

- [ ] **Step 4: Implement Main Board section in the RPC**

Replace the `v_payload := jsonb_build_object(...)` block in `81_profile_stats_v1_rpc.sql` so `main_board` is populated. Add ABOVE the `v_payload := ...` assignment:

```sql
DECLARE
  v_payload jsonb;
  v_main_board jsonb;
  -- ... (other section locals added in later tasks)
  v_zettel_quota_used int;
  v_zettel_quota_avail int;
  v_kasten_quota_used int;
  v_kasten_quota_avail int;
  v_kasten_quota_exists boolean;
BEGIN
  SET LOCAL statement_timeout = '45s';
  SET LOCAL work_mem = '32MB';

  -- Scope check (unchanged)
  IF NOT EXISTS ( ... ) THEN ... END IF;

  -- ─── Main Board ───────────────────────────────────────────────────────
  -- 1.1 26-week heatmap: daily zettel count for last 182 days, zero-filled.
  -- 1.2 Zettel quota: lifetime count + current-period quota from billing.
  -- 1.3 Kasten quota: lifetime count + (quota IF column exists, else NULL).

  -- Quota lookups (defensive: pricing_subscriptions schema must be verified
  -- in Phase 0 / Task 0.3 — substitute the real column names below).
  -- ASSUMPTION: pricing_subscriptions has a JSONB or denormalized column
  -- exposing per-period zettel + (maybe) kasten quotas. If Kasten quota
  -- does not exist, v_kasten_quota_exists stays false.
  SELECT
    COALESCE((entitlements->>'zettel_period_quota')::int, 0),
    (entitlements ? 'kasten_period_quota')
  INTO v_zettel_quota_avail, v_kasten_quota_exists
  FROM billing.pricing_subscriptions
  WHERE profile_id = auth.uid()
    AND status IN ('active','authenticated')
  ORDER BY created_at DESC
  LIMIT 1;

  IF v_kasten_quota_exists THEN
    SELECT (entitlements->>'kasten_period_quota')::int
      INTO v_kasten_quota_avail
      FROM billing.pricing_subscriptions
     WHERE profile_id = auth.uid()
       AND status IN ('active','authenticated')
     ORDER BY created_at DESC LIMIT 1;
  END IF;

  SELECT count(*) INTO v_zettel_quota_used
    FROM content.workspace_zettels
   WHERE workspace_id = p_workspace_id
     AND deleted_at IS NULL
     AND created_at >= date_trunc('month', now());

  SELECT count(*) INTO v_kasten_quota_used
    FROM rag.kastens
   WHERE workspace_id = p_workspace_id;

  WITH days AS (
    SELECT generate_series(
      (now() - interval '182 days')::date,
      now()::date,
      interval '1 day'
    )::date AS d
  ),
  buckets AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS d, count(*)::int AS n
      FROM content.workspace_zettels
     WHERE workspace_id = p_workspace_id
       AND deleted_at IS NULL
       AND created_at >= now() - interval '182 days'
     GROUP BY 1
  )
  SELECT jsonb_build_object(
    'heatmap', COALESCE(
      jsonb_agg(jsonb_build_object('date', days.d, 'count', COALESCE(buckets.n, 0)) ORDER BY days.d),
      '[]'::jsonb
    ),
    'zettels_quota', jsonb_build_object(
      'used', v_zettel_quota_used,
      'available', v_zettel_quota_avail,
      'period', 'month'
    ),
    'kastens', CASE
      WHEN v_kasten_quota_exists THEN jsonb_build_object(
        'total', v_kasten_quota_used,
        'used', v_kasten_quota_used,
        'available', v_kasten_quota_avail,
        'period', 'month'
      )
      ELSE jsonb_build_object(
        'total', v_kasten_quota_used,
        'quota_available', false
      )
    END
  ) INTO v_main_board
  FROM days LEFT JOIN buckets USING (d);

  -- ─── Assemble (sections to be filled by Tasks 3.2-3.7) ────────────────
  v_payload := jsonb_build_object(
    'meta', jsonb_build_object(
      'workspace_id', p_workspace_id::text,
      'profile_id', auth.uid()::text,
      'computed_at', now(),
      'schema_version', 1
    ),
    'main_board', v_main_board,
    'general', '{}'::jsonb,
    'zettel', '{}'::jsonb,
    'kasten', '{}'::jsonb,
    'domain', '{}'::jsonb,
    'activity', '{}'::jsonb,
    'graph', '{}'::jsonb
  );

  RETURN v_payload;
END;
$$;
```

⚠ **Implementer note**: The `entitlements->>'zettel_period_quota'` and `entitlements ? 'kasten_period_quota'` paths above are STRAWMEN. Task 0.3 will have produced the actual column/RPC names — replace them here. If `billing.pricing_consume_entitlement` is the canonical surface (per CLAUDE.md "Pricing Module Authority"), call it instead of reading `entitlements` directly. **NEVER alter `consume_entitlement` itself**; this RPC is read-only.

- [ ] **Step 5: Re-apply migration**

```bash
psql "$STAGING_DATABASE_URL" -f supabase/website/_v2/81_profile_stats_v1_rpc.sql
```

- [ ] **Step 6: Run test, verify pass**

```bash
python -m pytest tests/integration/v2/test_profile_stats_rpc.py::test_main_board_section -v
```

Expected: PASS.

- [ ] **Step 7: Verify query plan stays cheap**

```bash
psql "$STAGING_DATABASE_URL" -c "EXPLAIN (ANALYZE, BUFFERS) SELECT core.profile_stats_v1('<test-workspace-uuid>');"
```

Expected: total runtime <500 ms for a workspace with <100 zettels. No seq-scan over >100k rows. If any node shows seq-scan over >100k rows, STOP and revisit — that's the EXPLAIN-and-bound gate from architecture audit §4.

- [ ] **Step 8: Commit**

```bash
git add supabase/website/_v2/81_profile_stats_v1_rpc.sql tests/integration/v2/test_profile_stats_rpc.py tests/integration/v2/conftest.py
git commit -m "feat: stats RPC Main Board section"
```

### Task 3.2: General Overview section

**Files:**
- Modify: `supabase/website/_v2/81_profile_stats_v1_rpc.sql`
- Modify: `tests/integration/v2/test_profile_stats_rpc.py`

- [ ] **Step 1: Add the failing test**

```python
async def test_general_section(asyncpg_pool, mint_user, seed_zettels):
    user = await mint_user(email="gen@test.local")
    await seed_zettels(user["workspace_id"], count=8)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT core.profile_stats_v1($1) AS payload",
            user["workspace_id"],
        )
    g = row["payload"]["general"]
    assert g["member_since"]["days"] >= 0
    assert g["zettels_30d"]["count"] >= 0
    assert "delta_pct" in g["zettels_30d"]
    assert "sparkline" in g["zettels_30d"]
    assert g["kg_size"]["nodes"] >= 0
    assert g["kg_size"]["edges"] >= 0
    assert g["source_diversity"]["used"] >= 1
    assert g["source_diversity"]["max"] == 13
    assert g["plan"]["tier"] is not None
```

- [ ] **Step 2: Run, verify fail**

```bash
python -m pytest tests/integration/v2/test_profile_stats_rpc.py::test_general_section -v
```

- [ ] **Step 3: Implement General section in the RPC**

Add a `v_general` build block before the `v_payload := ...` assembly. Replace `'general', '{}'::jsonb,` in the assembly with `'general', v_general,`. Insert this between Main Board and the assembly:

```sql
  -- ─── General Overview ─────────────────────────────────────────────────
  WITH zettel_30d AS (
    SELECT
      count(*) FILTER (WHERE created_at >= now() - interval '30 days') AS last30,
      count(*) FILTER (WHERE created_at >= now() - interval '60 days'
                         AND created_at <  now() - interval '30 days') AS prev30
      FROM content.workspace_zettels
     WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
  ),
  sparkline AS (
    SELECT jsonb_agg(jsonb_build_object('week', wk, 'count', cnt) ORDER BY wk) AS arr
      FROM (
        SELECT date_trunc('week', d)::date AS wk, COALESCE(sum(c),0)::int AS cnt
          FROM (
            SELECT generate_series(
              (now() - interval '56 days')::date,
              now()::date, interval '1 day'
            )::date AS d
          ) days
          LEFT JOIN (
            SELECT (created_at AT TIME ZONE 'UTC')::date AS dd, count(*) AS c
              FROM content.workspace_zettels
             WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
               AND created_at >= now() - interval '56 days'
             GROUP BY 1
          ) z ON z.dd = days.d
         GROUP BY 1
      ) s
  )
  SELECT jsonb_build_object(
    'member_since', jsonb_build_object(
      'joined_at', (SELECT created_at FROM core.profiles WHERE id = auth.uid()),
      'days', (SELECT (now()::date - created_at::date) FROM core.profiles WHERE id = auth.uid())
    ),
    'zettels_30d', jsonb_build_object(
      'count', (SELECT last30 FROM zettel_30d),
      'delta_pct', CASE
        WHEN (SELECT prev30 FROM zettel_30d) = 0 THEN NULL
        ELSE round(100.0 * ((SELECT last30 FROM zettel_30d) - (SELECT prev30 FROM zettel_30d))
                  / (SELECT prev30 FROM zettel_30d)::numeric, 1)
      END,
      'sparkline', (SELECT arr FROM sparkline)
    ),
    'kg_size', jsonb_build_object(
      'nodes', (SELECT count(*) FROM kg.kg_nodes WHERE workspace_id = p_workspace_id),
      'edges', (SELECT count(*) FROM kg.kg_edges WHERE workspace_id = p_workspace_id)
    ),
    'source_diversity', jsonb_build_object(
      'used', (
        SELECT count(DISTINCT cz.source_type)
          FROM content.workspace_zettels wz
          JOIN content.canonical_zettels cz ON cz.id = wz.canonical_zettel_id
         WHERE wz.workspace_id = p_workspace_id AND wz.deleted_at IS NULL
      ),
      'max', 13
    ),
    'plan', jsonb_build_object(
      'tier', COALESCE((
        SELECT plan_id FROM billing.pricing_subscriptions
         WHERE profile_id = auth.uid() AND status IN ('active','authenticated')
         ORDER BY created_at DESC LIMIT 1
      ), 'free'),
      'period_end', (
        SELECT current_period_end FROM billing.pricing_subscriptions
         WHERE profile_id = auth.uid() AND status IN ('active','authenticated')
         ORDER BY created_at DESC LIMIT 1
      )
    )
  ) INTO v_general;
```

Add `v_general jsonb;` to the DECLARE block.

- [ ] **Step 4: Apply, run, verify pass**

```bash
psql "$STAGING_DATABASE_URL" -f supabase/website/_v2/81_profile_stats_v1_rpc.sql
python -m pytest tests/integration/v2/test_profile_stats_rpc.py::test_general_section -v
```

- [ ] **Step 5: EXPLAIN, verify <500ms**

- [ ] **Step 6: Commit**

```bash
git add supabase/website/_v2/81_profile_stats_v1_rpc.sql tests/integration/v2/test_profile_stats_rpc.py
git commit -m "feat: stats RPC General Overview section"
```

### Task 3.3: Zettel-level section

**Files:** same as Task 3.2.

- [ ] **Step 1: Add failing test**

```python
async def test_zettel_section(asyncpg_pool, mint_user, seed_zettels):
    user = await mint_user(email="zl@test.local")
    await seed_zettels(user["workspace_id"], count=6)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT core.profile_stats_v1($1) AS payload",
            user["workspace_id"],
        )
    z = row["payload"]["zettel"]
    assert z["top_source"]["source_type"] is not None
    assert z["top_source"]["count"] >= 1
    assert z["latest"]["title"] is not None
    assert z["avg_summary_chars"]["mean"] >= 0
    assert z["avg_summary_chars"]["min"] >= 0
    assert z["avg_summary_chars"]["max"] >= 0
    assert z["avg_user_tags"] >= 0
    assert 0.0 <= z["tagged_coverage_pct"] <= 1.0
```

- [ ] **Step 2-6: Same TDD cycle. Section code to insert before assembly:**

```sql
  -- ─── Zettel-level ─────────────────────────────────────────────────────
  WITH zw AS (
    SELECT wz.*, cz.source_type, cz.title, cz.body_md
      FROM content.workspace_zettels wz
      JOIN content.canonical_zettels cz ON cz.id = wz.canonical_zettel_id
     WHERE wz.workspace_id = p_workspace_id AND wz.deleted_at IS NULL
  ),
  top_src AS (
    SELECT source_type, count(*) AS n
      FROM zw GROUP BY source_type ORDER BY n DESC LIMIT 1
  ),
  latest AS (
    SELECT title, source_type, created_at FROM zw ORDER BY created_at DESC LIMIT 1
  )
  SELECT jsonb_build_object(
    'top_source', jsonb_build_object(
      'source_type', (SELECT source_type FROM top_src),
      'count', (SELECT n FROM top_src),
      'pct', round(100.0 * (SELECT n FROM top_src) / NULLIF((SELECT count(*) FROM zw),0), 1)
    ),
    'latest', jsonb_build_object(
      'title', (SELECT title FROM latest),
      'source_type', (SELECT source_type FROM latest),
      'created_at', (SELECT created_at FROM latest)
    ),
    'avg_summary_chars', jsonb_build_object(
      'mean', COALESCE(avg(length(ai_summary)),0)::int,
      'min', COALESCE(min(length(ai_summary)),0),
      'max', COALESCE(max(length(ai_summary)),0)
    ),
    'avg_user_tags', COALESCE(avg(COALESCE(array_length(user_tags,1),0))::numeric(4,1), 0),
    'tagged_coverage_pct', COALESCE(
      avg((COALESCE(array_length(user_tags,1),0) > 0)::int)::numeric(4,3), 0
    )
  ) INTO v_zettel
  FROM zw;
```

Add `v_zettel jsonb;` to DECLARE. Replace `'zettel', '{}'::jsonb,` with `'zettel', v_zettel,`.

- Commit message: `feat: stats RPC Zettel-level section`

### Task 3.4: Kasten-level section (with chat-message stats per locked decision)

**Files:** same.

⚠ **Documented anomaly**: Stats 4.2/4.3/4.4 come from `rag.chat_messages`/`citations`, not from Kasten tables. The UI tab labels them "Kasten-level" per locked product decision (2026-05-27).

- [ ] **Step 1: Add failing test**

```python
async def test_kasten_section(asyncpg_pool, mint_user, seed_zettels, seed_kastens, seed_chat_messages):
    user = await mint_user(email="ks@test.local")
    await seed_zettels(user["workspace_id"], count=10)
    await seed_kastens(user["workspace_id"], count=3, with_zettels=True)
    await seed_chat_messages(user["workspace_id"], user_messages=5, assistant_with_citations=3)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT core.profile_stats_v1($1) AS payload", user["workspace_id"])
    k = row["payload"]["kasten"]
    assert k["largest"]["name"] is not None
    assert k["largest"]["zettel_count"] >= 0
    assert k["largest"]["last_added_at"] is not None or k["largest"]["zettel_count"] == 0
    assert k["largest"]["age_days"] >= 0
    assert k["avg_conversation_depth"] >= 0
    assert k["most_cited_source_type"]["source_type"] is not None
    assert k["question_streak"]["current"] >= 0
    assert k["question_streak"]["longest"] >= 0
```

- [ ] **Step 2: Add `seed_chat_messages` fixture to `conftest.py`**

```python
@pytest.fixture
def seed_chat_messages(asyncpg_pool):
    async def _seed(workspace_id, user_messages: int, assistant_with_citations: int = 0):
        async with asyncpg_pool.acquire() as conn:
            session_id = await conn.fetchval(
                "INSERT INTO rag.chat_sessions (id, workspace_id, profile_id, created_at) "
                "VALUES (gen_random_uuid(), $1, (SELECT owner_profile_id FROM core.workspaces WHERE id=$1), now()) RETURNING id",
                workspace_id,
            )
            for i in range(user_messages):
                await conn.execute(
                    "INSERT INTO rag.chat_messages (id, session_id, workspace_id, role, content, created_at) "
                    "VALUES (gen_random_uuid(), $1, $2, 'user', 'q' || $3, now() - ($3 || ' hours')::interval)",
                    session_id, workspace_id, i,
                )
            for i in range(assistant_with_citations):
                # Build a sample citation referencing a real zettel
                cz_id = await conn.fetchval(
                    "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE workspace_id=$1 LIMIT 1",
                    workspace_id,
                )
                await conn.execute(
                    "INSERT INTO rag.chat_messages (id, session_id, workspace_id, role, content, citations, verdict, created_at) "
                    "VALUES (gen_random_uuid(), $1, $2, 'assistant', 'a' || $3, "
                    "jsonb_build_array(jsonb_build_object('canonical_zettel_id', $4::text)), 'supported', now())",
                    session_id, workspace_id, i, cz_id,
                )
    return _seed
```

- [ ] **Step 3-6: Implement section + verify**

```sql
  -- ─── Kasten-level (incl. chat stats per product decision 2026-05-27) ──
  WITH kasten_sizes AS (
    SELECT k.id, k.name, k.icon, k.color, k.created_at,
           count(*) FILTER (WHERE wz.deleted_at IS NULL) AS n,
           max(kz.added_at) AS last_add
      FROM rag.kastens k
      LEFT JOIN rag.kasten_zettels kz ON kz.kasten_id = k.id
      LEFT JOIN content.workspace_zettels wz ON wz.id = kz.workspace_zettel_id
     WHERE k.workspace_id = p_workspace_id
     GROUP BY k.id
  ),
  largest AS (
    SELECT * FROM kasten_sizes ORDER BY n DESC, created_at ASC LIMIT 1
  ),
  conv_depth AS (
    SELECT COALESCE(avg(turn_count)::numeric(6,2), 0) AS d
      FROM (
        SELECT session_id, count(*) FILTER (WHERE role='user') AS turn_count
          FROM rag.chat_messages
         WHERE workspace_id = p_workspace_id
         GROUP BY session_id
         HAVING count(*) FILTER (WHERE role='user') > 0
      ) s
  ),
  citation_src AS (
    SELECT cz.source_type, count(*) AS n
      FROM rag.chat_messages m,
           LATERAL jsonb_array_elements(COALESCE(m.citations, '[]'::jsonb)) AS cit
      JOIN content.canonical_zettels cz ON cz.id = (cit->>'canonical_zettel_id')::uuid
     WHERE m.workspace_id = p_workspace_id AND m.role = 'assistant'
     GROUP BY cz.source_type ORDER BY n DESC LIMIT 1
  ),
  q_days AS (
    SELECT DISTINCT date_trunc('day', created_at)::date AS d
      FROM rag.chat_messages
     WHERE workspace_id = p_workspace_id AND role = 'user'
  ),
  q_runs AS (
    SELECT d, d - (row_number() OVER (ORDER BY d))::int AS g FROM q_days
  ),
  q_groups AS (
    SELECT g, count(*) AS c, min(d) AS s, max(d) AS e FROM q_runs GROUP BY g
  ),
  q_current AS (
    SELECT COALESCE((
      SELECT c FROM q_groups WHERE e = (now()::date) OR e = (now()::date - 1)
       ORDER BY e DESC LIMIT 1
    ), 0) AS c
  ),
  q_longest AS (
    SELECT COALESCE(max(c), 0) AS c FROM q_groups
  )
  SELECT jsonb_build_object(
    'largest', jsonb_build_object(
      'name', (SELECT name FROM largest),
      'icon', (SELECT icon FROM largest),
      'color', (SELECT color FROM largest),
      'zettel_count', COALESCE((SELECT n FROM largest), 0),
      'last_added_at', (SELECT last_add FROM largest),
      'age_days', (SELECT (now()::date - created_at::date) FROM largest)
    ),
    'avg_conversation_depth', (SELECT d FROM conv_depth),
    'most_cited_source_type', jsonb_build_object(
      'source_type', (SELECT source_type FROM citation_src),
      'count', COALESCE((SELECT n FROM citation_src), 0)
    ),
    'question_streak', jsonb_build_object(
      'current', (SELECT c FROM q_current),
      'longest', (SELECT c FROM q_longest)
    )
  ) INTO v_kasten;
```

Add `v_kasten jsonb;` to DECLARE. Replace `'kasten', '{}'::jsonb,` with `'kasten', v_kasten,`.

- Commit: `feat: stats RPC Kasten-level section (incl. chat stats)`

### Task 3.5: Domain section

- [ ] **Step 1: Add failing test**

```python
async def test_domain_section(asyncpg_pool, mint_user, seed_zettels_with_tags):
    user = await mint_user(email="dm@test.local")
    await seed_zettels_with_tags(user["workspace_id"], tag_distribution={
        "python": 8, "rust": 5, "ml": 4, "stale": 1
    })
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT core.profile_stats_v1($1) AS payload", user["workspace_id"])
    d = row["payload"]["domain"]
    assert 0.0 <= d["concentration_hhi"] <= 1.0
    assert isinstance(d["emerging_top5"], list)
    assert len(d["emerging_top5"]) <= 5
    assert isinstance(d["declining_top5"], list)
    assert len(d["declining_top5"]) <= 5
```

- [ ] **Step 2: Add `seed_zettels_with_tags` fixture**

```python
@pytest.fixture
def seed_zettels_with_tags(asyncpg_pool):
    async def _seed(workspace_id, tag_distribution: dict[str, int]):
        async with asyncpg_pool.acquire() as conn:
            for tag, n in tag_distribution.items():
                for i in range(n):
                    cz = await conn.fetchval(
                        "INSERT INTO content.canonical_zettels (id, normalized_url, content_hash, source_type, title) "
                        "VALUES (gen_random_uuid(), 'https://example.com/' || gen_random_uuid()::text, md5(random()::text), 'web', $1) "
                        "RETURNING id",
                        f"{tag}-{i}",
                    )
                    await conn.execute(
                        "INSERT INTO content.workspace_zettels (workspace_id, canonical_zettel_id, ai_summary, user_tags, added_via, created_at) "
                        "VALUES ($1, $2, '', $3::text[], 'website', now() - ($4 || ' days')::interval)",
                        workspace_id, cz, [tag], (45 if tag == 'stale' else i),
                    )
    return _seed
```

- [ ] **Step 3-6: Implement section + verify**

```sql
  -- ─── Domain / Topic-level ─────────────────────────────────────────────
  WITH tag_rows AS (
    SELECT tag, wz.created_at
      FROM content.workspace_zettels wz, unnest(wz.user_tags) AS tag
     WHERE wz.workspace_id = p_workspace_id AND wz.deleted_at IS NULL
  ),
  totals AS (
    SELECT tag, count(*)::numeric AS c FROM tag_rows GROUP BY tag
  ),
  hhi AS (
    SELECT COALESCE(sum((c / NULLIF(sum(c) OVER (),0))^2)::numeric(5,4), 0) AS h FROM totals
  ),
  lifetime AS (
    SELECT tag, c, c / NULLIF(sum(c) OVER (),0) AS share FROM totals
  ),
  recent AS (
    SELECT tag, count(*)::numeric AS c, count(*) / NULLIF(sum(count(*)) OVER (),0) AS share
      FROM tag_rows WHERE created_at >= now() - interval '30 days' GROUP BY tag
  ),
  emerging AS (
    SELECT recent.tag, (recent.share - COALESCE(lifetime.share,0)) AS delta
      FROM recent LEFT JOIN lifetime ON lifetime.tag = recent.tag
     WHERE recent.c >= 2
     ORDER BY delta DESC LIMIT 5
  ),
  declining AS (
    SELECT lifetime.tag, (COALESCE(recent.share,0) - lifetime.share) AS delta
      FROM lifetime LEFT JOIN recent ON recent.tag = lifetime.tag
     WHERE lifetime.c >= 5
     ORDER BY delta ASC LIMIT 5
  )
  SELECT jsonb_build_object(
    'concentration_hhi', (SELECT h FROM hhi LIMIT 1),
    'emerging_top5', COALESCE(
      (SELECT jsonb_agg(jsonb_build_object('tag', tag, 'delta_share', round(delta::numeric, 4))) FROM emerging),
      '[]'::jsonb
    ),
    'declining_top5', COALESCE(
      (SELECT jsonb_agg(jsonb_build_object('tag', tag, 'delta_share', round(delta::numeric, 4))) FROM declining),
      '[]'::jsonb
    )
  ) INTO v_domain;
```

Add `v_domain jsonb;` to DECLARE. Replace `'domain', '{}'::jsonb,` with `'domain', v_domain,`.

- Commit: `feat: stats RPC Domain section`

### Task 3.6: Activity section

- [ ] **Step 1: Add failing test**

```python
async def test_activity_section(asyncpg_pool, mint_user, seed_zettels, seed_chat_messages):
    user = await mint_user(email="act@test.local")
    await seed_zettels(user["workspace_id"], count=12)
    await seed_chat_messages(user["workspace_id"], user_messages=3, assistant_with_citations=2)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT core.profile_stats_v1($1) AS payload", user["workspace_id"])
    a = row["payload"]["activity"]
    assert a["current_streak"] >= 0
    assert a["longest_streak"] >= 0
    assert a["week_over_week"]["this_week"] >= 0
    assert a["week_over_week"]["last_week"] >= 0
    assert "delta_pct" in a["week_over_week"]
    assert a["chat_vs_capture"]["captures_30d"] >= 0
    assert a["chat_vs_capture"]["chats_30d"] >= 0
```

- [ ] **Step 2-6: Implement**

```sql
  -- ─── Activity / Engagement ────────────────────────────────────────────
  -- Unified action stream: zettel-added + chat-sent + kasten-created.
  -- Bucketed by UTC date in v1 (timezone-correct version is a v2 follow-up).
  WITH actions AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS d
      FROM content.workspace_zettels
     WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
    UNION ALL
    SELECT (created_at AT TIME ZONE 'UTC')::date
      FROM rag.chat_messages
     WHERE workspace_id = p_workspace_id AND role = 'user'
    UNION ALL
    SELECT (created_at AT TIME ZONE 'UTC')::date
      FROM rag.kastens WHERE workspace_id = p_workspace_id
  ),
  days AS (
    SELECT DISTINCT d FROM actions
  ),
  runs AS (
    SELECT d, d - (row_number() OVER (ORDER BY d))::int AS g FROM days
  ),
  groups AS (
    SELECT g, count(*) AS c, min(d) AS s, max(d) AS e FROM runs GROUP BY g
  ),
  current_streak AS (
    SELECT COALESCE(
      (SELECT c FROM groups WHERE e = (now()::date) OR e = (now()::date - 1)
        ORDER BY e DESC LIMIT 1), 0
    ) AS c
  ),
  longest_streak AS (
    SELECT COALESCE(max(c), 0) AS c FROM groups
  ),
  week_over AS (
    SELECT
      count(*) FILTER (WHERE created_at >= date_trunc('week', now())) AS this_w,
      count(*) FILTER (WHERE created_at >= date_trunc('week', now()) - interval '7 days'
                         AND created_at <  date_trunc('week', now())) AS last_w
      FROM content.workspace_zettels
     WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
  ),
  cap_vs_chat AS (
    SELECT
      (SELECT count(*) FROM content.workspace_zettels
        WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
          AND created_at >= now() - interval '30 days') AS caps,
      (SELECT count(*) FROM rag.chat_messages
        WHERE workspace_id = p_workspace_id AND role = 'user'
          AND created_at >= now() - interval '30 days') AS chats
  )
  SELECT jsonb_build_object(
    'current_streak', (SELECT c FROM current_streak),
    'longest_streak', (SELECT c FROM longest_streak),
    'week_over_week', jsonb_build_object(
      'this_week', (SELECT this_w FROM week_over),
      'last_week', (SELECT last_w FROM week_over),
      'delta_pct', CASE
        WHEN (SELECT last_w FROM week_over) = 0 THEN NULL
        ELSE round(100.0 * ((SELECT this_w FROM week_over) - (SELECT last_w FROM week_over))
                  / (SELECT last_w FROM week_over)::numeric, 1)
      END
    ),
    'chat_vs_capture', jsonb_build_object(
      'captures_30d', (SELECT caps FROM cap_vs_chat),
      'chats_30d', (SELECT chats FROM cap_vs_chat),
      'capture_pct', CASE
        WHEN (SELECT caps + chats FROM cap_vs_chat) = 0 THEN NULL
        ELSE round(100.0 * (SELECT caps FROM cap_vs_chat)
                  / NULLIF((SELECT caps + chats FROM cap_vs_chat),0)::numeric, 1)
      END
    )
  ) INTO v_activity;
```

Add `v_activity jsonb;`. Replace `'activity', '{}'::jsonb,` with `'activity', v_activity,`.

- Commit: `feat: stats RPC Activity section`

### Task 3.7: Knowledge Graph section

- [ ] **Step 1: Add failing test**

```python
async def test_graph_section(asyncpg_pool, mint_user, seed_kg_graph):
    user = await mint_user(email="kg@test.local")
    await seed_kg_graph(user["workspace_id"], nodes=10, edges=15)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT core.profile_stats_v1($1) AS payload", user["workspace_id"])
    g = row["payload"]["graph"]
    assert g["mean_degree"] >= 0
    assert isinstance(g["top_hubs_10"], list)
    assert len(g["top_hubs_10"]) <= 10
    assert g["personal_vs_global_tags"]["user_tag_count"] >= 0
    assert g["personal_vs_global_tags"]["kg_node_count"] >= 0
    assert isinstance(g["relation_type_mix"], list)
```

- [ ] **Step 2: Add `seed_kg_graph` fixture**

```python
@pytest.fixture
def seed_kg_graph(asyncpg_pool):
    async def _seed(workspace_id, nodes: int, edges: int):
        async with asyncpg_pool.acquire() as conn:
            node_ids = []
            for i in range(nodes):
                nid = await conn.fetchval(
                    "INSERT INTO kg.kg_nodes (workspace_id, type, canonical_name, slug) "
                    "VALUES ($1, 'zettel', 'n' || $2, 'n' || $2) RETURNING id",
                    workspace_id, i,
                )
                node_ids.append(nid)
            for i in range(min(edges, nodes - 1)):
                await conn.execute(
                    "INSERT INTO kg.kg_edges (workspace_id, src_node_id, dst_node_id, relation_type, weight, workspace_strength) "
                    "VALUES ($1, $2, $3, 'shared_tag', 1.0, 0.5)",
                    workspace_id, node_ids[i], node_ids[i + 1],
                )
    return _seed
```

- [ ] **Step 3-6: Implement**

```sql
  -- ─── Knowledge Graph ──────────────────────────────────────────────────
  WITH counts AS (
    SELECT
      (SELECT count(*) FROM kg.kg_nodes WHERE workspace_id = p_workspace_id) AS nodes,
      (SELECT count(*) FROM kg.kg_edges WHERE workspace_id = p_workspace_id) AS edges
  ),
  deg AS (
    SELECT node_id, count(*) AS d FROM (
      SELECT src_node_id AS node_id FROM kg.kg_edges WHERE workspace_id = p_workspace_id
      UNION ALL
      SELECT dst_node_id FROM kg.kg_edges WHERE workspace_id = p_workspace_id
    ) e GROUP BY node_id
  ),
  top_hubs AS (
    SELECT n.canonical_name, n.type, deg.d
      FROM deg JOIN kg.kg_nodes n ON n.id = deg.node_id
     ORDER BY deg.d DESC LIMIT 10
  ),
  rel_mix AS (
    SELECT relation_type, count(*) AS n FROM kg.kg_edges
     WHERE workspace_id = p_workspace_id GROUP BY relation_type
  )
  SELECT jsonb_build_object(
    'mean_degree', CASE WHEN (SELECT nodes FROM counts) = 0 THEN 0
                        ELSE round(2.0 * (SELECT edges FROM counts) / (SELECT nodes FROM counts)::numeric, 2) END,
    'top_hubs_10', COALESCE(
      (SELECT jsonb_agg(jsonb_build_object('name', canonical_name, 'type', type, 'degree', d) ORDER BY d DESC)
         FROM top_hubs),
      '[]'::jsonb
    ),
    'personal_vs_global_tags', jsonb_build_object(
      'user_tag_count', (
        SELECT count(DISTINCT t)
          FROM content.workspace_zettels wz, unnest(wz.user_tags) AS t
         WHERE wz.workspace_id = p_workspace_id AND wz.deleted_at IS NULL
      ),
      'kg_node_count', (SELECT nodes FROM counts)
    ),
    'relation_type_mix', COALESCE(
      (SELECT jsonb_agg(jsonb_build_object('relation', relation_type, 'count', n) ORDER BY n DESC) FROM rel_mix),
      '[]'::jsonb
    )
  ) INTO v_graph;
```

Add `v_graph jsonb;`. Replace `'graph', '{}'::jsonb,` with `'graph', v_graph,`.

- Commit: `feat: stats RPC Knowledge Graph section`

### Task 3.8: Tenant isolation & 403 path

- [ ] **Step 1: Add failing test**

```python
async def test_rpc_rejects_unauthorized_workspace(asyncpg_pool, mint_user):
    user_a = await mint_user(email="a@test.local")
    user_b = await mint_user(email="b@test.local")
    # Call as user A but pass user B's workspace
    async with asyncpg_pool.acquire() as conn:
        await conn.execute("SET LOCAL request.jwt.claims = $1",
                           f'{{"sub":"{user_a["profile_id"]}"}}')
        with pytest.raises(Exception, match="workspace not accessible"):
            await conn.fetchrow("SELECT core.profile_stats_v1($1)", user_b["workspace_id"])
```

- [ ] **Step 2-5: The RPC's scope-check block (already in Task 3.0 scaffold) handles this. Run, verify pass, commit.**

If the scope check is the existing scaffold, this test passes immediately — keep it as a regression guard.

```bash
python -m pytest tests/integration/v2/test_profile_stats_rpc.py::test_rpc_rejects_unauthorized_workspace -v
git add tests/integration/v2/test_profile_stats_rpc.py
git commit -m "test: stats RPC cross-tenant denial"
```

---

## Phase 4 — Backend API endpoint

### Task 4.1: Pydantic response models

**Files:**
- Create: `website/features/user_stats/models.py`
- Create: `tests/unit/website/user_stats/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/website/user_stats/test_models.py
from website.features.user_stats.models import StatsResponse, MetaSection


def test_parses_full_payload():
    payload = {
        "meta": {"workspace_id": "00000000-0000-0000-0000-000000000001",
                 "profile_id": "00000000-0000-0000-0000-000000000002",
                 "computed_at": "2026-05-27T10:00:00Z", "schema_version": 1},
        "main_board": {"heatmap": [], "zettels_quota": {"used": 5, "available": 30, "period": "month"},
                       "kastens": {"total": 3, "quota_available": False}},
        "general": {"member_since": {"joined_at": "2026-01-01", "days": 146},
                    "zettels_30d": {"count": 12, "delta_pct": 14.0, "sparkline": []},
                    "kg_size": {"nodes": 50, "edges": 80},
                    "source_diversity": {"used": 5, "max": 13},
                    "plan": {"tier": "free", "period_end": None}},
        "zettel": {"top_source": {"source_type": "youtube", "count": 8, "pct": 53.0},
                   "latest": {"title": "x", "source_type": "web", "created_at": "2026-05-27T09:00:00Z"},
                   "avg_summary_chars": {"mean": 800, "min": 200, "max": 1500},
                   "avg_user_tags": 2.3, "tagged_coverage_pct": 0.75},
        "kasten": {"largest": {"name": "k1", "icon": None, "color": None, "zettel_count": 4,
                               "last_added_at": "2026-05-26T00:00:00Z", "age_days": 30},
                   "avg_conversation_depth": 1.5,
                   "most_cited_source_type": {"source_type": "youtube", "count": 3},
                   "question_streak": {"current": 2, "longest": 5}},
        "domain": {"concentration_hhi": 0.42, "emerging_top5": [], "declining_top5": []},
        "activity": {"current_streak": 3, "longest_streak": 8,
                     "week_over_week": {"this_week": 5, "last_week": 4, "delta_pct": 25.0},
                     "chat_vs_capture": {"captures_30d": 12, "chats_30d": 4, "capture_pct": 75.0}},
        "graph": {"mean_degree": 3.2, "top_hubs_10": [],
                  "personal_vs_global_tags": {"user_tag_count": 18, "kg_node_count": 50},
                  "relation_type_mix": []},
    }
    parsed = StatsResponse.model_validate(payload)
    assert parsed.meta.schema_version == 1
    assert parsed.general.kg_size.nodes == 50
```

- [ ] **Step 2: Run, verify fail (ImportError)**

- [ ] **Step 3: Write models**

```python
# website/features/user_stats/models.py
from __future__ import annotations
from datetime import datetime, date
from typing import Any
from pydantic import BaseModel, Field


class MetaSection(BaseModel):
    workspace_id: str
    profile_id: str
    computed_at: datetime
    schema_version: int


class HeatmapCell(BaseModel):
    date: date
    count: int


class QuotaPie(BaseModel):
    used: int
    available: int
    period: str


class KastensQuotaPie(BaseModel):
    total: int
    used: int | None = None
    available: int | None = None
    period: str | None = None


class KastensPlain(BaseModel):
    total: int
    quota_available: bool = False


class MainBoardSection(BaseModel):
    heatmap: list[HeatmapCell]
    zettels_quota: QuotaPie
    kastens: KastensQuotaPie | KastensPlain


class MemberSince(BaseModel):
    joined_at: datetime | date | None
    days: int


class SparkPoint(BaseModel):
    week: date
    count: int


class Zettels30d(BaseModel):
    count: int
    delta_pct: float | None
    sparkline: list[SparkPoint]


class KgSize(BaseModel):
    nodes: int
    edges: int


class SourceDiversity(BaseModel):
    used: int
    max: int


class Plan(BaseModel):
    tier: str
    period_end: datetime | None


class GeneralSection(BaseModel):
    member_since: MemberSince
    zettels_30d: Zettels30d
    kg_size: KgSize
    source_diversity: SourceDiversity
    plan: Plan


class TopSource(BaseModel):
    source_type: str | None
    count: int
    pct: float | None


class LatestZettel(BaseModel):
    title: str | None
    source_type: str | None
    created_at: datetime | None


class SummaryChars(BaseModel):
    mean: int
    min: int
    max: int


class ZettelSection(BaseModel):
    top_source: TopSource
    latest: LatestZettel
    avg_summary_chars: SummaryChars
    avg_user_tags: float
    tagged_coverage_pct: float


class LargestKasten(BaseModel):
    name: str | None
    icon: str | None
    color: str | None
    zettel_count: int
    last_added_at: datetime | None
    age_days: int | None


class MostCitedSource(BaseModel):
    source_type: str | None
    count: int


class QuestionStreak(BaseModel):
    current: int
    longest: int


class KastenSection(BaseModel):
    largest: LargestKasten
    avg_conversation_depth: float
    most_cited_source_type: MostCitedSource
    question_streak: QuestionStreak


class TagDelta(BaseModel):
    tag: str
    delta_share: float


class DomainSection(BaseModel):
    concentration_hhi: float
    emerging_top5: list[TagDelta]
    declining_top5: list[TagDelta]


class WeekOverWeek(BaseModel):
    this_week: int
    last_week: int
    delta_pct: float | None


class ChatVsCapture(BaseModel):
    captures_30d: int
    chats_30d: int
    capture_pct: float | None


class ActivitySection(BaseModel):
    current_streak: int
    longest_streak: int
    week_over_week: WeekOverWeek
    chat_vs_capture: ChatVsCapture


class HubNode(BaseModel):
    name: str
    type: str
    degree: int


class TagCoverage(BaseModel):
    user_tag_count: int
    kg_node_count: int


class RelationMix(BaseModel):
    relation: str
    count: int


class GraphSection(BaseModel):
    mean_degree: float
    top_hubs_10: list[HubNode]
    personal_vs_global_tags: TagCoverage
    relation_type_mix: list[RelationMix]


class StatsResponse(BaseModel):
    meta: MetaSection
    main_board: MainBoardSection
    general: GeneralSection
    zettel: ZettelSection
    kasten: KastenSection
    domain: DomainSection
    activity: ActivitySection
    graph: GraphSection
```

- [ ] **Step 4: Run, verify pass**

```bash
python -m pytest tests/unit/website/user_stats/test_models.py -v
```

- [ ] **Step 5: Commit**

```bash
git add website/features/user_stats/models.py tests/unit/website/user_stats/test_models.py
git commit -m "feat: stats endpoint Pydantic models"
```

### Task 4.2: In-process LRU cache

**Files:**
- Create: `website/features/user_stats/cache.py`
- Create: `tests/unit/website/user_stats/test_cache.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/website/user_stats/test_cache.py
import asyncio
import pytest
from website.features.user_stats.cache import StatsCache


@pytest.mark.asyncio
async def test_cache_returns_stored_value():
    cache = StatsCache(max_entries=10, ttl_seconds=60)
    await cache.set("ws1", "etag-a", {"x": 1})
    assert await cache.get("ws1", "etag-a") == {"x": 1}


@pytest.mark.asyncio
async def test_cache_misses_on_different_etag():
    cache = StatsCache(max_entries=10, ttl_seconds=60)
    await cache.set("ws1", "etag-a", {"x": 1})
    assert await cache.get("ws1", "etag-b") is None


@pytest.mark.asyncio
async def test_cache_expires_after_ttl():
    cache = StatsCache(max_entries=10, ttl_seconds=0.05)
    await cache.set("ws1", "etag-a", {"x": 1})
    await asyncio.sleep(0.1)
    assert await cache.get("ws1", "etag-a") is None


@pytest.mark.asyncio
async def test_cache_evicts_lru_when_full():
    cache = StatsCache(max_entries=2, ttl_seconds=60)
    await cache.set("ws1", "a", {"x": 1})
    await cache.set("ws2", "a", {"x": 2})
    await cache.get("ws1", "a")  # mark ws1 as MRU
    await cache.set("ws3", "a", {"x": 3})  # should evict ws2
    assert await cache.get("ws2", "a") is None
    assert await cache.get("ws1", "a") == {"x": 1}
    assert await cache.get("ws3", "a") == {"x": 3}
```

- [ ] **Step 2: Run, verify fail**

- [ ] **Step 3: Implement**

```python
# website/features/user_stats/cache.py
from __future__ import annotations
import asyncio
import time
from collections import OrderedDict
from typing import Any


class StatsCache:
    """Per-worker in-process LRU. Keyed by (workspace_id, etag)."""

    def __init__(self, *, max_entries: int = 256, ttl_seconds: float = 60.0) -> None:
        self._max = max_entries
        self._ttl = ttl_seconds
        self._store: OrderedDict[tuple[str, str], tuple[float, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, workspace_id: str, etag: str) -> Any | None:
        key = (workspace_id, etag)
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.monotonic() - ts > self._ttl:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, workspace_id: str, etag: str, value: Any) -> None:
        key = (workspace_id, etag)
        async with self._lock:
            self._store[key] = (time.monotonic(), value)
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)
```

- [ ] **Step 4: Run, verify pass**

- [ ] **Step 5: Commit**

```bash
git add website/features/user_stats/cache.py tests/unit/website/user_stats/test_cache.py
git commit -m "feat: stats endpoint LRU cache"
```

### Task 4.3: Repository (RPC call + cache integration)

**Files:**
- Create: `website/features/user_stats/repository.py`

- [ ] **Step 1: Write the module**

```python
# website/features/user_stats/repository.py
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from website.core.supabase_v2.client import get_v2_client
from website.features.user_stats.cache import StatsCache
from website.features.user_stats.models import StatsResponse

log = logging.getLogger(__name__)
_cache = StatsCache(max_entries=256, ttl_seconds=60.0)


def _compute_etag(workspace_id: str, latest_zettel_at: datetime | None,
                  latest_chat_at: datetime | None) -> str:
    """ETag = stable hash of workspace + the latest mutation timestamps.

    Cheap one-row probe: any new zettel or chat changes the etag, evicting cache.
    """
    parts = [workspace_id,
             latest_zettel_at.isoformat() if latest_zettel_at else "",
             latest_chat_at.isoformat() if latest_chat_at else ""]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


async def fetch_stats(workspace_id: str, profile_id: str) -> tuple[StatsResponse, str, bool]:
    """Returns (response, etag, from_cache).

    Cache hit path: a single 1-row SELECT to compute the etag, then in-process lookup.
    Cache miss path: the full RPC call.
    """
    client = get_v2_client()

    # Probe for ETag: cheapest possible read
    probe = await client.rpc("profile_stats_etag_probe_v1",
                              {"p_workspace_id": workspace_id}).execute()
    latest_zettel = probe.data.get("latest_zettel_at") if probe.data else None
    latest_chat = probe.data.get("latest_chat_at") if probe.data else None
    etag = _compute_etag(workspace_id, latest_zettel, latest_chat)

    cached = await _cache.get(workspace_id, etag)
    if cached is not None:
        return StatsResponse.model_validate(cached), etag, True

    # Cache miss: full RPC
    res = await client.rpc("profile_stats_v1",
                            {"p_workspace_id": workspace_id}).execute()
    payload = res.data
    if payload is None:
        raise RuntimeError("profile_stats_v1 returned no payload")
    parsed = StatsResponse.model_validate(payload)
    await _cache.set(workspace_id, etag, payload)
    return parsed, etag, False
```

⚠ **Implementer note**: This requires an additional tiny RPC `core.profile_stats_etag_probe_v1` (one query: `SELECT max(created_at) FROM workspace_zettels` + same from chat_messages). Add it as part of migration 81 (one extra function block), OR define it as a v1.1 micro-migration. Choose based on planner output — recommended: add to 81 since they're paired.

Add to migration 81:

```sql
CREATE OR REPLACE FUNCTION core.profile_stats_etag_probe_v1(p_workspace_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  SET LOCAL statement_timeout = '5s';
  IF NOT EXISTS (
    SELECT 1 FROM core.workspace_members
     WHERE workspace_id = p_workspace_id AND profile_id = auth.uid()
  ) THEN
    RAISE EXCEPTION 'workspace not accessible' USING ERRCODE = '42501';
  END IF;
  RETURN jsonb_build_object(
    'latest_zettel_at', (SELECT max(created_at) FROM content.workspace_zettels
                          WHERE workspace_id = p_workspace_id AND deleted_at IS NULL),
    'latest_chat_at',   (SELECT max(created_at) FROM rag.chat_messages
                          WHERE workspace_id = p_workspace_id)
  );
END;
$$;

REVOKE ALL ON FUNCTION core.profile_stats_etag_probe_v1(uuid) FROM public;
GRANT EXECUTE ON FUNCTION core.profile_stats_etag_probe_v1(uuid) TO authenticated, stats_reader, service_role;
```

- [ ] **Step 2: Apply the updated migration**

```bash
psql "$STAGING_DATABASE_URL" -f supabase/website/_v2/81_profile_stats_v1_rpc.sql
```

- [ ] **Step 3: Commit**

```bash
git add website/features/user_stats/repository.py supabase/website/_v2/81_profile_stats_v1_rpc.sql
git commit -m "feat: stats repository + ETag probe RPC"
```

### Task 4.4: FastAPI router

**Files:**
- Create: `website/features/user_stats/router.py`
- Modify: `website/app.py`

- [ ] **Step 1: Write the router**

```python
# website/features/user_stats/router.py
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from website.api.auth import get_current_user  # existing dep — confirm exact path in Phase 0
from website.features.user_stats.repository import fetch_stats
from website.features.user_stats.semaphore import SemaphoreFullError, StatsSemaphore

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile-stats"])
_semaphore = StatsSemaphore(max_concurrent=1, max_queued=2)


@router.get("/stats")
async def get_profile_stats(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
) -> dict:
    """GET /api/profile/stats — single payload for the Statistics tab.

    Safety: per-worker semaphore (1 in-flight, 2 queued, 503 above).
    Caching: in-process LRU keyed by (workspace_id, etag). ETag derived from
    max(workspace_zettels.updated_at, chat_messages.created_at).
    """
    if_none_match = request.headers.get("if-none-match")
    try:
        async with _semaphore.acquire():
            parsed, etag, from_cache = await fetch_stats(
                workspace_id=user.workspace_id,
                profile_id=user.profile_id,
            )
    except SemaphoreFullError:
        response.headers["retry-after"] = "5"
        raise HTTPException(status_code=503, detail="stats endpoint busy")

    response.headers["etag"] = etag
    response.headers["cache-control"] = "private, max-age=60"
    response.headers["x-stats-cache"] = "hit" if from_cache else "miss"

    if if_none_match == etag:
        return Response(status_code=304)
    return parsed.model_dump(mode="json")
```

- [ ] **Step 2: Register in `website/app.py`**

Find the section where other routers are included (search for `app.include_router`). Add:

```python
from website.features.user_stats.router import router as user_stats_router
app.include_router(user_stats_router)
```

- [ ] **Step 3: Commit**

```bash
git add website/features/user_stats/router.py website/app.py
git commit -m "feat: stats endpoint route registration"
```

### Task 4.5: Endpoint integration test

**Files:**
- Create: `tests/integration/v2/test_profile_stats_endpoint.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/v2/test_profile_stats_endpoint.py
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_endpoint_returns_full_payload(authed_client: AsyncClient, mint_user, seed_zettels):
    user = await mint_user(email="ep@test.local")
    await seed_zettels(user["workspace_id"], count=5)
    r = await authed_client.get("/api/profile/stats")
    assert r.status_code == 200
    body = r.json()
    assert "main_board" in body and "general" in body and "graph" in body
    assert "etag" in {k.lower() for k in r.headers}


async def test_endpoint_cache_hit_returns_304(authed_client: AsyncClient, mint_user, seed_zettels):
    user = await mint_user(email="ep2@test.local")
    await seed_zettels(user["workspace_id"], count=3)
    r1 = await authed_client.get("/api/profile/stats")
    etag = r1.headers["etag"]
    r2 = await authed_client.get("/api/profile/stats", headers={"if-none-match": etag})
    assert r2.status_code == 304


async def test_endpoint_503_when_semaphore_full(authed_client: AsyncClient, mint_user):
    user = await mint_user(email="ep3@test.local")
    # Saturate the semaphore by hammering — best-effort smoke (loop-based)
    # ... (skip if not feasible in CI) — see comment below
    pytest.skip("semaphore saturation requires concurrent client harness, run manually")
```

- [ ] **Step 2-5: Run, verify pass, commit**

```bash
python -m pytest tests/integration/v2/test_profile_stats_endpoint.py -v
git add tests/integration/v2/test_profile_stats_endpoint.py
git commit -m "test: stats endpoint integration"
```

---

## Phase 5 — Frontend Statistics Tab

### Task 5.1: HTML tab structure + skeletons

**Files:**
- Modify: `website/features/user_profile/index.html`

- [ ] **Step 1: Find the spot in the existing layout where the Statistics tab should land — likely below the identity hero, replacing the existing 4-stat-card row.**

- [ ] **Step 2: Add the loading box + tab nav + 7 tab panels.** Replace the existing 4 stat cards with the structure below.

Key layout decisions (locked 2026-05-27):
- The **loading box** sits ABOVE the stats panels (i.e., between the profile-avatar identity section and the stats grid). When a fresh fetch is in flight, the loading box is visible and the (cached) stats panels render below it. On fetch completion, the loading box fades out and the new stats slide up into its slot — old cached panels are then hot-swapped to new data and the loading box is removed from the flow.
- The `[data-stats-cache-state]` attribute on `.profile-stats` is the controller's state machine: `empty | stale-from-cache | loading-fresh | live`.
- Mobile UI is UNCHANGED — desktop `/profile` only (mobile redirects to `/m/` per `website/app.py` UA detector).

```html
<section class="profile-stats" data-profile-stats data-stats-cache-state="empty" aria-busy="true">
  <!-- LOADING BOX (controller toggles .is-visible). Lives ABOVE the tabs. -->
  <div class="profile-stats-loader" data-stats-loader hidden>
    <div class="profile-stats-loader__row">
      <span class="profile-stats-loader__type" data-stats-loader-type></span>
      <button type="button" class="profile-stats-loader__stop" data-stats-loader-stop aria-label="Stop loading">
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="3" y="3" width="10" height="10" rx="1.5" fill="currentColor"/></svg>
      </button>
    </div>
    <div class="profile-stats-loader__progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" data-stats-loader-progress>
      <span class="profile-stats-loader__bar" data-stats-loader-bar></span>
    </div>
  </div>

  <nav class="profile-stats-tabs" role="tablist" aria-label="Statistics sections">
    <button type="button" class="profile-stats-tab is-active" role="tab" aria-selected="true" data-stats-tab="main">Main Board</button>
    <button type="button" class="profile-stats-tab" role="tab" aria-selected="false" data-stats-tab="general">General</button>
    <button type="button" class="profile-stats-tab" role="tab" aria-selected="false" data-stats-tab="zettel">Zettel</button>
    <button type="button" class="profile-stats-tab" role="tab" aria-selected="false" data-stats-tab="kasten">Kasten</button>
    <button type="button" class="profile-stats-tab" role="tab" aria-selected="false" data-stats-tab="domain">Domain</button>
    <button type="button" class="profile-stats-tab" role="tab" aria-selected="false" data-stats-tab="activity">Activity</button>
    <button type="button" class="profile-stats-tab" role="tab" aria-selected="false" data-stats-tab="graph">Knowledge Graph</button>
  </nav>

  <div class="profile-stats-panels" data-stats-panels>
    <div class="profile-stats-panel is-active" role="tabpanel" data-stats-panel="main">
      <div class="profile-stats-grid">
        <article class="stats-card stats-card--heatmap" data-stat="main.heatmap"><div class="stats-skeleton stats-skeleton--heatmap"></div></article>
        <article class="stats-card stats-card--pie" data-stat="main.zettels_quota"><div class="stats-skeleton stats-skeleton--pie"></div></article>
        <article class="stats-card stats-card--pie" data-stat="main.kastens"><div class="stats-skeleton stats-skeleton--pie"></div></article>
      </div>
    </div>

    <div class="profile-stats-panel" role="tabpanel" data-stats-panel="general" hidden>
      <div class="profile-stats-grid">
        <article class="stats-card" data-stat="general.member_since"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="general.zettels_30d"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="general.kg_size"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="general.source_diversity"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="general.plan"><div class="stats-skeleton"></div></article>
      </div>
    </div>

    <div class="profile-stats-panel" role="tabpanel" data-stats-panel="zettel" hidden>
      <div class="profile-stats-grid">
        <article class="stats-card" data-stat="zettel.top_latest"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="zettel.avg_summary"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="zettel.avg_tags"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="zettel.tagged_coverage"><div class="stats-skeleton"></div></article>
      </div>
    </div>

    <div class="profile-stats-panel" role="tabpanel" data-stats-panel="kasten" hidden>
      <div class="profile-stats-grid">
        <article class="stats-card" data-stat="kasten.largest"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="kasten.avg_conversation_depth"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="kasten.most_cited_source"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="kasten.question_streak"><div class="stats-skeleton"></div></article>
      </div>
    </div>

    <div class="profile-stats-panel" role="tabpanel" data-stats-panel="domain" hidden>
      <div class="profile-stats-grid">
        <article class="stats-card" data-stat="domain.concentration"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="domain.emerging"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="domain.declining"><div class="stats-skeleton"></div></article>
      </div>
    </div>

    <div class="profile-stats-panel" role="tabpanel" data-stats-panel="activity" hidden>
      <div class="profile-stats-grid">
        <article class="stats-card" data-stat="activity.current_streak"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="activity.longest_streak"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="activity.week_over_week"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="activity.chat_vs_capture"><div class="stats-skeleton"></div></article>
      </div>
    </div>

    <div class="profile-stats-panel" role="tabpanel" data-stats-panel="graph" hidden>
      <div class="profile-stats-grid">
        <article class="stats-card" data-stat="graph.mean_degree"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="graph.top_hubs"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="graph.tag_coverage"><div class="stats-skeleton"></div></article>
        <article class="stats-card" data-stat="graph.relation_mix"><div class="stats-skeleton"></div></article>
      </div>
    </div>
  </div>
</section>
```

Also add the typewriter script tag (idempotent — if it's already included site-wide via shared header, skip):

```html
<script src="/static/js/zk_skeleton_typewriter.js?v=20260527a" defer></script>
```

- [ ] **Step 3: Bump CSS/JS asset query versions**

Find `?v=20260526f` etc. in `<link>` and `<script>` tags. Bump to `?v=20260527a` (or current date suffix).

- [ ] **Step 4: Commit**

```bash
git add website/features/user_profile/index.html
git commit -m "feat: profile statistics tab HTML scaffold"
```

### Task 5.2: CSS for tabs, grid, cards, skeletons

**Files:**
- Modify: `website/features/user_profile/css/user_profile.css`

- [ ] **Step 1: Append (do NOT introduce new color tokens; use existing `--bg-card`, `--accent`, `--text-primary`, etc.)**

```css
/* ─── Statistics tab ─────────────────────────────────────────── */
.profile-stats {
  margin-top: 2rem;
}

.profile-stats-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: 1.5rem;
  overflow-x: auto;
}

.profile-stats-tab {
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  padding: 0.75rem 1rem;
  font: inherit;
  color: var(--text-muted);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.profile-stats-tab:hover { color: var(--text-primary); }
.profile-stats-tab.is-active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.profile-stats-tab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.profile-stats-panel { display: none; }
.profile-stats-panel.is-active { display: block; }

.profile-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}

.stats-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 1rem;
  min-height: 120px;
  display: flex;
  flex-direction: column;
}

.stats-card--heatmap { grid-column: 1 / -1; }
.stats-card--pie { min-height: 220px; }

/* Skeleton shimmer (no purple — use neutral shimmer) */
.stats-skeleton {
  background: linear-gradient(90deg, var(--bg-elevated) 0%, var(--bg-card) 50%, var(--bg-elevated) 100%);
  background-size: 200% 100%;
  animation: stats-shimmer 1.4s ease-in-out infinite;
  border-radius: 0.25rem;
  flex: 1;
  min-height: 60px;
}

.stats-skeleton--heatmap { min-height: 120px; }
.stats-skeleton--pie { min-height: 180px; border-radius: 50%; aspect-ratio: 1; max-width: 180px; margin: auto; }

@keyframes stats-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Pie chart container (SVG injected by JS) */
.stats-pie {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
}
.stats-pie__svg { width: 160px; height: 160px; }
.stats-pie__label {
  text-align: center;
  font-size: 0.875rem;
  color: var(--text-muted);
}

/* Cache freshness chip */
.stats-freshness {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-left: auto;
}

/* ─── Loading box (above tabs; pushes cached panels below) ─── */
.profile-stats-loader {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 1rem 1.25rem;
  margin-bottom: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  /* Square-ish box, never wider than the grid */
  max-width: 100%;
  /* Reserved height so the layout doesn't jump when visible */
  min-height: 84px;

  opacity: 0;
  transform: translateY(-4px);
  transition: opacity 0.22s ease, transform 0.22s ease, max-height 0.32s ease, margin 0.32s ease, padding 0.32s ease;
  max-height: 0;
  overflow: hidden;
  pointer-events: none;
  padding-top: 0;
  padding-bottom: 0;
  margin-bottom: 0;
}
.profile-stats-loader.is-visible {
  opacity: 1;
  transform: translateY(0);
  max-height: 200px;
  padding: 1rem 1.25rem;
  margin-bottom: 1.25rem;
  pointer-events: auto;
}

.profile-stats-loader__row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.profile-stats-loader__type {
  /* The ZKSkeletonTyper attaches its own mono-styled <span> inside; this is
     just the container. Padding ensures it sits centered with the stop button. */
  flex: 1;
  min-height: 1.2em;
}

.profile-stats-loader__stop {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: 0.25rem;
  padding: 0.25rem 0.4rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}
.profile-stats-loader__stop:hover {
  color: var(--text-primary);
  border-color: var(--accent);
  background: var(--bg-elevated);
}
.profile-stats-loader__stop:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.profile-stats-loader__progress {
  background: var(--bg-elevated);
  border-radius: 999px;
  height: 4px;
  overflow: hidden;
}

.profile-stats-loader__bar {
  display: block;
  height: 100%;
  width: 0%;
  background: var(--accent);
  /* Default transition; JS overrides duration for the 90→100 burst */
  transition: width 0.1s linear;
  will-change: width;
}

/* Cached-data soft staleness cue */
.profile-stats[data-stats-cache-state="stale-from-cache"] .profile-stats-panels,
.profile-stats[data-stats-cache-state="loading-fresh"] .profile-stats-panels {
  opacity: 0.92;
}

/* Slide-in transition when new payload replaces stale */
.profile-stats-panels {
  transition: opacity 0.2s ease, transform 0.25s ease;
}
.profile-stats-panels.is-swapping-in {
  opacity: 0;
  transform: translateY(6px);
}

/* Cancelled-update hint (fades after a few seconds via JS) */
.profile-stats-cancel-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 0.5rem;
  opacity: 0;
  transition: opacity 0.2s ease;
}
.profile-stats-cancel-hint.is-visible { opacity: 1; }

/* Reduced-motion: kill the slide; keep opacity */
@media (prefers-reduced-motion: reduce) {
  .profile-stats-loader,
  .profile-stats-panels,
  .profile-stats-loader__bar {
    transition: opacity 0.15s ease !important;
    transform: none !important;
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add website/features/user_profile/css/user_profile.css
git commit -m "feat: profile statistics tab CSS"
```

### Task 5.3: JS tab switching + initial fetch

**Files:**
- Modify: `website/features/user_profile/js/user_profile.js`

- [ ] **Step 1: Add the controller (append after existing IIFE blocks)**

Implements the locked UX (2026-05-27):
1. On page open, render cached stats immediately (no skeleton flash if cache exists).
2. Loading box appears above the stats panels with a progress bar (0→80 linear, 80→90 slow, 90→100 only when fetch completes) + a stop button + the `ZKSkeletonTyper` line.
3. Cached payload stays visible (slightly dimmed) underneath the loading box throughout the fetch.
4. On completion, the loading box collapses and the stats panels hot-swap to the new data with a soft slide.
5. On `Stop`, the fetch aborts via `AbortController`; the cache stays as-is; a brief "Update cancelled — showing cached data" hint appears.
6. On 304 Not Modified, the loading box completes its progress sweep to 100% and collapses; no data swap (cache was already current).

```javascript
// ─── Statistics tab controller ──────────────────────────────────
(function initProfileStats() {
  const root = document.querySelector('[data-profile-stats]');
  if (!root) return;

  // ----- DOM handles -----
  const tabs = Array.from(root.querySelectorAll('[data-stats-tab]'));
  const panels = Array.from(root.querySelectorAll('[data-stats-panel]'));
  const panelsWrap = root.querySelector('[data-stats-panels]');
  const loader = root.querySelector('[data-stats-loader]');
  const loaderType = root.querySelector('[data-stats-loader-type]');
  const loaderBar = root.querySelector('[data-stats-loader-bar]');
  const loaderProgressEl = root.querySelector('[data-stats-loader-progress]');
  const loaderStop = root.querySelector('[data-stats-loader-stop]');

  // ----- Tab switching (purely visual, no fetch) -----
  function showTab(name) {
    tabs.forEach(t => {
      const active = t.dataset.statsTab === name;
      t.classList.toggle('is-active', active);
      t.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    panels.forEach(p => {
      const active = p.dataset.statsPanel === name;
      p.classList.toggle('is-active', active);
      if (active) p.removeAttribute('hidden'); else p.setAttribute('hidden', '');
    });
  }
  tabs.forEach(t => t.addEventListener('click', () => showTab(t.dataset.statsTab)));

  // ----- Cache helpers (delegated to Task 5.8 module ZKStatsCache) -----
  // Loaded from website/static/js/zk_stats_cache.js — see Task 5.8.
  const cache = window.ZKStatsCache;
  if (!cache) {
    console.warn('ZKStatsCache module missing; stats will fetch every load');
  }

  // ----- Loading-box controller -----
  let progressRaf = 0;
  let progressStart = 0;
  let typer = null;
  let abortCtrl = null;
  const PROGRESS_SCHEDULE = {
    fastDurationMs: 3000,   // 0 → 80
    slowDurationMs: 5000,   // 80 → 90
    burstDurationMs: 400,   // 90 → 100 on success
  };

  function setProgress(pct) {
    const clamped = Math.max(0, Math.min(100, pct));
    loaderBar.style.width = clamped + '%';
    loaderProgressEl.setAttribute('aria-valuenow', String(Math.round(clamped)));
  }

  function startProgressSimulator() {
    cancelAnimationFrame(progressRaf);
    progressStart = performance.now();
    loaderBar.style.transition = 'width 0.12s linear';
    const tick = () => {
      const t = performance.now() - progressStart;
      let p;
      if (t < PROGRESS_SCHEDULE.fastDurationMs) {
        p = (t / PROGRESS_SCHEDULE.fastDurationMs) * 80;
      } else if (t < PROGRESS_SCHEDULE.fastDurationMs + PROGRESS_SCHEDULE.slowDurationMs) {
        const slowT = t - PROGRESS_SCHEDULE.fastDurationMs;
        p = 80 + (slowT / PROGRESS_SCHEDULE.slowDurationMs) * 10;
      } else {
        p = 90;
      }
      setProgress(p);
      if (p < 90) progressRaf = requestAnimationFrame(tick);
    };
    progressRaf = requestAnimationFrame(tick);
  }

  function finishProgress() {
    cancelAnimationFrame(progressRaf);
    return new Promise(resolve => {
      loaderBar.style.transition = `width ${PROGRESS_SCHEDULE.burstDurationMs}ms ease-out`;
      // Force reflow so the new transition applies before we set width
      void loaderBar.offsetWidth;
      setProgress(100);
      setTimeout(resolve, PROGRESS_SCHEDULE.burstDurationMs + 30);
    });
  }

  function showLoader() {
    loader.hidden = false;
    // Force reflow so the .is-visible transition fires
    void loader.offsetWidth;
    loader.classList.add('is-visible');
    if (window.ZKSkeletonTyper && !typer) {
      typer = ZKSkeletonTyper.attach(loaderType, { initialPhase: 'queued' });
    }
    startProgressSimulator();
    // Phase ticker for typewriter copy variety
    setTimeout(() => typer && typer.update({ phase: 'running', elapsedMs: 3000 }), 3000);
    setTimeout(() => typer && typer.update({ phase: 'long', elapsedMs: 8000 }), 8000);
  }

  async function hideLoader(finalPhase) {
    if (typer) {
      try { typer.update({ phase: finalPhase || 'succeeded', elapsedMs: performance.now() - progressStart }); } catch (_) {}
    }
    loader.classList.remove('is-visible');
    // Wait for collapse transition to complete before unmounting typer
    await new Promise(r => setTimeout(r, 340));
    if (typer) { try { typer.detach(); } catch (_) {} typer = null; }
    loader.hidden = true;
    setProgress(0);
  }

  function showCancelHint() {
    let hint = root.querySelector('.profile-stats-cancel-hint');
    if (!hint) {
      hint = document.createElement('p');
      hint.className = 'profile-stats-cancel-hint';
      hint.textContent = 'Update cancelled — showing cached data.';
      loader.parentNode.insertBefore(hint, loader.nextSibling);
    }
    void hint.offsetWidth;
    hint.classList.add('is-visible');
    setTimeout(() => hint.classList.remove('is-visible'), 4000);
  }

  // ----- Swap cached → fresh with slide transition -----
  async function swapInFresh(payload) {
    panelsWrap.classList.add('is-swapping-in');
    await new Promise(r => setTimeout(r, 200));
    renderAll(payload);
    panelsWrap.classList.remove('is-swapping-in');
  }

  function renderAll(payload) {
    renderMainBoard(payload.main_board);
    renderGeneral(payload.general);
    renderZettel(payload.zettel);
    renderKasten(payload.kasten);
    renderDomain(payload.domain);
    renderActivity(payload.activity);
    renderGraph(payload.graph);
  }

  // ----- Main flow -----
  async function init() {
    // 1. Cache-first render (no skeleton if cache hit)
    const cached = cache ? await cache.read() : null;
    if (cached && cached.payload) {
      renderAll(cached.payload);
      root.dataset.statsCacheState = 'stale-from-cache';
      root.setAttribute('aria-busy', 'false');
    } else {
      root.dataset.statsCacheState = 'empty';
    }

    // 2. Always re-fetch in the background to refresh
    await fetchAndUpdate(cached ? cached.etag : null);
  }

  async function fetchAndUpdate(cachedEtag) {
    abortCtrl = new AbortController();
    root.dataset.statsCacheState = 'loading-fresh';
    showLoader();

    const headers = {};
    if (cachedEtag) headers['if-none-match'] = cachedEtag;

    let resp;
    try {
      resp = await zkFetch('/api/profile/stats', {
        headers,
        signal: abortCtrl.signal,
      });
    } catch (err) {
      if (err && err.name === 'AbortError') {
        await hideLoader('failed');
        showCancelHint();
        root.dataset.statsCacheState = cachedEtag ? 'stale-from-cache' : 'empty';
        return;
      }
      console.warn('stats fetch failed', err);
      await hideLoader('failed');
      root.dataset.statsCacheState = cachedEtag ? 'stale-from-cache' : 'empty';
      return;
    }

    if (resp.status === 304) {
      // Cache is current; finish progress then collapse, no data swap
      await finishProgress();
      await hideLoader('succeeded');
      root.dataset.statsCacheState = 'live';
      return;
    }

    if (!resp.ok) {
      await hideLoader('failed');
      root.dataset.statsCacheState = cachedEtag ? 'stale-from-cache' : 'empty';
      return;
    }

    const payload = await resp.json();
    const etag = resp.headers.get('etag') || '';
    if (cache && etag) await cache.write(etag, payload);

    await finishProgress();
    await hideLoader('succeeded');
    await swapInFresh(payload);
    root.dataset.statsCacheState = 'live';
    root.setAttribute('aria-busy', 'false');
  }

  loaderStop.addEventListener('click', () => {
    if (abortCtrl) abortCtrl.abort();
  });

  // Renderers (Tasks 5.4-5.6 fill each in)
  function renderMainBoard(s) { /* Task 5.4 */ }
  function renderGeneral(s) { /* Task 5.5 */ }
  function renderZettel(s) { /* Task 5.5 */ }
  function renderKasten(s) { /* Task 5.5 */ }
  function renderDomain(s) { /* Task 5.6 */ }
  function renderActivity(s) { /* Task 5.6 */ }
  function renderGraph(s) { /* Task 5.6 */ }

  init();
})();
```

- [ ] **Step 2: Commit**

```bash
git add website/features/user_profile/js/user_profile.js
git commit -m "feat: profile stats tab controller with cache-first + abortable progress"
```

### Task 5.4: Main Board renderer (heatmap reuse + pies)

**Files:**
- Modify: `website/features/user_profile/js/user_profile.js`

- [ ] **Step 1: Implement `renderMainBoard`**

```javascript
function renderMainBoard(s) {
  // 1.1 Heatmap: reuse the existing 26-week renderer if present; otherwise
  // render server-provided cells.
  const heatmapSlot = root.querySelector('[data-stat="main.heatmap"]');
  if (heatmapSlot && Array.isArray(s.heatmap)) {
    heatmapSlot.innerHTML = '';
    const grid = document.createElement('div');
    grid.className = 'activity-heatmap';
    // Group by week column (7 rows × N cols)
    const cells = s.heatmap.slice(-182); // last 26 weeks
    cells.forEach(c => {
      const cell = document.createElement('span');
      const lvl = c.count === 0 ? 0 : Math.min(4, Math.ceil(Math.log2(c.count + 1)));
      cell.className = `activity-heatmap__cell l${lvl}`;
      cell.title = `${c.date}: ${c.count}`;
      grid.appendChild(cell);
    });
    heatmapSlot.appendChild(grid);
  }

  // 1.2 Zettels pie
  const zSlot = root.querySelector('[data-stat="main.zettels_quota"]');
  if (zSlot && s.zettels_quota) {
    zSlot.innerHTML = renderPie('Zettels this month',
                                 s.zettels_quota.used,
                                 s.zettels_quota.available);
  }

  // 1.3 Kastens pie OR plain count
  const kSlot = root.querySelector('[data-stat="main.kastens"]');
  if (kSlot && s.kastens) {
    if (s.kastens.quota_available === false) {
      kSlot.innerHTML = `
        <div class="stats-pie">
          <span class="stats-big-number">${s.kastens.total}</span>
          <span class="stats-pie__label">Total Kastens</span>
        </div>
      `;
    } else {
      kSlot.innerHTML = renderPie('Kastens this month',
                                   s.kastens.used,
                                   s.kastens.available);
    }
  }
}

function renderPie(label, used, available) {
  const total = used + available;
  const pct = total > 0 ? (used / total) : 0;
  // Compute SVG arc for used segment
  const r = 60;
  const c = 2 * Math.PI * r;
  const dash = pct * c;
  return `
    <div class="stats-pie">
      <svg class="stats-pie__svg" viewBox="0 0 160 160">
        <circle cx="80" cy="80" r="${r}" fill="none" stroke="var(--bg-elevated)" stroke-width="20"/>
        <circle cx="80" cy="80" r="${r}" fill="none" stroke="var(--accent)" stroke-width="20"
                stroke-dasharray="${dash} ${c - dash}" stroke-dashoffset="${c / 4}"
                transform="rotate(-90 80 80)"/>
        <text x="80" y="85" text-anchor="middle" fill="var(--text-primary)" font-size="20" font-weight="600">
          ${used} / ${total}
        </text>
      </svg>
      <span class="stats-pie__label">${label}</span>
    </div>
  `;
}
```

- [ ] **Step 2: Commit**

```bash
git add website/features/user_profile/js/user_profile.js
git commit -m "feat: stats Main Board renderer"
```

### Task 5.5: General + Zettel + Kasten renderers

- [ ] **Step 1: Implement all three (compact, no extra dependencies)**

```javascript
function fmtRelative(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const h = diff / 3.6e6;
  if (h < 1) return `${Math.max(1, Math.round(diff / 6e4))}m ago`;
  if (h < 24) return `${Math.round(h)}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function tile(slot, html) {
  const el = root.querySelector(`[data-stat="${slot}"]`);
  if (el) el.innerHTML = html;
}

function renderGeneral(s) {
  tile('general.member_since', `
    <h3 class="stats-card__label">Member Since</h3>
    <span class="stats-big-number">${s.member_since.days}d</span>
    <span class="stats-card__sub">Joined ${new Date(s.member_since.joined_at).toLocaleDateString()}</span>
  `);
  tile('general.zettels_30d', `
    <h3 class="stats-card__label">Last 30 days</h3>
    <span class="stats-big-number">${s.zettels_30d.count}</span>
    <span class="stats-card__sub">${s.zettels_30d.delta_pct === null ? '—' : (s.zettels_30d.delta_pct >= 0 ? '+' : '') + s.zettels_30d.delta_pct + '%'} vs prior 30d</span>
  `);
  tile('general.kg_size', `
    <h3 class="stats-card__label">Knowledge Graph</h3>
    <span class="stats-big-number">${s.kg_size.nodes}</span>
    <span class="stats-card__sub">${s.kg_size.edges} links</span>
  `);
  tile('general.source_diversity', `
    <h3 class="stats-card__label">Source Diversity</h3>
    <span class="stats-big-number">${s.source_diversity.used} / ${s.source_diversity.max}</span>
  `);
  tile('general.plan', `
    <h3 class="stats-card__label">Plan</h3>
    <span class="stats-big-number">${s.plan.tier}</span>
    <span class="stats-card__sub">${s.plan.period_end ? 'Renews ' + new Date(s.plan.period_end).toLocaleDateString() : ''}</span>
  `);
}

function renderZettel(s) {
  tile('zettel.top_latest', `
    <h3 class="stats-card__label">Top source · Latest capture</h3>
    <span class="stats-big-number">${s.top_source.source_type || '—'} (${s.top_source.pct || 0}%)</span>
    <span class="stats-card__sub">Latest: ${s.latest.title ? s.latest.title.slice(0, 40) : '—'} · ${fmtRelative(s.latest.created_at)}</span>
  `);
  tile('zettel.avg_summary', `
    <h3 class="stats-card__label">Avg summary length</h3>
    <span class="stats-big-number">${s.avg_summary_chars.mean} chars</span>
    <span class="stats-card__sub">range ${s.avg_summary_chars.min}–${s.avg_summary_chars.max}</span>
  `);
  tile('zettel.avg_tags', `
    <h3 class="stats-card__label">Avg user tags / zettel</h3>
    <span class="stats-big-number">${s.avg_user_tags}</span>
  `);
  tile('zettel.tagged_coverage', `
    <h3 class="stats-card__label">Tagged coverage</h3>
    <span class="stats-big-number">${Math.round(s.tagged_coverage_pct * 100)}%</span>
  `);
}

function renderKasten(s) {
  tile('kasten.largest', `
    <h3 class="stats-card__label">Largest Kasten</h3>
    <span class="stats-big-number">${s.largest.name || '—'}</span>
    <span class="stats-card__sub">${s.largest.zettel_count} zettels · last add ${fmtRelative(s.largest.last_added_at)} · age ${s.largest.age_days || 0}d</span>
  `);
  tile('kasten.avg_conversation_depth', `
    <h3 class="stats-card__label">Avg conversation depth</h3>
    <span class="stats-big-number">${s.avg_conversation_depth}</span>
    <span class="stats-card__sub">turns per session</span>
  `);
  tile('kasten.most_cited_source', `
    <h3 class="stats-card__label">Most-cited source</h3>
    <span class="stats-big-number">${s.most_cited_source_type.source_type || '—'}</span>
    <span class="stats-card__sub">${s.most_cited_source_type.count} citations</span>
  `);
  tile('kasten.question_streak', `
    <h3 class="stats-card__label">Question streak</h3>
    <span class="stats-big-number">${s.question_streak.current}🔥</span>
    <span class="stats-card__sub">longest ${s.question_streak.longest}</span>
  `);
}
```

(Implementer ensures the HTML slots in Task 5.1 match these `data-stat="..."` keys; e.g., `zettel.top_latest` is the merged card.)

- [ ] **Step 2: Commit**

```bash
git add website/features/user_profile/js/user_profile.js website/features/user_profile/index.html
git commit -m "feat: stats General+Zettel+Kasten renderers"
```

### Task 5.6: Domain + Activity + Graph renderers

- [ ] **Step 1: Implement**

```javascript
function renderDomain(s) {
  const band = s.concentration_hhi < 0.15 ? 'Polymath' :
               s.concentration_hhi < 0.30 ? 'Balanced' :
               s.concentration_hhi < 0.50 ? 'Focused' : 'Specialist';
  tile('domain.concentration', `
    <h3 class="stats-card__label">Topic concentration</h3>
    <span class="stats-big-number">${s.concentration_hhi.toFixed(2)}</span>
    <span class="stats-card__sub">${band}</span>
  `);
  tile('domain.emerging', `
    <h3 class="stats-card__label">Emerging (last 30d)</h3>
    <ul class="stats-list">
      ${s.emerging_top5.map(t => `<li>${t.tag} <span class="stats-delta-up">+${(t.delta_share * 100).toFixed(1)}%</span></li>`).join('') || '<li class="stats-empty">no trends yet</li>'}
    </ul>
  `);
  tile('domain.declining', `
    <h3 class="stats-card__label">Declining (last 90d)</h3>
    <ul class="stats-list">
      ${s.declining_top5.map(t => `<li>${t.tag} <span class="stats-delta-down">${(t.delta_share * 100).toFixed(1)}%</span></li>`).join('') || '<li class="stats-empty">no decliners</li>'}
    </ul>
  `);
}

function renderActivity(s) {
  tile('activity.current_streak', `
    <h3 class="stats-card__label">Current streak</h3>
    <span class="stats-big-number">${s.current_streak}🔥</span>
  `);
  tile('activity.longest_streak', `
    <h3 class="stats-card__label">Longest streak</h3>
    <span class="stats-big-number">${s.longest_streak}</span>
  `);
  tile('activity.week_over_week', `
    <h3 class="stats-card__label">Week over week</h3>
    <span class="stats-big-number">${s.week_over_week.this_week}</span>
    <span class="stats-card__sub">last week ${s.week_over_week.last_week} · ${s.week_over_week.delta_pct === null ? '—' : (s.week_over_week.delta_pct >= 0 ? '+' : '') + s.week_over_week.delta_pct + '%'}</span>
  `);
  tile('activity.chat_vs_capture', `
    <h3 class="stats-card__label">Capture vs Chat (30d)</h3>
    <span class="stats-big-number">${s.chat_vs_capture.captures_30d} / ${s.chat_vs_capture.chats_30d}</span>
    <span class="stats-card__sub">${s.chat_vs_capture.capture_pct === null ? '—' : s.chat_vs_capture.capture_pct + '% capture'}</span>
  `);
}

function renderGraph(s) {
  tile('graph.mean_degree', `
    <h3 class="stats-card__label">Mean degree</h3>
    <span class="stats-big-number">${s.mean_degree}</span>
    <span class="stats-card__sub">avg connections / node</span>
  `);
  tile('graph.top_hubs', `
    <h3 class="stats-card__label">Top 10 hubs</h3>
    <ul class="stats-list">
      ${s.top_hubs_10.slice(0, 10).map(h => `<li>${h.name} <span class="stats-meta">${h.degree}</span></li>`).join('') || '<li class="stats-empty">graph still empty</li>'}
    </ul>
  `);
  tile('graph.tag_coverage', `
    <h3 class="stats-card__label">Personal vs Global tags</h3>
    <span class="stats-big-number">${s.personal_vs_global_tags.user_tag_count} / ${s.personal_vs_global_tags.kg_node_count}</span>
    <span class="stats-card__sub">your tags vs AI nodes</span>
  `);
  tile('graph.relation_mix', `
    <h3 class="stats-card__label">Relation types</h3>
    <ul class="stats-list">
      ${s.relation_type_mix.map(r => `<li>${r.relation} <span class="stats-meta">${r.count}</span></li>`).join('') || '<li class="stats-empty">no edges yet</li>'}
    </ul>
  `);
}
```

- [ ] **Step 2: Commit**

```bash
git add website/features/user_profile/js/user_profile.js
git commit -m "feat: stats Domain+Activity+Graph renderers"
```

### Task 5.7: Add list / delta CSS

**Files:**
- Modify: `website/features/user_profile/css/user_profile.css`

- [ ] **Step 1: Append**

```css
.stats-list {
  list-style: none;
  padding: 0;
  margin: 0;
  font-size: 0.875rem;
}
.stats-list li {
  display: flex;
  justify-content: space-between;
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--border);
}
.stats-list li:last-child { border-bottom: 0; }
.stats-empty { color: var(--text-muted); font-style: italic; }
.stats-meta { color: var(--text-muted); }
.stats-delta-up { color: hsl(160, 60%, 55%); } /* teal-leaning green, not purple */
.stats-delta-down { color: hsl(20, 60%, 55%); } /* warm amber-leaning, NOT used outside /knowledge-graph */
.stats-big-number { font-size: 2rem; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; }
.stats-card__label { font-size: 0.875rem; color: var(--text-muted); margin: 0 0 0.5rem; font-weight: 500; }
.stats-card__sub { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem; }
```

⚠ The amber tone in `.stats-delta-down` — per CLAUDE.md "No Purple + Teal/Amber Rules", amber/gold is reserved for `/knowledge-graph`. Use a muted red-orange that is NOT amber-gold (e.g. `hsl(20, 60%, 55%)` is more red than amber). Confirm in design review.

- [ ] **Step 2: Commit**

```bash
git add website/features/user_profile/css/user_profile.css
git commit -m "feat: stats list + delta colors (no purple, no amber)"
```

### Task 5.8: ZKStatsCache — persistent client-side cache (localStorage)

Goal: persist the latest stats payload per-workspace across browser sessions, so re-opening `/profile` instantly shows the prior report while the fresh fetch runs in the loading box (SWR pattern). Storage choice is localStorage — synchronous, ~5 MB origin budget, JSON-serializable. The whole payload is <50 KB. IndexedDB is not justified at this size and adds async overhead.

**Files:**
- Create: `website/static/js/zk_stats_cache.js`
- Modify: `website/features/user_profile/index.html` (add `<script>` tag before `user_profile.js`)

- [ ] **Step 1: Write the module**

```javascript
/* website/static/js/zk_stats_cache.js
 *
 * Per-workspace persistent cache for the profile stats payload.
 *
 * Storage shape (localStorage):
 *   key  = 'zk_stats_v1::' + workspace_id
 *   val  = JSON.stringify({ etag, payload, stored_at })
 *
 * Single most-recent entry per workspace (no history; the server ETag
 * is the only freshness lever). Eviction: if write fails due to quota,
 * scan all 'zk_stats_v1::*' keys and drop the oldest by stored_at.
 *
 * The module reads workspace_id from window.ZK_PROFILE.workspace_id
 * (already exposed by the profile page bootstrap) OR falls back to
 * the JWT 'workspace_id' claim if needed. If neither is available,
 * read/write become no-ops so the controller still works (just always
 * cache-misses).
 *
 * Public API (Promise-returning even though localStorage is sync, so
 * we can swap to IndexedDB later without touching callers):
 *   await ZKStatsCache.read()              -> {etag, payload, stored_at} | null
 *   await ZKStatsCache.write(etag, payload) -> void
 *   await ZKStatsCache.clear()              -> void
 */
(function () {
  'use strict';
  if (window.ZKStatsCache) return;

  var PREFIX = 'zk_stats_v1::';

  function getWorkspaceId() {
    try {
      if (window.ZK_PROFILE && window.ZK_PROFILE.workspace_id) {
        return String(window.ZK_PROFILE.workspace_id);
      }
    } catch (_) {}
    return null;
  }

  function keyFor(ws) { return PREFIX + ws; }

  function evictOldestUntilFits(value) {
    // Best-effort: scan our prefix, sort by stored_at, drop oldest.
    var entries = [];
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (k && k.indexOf(PREFIX) === 0) {
        try {
          var v = JSON.parse(localStorage.getItem(k));
          entries.push({ k: k, t: v && v.stored_at ? v.stored_at : 0 });
        } catch (_) {
          entries.push({ k: k, t: 0 });
        }
      }
    }
    entries.sort(function (a, b) { return a.t - b.t; });
    // Try to remove up to N oldest before giving up
    for (var j = 0; j < Math.min(entries.length, 5); j++) {
      try { localStorage.removeItem(entries[j].k); } catch (_) {}
      try {
        localStorage.setItem(value.key, value.serialized);
        return true;
      } catch (_) { /* try one more */ }
    }
    return false;
  }

  function read() {
    return new Promise(function (resolve) {
      var ws = getWorkspaceId();
      if (!ws) return resolve(null);
      var raw;
      try { raw = localStorage.getItem(keyFor(ws)); } catch (_) { return resolve(null); }
      if (!raw) return resolve(null);
      try {
        var parsed = JSON.parse(raw);
        if (!parsed || !parsed.payload) return resolve(null);
        resolve({ etag: parsed.etag || '', payload: parsed.payload, stored_at: parsed.stored_at || 0 });
      } catch (_) {
        resolve(null);
      }
    });
  }

  function write(etag, payload) {
    return new Promise(function (resolve) {
      var ws = getWorkspaceId();
      if (!ws) return resolve();
      var entry = { etag: etag, payload: payload, stored_at: Date.now() };
      var serialized;
      try { serialized = JSON.stringify(entry); } catch (_) { return resolve(); }
      var key = keyFor(ws);
      try {
        localStorage.setItem(key, serialized);
        return resolve();
      } catch (err) {
        // Quota: try to evict and retry once
        evictOldestUntilFits({ key: key, serialized: serialized });
        resolve();
      }
    });
  }

  function clear() {
    return new Promise(function (resolve) {
      var ws = getWorkspaceId();
      if (!ws) return resolve();
      try { localStorage.removeItem(keyFor(ws)); } catch (_) {}
      resolve();
    });
  }

  window.ZKStatsCache = { read: read, write: write, clear: clear };
})();
```

- [ ] **Step 2: Add script tag to `index.html` (place BEFORE user_profile.js):**

```html
<script src="/static/js/zk_stats_cache.js?v=20260527a" defer></script>
<script src="/static/js/zk_skeleton_typewriter.js?v=20260527a" defer></script>
<script src="/website/features/user_profile/js/user_profile.js?v=20260527a" defer></script>
```

- [ ] **Step 3: Verify `window.ZK_PROFILE.workspace_id` is exposed by the existing profile page bootstrap.** If not, add a single `<script>` block in `index.html` that sets it from the server-rendered profile context (the bootstrap already exposes profile id; workspace id may need to be added — confirm in Phase 0 Task 0.4 expected-outcome by checking the existing `user_profile.js` for where it reads workspace identity).

- [ ] **Step 4: Manual browser test (no automated JS-side tests for v1 — keep overhead minimal)**

In Chrome DevTools console on `/profile`:
```js
await ZKStatsCache.read();      // null on first load
// ... after a successful fetch:
await ZKStatsCache.read();      // {etag, payload, stored_at}
localStorage.getItem('zk_stats_v1::' + ZK_PROFILE.workspace_id);  // string < 50KB
```

- [ ] **Step 5: Commit**

```bash
git add website/static/js/zk_stats_cache.js website/features/user_profile/index.html
git commit -m "feat: persistent client cache for profile stats"
```

---

## Phase 6 — Verification, Deploy, Post-merge follow-up

### Task 6.1: Full test suite + ruff

- [ ] **Step 1: Run unit + integration tests**

```bash
python -m pytest tests/unit/website/user_stats -v
python -m pytest tests/integration/v2/test_profile_stats_rpc.py tests/integration/v2/test_profile_stats_endpoint.py -v
```

Expected: all PASS.

- [ ] **Step 2: Run ruff (single pass per CLAUDE.md "Batch ruff at end of plan")**

```bash
ruff check website/features/user_stats tests/unit/website/user_stats tests/integration/v2/test_profile_stats_*.py
ruff format website/features/user_stats tests/unit/website/user_stats tests/integration/v2/test_profile_stats_*.py
```

- [ ] **Step 3: Run full test suite (regression check)**

```bash
python -m pytest tests/ -m "not live"
```

Expected: no new failures.

- [ ] **Step 4: Commit any ruff-driven changes**

```bash
git add -u
git commit -m "chore: ruff lint+format pass"
```

### Task 6.2: EXPLAIN + ANALYZE pre-deploy

- [ ] **Step 1: Re-run `EXPLAIN (ANALYZE, BUFFERS)` on each section's underlying queries against a populated staging workspace.**

For each section, capture the timing line. Save output to `docs/claude_audits/user_stats_explain_2026-05-27.txt` (assistant-authored audit, NOT docs/research/).

Expected: combined total <500ms for a workspace with ~100 zettels + ~50 chats + ~30 kg nodes. Reject if any node shows seq-scan over >100k rows.

- [ ] **Step 2: Run `ANALYZE` on all touched tables (idempotent)**

```bash
psql "$STAGING_DATABASE_URL" -c "
  ANALYZE core.profiles;
  ANALYZE core.workspaces;
  ANALYZE core.workspace_members;
  ANALYZE content.canonical_zettels;
  ANALYZE content.workspace_zettels;
  ANALYZE content.canonical_chunks;
  ANALYZE rag.kastens;
  ANALYZE rag.kasten_zettels;
  ANALYZE rag.chat_sessions;
  ANALYZE rag.chat_messages;
  ANALYZE kg.kg_nodes;
  ANALYZE kg.kg_edges;
  ANALYZE billing.pricing_subscriptions;
"
```

- [ ] **Step 3: Commit the EXPLAIN audit doc**

```bash
git add docs/claude_audits/user_stats_explain_2026-05-27.txt
git commit -m "docs: stats RPC EXPLAIN baseline pre-deploy"
```

### Task 6.2.5: Apply migrations to production Supabase (separate from CI deploy)

The `deploy-droplet.yml` workflow deploys CODE only. SQL migrations are applied manually via Supabase SQL editor or `psql` against the prod connection string. Must be done BEFORE the code deploy lands so the new code finds the role/index/RPC it expects.

**HUMAN CHECKPOINT — operator authorization required per CLAUDE.md "Audit/Verify ≠ Authorization".**

- [ ] **Step 1: Pre-apply audit**

Operator confirms:
- [ ] Migrations 79, 80, 81 reviewed end-to-end against this plan (no drift)
- [ ] Down migrations exist for each (`79.down.sql`, `80.down.sql`, `81.down.sql`)
- [ ] EXPLAIN baseline doc captured in Task 6.2 shows no seq-scan over >100k rows
- [ ] Swapfile already on droplet per Phase 1 Task 1.2 HUMAN CHECKPOINT
- [ ] Staging applied cleanly + integration tests pass against staging

- [ ] **Step 2: Apply in order**

Run from operator's machine (NOT auto-executed):

```bash
# 1) Role + grants (no DDL on existing tables; safe to apply anytime)
psql "$PROD_DATABASE_URL" -f supabase/website/_v2/79_stats_reader_role.sql

# 2) Partial index (CREATE INDEX CONCURRENTLY — must NOT be wrapped in BEGIN/COMMIT)
psql "$PROD_DATABASE_URL" --single-transaction=off -f supabase/website/_v2/80_chat_messages_user_partial_idx.sql

# 3) The RPC (CREATE OR REPLACE FUNCTION × 2 — safe, no data change)
psql "$PROD_DATABASE_URL" -f supabase/website/_v2/81_profile_stats_v1_rpc.sql

# 4) ANALYZE (refresh planner stats post-index)
psql "$PROD_DATABASE_URL" -c "ANALYZE rag.chat_messages;"
```

- [ ] **Step 3: Verify each applied**

```bash
psql "$PROD_DATABASE_URL" -c "
  SELECT rolname, rolconfig FROM pg_roles WHERE rolname = 'stats_reader';
  SELECT indexname FROM pg_indexes WHERE indexname = 'idx_chat_messages_workspace_user_created';
  SELECT proname FROM pg_proc WHERE proname IN ('profile_stats_v1', 'profile_stats_etag_probe_v1');
"
```

Expected: 1 role row + 1 index row + 2 function rows.

- [ ] **Step 4: NOW merge the code PR.** The auto-deploy workflow will roll out the new endpoint, which will immediately find the prod-side role/index/RPC in place.

### Task 6.3: Open PR

- [ ] **Step 1: Push branch and open PR via `gh pr create`**

PR title: `feat: user statistics module + Statistics tab`

PR body MUST include the rollback runbook below so any on-call can execute it without context:

```markdown
## Summary
- New `/api/profile/stats` endpoint backed by a single SECURITY DEFINER RPC
- Statistics tab on `/profile` (desktop only — mobile `/m/` unchanged)
- 28 stats across 7 sections; cache-first SWR with abortable progress UX
- Architecture audit: `docs/claude_audits/user_stats_architecture_research_2026-05-26.md`
- Plan: `docs/superpowers/plans/2026-05-27-user-statistics-module.md`

## Migrations
- 79: `stats_reader` role + grants + timeouts (45s statement_timeout, 60s idle_in_transaction)
- 80: partial idx on `rag.chat_messages (workspace_id, created_at) WHERE role='user'` — CREATE INDEX CONCURRENTLY
- 81: `core.profile_stats_v1` + `core.profile_stats_etag_probe_v1` RPCs

## Pre-deploy checklist
- [ ] Droplet swapfile applied (1 GB, `vm.swappiness=10`) — Task 1.2 checkpoint
- [ ] Migrations 79/80/81 applied to prod via `psql` — Task 6.2.5
- [ ] EXPLAIN baseline captured: `docs/claude_audits/user_stats_explain_2026-05-27.txt`
- [ ] Staging integration tests pass

## Post-merge
- [ ] If Kasten quota does NOT exist in `billing.pricing_subscriptions` → open follow-up issue per Task 6.4
- [ ] Watch `pg_stat_statements` for first 24h; alert on any stats query >5s p95

## Rollback runbook (if /profile breaks)

1. **Code-only revert** (safest — keeps schema additions, just removes the endpoint):
   ```bash
   gh pr revert <this-pr-number>
   # Auto-deploy will roll back to prior code.
   ```
   Schema migrations 79/80/81 are read-only / additive — safe to leave in place.

2. **Full revert including schema** (only if the new RPC itself is hurting OLTP):
   ```bash
   gh pr revert <this-pr-number>
   psql "$PROD_DATABASE_URL" -f supabase/website/_v2/81_profile_stats_v1_rpc.down.sql
   psql "$PROD_DATABASE_URL" --single-transaction=off -f supabase/website/_v2/80_chat_messages_user_partial_idx.down.sql
   psql "$PROD_DATABASE_URL" -f supabase/website/_v2/79_stats_reader_role.down.sql
   ```

3. **Stats-only kill switch** (no migration revert needed — fastest):
   Add `STATS_TAB_ENABLED=false` to droplet container env and restart. The `/api/profile/stats` route checks this flag at request time and returns 503 if false. (Implementer: add this check in Task 4.4 if not present.)

## Test plan
- [ ] Visit https://zettelkasten.in/profile, verify all 7 tabs render
- [ ] Hard refresh — cached payload appears instantly, loading box runs alongside
- [ ] Click Stop mid-load — fetch aborts, cached data stays, "Update cancelled" hint
- [ ] `curl -sI -H 'Authorization: Bearer <jwt>' https://zettelkasten.in/api/profile/stats` returns 200 + etag header
- [ ] Same request with `if-none-match: <etag>` returns 304
- [ ] Watch `pg_stat_statements` for `profile_stats_v1` calls — p95 <500ms

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- [ ] **Step 2: Monitor CI**

Expected: `grep`, `scan`, `pytest (mocked)` all pass.

- [ ] **Step 3: Add the kill-switch check in `website/features/user_stats/router.py` if not already present**

In the `get_profile_stats` handler, before acquiring the semaphore:

```python
from website.core.settings import get_settings
settings = get_settings()
if not getattr(settings, "stats_tab_enabled", True):
    raise HTTPException(status_code=503, detail="stats endpoint disabled")
```

Add `stats_tab_enabled: bool = True` to the `Settings` class in `website/core/settings.py`. Default ON; flip to `false` in container env for emergency disable.

- [ ] **Step 4: Commit kill switch**

```bash
git add website/features/user_stats/router.py website/core/settings.py
git commit -m "feat: stats endpoint kill-switch env flag"
```

### Task 6.4: Post-merge follow-up — Kasten quota flag

- [ ] **Step 1: If Task 0.3 found `KASTEN QUOTA: NOT FOUND`, immediately after merge open a GitHub issue or new mem-vault observation:**

Title: `Add Kasten quota to pricing model (blocker for Main Board Kastens pie)`

Body:
```
Statistics tab Main Board currently shows Total Kastens as a plain count
because no per-period Kasten quota exists in billing.pricing_subscriptions
or docs/research/pricing1.md. Per operator decision 2026-05-27, Kasten quota
SHOULD exist. Next iteration to:
- Spec the per-tier Kasten quota (Free / Basic / Max)
- Add column or jsonb entitlement to pricing_subscriptions
- Backfill existing subscriptions
- Update Main Board renderer to show the Kastens pie (already coded
  defensively — flip the `quota_available` branch)
```

⚠ **DO NOT FORGET this step. The operator explicitly flagged it as the post-merge follow-up.**

- [ ] **Step 2: Save as mem-vault observation**

Call `mcp__plugin_mem-vault_mem-vault__save_observation` with `type=decision` and the issue body.

### Task 6.5: Deploy verification

- [ ] **Step 1: After merge, monitor the `deploy-droplet.yml` workflow**

- [ ] **Step 2: Smoke test on production:**

```bash
curl -sI -H "Authorization: Bearer <token>" https://zettelkasten.in/api/profile/stats
```

Expected: 200, `etag: <hash>`, `x-stats-cache: miss` on first hit, `hit` on subsequent.

- [ ] **Step 3: Visit `https://zettelkasten.in/profile` in a real browser, verify Statistics tab renders all 7 sections without console errors**

- [ ] **Step 4: Capture mem-vault observation**

```
type: feature
content: Shipped user_statistics module (PR #<n>): 28 stats across 7 sections,
single RPC core.profile_stats_v1, semaphore-gated endpoint, in-process LRU,
zero MVs in v1. Architecture audit + 100-stat catalog: docs/claude_audits/.
Follow-up open: Kasten quota gap (if applicable).
```

---

## Self-Review Checklist (run before handing off)

- [ ] Every stat from the user's spec maps to exactly one task (Tasks 3.1-3.7 + frontend Tasks 5.4-5.6)
- [ ] All exact file paths use absolute repo-relative paths (no placeholders like `<file>`)
- [ ] Every SQL block uses verified column names (`user_tags` not `derived_tags`, `wz.deleted_at IS NULL`, `workspace_members.profile_id` scope, etc.)
- [ ] Pricing column references in Task 3.1 marked with the "Implementer note" — Phase 0 Task 0.3 produces the real names
- [ ] No purple anywhere in CSS; amber-gold reserved for `/knowledge-graph` only
- [ ] Migration numbers verified (79, 80, 81) against existing `_v2/` directory
- [ ] Down migrations exist for 79 and 80 (per existing pattern in 73-78); 81 has a DROP FUNCTION down
- [ ] `CREATE INDEX CONCURRENTLY` flagged with the no-transaction caveat
- [ ] Phase 1 droplet swapfile has HUMAN CHECKPOINT (no auto-SSH)
- [ ] Post-merge Kasten quota follow-up is explicit and tied to the AskUserQuestion answer

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-27-user-statistics-module.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints

Which approach?
