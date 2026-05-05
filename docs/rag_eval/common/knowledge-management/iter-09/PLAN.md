# iter-09 RAG-eval Recovery Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read [RESEARCH.md](RESEARCH.md) before each phase.

**Goal:** Close the iter-04..iter-08 chapter on the KM Kasten by hitting composite ≥85, gold@1 ≥ 0.85, all 14 queries running with high confidence under multi-user concurrency. Recover the rerank-score regression (77.86 → 49.31) and restore burst-pressure 503 backpressure.

**Architecture:**
- Two production-touching changes (RES-1 critic-skip gate, RES-2 class-gated chunk-share) plus harness measurement truth (RES-5).
- One CLAUDE.md-guarded fix (RES-4 admission wire) gated on explicit chat approval already given.
- Two carry-forward iter-09 originals (warm-up, anchor-seed RPC) and the Postgres CHECK constraint migration that unblocks new verdict strings.
- Router rule-5 narrowing PRECEDES new router rules; cache invalidation via `ROUTER_VERSION` bump.
- Magnet-rerank-penalty and auto-title-side-effect refactor explicitly DEFERRED to iter-10.

**Tech Stack:** Python 3.12, FastAPI/uvicorn/gunicorn, asyncio, pytest + pytest-asyncio, Supabase Postgres + pgvector, BGE int8 cross-encoder, Gemini 2.5 (flash / flash-lite / pro), Caddy 2, Docker Compose blue/green on DigitalOcean droplet, Playwright Python harness.

---

## File Structure

| File | Responsibility | Phase / Task |
|---|---|---|
| `ops/scripts/eval_iter_03_playwright.py` | Add SSE-aware reader + `p_user_*_ms` fields; warm-up ping | 1 / 3, 4 + 2 / 5 |
| `tests/unit/ops_scripts/test_eval_sse_reader.py` | New: 5 SSE-parser cases | 1 / 3 |
| `.github/workflows/read_recent_logs.yml` | Add `lines` and `since` workflow_dispatch inputs | 2 / 6 |
| `supabase/website/kg_public/migrations/2026-05-04_chat_messages_verdict_constraint_v2.sql` | New: drop+recreate verdict CHECK allowlist | 2 / 7 |
| `supabase/website/kg_public/migrations/2026-05-04_rag_fetch_anchor_seeds.sql` | New: anchor-seed RPC with INNER JOIN sandbox_members | 2 / 8 |
| `website/features/rag_pipeline/retrieval/anchor_seed.py` | New: thin client for `rag_fetch_anchor_seeds` RPC | 2 / 8 |
| `website/features/rag_pipeline/retrieval/hybrid.py` | Wire anchor-seed fan-out into `retrieve()` loop | 2 / 8 |
| `website/features/rag_pipeline/query/router.py` | Narrow rule 5; add 3 new override rules; add LRU cache; bump `ROUTER_VERSION` | 2 / 9 |
| `tests/unit/rag_pipeline/query/test_router_overrides.py` | New: 6 cases (3 narrow rule 5, 3 new rules with counter-examples) | 2 / 9 |
| `tests/unit/rag_pipeline/query/test_router_cache.py` | New: cache-hit / version-bump / TTL eviction | 2 / 9 |
| `website/features/rag_pipeline/orchestrator.py` | Add `unsupported_with_gold_skip` gate + `_GOLD_RETRIEVED_DETAILS_TAG` | 3 / 10 |
| `tests/unit/rag/test_orchestrator_retry_policy.py` | New `_should_skip_retry` cases for the new gate | 3 / 10 |
| `website/features/rag_pipeline/retrieval/chunk_share.py` | Add `should_apply_chunk_share(class, counts)` ratio-to-median check | 3 / 11 |
| `website/features/rag_pipeline/retrieval/hybrid.py` | Gate chunk-share by class + magnet detection | 3 / 11 |
| `tests/unit/rag/retrieval/test_chunk_share.py` | 4 new cases: LOOKUP-no-damp, THEMATIC+uniform-no-damp, THEMATIC+outlier-damp, cold-start-no-damp | 3 / 11 |
| `website/api/chat_routes.py` | Wrap `_run_answer` in `acquire_rerank_slot()`; return 503 `Retry-After:5` on `QueueFull` | 4 / 12 |
| `tests/unit/api/test_chat_routes_admission.py` | New: 503 fires on adhoc non-stream path | 4 / 12 |
| `ops/.env.example` | Document new env flags | 2 / 9 + 3 / 10 + 3 / 11 |

---

## Phase 0 — Pre-flight (no code changes)

### Task 1: Pull droplet logs around iter-08 q5 500 timestamp

**Files:** none (workflow_dispatch only, after Task 6 ships).

- [ ] **Step 1: After Task 6 (workflow input) lands, dispatch the workflow with `since=2026-05-03T15:48:00Z lines=20000`.**

```bash
gh workflow run read_recent_logs.yml -f since=2026-05-03T15:48:00Z -f lines=20000
gh run list --workflow=read_recent_logs.yml --limit 1
```

- [ ] **Step 2: Read the resulting log artefact, `grep -iE "q5|500 |Traceback|HTTPException|chunk_share|entity_anchor|rag_resolve|rag_one_hop|rag_fetch|TypeError|KeyError|AttributeError"`.**

Expected: surfaces a single traceback within ~1 minute of `15:50:43 UTC`. Save excerpt to `docs/rag_eval/common/knowledge-management/iter-09/q5_500_traceback.txt`.

- [ ] **Step 3: Decide.**

If traceback names a deterministic null-deref / KeyError in the chunk-share or anchor RPC consumer path: open new task in Phase 5 with the pinpoint fix and stop-and-ask. If traceback is ambiguous or out-of-process (worker SIGKILL), keep q5 in HOLD; iter-09 stops here for that query.

### Task 2: Verify `_run_answer` admission wire (read-only)

**Files:** none.

- [ ] **Step 1: Run the diagnostic grep.**

```bash
grep -rn "acquire_rerank_slot\|_run_answer\|state.depth" website/api/chat_routes.py
```

Expected exact output:
- `acquire_rerank_slot` at L16 (import) and L240 (stream wrap) only
- `_run_answer` at L156, L457 (or near), L509 — none wrapped
- `state.depth` at L439, L489 (peek only)

- [ ] **Step 2: Confirm in chat that the wire-mismatch matches RES-4.**

If the layout has drifted (line numbers shifted but pattern matches), proceed. If `_run_answer` IS already wrapped, skip Phase 4 / Task 12.

---

## Phase 1 — Harness truth (60–90 min, harness-only, no production touch)

### Task 3: SSE-aware harness reader

**Files:**
- Modify: `ops/scripts/eval_iter_03_playwright.py:540–600` (add `api_fetch_sse` helper) and `:1053–1086` (call-site flip + new fields)
- Test: `tests/unit/ops_scripts/test_eval_sse_reader.py` (new)

- [ ] **Step 1: Write the failing test file.**

```python
# tests/unit/ops_scripts/test_eval_sse_reader.py
"""SSE byte-stream parser tests for the iter-09 harness reader.

Tests the JS-side reader logic indirectly by extracting the parser into a
pure-Python equivalent at ops/scripts/_sse_reader.py for unit testing. The
in-page Playwright `fetch().getReader()` consumer mirrors this behaviour.
"""
from ops.scripts._sse_reader import parse_sse_stream


def test_token_then_done_emits_first_and_complete():
    chunks = [
        b"event: token\ndata: \"hello\"\n\n",
        b"event: token\ndata: \" world\"\n\n",
        b"event: done\ndata: {\"turn\":{\"id\":\"t1\"}}\n\n",
    ]
    out = parse_sse_stream(chunks)
    assert out["p_user_first_token_ms"] is not None
    assert out["p_user_last_token_ms"] is not None
    assert out["p_user_complete_ms"] is not None
    assert out["p_user_first_token_ms"] <= out["p_user_last_token_ms"] <= out["p_user_complete_ms"]


def test_done_without_tokens_records_complete_only():
    chunks = [b"event: done\ndata: {\"turn\":{\"id\":\"t1\"}}\n\n"]
    out = parse_sse_stream(chunks)
    assert out["p_user_first_token_ms"] is None
    assert out["p_user_complete_ms"] is not None


def test_error_mid_stream_records_error():
    chunks = [
        b"event: token\ndata: \"hi\"\n\n",
        b"event: error\ndata: {\"code\":\"queue_full\"}\n\n",
    ]
    out = parse_sse_stream(chunks)
    assert out["error"] == {"code": "queue_full"}
    assert out["p_user_complete_ms"] is None


def test_heartbeat_only_then_done_does_not_miscount():
    chunks = [
        b": heartbeat\n\n",
        b": heartbeat\n\n",
        b"event: done\ndata: {\"turn\":{}}\n\n",
    ]
    out = parse_sse_stream(chunks)
    assert out["p_user_first_token_ms"] is None
    assert out["p_user_complete_ms"] is not None


def test_partial_frame_buffer_reassembly():
    chunks = [
        b"event: tok",
        b"en\ndata: \"split\"\n\n",
        b"event: done\ndata: {\"turn\":{}}\n\n",
    ]
    out = parse_sse_stream(chunks)
    assert out["p_user_first_token_ms"] is not None
    assert out["p_user_complete_ms"] is not None
```

- [ ] **Step 2: Run the failing test.**

```bash
pytest tests/unit/ops_scripts/test_eval_sse_reader.py -v
```

Expected: ImportError on `ops.scripts._sse_reader`.

- [ ] **Step 3: Implement the minimal `_sse_reader.py` parser.**

Create `ops/scripts/_sse_reader.py` with `parse_sse_stream(chunks: Iterable[bytes]) -> dict` returning `{p_user_first_token_ms, p_user_last_token_ms, p_user_complete_ms, error}`. Use a wall-clock approximation (monotonic ns deltas between chunk yields) sufficient to satisfy ordering invariants in tests; production timing is JS-side `performance.now()`.

```python
# ops/scripts/_sse_reader.py
"""Pure-Python SSE parser used to unit-test the iter-09 harness reader.

The in-page Playwright reader uses `r.body.getReader()` and `performance.now()`
for true wall-clock; this module replicates the framing logic so behaviour can
be validated without a browser.
"""
from __future__ import annotations

import json
import re
import time
from typing import Iterable


_FRAME_END = b"\n\n"
_EVENT_RE = re.compile(rb"event:\s*(\S+)")
_DATA_RE = re.compile(rb"data:\s*(.*)", re.DOTALL)


def parse_sse_stream(chunks: Iterable[bytes]) -> dict:
    t0 = time.monotonic_ns()
    buf = b""
    first_token_ns: int | None = None
    last_token_ns: int | None = None
    done_ns: int | None = None
    error: dict | None = None

    for chunk in chunks:
        buf += chunk
        while True:
            idx = buf.find(_FRAME_END)
            if idx < 0:
                break
            frame, buf = buf[:idx], buf[idx + len(_FRAME_END):]
            if frame.startswith(b":"):
                continue  # heartbeat
            ev_match = _EVENT_RE.search(frame)
            data_match = _DATA_RE.search(frame)
            if ev_match is None:
                continue
            ev = ev_match.group(1).decode("utf-8")
            now_ns = time.monotonic_ns()
            if ev == "token":
                if first_token_ns is None:
                    first_token_ns = now_ns
                last_token_ns = now_ns
            elif ev == "done":
                done_ns = now_ns
                break
            elif ev == "error" and data_match:
                try:
                    error = json.loads(data_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    error = {"raw": data_match.group(1).decode("utf-8", "replace")}
                break

    def _to_ms(ns: int | None) -> float | None:
        return None if ns is None else (ns - t0) / 1_000_000

    return {
        "p_user_first_token_ms": _to_ms(first_token_ns),
        "p_user_last_token_ms": _to_ms(last_token_ns),
        "p_user_complete_ms": _to_ms(done_ns),
        "error": error,
    }
```

- [ ] **Step 4: Run the test to verify pass.**

```bash
pytest tests/unit/ops_scripts/test_eval_sse_reader.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit.**

```bash
git add ops/scripts/_sse_reader.py tests/unit/ops_scripts/test_eval_sse_reader.py
git commit -m "feat: sse parser for harness p_user metrics"
```

### Task 4: Wire SSE reader into the harness

**Files:**
- Modify: `ops/scripts/eval_iter_03_playwright.py:540–600`, `:974`, `:1053–1086`, `:1286`

- [ ] **Step 1: Add `api_fetch_sse(page, path, token, body, timeout_ms)` JS evaluator** as a sibling of `api_fetch_json`. The JS reads `r.body.getReader()` and parses framed SSE with `performance.now()` timestamps for `event: token`, `event: done`, `event: error`. Returns `{turn, citations, p_user_first_token_ms, p_user_last_token_ms, p_user_complete_ms, elapsed_ms, error}`.

- [ ] **Step 2: At the existing `phase_rag_qa_chain` call site (around L1058), add an env-gated branch:**

```python
USE_SSE = os.environ.get("EVAL_USE_SSE_HARNESS", "true").lower() not in ("false", "0", "no", "off")
if USE_SSE:
    body["stream"] = True
    sse_result = api_fetch_sse(page, "/api/rag/adhoc", token, body=body, timeout_ms=120_000)
    elapsed_ms = sse_result.get("p_user_complete_ms") or sse_result.get("elapsed_ms")
    detail.update({k: sse_result.get(k) for k in ("p_user_first_token_ms", "p_user_last_token_ms", "p_user_complete_ms")})
    # within_budget now uses p_user_complete_ms
    detail["within_budget"] = bool(elapsed_ms is not None and elapsed_ms <= budget_ms)
else:
    body["stream"] = False
    resp = api_fetch_json(page, "/api/rag/adhoc", token, method="POST", body=body, timeout_ms=120_000)
    # ... existing path unchanged
```

- [ ] **Step 3: Update `_qa_summary` (around L1286) to add `p95_p_user_complete_ms`, `p95_p_user_first_token_ms`.**

- [ ] **Step 4: Manual smoke run.**

```powershell
$env:EVAL_USE_SSE_HARNESS="true"; python ops\scripts\eval_iter_03_playwright.py --iter iter-09-smoke
```

Expected: harness completes; `verification_results.json` contains the new fields and `p_user_complete_ms` is dramatically lower than `elapsed_ms` for fast queries (closer to `latency_ms_server` than to 30–50s).

- [ ] **Step 5: Commit.**

```bash
git add ops/scripts/eval_iter_03_playwright.py
git commit -m "feat: harness p_user metrics via stream:true sse"
```

---

## Phase 2 — Carry-forward iter-09 originals + admission CHECK + router

### Task 5: Warm-up ping in eval harness

**Files:**
- Modify: `ops/scripts/eval_iter_03_playwright.py` (near the existing public_pages phase, before `phase_rag_qa_chain`)

- [ ] **Step 1: Add a `warmup_ping()` helper that issues `GET /api/health` up to 3 times with 2s sleeps; logs success/failure but does NOT abort the eval.**

```python
def warmup_ping(page, max_attempts: int = 3, sleep_s: float = 2.0) -> dict:
    """iter-09: hit /api/health to dodge BGE int8 cold-start on the first eval query."""
    last = {"ok": False, "attempts": 0, "elapsed_ms": 0}
    for i in range(1, max_attempts + 1):
        t0 = time.monotonic()
        try:
            resp = page.evaluate("async () => (await fetch('/api/health')).status")
            last = {"ok": resp == 200, "attempts": i, "status": resp,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000)}
            if resp == 200:
                return last
        except Exception as exc:  # noqa: BLE001
            last = {"ok": False, "attempts": i, "error": type(exc).__name__,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000)}
        time.sleep(sleep_s)
    return last
```

- [ ] **Step 2: Call before `phase_rag_qa_chain`.**

```python
warmup = warmup_ping(page)
phases.append({"phase": "warmup_ping", "duration_ms": warmup.get("elapsed_ms", 0),
               "checks": [{"name": "warmup", "passed": warmup.get("ok", False), "detail": warmup}]})
```

- [ ] **Step 3: Commit.**

```bash
git add ops/scripts/eval_iter_03_playwright.py
git commit -m "feat: warm-up ping before rag qa chain"
```

### Task 6: Log-pull workflow inputs

**Files:**
- Modify: `.github/workflows/read_recent_logs.yml`

- [ ] **Step 1: Add `inputs.lines` (default `5000`) and `inputs.since` (default empty)** to the workflow_dispatch block.

- [ ] **Step 2: In the run step, build the `journalctl --since "$INPUTS_SINCE"` and `--lines $INPUTS_LINES` flags conditionally.** When `since` is empty, default to current behaviour (`--lines 500`).

- [ ] **Step 3: Commit.**

```bash
git add .github/workflows/read_recent_logs.yml
git commit -m "ops: read_recent_logs workflow inputs lines and since"
```

### Task 7: Postgres CHECK constraint v2

**Files:**
- Create: `supabase/website/kg_public/migrations/2026-05-04_chat_messages_verdict_constraint_v2.sql`

- [ ] **Step 1: Author the migration.**

```sql
-- iter-09 RES-7 + RES-1: drop+recreate chat_messages_critic_verdict_check
-- to allow new verdict strings shipped iter-08..iter-09 without breaking
-- existing rows. Backwards-compatible: validates new inserts only.
BEGIN;

ALTER TABLE chat_messages
    DROP CONSTRAINT IF EXISTS chat_messages_critic_verdict_check;

ALTER TABLE chat_messages
    ADD CONSTRAINT chat_messages_critic_verdict_check
    CHECK (
        critic_verdict IS NULL OR critic_verdict IN (
            'supported',
            'partial',
            'unsupported',
            'retried_supported',
            'retried_low_confidence',
            'retry_failed',
            'retry_skipped_dejavu',
            'unsupported_no_retry',
            'partial_with_gold_skip',
            'retry_budget_exceeded',
            'unsupported_with_gold_skip'
        )
    ) NOT VALID;

ALTER TABLE chat_messages
    VALIDATE CONSTRAINT chat_messages_critic_verdict_check;

COMMIT;
```

- [ ] **Step 2: Apply via the existing idempotent `apply_iter08_migrations.py` pattern.** Confirm the script supports the new file (it picks up everything in the migrations dir matching the date pattern).

- [ ] **Step 3: Re-verify RES-2 kasten_freq diagnosis.**

```bash
# After CHECK fix, query chat_messages for a sample of recent supported verdicts
# and confirm record_hit calls succeeded. If the iter-08 record_hit data was
# being silently rejected, kasten_freq's "always-off" floor=50 reasoning is
# invalid and the prior iters' dataset is contaminated.
python ops/scripts/diagnose_kasten_freq.py --since=2026-04-26 > docs/rag_eval/common/knowledge-management/iter-09/kasten_freq_recheck.md
```

If the script doesn't exist, defer to a follow-up task.

- [ ] **Step 4: Commit.**

```bash
git add supabase/website/kg_public/migrations/2026-05-04_chat_messages_verdict_constraint_v2.sql
git commit -m "fix: chat_messages verdict check allowlist v2"
```

### Task 8: Q10 anchor seed RPC + injection

**Files:**
- Create: `supabase/website/kg_public/migrations/2026-05-04_rag_fetch_anchor_seeds.sql`
- Create: `website/features/rag_pipeline/retrieval/anchor_seed.py`
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py` (around the `retrieve()` post-RPC fan-out)
- Test: `tests/unit/rag_pipeline/retrieval/test_anchor_seed.py` (new)

- [ ] **Step 1: Write the failing test.**

```python
# tests/unit/rag_pipeline/retrieval/test_anchor_seed.py
import pytest
from website.features.rag_pipeline.retrieval.anchor_seed import fetch_anchor_seeds


class _Stub:
    def __init__(self, rows):
        self._rows = rows
    def rpc(self, name, params):
        assert name == "rag_fetch_anchor_seeds"
        assert "p_sandbox_id" in params and "p_anchor_nodes" in params and "p_query_embedding" in params
        return self
    def execute(self):
        class R:
            data = self._rows  # noqa: B023
        return R()


@pytest.mark.asyncio
async def test_returns_seeds_when_rpc_succeeds():
    stub = _Stub([{"node_id": "yt-x", "score": 0.42}])
    seeds = await fetch_anchor_seeds(["jobs"], "00000000-0000-0000-0000-000000000000", [0.1] * 768, stub)
    assert seeds == [{"node_id": "yt-x", "score": 0.42}]


@pytest.mark.asyncio
async def test_empty_anchors_returns_empty():
    stub = _Stub([{"node_id": "yt-x", "score": 0.42}])
    seeds = await fetch_anchor_seeds([], "00000000-0000-0000-0000-000000000000", [0.1] * 768, stub)
    assert seeds == []


@pytest.mark.asyncio
async def test_rpc_exception_returns_empty():
    class Bad:
        def rpc(self, *a, **k):
            raise RuntimeError("boom")
    seeds = await fetch_anchor_seeds(["jobs"], "00000000-0000-0000-0000-000000000000", [0.1] * 768, Bad())
    assert seeds == []
```

- [ ] **Step 2: Run the test to verify failure.**

```bash
pytest tests/unit/rag_pipeline/retrieval/test_anchor_seed.py -v
```

Expected: ImportError on `anchor_seed`.

- [ ] **Step 3: Implement the migration SQL.**

```sql
-- iter-09 RES-7 / Q10: anchor-seed RPC. Returns seed candidates for the
-- supplied anchor node ids restricted to the sandbox's members. INNER JOIN
-- on rag_sandbox_members is mandatory for cross-tenant safety.
BEGIN;

CREATE OR REPLACE FUNCTION rag_fetch_anchor_seeds(
    p_sandbox_id    uuid,
    p_anchor_nodes  text[],
    p_query_embedding vector(768)
) RETURNS TABLE (node_id text, score double precision)
LANGUAGE sql STABLE AS $$
    SELECT m.node_id,
           1 - (kc.embedding <=> p_query_embedding) AS score
    FROM rag_sandbox_members m
    INNER JOIN kg_node_chunks kc ON kc.node_id = m.node_id
    WHERE m.sandbox_id = p_sandbox_id
      AND m.node_id = ANY(p_anchor_nodes)
    ORDER BY score DESC
    LIMIT 8;
$$;

GRANT EXECUTE ON FUNCTION rag_fetch_anchor_seeds(uuid, text[], vector) TO anon, authenticated;

COMMIT;
```

- [ ] **Step 4: Implement the Python client.**

```python
# website/features/rag_pipeline/retrieval/anchor_seed.py
"""iter-09 RES-7: anchor-seed RPC client for Q10-style cross-tenant safe seeding."""
from __future__ import annotations

from typing import Any
from uuid import UUID


async def fetch_anchor_seeds(
    anchor_nodes: list[str],
    sandbox_id: UUID | str | None,
    query_embedding: list[float],
    supabase: Any,
) -> list[dict]:
    """Fetch seed candidates for anchor nodes restricted to the sandbox's members.

    Returns a list of `{node_id, score}` dicts. RPC failure or empty input
    degrades to empty list (mirrors entity_anchor.py error semantics).
    """
    if not anchor_nodes or sandbox_id is None or not query_embedding:
        return []
    try:
        response = supabase.rpc(
            "rag_fetch_anchor_seeds",
            {
                "p_sandbox_id": str(sandbox_id),
                "p_anchor_nodes": list(anchor_nodes),
                "p_query_embedding": list(query_embedding),
            },
        ).execute()
        return list(response.data or [])
    except Exception:
        return []
```

- [ ] **Step 5: Run the test to verify pass.**

```bash
pytest tests/unit/rag_pipeline/retrieval/test_anchor_seed.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Wire into `hybrid.py:retrieve()` post-RPC fan-out.**

After the existing entity-anchor resolution (and before the candidate dedup), add a gated fan-out:

```python
# iter-09 RES-7 / Q10: anchor-seed injection
import os as _os
_ANCHOR_SEED_ENABLED = _os.environ.get("RAG_ANCHOR_SEED_INJECTION_ENABLED", "true").lower() not in ("false", "0", "no", "off")
_ANCHOR_SEED_FLOOR_RRF = 0.30

if _ANCHOR_SEED_ENABLED and anchor_nodes:
    compare = bool(getattr(query_metadata, "compare_intent", False))
    n_anchors = len(anchor_nodes)
    is_lookup = query_class is QueryClass.LOOKUP
    n_persons = len(getattr(query_metadata, "authors", None) or [])
    n_entities = len(getattr(query_metadata, "entities", None) or [])
    if compare or (is_lookup and (n_persons + n_entities) >= 1):
        from website.features.rag_pipeline.retrieval.anchor_seed import fetch_anchor_seeds
        seeds = await fetch_anchor_seeds(list(anchor_nodes), sandbox_id, query_embedding, supabase)
        for seed in seeds:
            nid = seed.get("node_id")
            if not nid:
                continue
            existing = by_key.get(nid)
            if existing is None:
                # synthesize a candidate at floor; cross-encoder decides final rank
                by_key[nid] = RetrievalCandidate(
                    node_id=nid,
                    rrf_score=max(seed.get("score", 0.0), _ANCHOR_SEED_FLOOR_RRF),
                    # ... fill remaining fields from a stub-fetch; defer to existing helper
                )
            else:
                existing.rrf_score = max(existing.rrf_score, _ANCHOR_SEED_FLOOR_RRF)
```

(Exact attribute names to match `RetrievalCandidate` dataclass — executor: read the dataclass and adapt.)

- [ ] **Step 7: Apply migration manually.**

```bash
python ops/scripts/apply_iter08_migrations.py --file 2026-05-04_rag_fetch_anchor_seeds.sql
```

- [ ] **Step 8: Commit.**

```bash
git add supabase/website/kg_public/migrations/2026-05-04_rag_fetch_anchor_seeds.sql website/features/rag_pipeline/retrieval/anchor_seed.py website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag_pipeline/retrieval/test_anchor_seed.py
git commit -m "feat: anchor seed injection for q10"
```

### Task 9: Router rule-5 narrow + new rules + LRU cache + ROUTER_VERSION bump

**Files:**
- Modify: `website/features/rag_pipeline/query/router.py`
- Test: `tests/unit/rag_pipeline/query/test_router_overrides.py` (new)
- Test: `tests/unit/rag_pipeline/query/test_router_cache.py` (new)

- [ ] **Step 1: Write the failing override test.**

```python
# tests/unit/rag_pipeline/query/test_router_overrides.py
import pytest
from website.features.rag_pipeline.query.router import apply_class_overrides
from website.features.rag_pipeline.query.types import QueryClass


# Narrowed rule 5: word_count threshold is 25 (was 18).
def test_rule5_narrow_22_word_lookup_no_persons_stays_lookup():
    """iter-09 RES-6: 22-word LOOKUP (q13-shape) must stay LOOKUP."""
    q = "What does the Pragmatic Engineer newsletter mean by a product-minded engineer and how it differs from implementation-focused"
    cls, reason = apply_class_overrides(q, QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.LOOKUP
    assert reason is None or reason != "override_long_query_upgrade"


def test_rule5_narrow_19_word_matuschak_lookup_stays_lookup():
    """iter-09 RES-6: 19-word LOOKUP (q14-shape) must stay LOOKUP."""
    q = "In Matuschak's Transformative Tools for Thought essay what specifically does he mean by an augmented book"
    cls, reason = apply_class_overrides(q, QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.LOOKUP


def test_rule5_still_fires_at_25_words_no_persons():
    """iter-09 RES-6: at >=25 words rule 5 still upgrades to MULTI_HOP (q3-shape protection)."""
    q = " ".join(["word"] * 25 + ["?"])
    cls, reason = apply_class_overrides(q, QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.MULTI_HOP
    assert reason == "override_long_query_upgrade"


# New rules from iter-09 item 5C
def test_double_question_mark_routes_to_multi_hop():
    cls, reason = apply_class_overrides("What is X? And what is Y?", QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.MULTI_HOP
    assert reason == "override_double_question"


def test_single_question_mark_does_not_route_multi_hop():
    cls, reason = apply_class_overrides("What is X?", QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.LOOKUP


def test_how_does_relate_to_routes_multi_hop():
    cls, reason = apply_class_overrides("how does X relate to Y", QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.MULTI_HOP
    assert reason == "override_relate_pattern"


def test_how_does_work_does_not_match_relate():
    cls, reason = apply_class_overrides("how does X work", QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.LOOKUP


def test_summary_of_routes_thematic():
    cls, reason = apply_class_overrides("summary of the kasten", QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.THEMATIC
    assert reason == "override_summary_of_pattern"


def test_summary_table_does_not_match():
    cls, reason = apply_class_overrides("summary table for the report", QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.LOOKUP
```

- [ ] **Step 2: Write the failing cache test.**

```python
# tests/unit/rag_pipeline/query/test_router_cache.py
import asyncio
import pytest
from website.features.rag_pipeline.query.router import QueryRouter, ROUTER_VERSION
from website.features.rag_pipeline.query.types import QueryClass


class _StubPool:
    def __init__(self, response):
        self._response = response
        self.calls = 0
    async def generate_content(self, *a, **k):
        self.calls += 1
        return self._response


@pytest.mark.asyncio
async def test_classify_caches_repeat_query(monkeypatch):
    monkeypatch.setenv("ROUTER_CACHE_ENABLED", "true")
    pool = _StubPool('{"class":"lookup"}')
    router = QueryRouter(pool=pool, kasten_id="k1")
    cls1 = await router.classify("hello world")
    cls2 = await router.classify("hello world")
    assert cls1 is QueryClass.LOOKUP
    assert cls2 is QueryClass.LOOKUP
    assert pool.calls == 1


@pytest.mark.asyncio
async def test_router_version_bump_invalidates_cache(monkeypatch):
    monkeypatch.setenv("ROUTER_CACHE_ENABLED", "true")
    pool = _StubPool('{"class":"lookup"}')
    router_a = QueryRouter(pool=pool, kasten_id="k1")
    await router_a.classify("hello")
    monkeypatch.setattr("website.features.rag_pipeline.query.router.ROUTER_VERSION", "v_test_bump")
    router_b = QueryRouter(pool=pool, kasten_id="k1")
    await router_b.classify("hello")
    assert pool.calls == 2


@pytest.mark.asyncio
async def test_cache_disabled_via_env(monkeypatch):
    monkeypatch.setenv("ROUTER_CACHE_ENABLED", "false")
    pool = _StubPool('{"class":"lookup"}')
    router = QueryRouter(pool=pool, kasten_id="k1")
    await router.classify("hello")
    await router.classify("hello")
    assert pool.calls == 2
```

- [ ] **Step 3: Run both tests to verify failure.**

```bash
pytest tests/unit/rag_pipeline/query/test_router_overrides.py tests/unit/rag_pipeline/query/test_router_cache.py -v
```

- [ ] **Step 4: Implement the router changes.**

In `website/features/rag_pipeline/query/router.py`:
1. Add module constant `ROUTER_VERSION = "v3"`.
2. Add patterns: `_DOUBLE_QUESTION_PATTERN`, `_RELATE_PATTERN = re.compile(r"\bhow does .+ relate to .+", re.IGNORECASE)`, `_SUMMARY_OF_PATTERN = re.compile(r"\b(summary|summarize|key ideas) of\b", re.IGNORECASE)`.
3. In `apply_class_overrides`, insert new rules BEFORE the existing rule 5 word-count rule.
4. Modify rule 5 word-count threshold: `18` → `25`.
5. Modify `QueryRouter.__init__` to accept `kasten_id: str | None = None`.
6. Add `cachetools.TTLCache(maxsize=10_000, ttl=86400)` instance attribute.
7. In `classify`, build cache key `hashlib.sha256(f"{ROUTER_VERSION}|{self._kasten_id or ''}|{query.strip().lower()}".encode()).hexdigest()`, look up before LLM call, populate after.
8. Gate cache use on `os.environ.get("ROUTER_CACHE_ENABLED", "true")` not in falsey set.

- [ ] **Step 5: Run tests to verify pass.**

```bash
pytest tests/unit/rag_pipeline/query/ -v
```

Expected: all green (existing + new).

- [ ] **Step 6: Replay-stability check (informational, manual).**

Re-run the iter-04..iter-08 fixtures' queries through the router with rule changes; assert zero class flips between consecutive iters' identical queries.

- [ ] **Step 7: Commit.**

```bash
git add website/features/rag_pipeline/query/router.py tests/unit/rag_pipeline/query/test_router_overrides.py tests/unit/rag_pipeline/query/test_router_cache.py
git commit -m "feat: router rule5 narrow plus new rules and lru cache"
```

---

## Phase 3 — RES-1 + RES-2 production changes

### Task 10: `unsupported_with_gold_skip` retry-skip gate

**Files:**
- Modify: `website/features/rag_pipeline/orchestrator.py:165–214` (function `_should_skip_retry`) and tag definitions near `_LOW_CONFIDENCE_DETAILS_TAG`
- Test: `tests/unit/rag/test_orchestrator_retry_policy.py` (extend)

- [ ] **Step 1: Write failing tests.**

```python
# tests/unit/rag/test_orchestrator_retry_policy.py — append cases
import pytest
from website.features.rag_pipeline.orchestrator import _should_skip_retry, _GOLD_RETRIEVED_DETAILS_TAG
from website.features.rag_pipeline.query.types import QueryClass
from website.features.rag_pipeline.types import QueryMetadata


def _cand(score):
    class C:
        rerank_score = score
    return C()


def _meta():
    return QueryMetadata(authors=[], entities=[], compare_intent=False)


def test_lookup_unsupported_with_high_rerank_skips_retry(monkeypatch):
    monkeypatch.setenv("RAG_UNSUPPORTED_WITH_GOLD_SKIP_ENABLED", "true")
    skip, reason = _should_skip_retry(
        answer_text="some draft",
        used_candidates=[_cand(0.85)],
        query_class=QueryClass.LOOKUP,
        metadata=_meta(),
        first_verdict="unsupported",
    )
    assert skip is True
    assert reason == "unsupported_with_gold_skip"


def test_lookup_unsupported_with_low_rerank_still_retries(monkeypatch):
    monkeypatch.setenv("RAG_UNSUPPORTED_WITH_GOLD_SKIP_ENABLED", "true")
    skip, reason = _should_skip_retry(
        answer_text="some draft",
        used_candidates=[_cand(0.55)],
        query_class=QueryClass.LOOKUP,
        metadata=_meta(),
        first_verdict="unsupported",
    )
    # falls through to evaluator_low_score or no skip; must NOT return our new gate
    assert reason != "unsupported_with_gold_skip"


def test_multihop_unsupported_with_high_rerank_does_not_skip(monkeypatch):
    monkeypatch.setenv("RAG_UNSUPPORTED_WITH_GOLD_SKIP_ENABLED", "true")
    skip, reason = _should_skip_retry(
        answer_text="some draft",
        used_candidates=[_cand(0.85)],
        query_class=QueryClass.MULTI_HOP,
        metadata=_meta(),
        first_verdict="unsupported",
    )
    assert reason != "unsupported_with_gold_skip"


def test_gate_disabled_via_env(monkeypatch):
    monkeypatch.setenv("RAG_UNSUPPORTED_WITH_GOLD_SKIP_ENABLED", "false")
    skip, reason = _should_skip_retry(
        answer_text="some draft",
        used_candidates=[_cand(0.85)],
        query_class=QueryClass.LOOKUP,
        metadata=_meta(),
        first_verdict="unsupported",
    )
    assert reason != "unsupported_with_gold_skip"


def test_gold_retrieved_tag_constant_distinct_from_low_confidence():
    from website.features.rag_pipeline.orchestrator import _LOW_CONFIDENCE_DETAILS_TAG
    assert _GOLD_RETRIEVED_DETAILS_TAG != _LOW_CONFIDENCE_DETAILS_TAG
    assert "reflects" in _GOLD_RETRIEVED_DETAILS_TAG.lower()
```

- [ ] **Step 2: Run tests to verify failure.**

```bash
pytest tests/unit/rag/test_orchestrator_retry_policy.py -v
```

- [ ] **Step 3: Implement.**

In `website/features/rag_pipeline/orchestrator.py`, add near the existing `_LOW_CONFIDENCE_DETAILS_TAG`:

```python
# iter-09 RES-1: distinct tag for gold-retrieved + critic-unsupported skip path.
# The answer is grounded in retrieved sources; the critic flagged it for
# missing literal phrasing rather than missing evidence. Phrasing is
# non-defensive per Anthropic citations guidance.
_GOLD_RETRIEVED_DETAILS_TAG = (
    "\n\n<details>"
    "<summary>How sure am I?</summary>"
    "Answer reflects retrieved sources; some details may be paraphrased rather than quoted verbatim."
    "</details>"
)


_UNSUPPORTED_WITH_GOLD_SKIP_ENABLED = os.environ.get(
    "RAG_UNSUPPORTED_WITH_GOLD_SKIP_ENABLED", "true"
).lower() not in ("false", "0", "no", "off")
_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR = float(
    os.environ.get("RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR", "0.7")
)
```

In `_should_skip_retry`, AFTER the existing `partial_with_gold_skip` block (around L189) and BEFORE the refusal-regex check (L190):

```python
# iter-09 RES-1: parallel skip gate for unsupported-with-gold (LOOKUP only).
# Critic flagged unsupported but retrieval surfaced a gold-tier chunk; the
# first-pass draft is materially better than burning 12s on retry. Tag with
# the new "answer reflects retrieved sources" details rather than the
# negative-valence low-confidence tag.
if (
    _UNSUPPORTED_WITH_GOLD_SKIP_ENABLED
    and first_verdict == "unsupported"
    and query_class is QueryClass.LOOKUP
    and used_candidates
    and top_score >= _UNSUPPORTED_WITH_GOLD_SKIP_FLOOR
):
    return True, "unsupported_with_gold_skip"
```

In the orchestrator `unsupported` branch (around L840–862), add a sibling clause to the existing `partial_with_gold_skip` handler:

```python
elif skip_reason == "unsupported_with_gold_skip":
    verdict = "unsupported_with_gold_skip"
    answer_text = answer_text + _GOLD_RETRIEVED_DETAILS_TAG
    replaced_text = answer_text
```

- [ ] **Step 4: Run tests to verify pass.**

```bash
pytest tests/unit/rag/test_orchestrator_retry_policy.py -v
```

- [ ] **Step 5: Confirm verdict allowlist match.** Verify Task 7 migration includes `'unsupported_with_gold_skip'`. If not, fix Task 7 first.

- [ ] **Step 6: Commit.**

```bash
git add website/features/rag_pipeline/orchestrator.py tests/unit/rag/test_orchestrator_retry_policy.py
git commit -m "feat: unsupported with gold skip retry gate"
```

### Task 11: Class-conditional chunk-share + ratio-to-median magnet detection

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/chunk_share.py` (add `should_apply_chunk_share`)
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py:423–432` (gate insertion)
- Test: `tests/unit/rag/retrieval/test_chunk_share.py` (extend)

- [ ] **Step 1: Write failing tests.**

```python
# tests/unit/rag/retrieval/test_chunk_share.py — append
from website.features.rag_pipeline.retrieval.chunk_share import should_apply_chunk_share
from website.features.rag_pipeline.query.types import QueryClass


KM_COUNTS = {"yt-effective-public-speakin": 16, "yt-steve-jobs-2005-stanford": 13,
             "nl-the-pragmatic-engineer-t": 10, "yt-programming-workflow-is": 6,
             "web-transformative-tools-for": 6, "yt-matt-walker-sleep-depriv": 3,
             "gh-zk-org-zk": 2}


def test_lookup_class_skips_damp(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_SHARE_CLASS_GATE_ENABLED", "true")
    apply, reason = should_apply_chunk_share(QueryClass.LOOKUP, KM_COUNTS)
    assert apply is False


def test_thematic_with_outlier_applies_damp(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_SHARE_CLASS_GATE_ENABLED", "true")
    monkeypatch.setenv("RAG_CHUNK_SHARE_MAGNET_RATIO", "2.0")
    apply, reason = should_apply_chunk_share(QueryClass.THEMATIC, KM_COUNTS)
    assert apply is True


def test_thematic_uniform_distribution_no_damp(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_SHARE_CLASS_GATE_ENABLED", "true")
    monkeypatch.setenv("RAG_CHUNK_SHARE_MAGNET_RATIO", "2.0")
    uniform = {f"n{i}": 5 for i in range(7)}
    apply, reason = should_apply_chunk_share(QueryClass.THEMATIC, uniform)
    assert apply is False


def test_cold_start_kasten_skips_damp(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_SHARE_CLASS_GATE_ENABLED", "true")
    apply, reason = should_apply_chunk_share(QueryClass.THEMATIC, {"a": 16, "b": 1})
    # only 2 nodes < 5 cold-start floor
    assert apply is False


def test_multi_hop_with_outlier_applies_damp(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_SHARE_CLASS_GATE_ENABLED", "true")
    apply, reason = should_apply_chunk_share(QueryClass.MULTI_HOP, KM_COUNTS)
    assert apply is True


def test_vague_class_skips_damp_even_with_outlier(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_SHARE_CLASS_GATE_ENABLED", "true")
    apply, reason = should_apply_chunk_share(QueryClass.VAGUE, KM_COUNTS)
    assert apply is False


def test_class_gate_disabled_falls_back_to_iter08_behaviour(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_SHARE_CLASS_GATE_ENABLED", "false")
    apply, reason = should_apply_chunk_share(QueryClass.LOOKUP, KM_COUNTS)
    assert apply is True  # iter-08 always-on behaviour
```

- [ ] **Step 2: Run failing tests.**

```bash
pytest tests/unit/rag/retrieval/test_chunk_share.py -v
```

- [ ] **Step 3: Implement `should_apply_chunk_share`.**

```python
# website/features/rag_pipeline/retrieval/chunk_share.py — append
import os
import statistics
from website.features.rag_pipeline.query.types import QueryClass


_GATED_CLASSES = {QueryClass.THEMATIC, QueryClass.MULTI_HOP}
_COLD_START_MIN = 5


def should_apply_chunk_share(
    query_class: QueryClass,
    chunk_counts: dict[str, int],
) -> tuple[bool, str]:
    """iter-09 RES-2: gate chunk-share normalization on class + per-query magnet detection.

    Returns ``(apply, reason)``. Reasons: ``class_gate_off`` (env disabled →
    legacy iter-08 behaviour), ``class_excluded``, ``cold_start``,
    ``no_magnet``, ``magnet_detected``.
    """
    enabled = os.environ.get("RAG_CHUNK_SHARE_CLASS_GATE_ENABLED", "true").lower() not in ("false", "0", "no", "off")
    if not enabled:
        return True, "class_gate_off"
    if query_class not in _GATED_CLASSES:
        return False, "class_excluded"
    if not chunk_counts or len(chunk_counts) < _COLD_START_MIN:
        return False, "cold_start"
    counts = list(chunk_counts.values())
    median = statistics.median(counts)
    if median <= 0:
        return False, "cold_start"
    ratio = max(counts) / median
    threshold = float(os.environ.get("RAG_CHUNK_SHARE_MAGNET_RATIO", "2.0"))
    if ratio < threshold:
        return False, "no_magnet"
    return True, "magnet_detected"
```

- [ ] **Step 4: Wire into `hybrid.py`.**

Replace lines 423–432 with:

```python
chunk_share_enabled_legacy = os.environ.get(
    "RAG_CHUNK_SHARE_NORMALIZATION_ENABLED", "true"
).lower() not in ("false", "0", "no", "off")
should_apply, gate_reason = should_apply_chunk_share(query_class, chunk_counts or {})
if (
    chunk_share_enabled_legacy
    and chunk_counts
    and not compare_intent
    and should_apply
):
    _apply_chunk_share_normalization(list(by_key.values()), chunk_counts)
elif compare_intent:
    _log.debug("chunk-share normalization disabled: compare-intent detected")
else:
    _log.debug("chunk-share normalization skipped: gate=%s", gate_reason)
```

Add the import: `from website.features.rag_pipeline.retrieval.chunk_share import should_apply_chunk_share`.

- [ ] **Step 5: Run tests to verify pass.**

```bash
pytest tests/unit/rag/retrieval/ tests/unit/rag/ -v
```

- [ ] **Step 6: Commit.**

```bash
git add website/features/rag_pipeline/retrieval/chunk_share.py website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_chunk_share.py
git commit -m "feat: class gated chunk share with magnet detection"
```

---

## Phase 4 — Adhoc admission wire (CLAUDE.md guarded; explicit chat approval already given)

### Task 12: Wrap `_run_answer` in `acquire_rerank_slot()`

**Files:**
- Modify: `website/api/chat_routes.py:156–182` (wrap `_run_answer` body) and `:509` (call site stays the same; wrapping is internal)
- Test: `tests/unit/api/test_chat_routes_admission.py` (new)

- [ ] **Step 1: Write failing test.**

```python
# tests/unit/api/test_chat_routes_admission.py
import asyncio
import pytest
from fastapi import HTTPException
from website.api._concurrency import QueueFull, get_concurrency_state


@pytest.mark.asyncio
async def test_run_answer_increments_state_depth(monkeypatch):
    """iter-09 RES-4: non-stream adhoc must increment state.depth via acquire_rerank_slot."""
    from website.api import chat_routes
    state = get_concurrency_state()
    state.depth = 0
    state.queue_max = 8
    observed = {}

    async def _fake_orchestrator_answer(*a, **k):
        observed["depth_during_answer"] = state.depth
        return {"turn": {"id": "t1"}}

    monkeypatch.setattr(chat_routes.runtime.orchestrator, "answer", _fake_orchestrator_answer)
    # ... invoke _run_answer with minimal stub args
    await chat_routes._run_answer(...)  # executor: fill in stub args
    assert observed["depth_during_answer"] >= 1
    assert state.depth == 0  # depth restored after exit


@pytest.mark.asyncio
async def test_run_answer_returns_503_on_queue_full(monkeypatch):
    """iter-09 RES-4: when QueueFull is raised inside the slot, propagate as HTTP 503 with Retry-After: 5."""
    from website.api import chat_routes
    state = get_concurrency_state()
    state.depth = state.queue_max  # already full
    with pytest.raises(HTTPException) as exc_info:
        await chat_routes._run_answer(...)  # executor: fill in stub args
    assert exc_info.value.status_code == 503
    assert exc_info.value.headers.get("Retry-After") == "5"
```

- [ ] **Step 2: Run tests to verify failure.**

- [ ] **Step 3: Implement the wrap inside `_run_answer`.**

```python
# website/api/chat_routes.py — modify _run_answer body
from website.api._concurrency import acquire_rerank_slot, QueueFull
from fastapi import HTTPException

async def _run_answer(...):
    try:
        async with acquire_rerank_slot():
            payload = await runtime.orchestrator.answer(...)
            await _post_answer_side_effects(...)  # existing
            return payload
    except QueueFull as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "queue_full", "message": "Rerank capacity full; retry shortly."},
            headers={"Retry-After": "5"},
        ) from exc
```

- [ ] **Step 4: Verify the existing peek-check at L489 still works.** With `_run_answer` now wrapping, the peek-check becomes a fast-fail before the heavy path; both fire 503. Keep both for defence in depth.

- [ ] **Step 5: Run all tests.**

```bash
pytest tests/unit/api/ -v
```

- [ ] **Step 6: Commit.**

```bash
git add website/api/chat_routes.py tests/unit/api/test_chat_routes_admission.py
git commit -m "fix: wrap run_answer in acquire_rerank_slot for adhoc 503"
```

---

## Phase 5 — Investigations (no code changes without further approval)

### Task 13: Auto-title side-effect timing measurement

**Files:** none (analysis only).

- [ ] **Step 1: After Phase 1 ships and Phase 2 deploys, run iter-09 eval with `EVAL_USE_SSE_HARNESS=true`.**

- [ ] **Step 2: Compute the gap `latency_ms_server - p_user_complete_ms` and `p_user_complete_ms - p_user_last_token_ms` per query.**

- [ ] **Step 3: Write findings to `docs/rag_eval/common/knowledge-management/iter-09/auto_title_timing.md`.** Decide whether to file an iter-10 task to move `_post_answer_side_effects` to a background task.

### Task 14: Q5 500 root-cause (HOLD until logs in hand)

**Files:** none until proven.

- [ ] **Step 1: After Task 1 logs are in hand, identify the exact traceback frame.**

- [ ] **Step 2: Stop and ask the user before proposing a fix.** CLAUDE.md prohibits speculative fixes on the q5 path.

---

## Phase 6 — DEFER to iter-10 (no code in iter-09)

Documented for posterity; do not start work without a fresh iter-10 spec.

- **Rerank-stage magnet penalty** (RES-3). Re-evaluate after iter-09 eval. Multi-gate version only: `(rerank_score within 0.05 of #2) AND (low_title_overlap with query) AND (chunk_count_share >= 15%)`. Hook point: `cascade.py:583`. Multiplicative damp `× 0.95`, never subtractive.
- **Q7 magnet damp exponent change + gazetteer boost** (original iter-09 item 3). Dropped from iter-09 per RES-3 conclusion.
- **`_post_answer_side_effects` background task** (Phase 5 Task 13 may motivate).
- **Admission middleware refactor** (RES-4 industry alternative). Replace per-route guards with a single ASGI middleware.

---

## Phase 7 — Deploy + final eval

### Task 15: Update `ops/.env.example`

**Files:** `ops/.env.example`

- [ ] **Step 1: Add the iter-09 env flags** with comments referencing RES-N sections.

- [ ] **Step 2: Commit.**

```bash
git add ops/.env.example
git commit -m "docs: iter-09 env flags"
```

### Task 16: Run full pytest suite + push

**Files:** none.

- [ ] **Step 1: Run all tests.**

```bash
pytest -q
```

Expected: 542+ passed (existing pre-iter-09 baseline + new iter-09 tests).

- [ ] **Step 2: Push including the local `ee31c85` NDCG hotfix.**

```bash
git push origin master
```

### Task 17: Re-run eval and write `scores.md`

**Files:** `docs/rag_eval/common/knowledge-management/iter-09/scores.md` (new), `verification_results.json` (new).

- [ ] **Step 1: After deploy completes, run eval.**

```powershell
python ops\scripts\eval_iter_03_playwright.py --iter iter-09
python ops\scripts\score_rag_eval.py --iter iter-09
```

- [ ] **Step 2: Write `scores.md`** matching iter-08's structure. Include `p_user_*_ms` per query. Annotate which iter-08 failures recovered.

- [ ] **Step 3: Commit.**

```bash
git add docs/rag_eval/common/knowledge-management/iter-09/
git commit -m "docs: iter-09 scores and verification results"
git push origin master
```

---

## Self-review checklist (executor: run before claiming done)

- [ ] Every iter-09 brief item from the original user prompt is either implemented or explicitly DEFER'd in this plan with a reason.
- [ ] No `TBD`, `TODO`, or "fill in later" placeholders in any task body.
- [ ] Type/method names consistent across tasks (e.g., `should_apply_chunk_share` referenced identically in test + impl + import).
- [ ] Postgres CHECK migration (Task 7) includes ALL new verdict strings used in code (Task 10's `unsupported_with_gold_skip`).
- [ ] `ROUTER_VERSION` bumped from `"v2"` (or current value) to `"v3"` in Task 9.
- [ ] No protected CLAUDE.md knob touched outside Phase 4 (which has explicit user approval).
- [ ] Phase 5 tasks remain investigation-only.
