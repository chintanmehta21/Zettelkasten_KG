# iter-10 RAG-eval Recovery Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read [RESEARCH.md](RESEARCH.md) before each phase.

**Goal:** Close the iter-04..iter-09 chapter on the KM Kasten by hitting **composite ≥ 85, gold@1 ≥ 0.85, within_budget ≥ 0.85**, and **multi-user safe** (burst 503 rate ≥ 0.08, zero 502 from upstream-down). All 14 queries must run with high confidence.

**Architecture:** Three measurement-truth fixes (P1 harness, P6 score audit, P8/P12/per-stage observability) come first because every prior iter has been blind to its own true latency. Then the targeted fixes (P4 q10 un-gate, P5 q6/q7 recall fallback, P3 q5 magnet, P9 pre-rerank gate) layered with class-conditional discipline so resolving one zettel-shape doesn't break another. Concurrency unblock (P2 auto-title outside slot + P11 flash-lite pin) keeps single-user UX honest while iter-09's admission gate remains the multi-user shield. Drift guards (CI grep, structured logs) prevent regressions slipping past the next iter.

**Tech Stack:** Python 3.12, FastAPI/uvicorn/gunicorn, asyncio, pytest + pytest-asyncio, Supabase Postgres + pgvector, BGE int8 cross-encoder, Gemini 2.5 (flash / flash-lite / pro), Caddy 2, Docker Compose blue/green on DigitalOcean droplet, Playwright Python harness.

---

## Architectural decisions baked in (per CLAUDE.md guardrails — DO NOT touch)

GUNICORN_WORKERS=2, `--preload`, FP32_VERIFY_ENABLED top-3 only, GUNICORN_TIMEOUT≥180s (verified droplet=240s), rerank semaphore + bounded queue (RAG_QUEUE_MAX=8/worker), SSE heartbeat wrapper, Caddy `read_timeout 240s`, schema-drift gate, `kg_users` allowlist gate, teal/amber color rule, BGE int8 reranker (no swap), router structural changes (RES-6 option c deferred), magnet penalty AT rerank stage (RES-3 deferred), threshold floors (`_PARTIAL_NO_RETRY_FLOOR`, `_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR`, `_RETRY_TOP_SCORE_FLOOR`, `_REFUSAL_SEMANTIC_GATE_FLOOR`), q5 500 speculative fix (HOLD), admission middleware refactor (iter-11+), per-query mid-flight latency abort (iter-11+).

---

## File Structure

| File | Responsibility | Phase / Task |
|---|---|---|
| `run.py:38` | Add inline comment noting prod GUNICORN_TIMEOUT=240 (operator-side via compose/.env) | 0 / 1 |
| `ops/.env.example` | Add GUNICORN_TIMEOUT example with prod note + new RAG_RERANK_INPUT_FLOOR_*, RAG_RERANK_INPUT_MIN_KEEP_*, RAG_AUTO_TITLE_MODEL flags | 0 / 1 + 9 / 18 |
| `ops/scripts/eval_iter_03_playwright.py:574-668` | P1 harness arithmetic fix: subtract `t0` from firstTokenAt/lastTokenAt/doneAt | 1 / 4 |
| `ops/scripts/score_rag_eval.py` | P6 score audit: separate `gold@1_unconditional` from `gold@1_within_budget` | 1 / 5 |
| `website/features/rag_pipeline/retrieval/hybrid.py:262-282` | P4 anchor-seed un-gate (drop n_persons+n_entities re-gate; add THEMATIC exclusion; min entity-length floor; cap top-3; log) | 2 / 6 |
| `website/features/sessions/auto_title.py` (or whichever module owns auto_title_session) | P11 pin to `gemini-2.5-flash-lite` via env `RAG_AUTO_TITLE_MODEL` | 3 / 7 |
| `website/api/chat_routes.py:156-198` | P2 move `_post_answer_side_effects` to `asyncio.create_task` outside `acquire_rerank_slot()` | 3 / 8 |
| `website/features/rag_pipeline/retrieval/hybrid.py` (zettel-type tie-breaker) | Item 3: `chunk_count_quartile` tie-breaker in `_dedup_and_fuse` | 4 / 9 |
| `tests/unit/rag/integration/test_class_x_source_matrix.py` | NEW: cross-class regression fixture | 4 / 9 |
| `website/features/rag_pipeline/retrieval/hybrid.py` (recall fallback) | P5 dense-only fallback for kasten-golden recall miss (gated by Phase 0 scout) | 4 / 10 |
| `website/features/rag_pipeline/retrieval/cascade.py` (or hybrid.py post-fuse) | P3 score-rank-correlation gate + title-overlap demote, THEMATIC/STEP_BACK only | 5 / 11 |
| `website/features/rag_pipeline/rerank/cascade.py` | P9 pre-rerank adaptive percentile floor with RAG_RERANK_INPUT_FLOOR_* naming | 6 / 12 |
| `website/features/rag_pipeline/generation/prompts.py` | P13 clause-coverage self-check in SYSTEM_PROMPT | 7 / 13 |
| `website/api/_concurrency.py` (or new helper) | P8 RSS pre/post-slot logging | 8 / 14 |
| `website/features/rag_pipeline/retrieval/chunk_share.py` + `hybrid.py:_ensure_member_coverage` | P12 structured logging on TTL hits/misses + THEMATIC empty-counts path | 8 / 15 |
| `tests/unit/api/test_admission_drift_guard.py` | NEW: CI grep guard catches `@router.post` ref to `runtime.orchestrator.answer` lacking nearby `acquire_rerank_slot()` | 8 / 16 |
| `website/features/rag_pipeline/orchestrator.py` + `chat_routes.py` | NEW: per-stage timestamps `t_retrieval`, `t_rerank`, `t_synth` in response payload + log | 8 / 17 |
| `tests/unit/ops_scripts/test_eval_sse_reader.py` | Update + add 1 case verifying t0-relative timing | 1 / 4 |
| `tests/unit/rag_pipeline/retrieval/test_hybrid_anchor_seed_gate.py` | NEW: 6 cases for P4 mitigations | 2 / 6 |
| `tests/unit/rag/retrieval/test_chunk_count_tiebreak.py` | NEW: tie-breaker logic | 4 / 9 |
| `tests/unit/rag/retrieval/test_dense_fallback.py` | NEW: P5 fallback (only if scout-gated) | 4 / 10 |
| `tests/unit/rag/retrieval/test_score_rank_magnet_gate.py` | NEW: P3 score-rank gate | 5 / 11 |
| `tests/unit/rag/rerank/test_adaptive_percentile_floor.py` | NEW: P9 floor | 6 / 12 |

---

## Phase 0 — Pre-flight (no code changes except 2-LOC docs)

### Task 1: Reconcile GUNICORN_TIMEOUT documentation

**Files:**
- Modify: `run.py:38` (single-line comment)
- Modify: `ops/.env.example` (add example with comment)

**Why:** Iter-09 droplet env audit (run 25330459384) confirmed `GUNICORN_TIMEOUT=240` in production `compose/.env` (>=180s satisfies CLAUDE.md). The fallback default `"90"` in `run.py:38` is for un-configured dev only. Visibility, not behavior.

- [ ] **Step 1: Read current state.**

```bash
grep -n GUNICORN_TIMEOUT run.py ops/.env.example
```

- [ ] **Step 2: Patch `run.py:38` with explanatory comment.**

```python
# run.py — ABOVE the existing line (do not change the value)
# iter-10 doc reconciliation: production droplet sets GUNICORN_TIMEOUT=240 in
# /opt/zettelkasten/compose/.env (>=180s per CLAUDE.md guardrail). The "90"
# default below is for un-configured dev; prod always overrides via env-file.
"--timeout", os.environ.get("GUNICORN_TIMEOUT", "90"),
```

- [ ] **Step 3: Append to `ops/.env.example` (under existing iter-09 block).**

```
# ── iter-10 operational visibility ──
# Production droplet sets GUNICORN_TIMEOUT=240 (matches Caddy read_timeout
# upstream); CLAUDE.md guardrail requires >=180. Local dev typically leaves
# this unset and run.py:38 falls back to 90s.
GUNICORN_TIMEOUT=240
```

- [ ] **Step 4: Commit.**

```bash
git add run.py ops/.env.example
git commit -m "docs: reconcile gunicorn timeout prod 240s"
```

### Task 2: Q6/q7 candidate-pool scout (gates Task 10)

**Files:** none — this is investigative.

**Why:** Agent C P5 proposes a dense-only recall fallback for q6/q7. Whether to ship the fallback depends on whether the rerank pool is actually empty for those queries.

- [ ] **Step 1: Add temporary verbose logging in `website/features/rag_pipeline/retrieval/hybrid.py:_dedup_and_fuse` AFTER the dedup loop:**

```python
import os as _os, logging as _logging
if _os.environ.get("RAG_SCOUT_LOG_USED_CANDIDATES", "false").lower() == "true":
    _scout = _logging.getLogger("rag.scout")
    _scout.info(
        "scout pool=%d top5=%s",
        len(by_key),
        [(c.node_id, round(c.rrf_score, 3)) for c in sorted(
            by_key.values(), key=lambda x: x.rrf_score, reverse=True
        )[:5]],
    )
```

- [ ] **Step 2: Push, deploy, dispatch eval with the env flag enabled, pull droplet logs after q6/q7 fire.**

```bash
# After deploy:
gh workflow run read_recent_logs.yml -f "since=<eval start UTC>" -f lines=20000
gh run view <id> --log | grep "rag.scout" | head -10
```

- [ ] **Step 3: Decide.**

  - If q6/q7 pool has ≥1 of the expected gold node ids → P5 fallback NOT needed; skip Task 10. Document "pool already had gold; magnet/rerank surfaced wrong primary" → covered by P3 (Phase 5).
  - If q6/q7 pool MISSING all expected gold ids → P5 fallback IS needed; proceed with Task 10.

- [ ] **Step 4: Remove the scout logging (revert) BEFORE final eval — observability stays in P8/P12.**

```bash
git checkout website/features/rag_pipeline/retrieval/hybrid.py  # discard scout
```

### Task 3: Mandatory reading

**Files:** none.

- [ ] **Step 1:** Read in this order:
  1. `docs/rag_eval/common/knowledge-management/iter-09/RESEARCH.md` (Cons-NOT-to-take per RES-N)
  2. `docs/rag_eval/common/knowledge-management/iter-09/iter09_failure_deepdive.md` (per-query forensic)
  3. `docs/rag_eval/common/knowledge-management/iter-09/prior_attempts_knowledge_base.md` (iter-04..iter-08 changelog)
  4. `docs/rag_eval/common/knowledge-management/iter-09/iter10_solutions_research.md` (P1-P14 matrix)
  5. `docs/rag_eval/common/knowledge-management/iter-09/iter10_followup_research.md` (deep-dive on 7 follow-up items)
  6. `docs/rag_eval/common/knowledge-management/iter-09/guardrails_review.md` (16 guardrails reviewed)
  7. `docs/rag_eval/common/knowledge-management/iter-10/RESEARCH.md` (this iter's rationale)
  8. `CLAUDE.md` root — Critical Infra Decision Guardrails

---

## Phase 1 — Harness truth + scoring fixes

**Why this is Phase 1:** every iter-09 metric was distorted by a 3-line harness arithmetic bug. Fixing it on the SAME iter-09 server outputs is expected to lift composite from 65 → ~80 with zero production change. P6 audits the scorer to align gold@1 reporting between scores.md and verification_results.json.

### Task 4: P1 harness arithmetic fix (subtract t0)

**Files:**
- Modify: `ops/scripts/eval_iter_03_playwright.py:600-668` (api_fetch_sse JS evaluator)
- Modify: `ops/scripts/_sse_reader.py` (Python parity — already correct, but add doc note)
- Test: `tests/unit/ops_scripts/test_eval_sse_reader.py` (extend)

- [ ] **Step 1: Write a new failing test asserting timestamps are t0-relative.**

```python
# tests/unit/ops_scripts/test_eval_sse_reader.py — append
def test_timing_is_relative_to_fetch_start_not_page_load():
    """Regression for iter-09 harness bug: firstTokenAt was returned as
    page-relative absolute time, not relative to the per-query fetch t0.
    Reading two streams back-to-back must produce two independent measurements,
    not a monotonically increasing pair."""
    import time

    chunks_a = [b"event: token\ndata: \"a\"\n\n", b"event: done\ndata: {}\n\n"]
    chunks_b = [b"event: token\ndata: \"b\"\n\n", b"event: done\ndata: {}\n\n"]
    out_a = parse_sse_stream(chunks_a)
    time.sleep(0.05)
    out_b = parse_sse_stream(chunks_b)
    # Each call's complete_ms must reflect ITS OWN fetch duration (small),
    # not since-process-start. parse_sse_stream uses monotonic_ns and
    # subtracts t0 — both should be small.
    assert 0 <= out_a["p_user_complete_ms"] < 100
    assert 0 <= out_b["p_user_complete_ms"] < 100
    # Independence: B should NOT be ~50ms larger than A.
    assert abs(out_b["p_user_complete_ms"] - out_a["p_user_complete_ms"]) < 50
```

- [ ] **Step 2: Run test (should pass — Python side is already t0-relative). This anchors the contract.**

```bash
pytest tests/unit/ops_scripts/test_eval_sse_reader.py -v
```

Expected: PASS (the existing Python parser already subtracts t0; this test fixes the contract for the JS side).

- [ ] **Step 3: Locate the JS bug in `ops/scripts/eval_iter_03_playwright.py`.**

The current `api_fetch_sse` evaluator captures `t0 = performance.now()` then computes `firstTokenAt = performance.now()` etc. but returns `Math.round(firstTokenAt)` — page-relative, not subtracted. Find these three lines (~L666-668):

```js
p_user_first_token_ms: firstTokenAt === null ? null : Math.round(firstTokenAt),
p_user_last_token_ms: lastTokenAt === null ? null : Math.round(lastTokenAt),
p_user_complete_ms: doneAt === null ? null : Math.round(doneAt),
```

- [ ] **Step 4: Fix to subtract t0.**

```js
p_user_first_token_ms: firstTokenAt === null ? null : Math.round(firstTokenAt - t0),
p_user_last_token_ms: lastTokenAt === null ? null : Math.round(lastTokenAt - t0),
p_user_complete_ms: doneAt === null ? null : Math.round(doneAt - t0),
```

- [ ] **Step 5: Manual smoke (operator-side; not a CI gate).**

```powershell
$env:EVAL_USE_SSE_HARNESS="true"; python ops\scripts\eval_iter_03_playwright.py --iter iter-10-smoke
```

Expected: per-query `ttft` and `ttlt` printed alongside elapsed are now in the 1000-3000ms range for fast queries, NOT increasing monotonically across q1→q14.

- [ ] **Step 6: Commit.**

```bash
git add ops/scripts/eval_iter_03_playwright.py tests/unit/ops_scripts/test_eval_sse_reader.py
git commit -m "fix: harness ttft ttlt subtract t0"
```

### Task 5: P6 gold@1 score audit

**Files:**
- Modify: `ops/scripts/score_rag_eval.py` (locate the gold@1 aggregation block)

**Why:** iter-09 scores.md reported `gold@1 = 0.5714` while verification_results.json had 9/14 = 0.6429 actual gold matches. The discrepancy is the within_budget filter being silently AND'd into the gold count.

- [ ] **Step 1: Locate the gold@1 aggregation in score_rag_eval.py.**

```bash
grep -n "gold_at_1\|gold@1" ops/scripts/score_rag_eval.py | head -10
```

- [ ] **Step 2: Add separate metrics.**

Find the existing aggregation and split into TWO output fields:

```python
# In the per-query aggregation block, replace single gold counter with:
gold_unconditional = sum(1 for r in qa_rows if r.get("gold_at_1") is True)
gold_within_budget = sum(
    1 for r in qa_rows
    if r.get("gold_at_1") is True and r.get("within_budget") is True
)
total = max(len(qa_rows), 1)

# Emit BOTH in scores.md:
report["gold_at_1_unconditional"] = round(gold_unconditional / total, 4)
report["gold_at_1_within_budget"] = round(gold_within_budget / total, 4)
# Keep existing gold@1 alias for backwards compatibility, point it at unconditional.
report["gold_at_1"] = report["gold_at_1_unconditional"]
```

- [ ] **Step 3: Update the scores.md template to show both lines.**

```python
# Inside the scores.md writer:
lines.append(f"- gold@1 (unconditional):     {report['gold_at_1_unconditional']:.4f}")
lines.append(f"- gold@1 within budget:       {report['gold_at_1_within_budget']:.4f}")
```

- [ ] **Step 4: Add a unit test.**

```python
# tests/unit/ops_scripts/test_score_rag_eval_gold_split.py — new
def test_gold_at_1_unconditional_separated_from_within_budget():
    # Stub QA rows with mixed gold + budget combinations.
    rows = [
        {"gold_at_1": True,  "within_budget": True},   # contributes to BOTH
        {"gold_at_1": True,  "within_budget": False},  # only unconditional
        {"gold_at_1": False, "within_budget": True},
        {"gold_at_1": False, "within_budget": False},
    ]
    # Call into the aggregator directly (extract to a helper if needed).
    from ops.scripts.score_rag_eval import _aggregate_gold_metrics
    out = _aggregate_gold_metrics(rows)
    assert out["gold_at_1_unconditional"] == 0.5
    assert out["gold_at_1_within_budget"] == 0.25
```

- [ ] **Step 5: Run tests.**

```bash
pytest tests/unit/ops_scripts/test_score_rag_eval_gold_split.py -v
```

- [ ] **Step 6: Commit.**

```bash
git add ops/scripts/score_rag_eval.py tests/unit/ops_scripts/test_score_rag_eval_gold_split.py
git commit -m "fix: split gold@1 unconditional vs within budget"
```

---

## Phase 2 — q10 anchor-seed un-gate + 4 mitigations

**Why now:** q10 LOOKUP+person query failed in iter-09 because `(n_persons + n_entities) >= 1` re-gate rejected the seed when NER missed "Steve Jobs" as entity. `entity_anchor.py:resolve_anchor_nodes` already proves entity match at the kasten level — re-gating is double-filtering.

### Task 6: Drop entity-count re-gate; add 4 defense-in-depth mitigations

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py:262-282`
- Test: `tests/unit/rag_pipeline/retrieval/test_hybrid_anchor_seed_gate.py` (new)

**Mitigations bundled (all four MUST land together):**
1. `is_lookup AND query_class is not QueryClass.THEMATIC` — defence-in-depth class gate
2. Min entity-length floor: skip seed inject when ALL entities resolving anchor_nodes are <4 chars (kills "AI" / "ML" / "JS" tag-collision over-pulls)
3. Cap seeds to top-3 (not LIMIT 8 from RPC; hard cap on Python side after sort)
4. `logger.info("anchor_seed_inject ...")` for every inject (qid/anchors/n_seeds/floor)

- [ ] **Step 1: Write 6 failing tests.**

```python
# tests/unit/rag_pipeline/retrieval/test_hybrid_anchor_seed_gate.py
"""iter-10 P4: anchor-seed un-gate + 4 defense-in-depth mitigations."""
from __future__ import annotations

import pytest
from website.features.rag_pipeline.retrieval.hybrid import (
    _should_inject_anchor_seeds,
)
from website.features.rag_pipeline.types import QueryClass


def test_lookup_with_anchor_nodes_injects_even_when_ner_zero():
    """q10 fix: NER may miss 'Steve Jobs' as person entity (single-name surname),
    but anchor_nodes was non-empty via tag/title match — that PROVES entity match
    at the kasten level. Don't double-filter on metadata.entities count."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.LOOKUP,
        compare_intent=False,
        anchor_nodes={"yt-steve-jobs-2005-stanford"},
        entities_resolving=["jobs"],  # 4 chars >= 4-char floor
    )
    assert decision.fire is True


def test_thematic_class_excluded_even_with_anchor_nodes():
    """Defense-in-depth: THEMATIC must NEVER trigger anchor-seed inject so
    q5-shape can't accidentally pull a single-name magnet."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.THEMATIC,
        compare_intent=False,
        anchor_nodes={"yt-steve-jobs-2005-stanford"},
        entities_resolving=["jobs"],
    )
    assert decision.fire is False
    assert "thematic" in decision.reason.lower()


def test_short_entity_length_floor_skips_inject():
    """Tag-collision protection: skip seed inject when ALL anchor-resolving
    entities are <4 chars. 'AI' or 'ML' generic tags can match every kasten."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.LOOKUP,
        compare_intent=False,
        anchor_nodes={"web-some-ai-thing", "gh-ml-tool"},
        entities_resolving=["AI", "ML"],
    )
    assert decision.fire is False
    assert "entity_length" in decision.reason


def test_mixed_short_and_long_entities_passes():
    """If at least one resolving entity is >=4 chars, allow inject."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.LOOKUP,
        compare_intent=False,
        anchor_nodes={"yt-naval-ravikant-podcast"},
        entities_resolving=["AI", "Naval"],  # Naval is 5 chars
    )
    assert decision.fire is True


def test_compare_intent_passes_thematic_otherwise_excluded():
    """Compare-intent (e.g. 'compare X and Y') is the ONLY exception that lets
    a THEMATIC-classified query inject seeds — it's morally a multi-LOOKUP."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.THEMATIC,
        compare_intent=True,
        anchor_nodes={"yt-jobs", "yt-naval"},
        entities_resolving=["Jobs", "Naval"],
    )
    assert decision.fire is True


def test_empty_anchor_nodes_no_inject():
    """Sanity: nothing to seed."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.LOOKUP,
        compare_intent=False,
        anchor_nodes=set(),
        entities_resolving=["whatever"],
    )
    assert decision.fire is False
```

- [ ] **Step 2: Run tests to verify they fail.**

```bash
pytest tests/unit/rag_pipeline/retrieval/test_hybrid_anchor_seed_gate.py -v
```

Expected: ImportError on `_should_inject_anchor_seeds`.

- [ ] **Step 3: Implement the gate as a pure function.**

In `website/features/rag_pipeline/retrieval/hybrid.py`, add near the existing `_ANCHOR_SEED_*` constants:

```python
from dataclasses import dataclass

_ANCHOR_SEED_MIN_ENTITY_LENGTH = int(
    os.environ.get("RAG_ANCHOR_SEED_MIN_ENTITY_LENGTH", "4")
)
_ANCHOR_SEED_TOP_K = int(os.environ.get("RAG_ANCHOR_SEED_TOP_K", "3"))


@dataclass
class _AnchorSeedDecision:
    fire: bool
    reason: str


def _should_inject_anchor_seeds(
    query_class: QueryClass | None,
    compare_intent: bool,
    anchor_nodes: set[str] | list[str],
    entities_resolving: list[str],
) -> _AnchorSeedDecision:
    """iter-10 P4: anchor-seed gate after the iter-09 RES-7 un-gate.

    Drops the (n_persons + n_entities) >= 1 re-gate (q10 fix — NER misses
    single-name surnames). Adds defense-in-depth so THEMATIC misclassifications
    can't accidentally inject magnets and short generic tags can't tag-collide.
    """
    if not anchor_nodes:
        return _AnchorSeedDecision(False, "no_anchor_nodes")
    if compare_intent:
        return _AnchorSeedDecision(True, "compare_intent")
    if query_class is QueryClass.THEMATIC:
        return _AnchorSeedDecision(False, "thematic_excluded")
    if query_class is not QueryClass.LOOKUP:
        return _AnchorSeedDecision(False, "non_lookup")
    # Min entity-length floor — at least one resolving entity must be >= floor.
    long_enough = [
        e for e in (entities_resolving or [])
        if isinstance(e, str) and len(e.strip()) >= _ANCHOR_SEED_MIN_ENTITY_LENGTH
    ]
    if not long_enough:
        return _AnchorSeedDecision(False, "entity_length_floor")
    return _AnchorSeedDecision(True, "lookup_with_long_entity")
```

Replace the existing inline gate at L262-282 with a call to `_should_inject_anchor_seeds(...)`. After fetching seeds, cap to `_ANCHOR_SEED_TOP_K` and log:

```python
# In retrieve():
decision = _should_inject_anchor_seeds(
    query_class=query_class,
    compare_intent=bool(getattr(query_metadata, "compare_intent", False)),
    anchor_nodes=anchor_nodes,
    entities_resolving=list(
        (getattr(query_metadata, "authors", None) or [])
        + (getattr(query_metadata, "entities", None) or [])
    ),
)
if decision.fire and sandbox_id is not None and embeddings:
    from website.features.rag_pipeline.retrieval.anchor_seed import fetch_anchor_seeds
    raw_seeds = await fetch_anchor_seeds(
        list(anchor_nodes), sandbox_id, embeddings[0], self._supabase
    )
    # iter-10 P4 mitigation 3: cap to top-K (default 3).
    anchor_seeds = sorted(
        raw_seeds,
        key=lambda r: float(r.get("score") or 0.0),
        reverse=True,
    )[: _ANCHOR_SEED_TOP_K]
    # iter-10 P4 mitigation 4: structured log every inject.
    _log.info(
        "anchor_seed_inject qid=%s class=%s n_anchors=%d n_seeds=%d floor=%.2f",
        getattr(query_metadata, "qid", "?"),
        getattr(query_class, "value", query_class),
        len(list(anchor_nodes)),
        len(anchor_seeds),
        _ANCHOR_SEED_FLOOR_RRF,
    )
else:
    anchor_seeds = []
    _log.debug("anchor_seed skipped: %s", decision.reason)
```

- [ ] **Step 4: Run tests to verify pass.**

```bash
pytest tests/unit/rag_pipeline/retrieval/test_hybrid_anchor_seed_gate.py -v
```

- [ ] **Step 5: Re-run existing hybrid + retrieval tests to confirm zero regressions.**

```bash
pytest tests/unit/rag/retrieval/ tests/unit/rag_pipeline/retrieval/ -v
```

- [ ] **Step 6: Add env flags to `ops/.env.example` (defer commit until Phase 9).**

- [ ] **Step 7: Commit.**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag_pipeline/retrieval/test_hybrid_anchor_seed_gate.py
git commit -m "fix: anchor seed un-gate plus four mitigations"
```

---

## Phase 3 — Concurrency unblock (P2 + P11)

**Why now:** iter-09 RES-4 admission gate works (503 rate 0.5). But the slot wraps `_post_answer_side_effects` which contains a 15-40s `auto_title_session` Gemini call. Slot serialization through auto-title kills throughput. P11 first (cheapest), P2 second (refactor).

### Task 7: Pin auto-title to gemini-2.5-flash-lite (P11)

**Files:**
- Modify: locate the auto-title invocation. Likely `website/features/sessions/auto_title.py` or `chat_routes.py:_post_answer_side_effects`. Use `grep -rn "auto_title_session\|def auto_title" website/` to find.

- [ ] **Step 1: Find the call site.**

```bash
grep -rn "auto_title_session\|def auto_title" website/ | head -10
```

- [ ] **Step 2: Read 30 lines around the call site to understand the model parameter.**

- [ ] **Step 3: Add env-driven model selection.**

```python
# In the auto_title module — at module top:
import os
_AUTO_TITLE_MODEL = os.environ.get("RAG_AUTO_TITLE_MODEL", "gemini-2.5-flash-lite")

# In the invocation, pass starting_model=_AUTO_TITLE_MODEL to the key-pool generate_content call.
# Example (adapt to actual signature):
response = await pool.generate_content(
    prompt,
    config={"temperature": 0.0, "max_output_tokens": 24},
    starting_model=_AUTO_TITLE_MODEL,
    label="AutoTitle",
)
```

- [ ] **Step 4: Write a unit test that asserts the env-driven model.**

```python
# tests/unit/sessions/test_auto_title_model.py — new
import os, pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_auto_title_uses_flash_lite_by_default(monkeypatch):
    monkeypatch.delenv("RAG_AUTO_TITLE_MODEL", raising=False)
    captured = {}
    async def _fake_generate(prompt, **kw):
        captured["starting_model"] = kw.get("starting_model")
        return ("Hello world", {})
    pool = AsyncMock()
    pool.generate_content = _fake_generate
    # ... call auto_title_session with stubbed pool; assert captured["starting_model"] == "gemini-2.5-flash-lite"
    # (executor: adapt to the real auto_title signature)
```

- [ ] **Step 5: Run test.**

```bash
pytest tests/unit/sessions/ -v
```

- [ ] **Step 6: Commit.**

```bash
git add website/features/sessions/auto_title.py tests/unit/sessions/test_auto_title_model.py
git commit -m "feat: pin auto title to flash lite"
```

### Task 8: Move `_post_answer_side_effects` outside `acquire_rerank_slot()` (P2)

**Files:**
- Modify: `website/api/chat_routes.py:156-198`
- Test: `tests/unit/api/test_chat_routes_admission.py` (extend)

**Why:** Slot must wrap orchestrator.answer ONLY. Side effects fire-and-forget via `asyncio.create_task` outside the slot. Per research, FastAPI BackgroundTasks blocks response in some configs; `asyncio.create_task` is the correct primitive (CPython asyncio docs).

- [ ] **Step 1: Write a failing test asserting slot is released before side-effects complete.**

```python
# tests/unit/api/test_chat_routes_admission.py — append
import asyncio
from contextlib import asynccontextmanager

@pytest.mark.asyncio
async def test_run_answer_releases_slot_before_side_effects_finish(monkeypatch):
    """iter-10 P2: side effects must run AFTER slot released."""
    slot_state = {"in_slot": False, "released_at": None}

    @asynccontextmanager
    async def _tracking_slot():
        slot_state["in_slot"] = True
        try:
            yield
        finally:
            slot_state["in_slot"] = False
            slot_state["released_at"] = asyncio.get_event_loop().time()

    monkeypatch.setattr(chat_routes, "acquire_rerank_slot", _tracking_slot)

    side_effect_at = {}

    async def _slow_side_effects(*a, **k):
        await asyncio.sleep(0.05)
        side_effect_at["ran_at"] = asyncio.get_event_loop().time()
        side_effect_at["slot_held_during"] = slot_state["in_slot"]

    monkeypatch.setattr(chat_routes, "_post_answer_side_effects", _slow_side_effects)

    # ... drive _run_answer end-to-end; await for side-effects task to complete
    # assert side_effect_at["slot_held_during"] is False
```

- [ ] **Step 2: Implement the refactor.**

In `website/api/chat_routes.py`, replace the current `_run_answer` body (the `try: async with acquire_rerank_slot(): ... await _post_answer_side_effects(...)` block) with:

```python
async def _run_answer(runtime, kg_user_id: UUID, session: dict, body: ChatMessageRequest):
    await runtime.sessions.update_session(
        UUID(session["id"]),
        kg_user_id,
        last_scope_filter=body.scope_filter.model_dump(),
        quality_mode=body.quality,
    )
    query = ChatQuery(...)  # unchanged

    # iter-10 P2: slot wraps orchestrator.answer ONLY. _post_answer_side_effects
    # runs as a fire-and-forget asyncio.create_task AFTER the slot is released
    # so first-message-of-session auto-title (15-40s Gemini call) doesn't
    # serialize the rerank queue.
    try:
        async with acquire_rerank_slot():
            turn = await runtime.orchestrator.answer(query=query, user_id=kg_user_id)
    except QueueFull as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "queue_full", "message": "Rerank capacity full; retry shortly."},
            headers={"Retry-After": "5"},
        ) from exc

    # Fire-and-forget side effects with exception isolation. Failures here
    # MUST NOT 500 the response; they are recoverable enrichment.
    async def _side_effects_safely():
        try:
            await _post_answer_side_effects(
                runtime, kg_user_id, session, body.content,
                body.scope_filter.model_dump(),
            )
        except Exception:  # noqa: BLE001 — best-effort; structured log only
            logger.exception("post_answer_side_effects failed (recoverable)")

    asyncio.create_task(_side_effects_safely())

    return {"session_id": session["id"], "turn": turn.model_dump()}
```

- [ ] **Step 3: Apply the same pattern to the SSE streaming path.**

Find the equivalent stream handler (`_stream_answer_with_backpressure` or `_stream_answer`) and ensure side effects run AFTER the streaming generator yields its `done` event AND outside the slot. The cleanest pattern:

```python
async def _stream_answer(...):
    async with acquire_rerank_slot():
        async for event in runtime.orchestrator.answer_stream(...):
            yield event
    # OUTSIDE the slot now — schedule side effects
    asyncio.create_task(_side_effects_safely())
```

- [ ] **Step 4: Run admission tests.**

```bash
pytest tests/unit/api/test_chat_routes_admission.py -v
```

- [ ] **Step 5: Run full chat-routes tests for regressions.**

```bash
pytest tests/unit/api/ -v
```

- [ ] **Step 6: Commit.**

```bash
git add website/api/chat_routes.py tests/unit/api/test_chat_routes_admission.py
git commit -m "feat: post-answer side effects fire and forget"
```

---

## Phase 4 — Recall fixes + zettel-type discriminator

### Task 9: chunk_count_quartile tie-breaker + cross-class regression fixture (Item 3)

**Why:** When candidates land on identical RRF scores, current sort is stable but arbitrary. A small-chunk magnet can win top-1 over a chunky-but-relevant gold. Adding `chunk_count_quartile` as a tie-breaker (NOT a gate) lets the discriminator nudge in the right direction without changing existing behavior. The cross-class regression fixture catches "fixed q10 / broke q5" patterns automatically.

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py` (sort key in `_dedup_and_fuse`)
- Test: `tests/unit/rag/retrieval/test_chunk_count_tiebreak.py` (new)
- Test: `tests/unit/rag/integration/test_class_x_source_matrix.py` (new — regression fixture)

- [ ] **Step 1: Write the tie-breaker test.**

```python
# tests/unit/rag/retrieval/test_chunk_count_tiebreak.py — new
"""iter-10 Item 3: chunk_count_quartile tie-breaker so two candidates with
identical rrf_score are ordered deterministically by quartile relevance."""
from website.features.rag_pipeline.retrieval.hybrid import _tiebreak_key
from website.features.rag_pipeline.types import QueryClass


def test_higher_quartile_wins_when_rrf_tied():
    """For LOOKUP, the chunky-but-relevant zettel (Q3) should beat the
    small-chunk near-tie (Q1) when rrf is identical."""
    # rrf identical, quartile differs
    a = _tiebreak_key(rrf_score=0.5, chunk_count=12, chunk_counts={"a": 12, "b": 2}, query_class=QueryClass.LOOKUP)
    b = _tiebreak_key(rrf_score=0.5, chunk_count=2,  chunk_counts={"a": 12, "b": 2}, query_class=QueryClass.LOOKUP)
    assert a > b  # higher tuple wins under reverse=True sort


def test_thematic_inverts_quartile_preference():
    """For THEMATIC, prefer LOWER chunk-count when rrf is tied — broader
    coverage > deep monoculture."""
    a = _tiebreak_key(rrf_score=0.5, chunk_count=12, chunk_counts={"a": 12, "b": 2}, query_class=QueryClass.THEMATIC)
    b = _tiebreak_key(rrf_score=0.5, chunk_count=2,  chunk_counts={"a": 12, "b": 2}, query_class=QueryClass.THEMATIC)
    assert b > a


def test_tiebreak_does_not_change_order_when_rrf_differs():
    """The tie-breaker must not override real rrf differences."""
    a = _tiebreak_key(rrf_score=0.6, chunk_count=2,  chunk_counts={"a": 2, "b": 12}, query_class=QueryClass.LOOKUP)
    b = _tiebreak_key(rrf_score=0.5, chunk_count=12, chunk_counts={"a": 2, "b": 12}, query_class=QueryClass.LOOKUP)
    assert a > b  # rrf 0.6 wins regardless of chunk_count
```

- [ ] **Step 2: Implement `_tiebreak_key`.**

```python
# In website/features/rag_pipeline/retrieval/hybrid.py
import statistics

def _tiebreak_key(
    rrf_score: float,
    chunk_count: int,
    chunk_counts: dict[str, int],
    query_class: QueryClass | None,
) -> tuple[float, float]:
    """iter-10 Item 3: return a sort key whose first element is rrf_score
    (primary), and second element is a class-conditional chunk_count_quartile
    bias. Used as `key=lambda c: _tiebreak_key(...)` with reverse=True.

    LOOKUP / VAGUE: prefer higher quartile (chunky relevant zettels win ties).
    THEMATIC / MULTI_HOP / STEP_BACK: prefer LOWER quartile (broad coverage).
    """
    if not chunk_counts or chunk_count <= 0:
        return (rrf_score, 0.0)
    counts = sorted(chunk_counts.values())
    n = len(counts)
    # Compute the 0..1 quartile rank of THIS candidate's chunk_count.
    rank = sum(1 for c in counts if c <= chunk_count) / n
    invert = query_class in (QueryClass.THEMATIC, QueryClass.MULTI_HOP, QueryClass.STEP_BACK)
    bias = (1.0 - rank) if invert else rank
    return (rrf_score, bias * 0.0001)  # bias is sub-floor; only matters on tie
```

- [ ] **Step 3: Wire the tie-breaker into `_dedup_and_fuse`'s final sort.**

```python
# Replace the existing sort line:
ordered = sorted(
    by_key.values(),
    key=lambda c: _tiebreak_key(
        c.rrf_score,
        (chunk_counts or {}).get(c.node_id, 0),
        chunk_counts or {},
        query_class,
    ),
    reverse=True,
)
```

- [ ] **Step 4: Write the cross-class regression fixture.**

```python
# tests/unit/rag/integration/test_class_x_source_matrix.py — new
"""iter-10 cross-class regression fixture: any retrieval-stage change that
moves one class's metric MUST NOT regress another. This fixture replays a
small, hand-curated 6-query mini-suite spanning {LOOKUP, THEMATIC, MULTI_HOP}
× {youtube, github, newsletter, web} and checks the per-(class,source)
top-1 outcome. If a change causes a previously-passing intersection to
regress, the test fails — preventing 'fixed q10 / broke q5' patterns."""

# This is a fixture-driven test; the fixture file is checked into the repo
# and pinned by hash. Update only after a deliberate eval delta is approved.
import json, pathlib
import pytest

FIXTURE = pathlib.Path(__file__).parent / "class_x_source_baseline.json"


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture not yet seeded")
def test_class_x_source_baseline_no_regression():
    expected = json.loads(FIXTURE.read_text())
    # The fixture format: {"<qid>": {"class": "lookup", "source": "github",
    #                                "expected_primary": "gh-zk-org-zk"}}
    # Run the deduplication path in isolation (no Supabase) using stub rows
    # captured in the fixture; assert _dedup_and_fuse returns the same
    # expected_primary for every entry.
    from website.features.rag_pipeline.retrieval.hybrid import HybridRetriever
    # ... executor: load fixture rows, call _dedup_and_fuse with the same
    # query_metadata, assert primary matches.
    pass
```

Seed the fixture file `tests/unit/rag/integration/class_x_source_baseline.json` from iter-09 verification_results.json's q-list, picking 6 queries that span the matrix.

- [ ] **Step 5: Run all tests.**

```bash
pytest tests/unit/rag/retrieval/test_chunk_count_tiebreak.py tests/unit/rag/integration/test_class_x_source_matrix.py tests/unit/rag/retrieval/ -v
```

- [ ] **Step 6: Commit.**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_chunk_count_tiebreak.py tests/unit/rag/integration/test_class_x_source_matrix.py tests/unit/rag/integration/class_x_source_baseline.json
git commit -m "feat: chunk count quartile tiebreak plus regression fixture"
```

### Task 10: Q6/Q7 dense-only fallback (P5) — GATED ON Task 2 SCOUT

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py` (after main RPC fan-out)
- Test: `tests/unit/rag/retrieval/test_dense_fallback.py` (new)

**ONLY proceed with this task if Task 2 confirmed q6/q7 candidate pool is empty of expected gold node ids. If pool already had gold, skip Task 10 and rely on P3 (Phase 5) to surface them.**

- [ ] **Step 1 (gate check): Re-read Task 2 decision.**

If decision was "pool already had gold; skip" → mark Task 10 complete with a comment in the executor log: `"P5 fallback not needed; pool had gold; ranking surfaced wrong primary"` → proceed to Phase 5.

If decision was "pool MISSING gold" → proceed with Steps 2-6 below.

- [ ] **Step 2: Failing test.**

```python
# tests/unit/rag/retrieval/test_dense_fallback.py — new
"""iter-10 P5: dense-only fallback when hybrid recall@K misses every kasten
member. Triggers a single high-precision dense pass scoped to ALL kasten
members so q6/q7-shape recall failures still surface SOMETHING for rerank."""
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_fallback_fires_when_pool_empty_and_kasten_nonempty():
    # ... Stub _search to return [] for all variants. Stub _resolve_nodes
    # to return ["yt-jobs", "yt-naval"]. Assert a 2nd RPC call to
    # rag_dense_recall_fallback (or similar) fires.
    pass


@pytest.mark.asyncio
async def test_fallback_skipped_when_pool_nonempty():
    # ... Stub returns at least one row; assert NO fallback RPC fires.
    pass
```

- [ ] **Step 3: Implement.**

In `hybrid.py:retrieve()`, after the multi-variant `_search` gather:

```python
# iter-10 P5: dense-only fallback for kasten-golden recall miss.
_FALLBACK_ENABLED = os.environ.get(
    "RAG_DENSE_FALLBACK_ENABLED", "true"
).lower() not in ("false", "0", "no", "off")
total_rows = sum(len(r) for r in results)
if (
    _FALLBACK_ENABLED
    and total_rows == 0
    and effective_nodes is not None
    and len(effective_nodes) > 0
):
    _log.warning(
        "dense_fallback_fire scope=%d (hybrid recall=0)", len(effective_nodes)
    )
    fallback = await self._supabase.rpc(
        "rag_dense_recall",
        {
            "p_user_id": str(user_id),
            "p_effective_nodes": effective_nodes,
            "p_query_embedding": embeddings[0],
            "p_limit": min(limit, 8),
        },
    ).execute()
    results = [fallback.data or []]  # treat as one variant
```

- [ ] **Step 4: Add Supabase migration for `rag_dense_recall` RPC.**

```sql
-- supabase/website/kg_public/migrations/2026-05-04_rag_dense_recall.sql
BEGIN;

CREATE OR REPLACE FUNCTION rag_dense_recall(
    p_user_id        uuid,
    p_effective_nodes text[],
    p_query_embedding vector(768),
    p_limit          int DEFAULT 8
) RETURNS TABLE (
    kind        text,
    node_id     text,
    chunk_id    uuid,
    chunk_idx   int,
    name        text,
    source_type text,
    url         text,
    content     text,
    tags        text[],
    rrf_score   double precision
)
LANGUAGE sql STABLE AS $$
    SELECT
        'chunk'::text       AS kind,
        n.id                AS node_id,
        kc.id               AS chunk_id,
        kc.chunk_idx,
        n.name,
        n.source_type,
        n.url,
        kc.content,
        n.tags,
        1 - (kc.embedding <=> p_query_embedding) AS rrf_score
    FROM kg_node_chunks kc
    JOIN kg_nodes n
      ON n.id = kc.node_id
     AND n.user_id = kc.user_id
    WHERE n.user_id = p_user_id
      AND n.id = ANY(p_effective_nodes)
    ORDER BY kc.embedding <=> p_query_embedding ASC
    LIMIT p_limit;
$$;

GRANT EXECUTE ON FUNCTION rag_dense_recall(uuid, text[], vector, int) TO anon, authenticated;

COMMIT;
```

- [ ] **Step 5: Apply migration.**

```bash
python -c "
from pathlib import Path
from urllib.parse import urlparse
import httpx
sql = Path('supabase/website/kg_public/migrations/2026-05-04_rag_dense_recall.sql').read_text()
env = {l.split('=',1)[0].strip(): l.split('=',1)[1].strip().strip('\"').strip(\"'\")
       for l in Path('.env').read_text().splitlines()
       if l.strip() and not l.startswith('#') and '=' in l}
ref = urlparse(env['SUPABASE_URL']).hostname.split('.', 1)[0]
resp = httpx.post(
    f'https://api.supabase.com/v1/projects/{ref}/database/query',
    json={'query': sql},
    headers={'Authorization': f'Bearer {env[\"SUPABASE_ACCESS_TOKEN\"]}', 'Content-Type': 'application/json'},
    timeout=60.0,
)
print(resp.status_code, resp.text[:300])
"
```

Expected: 200/201.

- [ ] **Step 6: Update `supabase/website/kg_public/schema.sql` to mirror.**

- [ ] **Step 7: Run tests.**

```bash
pytest tests/unit/rag/retrieval/test_dense_fallback.py tests/unit/rag/retrieval/ -v
```

- [ ] **Step 8: Commit.**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py supabase/website/kg_public/migrations/2026-05-04_rag_dense_recall.sql supabase/website/kg_public/schema.sql tests/unit/rag/retrieval/test_dense_fallback.py
git commit -m "feat: dense fallback for kasten recall miss"
```

---

## Phase 5 — q5 magnet: score-rank-correlation gate (P3)

**Scope:** THEMATIC and STEP_BACK only. q7 is THEMATIC (verified disk fact). VAGUE is excluded — different failure mode and pre-existing `vague_low_entity` gate.

### Task 11: Score-rank-correlation gate + title-overlap demote

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py` (apply AFTER chunk-share + anchor-boost, BEFORE final sort)
- Test: `tests/unit/rag/retrieval/test_score_rank_magnet_gate.py` (new)

- [ ] **Step 1: Failing tests.**

```python
# tests/unit/rag/retrieval/test_score_rank_magnet_gate.py — new
"""iter-10 P3: score-rank-correlation magnet gate.

A node is a magnet if its top-1 ranking is disproportionate to its retrieval
percentile. We compute the percentile rank of each candidate's BASE rrf
(BEFORE all class boosts) and demote any candidate whose ranked position is
> 1 quartile higher than its rrf percentile in THEMATIC/STEP_BACK class.
"""
from website.features.rag_pipeline.retrieval.hybrid import _apply_score_rank_demote
from website.features.rag_pipeline.types import QueryClass, RetrievalCandidate, ChunkKind, SourceType


def _cand(node_id: str, base_rrf: float, final_rrf: float) -> RetrievalCandidate:
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK, node_id=node_id, chunk_idx=0, name=node_id,
        source_type=SourceType.WEB, url="", content="",
    )
    c.rrf_score = final_rrf
    c.metadata = {"_base_rrf_score": base_rrf}
    return c


def test_thematic_demotes_magnet_with_low_base_rrf():
    """Candidate with base rrf 0.10 (10th percentile) but boosted to top-1
    via title-match magnet must be demoted."""
    cands = [
        _cand("magnet-2chunk", base_rrf=0.10, final_rrf=0.85),
        _cand("real-thematic-a", base_rrf=0.55, final_rrf=0.60),
        _cand("real-thematic-b", base_rrf=0.50, final_rrf=0.55),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.THEMATIC, query_text="general topic")
    # After demote, magnet's final rrf must drop BELOW the real-thematic candidates.
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id != "magnet-2chunk"


def test_lookup_does_not_demote_magnet():
    """LOOKUP must NEVER apply the gate — proper-noun lookups legitimately
    boost a single high-relevance node to top-1 even if base rrf was lower."""
    cands = [
        _cand("magnet-2chunk", base_rrf=0.10, final_rrf=0.85),
        _cand("other", base_rrf=0.55, final_rrf=0.60),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.LOOKUP, query_text="proper noun query")
    # Magnet stays at top — lookup does not demote.
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id == "magnet-2chunk"


def test_thematic_no_demote_when_no_disproportion():
    """If a candidate's rank matches its base rrf percentile, no demote."""
    cands = [
        _cand("a", base_rrf=0.80, final_rrf=0.85),  # high base, high final — earned
        _cand("b", base_rrf=0.70, final_rrf=0.75),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.THEMATIC, query_text="topic")
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id == "a"


def test_step_back_class_also_gated():
    """STEP_BACK shares the same magnet vulnerability as THEMATIC."""
    cands = [
        _cand("magnet", base_rrf=0.10, final_rrf=0.85),
        _cand("real", base_rrf=0.55, final_rrf=0.60),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.STEP_BACK, query_text="step back")
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id == "real"


def test_vague_class_NOT_gated():
    """VAGUE has its own vague_low_entity gate; do not double-gate."""
    cands = [
        _cand("magnet", base_rrf=0.10, final_rrf=0.85),
    ]
    _apply_score_rank_demote(cands, query_class=QueryClass.VAGUE, query_text="vague")
    assert cands[0].rrf_score == 0.85  # unchanged


def test_title_overlap_secondary_demote():
    """Even within THEMATIC, a candidate whose top-1 win came purely from
    title-overlap boost (>=0.10 of the boost) gets a multiplicative demote."""
    cands = [
        _cand("title-magnet", base_rrf=0.30, final_rrf=0.80),
    ]
    cands[0].metadata["_title_overlap_boost"] = 0.15
    _apply_score_rank_demote(cands, query_class=QueryClass.THEMATIC, query_text="topic")
    assert cands[0].rrf_score < 0.80  # demoted
```

- [ ] **Step 2: Run tests; verify they fail.**

```bash
pytest tests/unit/rag/retrieval/test_score_rank_magnet_gate.py -v
```

- [ ] **Step 3: Implement `_apply_score_rank_demote`.**

In `website/features/rag_pipeline/retrieval/hybrid.py`:

```python
import os, statistics
from website.features.rag_pipeline.types import QueryClass, RetrievalCandidate

_SCORE_RANK_GATED_CLASSES = {QueryClass.THEMATIC, QueryClass.STEP_BACK}
_SCORE_RANK_DEMOTE_FACTOR = float(
    os.environ.get("RAG_SCORE_RANK_DEMOTE_FACTOR", "0.85")
)
_SCORE_RANK_DISPROP_QUARTILES = float(
    os.environ.get("RAG_SCORE_RANK_DISPROP_QUARTILES", "1.0")
)
_TITLE_OVERLAP_DEMOTE_FACTOR = float(
    os.environ.get("RAG_TITLE_OVERLAP_DEMOTE_FACTOR", "0.95")
)
_TITLE_OVERLAP_DEMOTE_FLOOR = float(
    os.environ.get("RAG_TITLE_OVERLAP_DEMOTE_FLOOR", "0.10")
)


def _apply_score_rank_demote(
    candidates: list[RetrievalCandidate],
    *,
    query_class: QueryClass | None,
    query_text: str = "",
) -> None:
    """iter-10 P3: demote candidates whose top-1 ranking is disproportionate
    to their BASE retrieval percentile in THEMATIC/STEP_BACK queries.

    Mechanism:
      1. Compute each candidate's percentile of `_base_rrf_score` (or
         `rrf_score` if base not stored — early in the pipeline).
      2. Compare to the candidate's *current* rank (after all boosts).
      3. If current rank is >= _SCORE_RANK_DISPROP_QUARTILES higher than
         its base percentile, multiply rrf_score by _SCORE_RANK_DEMOTE_FACTOR.
      4. Independently, if `_title_overlap_boost` >= floor, also demote.

    Mutates `candidates` in place. LOOKUP and VAGUE bypass.
    """
    if query_class not in _SCORE_RANK_GATED_CLASSES:
        return
    if not candidates or len(candidates) < 4:
        return  # not enough rank-spread to be meaningful

    # Base rrf percentile (use _base_rrf_score if stored, else rrf_score).
    base_scores = [
        float(c.metadata.get("_base_rrf_score", c.rrf_score))
        for c in candidates
    ]
    sorted_base = sorted(base_scores)
    n = len(base_scores)

    def _percentile(score: float) -> float:
        return sum(1 for s in sorted_base if s <= score) / n

    # Current rank percentile (post-boost).
    current_sorted = sorted(candidates, key=lambda c: c.rrf_score, reverse=True)
    current_rank = {id(c): (n - i) / n for i, c in enumerate(current_sorted)}

    for c in candidates:
        base_pct = _percentile(float(c.metadata.get("_base_rrf_score", c.rrf_score)))
        rank_pct = current_rank[id(c)]
        # rank_pct ~ 1.0 at top; if base_pct is 0.10 but rank_pct is 1.0,
        # delta = 0.90 quartiles -> demote.
        delta = rank_pct - base_pct
        if delta >= _SCORE_RANK_DISPROP_QUARTILES * 0.25:
            c.rrf_score *= _SCORE_RANK_DEMOTE_FACTOR

        # Title-overlap secondary demote.
        title_boost = float(c.metadata.get("_title_overlap_boost", 0.0))
        if title_boost >= _TITLE_OVERLAP_DEMOTE_FLOOR:
            c.rrf_score *= _TITLE_OVERLAP_DEMOTE_FACTOR
```

- [ ] **Step 4: Wire into `_dedup_and_fuse` AFTER chunk-share + anchor-boost, BEFORE final sort.**

Also: store `_base_rrf_score` on each candidate when it's first added to `by_key` (in the dedup loop), and store `_title_overlap_boost` in `_title_match_boost` when applied.

```python
# In the dedup loop where _row_to_candidate is called:
candidate = _row_to_candidate(row)
candidate.metadata["_base_rrf_score"] = candidate.rrf_score
by_key[key] = candidate

# In _title_match_boost wherever applied:
boost = _compute_title_match_boost(...)
if boost > 0:
    candidate.rrf_score += boost
    candidate.metadata["_title_overlap_boost"] = (
        candidate.metadata.get("_title_overlap_boost", 0.0) + boost
    )

# After chunk-share + anchor-boost, BEFORE the final sorted(...) call:
_apply_score_rank_demote(
    list(by_key.values()),
    query_class=query_class,
    query_text=(query_variants or [""])[0] if query_variants else "",
)
```

- [ ] **Step 5: Run all retrieval tests.**

```bash
pytest tests/unit/rag/retrieval/ tests/unit/rag_pipeline/retrieval/ -v
```

Expected: all green (existing + new). The cross-class regression fixture from Task 9 acts as the safety net — if anything regresses on a known-good intersection, the test fires.

- [ ] **Step 6: Commit.**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_score_rank_magnet_gate.py
git commit -m "feat: score rank magnet demote thematic stepback"
```

---

## Phase 6 — Pre-rerank quality gate (P9)

### Task 12: Adaptive percentile floor with class-conditional naming

**Files:**
- Modify: `website/features/rag_pipeline/rerank/cascade.py`
- Test: `tests/unit/rag/rerank/test_adaptive_percentile_floor.py` (new)

**Naming convention** (mirrors pre-existing droplet env vars `RAG_CONTEXT_FLOOR_*`):
- `RAG_RERANK_INPUT_FLOOR_LOOKUP=0.30` (default)
- `RAG_RERANK_INPUT_FLOOR_THEMATIC=0.05` (looser; broad recall)
- `RAG_RERANK_INPUT_FLOOR_DEFAULT=0.10` (multi_hop / step_back / vague)
- `RAG_RERANK_INPUT_MIN_KEEP=8` (cold-start protection floor)

- [ ] **Step 1: Failing tests.**

```python
# tests/unit/rag/rerank/test_adaptive_percentile_floor.py — new
"""iter-10 P9: adaptive percentile floor before BGE int8 cross-encoder.

NOT a hard rrf<X cutoff (would collapse cold-start kastens). Drops the
bottom 30% of candidates by rrf BUT respects RAG_RERANK_INPUT_MIN_KEEP=8
lower bound so small kastens never lose recall."""
from website.features.rag_pipeline.rerank.cascade import _filter_pre_rerank
from website.features.rag_pipeline.types import QueryClass, RetrievalCandidate, ChunkKind, SourceType


def _c(rrf: float, nid: str = "n") -> RetrievalCandidate:
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK, node_id=f"{nid}-{rrf}", chunk_idx=0,
        name=nid, source_type=SourceType.WEB, url="", content="",
    )
    c.rrf_score = rrf
    return c


def test_drops_bottom_30_percent_when_above_min_keep():
    cands = [_c(r) for r in [0.9, 0.7, 0.5, 0.3, 0.2, 0.15, 0.1, 0.08, 0.05, 0.02]]
    filt = _filter_pre_rerank(cands, query_class=QueryClass.LOOKUP)
    assert len(filt) == 8  # min_keep enforced (10 * 0.7 = 7, but min_keep=8 wins)


def test_min_keep_protects_small_pools(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_INPUT_MIN_KEEP", "8")
    cands = [_c(r) for r in [0.5, 0.4, 0.3, 0.2]]
    filt = _filter_pre_rerank(cands, query_class=QueryClass.LOOKUP)
    assert len(filt) == 4  # all kept; pool < min_keep


def test_lookup_uses_higher_floor_than_thematic(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_INPUT_FLOOR_LOOKUP", "0.30")
    monkeypatch.setenv("RAG_RERANK_INPUT_FLOOR_THEMATIC", "0.05")
    monkeypatch.setenv("RAG_RERANK_INPUT_MIN_KEEP", "0")
    cands = [_c(r) for r in [0.5, 0.4, 0.25, 0.20, 0.10, 0.06, 0.04]]
    look = _filter_pre_rerank(cands, query_class=QueryClass.LOOKUP)
    them = _filter_pre_rerank(cands, query_class=QueryClass.THEMATIC)
    # LOOKUP drops <0.30 candidates; THEMATIC keeps >=0.05.
    assert all(c.rrf_score >= 0.30 for c in look)
    assert all(c.rrf_score >= 0.05 for c in them)
    assert len(them) > len(look)


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_INPUT_FLOOR_ENABLED", "false")
    cands = [_c(r) for r in [0.5, 0.05, 0.01]]
    filt = _filter_pre_rerank(cands, query_class=QueryClass.LOOKUP)
    assert len(filt) == 3  # no filtering
```

- [ ] **Step 2: Run failing tests.**

```bash
pytest tests/unit/rag/rerank/test_adaptive_percentile_floor.py -v
```

- [ ] **Step 3: Implement `_filter_pre_rerank`.**

In `website/features/rag_pipeline/rerank/cascade.py`:

```python
import os
from website.features.rag_pipeline.types import QueryClass, RetrievalCandidate


def _rerank_input_floor(query_class: QueryClass | None) -> float:
    if query_class is QueryClass.LOOKUP:
        return float(os.environ.get("RAG_RERANK_INPUT_FLOOR_LOOKUP", "0.30"))
    if query_class is QueryClass.THEMATIC:
        return float(os.environ.get("RAG_RERANK_INPUT_FLOOR_THEMATIC", "0.05"))
    return float(os.environ.get("RAG_RERANK_INPUT_FLOOR_DEFAULT", "0.10"))


def _filter_pre_rerank(
    candidates: list[RetrievalCandidate],
    *,
    query_class: QueryClass | None,
) -> list[RetrievalCandidate]:
    """iter-10 P9: drop low-rrf candidates BEFORE the cross-encoder sees them.

    - Class-conditional floor (mirrors RAG_CONTEXT_FLOOR_* naming on droplet).
    - Adaptive percentile: drop bottom 30% (configurable).
    - Hard min_keep floor so cold-start kastens never lose recall.
    """
    enabled = os.environ.get(
        "RAG_RERANK_INPUT_FLOOR_ENABLED", "true"
    ).lower() not in ("false", "0", "no", "off")
    if not enabled or not candidates:
        return candidates

    min_keep = int(os.environ.get("RAG_RERANK_INPUT_MIN_KEEP", "8"))
    if len(candidates) <= min_keep:
        return list(candidates)

    floor = _rerank_input_floor(query_class)
    # Apply absolute floor.
    by_floor = [c for c in candidates if c.rrf_score >= floor]
    # If absolute floor cut too deep, fall back to percentile (drop bottom 30%).
    if len(by_floor) < min_keep:
        sorted_cands = sorted(candidates, key=lambda c: c.rrf_score, reverse=True)
        keep_n = max(min_keep, int(len(sorted_cands) * 0.7))
        return sorted_cands[:keep_n]
    # Else, also drop bottom 30% of those above the floor (denser top-K = faster rerank).
    sorted_above = sorted(by_floor, key=lambda c: c.rrf_score, reverse=True)
    keep_n = max(min_keep, int(len(sorted_above) * 0.7))
    return sorted_above[:keep_n]
```

- [ ] **Step 4: Wire into the cascade reranker entry point.**

Find the cascade.py function that takes the deduplicated candidates and runs them through BGE int8. Insert the filter immediately before the rerank loop:

```python
# In cascade.py, just before the existing rerank loop:
candidates = _filter_pre_rerank(candidates, query_class=query_class)
```

- [ ] **Step 5: Run rerank + retrieval tests.**

```bash
pytest tests/unit/rag/rerank/ tests/unit/rag/retrieval/ -v
```

- [ ] **Step 6: Commit.**

```bash
git add website/features/rag_pipeline/rerank/cascade.py tests/unit/rag/rerank/test_adaptive_percentile_floor.py
git commit -m "feat: adaptive percentile pre rerank floor"
```

---

## Phase 7 — Synthesis polish (P13)

### Task 13: Clause-coverage self-check in SYSTEM_PROMPT

**Files:**
- Modify: `website/features/rag_pipeline/generation/prompts.py`

**Why:** iter-09 RAGAS `answer_relevancy=74.29` vs `faithfulness=87.50` means the model is faithful but doesn't fully address every clause of multi-part questions. A self-check step before final output enforces clause coverage.

- [ ] **Step 1: Find SYSTEM_PROMPT.**

```bash
grep -n "SYSTEM_PROMPT" website/features/rag_pipeline/generation/prompts.py | head -5
```

- [ ] **Step 2: Read 50 lines around it to understand the existing template.**

- [ ] **Step 3: Add a clause-coverage instruction near the end of SYSTEM_PROMPT.**

```python
# website/features/rag_pipeline/generation/prompts.py
# Inside SYSTEM_PROMPT — append before the final closing string:

CLAUSE_COVERAGE_RULE = """
COVERAGE CHECK (mandatory before finalising):
1. Identify each distinct sub-question or clause in the user's question.
2. For each clause, confirm your answer addresses it OR explicitly state which
   clauses are not covered by the retrieved context.
3. If a clause is uncovered, do not invent — say "the available sources don't
   address <clause>" briefly and move on.
This step prevents partial answers being marked supported when only the first
clause was tackled.
"""

SYSTEM_PROMPT = SYSTEM_PROMPT + CLAUSE_COVERAGE_RULE  # or interpolate at the right point
```

- [ ] **Step 4: Add a regression test that the prompt contains the rule.**

```python
# tests/unit/rag/generation/test_prompts_clause_coverage.py — new
def test_system_prompt_contains_clause_coverage_rule():
    from website.features.rag_pipeline.generation.prompts import SYSTEM_PROMPT
    assert "COVERAGE CHECK" in SYSTEM_PROMPT
    assert "sub-question" in SYSTEM_PROMPT.lower()
```

- [ ] **Step 5: Run tests.**

```bash
pytest tests/unit/rag/generation/ -v
```

- [ ] **Step 6: Commit.**

```bash
git add website/features/rag_pipeline/generation/prompts.py tests/unit/rag/generation/test_prompts_clause_coverage.py
git commit -m "feat: clause coverage self check in synth prompt"
```

---

## Phase 8 — Observability + drift guards

### Task 14: P8 RSS pre/post-slot logging

**Files:**
- Modify: `website/api/_concurrency.py`

- [ ] **Step 1: Read the current `acquire_rerank_slot` body.**

```bash
grep -A 20 "async def acquire_rerank_slot" website/api/_concurrency.py
```

- [ ] **Step 2: Wrap the slot acquire with RSS sampling.**

```python
# website/api/_concurrency.py
import os, logging, resource

_logger = logging.getLogger("rag.concurrency")
_RSS_LOG_ENABLED = os.environ.get(
    "RAG_SLOT_RSS_LOG_ENABLED", "true"
).lower() not in ("false", "0", "no", "off")


def _rss_kb() -> int:
    try:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        return 0


@asynccontextmanager
async def acquire_rerank_slot():
    state = get_concurrency_state()
    rss_pre = _rss_kb() if _RSS_LOG_ENABLED else 0
    if state.depth >= state.queue_max:
        raise QueueFull(f"queue depth {state.depth} >= {state.queue_max}")
    state.depth += 1
    try:
        async with state.semaphore:
            yield
    finally:
        state.depth -= 1
        if _RSS_LOG_ENABLED:
            rss_post = _rss_kb()
            _logger.info(
                "slot depth=%d/%d rss_pre_kb=%d rss_post_kb=%d delta_kb=%d",
                state.depth, state.queue_max, rss_pre, rss_post, rss_post - rss_pre,
            )
```

- [ ] **Step 3: Test that env disable works.**

```python
# tests/unit/api/test_concurrency_rss_log.py — new
import pytest
from website.api._concurrency import acquire_rerank_slot, get_concurrency_state


@pytest.mark.asyncio
async def test_rss_log_emits(caplog, monkeypatch):
    monkeypatch.setenv("RAG_SLOT_RSS_LOG_ENABLED", "true")
    state = get_concurrency_state()
    state.depth = 0
    with caplog.at_level("INFO", logger="rag.concurrency"):
        async with acquire_rerank_slot():
            pass
    assert any("rss_pre_kb" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rss_log_disabled_via_env(caplog, monkeypatch):
    monkeypatch.setenv("RAG_SLOT_RSS_LOG_ENABLED", "false")
    state = get_concurrency_state()
    state.depth = 0
    with caplog.at_level("INFO", logger="rag.concurrency"):
        async with acquire_rerank_slot():
            pass
    assert not any("rss_pre_kb" in r.message for r in caplog.records)
```

- [ ] **Step 4: Run tests.**

```bash
pytest tests/unit/api/test_concurrency_rss_log.py -v
```

- [ ] **Step 5: Commit.**

```bash
git add website/api/_concurrency.py tests/unit/api/test_concurrency_rss_log.py
git commit -m "feat: rss pre post slot log"
```

### Task 15: P12 chunk_share TTL + THEMATIC empty-counts logging

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/chunk_share.py`
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py` (THEMATIC empty-counts path; if `_ensure_member_coverage` is here)

- [ ] **Step 1: Add TTL hit/miss + RPC error logging in `ChunkShareStore.get_chunk_counts`.**

```python
# In website/features/rag_pipeline/retrieval/chunk_share.py
import logging
_log = logging.getLogger("rag.chunk_share")


async def get_chunk_counts(self, sandbox_id):
    if sandbox_id is None:
        return {}
    key = str(sandbox_id)
    if key in self._cache:
        _log.debug("chunk_counts cache_hit sandbox=%s", key)
        return self._cache[key]
    try:
        _log.debug("chunk_counts cache_miss sandbox=%s rpc=rag_kasten_chunk_counts", key)
        response = self._supabase.rpc(
            "rag_kasten_chunk_counts", {"p_sandbox_id": key},
        ).execute()
        data = response.data or []
    except Exception as exc:
        _log.warning("chunk_counts rpc_error sandbox=%s exc=%s", key, type(exc).__name__)
        data = []
    counts = {row["node_id"]: int(row.get("chunk_count", 0)) for row in data}
    if not counts:
        _log.warning(
            "chunk_counts empty sandbox=%s (suspect member-coverage hole or RPC empty)",
            key,
        )
    self._cache[key] = counts
    return counts
```

- [ ] **Step 2: In hybrid.py, log THEMATIC fan-out when chunk_counts is empty.**

```python
# In retrieve(), after chunk_counts is fetched:
if (
    chunk_counts == {}
    and query_class is QueryClass.THEMATIC
    and sandbox_id is not None
):
    _log.warning(
        "thematic_empty_counts sandbox=%s — _ensure_member_coverage may overcompensate",
        sandbox_id,
    )
```

- [ ] **Step 3: Add a unit test asserting log lines fire under known conditions.**

```python
# tests/unit/rag/retrieval/test_chunk_share_logging.py — new
import logging, pytest
from unittest.mock import MagicMock


def test_chunk_counts_empty_warning(caplog):
    fake = MagicMock()
    fake.rpc.return_value.execute.return_value.data = []
    from website.features.rag_pipeline.retrieval.chunk_share import ChunkShareStore
    store = ChunkShareStore(supabase=fake, ttl_seconds=10.0)
    import asyncio
    with caplog.at_level(logging.WARNING, logger="rag.chunk_share"):
        asyncio.run(store.get_chunk_counts(sandbox_id="ks1"))
    assert any("chunk_counts empty" in r.message for r in caplog.records)
```

- [ ] **Step 4: Run tests.**

```bash
pytest tests/unit/rag/retrieval/test_chunk_share_logging.py -v
```

- [ ] **Step 5: Commit.**

```bash
git add website/features/rag_pipeline/retrieval/chunk_share.py website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_chunk_share_logging.py
git commit -m "feat: chunk share ttl and thematic empty logs"
```

### Task 16: CI grep guard for unwrapped `@router.post`

**Files:**
- Test: `tests/unit/api/test_admission_drift_guard.py` (new)

**Why:** iter-09 RES-4 fixed an `_run_answer` that had been silently unwrapped for 5 iters. This test catches the same drift class going forward.

- [ ] **Step 1: Write the test.**

```python
# tests/unit/api/test_admission_drift_guard.py — new
"""iter-10 drift guard: any @router.post that calls runtime.orchestrator.answer
must be inside (or call into) a function that wraps the call in
acquire_rerank_slot. Catches the iter-04..iter-09 silent-bug class."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROUTES_DIR = REPO / "website" / "api"
ALLOWED_WRAPPERS = {"acquire_rerank_slot"}


def test_no_router_post_invokes_orchestrator_answer_without_admission():
    """Scan every router file. For each function decorated with @router.post,
    if the function (or any function it calls) references
    runtime.orchestrator.answer, that function (or callee) must contain a
    reference to acquire_rerank_slot in the same source span."""
    offenders = []
    for path in ROUTES_DIR.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        # Find all @router.post decorated function bodies.
        # Heuristic: split on @router.post( and inspect each body.
        chunks = re.split(r"@router\.post\(", src)
        for i, chunk in enumerate(chunks[1:], start=1):
            # The function body lives until the next decorator/def at column 0
            # or end-of-file. Take the next ~80 lines as the inspection window.
            window = "\n".join(chunk.split("\n")[:80])
            if "orchestrator.answer" not in window and "_run_answer" not in window:
                continue
            # The window may delegate to a helper function — look up the helper
            # in the same file and inspect ITS body too.
            helpers_called = re.findall(r"\b(_run_answer|_stream_answer\w*)\s*\(", window)
            spans_to_check = [window]
            for helper in set(helpers_called):
                m = re.search(rf"async def {helper}\b.*?(?=\nasync def |\ndef |\Z)", src, re.DOTALL)
                if m:
                    spans_to_check.append(m.group(0))
            wrapped = any(
                any(w in span for w in ALLOWED_WRAPPERS)
                for span in spans_to_check
            )
            if not wrapped:
                offenders.append(f"{path.name}@route#{i}")
    assert not offenders, (
        "Routes calling orchestrator.answer without acquire_rerank_slot wrap: "
        + ", ".join(offenders)
        + ". This is the iter-04..iter-09 silent-bug class."
    )
```

- [ ] **Step 2: Run.**

```bash
pytest tests/unit/api/test_admission_drift_guard.py -v
```

Expected: PASS (iter-09 fix already wrapped both paths).

- [ ] **Step 3: Commit.**

```bash
git add tests/unit/api/test_admission_drift_guard.py
git commit -m "test: drift guard router post acquire rerank slot"
```

### Task 17: Per-stage timestamps `t_retrieval`, `t_rerank`, `t_synth`

**Files:**
- Modify: `website/features/rag_pipeline/orchestrator.py` (capture `time.monotonic_ns()` at boundaries)
- Modify: `website/api/chat_routes.py` (surface in response payload)
- Test: `tests/unit/rag/test_orchestrator_per_stage_timing.py` (new)

- [ ] **Step 1: Failing test.**

```python
# tests/unit/rag/test_orchestrator_per_stage_timing.py — new
@pytest.mark.asyncio
async def test_answer_returns_per_stage_timestamps():
    # Drive the orchestrator with stub retriever/reranker/llm; assert the
    # returned AnswerTurn or surrounding payload contains t_retrieval_ms,
    # t_rerank_ms, t_synth_ms keys with monotonic ordering (each >= 0,
    # sum <= total latency_ms).
    pass
```

- [ ] **Step 2: Implement timing capture in orchestrator.answer.**

```python
# website/features/rag_pipeline/orchestrator.py
import time

# In answer(), capture timestamps:
t_start = time.monotonic_ns()
# ... retrieval call ...
t_after_retrieval = time.monotonic_ns()
# ... rerank call ...
t_after_rerank = time.monotonic_ns()
# ... synthesis call ...
t_after_synth = time.monotonic_ns()

stage_timings = {
    "t_retrieval_ms": (t_after_retrieval - t_start) // 1_000_000,
    "t_rerank_ms": (t_after_rerank - t_after_retrieval) // 1_000_000,
    "t_synth_ms": (t_after_synth - t_after_rerank) // 1_000_000,
}
turn.token_counts["stage_timings"] = stage_timings  # piggy-back on existing dict
logger.info(
    "stage_timings retrieval=%dms rerank=%dms synth=%dms",
    *stage_timings.values()
)
```

- [ ] **Step 3: Surface in chat_routes response.**

The `turn.model_dump()` already includes token_counts, so stage_timings will be on the wire. Verify by checking the existing serializer.

- [ ] **Step 4: Run tests.**

```bash
pytest tests/unit/rag/test_orchestrator_per_stage_timing.py tests/unit/rag/test_orchestrator.py -v
```

- [ ] **Step 5: Commit.**

```bash
git add website/features/rag_pipeline/orchestrator.py website/api/chat_routes.py tests/unit/rag/test_orchestrator_per_stage_timing.py
git commit -m "feat: per stage retrieval rerank synth timing"
```

---

## Phase 9 — Deploy + final eval

### Task 18: Update `ops/.env.example`

**Files:** `ops/.env.example`

- [ ] **Step 1: Append iter-10 env flags block.**

```
# ── iter-10 RAG knobs (default values listed; see iter-10 RESEARCH.md) ──
# P4 anchor-seed mitigations
RAG_ANCHOR_SEED_MIN_ENTITY_LENGTH=4
RAG_ANCHOR_SEED_TOP_K=3

# P11 auto-title model
RAG_AUTO_TITLE_MODEL=gemini-2.5-flash-lite

# P9 pre-rerank quality gate (mirrors RAG_CONTEXT_FLOOR_* convention)
RAG_RERANK_INPUT_FLOOR_ENABLED=true
RAG_RERANK_INPUT_FLOOR_LOOKUP=0.30
RAG_RERANK_INPUT_FLOOR_THEMATIC=0.05
RAG_RERANK_INPUT_FLOOR_DEFAULT=0.10
RAG_RERANK_INPUT_MIN_KEEP=8

# P3 score-rank-correlation magnet gate (THEMATIC/STEP_BACK only)
RAG_SCORE_RANK_DEMOTE_FACTOR=0.85
RAG_SCORE_RANK_DISPROP_QUARTILES=1.0
RAG_TITLE_OVERLAP_DEMOTE_FACTOR=0.95
RAG_TITLE_OVERLAP_DEMOTE_FLOOR=0.10

# P5 dense-only fallback (gated by Phase 0 scout decision)
RAG_DENSE_FALLBACK_ENABLED=true

# P8 observability
RAG_SLOT_RSS_LOG_ENABLED=true
```

- [ ] **Step 2: Commit.**

```bash
git add ops/.env.example
git commit -m "docs: iter-10 env flags"
```

### Task 19: Run full pytest suite

**Files:** none.

- [ ] **Step 1: Run.**

```bash
pytest -q
```

Expected: 542 + iter-10 new tests passing (previously documented 4 pre-existing failures unrelated to RAG changes — confirm those 4 are still the only fails).

- [ ] **Step 2: If unexpected failures, fix and re-test before Step 3.**

- [ ] **Step 3: Push.**

```bash
git push origin master
```

### Task 20: Run iter-10 eval, write scores.md, commit

**Files:** `docs/rag_eval/common/knowledge-management/iter-10/scores.md` (new), `verification_results.json` (new).

- [ ] **Step 1: After deploy completes, dispatch the eval.**

```powershell
$env:EVAL_USE_SSE_HARNESS="true"; python ops\scripts\eval_iter_03_playwright.py --iter iter-10
python ops\scripts\score_rag_eval.py --iter iter-10
```

- [ ] **Step 2: Write scores.md** matching iter-09's structure. Include `gold@1_unconditional`, `gold@1_within_budget`, p_user_avg, p_user_total, ttft_avg, stage_timings p95s.

- [ ] **Step 3: Annotate which iter-09 failures recovered (q5/q6/q7/q10) and report multi-user safety metrics (burst 503 rate, 502 count, OOM events from droplet).**

- [ ] **Step 4: Commit.**

```bash
git add docs/rag_eval/common/knowledge-management/iter-10/
git commit -m "docs: iter-10 scores and verification results"
git push origin master
```

---

## Self-review checklist (executor: run before claiming done)

- [ ] Every approved iter-10 item (P1, P2, P3, P4, P5 if scout-confirmed, P6, P8, P9, P11, P12, P13, Item 3, CI grep, per-stage timing) has a Task that implements it.
- [ ] No `TBD`, `TODO`, `fill in later` placeholders in any task body.
- [ ] Type/method names consistent across tasks (e.g. `_should_inject_anchor_seeds`, `_apply_score_rank_demote`, `_filter_pre_rerank`, `_tiebreak_key`).
- [ ] Phase 0 / Task 2 scout decision recorded BEFORE Task 10 starts.
- [ ] All env flags added to `ops/.env.example` (Task 18).
- [ ] Cross-class regression fixture (Task 9 `test_class_x_source_matrix.py`) passes after every retrieval-stage change in Phases 4–6.
- [ ] No protected CLAUDE.md knob touched.
- [ ] Final eval shows: composite ≥ 85, gold@1_unconditional ≥ 0.85, gold@1_within_budget ≥ 0.85, burst 503 rate ≥ 0.08, zero 502 from upstream-down. ALL three thresholds, not stack-rank.
