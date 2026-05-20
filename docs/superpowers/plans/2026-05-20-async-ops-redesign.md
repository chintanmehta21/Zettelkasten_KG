# Async Operations Redesign — Postgres-as-the-Truth + State-Guarded RPCs

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`. Per-phase TDD + idempotency + two-stage review (spec then code-quality). Branch (TBD per merge sequence) — commit per phase. NO push until D1 phase complete; NO PR until operator says. Per-phase verification on full `tests/unit/website/ tests/unit/summarization_engine/ tests/unit/frontend/` suite; ONLY acceptable pre-existing failure: `tests/unit/website/test_youtube_422_diagnostics.py::test_youtube_extraction_failure_returns_problem_detail`. Operator runs the eventual rebase-merge.

**Goal:** Replace the current hybrid (per-worker in-memory dicts + Supabase row) async-operations design with a canonical **Postgres-as-the-only-truth + state-guarded SQL RPCs + in-process asyncio workers** architecture. This eliminates the entire 8-bug Codex class **by construction** — every race, lost-write, stuck-slot, false-failure, structured-detail-loss is impossible because the offending mechanism (duplicated state, blind upsert, LRU cancel, per-worker dedup) is **deleted**, not patched.

**Locked decisions (operator-approved 2026-05-20):** D1–D10 per `mem-vault://EBZVmrWwZWa63qgrTINIw4QK` and dossier delivered same day. Anchors: Microsoft Learn Async Request-Reply (2026-04), RFC 9457 Problem Details, RFC 7240 Prefer header, Stripe + Brandur idempotency keys, River queue (2023), PlanetScale Postgres queue health (2026).

**Tech stack:** Python 3.12 / FastAPI / asyncpg-via-PostgREST / Supabase (managed Postgres) / pg_cron / vanilla JS frontend. No new dependencies, no new processes. Net droplet RAM impact: negative (deletes three in-memory dicts).

**Protected knobs untouched:** `GUNICORN_WORKERS=2`, `--preload`, `GUNICORN_TIMEOUT=180s`, rerank semaphore, SSE heartbeat, Caddy `read_timeout 240s`, schema-drift gate, `kg_users` allowlist. Verified per CLAUDE.md §"Critical Infra Decision Guardrails".

---

## Branch sequence (operator-gated)

The current PR #30 (`fix/add-zettel-ux-524`, tip `d65f0914`) is the bug-fix + UX + text-quality baseline; it encodes the OLD in-memory architecture this plan deletes. To avoid rebase pain, the redesign branch MUST fork from **post-merge master**, not from `fix/add-zettel-ux-524`. Operator action:

1. Operator does `gh pr merge 30 --rebase --delete-branch` for PR #30 (zero new code from this redesign needed for that step — PR #30 is review-clean as-is).
2. After merge, this plan executes on a new branch `feat/async-ops-redesign` from updated `master`.
3. Migration 48 + 49 are already live in prod (sanctioned co-apply); migration 50 (PR #31, RLS partitions + migrations table) landed with PR #31 on 2026-05-20; this plan ships migration 51 (Phase 1) + 52 (Phase 4), both co-applied at landing-time.

---

## File structure

- **New:** `supabase/website/_v2/51_operations_state_machine.sql` — partial UNIQUE index, status CHECK, three RPCs (`ops_accept`, `ops_start`, `ops_finalize`).
- **New:** `supabase/website/_v2/57_stuck_running_reaper.sql` — pg_cron job extension (or amends 49 if cleanly possible; see Phase 4).
- **Modify:** `website/core/operations_repo.py` — replace `create_accepted` / `mark_succeeded` / `mark_failed` / `_mark` with `accept(...)` / `start(...)` / `finalize(...)` Python wrappers calling the RPCs; add `get_operation` (kept) and new `count_in_flight_for_user(...)` (backpressure) and `cancel(...)`.
- **Modify:** `website/api/zettels_routes.py` — delete `_OPERATIONS`, `_OPERATION_TASKS`, `_IN_FLIGHT`, `_operation_put`, `_operation_get`, `_cache_get`, `_cache_put`, `_store_operation_result`'s in-memory branches, `_persist_terminal`, the LRU/eviction logic. Keep one `_LIVE_TASKS: dict[str, asyncio.Task]` strong-ref + cancel target (never read by GET). New `operation_status` GET reads DB only. New POST flow: `accept()` → 202 + Location + Retry-After (idempotent by partial unique index) → `_LIVE_TASKS[op_id] = asyncio.create_task(_run(...))` → `start()` inside `_run` → `finalize()` in try/except/finally.
- **Modify:** `website/api/zettels_routes.py` sync error path — refactor `_problem()` to return / mirror the RFC 9457 shape exactly; the async `finalize(error=...)` writes the SAME shape into the jsonb column.
- **Modify:** `website/api/module_runners/summarization.py` — `AddZettelPipelineOutput.error` field already exists from prior d65f0914; keep, document its RFC 9457 contract.
- **Modify:** `website/static/js/add_zettel_api.js` — confirm `pollAccepted` reject contract reads `body.error` (RFC 9457 dict with `.code`, `.title`, `.detail`, `.status`, `.type`, `.instance`); no other JS change.
- **Modify:** `website/features/user_home/js/home.js`, `website/features/user_zettels/js/user_zettels.js` — confirm `err.detail.code` key path still resolves (it will: pollAccepted reject preserves `err.detail = next.error || next`). No structural change.
- **Modify:** `website/features/functional_gates/` if appropriate — per the feedback memory `feedback_functional_gates_reuse.md`, the per-user backpressure check (`count_in_flight_for_user → 429`) is a cross-cutting gate; live it in `website/features/functional_gates/async_backpressure.py` for reuse.
- **Delete (after Phase 2 verifies green):** the bodies / call sites listed in §"Migration deletions" below.
- **Tests:**
  - `tests/integration/v2/test_ops_state_machine.py` (NEW; real Supabase, exercises RPC state-guard guarantees end-to-end with mint_user_with_workspaces fixture)
  - `tests/unit/website/test_operations_repo.py` (rewritten to assert new accept/start/finalize shapes incl. on_conflict, status guards, idempotency-via-unique-index)
  - `tests/unit/website/test_async_operations_transport.py` (rewritten to exercise GET-from-DB-only path; covers the prior 8-bug class via state-machine invariants)
  - `tests/unit/website/test_async_backpressure_gate.py` (NEW; per-user count → 429)
  - `tests/unit/website/test_store_operation_result_concurrency.py` (REVISED; the prior CancelledError tests stay relevant — assert that an in-process cancel triggers a finalize(cancelled) RPC that is a no-op if status is already terminal)
  - `tests/integration/v2/test_stuck_running_reaper.py` (NEW; pg_cron job reaps stale running rows to `failed worker_lost`)
  - delete: `tests/unit/website/test_operation_put_eviction.py` (the LRU-cancel test is obsolete — the mechanism it tests no longer exists)

---

## Phases

### Phase 0 — Documentation Discovery (no implementation)

- [ ] **Step 1:** Confirm PostgREST RPC call shape for the Python client (`supabase-py 2.28.3`/`postgrest 2.28.3`). Inspect installed source for `.rpc(name, params).execute()` semantics + how it propagates `RETURNING` rows (the state-guard pattern depends on detecting zero-rows-affected via empty `.data`).
- [ ] **Step 2:** Confirm `ON CONFLICT … WHERE …` partial index supported with `INSERT … ON CONFLICT (cols) DO NOTHING` and that PostgREST exposes `Prefer: resolution=ignore-duplicates` against a PARTIAL unique index (verified earlier for D3 in the C3-fix). Read `48_operations.sql` + `49_operations_sweep.sql` to align style.
- [ ] **Step 3:** Confirm pg_cron extension syntax for amending an existing schedule vs adding a second job. Read migration 49 to see the existing job's exact format.
- [ ] **Step 4:** Confirm RFC 9457 exact field set (`type`, `title`, `status`, `detail`, `instance`, plus extensions) per `https://www.rfc-editor.org/rfc/rfc9457.html`. Note: the existing `_problem()` already emits a close-but-not-identical shape; the unification mapping must be exact.
- [ ] **Step 5:** Confirm asyncpg connection pool reuse (no new connection cost per RPC) — already in `core.supabase_v2.client`.
- [ ] **Step 6:** Write a one-page "schema contract" doc inline in this plan (Phase 1 below); operator confirms before any SQL writes.

**Verification:** zero code/SQL changes. Output is a brief discovery note appended to this plan section as a tick-list with citations.

---

### Phase 1 — Schema + RPC migration (`51_operations_state_machine.sql`)

- [ ] **Step 1:** Add `CHECK (status IN ('queued','running','succeeded','failed','cancelled','expired'))` constraint on `core.operations.status`. If the column already has a different CHECK, migrate via `ALTER TABLE … DROP CONSTRAINT … ADD CONSTRAINT …` in the same transaction; reject in-flight rows that violate (none expected since current values are subset).
- [ ] **Step 2:** Add partial unique index:
  ```sql
  CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ops_user_req_hash_active_uniq
    ON core.operations (user_id, request_hash)
    WHERE status IN ('queued','running','succeeded');
  ```
  (`CONCURRENTLY` so prod apply doesn't lock the table.)
- [ ] **Step 3:** Three RPCs as `SECURITY DEFINER` functions (service-role only; per existing RLS posture):
  - `core.ops_accept(p_user_id uuid, p_operation_id text, p_request_hash text, p_accepted jsonb, p_ttl_seconds int default 86400) RETURNS TABLE(operation_id text, status text, is_new boolean)` — INSERT ON CONFLICT DO NOTHING using the partial unique index; if conflict, SELECT existing row and return `is_new=false`.
  - `core.ops_start(p_user_id uuid, p_operation_id text) RETURNS text` — UPDATE …WHERE status='queued' RETURNING status; returns NULL if no row matched (already running or terminal).
  - `core.ops_finalize(p_user_id uuid, p_operation_id text, p_target text, p_response jsonb, p_error jsonb) RETURNS text` — UPDATE …WHERE status IN ('queued','running') RETURNING status; CHECK `p_target IN ('succeeded','failed','cancelled')`. NO-op (returns NULL) if already terminal — kills the create_accepted-downgrade race and the duplicate-finalize race by construction.
- [ ] **Step 4:** Idempotency / state-machine tests (unit-level on the SQL via psycopg or supabase-py against a test schema; integration tests in Phase 5):
  - accept twice with same (user_id, request_hash) while status IN active set → second returns `is_new=false` with existing operation_id (Stripe / Brandur semantics)
  - accept after a previous run reached terminal `failed` → new operation_id (terminal failed rows don't dedup per partial index)
  - start on a non-existent row → returns NULL
  - finalize(succeeded) on a row already finalize(failed) → returns NULL, row unchanged (the bug-class killer)
  - finalize(cancelled) → idempotent under duplicate cancel
- [ ] **Step 5:** Commit `feat: 51_operations state machine + idempotency partial unique`.

---

### Phase 2 — Python repo refactor + route rewrite

- [ ] **Step 1:** Rewrite `website/core/operations_repo.py`:
  - `accept(user_id, operation_id, request_hash, accepted_body, ttl_seconds=86400) -> tuple[str, bool]` — calls `ops_accept` RPC; returns `(canonical_operation_id, is_new)`. Defensive try/except → on error returns `(operation_id, True)` as best-effort fallback (logged) so the request path never 5xxs (existing posture).
  - `start(user_id, operation_id) -> bool` — calls `ops_start`; True iff transition fired.
  - `finalize(user_id, operation_id, target, *, response=None, error=None) -> bool` — calls `ops_finalize`; True iff transition fired.
  - `get_operation(user_id, operation_id) -> dict | None` — unchanged (already correct).
  - `count_in_flight_for_user(user_id) -> int` — `SELECT count(*) WHERE user_id=$1 AND status IN ('queued','running')`. Used by backpressure gate.
  - DELETE: `create_accepted`, `mark_succeeded`, `mark_failed`, `_mark`.
- [ ] **Step 2:** Rewrite `_store_operation_result` (the asyncio done-callback) and `_run` (the bg coroutine in `zettels_routes.py`):
  - `_run` wraps the work: `await ops.start(...)` (no-op if not in queued); `try: result = await summarize(...); await ops.finalize(..., 'succeeded', response=result)` except `asyncio.CancelledError: await ops.finalize(..., 'cancelled', error=_problem_dict(...))` except Exception as exc: `await ops.finalize(..., 'failed', error=_async_failure_error_payload(exc))`.
  - Done-callback shrinks dramatically: only `_LIVE_TASKS.pop(op_id, None)`. No in-memory state mutations. The DB row is the truth.
  - DELETE: `_persist_terminal`, the in-memory cache_put/get, the LRU-eviction-cancel branch.
- [ ] **Step 3:** Rewrite the POST `/api/zettels/add` accept path:
  - Honor `Idempotency-Key` HTTP header per IETF draft. If absent, compute `request_hash` server-side (current behavior, retained).
  - `operation_id` is the client-supplied `client_action_id` (current) OR server-generated UUID v7 if absent.
  - Backpressure gate: `if await ops.count_in_flight_for_user(user_id) > _MAX_IN_FLIGHT_PER_USER:` → 429 with `Retry-After: 30`. Move to `website/features/functional_gates/async_backpressure.py` per reuse rule.
  - `(canonical_op_id, is_new) = await ops.accept(...)`. If `not is_new`, skip the task spawn and just return 202 pointing at the canonical op (Stripe pattern — duplicate request returns the same operation_id; client polls and gets the same result).
  - If `is_new`: `_LIVE_TASKS[canonical_op_id] = asyncio.create_task(_run(...))`; the task strong-ref is the `_LIVE_TASKS` entry (idempotent re-add to `_BG_TASKS` is fine if we keep that as a secondary safety net, but `_LIVE_TASKS` is canonical).
  - Return `202 Accepted` + `Location: /api/zettels/operations/{op_id}` + `Retry-After: <s>`.
- [ ] **Step 4:** Rewrite `GET /api/zettels/operations/{operation_id}`:
  - `row = await ops.get_operation(user_id=effective_user_id, operation_id=op_id)`
  - If row is None → still return `202 + Retry-After` (the prior P2 fix — Supabase write-replica lag during accept). Do NOT 404; the client's existing 180s poll budget bounds the wait.
  - If `row['status'] in ('queued','running')` → return `202 + Retry-After`.
  - If `row['status'] == 'succeeded'` → return `200` with `row['response']` (the AddZettelResponse body).
  - If `row['status'] in ('failed','cancelled')` → return `200` with `{status: row['status'], operation_id, error: row['error']}` (RFC 9457 in `error`).
  - If `row['status'] == 'expired'` → return `410 Gone` + RFC 9457 body.
  - DELETE: the in-memory `_operation_get` fallback, the `_problem(404)` branch.
- [ ] **Step 5:** Add `DELETE /api/zettels/operations/{operation_id}` per Microsoft Learn pattern: calls `ops.finalize(..., 'cancelled', error=_problem_dict(code='client_cancelled', ...))` and, if `_LIVE_TASKS.get(op_id)`, cancels the local task (cooperative; even if it completes after, its `finalize` is a no-op via state guard).
- [ ] **Step 6:** Frontend confirmation (no JS code change required; verify only):
  - `pollAccepted` reject contract: `err.detail = body.error || body` already in place — RFC 9457 `error` flows naturally.
  - Both consumers' `e.detail.code === 'quota_exhausted'` (and similar) keys continue to work — only the SHAPE source-of-truth moved from `_problem()` strings to the unified RFC 9457 jsonb.
- [ ] **Step 7:** Run targeted suites → green → commit `feat: ops state machine adapter + GET-from-DB-only`.

---

### Phase 3 — RFC 9457 error-shape unification

- [ ] **Step 1:** Audit `_problem()` (current implementation) — quote each `_problem(status_code=…, title=…, detail=…, type_slug=…, extra=…)` call site (already done in the d65f0914 review; ~6 call sites). For each, define the RFC 9457 dict exactly:
  ```python
  {
    "type": f"https://zettelkasten.in/problems/{type_slug}",
    "title": title,
    "status": status_code,
    "detail": detail,
    "instance": f"/api/zettels/operations/{op_id}" if op_id else request.url.path,
    # extensions:
    "code": <type_slug>,
    **(extra or {}),
  }
  ```
  Both the sync HTTPException (FastAPI handler converts to JSON) and the async `finalize(error=...)` write this EXACT shape. Frontend keys off `.code` (same key now in both paths).
- [ ] **Step 2:** Refactor `_problem()` to BUILD the dict from a single internal helper `_problem_dict(...)` and then `_problem()` returns `JSONResponse(_problem_dict(...), status_code=..., media_type='application/problem+json')`. The async path's `_async_failure_error_payload(exc)` (already in place from d65f0914) is rewritten to call `_problem_dict(...)` directly so the two paths are physically the same code, not parallel implementations.
- [ ] **Step 3:** Rewrite tests:
  - `test_problem_response_shape_is_rfc_9457` — sync 4xx response body shape exact.
  - `test_async_finalize_failed_writes_same_problem_shape` — finalize(failed, error=_problem_dict(...)) → GET returns body with identical `.error` dict.
- [ ] **Step 4:** Commit `feat: unify sync + async error shape on RFC 9457`.

---

### Phase 4 — Backpressure gate + stuck-running reaper

- [ ] **Step 1:** New `website/features/functional_gates/async_backpressure.py`:
  - `class AsyncBackpressureGate: async def check(self, user_id, *, limit=_MAX_IN_FLIGHT_PER_USER) -> None | JSONResponse:` returns a 429-with-RFC-9457-body if exceeded, else None.
  - Default `_MAX_IN_FLIGHT_PER_USER = 3` (tuned later; bias conservative). Configurable via env if needed.
- [ ] **Step 2:** Wire the gate at the accept path of `add_zettel` BEFORE `ops.accept(...)`. (Per the reuse rule — single source for future endpoints like file upload, chat.)
- [ ] **Step 3:** `supabase/website/_v2/57_stuck_running_reaper.sql` — extend the existing pg_cron job from migration 49 to also:
  ```sql
  UPDATE core.operations
  SET status='failed',
      error=jsonb_build_object(
        'type','https://zettelkasten.in/problems/worker-lost',
        'title','Background worker lost',
        'status',500,
        'detail','The worker handling this operation did not finalize within the watchdog window.',
        'code','worker_lost'
      ),
      updated_at=now()
  WHERE status='running'
    AND updated_at < now() - interval '5 minutes';
  ```
  (5 min > the 180s GUNICORN_TIMEOUT — anything older than 5 min is definitively dead.)
- [ ] **Step 4:** Tests:
  - `test_backpressure_gate_returns_429_at_limit` (unit)
  - `test_stuck_running_reaper_marks_dead_rows_failed` (integration, real Supabase)
- [ ] **Step 5:** Commit `feat: per-user async backpressure + stuck-running reaper`.

---

### Phase 5 — Migration deletions, regression, ruff, co-apply plan

- [ ] **Step 1:** Delete code marked obsolete by Phases 1–4:
  - `_OPERATIONS` dict + `_OPERATION_TASKS` dict + `_IN_FLIGHT` dict + `_operation_put` + `_operation_get` + `_cache_get` + `_cache_put` + `_persist_terminal` + the LRU-cancel branch in `_operation_put`.
  - `tests/unit/website/test_operation_put_eviction.py` (mechanism gone).
  - Any `_idempotency_conflict` helper that the per-worker `_IN_FLIGHT` dict fed (the partial unique index is now the idempotency mechanism; the helper either moves to read from `ops.accept(...)`'s `is_new=False` return path or is deleted).
- [ ] **Step 2:** Full-suite gate: `python -m pytest tests/unit/website/ tests/unit/summarization_engine/ tests/unit/frontend/ -q 2>&1 | tail -15` — green (sole acceptable failure: documented `test_youtube_422_diagnostics::test_youtube_extraction_failure_returns_problem_detail`).
- [ ] **Step 3:** `python -m pytest tests/integration/v2/ -q 2>&1 | tail -15` — green (covers the state-machine RPCs end-to-end with real Supabase + the stuck-running reaper).
- [ ] **Step 4:** `python -m ruff check website tests` → `All checks passed!`.
- [ ] **Step 5:** `node --check website/features/user_home/js/home.js && node --check website/features/user_zettels/js/user_zettels.js && node --check website/static/js/add_zettel_api.js`.
- [ ] **Step 6:** Co-apply plan documented (`ops/co_apply/2026-05-20-migration-51-57.md`): operator runs `python ops/scripts/apply_migrations.py --v2 51_operations_state_machine.sql 57_stuck_running_reaper.sql` against prod via the sanctioned path; manifest entry; rollback procedure; smoke test (POST /api/zettels/add of a known URL → poll → succeed).
- [ ] **Step 7:** Commit `feat: delete obsolete in-memory ops state` + `docs: co-apply plan migration 51+57`.
- [ ] **Step 8:** Brief summary; **STOP for operator rebase-merge approval + prod co-apply approval**. No autonomous push/PR/merge; never autonomous co-apply (operator runs the migration).

---

## Migration deletions (audit checklist for Phase 5)

| Symbol | File | Replacement |
|---|---|---|
| `_OPERATIONS` (LRU dict) | zettels_routes.py | DELETED — `core.operations` row is the truth |
| `_OPERATION_TASKS` (dict) | zettels_routes.py | DELETED — merged into `_LIVE_TASKS` |
| `_IN_FLIGHT` (dict) | zettels_routes.py | DELETED — partial unique index on (user_id, request_hash) |
| `_operation_put` | zettels_routes.py | DELETED |
| `_operation_get` | zettels_routes.py | DELETED — GET reads `ops.get_operation` |
| `_cache_get` / `_cache_put` | zettels_routes.py | DELETED — Supabase row is the cache |
| `_persist_terminal` | zettels_routes.py | DELETED — `_run` awaits `ops.finalize` directly |
| LRU cancel branch in `_operation_put` | zettels_routes.py | DELETED — per-user count → 429 replaces it |
| `_MAX_OPERATION_RECORDS = 128` | zettels_routes.py | DELETED |
| `create_accepted` / `mark_succeeded` / `mark_failed` / `_mark` | operations_repo.py | DELETED — replaced by `accept` / `start` / `finalize` |
| `test_operation_put_eviction.py` | tests/unit/website/ | DELETED |

The rewritten state-machine tests cover the same correctness properties (idempotency, cross-worker visibility, no-clobber under race, cancellation safety) at the layer where they actually hold — the DB row, not the in-memory mirror.

---

## Verification against the 8 Codex findings (proof the redesign closes each by construction, not by patch)

| Finding | How it dies under D1–D10 |
|---|---|
| 1. _mark blind update | `ops_finalize` is `UPDATE … WHERE status IN (queued,running) RETURNING status`; if status is already terminal, returns NULL → no-op, no clobber |
| 2. create_accepted overwrites terminal | `ops_accept` is `INSERT … ON CONFLICT … DO NOTHING` on the PARTIAL unique index that does NOT include terminal statuses → cannot fire after terminal |
| 3. _persist_terminal GC | The body of `_run` awaits `ops.finalize` synchronously inside the running coroutine (which IS strong-referenced by `_LIVE_TASKS`); no fire-and-forget step exists |
| 4. LRU cancel of running tasks | LRU + cap deleted; backpressure is per-user count → 429 BEFORE accept; never cancels in-flight |
| 5. CancelledError stuck slot | No per-worker `_IN_FLIGHT` dict to stick; cancellation routes to `ops.finalize(cancelled, ...)` which is the same idempotent path |
| 6. cross-worker 404 | GET only reads DB; both workers see the same row. The replication-lag-during-accept window stays handled by the 202+Retry-After response on row-missing (preserves the prior P2 fix's intent without the patch's complexity) |
| 7. pollAccepted resolves on failed → "Untitled" | Frontend contract already corrected in F1 (commit 92d94760); confirmed compatible with the new RFC 9457 error shape (key path `body.error.code` unchanged) |
| 8. structured failure detail dropped | `ops.finalize(failed, error=_problem_dict(...))` writes the SAME RFC 9457 jsonb the sync 4xx path emits; GET returns it verbatim |

---

## Risks + mitigations

| Risk | Mitigation | Source |
|---|---|---|
| Migration 50 needs `CONCURRENTLY` to avoid a brief prod lock during partial-index build | Use `CREATE INDEX CONCURRENTLY`; cannot run inside a transaction → migration runner must split the statement out | PostgreSQL docs `CREATE INDEX CONCURRENTLY` |
| RPC SECURITY DEFINER + RLS posture mismatch | Mirror the existing migration 48 pattern (service-role only, GRANT EXECUTE) | `supabase/website/_v2/48_operations.sql` |
| Stuck-running reaper races a tardy real finalize | Reaper UPDATE has `WHERE status='running'`; if the real finalize wins, reaper's UPDATE is a no-op (same state-guard pattern) | RFC 7240 / Brandur idempotency |
| `count(in_flight)` per accept = extra DB roundtrip per request | Acceptable cost (~1ms); if measured-hot, cache with 1s TTL per user via `lru_cache(maxsize=…)` — defer | PlanetScale Postgres queue health (2026) |
| Idempotency-Key header collisions across users | Index is on `(user_id, request_hash)` — scoped per user; cross-user collisions impossible | Stripe / Brandur |

---

## Notes for the implementer

- Branch (TBD) on a fresh fork of post-merge master; commit per phase.
- **Conservative/surgical guarantee:** Phases 1–4 ADD the new mechanism alongside the old; Phase 5 deletes the old ONLY AFTER Phase 2/3/4 prove the new path is green on the full suite. There is no "all-or-nothing" cutover.
- **No new deps, no new processes.** Pure SQL + Python + Supabase RPC.
- **Single sources of truth (per CLAUDE.md `feedback_functional_gates_reuse.md` + Source Allies state anti-pattern):** the DB row for op state; `_problem_dict()` for error shape; `_LIVE_TASKS` for in-process coroutine GC + cancel.
- Operator runs the rebase-merge and the prod migration co-apply per CLAUDE.md "Audit/Verify ≠ Authorization" rule.
- Per `feedback_resolve_in_pr_no_deferral.md` — if any new Codex finding lands during this PR, fix it within this PR (it should be RARE given the redesign closes the bug class by construction).

---

## Phase 0 — Discovery Notes (completed 2026-05-20)

All five verification steps executed read-only against installed package source, live web docs, and project SQL/Python files. No code changes.

### Step 1 — PostgREST / supabase-py RPC call shape

**Verified findings:**
- Versions pinned: `postgrest 2.28.3` / `supabase 2.28.3` (matches PR #30 baseline).
- `supabase.Client.rpc(fn, params=None, count=None, head=False, get=False)` delegates directly to `self.postgrest.rpc(...)` — same call shape on either side. Source: `<site-packages>/supabase/_sync/client.py::Client.rpc`.
- `supabase.Client.schema(schema)` returns the underlying `SyncPostgrestClient` configured against that schema, so `client.schema('core').rpc('ops_finalize', {...}).execute()` is the canonical idiom and routes to PostgREST against the `core` schema (PostgREST sets `Accept-Profile`/`Content-Profile` header). Source: `<site-packages>/supabase/_sync/client.py::Client.schema`.
- `SyncPostgrestClient.rpc(func, params, count, head, get)` builds an HTTP POST (or GET when `get=True`) to `/rpc/<func>` with `params` as the JSON body; returns a `SyncRPCFilterRequestBuilder` whose `.execute()` returns an `APIResponse` with `.data` populated from the PostgREST response body. Source: `<site-packages>/postgrest/_sync/client.py::SyncPostgrestClient.rpc`.
- `RETURNING` / function row results: when a PL/pgSQL function returns `TABLE(...)` or `SETOF`, `.data` is a `list[dict]` (one element per returned row); when it returns a scalar, `.data` is that scalar value (typed per PostgREST JSON serialization). The state-guard pattern (RPC returns NULL when WHERE matched zero rows) surfaces as `.data is None` for scalar returns, or `.data == []` for `TABLE(...)` returns. Both are unambiguous — the wrapper checks `is None or not data` to detect a no-op transition.
- Async vs sync: `operations_repo.py` head comment explicitly says "Sync by design — callable from the FastAPI request path via `asyncio.to_thread`" (line 6-7). New `accept/start/finalize` wrappers stay sync; the route layer wraps each call in `await asyncio.to_thread(ops.<fn>, ...)`. No async-client churn needed.
- Schema-qualified RPC permission: migration 48 currently exposes the `core.operations` table via the existing service-role RLS policy (`operations_service_all`). For RPCs the equivalent requirement is `GRANT EXECUTE ON FUNCTION core.ops_accept(...) TO service_role` (and similarly for the other two); without it PostgREST will return 401/403 even though the table grant exists. Phase 1 migration 51 MUST include the `GRANT EXECUTE` lines for each new SECURITY DEFINER function.

**Citations:**
- `<site-packages>/postgrest/_sync/client.py::SyncPostgrestClient.rpc` (lines containing `method = "HEAD" if head else "GET" if get else "POST"` and the `RequestConfig` build).
- `<site-packages>/supabase/_sync/client.py::Client.rpc` and `Client.schema`.
- `website/core/operations_repo.py:6-7` (sync-by-design comment).
- `supabase/website/_v2/48_operations.sql:32-36` (service-role RLS policy pattern Phase 1 will mirror for `GRANT EXECUTE`).

**Impact on Phase 1+:** No call-shape surprises. Migration 50 MUST add explicit `GRANT EXECUTE ON FUNCTION core.ops_accept(...) TO service_role;` (and start/finalize) — this is NOT in the current plan body and should be added to Phase 1 Step 3. Wrapper functions inspect `resp.data` for `None` / `[]` to detect zero-rows-affected; for `ops_accept` which returns `TABLE(operation_id, status, is_new)` the wrapper reads `resp.data[0]` (always one row — INSERT-or-SELECT-existing guarantees a row).

### Step 2 — Partial UNIQUE index + ON CONFLICT semantics

**Verified findings:**
- `core.operations` current schema (`supabase/website/_v2/48_operations.sql:10-21`):
  - PK is composite `(user_id, operation_id)`.
  - `status text NOT NULL CHECK (status IN ('accepted', 'succeeded', 'failed'))` — Phase 1 MUST `ALTER TABLE … DROP CONSTRAINT … ADD CONSTRAINT …` to expand the allowed set to `('queued','running','succeeded','failed','cancelled','expired')`. There is no `accepted` carryover in the new lexicon — Phase 1 should add an explicit data migration `UPDATE core.operations SET status='queued' WHERE status='accepted'` BEFORE swapping the CHECK, otherwise the new CHECK rejects existing in-flight rows.
  - `request_hash text NOT NULL` — Phase 1's `INSERT … ON CONFLICT` must always supply request_hash (it does).
  - Existing index: only `operations_expires_at_idx ON (expires_at)`. No conflict with the new partial unique index.
- PostgreSQL supports partial unique indexes. Quote (PG manual §11.8 Partial Indexes): *"The idea here is to create a unique index over a subset of a table"*. Syntax matches Phase 1 plan: `CREATE UNIQUE INDEX ... ON table (cols) WHERE predicate`. Cited: https://www.postgresql.org/docs/current/indexes-partial.html (accessed 2026-05-20).
- `ON CONFLICT` inference against a partial unique index: PG manual §INSERT defines `index_predicate` as *"Used to allow inference of partial unique indexes. Any indexes that satisfy the predicate ... can be inferred."* Practical consequence: the `INSERT … ON CONFLICT (user_id, request_hash) WHERE status IN ('queued','running','succeeded') DO NOTHING` form MUST include the explicit `WHERE` clause on the INSERT statement to disambiguate inference when other (future) indexes on the same columns might exist. Cited: https://www.postgresql.org/docs/current/sql-insert.html (accessed 2026-05-20).
- `CREATE INDEX CONCURRENTLY` CANNOT run inside a transaction block. Quote (PG manual): *"a regular CREATE INDEX command can be performed within a transaction block, but CREATE INDEX CONCURRENTLY cannot."* Cited: https://www.postgresql.org/docs/current/sql-createindex.html (accessed 2026-05-20).
- Migration 48 (`BEGIN; ... COMMIT;`) and 49 are single-transaction files. Migration 51 MUST split: (a) one `BEGIN/COMMIT` block for the CHECK swap + data backfill + RPC `CREATE OR REPLACE FUNCTION` statements, (b) the `CREATE UNIQUE INDEX CONCURRENTLY` OUTSIDE any transaction. The project's migration runner (`ops/scripts/apply_migrations.py`) must already tolerate this for any prior CONCURRENTLY migration — Phase 1 step 2 must verify this, and if the runner wraps the whole file in a transaction the CONCURRENTLY statement must be moved to a separate migration file (e.g. `51_operations_state_machine.sql` for the txn parts, `51a_partial_unique_concurrent.sql` for the index).
- PostgREST `Prefer: resolution=ignore-duplicates` against a partial unique index: the live PostgREST docs page consulted (https://postgrest.org/en/stable/references/api/tables_views.html, accessed 2026-05-20) does NOT explicitly confirm or deny partial-unique-index inference. However, PostgREST sends `INSERT … ON CONFLICT … DO NOTHING` to Postgres; conflict resolution is then PG's responsibility and the `index_predicate` inference rule above applies. The new RPC approach SIDESTEPS this ambiguity entirely — the SQL function body inside `ops_accept` writes the `INSERT … ON CONFLICT (user_id, request_hash) WHERE status IN ('queued','running','succeeded') DO NOTHING` directly with the explicit predicate, so PostgREST's upsert magic is not in the path. The PR #30 C3 fix relied on PostgREST's `ignore_duplicates=True`; the new design relies on raw SQL inside the SECURITY DEFINER function — strictly more robust.

**Citations:**
- `supabase/website/_v2/48_operations.sql:10-21` (current schema, CHECK, PK).
- `supabase/website/_v2/48_operations.sql:23-24` (existing index).
- https://www.postgresql.org/docs/current/indexes-partial.html (partial unique indexes; accessed 2026-05-20).
- https://www.postgresql.org/docs/current/sql-insert.html (ON CONFLICT, index_predicate; accessed 2026-05-20).
- https://www.postgresql.org/docs/current/sql-createindex.html (CONCURRENTLY transaction restriction; accessed 2026-05-20).

**Impact on Phase 1+:**
- Add data-backfill `UPDATE core.operations SET status='queued' WHERE status='accepted'` BEFORE the new CHECK constraint swap.
- Split migration 51 into a transactional file and a separate `CREATE INDEX CONCURRENTLY` file (or trust the runner to handle a CONCURRENTLY statement outside the txn block) — Phase 1 Step 2 must verify `ops/scripts/apply_migrations.py` behavior and report. Default recommendation: ship as `51_operations_state_machine.sql` (CHECK + RPCs in txn) + `51a_operations_partial_unique.sql` (CONCURRENTLY index, no txn).
- The `INSERT` inside `ops_accept` SQL function MUST repeat the partial-index predicate in its `ON CONFLICT (user_id, request_hash) WHERE status IN ('queued','running','succeeded') DO NOTHING` clause to guarantee inference.

### Step 3 — pg_cron job amendment vs add

**Verified findings:**
- Migration 49 (`supabase/website/_v2/49_operations_sweep.sql:18-29`) creates job `'sweep_stale_operations'` running `DELETE FROM core.operations WHERE expires_at < now()` every hour at `:00 UTC`, idempotently guarded by `IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'sweep_stale_operations')`.
- pg_cron supports `cron.alter_job(job_id, schedule, command, database, username, active)` for in-place modification. Signature: *"CREATE OR REPLACE FUNCTION cron.alter_job(job_id bigint, schedule text DEFAULT NULL::text, command text DEFAULT NULL::text, database text DEFAULT NULL::text, username text DEFAULT NULL::text, active boolean DEFAULT NULL::boolean) RETURNS void"*. Cited: https://github.com/citusdata/pg_cron/blob/main/README.md (accessed 2026-05-20).
- `cron.schedule(name, schedule, command)` does NOT have documented upsert/replace behavior; calling it twice with the same name is not guaranteed to replace. Safe pattern is `cron.unschedule(name)` then `cron.schedule(name, ...)`, or look up the job_id and call `cron.alter_job(job_id, ...)`.

**Recommendation (must operator-confirm in Phase 4, not auto-decided here):** Ship the stuck-running reaper as a SEPARATE new pg_cron job in a NEW migration `57_stuck_running_reaper.sql` (per the plan filename) with its own job name `'reap_stuck_running_operations'`, not by modifying job 49's command. Rationale:
1. Separation of concerns: TTL sweep (DELETE expired) and stuck-running reaper (UPDATE running→failed) have different cadences and different blast radii.
2. Migration hygiene: migration 49 is already live in prod; amending its body would require a destructive `cron.unschedule` + re-`cron.schedule` (or `cron.alter_job(job_id, command:=...)`), introducing a brief window where the sweep is unscheduled if the migration is interrupted.
3. Idempotency: the same `IF NOT EXISTS` guard pattern from migration 49 trivially extends.

**Citations:**
- `supabase/website/_v2/49_operations_sweep.sql:18-29`.
- https://github.com/citusdata/pg_cron/blob/main/README.md `cron.alter_job` signature + `cron.schedule` semantics (accessed 2026-05-20).

**Impact on Phase 1+:** Phase 4 step 3 SHOULD ship as standalone migration 57 with a new job name, per the recommendation above. The plan body already aligns with this (it names `57_stuck_running_reaper.sql`); the open option to "amend 49 if cleanly possible" is REJECTED here for the three reasons listed.

### Step 4 — RFC 9457 exact field set

**Verified findings:**
- MIME type: `application/problem+json`. Cited: RFC 9457 §3.
- Members (ALL optional per the spec, but conventionally the type + title + status triple is sent):
  - `type` — *"URI reference that identifies the problem type"* (RFC 9457 §3.1.1).
  - `title` — *"Short, human-readable summary of the problem type"* (§3.1.2).
  - `status` — *"JSON number indicating the HTTP status code generated by origin server"* (§3.1.3).
  - `detail` — *"Human-readable explanation specific to this occurrence"* (§3.1.4).
  - `instance` — *"URI reference identifying the specific occurrence of the problem"* (§3.1.5).
- Extension members (§3.2): problem type definitions MAY add type-specific top-level members. Consumers MUST ignore unrecognized extensions. Names: ≥3 chars, start with letter, alphanumeric + underscore, conform to XML Name rules.
- Current `_problem()` implementation (`website/api/zettels_routes.py:104-124`) ALREADY emits a close-but-not-exact shape:
  - Sets `type` as `https://zettelkasten.in/problems/errors/{type_slug}` (note the extra `errors/` path segment).
  - Sets `title`, `status`, `detail`, `instance` correctly.
  - Sets `operation_id` as a top-level extension (when present) — VALID per §3.2.
  - Spreads `extra` keys at top level — VALID per §3.2.
  - Uses `media_type="application/problem+json"` correctly.

**Mapping (Phase 3 unification — exact target shape):**
```python
{
  "type":     f"https://zettelkasten.in/problems/{type_slug}",   # drop "errors/" segment for cleaner URN
  "title":    title,
  "status":   status_code,
  "detail":   detail,
  "instance": f"/api/zettels/operations/{operation_id}" if operation_id else request.url.path,
  "code":     type_slug,    # extension — keys frontend dispatch (already used: e.g. "quota_exhausted")
  **(extra or {}),          # additional extensions (e.g. retry_after, plan_required)
}
```
Decision item for operator at Phase 3: keep current `type` prefix `errors/` or drop it. Recommendation: drop `errors/` for cleanliness; document the change is purely cosmetic since clients key off `code` (extension), not `type`. **Operator approval needed before Phase 3 ships the change** (per "Beyond-Plan = New Decision" rule — the plan body shows the URL without `errors/`, so adopting the cleaner URL is in-plan; but the user-facing URL change is observable and worth a confirmation).

**Citations:**
- https://www.rfc-editor.org/rfc/rfc9457.html §3, §3.1.1-5, §3.2 (accessed 2026-05-20).
- `website/api/zettels_routes.py:104-124` (current `_problem()` body).

**Impact on Phase 1+:** Phase 3 unification is straightforward — the only field mapping changes are (a) drop `errors/` segment in `type` (or retain — operator's call), (b) standardize `instance` to `/api/zettels/operations/{op_id}` (current uses `/api/zettels/add/{op_id}`), (c) ensure `code` extension is always set to `type_slug`. The async path's `finalize(error=...)` writes the SAME dict; GET endpoint returns it verbatim under `body.error`. Frontend contract (`body.error.code`) is preserved.

### Step 5 — Supabase / asyncpg pool reuse

**Verified findings:**
- `website/core/supabase_v2/client.py:96-104` — `get_v2_client()` is `@lru_cache(maxsize=1)` (singleton), creates a single `Client` with an explicit `httpx.Client(timeout=..., limits=httpx.Limits(max_keepalive_connections=8, max_connections=16))`. The connection pool is keep-alive-capped at 8 across all calls.
- `client.schema('core').rpc(...)` and `client.schema('core').table(...).select(...)` BOTH route through the same underlying `SyncPostgrestClient` (the `Client.schema()` method delegates to `self.postgrest.schema(schema)` which returns a per-call wrapper that shares the parent's `session` — the same `httpx.Client`). So RPC calls reuse the same HTTP connection pool as table reads. No new connections per RPC; the connection-budget impact of adding `accept` → `start` → poll → `finalize` is purely throughput on the existing pool.
- Expected per-add-zettel cycle DB traffic: 1× POST `/rpc/ops_accept` + 1× POST `/rpc/ops_start` + N× GET `/operations?...` (one per poll) + 1× POST `/rpc/ops_finalize` = (3 + N) requests against the keep-alive pool. At baseline poll cadence (1s for 180s budget) and current user load (~10-15 users), this is well below the pool's max-keepalive=8 cap.
- Backpressure-gate read (`count_in_flight_for_user`) adds 1 more SELECT per accept. Acceptable cost; Phase 4 plan body already notes the 1ms-ish overhead and the deferred lru_cache optimization.

**Citations:**
- `website/core/supabase_v2/client.py:77-104` (singleton + httpx.Limits configuration).
- `<site-packages>/supabase/_sync/client.py::Client.schema` (delegation to `self.postgrest.schema(...)`).

**Impact on Phase 1+:** Zero new connection-pool tuning required. The 4-RPC-per-add-zettel cycle reuses the existing 8-keepalive pool. No new DigitalOcean droplet RAM or connection-budget impact (per CLAUDE.md guardrails — protected knobs untouched).

### Phase 0 verdict

**READY for Phase 1**, with two amendments the implementer MUST fold into the Phase 1 SQL writes (neither is a scope change; both are derived from the spec):

1. **Add `GRANT EXECUTE ON FUNCTION core.ops_accept(...) TO service_role;` (and `ops_start`, `ops_finalize`)** in migration 51 — without it, PostgREST returns 401/403 for the new RPCs even though the table grant exists.
2. **Add data backfill `UPDATE core.operations SET status='queued' WHERE status='accepted';`** in migration 51 BEFORE swapping the CHECK constraint — otherwise the new CHECK rejects in-flight rows.
3. **Split migration 51** into a transactional file (CHECK + RPCs) plus a non-transactional `51a` for `CREATE UNIQUE INDEX CONCURRENTLY` — UNLESS Phase 1 Step 2 verifies `ops/scripts/apply_migrations.py` already handles CONCURRENTLY statements outside the file's transaction.

No blockers. Live-doc fetches all returned canonical guidance; package source confirms the call shapes the wrappers will use; existing project files (48, 49, operations_repo.py, supabase_v2/client.py) align with the design.

