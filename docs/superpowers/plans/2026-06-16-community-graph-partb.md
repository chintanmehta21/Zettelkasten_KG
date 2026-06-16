# Community Graph — Part B (Phase 0 + Phase 1) — TDD Implementation Plan

**Date:** 2026-06-16 (revised 2026-06-17 for the privacy MODEL FLIP — opt-out)
**Branch:** `feat/community-graph-partb` (off master `7a920f38`, includes merged Part A / PR #157)
**Methodology:** superpowers:writing-plans (bite-sized TDD: failing test → run-fail → minimal impl → run-pass → commit)
**Authoritative model:** `docs/claude_audits/community_graph_design_2026-06-15.md` → **"▶ REV 3 — privacy MODEL FLIP: all-public + per-zettel opt-OUT"** (operator decision 2026-06-16). **Rev 3 supersedes Rev 2's opt-in model.** Where this plan and Rev 2 disagree, Rev 3 wins.

## Goal

Ship the privacy floor (**Phase 0**) and the MVP public community graph (**Phase 1**) for `/knowledge-graph` under an **all-public + per-zettel opt-OUT** model. After this plan, `view=global` is built from **all users' zettels by default** (auto-updating as users add more), each zettel **shown with the owner's `display_name`**, with any zettel **markable private** to hide it from Global. The surface is served through a fail-closed least-privilege DB role, cached with SWR + a cross-worker version counter, edge-cacheable on Cloudflare, and surfaced with a per-zettel **Make-private** toggle + teal **"Private"** badge + undo toast. A dismissible **signup/first-use NOTICE** ("Your saved zettels are public and shown with your display name. Mark any private to hide it.") is the consent surface — it replaces the per-publish consent modal. The Part A Personal/Community toggle maps Global → the real community graph; `view=my`/`kasten` now **hard-401** on missing/expired auth (operator approved 2026-06-16).

## Architecture

- **Privacy gate (defence in depth, in priority order):** the *shape* is unchanged from the opt-in design; ONLY the predicate flips to `is_private = false`.
  1. **Forced-predicate RPC** — `content.community_graph_v1(...)` is `SECURITY DEFINER`, hardcodes `WHERE wz.is_private = false AND wz.deleted_at IS NULL`, strips `user_id`, joins attribution through `core.profiles.display_name`. It is the ONLY read path for the community surface.
  2. **Least-privilege role** — the RPC is `OWNED BY community_reader` (a `NOLOGIN`, **non-BYPASSRLS**, SELECT-only role). Because SECURITY DEFINER executes as the owner and `community_reader` does NOT bypass RLS, even a forgotten predicate in a future edit **fails closed** at the row level via the RLS policy below — now protecting the **marked-private** subset.
  3. **RLS policy** — `content.workspace_zettels` already has RLS enabled (`08_rls_policies.sql:22`). We add `FOR SELECT TO community_reader USING (is_private = false AND deleted_at IS NULL)`. `service_role` keeps BYPASSRLS so the rest of the app is unaffected; `authenticated`'s existing own-workspace policy is unchanged; there is **no `anon` SELECT policy** (verified — enabling nothing new for anon).
  4. **App wrapper** — a single Python repository method (`CommunityGraphRepository.get_community_graph`) calls the RPC; serving never re-implements the predicate.
  5. **CI regression gate** — a `@pytest.mark.live` test proves `view=global` never returns an `is_private=true` row even though the app connects via `service_role`/BYPASSRLS.
- **Consent / privacy basis:** the **signup/first-use NOTICE** (Task 1.8) is the consent surface (public-by-default is disclosed up front). A per-zettel `is_private boolean NOT NULL DEFAULT false` flag (default = **public**) + `made_private_at timestamptz` (nullable) on `content.workspace_zettels` record each opt-out. An append-only `content.zettel_privacy_events` audit table logs every `make_private`/`make_public`. **No `is_published`/`published_at`/`attribution` columns; no backfill** — the existing ~80 zettels become public via the column default.
- **Serving:** `run_view_graph`'s `view='global'` branch is rebuilt from the wrapper, behind the existing `graph_cache` SWR + single-flight cache, invalidated by a Postgres `content.community_cache_version` counter bumped on make-private/make-public. The **file-store is RETIRED from the live global path** — Global is the real all-public community graph (there IS data). A graceful empty-state overlay ("No community zettels yet") shows only if the community is ever genuinely empty; there is **no file-store fallback**.
- **Headers/CDN:** `view=global` → `public, max-age=60, s-maxage=300, stale-while-revalidate=600` + `Vary: Accept-Encoding` only + zero `Set-Cookie`; client drops `Authorization` for global. `view=my`/`kasten` → `private`-style headers **and hard-401** on missing/expired auth (replaces Part A's Optional-user→empty). Ops note (not code) for the Cloudflare Cache Rule.
- **UX:** per-zettel **Make-private / Make-public** toggle in the KG side panel (default = public/shown), persistent **teal** "Private" badge on hidden zettels, undo toast. A dismissible teal signup/first-use notice on `/home`. Pure JS helpers behind the `/* test-exports */` fence with vitest.

## Tech Stack

- DB: Supabase Postgres v2 (`core, content, kg, rag, pipelines, billing` schemas). Versioned migrations `supabase/website/_v2/NN_*.sql` (each with `.down.sql`), repeatable `repeatable/R__*.sql`. Runner: `ops/scripts/apply_migrations.py --v2` (lexical order, checksum-gated, schema-drift manifest gate, exit code 3 on drift). Latest versioned slot is **84** → this plan uses **85, 86, 87, 88, 89**.
- Backend: FastAPI async (`asyncio_mode = auto`), supabase-py service_role client (`get_v2_client()`), asyncpg for tests.
- Frontend: vanilla JS (`website/features/knowledge_graph/js/app.js`, `website/features/user_home/js/home.js`), vitest for pure helpers.
- Tests: pytest (`@pytest.mark.live` for DB; run `pytest --live`); fixtures in `tests/integration/v2/conftest.py` (`asyncpg_pool`, `mint_user`, `bulk_insert_zettels`) + `tests/v2/fixtures/users.py` (`MintedUser`). Unit tests mock `get_settings()`. JS: `npx vitest run tests/js/<area>/<file>`.

## REQUIRED SUB-SKILL: superpowers:subagent-driven-development

Execute this plan with **superpowers:subagent-driven-development** — one Implementation subagent per task, then Verification, Anti-pattern, Code-Quality, and Commit subagents. Never advance a task until its verification step passes. This repo's multi-phase work is **dashboard-only** (see CLAUDE.md memory): render the bordered dashboard at every task/gate boundary, one-line tick between minor steps, no prose narration.

## Scope note — Phases 2–4 are SEPARATE follow-on plans

This plan covers **Phase 0 (privacy floor)** and **Phase 1 (MVP public community graph)** ONLY. The following are explicitly OUT of scope and will be planned separately:
- **Phase 2** — moderation pipeline (`content_reports` → review queue → make-private lever) + legal (ToS/AUP/Privacy/DMCA) + per-user privacy-toggle rate-limit (anti-abuse) + wire-make-private→Cloudflare-purge.
- **Phase 3** — out-of-DB igraph Leiden(modularity)+PageRank clustering + per-node top-K/tag-frequency edge capping + discovery surfaces.
- **Phase 4** — precompute tier (MV CONCURRENTLY first, staging-swap only on measured triggers).

Deferred items (each a standalone decision when triggered): OpenAI Moderation triage, shadow-ban, DSA portal, **anonymous-contribution mode** (public zettels currently always show `display_name`), CC export, engagement-ranked trending.

---

## Guardrails (HARD constraints — keep in view for every task)

- **`service_role` bypasses RLS.** The `community_reader` role + the SECURITY-DEFINER RPC owned by it + the RLS policy are the *real* gate. The app-layer wrapper is the convenience layer, not the security boundary. The P0-e regression gate + P0-d wrapper are load-bearing — build them in order: **schema → audit table → role/RLS/RPC → wrapper → regression gate → serving → headers → UX**.
- **Opt-out predicate is `is_private = false`** everywhere (RPC, RLS policy, wrapper, regression gate). Default-public means a *new* zettel is visible the moment it exists; the privacy mechanism is the per-zettel opt-out, the signup notice, and erasure.
- **Every NEW table/role migration needs explicit GRANTs.** Do NOT rely on `08_rls_policies.sql`'s `GRANT ALL ... TO service_role` (covers tables existing at line 4's execution) or `64_grant_all_v2_tables_to_service_role.sql` (covers ≤64). New objects in 85–89 get their own explicit grants.
- **End every schema migration with `NOTIFY pgrst, 'reload schema';`** (and `'reload config'` where grants/roles change, mirroring `29`/`R__content_rpcs.sql`).
- **Never break Part A:** Personal view, the Personal/Community toggle, `auth-core.js`/`zk_fetch.js`/`zk_fetch` 401→refresh→banner pipeline, `buildGraphApiUrl`, `loadUserOwnedIds`, the `/* test-exports */` fence and existing vitest tests. The hard-401 (Task 1.2) is IN scope but MUST be wired so the existing 401→refresh→banner pipeline + `loadUserOwnedIds` handle it without breaking the page (Part A regression checks are part of that task). If during implementation the hard-401 proves to break Part A, the implementer must surface it.
- **UI:** teal (`#14b8a6`) for community/Personal surfaces; amber/gold ONLY on the `/knowledge-graph` 3D viz; **NEVER purple**.
- **No infra disclosure** in user-facing UI (no model names/scores/latency/user_ids).
- **Protected knobs untouched:** `GUNICORN_WORKERS≥2` + `--preload`, `GUNICORN_TIMEOUT≥180s`, rerank semaphore, SSE heartbeat, Caddy `transport http { read_timeout 240s ... }`.
- **Post-fork thread rule:** any background refresh thread must start POST-FORK (lazily, on first request), never at import — the gunicorn pre-fork thread-death bug. The existing `graph_cache` already obeys this (lazy `get_default_cache()` + `asyncio.create_task` inside request handling); we extend it, not replace it.
- **Migration immutability:** never edit an applied versioned migration body (checksum drift → exit 3). Code-objects that legitimately evolve go in `repeatable/R__*.sql`. The `community_graph_v1` RPC ownership + grants are one-time DDL → versioned file; see DESIGN DECISIONS for why the body lives there too (not in R__).

---

## File Structure (every file created / modified)

**Created — migrations (`supabase/website/_v2/`):**
- `85_workspace_zettels_privacy.sql` + `.down.sql` — ADD `is_private`/`made_private_at` columns + community partial index on `content.workspace_zettels`.
- `86_zettel_privacy_events.sql` + `.down.sql` — append-only `content.zettel_privacy_events` table + explicit grants.
- `87_community_reader_role.sql` + `.down.sql` — `community_reader` NOLOGIN role + timeouts + SELECT grants + RLS SELECT policy (`is_private = false`) on `content.workspace_zettels`.
- `88_community_graph_v1_rpc.sql` + `.down.sql` — `content.community_graph_v1(int, float)` SECURITY DEFINER RPC (predicate `is_private = false`), `ALTER FUNCTION ... OWNER TO community_reader`, `GRANT EXECUTE ... TO service_role`.
- `89_community_cache_version.sql` + `.down.sql` — `content.community_cache_version` single-row counter + `content.bump_community_cache_version()` RPC + grants.

**Created — Python:**
- `website/core/supabase_v2/repositories/community_repository.py` — `CommunityGraphRepository` (the forced-predicate wrapper: `get_community_graph`, `read_cache_version`, `bump_cache_version`, `set_private`).

**Created — tests:**
- `tests/integration/v2/test_community_privacy_schema.py` — schema/column/index assertions (live).
- `tests/integration/v2/test_zettel_privacy_events.py` — audit table insert/append-only assertions (live).
- `tests/integration/v2/test_community_reader_role.py` — role exists, non-BYPASSRLS, RLS fails closed under `SET ROLE` (private rows hidden) (live).
- `tests/integration/v2/test_community_graph_v1_rpc.py` — RPC ownership, predicate (`is_private=false`), no user_id, attribution (live).
- `tests/integration/v2/test_community_graph_regression_gate.py` — **the load-bearing privacy proof** (live).
- `tests/integration/v2/test_community_repository.py` — wrapper calls RPC, never leaks private (live).
- `tests/integration/v2/test_community_cache_version.py` — counter read/bump (live).
- `tests/integration/v2/test_view_graph_global_community.py` — `run_view_graph` global branch builds from community (no file-store fallback) (live).
- `tests/integration/v2/test_graph_my_hard_401.py` — `view=my`/`kasten` return 401 for anonymous; `view=global` stays anonymous-OK (live + unit).
- `tests/integration/v2/test_privacy_endpoint.py` — `POST /private` / `/public` ownership, audit row, cache bump (live).
- `tests/website/test_graph_data_global_headers.py` — global vs my Cache-Control/Vary/Set-Cookie + my-anon 401 (unit, mocked).
- `tests/js/knowledge_graph/privacy_helpers.test.js` — vitest for pure privacy-toggle JS helpers.
- `tests/js/knowledge_graph/build_graph_api_url_auth.test.js` — vitest proving Authorization is dropped for global + `loadUserOwnedIds` survives 401.
- `tests/js/user_home/signup_notice.test.js` — vitest for the pure signup-notice helper.

**Modified:**
- `website/api/module_runners/view_graph.py` — rebuild `view='global'` branch from the wrapper (no file-store fallback) + version-counter cache key.
- `website/api/routes.py` — branch `graph_data` cache headers on `view`; **hard-401** when resolved view is `my`/`kasten` and the caller is anonymous; add `POST /api/zettels/{workspace_zettel_id}/private` + `/public`; keep Part A `view=my`-authed path intact.
- `website/features/knowledge_graph/js/app.js` — drop `Authorization` for `view=global`; ensure `loadUserOwnedIds` tolerates 401; add Make-private toggle/badge/undo-toast helpers (pure helpers inside the fence); empty-community overlay.
- `website/features/knowledge_graph/index.html` — Make-private toggle button in the side panel + "Private" badge element; bump `app.js?v=` cache-bust.
- `website/features/user_home/js/home.js` — pure signup-notice helper (inside a new test-export fence) + DOM wiring in `init()`.
- `website/features/user_home/index.html` — dismissible teal signup/first-use notice element in the welcome block; bump `home.js?v=` cache-bust.
- `website/features/user_home/css/home.css` — teal notice styling.
- `ops/runbooks/` (or the plan's ops-note task) — Cloudflare Cache Rule note (doc only, no code).

---

# PHASE 0 — Privacy Floor

> Must fully land (schema + role + RLS + RPC + wrapper + regression gate) before any Phase 1 serving task. The regression gate (Task 0.6) is the privacy proof and MUST be green before Task 1.1.

---

## Task 0.1 — Schema: privacy columns on `content.workspace_zettels`

**Files:**
- `supabase/website/_v2/85_workspace_zettels_privacy.sql` (new)
- `supabase/website/_v2/85_workspace_zettels_privacy.down.sql` (new)
- `tests/integration/v2/test_community_privacy_schema.py` (new)

Grounding: column-add idiom mirrors `72_workspace_zettels_derived_tags.sql:19-44` (BEGIN; `SET LOCAL lock_timeout='3s'`/`statement_timeout='60s'`; `ADD COLUMN IF NOT EXISTS`; COMMENT). Partial-index + reload idiom mirrors `66_workspace_zettels_partial_indexes.sql:35-53` (`CREATE INDEX IF NOT EXISTS ... WHERE ...`; end with `NOTIFY pgrst, 'reload schema';`). Column adds on an already-granted table need no new table grants; the index + PostgREST reload do — keep the NOTIFY. Table columns confirmed in `02_content_schema.sql:74-94`. **No backfill** — the existing ~80 zettels become public via `DEFAULT false`.

### Step 1 — Write the failing test

`tests/integration/v2/test_community_privacy_schema.py`:

```python
"""Schema assertions for migration 85 (privacy columns on workspace_zettels).

Marked @pytest.mark.live — introspects the live v2 Postgres catalog via the
direct asyncpg pool. No user data is written.

Opt-OUT model: is_private DEFAULT false (default PUBLIC); made_private_at nullable.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_is_private_column_exists_default_false_not_null(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT data_type, is_nullable, column_default
              FROM information_schema.columns
             WHERE table_schema = 'content'
               AND table_name = 'workspace_zettels'
               AND column_name = 'is_private'
            """
        )
    assert row is not None, "is_private column missing"
    assert row["data_type"] == "boolean"
    assert row["is_nullable"] == "NO"
    # Default FALSE = PUBLIC-by-default (the whole point of the opt-out flip).
    assert "false" in (row["column_default"] or "").lower()


@pytest.mark.asyncio
async def test_made_private_at_column_exists_nullable_timestamptz(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = 'content'
               AND table_name = 'workspace_zettels'
               AND column_name = 'made_private_at'
            """
        )
    assert row is not None, "made_private_at column missing"
    assert row["data_type"] == "timestamp with time zone"
    assert row["is_nullable"] == "YES"


@pytest.mark.asyncio
async def test_legacy_publish_columns_absent(asyncpg_pool):
    """The opt-in columns must NOT exist under the opt-out model."""
    async with asyncpg_pool.acquire() as conn:
        present = {
            r["column_name"]
            for r in await conn.fetch(
                """
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_schema = 'content'
                   AND table_name = 'workspace_zettels'
                   AND column_name IN ('is_published', 'published_at', 'attribution')
                """
            )
        }
    assert present == set(), f"legacy opt-in columns must be absent, found {present}"


@pytest.mark.asyncio
async def test_community_partial_index_exists(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        ddl = await conn.fetchval(
            """
            SELECT indexdef
              FROM pg_indexes
             WHERE schemaname = 'content'
               AND tablename = 'workspace_zettels'
               AND indexname = 'idx_workspace_zettels_community'
            """
        )
    assert ddl is not None, "idx_workspace_zettels_community missing"
    assert "is_private" in ddl.lower()
    assert "where" in ddl.lower()  # partial
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_community_privacy_schema.py --live -q
```
Expected: failures — `is_private column missing` etc. (columns/index don't exist yet). `test_legacy_publish_columns_absent` passes trivially (they were never added).

### Step 3 — Minimal implementation

`supabase/website/_v2/85_workspace_zettels_privacy.sql`:

```sql
-- Migration 85 (Community Graph Part B / Phase 0 — P0-a): per-zettel PRIVACY flag.
--
-- OPT-OUT model (design Rev 3, operator decision 2026-06-16): every zettel is
-- PUBLIC in the community graph by default; a user marks a zettel private to
-- hide it. The flag lives on the per-(user,canonical) overlay row
-- content.workspace_zettels, NEVER on the deduped content.canonical_zettels
-- (UNIQUE(normalized_url), PR #25): a flag on the shared canonical row would let
-- User A's choice silently control User B the moment a second user saves the
-- same URL. Per-overlay is the granular, per-data-subject unit.
--
-- is_private DEFAULT false => existing ~80 zettels become PUBLIC via the column
-- default; NO BACKFILL is run. made_private_at is set when a zettel flips
-- private (internal audit; never returned by any public API).
--
-- Column adds on an already-granted table need no new GRANT (08_rls_policies.sql
-- granted ALL on content.* to service_role + SELECT/INSERT/UPDATE/DELETE to
-- authenticated). The partial index + the PostgREST reload DO need the NOTIFY.
-- Idempotent: ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.

BEGIN;
  SET LOCAL lock_timeout = '3s';
  SET LOCAL statement_timeout = '60s';

  ALTER TABLE content.workspace_zettels
    ADD COLUMN IF NOT EXISTS is_private boolean NOT NULL DEFAULT false;

  ALTER TABLE content.workspace_zettels
    ADD COLUMN IF NOT EXISTS made_private_at timestamptz;
COMMIT;

COMMENT ON COLUMN content.workspace_zettels.is_private IS
  'Per-zettel OPT-OUT flag. Default FALSE = PUBLIC (shown in the community graph with the owner display_name). TRUE hides it. NEVER on canonical_zettels (would over-hide/over-share via URL dedup).';
COMMENT ON COLUMN content.workspace_zettels.made_private_at IS
  'Internal audit timestamp set when is_private flips TRUE. NEVER returned by any public API.';

-- Community-read partial index: the community RPC scans the PUBLIC, non-deleted
-- hot set. A partial index materializes just that set ordered by recency so the
-- cross-workspace read (and any "recently added" surface) stays cheap at scale.
-- At ~80 rows this is moot, but it is designed for the 10k+ scale target.
CREATE INDEX IF NOT EXISTS idx_workspace_zettels_community
    ON content.workspace_zettels (created_at DESC)
    WHERE is_private = false AND deleted_at IS NULL;

NOTIFY pgrst, 'reload schema';
```

`supabase/website/_v2/85_workspace_zettels_privacy.down.sql`:

```sql
-- Reverse migration 85. Idempotent.
BEGIN;
  DROP INDEX IF EXISTS content.idx_workspace_zettels_community;
  ALTER TABLE content.workspace_zettels DROP COLUMN IF EXISTS made_private_at;
  ALTER TABLE content.workspace_zettels DROP COLUMN IF EXISTS is_private;
COMMIT;
NOTIFY pgrst, 'reload schema';
```

Apply:
```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
python ops/scripts/apply_migrations.py --v2 --update-manifest
```
(`--update-manifest` regenerates `supabase/website/_v2/expected_schema.json` so the post-apply schema-drift gate passes — the new columns are a deliberate change. NOTE: the manifest gate introspects the `public` schema only per `apply_migrations.py:419`, so content.* columns may not appear there; run `--update-manifest` regardless so any captured surface stays fresh.)

### Step 4 — Run, expect PASS

```bash
pytest tests/integration/v2/test_community_privacy_schema.py --live -q
```
Expected: 4 passed.

### Step 5 — Commit

```
feat: add per-zettel privacy column to workspace_zettels
```

---

## Task 0.2 — Privacy-audit table `content.zettel_privacy_events`

**Files:**
- `supabase/website/_v2/86_zettel_privacy_events.sql` (new)
- `supabase/website/_v2/86_zettel_privacy_events.down.sql` (new)
- `tests/integration/v2/test_zettel_privacy_events.py` (new)

Grounding: NEW table → explicit grants required (V2-grants rule; `08`/`64` GRANT ALL don't cover >84). Append-only → grant `SELECT, INSERT` only (no UPDATE/DELETE) to `service_role`. `community_reader` does NOT read it → no grant. FK to `content.workspace_zettels(id)` ON DELETE CASCADE. `gen_random_uuid()` is available (`00_extensions.sql`/pgcrypto, used across `01_core_schema.sql`). End with `NOTIFY pgrst`. RLS: enable + service-role-all policy to match the `08` pattern for operational tables. Schema per Rev 3 R3.1: `(id, actor_user_id, workspace_zettel_id, action ('make_private'|'make_public'), created_at)`.

### Step 1 — Write the failing test

`tests/integration/v2/test_zettel_privacy_events.py`:

```python
"""Migration 86: append-only content.zettel_privacy_events audit table.

@pytest.mark.live — uses the direct asyncpg pool + mint_user + bulk_insert_zettels.
Records each make_private / make_public action (privacy demonstrability).
"""
from __future__ import annotations

import asyncpg
import pytest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_table_exists_with_expected_columns(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        cols = {
            r["column_name"]: r["data_type"]
            for r in await conn.fetch(
                """
                SELECT column_name, data_type
                  FROM information_schema.columns
                 WHERE table_schema = 'content'
                   AND table_name = 'zettel_privacy_events'
                """
            )
        }
    for c in ("id", "actor_user_id", "workspace_zettel_id", "action", "created_at"):
        assert c in cols, f"missing column {c}: {cols}"


@pytest.mark.asyncio
async def test_action_check_enforced(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="privacy"))[0]
    async with asyncpg_pool.acquire() as conn:
        # Valid inserts OK.
        await conn.execute(
            """
            INSERT INTO content.zettel_privacy_events
              (actor_user_id, workspace_zettel_id, action)
            VALUES ($1, $2, 'make_private')
            """,
            user.profile_id, wz_id,
        )
        await conn.execute(
            """
            INSERT INTO content.zettel_privacy_events
              (actor_user_id, workspace_zettel_id, action)
            VALUES ($1, $2, 'make_public')
            """,
            user.profile_id, wz_id,
        )
        # Bad action rejected by CHECK.
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                """
                INSERT INTO content.zettel_privacy_events
                  (actor_user_id, workspace_zettel_id, action)
                VALUES ($1, $2, 'nuke')
                """,
                user.profile_id, wz_id,
            )


@pytest.mark.asyncio
async def test_service_role_has_no_update_or_delete_grant(asyncpg_pool):
    """Append-only: service_role may SELECT/INSERT but not UPDATE/DELETE."""
    async with asyncpg_pool.acquire() as conn:
        privs = {
            r["privilege_type"]
            for r in await conn.fetch(
                """
                SELECT privilege_type
                  FROM information_schema.role_table_grants
                 WHERE table_schema = 'content'
                   AND table_name = 'zettel_privacy_events'
                   AND grantee = 'service_role'
                """
            )
        }
    assert "SELECT" in privs and "INSERT" in privs
    assert "UPDATE" not in privs, f"append-only violated: {privs}"
    assert "DELETE" not in privs, f"append-only violated: {privs}"
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_zettel_privacy_events.py --live -q
```
Expected: failures — relation `content.zettel_privacy_events` does not exist.

### Step 3 — Minimal implementation

`supabase/website/_v2/86_zettel_privacy_events.sql`:

```sql
-- Migration 86 (Community Graph Part B / Phase 0 — P0-b): privacy audit log.
--
-- Append-only record of every make_private / make_public action (privacy
-- demonstrability; withdrawal of public visibility never erases the proof the
-- action happened). Replaces the opt-in design's publish_consent_events: under
-- opt-out the consent basis is the signup NOTICE, and what we audit is the
-- privacy TOGGLE, not a publish event.
--
-- NEW table => explicit grants are REQUIRED. 08_rls_policies.sql's GRANT ALL and
-- 64_grant_all_v2_tables_to_service_role.sql only cover tables that existed when
-- they ran (<= slot 64/84). Append-only ⇒ service_role gets SELECT + INSERT
-- only (NO UPDATE/DELETE). community_reader does NOT read this table → no grant.
-- Idempotent: CREATE TABLE IF NOT EXISTS + DROP/CREATE POLICY.

BEGIN;
  SET LOCAL lock_timeout = '3s';
  SET LOCAL statement_timeout = '60s';

  CREATE TABLE IF NOT EXISTS content.zettel_privacy_events (
      id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      actor_user_id        uuid,
      workspace_zettel_id  uuid REFERENCES content.workspace_zettels(id) ON DELETE CASCADE,
      action               text NOT NULL CHECK (action IN ('make_private', 'make_public')),
      created_at           timestamptz NOT NULL DEFAULT now()
  );

  CREATE INDEX IF NOT EXISTS idx_zettel_privacy_events_wz
      ON content.zettel_privacy_events (workspace_zettel_id, created_at DESC);

  ALTER TABLE content.zettel_privacy_events ENABLE ROW LEVEL SECURITY;

  -- service_role: append-only (no UPDATE/DELETE policy, no UPDATE/DELETE grant).
  DROP POLICY IF EXISTS zettel_privacy_events_service_select ON content.zettel_privacy_events;
  CREATE POLICY zettel_privacy_events_service_select ON content.zettel_privacy_events
      FOR SELECT TO service_role USING (true);
  DROP POLICY IF EXISTS zettel_privacy_events_service_insert ON content.zettel_privacy_events;
  CREATE POLICY zettel_privacy_events_service_insert ON content.zettel_privacy_events
      FOR INSERT TO service_role WITH CHECK (true);

  GRANT SELECT, INSERT ON content.zettel_privacy_events TO service_role;
COMMIT;

COMMENT ON TABLE content.zettel_privacy_events IS
  'Append-only privacy audit. One row per make_private/make_public. service_role has SELECT+INSERT only; never UPDATE/DELETE.';

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
```

`supabase/website/_v2/86_zettel_privacy_events.down.sql`:

```sql
-- Reverse migration 86. Idempotent.
BEGIN;
  DROP TABLE IF EXISTS content.zettel_privacy_events;
COMMIT;
NOTIFY pgrst, 'reload schema';
```

Apply:
```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
python ops/scripts/apply_migrations.py --v2 --update-manifest
```

### Step 4 — Run, expect PASS

```bash
pytest tests/integration/v2/test_zettel_privacy_events.py --live -q
```
Expected: 3 passed.

### Step 5 — Commit

```
feat: add append-only zettel privacy audit table
```

---

## Task 0.3 — Least-privilege `community_reader` role + RLS SELECT policy

**Files:**
- `supabase/website/_v2/87_community_reader_role.sql` (new)
- `supabase/website/_v2/87_community_reader_role.down.sql` (new)
- `tests/integration/v2/test_community_reader_role.py` (new)

Grounding: role idiom mirrors `79_stats_reader_role.sql` (idempotent `pg_roles` check; `CREATE ROLE ... NOLOGIN`; `ALTER ROLE ... SET statement_timeout/idle_in_transaction_session_timeout/lock_timeout/work_mem`; `GRANT USAGE ON SCHEMA ...`; static `GRANT SELECT ON <explicit tables>`). RLS policy idiom mirrors `29_kasten_sharing_rls.sql:63-73` + `08_rls_policies.sql:140-151` (`DROP POLICY IF EXISTS`; `CREATE POLICY ... FOR SELECT TO <role> USING (...)`). RLS is already ENABLED on `content.workspace_zettels` (`08:22`). **community_reader needs SELECT on the tables the SECURITY-DEFINER RPC reads** (it runs as the owner = community_reader): `content.workspace_zettels`, `content.canonical_zettels`, plus `core.workspaces` + `core.profiles` for the attribution display_name join. Grant USAGE on both `content` and `core` schemas. The policy predicate is the opt-out predicate: `USING (is_private = false AND deleted_at IS NULL)`.

### Step 1 — Write the failing test

`tests/integration/v2/test_community_reader_role.py`:

```python
"""Migration 87: community_reader least-privilege role + RLS fail-closed.

The decisive privacy upgrade: community_reader is NOLOGIN + NOT BYPASSRLS +
SELECT-only on the community surface. We prove fail-closed by SET ROLE
community_reader on the asyncpg connection (service_role/superuser session)
and asserting a PRIVATE row is invisible even with a bare SELECT, while a
default (public) row is visible.

@pytest.mark.live.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_role_exists_nologin_not_bypassrls(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = 'community_reader'"
        )
    assert row is not None, "community_reader role missing"
    assert row["rolcanlogin"] is False, "must be NOLOGIN"
    assert row["rolbypassrls"] is False, "must NOT bypass RLS (the whole point)"


@pytest.mark.asyncio
async def test_role_has_select_grants_on_community_surface(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        granted = {
            (r["table_schema"], r["table_name"])
            for r in await conn.fetch(
                """
                SELECT table_schema, table_name
                  FROM information_schema.role_table_grants
                 WHERE grantee = 'community_reader' AND privilege_type = 'SELECT'
                """
            )
        }
    assert ("content", "workspace_zettels") in granted
    assert ("content", "canonical_zettels") in granted
    assert ("core", "workspaces") in granted
    assert ("core", "profiles") in granted


@pytest.mark.asyncio
async def test_rls_fails_closed_under_set_role(asyncpg_pool, mint_user, bulk_insert_zettels):
    """A bare SELECT as community_reader returns ONLY public (is_private=false) rows."""
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=2, prefix="failclosed")
    public_id, private_id = wz_ids[0], wz_ids[1]
    async with asyncpg_pool.acquire() as conn:
        # bulk_insert_zettels creates default (public) rows; mark one private.
        await conn.execute(
            "UPDATE content.workspace_zettels SET is_private = true, made_private_at = now() WHERE id = $1",
            private_id,
        )
        # Impersonate the non-BYPASSRLS role within this (superuser) session.
        await conn.execute("SET ROLE community_reader")
        try:
            visible = {
                r["id"]
                for r in await conn.fetch(
                    "SELECT id FROM content.workspace_zettels WHERE id = ANY($1::uuid[])",
                    [public_id, private_id],
                )
            }
        finally:
            await conn.execute("RESET ROLE")
    assert public_id in visible, "public row must be visible to community_reader"
    assert private_id not in visible, "PRIVATE row leaked to community_reader — RLS not fail-closed"
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_community_reader_role.py --live -q
```
Expected: failures — role does not exist / `SET ROLE community_reader` errors.

### Step 3 — Minimal implementation

`supabase/website/_v2/87_community_reader_role.sql`:

```sql
-- Migration 87 (Community Graph Part B / Phase 0 — P0-c): least-privilege
-- public-read role + RLS fail-closed policy.
--
-- WHY: the app talks to Supabase via the service_role client, which has
-- BYPASSRLS — so RLS is INERT on the app path and the app-layer WHERE filter is
-- the only runtime gate there. The decisive upgrade (design D4, APPROVED
-- 2026-06-16): serve view=global through a SEPARATE non-BYPASSRLS, SELECT-only
-- role that OWNS the community RPC (migration 88). Because a SECURITY DEFINER
-- function executes as its owner, the RPC body runs as community_reader, and a
-- forgotten predicate then FAILS CLOSED at the row level via the policy below —
-- under opt-out, that policy protects the marked-PRIVATE subset.
--
-- Mirrors 79_stats_reader_role.sql (NOLOGIN role + hard timeouts + static
-- least-priv SELECT grants) and the RLS-policy idiom in 29_kasten_sharing_rls.sql.
-- community_reader needs SELECT on every table the RPC reads (it runs AS this
-- role): content.workspace_zettels + content.canonical_zettels (the surface) and
-- core.workspaces + core.profiles (attribution display_name join).
-- Idempotent: pg_roles guard + DROP/CREATE POLICY + IF NOT EXISTS grants.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'community_reader') THEN
    CREATE ROLE community_reader NOLOGIN;
  END IF;
END $$;

-- Hard guardrails (a runaway public-graph aggregation must not starve OLTP /
-- OOM the 2 GB droplet). Mirrors 79's stats_reader settings.
ALTER ROLE community_reader SET statement_timeout = '30s';
ALTER ROLE community_reader SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE community_reader SET lock_timeout = '5s';
ALTER ROLE community_reader SET work_mem = '32MB';

GRANT USAGE ON SCHEMA content, core TO community_reader;

-- Static least-privilege grant list. community_reader OWNS the community RPC
-- (88) and runs its body; these are exactly the tables that RPC reads.
GRANT SELECT ON
  content.workspace_zettels,
  content.canonical_zettels,
  core.workspaces,
  core.profiles
TO community_reader;

-- Fail-closed RLS: RLS is already ENABLED on content.workspace_zettels
-- (08_rls_policies.sql). Add a SELECT policy scoping community_reader to PUBLIC
-- (non-private, non-deleted) rows ONLY. service_role keeps BYPASSRLS (its own
-- FOR ALL policy is unchanged); authenticated's own-workspace SELECT policy is
-- unchanged; there is NO anon SELECT policy (verified) so PostgREST anon cannot
-- read this table.
DROP POLICY IF EXISTS workspace_zettels_community_reader_select ON content.workspace_zettels;
CREATE POLICY workspace_zettels_community_reader_select ON content.workspace_zettels
    FOR SELECT TO community_reader USING (is_private = false AND deleted_at IS NULL);

COMMIT;

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
```

`supabase/website/_v2/87_community_reader_role.down.sql`:

```sql
-- Reverse migration 87. Idempotent.
BEGIN;
  DROP POLICY IF EXISTS workspace_zettels_community_reader_select ON content.workspace_zettels;
  DO $$
  BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'community_reader') THEN
      -- Function 88 must be dropped (or re-owned) before the role can drop; the
      -- 88 down-migration handles that. If 88 is still present this REVOKE/DROP
      -- of grants is still safe.
      REVOKE SELECT ON
        content.workspace_zettels,
        content.canonical_zettels,
        core.workspaces,
        core.profiles
      FROM community_reader;
      REVOKE USAGE ON SCHEMA content, core FROM community_reader;
      DROP ROLE community_reader;
    END IF;
  END $$;
COMMIT;
NOTIFY pgrst, 'reload schema';
```

Apply:
```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
python ops/scripts/apply_migrations.py --v2 --update-manifest
```

### Step 4 — Run, expect PASS

```bash
pytest tests/integration/v2/test_community_reader_role.py --live -q
```
Expected: 3 passed (notably `test_rls_fails_closed_under_set_role`).

### Step 5 — Commit

```
feat: add community_reader role with fail-closed RLS
```

---

## Task 0.4 — Forced-predicate RPC `content.community_graph_v1`

**Files:**
- `supabase/website/_v2/88_community_graph_v1_rpc.sql` (new)
- `supabase/website/_v2/88_community_graph_v1_rpc.down.sql` (new)
- `tests/integration/v2/test_community_graph_v1_rpc.py` (new)

Grounding: SECURITY DEFINER + GRANT EXECUTE idiom mirrors `81_profile_stats_v1_rpc.sql:30-36,611-613` (`CREATE OR REPLACE FUNCTION ... LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public`; `REVOKE ALL FROM public`; `GRANT EXECUTE ... TO ...`). The new wrinkle: the function must be **OWNED BY community_reader** (so SECURITY DEFINER runs as the non-BYPASSRLS role) → `ALTER FUNCTION content.community_graph_v1(int, float) OWNER TO community_reader;`. Attribution join: `workspace_zettels.workspace_id → core.workspaces.owner_profile_id → core.profiles.display_name` (`01_core_schema.sql:5-24`). Dedup by `canonical_zettel_id` so one canonical saved by N users yields ONE node. Returns NO `user_id`, NO `made_private_at`, NO private rows. Node id is `'web-' || left(cz.id::text, 12)` style (opaque, derived from canonical id NOT user_id — matches existing node-id convention in `view_graph.py:167`). RETURNS TABLE → supabase-py returns a list of dicts (like `upsert_canonical_zettel`). Predicate flips to `WHERE wz.is_private = false AND wz.deleted_at IS NULL`. Public zettels SHOW the owner's `display_name` (the chosen attribution model).

### Step 1 — Write the failing test

`tests/integration/v2/test_community_graph_v1_rpc.py`:

```python
"""Migration 88: content.community_graph_v1 forced-predicate RPC.

@pytest.mark.live. Calls the RPC via the service_role client (the app's real
connection — BYPASSRLS) and asserts: only PUBLIC rows (is_private=false), no
user_id, dedup by canonical, attribution display_name.
"""
from __future__ import annotations

import pytest

from website.core.supabase_v2.client import get_v2_client

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_rpc_is_owned_by_community_reader(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        owner = await conn.fetchval(
            """
            SELECT r.rolname
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
              JOIN pg_roles r ON r.oid = p.proowner
             WHERE n.nspname = 'content' AND p.proname = 'community_graph_v1'
             LIMIT 1
            """
        )
    assert owner == "community_reader", f"RPC must be owned by community_reader, got {owner!r}"


@pytest.mark.asyncio
async def test_rpc_returns_public_only_no_user_id(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=2, prefix="rpcpub")
    public_id, private_id = wz_ids[0], wz_ids[1]
    async with asyncpg_pool.acquire() as conn:
        public_cz = await conn.fetchval(
            "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", public_id
        )
        private_cz = await conn.fetchval(
            "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", private_id
        )
        await conn.execute(
            "UPDATE content.workspace_zettels SET is_private = true, made_private_at = now() WHERE id = $1",
            private_id,
        )

    client = get_v2_client()
    resp = client.schema("content").rpc(
        "community_graph_v1", {"p_limit": 5000, "p_min_strength": 0.0}
    ).execute()
    rows = resp.data or []
    cz_ids = {str(r.get("canonical_zettel_id")) for r in rows}
    assert str(public_cz) in cz_ids, "public canonical missing from community graph"
    assert str(private_cz) not in cz_ids, "PRIVATE canonical leaked into community graph"
    for r in rows:
        assert "user_id" not in r, f"user_id leaked in payload: {r}"
        assert "owner_profile_id" not in r
        assert "made_private_at" not in r


@pytest.mark.asyncio
async def test_rpc_dedups_canonical_across_two_savers(asyncpg_pool, mint_user):
    """Two users saving the SAME canonical (both public) → exactly one community node."""
    user_a = mint_user(workspace_count=1)
    user_b = mint_user(workspace_count=1)
    async with asyncpg_pool.acquire() as conn:
        cz_id = await conn.fetchval(
            """
            INSERT INTO content.canonical_zettels (id, normalized_url, content_hash, source_type, title)
            VALUES (gen_random_uuid(), 'https://dedup-' || gen_random_uuid()::text || '.example.com/',
                    decode(md5(random()::text), 'hex'), 'web', 'dedup shared')
            RETURNING id
            """
        )
        for u in (user_a, user_b):
            await conn.execute(
                """
                INSERT INTO content.workspace_zettels
                  (workspace_id, canonical_zettel_id, ai_summary, user_tags, added_via, is_private)
                VALUES ($1, $2, '', ARRAY['dedup']::text[], 'website', false)
                """,
                u.workspace_ids[0], cz_id,
            )
    client = get_v2_client()
    resp = client.schema("content").rpc(
        "community_graph_v1", {"p_limit": 5000, "p_min_strength": 0.0}
    ).execute()
    matches = [r for r in (resp.data or []) if str(r.get("canonical_zettel_id")) == str(cz_id)]
    assert len(matches) == 1, f"expected 1 deduped node, got {len(matches)}"
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_community_graph_v1_rpc.py --live -q
```
Expected: failures — function `content.community_graph_v1` does not exist.

### Step 3 — Minimal implementation

`supabase/website/_v2/88_community_graph_v1_rpc.sql`:

```sql
-- Migration 88 (Community Graph Part B / Phase 0 — P0-c cont.): the forced-
-- predicate community read RPC. This is the ONLY read path for the community
-- surface (design D3/D4 — the predicate lives in the DB, not re-implemented in
-- Python). SECURITY DEFINER + OWNED BY community_reader means the body runs as
-- the non-BYPASSRLS role: a forgotten predicate fails closed via the RLS policy
-- from migration 87.
--
-- OPT-OUT predicate: returns PUBLIC nodes only (is_private = false AND
-- deleted_at IS NULL), deduped by canonical_zettel_id (one canonical saved by N
-- users => ONE node). NO user_id, NO owner_profile_id, NO made_private_at.
-- Attribution = the owner's display_name (the chosen public-attribution model;
-- anonymous mode is deferred). Node id is opaque + derived from the canonical id
-- (NOT user_id, so the id itself cannot fingerprint a user), matching the
-- existing assembler node-id convention ({prefix}-{canonical[:N]}).
--
-- Mirrors 81_profile_stats_v1_rpc.sql's SECURITY DEFINER + REVOKE/GRANT idiom.
-- This is a CREATE OR REPLACE code-object, but it is kept VERSIONED (not in
-- repeatable/R__) because it carries one-time ownership DDL (ALTER FUNCTION
-- OWNER) that must run AFTER role 87 exists; see plan DESIGN DECISIONS.

BEGIN;

CREATE OR REPLACE FUNCTION content.community_graph_v1(
    p_limit int DEFAULT 5000,
    p_min_strength float DEFAULT 0.0
)
RETURNS TABLE (
    canonical_zettel_id uuid,
    node_id             text,
    title               text,
    source_type         text,
    url                 text,
    author_display_name text,
    contributor_count   int
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- Per-call safety net (independent of role-level settings on community_reader).
  SET LOCAL statement_timeout = '30s';
  SET LOCAL work_mem = '32MB';

  RETURN QUERY
  WITH public_rows AS (
    SELECT
      cz.id                AS canonical_zettel_id,
      cz.title             AS title,
      cz.source_type       AS source_type,
      cz.normalized_url    AS url,
      -- Attribution: earliest saver's display_name (public-by-default model).
      (ARRAY_AGG(p.display_name ORDER BY wz.created_at ASC NULLS LAST))[1]
                           AS author_display_name,
      COUNT(DISTINCT wz.workspace_id)::int AS contributor_count
    FROM content.workspace_zettels wz
    JOIN content.canonical_zettels cz ON cz.id = wz.canonical_zettel_id
    JOIN core.workspaces w           ON w.id  = wz.workspace_id
    JOIN core.profiles   p           ON p.id  = w.owner_profile_id
    WHERE wz.is_private = false      -- the forced opt-out predicate (D3, Rev 3)
      AND wz.deleted_at IS NULL
    GROUP BY cz.id, cz.title, cz.source_type, cz.normalized_url
  )
  SELECT
    public_rows.canonical_zettel_id,
    'web-' || left(public_rows.canonical_zettel_id::text, 12) AS node_id,
    public_rows.title,
    public_rows.source_type,
    public_rows.url,
    public_rows.author_display_name,
    public_rows.contributor_count
  FROM public_rows
  ORDER BY public_rows.canonical_zettel_id
  LIMIT GREATEST(1, LEAST(p_limit, 10000));
END
$$;

-- The function must run AS community_reader (non-BYPASSRLS) so the RLS policy
-- bites if the predicate is ever dropped. OWNER change is the load-bearing DDL.
ALTER FUNCTION content.community_graph_v1(int, float) OWNER TO community_reader;

-- The app calls this via the service_role connection; only service_role needs
-- EXECUTE. Deny PUBLIC/anon/authenticated (no direct PostgREST exposure).
REVOKE ALL ON FUNCTION content.community_graph_v1(int, float) FROM public;
GRANT EXECUTE ON FUNCTION content.community_graph_v1(int, float) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
```

`supabase/website/_v2/88_community_graph_v1_rpc.down.sql`:

```sql
-- Reverse migration 88. Drop the function (also unblocks dropping
-- community_reader in 87.down). Idempotent.
BEGIN;
  DROP FUNCTION IF EXISTS content.community_graph_v1(int, float);
COMMIT;
NOTIFY pgrst, 'reload schema';
```

Apply:
```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
python ops/scripts/apply_migrations.py --v2 --update-manifest
```

### Step 4 — Run, expect PASS

```bash
pytest tests/integration/v2/test_community_graph_v1_rpc.py --live -q
```
Expected: 3 passed.

### Step 5 — Commit

```
feat: add community_graph_v1 forced-predicate RPC
```

---

## Task 0.5 — Forced-predicate repository wrapper (Python)

**Files:**
- `website/core/supabase_v2/repositories/community_repository.py` (new)
- `tests/integration/v2/test_community_repository.py` (new)

Grounding: RPC-call idiom mirrors `content_repository.py:40-58` (`self._client.schema("content").rpc("name", {params}).execute()`; `response.data` is a list for RETURNS TABLE). `get_v2_client()` from `website.core.supabase_v2.client`. `_first` helper pattern at `content_repository.py:716`. This wrapper is the SINGLE app entrypoint to the community surface — serving never calls the RPC directly. `set_private` (was `set_published`) flips `is_private`/`made_private_at`, inserts a `zettel_privacy_events` row, AND bumps the cache version — so the endpoint and any future caller cannot forget the audit + invalidation.

### Step 1 — Write the failing test

`tests/integration/v2/test_community_repository.py`:

```python
"""CommunityGraphRepository: the single forced-predicate app read path.

@pytest.mark.live.
"""
from __future__ import annotations

import pytest

from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_get_community_graph_returns_public_only(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=2, prefix="repo")
    public_id, private_id = wz_ids[0], wz_ids[1]
    async with asyncpg_pool.acquire() as conn:
        public_cz = await conn.fetchval(
            "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", public_id
        )
        private_cz = await conn.fetchval(
            "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", private_id
        )
        await conn.execute(
            "UPDATE content.workspace_zettels SET is_private = true, made_private_at = now() WHERE id = $1",
            private_id,
        )

    repo = CommunityGraphRepository()
    graph = repo.get_community_graph(limit=5000, min_strength=0.0)
    node_cz = {str(n["canonical_zettel_id"]) for n in graph["nodes"]}
    assert str(public_cz) in node_cz
    assert str(private_cz) not in node_cz
    # No user identifiers anywhere in nodes.
    for n in graph["nodes"]:
        assert "user_id" not in n and "owner_profile_id" not in n


@pytest.mark.asyncio
async def test_set_private_round_trips_and_audits(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="setpriv"))[0]
    repo = CommunityGraphRepository()
    repo.set_private(workspace_zettel_id=wz_id, private=True, actor_user_id=user.profile_id)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_private, made_private_at FROM content.workspace_zettels WHERE id = $1", wz_id
        )
        events = await conn.fetch(
            "SELECT action FROM content.zettel_privacy_events WHERE workspace_zettel_id = $1 ORDER BY created_at",
            wz_id,
        )
    assert row["is_private"] is True
    assert row["made_private_at"] is not None
    assert [e["action"] for e in events][-1] == "make_private"

    repo.set_private(workspace_zettel_id=wz_id, private=False, actor_user_id=user.profile_id)
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_private FROM content.workspace_zettels WHERE id = $1", wz_id
        )
        events = await conn.fetch(
            "SELECT action FROM content.zettel_privacy_events WHERE workspace_zettel_id = $1 ORDER BY created_at",
            wz_id,
        )
    assert row["is_private"] is False
    assert [e["action"] for e in events][-1] == "make_public"


@pytest.mark.asyncio
async def test_read_cache_version_returns_int(asyncpg_pool):
    repo = CommunityGraphRepository()
    v = repo.read_cache_version()
    assert isinstance(v, int) and v >= 0
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_community_repository.py --live -q
```
Expected: ImportError / collection error — module does not exist. (Note: `test_read_cache_version_returns_int` and the cache-bump inside `set_private` depend on Task 0.7's table; if running 0.5 before 0.7, mark that one test `@pytest.mark.xfail(reason="cache version table lands in Task 0.7")` and have `set_private` swallow a missing-table bump error defensively. The set_private/audit + get_community_graph tests pass standalone.)

### Step 3 — Minimal implementation

`website/core/supabase_v2/repositories/community_repository.py`:

```python
"""Repository for the PUBLIC community graph — the single forced-predicate path.

Every read of the community surface goes through ``get_community_graph``, which
calls ``content.community_graph_v1`` (SECURITY DEFINER, owned by the
non-BYPASSRLS ``community_reader`` role). The predicate ``is_private = false``
lives in the DB, not here — so a bug in this file cannot widen the surface
(the RLS policy fails closed). This class is the convenience layer, not the
security boundary.

Opt-OUT model: zettels are PUBLIC by default; ``set_private`` is the per-zettel
opt-out, which also writes the privacy-audit row and bumps the cache version so
no caller can forget either.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from supabase import Client

from website.core.supabase_v2.client import get_v2_client


class CommunityGraphRepository:
    def __init__(self, client: Client | None = None) -> None:
        self._client = client or get_v2_client()

    def get_community_graph(
        self, *, limit: int = 5000, min_strength: float = 0.0
    ) -> dict[str, Any]:
        """Return ``{"nodes": [...], "links": [...], "total_nodes": int}``.

        Nodes carry NO user_id. Links are empty in Phase 1 (edge computation is
        Phase 3); the shape stays graph-compatible so the frontend renders.
        """
        resp = (
            self._client.schema("content")
            .rpc(
                "community_graph_v1",
                {"p_limit": int(limit), "p_min_strength": float(min_strength)},
            )
            .execute()
        )
        rows = resp.data or []
        nodes: list[dict[str, Any]] = []
        for r in rows:
            nodes.append(
                {
                    "id": r["node_id"],
                    "canonical_zettel_id": str(r["canonical_zettel_id"]),
                    "name": r.get("title") or r["node_id"],
                    "group": r.get("source_type") or "web",
                    "url": r.get("url") or "",
                    "author": r.get("author_display_name"),
                    "contributor_count": int(r.get("contributor_count") or 1),
                }
            )
        return {"nodes": nodes, "links": [], "total_nodes": len(nodes)}

    def set_private(
        self, *, workspace_zettel_id: UUID, private: bool, actor_user_id: UUID | str | None
    ) -> None:
        """Flip is_private on ONE workspace_zettel (ownership checked upstream).

        Also writes an append-only zettel_privacy_events row and bumps the
        cross-worker cache version. made_private_at is set when going private and
        left as-is when going public (the events table is the authoritative log;
        the RPC never returns made_private_at, so it never leaks). Mutates via
        the service_role client; the privacy ENDPOINT enforces caller ownership
        before calling this.
        """
        update: dict[str, Any] = {"is_private": private}
        if private:
            update["made_private_at"] = datetime.now(timezone.utc).isoformat()
        (
            self._client.schema("content")
            .table("workspace_zettels")
            .update(update)
            .eq("id", str(workspace_zettel_id))
            .execute()
        )
        # Append-only privacy audit (one row per toggle).
        self._client.schema("content").table("zettel_privacy_events").insert(
            {
                "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
                "workspace_zettel_id": str(workspace_zettel_id),
                "action": "make_private" if private else "make_public",
            }
        ).execute()
        # Cross-worker cache invalidation (the public graph changed).
        try:
            self.bump_cache_version()
        except Exception:  # noqa: BLE001 — bump failure must not fail the toggle
            pass

    def read_cache_version(self) -> int:
        """Return the current community cache version counter (Task 0.7)."""
        resp = (
            self._client.schema("content")
            .table("community_cache_version")
            .select("version")
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return int(rows[0]["version"]) if rows else 0

    def bump_cache_version(self) -> int:
        """Atomically increment the counter; returns the new value (Task 0.7)."""
        resp = (
            self._client.schema("content")
            .rpc("bump_community_cache_version", {})
            .execute()
        )
        return int(resp.data) if resp.data is not None else 0
```

### Step 4 — Run, expect PASS

```bash
pytest tests/integration/v2/test_community_repository.py --live -q
```
Expected: `get_community_graph` + `set_private`/audit tests pass; the cache-version test passes after Task 0.7 (or xfail until then).

### Step 5 — Commit

```
feat: add community graph repository wrapper
```

---

## Task 0.6 — CI regression gate (the load-bearing privacy proof)

**Files:**
- `tests/integration/v2/test_community_graph_regression_gate.py` (new)

Grounding: this is the test the design (Rev 3 R3.1 #6) and research (§2.1/§2.2) mandate as a CI deploy gate — "Do not deploy changes that make the tests fail" (OWASP). It connects via the **service_role** path (the app's real BYPASSRLS connection) through the wrapper and proves the predicate holds anyway. Uses `mint_user` + `bulk_insert_zettels` + `asyncpg_pool`. The five assertions (Rev 3 R3.1 #6): (1) a `is_private=true` zettel NEVER appears even under service_role/BYPASSRLS; (2) a default (unmarked) zettel DOES appear; (3) flipping private→public toggles its presence; (4) no `user_id` in returned nodes; (5) an edge never touches a private node.

### Step 1 — Write the failing test

`tests/integration/v2/test_community_graph_regression_gate.py`:

```python
"""LOAD-BEARING PRIVACY PROOF — community read never leaks PRIVATE rows.

The app connects to Supabase via service_role (BYPASSRLS). This gate proves the
community read path (CommunityGraphRepository → community_graph_v1) still NEVER
returns an is_private=true row, that a default (public) zettel DOES appear, that
flipping private->public toggles presence, that no user_id is present, and that
no edge connects to a private node.

DO NOT DELETE OR SKIP THIS TEST. A failure here is a privacy breach, not a flake.
@pytest.mark.live.
"""
from __future__ import annotations

import pytest

from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


async def _cz_for(conn, wz_id):
    return await conn.fetchval(
        "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", wz_id
    )


@pytest.mark.asyncio
async def test_private_never_in_community_under_service_role(
    asyncpg_pool, mint_user, bulk_insert_zettels
):
    user = mint_user(workspace_count=1)
    wz_ids = await bulk_insert_zettels(owner_user=user, n=5, prefix="gate")
    # Mark 4 private; leave 1 public (default).
    async with asyncpg_pool.acquire() as conn:
        await conn.executemany(
            "UPDATE content.workspace_zettels SET is_private = true, made_private_at = now() WHERE id = $1",
            [(wz,) for wz in wz_ids[1:]],
        )
        private_cz = {str(await _cz_for(conn, wz)) for wz in wz_ids[1:]}
        public_cz = str(await _cz_for(conn, wz_ids[0]))

    repo = CommunityGraphRepository()
    graph = repo.get_community_graph(limit=5000, min_strength=0.0)
    returned_cz = {str(n["canonical_zettel_id"]) for n in graph["nodes"]}
    leaked = returned_cz & private_cz
    assert not leaked, f"PRIVACY BREACH: private canonicals returned: {leaked}"
    assert public_cz in returned_cz, "default (public) zettel must appear in community"


@pytest.mark.asyncio
async def test_make_private_then_public_toggles_node_presence(
    asyncpg_pool, mint_user, bulk_insert_zettels
):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="toggle"))[0]
    async with asyncpg_pool.acquire() as conn:
        cz = str(await _cz_for(conn, wz_id))

    repo = CommunityGraphRepository()
    # Default = public → present.
    assert cz in {str(n["canonical_zettel_id"]) for n in repo.get_community_graph()["nodes"]}, \
        "default public zettel missing from community"

    repo.set_private(workspace_zettel_id=wz_id, private=True, actor_user_id=user.profile_id)
    assert cz not in {str(n["canonical_zettel_id"]) for n in repo.get_community_graph()["nodes"]}, \
        "marking private did not remove the node"

    repo.set_private(workspace_zettel_id=wz_id, private=False, actor_user_id=user.profile_id)
    assert cz in {str(n["canonical_zettel_id"]) for n in repo.get_community_graph()["nodes"]}, \
        "marking public did not restore the node"


@pytest.mark.asyncio
async def test_no_user_id_and_edges_only_between_public(
    asyncpg_pool, mint_user, bulk_insert_zettels
):
    user = mint_user(workspace_count=1)
    await bulk_insert_zettels(owner_user=user, n=2, prefix="edge")
    repo = CommunityGraphRepository()
    graph = repo.get_community_graph()
    for n in graph["nodes"]:
        assert "user_id" not in n, f"user_id present: {n}"
    # Phase 1 ships zero edges; if/when edges exist, both endpoints must be in
    # the public node set. Assert the invariant defensively now.
    node_ids = {n["id"] for n in graph["nodes"]}
    for link in graph["links"]:
        src = link["source"] if isinstance(link["source"], str) else link["source"]["id"]
        dst = link["target"] if isinstance(link["target"], str) else link["target"]["id"]
        assert src in node_ids and dst in node_ids, "edge connects to a non-public node"
```

### Step 2 — Run, expect FAIL → then PASS

Because Tasks 0.1–0.5 already landed the schema/role/RPC/wrapper, this gate should PASS immediately when written correctly. To honor TDD, confirm the gate has teeth via a falsification check.

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_community_graph_regression_gate.py --live -q
```
Expected: PASS (3 passed) on a correct stack. **Falsification check (do once, then revert):** temporarily change migration 88's predicate to `WHERE true` in a scratch apply against a throwaway branch DB, re-run — the gate MUST go red (private rows appear) — then revert. Document the red run in the task's verification notes as proof the gate has teeth. (Never apply `WHERE true` to the real project.)

### Step 3 — (no impl; the gate guards Tasks 0.1–0.5)

If the gate is red on the real stack, STOP — that is a privacy defect in 0.1–0.4; debug via superpowers:systematic-debugging before proceeding.

### Step 4 — Run, expect PASS

```bash
pytest tests/integration/v2/test_community_graph_regression_gate.py --live -q
```
Expected: 3 passed.

### Step 5 — Commit

```
test: add community graph privacy regression gate
```

---

## Task 0.7 — Cross-worker cache version counter

**Files:**
- `supabase/website/_v2/89_community_cache_version.sql` (new)
- `supabase/website/_v2/89_community_cache_version.down.sql` (new)
- `tests/integration/v2/test_community_cache_version.py` (new)

Grounding: research §2.5 / Rev 3 R3.1 #7 — a single version-counter row + TTL backstop (poll at scale; `LISTEN/NOTIFY` does not scale). One row, one int, one bump RPC. Bumped on make-private/make-public (inside `set_private`). NEW table → explicit grants. The bump RPC is `SECURITY DEFINER` so the service_role app can call it; returns the new value. End with NOTIFY.

### Step 1 — Write the failing test

`tests/integration/v2/test_community_cache_version.py`:

```python
"""Migration 89: content.community_cache_version counter + bump RPC.

@pytest.mark.live.
"""
from __future__ import annotations

import pytest

from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_single_row_seeded(asyncpg_pool):
    async with asyncpg_pool.acquire() as conn:
        cnt = await conn.fetchval("SELECT count(*) FROM content.community_cache_version")
        ver = await conn.fetchval("SELECT version FROM content.community_cache_version LIMIT 1")
    assert cnt == 1, f"expected exactly one row, got {cnt}"
    assert ver is not None and ver >= 0


@pytest.mark.asyncio
async def test_bump_increments_monotonically(asyncpg_pool):
    repo = CommunityGraphRepository()
    before = repo.read_cache_version()
    after = repo.bump_cache_version()
    assert after == before + 1, f"bump not monotonic: {before} -> {after}"
    assert repo.read_cache_version() == after
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_community_cache_version.py --live -q
```
Expected: failures — relation `content.community_cache_version` does not exist.

### Step 3 — Minimal implementation

`supabase/website/_v2/89_community_cache_version.sql`:

```sql
-- Migration 89 (Community Graph Part B / Phase 0 — P1 prereq): cross-worker
-- cache coherency counter. The community graph is a single aggregate object;
-- "mark one node private => it (and its edges) vanish" can't be expressed
-- per-key, so we use a generation counter (research §2.5). Workers poll this int
-- once per TTL window (PgBouncer-safe; LISTEN/NOTIFY does not scale to the 10k+
-- write target). Bumped on make-private/make-public via set_private. NEW table
-- => explicit grants (08/64 GRANT ALL only cover <= their slot). Idempotent:
-- CREATE TABLE IF NOT EXISTS + seed-once INSERT guard.

BEGIN;
  SET LOCAL lock_timeout = '3s';

  CREATE TABLE IF NOT EXISTS content.community_cache_version (
      id        boolean PRIMARY KEY DEFAULT true CHECK (id),  -- single-row guard
      version   bigint NOT NULL DEFAULT 0,
      bumped_at timestamptz NOT NULL DEFAULT now()
  );

  INSERT INTO content.community_cache_version (id, version)
  VALUES (true, 0)
  ON CONFLICT (id) DO NOTHING;

  ALTER TABLE content.community_cache_version ENABLE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS community_cache_version_service_all ON content.community_cache_version;
  CREATE POLICY community_cache_version_service_all ON content.community_cache_version
      FOR ALL TO service_role USING (true) WITH CHECK (true);

  GRANT SELECT, UPDATE ON content.community_cache_version TO service_role;

  CREATE OR REPLACE FUNCTION content.bump_community_cache_version()
  RETURNS bigint
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
  DECLARE
    v bigint;
  BEGIN
    UPDATE content.community_cache_version
       SET version = version + 1, bumped_at = now()
     WHERE id = true
     RETURNING version INTO v;
    RETURN v;
  END
  $$;

  REVOKE ALL ON FUNCTION content.bump_community_cache_version() FROM public;
  GRANT EXECUTE ON FUNCTION content.bump_community_cache_version() TO service_role;
COMMIT;

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
```

`supabase/website/_v2/89_community_cache_version.down.sql`:

```sql
-- Reverse migration 89. Idempotent.
BEGIN;
  DROP FUNCTION IF EXISTS content.bump_community_cache_version();
  DROP TABLE IF EXISTS content.community_cache_version;
COMMIT;
NOTIFY pgrst, 'reload schema';
```

Apply:
```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
python ops/scripts/apply_migrations.py --v2 --update-manifest
```

### Step 4 — Run, expect PASS

```bash
pytest tests/integration/v2/test_community_cache_version.py --live -q
# Re-run the wrapper test now that the table exists:
pytest tests/integration/v2/test_community_repository.py --live -q
```
Expected: 2 passed (version) + repository tests green (including the version read + the set_private bump).

### Step 5 — Commit

```
feat: add community cache version counter
```

### PHASE 0 GATE

Run the whole Phase-0 suite green before any Phase-1 task:
```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_community_privacy_schema.py tests/integration/v2/test_zettel_privacy_events.py tests/integration/v2/test_community_reader_role.py tests/integration/v2/test_community_graph_v1_rpc.py tests/integration/v2/test_community_repository.py tests/integration/v2/test_community_graph_regression_gate.py tests/integration/v2/test_community_cache_version.py --live -q
```
Expected: all passed. The regression gate (0.6) MUST be green.

---

# PHASE 1 — MVP Public Community Graph

---

## Task 1.1 — Serving: build `view='global'` from the community wrapper (file-store RETIRED)

**Files:**
- `website/api/module_runners/view_graph.py` (modify the `resolved_view == "global"` branch, lines 272-297; `_load_global` is 277-284)
- `tests/integration/v2/test_view_graph_global_community.py` (new)

Grounding: current global branch (`view_graph.py:272-297`) builds from `_file_store_graph()` via `routes_mod._enrich_graph_with_analytics` + `_trim_graph_response`, cached via `_get_default_cache().get_or_load("__anon__", bucket, loader)`. We rebuild `_load_global` to call `CommunityGraphRepository().get_community_graph(...)` and **retire the file-store from the live path** (Rev 3 R3.1: Global IS the real all-public community graph — there is data). When the community returns 0 nodes we serve the empty graph (the JS layer shows the empty-state overlay, Task 1.6) — **NOT** the file-store. Enrich + trim; set `meta.source = "community"`. Keep the SWR cache; fold the cache version counter into the bucket key so a make-private/make-public bump invalidates all workers. Keep `_apply_min_strength_filter` post-cache. The existing cache already starts its refresh task post-fork (inside request handling) — no import-time thread.

### Step 1 — Write the failing test

`tests/integration/v2/test_view_graph_global_community.py`:

```python
"""run_view_graph view='global' is built from the community wrapper (no file-store).

@pytest.mark.live. Asserts the published-by-default node appears, meta.source is
'community' (never 'file-store'), and no user_id leaks into global nodes.
"""
from __future__ import annotations

import pytest

from website.api.module_runners.view_graph import run_view_graph
from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_global_includes_public_node(asyncpg_pool, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="vgglobal"))[0]
    async with asyncpg_pool.acquire() as conn:
        cz = str(await conn.fetchval(
            "SELECT canonical_zettel_id FROM content.workspace_zettels WHERE id = $1", wz_id
        ))
    # Default is public; bump cache so any prior cached payload is invalidated.
    CommunityGraphRepository().bump_cache_version()

    payload = await run_view_graph(user=None, view="global", limit=5000, offset=0, min_strength=0.0)
    node_cz = {str(n.get("canonical_zettel_id")) for n in payload.get("nodes", [])}
    assert cz in node_cz, "default public node missing from view=global"
    assert payload["meta"]["view"] == "global"
    assert payload["meta"]["source"] == "community", "global must be the real community, not file-store"
    for n in payload.get("nodes", []):
        assert "user_id" not in n


@pytest.mark.asyncio
async def test_global_source_is_always_community(asyncpg_pool, mint_user, bulk_insert_zettels):
    """Even if a private-only state existed, source must be 'community' (file-store retired)."""
    payload = await run_view_graph(user=None, view="global", limit=5000, offset=0, min_strength=0.0)
    assert payload["meta"]["source"] == "community"
    for n in payload.get("nodes", []):
        assert "user_id" not in n and "owner_profile_id" not in n
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_view_graph_global_community.py --live -q
```
Expected: failures — `meta.source` is `"file-store"` and the public node is absent (global still file-store-only).

### Step 3 — Minimal implementation

In `website/api/module_runners/view_graph.py`, add a lazy facade near the others (after `_file_store_graph`, ~line 89):

```python
def _community_repository() -> Any:
    from website.core.supabase_v2.repositories.community_repository import (
        CommunityGraphRepository,
    )

    return CommunityGraphRepository()
```

Replace the `resolved_view == "global"` block (lines 272-297) with:

```python
    if resolved_view == "global":
        # Part B (Phase 1, opt-OUT): global IS the PUBLIC community graph, built
        # from the forced-predicate wrapper (is_private=false workspace_zettels
        # only, no user_id, deduped by canonical). The file-store seed is RETIRED
        # from the live path — there is real community data. An empty community
        # surfaces the empty-state overlay client-side (Task 1.6); we never fall
        # back to the file-store.
        async def _load_global() -> dict[str, Any]:
            community = await asyncio.to_thread(
                _community_repository().get_community_graph,
                limit=limit,
                min_strength=0.0 if min_strength is None else min_strength,
            )
            payload = routes_mod._enrich_graph_with_analytics(community, min_strength=None)
            payload = routes_mod._trim_graph_response(payload)
            payload.setdefault("meta", {})["view"] = "global"
            payload["meta"]["source"] = "community"
            return payload

        if not _is_cacheable_page(limit, offset):
            uncached = await _load_global()
            return routes_mod._apply_min_strength_filter(uncached, min_strength)
        cache = _get_default_cache()
        # Fold the cross-worker version counter into the bucket so a make-private/
        # make-public bump invalidates every worker's per-process cache. Reading
        # the counter is one tiny indexed SELECT (TTL-bounded by the cache).
        try:
            version = await asyncio.to_thread(_community_repository().read_cache_version)
        except Exception:  # noqa: BLE001 — counter read must never break serving
            version = 0
        bucket = _bucket_label_global(min_strength) + f":v{version}"
        cached = await cache.get_or_load("__community__", bucket, _load_global)
        return routes_mod._apply_min_strength_filter(cached, min_strength)
```

(Note: the cache user-key changes `"__anon__"` → `"__community__"` so the community payload doesn't collide with any legacy anon file-store entry; existing `invalidate("__anon__")` calls in mutation handlers are harmless no-ops against the new key, and the version counter is the real invalidator. `_file_store_graph()` remains defined but is no longer referenced on the live global path; leave it in place for the CLI/seed tooling.)

### Step 4 — Run, expect PASS

```bash
pytest tests/integration/v2/test_view_graph_global_community.py --live -q
# Regression: Part A personal path still works.
pytest tests/integration/v2/test_api_graph_v2.py --live -q
```
Expected: 2 passed + Part A graph tests still green. (If a Part A test asserted `meta.source == "file-store"` for anonymous global, it must be updated to `"community"` in this task — that is the deliberate behavior change, not a regression. Flag any such test for the operator.)

### Step 5 — Commit

```
feat: serve global graph from community public surface
```

---

## Task 1.2 — Cache headers, client Authorization drop, and `view=my` hard-401

**Files:**
- `website/api/routes.py` (modify `graph_data`, lines 1656-1673 for headers; add the hard-401 branch before/after `run_view_graph`)
- `website/features/knowledge_graph/js/app.js` (modify `loadGraphData` fetch, line 793; `loadUserOwnedIds` 401-tolerance, line 545; helper inside fence)
- `tests/website/test_graph_data_global_headers.py` (new, unit)
- `tests/integration/v2/test_graph_my_hard_401.py` (new — anon 401 for my/kasten, anon-OK for global)
- `tests/js/knowledge_graph/build_graph_api_url_auth.test.js` (new, vitest)

Grounding (headers): current handler (`routes.py:1666-1670`) sets one header set for all views: `private, max-age=30, stale-while-revalidate=300` + `ETag` + `Vary: Accept-Encoding`. Rev 3 / research §2.4: `view=global` → `public, max-age=60, s-maxage=300, stale-while-revalidate=600` + `Vary: Accept-Encoding` ONLY + **no `Set-Cookie`** + DROP `Vary: Authorization`. `view=my`/`kasten` keep `private`.

Grounding (hard-401, NEW in Rev 3): `graph_data` (`routes.py:1568-1576`) depends on `Depends(get_optional_user)` (`auth.py:192`), so `user` is `dict | None`. `run_view_graph` (`view_graph.py:230`) resolves the view via `_resolve_view(user, view)` (`view_graph.py:137`), and for anonymous `view=my`/`kasten` currently returns `_empty_personal_graph(None)` (`view_graph.py:304-305`). The flip: at the **route layer**, when the *resolved* view is `my` or `kasten` and `user is None`, raise `HTTPException(401)` instead of returning the empty graph — WITHOUT swapping the dependency (that would break the anonymous `view=global` path, which must stay 200). The resolution rule mirrors `_resolve_view`: `view or ("my" if user is not None else "global")`; so an anonymous caller with an *explicit* `view=my`/`kasten` must 401, while an anonymous caller who omits `view` (resolves to `global`) stays 200. `get_current_user` (`auth.py:159-189`) already returns the canonical 401 detail strings ("Not authenticated"/"Token expired"); reuse the same `WWW-Authenticate: Bearer` discipline. **Part A regression checks (in this task):** the `zk_fetch` 401→refresh→banner pipeline (`auth.py:206-222` observability + frontend) must handle the new 401 on `view=my`; `loadUserOwnedIds` (`app.js:545`, a `view=my` fetch issued even while in Global) must not break the page when it 401s for a logged-out user — it must catch and degrade to "no owned ids" (the Personal toggle is already greyed for logged-out users in Part A).

Grounding (client auth): `loadGraphData` (`app.js:793`) currently sends `authHeaders()` for ALL views — drop Authorization when `currentView` maps to global. `buildGraphApiUrl` (`app.js:128-133`) is inside the fence (fence at `app.js:12-148`); add a pure `headersForView(view, authHeaders)` helper inside the fence and use it.

### Step 1 — Write the failing tests

`tests/website/test_graph_data_global_headers.py`:

```python
"""Unit test: /api/graph cache headers branch on view + my-anon hard-401.

view=global → public edge-cacheable, Vary: Accept-Encoding only, no Set-Cookie.
view=my → private, never edge-cacheable. Anonymous view=my → 401. Settings are
mocked (get_settings() unmocked raises SystemExit(1)).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    from website.app import create_app
    return TestClient(create_app())


def _patch_runner(payload):
    # Patch run_view_graph where graph_data imports it (function-local import).
    return patch(
        "website.api.module_runners.view_graph.run_view_graph",
        return_value=payload,
    )


def test_global_response_is_public_no_cookie(client):
    payload = {"nodes": [], "links": [], "total_nodes": 0, "meta": {"view": "global", "source": "community"}}
    with _patch_runner(payload):
        resp = client.get("/api/graph?view=global&min_strength=0.3")
    assert resp.status_code in (200, 304)
    cc = resp.headers.get("Cache-Control", "")
    assert "public" in cc, cc
    assert "s-maxage=300" in cc, cc
    assert "stale-while-revalidate=600" in cc, cc
    assert "private" not in cc, cc
    assert resp.headers.get("Vary") == "Accept-Encoding"
    assert "set-cookie" not in {k.lower() for k in resp.headers.keys()}


def test_my_response_stays_private(client):
    payload = {"nodes": [], "links": [], "total_nodes": 0, "meta": {"view": "my", "source": "v2"}}
    # Authenticated user fixture: patch get_optional_user to return a claims dict.
    with _patch_runner(payload), patch(
        "website.api.routes.get_optional_user", return_value={"sub": "u-1"}
    ):
        resp = client.get("/api/graph?view=my&min_strength=0.3")
    cc = resp.headers.get("Cache-Control", "")
    assert "private" in cc, cc
    assert "public" not in cc, cc
    # Must NOT advertise Vary: Authorization (Cloudflare ignores it; false safety).
    assert "authorization" not in resp.headers.get("Vary", "").lower()


def test_anonymous_my_is_hard_401(client):
    """Anonymous explicit view=my → 401 (Rev 3 hard-401), not an empty graph."""
    resp = client.get("/api/graph?view=my")
    assert resp.status_code == 401, resp.text
    assert "bearer" in resp.headers.get("WWW-Authenticate", "").lower()


def test_anonymous_global_still_ok(client):
    payload = {"nodes": [], "links": [], "total_nodes": 0, "meta": {"view": "global", "source": "community"}}
    with _patch_runner(payload):
        resp = client.get("/api/graph?view=global")
    assert resp.status_code in (200, 304)


def test_anonymous_omitted_view_resolves_global_ok(client):
    """No view + anonymous resolves to global → 200, NOT 401."""
    payload = {"nodes": [], "links": [], "total_nodes": 0, "meta": {"view": "global", "source": "community"}}
    with _patch_runner(payload):
        resp = client.get("/api/graph")
    assert resp.status_code in (200, 304)
```

`tests/integration/v2/test_graph_my_hard_401.py`:

```python
"""Live: anonymous view=my/kasten → 401; global stays anonymous-OK (Rev 3).

@pytest.mark.live — exercises the real route + auth dependency (no run_view_graph
patch), so it proves the route-layer 401 fires before any DB work.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live


@pytest.fixture
def v2_app(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    from website.app import create_app
    return create_app()


def test_anonymous_my_401(v2_app):
    with TestClient(v2_app) as client:
        assert client.get("/api/graph?view=my").status_code == 401


def test_anonymous_kasten_401(v2_app):
    import uuid
    with TestClient(v2_app) as client:
        r = client.get(f"/api/graph?view=kasten&kasten_id={uuid.uuid4()}")
    assert r.status_code == 401


def test_anonymous_global_200(v2_app):
    with TestClient(v2_app) as client:
        assert client.get("/api/graph?view=global").status_code in (200, 304)
```

`tests/js/knowledge_graph/build_graph_api_url_auth.test.js`:

```javascript
/**
 * Vitest: view=global must NOT send Authorization; view=my must send it.
 * Exercises the pure headersForView() helper from the test-exports fence.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const appSrc = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8'
);
const fenced = appSrc.match(/\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//)[1];
// eslint-disable-next-line no-new-func
const ctx = new Function(fenced + '; return { headersForView, buildGraphApiUrl };')();
const { headersForView, buildGraphApiUrl } = ctx;

describe('headersForView (Part B Phase 1)', () => {
  const authHeaders = () => ({ Authorization: 'Bearer tok' });
  it('drops Authorization for global', () => {
    expect(headersForView('global', authHeaders)).toEqual({});
  });
  it('keeps Authorization for my', () => {
    expect(headersForView('my', authHeaders)).toEqual({ Authorization: 'Bearer tok' });
  });
  it('treats any non-my view as global (binary)', () => {
    expect(headersForView('whatever', authHeaders)).toEqual({});
  });
});

describe('buildGraphApiUrl (Part A unchanged)', () => {
  it('still emits explicit view', () => {
    expect(buildGraphApiUrl('global', 0.3)).toContain('view=global');
    expect(buildGraphApiUrl('my', 0.3)).toContain('view=my');
  });
});
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/website/test_graph_data_global_headers.py -q
pytest tests/integration/v2/test_graph_my_hard_401.py --live -q
npx vitest run tests/js/knowledge_graph/build_graph_api_url_auth.test.js
```
Expected: pytest — `test_global_response_is_public_no_cookie` fails (header is `private`); `test_anonymous_my_is_hard_401` fails (returns 200 empty graph today). vitest — `headersForView is not a function`.

### Step 3 — Minimal implementation

In `website/api/routes.py` `graph_data`, add the hard-401 guard. Place it right after the `view` whitelist validation (after line 1614) so an anonymous explicit `my`/`kasten` 401s before any work:

```python
    # Rev 3 (operator-approved 2026-06-16): view=my / kasten REQUIRE auth.
    # Resolve the effective view exactly as run_view_graph does
    # (_resolve_view): an explicit view wins; otherwise infer from auth. An
    # anonymous caller asking for a personal/kasten view gets a hard 401 (the
    # Part A "empty personal graph for anon" fallthrough is retired) so the
    # frontend's zk_fetch 401->refresh->banner pipeline fires. Anonymous
    # global (explicit or inferred) stays 200.
    effective_view = view or ("my" if user is not None else "global")
    if effective_view in ("my", "kasten") and user is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

Then replace the header block (lines 1656-1673) with a view-branched version:

```python
    body = json.dumps(
        jsonable_encoder(payload), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    etag = 'W/"' + hashlib.blake2s(body, digest_size=16).hexdigest() + '"'

    resolved = (payload or {}).get("meta", {}).get("view") or view or (
        "my" if user is not None else "global"
    )
    if resolved == "global":
        # Part B Phase 1: the public community graph is edge-cacheable. public +
        # s-maxage lets Cloudflare cache; Vary: Accept-Encoding ONLY (Cloudflare
        # ignores every other Vary — Vary: Authorization is false safety). No
        # Set-Cookie is emitted on this path (a stray Set-Cookie forces CF
        # BYPASS). The JS client also drops Authorization for global.
        cache_headers = {
            "Cache-Control": "public, max-age=60, s-maxage=300, stale-while-revalidate=600",
            "ETag": etag,
            "Vary": "Accept-Encoding",
        }
    else:
        # view=my / kasten: per-user, NEVER edge-cached (Cloudflare async-SWR
        # would otherwise serve A's graph to B). Part A behaviour, unchanged.
        cache_headers = {
            "Cache-Control": "private, max-age=30, stale-while-revalidate=300",
            "ETag": etag,
            "Vary": "Accept-Encoding",
        }
    if if_none_match(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=cache_headers)
    return Response(content=body, media_type="application/json", headers=cache_headers)
```

In `website/features/knowledge_graph/js/app.js`, add inside the fence (after `buildGraphApiUrl`, before `authChangeDecision`):

```javascript
// Part B Phase 1: view=global is a PUBLIC, edge-cached response. Sending
// Authorization on it makes Cloudflare BYPASS the cache (and risks keying a
// private response). currentView is binary — anything not 'my' is global, which
// must be sent with NO Authorization header. view=my keeps auth.
function headersForView(view, authHeadersFn) {
  if (view === 'my') return authHeadersFn();
  return {};
}
```

Update `loadGraphData` (line 793) from:

```javascript
    zkFetch(apiUrl, { headers: authHeaders() })
```
to:
```javascript
    zkFetch(apiUrl, { headers: headersForView(currentView, authHeaders) })
```

`loadUserOwnedIds` (line 545, an explicit `view=my` fetch) keeps `authHeaders()` — but now must TOLERATE a 401 for a logged-out user without breaking the page. Ensure its fetch handler treats a 401 (or any non-OK) as "no owned ids" and returns an empty set rather than throwing (it already runs even while in Global to grey/enable the Personal toggle and to gate the Make-private button). Concretely, wrap the response check so a 401 resolves to `userOwnedIds = new Set()` and the function returns quietly; the existing `zk_fetch` 401→refresh path still attempts a refresh first for a genuinely-expired session, and only a truly-anonymous user falls through to the empty set.

### Step 4 — Run, expect PASS

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/website/test_graph_data_global_headers.py -q
pytest tests/integration/v2/test_graph_my_hard_401.py --live -q
npx vitest run tests/js/knowledge_graph/build_graph_api_url_auth.test.js
# Part A regression: existing KG vitest helpers still pass.
npx vitest run tests/js/knowledge_graph/cull_links.test.js tests/js/knowledge_graph/default_min_strength.test.js
```
Expected: pytest all passed (headers + hard-401 + anon-global-OK); vitest all green.

### Step 5 — Commit

```
feat: public cache headers, auth drop, my hard-401 for graph
```

---

## Task 1.3 — Ops note: Cloudflare Cache Rule (doc only, no code)

**Files:**
- `ops/runbooks/community-graph-cloudflare.md` (new, doc only)

Grounding: research §2.4 — a Cloudflare Cache Rule keyed on path + the `view` query param only; respect origin TTL; SWR on; verify `cf-cache-status` with curl. This is operations documentation, NOT code — no test. (Per CLAUDE.md: ops touches need approval; this is a runbook doc, but flag it for operator review before anyone applies the Cloudflare dashboard change.)

### Step 1 — (no test; documentation task)

### Step 2 — N/A

### Step 3 — Write the runbook

`ops/runbooks/community-graph-cloudflare.md`:

```markdown
# Cloudflare Cache Rule — public community graph (`/api/graph?view=global`)

**Status:** PROPOSED — requires operator approval before applying in the
Cloudflare dashboard. This is the CDN half of Part B Phase 1; the origin already
sends `public, max-age=60, s-maxage=300, stale-while-revalidate=600` +
`Vary: Accept-Encoding` and emits no `Set-Cookie` for `view=global`.

## Rule
- **When incoming requests match:** `URI Path equals /api/graph` AND
  `URI Query String contains "view=global"`.
- **Then — Cache eligibility:** *Eligible for cache*.
- **Cache Key → Query String:** *Include only* `view` (ignore all other query
  params: `min_strength`, `limit`, `offset` are folded server-side / not part of
  the public cache identity). This prevents cache fragmentation AND web-cache-
  deception (no `;.css`/`.css` suffix can produce a cacheable variant).
- **Edge TTL:** *Respect origin TTL* (honours `s-maxage=300`).
- **Browser TTL:** *Override to 60s*.
- **Serve stale while revalidating:** *ON*.

## Why no `Vary: Authorization`
Cloudflare ignores every `Vary` value except `Accept-Encoding`. Private safety
for `view=my` rests on `private`/hard-401 + the client dropping Authorization on
global + this rule keying only on path+`view` — never on `Vary`.

## Verify after applying
```bash
# First request warms the edge; second should HIT.
curl -sI "https://zettelkasten.in/api/graph?view=global&min_strength=0.3" | grep -i cf-cache-status
curl -sI "https://zettelkasten.in/api/graph?view=global&min_strength=0.3" | grep -i cf-cache-status
# Expect: cf-cache-status: MISS (or EXPIRED) then HIT.
# Confirm a private call is NEVER cached, and anon view=my is 401:
curl -sI -H "Authorization: Bearer <tok>" "https://zettelkasten.in/api/graph?view=my" | grep -iE 'cf-cache-status|cache-control'
curl -sI "https://zettelkasten.in/api/graph?view=my" | grep -iE 'HTTP/|www-authenticate'
# Expect: authed → cf-cache-status: DYNAMIC/BYPASS, Cache-Control: private; anon → HTTP 401.
```
Cloudflare Free-plan async SWR is non-uniform per open reports — re-verify
`cf-cache-status` behaviour on this zone before relying on stale-serving.
```

### Step 4 — Verify it renders / links are valid

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
python -c "import pathlib; print(pathlib.Path('ops/runbooks/community-graph-cloudflare.md').read_text(encoding='utf-8')[:200])"
```
Expected: prints the runbook header.

### Step 5 — Commit

```
docs: add Cloudflare cache rule note for global graph
```

---

## Task 1.4 — Privacy UX: pure JS helpers (toggle state, label, badge)

**Files:**
- `website/features/knowledge_graph/js/app.js` (add helpers inside the fence)
- `tests/js/knowledge_graph/privacy_helpers.test.js` (new, vitest)

Grounding: vitest fence-extraction idiom from `tests/js/knowledge_graph/cull_links.test.js`; fence at `app.js:12-148`. Pure helpers only (no DOM, no THREE). They drive: the Make-private toggle's pressed state + label (default = public/shown, so the action label is "Make private" → "Make public"), and the **teal "Private"** badge text/class shown on hidden zettels. There is **no consent modal** under opt-out (the signup notice in Task 1.8 is the consent surface); subsequent toggles use an undo toast. The DOM wiring (button click → fetch → badge → toast) is added in Task 1.5; these are the unit-tested decisions.

### Step 1 — Write the failing test

`tests/js/knowledge_graph/privacy_helpers.test.js`:

```javascript
/**
 * Vitest for pure privacy-toggle helpers (Part B Phase 1, opt-out model).
 * Fence-extracted from app.js (see test-exports markers).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const appSrc = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8'
);
const fenced = appSrc.match(/\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//)[1];
// eslint-disable-next-line no-new-func
const ctx = new Function(
  fenced + '; return { privacyToggleLabel, privacyBadge, undoToastText };'
)();
const { privacyToggleLabel, privacyBadge, undoToastText } = ctx;

describe('privacyToggleLabel', () => {
  it('public zettel → offers "Make private"', () => {
    expect(privacyToggleLabel(false)).toBe('Make private');
  });
  it('private zettel → offers "Make public"', () => {
    expect(privacyToggleLabel(true)).toBe('Make public');
  });
});

describe('privacyBadge (teal, never amber/purple)', () => {
  it('returns a teal Private badge spec when private', () => {
    const b = privacyBadge(true);
    expect(b.visible).toBe(true);
    expect(b.text).toBe('Private');
    expect(b.className).toContain('kg-private-badge');
  });
  it('hidden when public', () => {
    expect(privacyBadge(false)).toEqual({ visible: false, text: '', className: '' });
  });
});

describe('undoToastText', () => {
  it('made-private toast offers undo', () => {
    expect(undoToastText(true)).toBe('Marked private. Undo?');
  });
  it('made-public toast offers undo', () => {
    expect(undoToastText(false)).toBe('Made public. Undo?');
  });
});
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
npx vitest run tests/js/knowledge_graph/privacy_helpers.test.js
```
Expected: `privacyToggleLabel is not a function`.

### Step 3 — Minimal implementation

In `website/features/knowledge_graph/js/app.js`, add inside the fence (after `headersForView`):

```javascript
// Part B Phase 1 — pure privacy-UX helpers (DOM wiring lives outside the fence).
// Opt-OUT model: zettels are public by default; the action toggles privacy.
function privacyToggleLabel(isPrivate) {
  return isPrivate ? 'Make public' : 'Make private';
}
// Persistent "Private" badge spec, shown ONLY on hidden zettels. TEAL only
// (amber is reserved for the /knowledge-graph 3D viz; never purple). Returns a
// spec the DOM layer applies.
function privacyBadge(isPrivate) {
  if (!isPrivate) return { visible: false, text: '', className: '' };
  return { visible: true, text: 'Private', className: 'kg-private-badge' };
}
// Undo toast copy after a toggle (NN/G: reversible action over a blocking modal).
function undoToastText(nowPrivate) {
  return nowPrivate ? 'Marked private. Undo?' : 'Made public. Undo?';
}
```

Defining them inside the fence is sufficient — each vitest file constructs its own `new Function(... return {names})`.

### Step 4 — Run, expect PASS

```bash
npx vitest run tests/js/knowledge_graph/privacy_helpers.test.js
```
Expected: all green.

### Step 5 — Commit

```
feat: add pure privacy-toggle UI helpers
```

---

## Task 1.5 — Privacy endpoint + DOM wiring (toggle, undo toast, badge)

**Files:**
- `website/api/routes.py` (add `POST /api/zettels/{workspace_zettel_id}/private` + `/public`)
- `website/features/knowledge_graph/index.html` (Make-private button in side panel + Private badge markup; bump `app.js?v=`)
- `website/features/knowledge_graph/js/app.js` (DOM wiring: button → fetch → badge → undo toast)
- `tests/integration/v2/test_privacy_endpoint.py` (new, live)

Grounding: authed-mutation pattern mirrors `sandbox_routes.py` (`Depends(get_current_user)` at `auth.py:159`; `get_supabase_v2_scope(user["sub"])` returning `(content_repo, profile_id, workspace_id)` at `persist.py:274`; BOLA → 403 via ownership check). Ownership check: the caller's `workspace_id` must own the `workspace_zettel` (query `content.workspace_zettels WHERE id=$1 AND workspace_id=$2 AND deleted_at IS NULL`). On toggle: `CommunityGraphRepository.set_private(...)` (which itself writes the `zettel_privacy_events` row AND bumps the cache version — the endpoint does NOT duplicate those). Two endpoints (`/private`, `/public`) mirror the helper's binary; a single toggle endpoint is the alternative (see DESIGN DECISIONS — two-endpoint chosen for idempotency + clean audit). Side-panel button home = next to `panel-add-kasten` (`index.html:220`). Badge follows the existing badge markup conventions; teal styling. `app.js?v=` bump at `index.html:376`.

### Step 1 — Write the failing test

`tests/integration/v2/test_privacy_endpoint.py`:

```python
"""POST /api/zettels/{id}/private + /public (Part B Phase 1, opt-out).

@pytest.mark.live. Asserts: owner can mark private/public, ownership is enforced
(403 for a non-owner), a zettel_privacy_events row is written, the cache version
bumps, and the node then disappears from / reappears in view=global.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

pytestmark = pytest.mark.live


@pytest.fixture
def v2_app(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    from website.api import auth as auth_mod
    auth_mod._jwks_client = None
    from website.core import persist as persist_mod
    persist_mod._v2_core_repo = None
    persist_mod._v2_content_repo = None
    from website.app import create_app
    return create_app()


def _hdr(jwt):
    return {"Authorization": f"Bearer {jwt}"}


@pytest.mark.asyncio
async def test_owner_make_private_writes_audit_and_bumps_version(
    v2_app, asyncpg_pool, mint_user, bulk_insert_zettels
):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="privapi"))[0]

    repo = CommunityGraphRepository()
    before_version = repo.read_cache_version()

    with TestClient(v2_app) as client:
        resp = client.post(f"/api/zettels/{wz_id}/private", headers=_hdr(user.jwt))
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_private"] is True

    assert repo.read_cache_version() == before_version + 1, "cache version not bumped on toggle"
    async with asyncpg_pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT action FROM content.zettel_privacy_events WHERE workspace_zettel_id = $1 "
            "ORDER BY created_at DESC LIMIT 1",
            wz_id,
        )
    assert last == "make_private"


@pytest.mark.asyncio
async def test_non_owner_cannot_toggle(v2_app, mint_user, bulk_insert_zettels):
    owner = mint_user(workspace_count=1)
    attacker = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=owner, n=1, prefix="bola"))[0]
    with TestClient(v2_app) as client:
        resp = client.post(f"/api/zettels/{wz_id}/private", headers=_hdr(attacker.jwt))
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_make_public_round_trip(v2_app, mint_user, bulk_insert_zettels):
    user = mint_user(workspace_count=1)
    wz_id = (await bulk_insert_zettels(owner_user=user, n=1, prefix="pubround"))[0]
    with TestClient(v2_app) as client:
        assert client.post(f"/api/zettels/{wz_id}/private", headers=_hdr(user.jwt)).status_code == 200
        resp = client.post(f"/api/zettels/{wz_id}/public", headers=_hdr(user.jwt))
    assert resp.status_code == 200
    assert resp.json()["is_private"] is False
```

> Implementation note for the test author: `bulk_insert_zettels` / `asyncpg_pool` in `tests/integration/v2/conftest.py` are async fixtures. These tests are `@pytest.mark.asyncio`, `await` the seeders, and call the sync `TestClient` inside the async test (Starlette's TestClient runs its own loop) — exactly the pattern in `test_view_graph_global_community.py`.

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_privacy_endpoint.py --live -q
```
Expected: 404 on `POST /api/zettels/{id}/private` (route absent).

### Step 3 — Minimal implementation

In `website/api/routes.py`, add (near the other authed routes; reuse existing imports `Depends`, `HTTPException`, `Annotated`, `get_current_user` — import `get_current_user` from `website.api.auth` if not already imported at top):

```python
@router.post("/zettels/{workspace_zettel_id}/private")
async def make_zettel_private(
    workspace_zettel_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Hide ONE of the caller's zettels from the community graph (opt-out).

    Verifies ownership (BOLA → 403), flips is_private=true. The repository
    writes the append-only privacy-audit row and bumps the cross-worker cache
    version. Zettels are PUBLIC by default; this is the explicit opt-out action.
    """
    return await _set_zettel_private(workspace_zettel_id, user, private=True)


@router.post("/zettels/{workspace_zettel_id}/public")
async def make_zettel_public(
    workspace_zettel_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Restore the caller's zettel to the community graph. Ownership enforced."""
    return await _set_zettel_private(workspace_zettel_id, user, private=False)


async def _set_zettel_private(workspace_zettel_id: str, user: dict, *, private: bool):
    from uuid import UUID as _UUID

    from website.core.persist import get_supabase_v2_scope
    from website.core.supabase_v2.client import get_v2_client
    from website.core.supabase_v2.repositories.community_repository import (
        CommunityGraphRepository,
    )

    try:
        wz_uuid = _UUID(str(workspace_zettel_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="workspace_zettel_id must be a UUID")

    scope = get_supabase_v2_scope(user.get("sub"))
    if scope is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    _content_repo, profile_id, workspace_id = scope

    client = get_v2_client()
    # Ownership: the caller's workspace must own this overlay row (BOLA gate).
    owned = (
        client.schema("content")
        .table("workspace_zettels")
        .select("id")
        .eq("id", str(wz_uuid))
        .eq("workspace_id", str(workspace_id))
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    if not (owned.data or []):
        raise HTTPException(status_code=403, detail="Forbidden")

    repo = CommunityGraphRepository(client)
    # set_private writes the zettel_privacy_events audit row AND bumps the
    # cross-worker cache version internally — do NOT duplicate them here.
    repo.set_private(
        workspace_zettel_id=wz_uuid, private=private, actor_user_id=profile_id
    )
    return {"workspace_zettel_id": str(wz_uuid), "is_private": private}
```

In `website/features/knowledge_graph/index.html`:
- Add a Make-private button next to `panel-add-kasten` (after line 222), e.g.:
```html
        <button class="kg-panel-icon-btn" id="panel-privacy" type="button" title="Make private" aria-label="Make private" aria-pressed="false">
          <span class="kg-panel-icon-mask" style="--mask-url: url(/artifacts/icon-eye-off.svg)"></span>
        </button>
```
(If `/artifacts/icon-eye-off.svg` does not exist, inline an SVG mirroring the close button at `index.html:224` — see DESIGN DECISIONS.)
- Add a teal "Private" badge span in the meta row (near `panel-badge`, line 210):
```html
        <span class="kg-private-badge hidden" id="panel-private-badge">Private</span>
```
- Add CSS: `.kg-private-badge { background: rgba(20,184,166,0.15); color: #14b8a6; border: 1px solid #14b8a6; ... }` (teal, never amber/purple).
- Bump the app.js cache-bust at line 376: `app.js?v=20260617a`.

In `website/features/knowledge_graph/js/app.js` (DOM wiring, OUTSIDE the fence — uses the pure helpers from Task 1.4): wire `#panel-privacy` click → `POST /api/zettels/{id}/private` (or `/public` when currently private) with `authHeaders()` (this is an authed mutation, keep auth); on success flip the in-memory node state, update `aria-pressed` + the button title via `privacyToggleLabel`, toggle `#panel-private-badge` via `privacyBadge`, show an undo toast via `undoToastText` (clicking Undo re-POSTs the inverse endpoint); if currently in global view call `loadGraphData()` to refresh. Only show the Make-private button when the selected node is user-owned (reuse `userOwnedIds` from `loadUserOwnedIds`). There is NO consent modal here — the signup notice (Task 1.8) is the consent surface.

### Step 4 — Run, expect PASS

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
pytest tests/integration/v2/test_privacy_endpoint.py --live -q
npx vitest run tests/js/knowledge_graph/privacy_helpers.test.js
```
Expected: endpoint tests pass (owner toggle 200 + audit + bump; non-owner 403; public round-trip); vitest green.

### Step 5 — Commit

```
feat: add privacy endpoints and KG make-private toggle
```

---

## Task 1.6 — Personal/Community toggle maps Global → real community + empty-state overlay

**Files:**
- `website/features/knowledge_graph/js/app.js` (empty-community overlay decision; ensure toggle still calls loadGraphData)
- `website/features/knowledge_graph/index.html` (empty-community overlay element, if not reusing `overlay-empty`)
- `tests/js/knowledge_graph/privacy_helpers.test.js` (extend with a `communityEmptyState` helper test) OR a new small vitest file

Grounding: Part A toggle wiring is at `app.js:640-650` (`currentView = newView; ... loadGraphData()`) and the auth-state sync at `app.js:657-673`. `loadGraphData` already shows `overlay-empty`/`overlay-error` (`app.js:786-788, 884-885`). The toggle ALREADY calls `loadGraphData()`, and Task 1.1 made global = community (file-store retired) — so the mapping is done; this task adds the empty-community UX ("No community zettels yet") which is now the ONLY empty-global path (no file-store fallback to mask it). Keep it a pure helper + minimal DOM.

### Step 1 — Write the failing test

Append to `tests/js/knowledge_graph/privacy_helpers.test.js` (or new file `community_empty_overlay.test.js`):

```javascript
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const appSrc = readFileSync(resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'), 'utf8');
const fenced = appSrc.match(/\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//)[1];
// eslint-disable-next-line no-new-func
const ctx = new Function(fenced + '; return { communityEmptyState };')();
const { communityEmptyState } = ctx;

describe('communityEmptyState', () => {
  it('global view with zero nodes → show empty overlay', () => {
    expect(communityEmptyState('global', 0)).toEqual({ show: true, text: 'No community zettels yet' });
  });
  it('global view with nodes → no overlay', () => {
    expect(communityEmptyState('global', 5).show).toBe(false);
  });
  it('my view with zero nodes → not the community overlay (Part A empty handles it)', () => {
    expect(communityEmptyState('my', 0).show).toBe(false);
  });
});
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
npx vitest run tests/js/knowledge_graph/privacy_helpers.test.js
```
Expected: `communityEmptyState is not a function`.

### Step 3 — Minimal implementation

Add inside the fence in `app.js`:

```javascript
// Part B Phase 1 — community empty-state decision. Only the GLOBAL view shows
// the "No community zettels yet" overlay; the Personal view keeps its own Part A
// empty-state ("No zettels yet — add one"). With the file-store retired, this is
// the ONLY empty-global path. Pure decision; DOM layer applies it.
function communityEmptyState(view, nodeCount) {
  if (view === 'global' && (Number(nodeCount) || 0) === 0) {
    return { show: true, text: 'No community zettels yet' };
  }
  return { show: false, text: '' };
}
```

In `loadGraphData`'s success handler (after `fullData` is set, ~`app.js:800`), apply it via the existing overlay helpers:

```javascript
        var _empty = communityEmptyState(currentView, (data.nodes || []).length);
        if (_empty.show) { showOverlay('overlay-empty', _empty.text); }
        else { hideOverlay('overlay-empty'); }
```

(Reuse the existing `overlay-empty` element; no new HTML needed unless the operator wants distinct copy.)

### Step 4 — Run, expect PASS

```bash
npx vitest run tests/js/knowledge_graph/privacy_helpers.test.js
# Full KG vitest regression:
npx vitest run tests/js/knowledge_graph/
```
Expected: all green (including Part A helpers).

### Step 5 — Commit

```
feat: community empty-state overlay for global view
```

---

## Task 1.7 — Phase 1 end-to-end verification gate

**Files:** none new — runs the full suite.

### Step 1–4 — Run all Part B tests + Part A regressions

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
# Phase 0 + Phase 1 live DB tests:
pytest tests/integration/v2/test_community_privacy_schema.py tests/integration/v2/test_zettel_privacy_events.py tests/integration/v2/test_community_reader_role.py tests/integration/v2/test_community_graph_v1_rpc.py tests/integration/v2/test_community_repository.py tests/integration/v2/test_community_graph_regression_gate.py tests/integration/v2/test_community_cache_version.py tests/integration/v2/test_view_graph_global_community.py tests/integration/v2/test_graph_my_hard_401.py tests/integration/v2/test_privacy_endpoint.py --live -q
# Unit + Part A regressions:
pytest tests/website/test_graph_data_global_headers.py -q
pytest tests/integration/v2/test_api_graph_v2.py --live -q
# All KG + user_home vitest:
npx vitest run tests/js/knowledge_graph/ tests/js/user_home/
# Lint (one final pass, per "batch ruff at end" rule):
ruff check website/ tests/
```
Expected: everything green; the privacy regression gate (Task 0.6) green; the my-anon hard-401 green; Part A graph + KG vitest green; ruff clean.

### Step 5 — Commit (only if final lint fixes were needed)

```
chore: lint pass for community graph part b
```

---

## Task 1.8 — Signup / first-use public-content NOTICE (the consent surface)

**Files:**
- `website/features/user_home/index.html` (dismissible teal notice in the welcome block)
- `website/features/user_home/js/home.js` (pure notice helper inside a NEW test-export fence + DOM wiring in `init()`)
- `website/features/user_home/css/home.css` (teal notice styling)
- `tests/js/user_home/signup_notice.test.js` (new, vitest)

Grounding: this is the Rev 3 R3.3 NEW requirement — the consent surface that REPLACES the per-publish modal. It must clearly state that saved zettels are public + attributed + how to mark private, be dismissible, teal, no purple. **Home choice (verified):** `website/features/user_home/index.html` has a `home-welcome` block (`<div class="home-welcome" id="home-welcome">`, lines 22-24) shown to every logged-in user on `/home` — the natural home for a first-visit banner (a logged-in user has already saved or is about to). `home.js` has `async function init()` (line 197) wired via `document.addEventListener('DOMContentLoaded', init)` (line 2029) but **no existing test-export fence** — add one matching the `app.js:12` convention (`/* test-exports:start */ ... /* test-exports:end */`). Dismissal persists in `localStorage` (`kg.publicNoticeDismissed='1'`) so it shows once. This is a logged-in surface (not the public landing page) so it reaches the user who actually owns zettels; the signup/auth flow is OAuth-redirect (no app-owned signup form to host copy in), so `/home` first-visit is the correct surface. See DESIGN DECISIONS for the home rationale + alternative.

### Step 1 — Write the failing test

`tests/js/user_home/signup_notice.test.js`:

```javascript
/**
 * Vitest for the pure signup/first-use public-content notice helper.
 * Fence-extracted from home.js (new test-exports markers added in this task).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const homeSrc = readFileSync(
  resolve(__dirname, '../../../website/features/user_home/js/home.js'),
  'utf8'
);
const fenced = homeSrc.match(/\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//)[1];
// eslint-disable-next-line no-new-func
const ctx = new Function(fenced + '; return { shouldShowPublicNotice, publicNoticeText };')();
const { shouldShowPublicNotice, publicNoticeText } = ctx;

describe('shouldShowPublicNotice', () => {
  it('shows when never dismissed', () => {
    expect(shouldShowPublicNotice(null)).toBe(true);
    expect(shouldShowPublicNotice('')).toBe(true);
  });
  it('hidden once dismissed', () => {
    expect(shouldShowPublicNotice('1')).toBe(false);
  });
});

describe('publicNoticeText', () => {
  it('states zettels are public + attributed + how to hide', () => {
    const t = publicNoticeText();
    expect(t).toContain('public');
    expect(t.toLowerCase()).toContain('display name');
    expect(t.toLowerCase()).toContain('private');
  });
});
```

### Step 2 — Run, expect FAIL

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
npx vitest run tests/js/user_home/signup_notice.test.js
```
Expected: extraction fails / `shouldShowPublicNotice is not a function` (no fence in home.js yet).

### Step 3 — Minimal implementation

In `website/features/user_home/js/home.js`, add near the top of the file (before `init`) a test-export fence matching the `app.js` convention:

```javascript
/* test-exports:start */
// Pure helpers — extracted so vitest can exercise them without booting the DOM.
// The fence markers are load-bearing — tests/js/user_home/*.test.js regex-
// extracts everything between them. Edit with care. (Mirrors app.js:12.)

// Part B Phase 1 (opt-out): the public-content NOTICE is the consent surface
// that replaces the per-publish modal. Show it once per browser until dismissed.
function shouldShowPublicNotice(dismissedFlag) {
  return !dismissedFlag;
}
function publicNoticeText() {
  return 'Your saved zettels are public and shown with your display name. ' +
         'Mark any private to hide it.';
}
/* test-exports:end */
```

In `init()` (around line 197+), wire the notice once the welcome block is in the DOM:

```javascript
  // Public-content notice (opt-out consent surface). Shows once; teal; no purple.
  try {
    var _noticeEl = document.getElementById('home-public-notice');
    if (_noticeEl) {
      if (shouldShowPublicNotice(localStorage.getItem('kg.publicNoticeDismissed'))) {
        var _txt = _noticeEl.querySelector('.home-public-notice-text');
        if (_txt) { _txt.textContent = publicNoticeText(); }
        _noticeEl.classList.remove('hidden');
      }
      var _dismiss = document.getElementById('home-public-notice-dismiss');
      if (_dismiss) {
        _dismiss.addEventListener('click', function () {
          localStorage.setItem('kg.publicNoticeDismissed', '1');
          _noticeEl.classList.add('hidden');
        });
      }
    }
  } catch (_e) { /* notice is non-critical; never block home render */ }
```

In `website/features/user_home/index.html`, add the dismissible notice inside the welcome block (after line 24, inside/under `#home-welcome`):

```html
            <div class="home-public-notice hidden" id="home-public-notice" role="note">
              <span class="home-public-notice-text"></span>
              <button class="home-public-notice-dismiss" id="home-public-notice-dismiss" type="button" aria-label="Dismiss">Got it</button>
            </div>
```
Bump the home.js cache-bust where it is loaded (the `<script src="/home/js/home.js?v=...">` tag near the bottom of `index.html`): `home.js?v=20260617a`.

In `website/features/user_home/css/home.css`, add teal styling (never purple):

```css
.home-public-notice {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.75rem;
  padding: 0.6rem 0.9rem;
  background: rgba(20, 184, 166, 0.10);
  border: 1px solid #14b8a6;
  border-radius: 8px;
  color: #0f766e;
  font-size: 0.9rem;
}
.home-public-notice.hidden { display: none; }
.home-public-notice-dismiss {
  margin-left: auto;
  background: #14b8a6;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 0.3rem 0.7rem;
  cursor: pointer;
  font-size: 0.85rem;
}
```

### Step 4 — Run, expect PASS

```bash
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/community-graph-partb
npx vitest run tests/js/user_home/signup_notice.test.js
# Regression: no existing user_home vitest to break, but confirm KG fence still extracts:
npx vitest run tests/js/knowledge_graph/
```
Expected: notice tests green; KG vitest still green.

### Step 5 — Commit

```
feat: add public-content signup notice on home
```

---

## Self-Review

### Spec-coverage checklist (against the Rev 3 flip points 1–13)

- **Flip #1 schema** (`is_private` DEFAULT false + `made_private_at`, drop publish columns, NO backfill, community partial index, NOTIFY tail) → Task 0.1. ✓
- **Flip #2 audit table** (`content.zettel_privacy_events`, action `make_private`/`make_public`, append-only `SELECT,INSERT` grant) → Task 0.2. ✓
- **Flip #3 role + RLS** (`community_reader` unchanged; RLS `USING (is_private = false AND deleted_at IS NULL)`; anon/authenticated unaffected; service_role BYPASSRLS) → Task 0.3. ✓
- **Flip #4 RPC** (predicate `is_private = false AND deleted_at IS NULL`, strip user_id, dedup, JOIN display_name, SECURITY DEFINER OWNED BY community_reader, GRANT EXECUTE to service_role) → Task 0.4. ✓
- **Flip #5 wrapper** (`get_community_graph`, `read_cache_version`, `set_private(...)` flips is_private/made_private_at + inserts privacy event + bumps version) → Task 0.5. ✓
- **Flip #6 regression gate** (private never appears under service_role; default appears; private↔public toggles; no user_id; edge never touches private) → Task 0.6. ✓
- **Flip #7 cache version** (`community_cache_version` + `bump_community_cache_version`, bumped in set_private) → Task 0.7. ✓
- **Flip #8 serving** (global from wrapper, file-store RETIRED from live path, empty-state overlay not fallback, SWR + version-counter cache, meta.source='community') → Task 1.1 (+ overlay in 1.6). ✓
- **Flip #9 headers + hard-401** (global public+s-maxage+swr, Vary: Accept-Encoding only, no Set-Cookie, drop Authorization; `view=my`/`kasten` hard-401 with Part A 401→refresh→banner + `loadUserOwnedIds`-survives-401 checks) → Task 1.2. ✓
- **Flip #10 UX + endpoint** (Make-private/Make-public toggle default-public, teal Private badge, undo toast, `POST /private` + `/public` with ownership + audit + bump, consent modal REMOVED) → Tasks 1.4 + 1.5. ✓
- **Flip #11 signup notice** (dismissible teal public-content notice on /home, pure helper + test) → Task 1.8. ✓
- **Flip #12 toggle→community + empty state** (Global maps to real community, empty overlay, no file-store) → Task 1.6. ✓
- **Flip #13 E2E gate** (assertions updated for opt-out) → Task 1.7. ✓

### Placeholder scan
- No `TODO`/`FIXME`/stub/`pass`-only bodies in shipped code.
- Every migration has a matching `.down.sql`.
- Every schema migration ends with `NOTIFY pgrst, 'reload schema';` (and `'reload config'` where grants/roles change).
- No `is_published`/`published_at`/`attribution`/`publish_consent_events` references remain anywhere in the plan; no backfill step exists.

### Type / name consistency
- RPC: `content.community_graph_v1(p_limit int, p_min_strength float)` — same name in migration 88, the wrapper (`community_repository.py`), and all tests.
- Role: `community_reader` — migration 87, 88 ownership, role test.
- Counter: `content.community_cache_version` + `content.bump_community_cache_version()` — migration 89, wrapper `read_cache_version`/`bump_cache_version`, view_graph bucket key.
- Columns: `is_private` / `made_private_at` — migration 85, RPC, wrapper, endpoint, tests.
- Audit: `content.zettel_privacy_events` with `action IN ('make_private','make_public')` — migration 86, wrapper `set_private`, endpoint, tests.
- JS helpers: `headersForView`, `privacyToggleLabel`, `privacyBadge`, `undoToastText`, `communityEmptyState` (app.js fence); `shouldShowPublicNotice`, `publicNoticeText` (home.js fence) — each vitest file constructs its own `new Function(... return {names})`.
- Cache user-key `"__community__"` (Task 1.1) is internal to view_graph; version counter is the real invalidator.

### Migration numbering / ordering
- Slots 85–89 are free (latest existing is 84). Lexical order applies them 85→89. Ordering is correct: 85 columns → 86 audit → 87 role+RLS → 88 RPC (needs role 87) → 89 counter. The 88 RPC `ALTER FUNCTION ... OWNER TO community_reader` requires role 87 to exist first — satisfied by lexical order.
- Filenames renamed for the opt-out model: `85_workspace_zettels_privacy`, `86_zettel_privacy_events`, `87_community_reader_role`, `88_community_graph_v1_rpc`, `89_community_cache_version`.
- Down-migrations: 88.down drops the function before 87.down drops the role (operator runs `--rollback` in reverse order 89→85; 87.down also guards by re-checking the role).

### Anti-pattern guards
- service_role-bypass is mitigated at the DB (role+RLS+SECURITY DEFINER owner), not just in Python.
- No background thread started at import (cache stays lazy/post-fork; counter read is a request-time `asyncio.to_thread`).
- No protected knob touched; no purple; teal badge + teal notice only; amber untouched; no infra disclosure in payload (RPC excludes user_id/made_private_at).
- Part A untouched except the deliberate hard-401: `buildGraphApiUrl` unchanged; `loadUserOwnedIds` keeps auth but now tolerates 401; `view=my` headers unchanged; existing vitest files re-run green in Tasks 1.2/1.4/1.6. The hard-401 is gated by explicit Part A regression checks in Task 1.2.

---

## DESIGN DECISIONS & AMBIGUITIES (operator confirmation where flagged)

These are recorded inline in the relevant tasks and must be captured as claude-mem `decision` observations per CLAUDE.md.

1. **RPC lives in a VERSIONED migration (88), not `repeatable/R__content_rpcs.sql`.** *Decision because:* although `community_graph_v1` is a `CREATE OR REPLACE` code-object (which usually goes in `R__`), it carries one-time ownership DDL (`ALTER FUNCTION ... OWNER TO community_reader`) that (a) must run after role-migration 87 exists and (b) is not idempotent-friendly to re-run on every deploy. Keeping it versioned guarantees ordering after 87 and a clean `.down.sql`. If the RPC body later needs frequent iteration, follow the repo's established `NN_migrate_X_to_repeatable.sql` pattern (e.g. `47_migrate_17_to_repeatable.sql`) to promote it then. **No operator action needed** — flagging the rationale.

2. **File-store RETIRED from the live global path (Task 1.1) — NO fallback.** *Decision because:* Rev 3 makes Global the real all-public community graph and there IS data (the ~80 existing zettels are public by default). An empty community now surfaces the empty-state overlay (Task 1.6), never the curated 29-node seed. `_file_store_graph()` is left defined for CLI/seed tooling but is unreferenced on the live path. **Behavior change to flag:** any existing Part A test asserting `meta.source == "file-store"` for anonymous global must be updated to `"community"` — that is intended, not a regression. **CONFIRM** the operator is OK retiring the seed entirely (recommended per Rev 3).

3. **`view=my` / `kasten` HARD-401 is now IN scope (Task 1.2), implemented at the ROUTE layer.** *Decision because:* Rev 3 (operator-approved 2026-06-16) requires auth for personal views. The cleanest non-breaking implementation raises `HTTPException(401)` in `graph_data` when the *effective* view is `my`/`kasten` and `user is None` — WITHOUT swapping the `Depends(get_optional_user)` dependency (swapping it would also 401 the anonymous `view=global` path, which must stay 200). The effective-view rule mirrors `_resolve_view`. **Part A risk surfaced (analysis):** (a) `loadUserOwnedIds` (`app.js:545`) issues a `view=my` fetch *even while in Global* to gate the Personal toggle + the Make-private button — for a logged-out user this previously returned an empty graph (200) and now returns 401; the task explicitly hardens it to catch 401 → empty set so the page does not break. (b) The `zk_fetch` 401→refresh→banner pipeline already exists (`auth.py:206-222` + the frontend banner) and is the intended handler for an *expired* session; a *never-authenticated* anonymous user simply gets the empty-set degrade. (c) The Personal toggle is already greyed for logged-out users in Part A, so no new dead-end. **No additional operator approval needed** (already approved), but the implementer MUST run the Part A regression checks in Task 1.2 and surface immediately if any break.

4. **Attribution = earliest saver's `display_name`; `contributor_count` exposed.** *Decision because:* a canonical saved by N users needs one node; under the opt-out/public-by-default model every public zettel is shown with its owner's name (the chosen attribution model — anonymous mode is deferred), so showing the first saver's name and a `contributor_count` is consistent with "public + attributed." **Adversarial note (Rev 3 R3.2):** since the data is public by the chosen model, N=1 attribution is acceptable; the N≥5 suppression rule only applies to any *future non-consensual* aggregate. **CONFIRM** exposing `contributor_count` in the public payload is acceptable (recommended: yes).

5. **Cache user-key `"__anon__"` → `"__community__"` (Task 1.1).** *Decision because:* the community payload is a different object than the legacy anon file-store payload; a distinct key avoids cross-contamination, and the new version-counter (folded into the bucket) is the authoritative invalidator. Existing `invalidate("__anon__")` calls become harmless no-ops. **No operator action** — rationale flagged.

6. **`set_private` does NOT clear `made_private_at` on make-public.** *Decision because:* `made_private_at` is internal audit; leaving the last-made-private timestamp is informative and the `zettel_privacy_events` table is the authoritative action log. The RPC never returns `made_private_at`, so this never leaks. **CONFIRM** (recommended: leave as-is).

7. **Make-private button visibility gated to user-owned nodes only (Task 1.5).** *Decision because:* you can only change privacy on your own zettel; showing the toggle on a stranger's community node would be confusing and the endpoint would 403 anyway. Reuses `userOwnedIds` (already loaded by Part A's `loadUserOwnedIds`). **No operator action.**

8. **Two endpoints `POST /private` + `POST /public` (Task 1.5), not one toggle endpoint.** *Decision because:* explicit verbs are idempotent (re-POSTing `/private` is a safe no-op), produce a clean audit action per call, and make the Undo affordance a literal inverse call. A single `POST /privacy` taking `{private: bool}` is the alternative — slightly fewer routes but a mutable body and a less self-documenting audit. **CONFIRM** the two-endpoint shape (recommended) vs a single toggle endpoint.

9. **Signup notice lives on `/home` (`user_home`), first-visit, dismissible (Task 1.8).** *Decision because:* the app's auth is OAuth-redirect with no app-owned signup form to host the copy; `/home` (`website/features/user_home/index.html`, `#home-welcome` block, verified lines 22-24) is the first logged-in surface every user sees and the one where they own/are-about-to-own zettels. Dismissal persists in `localStorage` (`kg.publicNoticeDismissed`). **Alternative:** also/instead show it on `/home/zettels` or as a one-time interstitial after first capture. **CONFIRM** `/home` first-visit is the right surface and the copy ("Your saved zettels are public and shown with your display name. Mark any private to hide it.").

10. **Adding a NEW test-export fence to `home.js` (Task 1.8).** *Decision because:* `home.js` has no existing fence; the signup-notice helper is pure and should be unit-tested the same way KG helpers are. The fence markers mirror `app.js:12` exactly so the extraction regex is identical. **No operator action** — flagged so the implementer adds the fence rather than exporting via `module.exports`.

11. **Icon asset for the Make-private button (`icon-eye-off.svg`) (Task 1.5).** *Ambiguity:* the side-panel buttons use `--mask-url: url(/artifacts/...)`. If no eye-off asset exists, inline an SVG mirroring the close button at `index.html:224`. **CONFIRM** an asset exists or accept the inline-SVG substitute (recommended: inline SVG to avoid a missing-asset dependency).

12. **Manifest gate (`apply_migrations.py` schema-drift) introspects `public` schema only.** *Observation:* the drift manifest (`expected_schema.json`) snapshots `public.*` (per `_introspect_schema`, `information_schema.columns WHERE table_schema='public'`). Our objects are in `content`/`core`, so they likely won't appear in the manifest and won't trip the gate — but each migration task runs `apply_migrations.py --v2 --update-manifest` defensively so any captured surface stays fresh. **No operator action** — flagged so the executor doesn't panic if `--update-manifest` shows "0 changes".

13. **Ops note (Task 1.3) and the Cloudflare dashboard change are NOT auto-applied.** Per CLAUDE.md, infra/ops touches need operator approval per occurrence. The runbook is committed as a doc; **the operator applies the Cache Rule manually** and runs the `curl` verification.

14. **No backfill (Task 0.1).** *Decision because:* Rev 3 makes the ~80 existing zettels public via the `DEFAULT false` column default — running an `UPDATE ... SET is_private = ...` backfill is unnecessary and would be the wrong direction. This is a deliberate omission, not a missing step. **No operator action** — flagged so the executor does not "helpfully" add a backfill.
