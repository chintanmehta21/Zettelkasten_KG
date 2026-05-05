# iter-11 RAG-eval Recovery Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read [RESEARCH.md](RESEARCH.md) before each phase.

**Goal:** Close the iter-04..iter-10 chapter on the KM Kasten by hitting **composite ≥ 85, gold@1 ≥ 0.85, within_budget ≥ 0.85**, plus zero burst 502 and confirmed-or-corrected p_user latency. iter-10 landed measurement-truth (within_budget +0.57) and observability (per-stage timing, RSS, chunk-share logs); iter-11 closes the 5 ranking failures plus 2 cosmetic/observability extras.

**Architecture:** Five class-generic fixes targeting query-classes of failures (NOT individual queries) — Class A entity-anchor exemption on magnet gate, Class B name-overlap override on THEMATIC tiebreak, Class C per-entity anchor union, Class D short-query entity-hint expansion, Class F class-conditional critic threshold. Plus scorer N/A handling for `expected=[]` (E1) and an SSE-buffering investigation that may reframe p_user accounting (E2). Each fix lands behind an env flag, has a unit test, and is verifiable against `tests/unit/rag/integration/test_class_x_source_matrix.py` plus a new fixture per class.

**Tech Stack:** Python 3.12, FastAPI/uvicorn/gunicorn, asyncio, pytest + pytest-asyncio, Supabase Postgres + pgvector, BGE int8 cross-encoder, Gemini 2.5 (flash-lite for cheap rewriter calls), Caddy 2 SSE, Docker Compose blue/green on DigitalOcean droplet, Playwright Python harness.

---

## Architectural decisions baked in (per CLAUDE.md guardrails — DO NOT touch)

`GUNICORN_WORKERS=2`, `--preload`, `FP32_VERIFY_ENABLED` top-3 only, `GUNICORN_TIMEOUT≥180s` (verified prod=240s), rerank semaphore + bounded queue (`RAG_QUEUE_MAX=8/worker`), SSE heartbeat wrapper, Caddy `read_timeout 240s`, schema-drift gate, `kg_users` allowlist gate, teal/amber color rule, BGE int8 reranker (no swap), threshold floors (`_PARTIAL_NO_RETRY_FLOOR`, `_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR`, `_RETRY_TOP_SCORE_FLOOR`, `_REFUSAL_SEMANTIC_GATE_FLOOR`).

**iter-11 explicit operator approval:** Class F (class-conditional critic threshold for THEMATIC/STEP_BACK) is authorised to layer ABOVE the LOOKUP-default `_PARTIAL_NO_RETRY_FLOOR` — adding a per-class additive offset, NOT lowering the LOOKUP floor itself. Operator chat-confirmed approval before iter-11 implementation.

---

## File Structure

| File | Responsibility | Phase / Task |
|---|---|---|
| `website/features/rag_pipeline/retrieval/entity_anchor.py` | Class C: per-entity union + structured logging on `resolve_anchor_nodes` | 1 / 2, 1 / 3 |
| `website/features/rag_pipeline/retrieval/hybrid.py` | Class A entity-anchor exemption on `_apply_score_rank_demote` + Class B name-overlap on `_tiebreak_key` + Class C anchor flow + score-rank gate observability log | 2-3 |
| `website/features/rag_pipeline/query/transformer.py` | Class D: extend gazetteer/HyDE to short-THEMATIC and gate by `len(query.split()) <= 4` | 4 / 9 |
| `website/features/rag_pipeline/query/vague_expander.py` | Class D: ensure gazetteer keys cover all the "commencement"-shape token families | 4 / 9 (review only) |
| `website/features/rag_pipeline/orchestrator.py` | Class F: class-conditional critic threshold gate via env-driven additive offsets | 5 / 11 |
| `ops/scripts/score_rag_eval.py` | E1: `expected=[]` N/A handling in `_aggregate_gold_metrics` + scores.md template line | 6 / 12 |
| `ops/scripts/eval_iter_03_playwright.py` | E2: capture true server-render-start time vs Cloudflare-deliver time so p_user reflects user-waited duration | 7 / 13 |
| `tests/unit/rag/retrieval/test_hybrid_anchor_seed_gate.py` | Class A unit tests | 2 / 5 |
| `tests/unit/rag/retrieval/test_chunk_count_tiebreak.py` | Class B name-overlap override tests | 3 / 6 |
| `tests/unit/rag/retrieval/test_entity_anchor_per_entity.py` | NEW: Class C per-entity union tests | 1 / 2 |
| `tests/unit/rag/query/test_short_query_expansion.py` | NEW: Class D tests | 4 / 9 |
| `tests/unit/rag/test_orchestrator_critic_threshold.py` | NEW: Class F tests | 5 / 11 |
| `tests/unit/ops_scripts/test_score_rag_eval_gold_split.py` | E1 add `expected=[]` test cases | 6 / 12 |
| `tests/unit/rag/integration/test_class_x_source_matrix.py` | Cross-class regression net — extend with one fixture per new class | 1-5 (per phase) |
| `ops/.env.example` | New env flags for all five classes + iter-11 documentation | 8 / 14 |
| `docs/rag_eval/common/knowledge-management/iter-11/scores.md` | Final scorecard (canonical template — NO fix recommendations in scores.md) | 8 / 16 |

---

## Phase 0 — Pre-flight (no code changes)

### Task 1: Mandatory reading

**Files:** none.

- [ ] **Step 1:** Read in this order:
  1. `docs/rag_eval/common/knowledge-management/iter-10/scores.md` — iter-10 outcomes + per-query forensic
  2. `docs/rag_eval/common/knowledge-management/iter-10/PLAN.md` — what iter-10 implemented (avoid duplicate work)
  3. `docs/rag_eval/common/knowledge-management/iter-10/RESEARCH.md` — RES-1 through RES-11 rationale; especially RES-3 (P3 magnet gate), RES-4 (P4 anchor un-gate), RES-7 deepdive correction, RES-11 (deferred items)
  4. `docs/rag_eval/common/knowledge-management/iter-11/RESEARCH.md` (this iter's rationale, classes A-F)
  5. `docs/rag_eval/common/knowledge-management/iter-09/iter09_failure_deepdive.md` — per-query forensic (note: deepdive's auto-title-Gemini claim is INCORRECT, see iter-10 RES-7 correction)
  6. `CLAUDE.md` root — Critical Infra Decision Guardrails (Class F operator-approved exemption is THE guardrail interaction; everything else stays untouched)

### Task 2 (renamed Task numbering: scout / no-scout decision)

**Files:** none — investigative.

**Why:** the user-approved Class C is "per-entity anchor resolution + union". On reading iter-11 RESEARCH.md (Class C section), we found that the existing `rag_resolve_entity_anchors` RPC already uses OR-semantics over `unnest(p_entities)`. This raises a question: is q10's failure actually metadata extraction (no entities surfaced to call the resolver with), or anchor-seed cap=3 dropping the Jobs node, or something else?

- [ ] **Step 1:** Add temporary logging in `hybrid.py:retrieve()` BEFORE Phase 1 / Task 2 implementation:

```python
import logging as _logging
_scout = _logging.getLogger("rag.iter11_scout")
_scout.info(
    "iter11_scout qid=%s class=%s authors=%r entities=%r anchor_nodes=%r anchor_seeds_n=%d",
    getattr(query_metadata, "qid", "?"),
    getattr(query_class, "value", query_class),
    getattr(query_metadata, "authors", None),
    getattr(query_metadata, "entities", None),
    list(anchor_nodes),
    len(anchor_seeds),
)
```

- [ ] **Step 2:** Push the scout commit (mid-impl push allowed on iter-11 once with operator approval; ask explicitly before pushing). After deploy, dispatch the eval just for q10. Pull droplet logs.

- [ ] **Step 3:** Branch on the signal:
  - If `authors=[] entities=[]` for q10 → root cause is **metadata extraction** (Steve Jobs / Naval Ravikant not surfaced). Implement Phase 1 by fixing the metadata extractor PLUS adding the per-entity union (defence in depth).
  - If `authors=["Steve Jobs"] entities=...` AND `anchor_nodes=set()` → root cause is **resolver behaviour** despite OR-semantics (e.g. RPC empty due to schema match nuance). Implement Phase 1 with per-entity loop.
  - If `anchor_nodes={"yt-steve-jobs-2005-stanford"}` AND `anchor_seeds_n=0` → root cause is **anchor-seed RPC** (`fetch_anchor_seeds`) returning empty. Investigate that RPC; per-entity loop in resolver isn't the right fix.

- [ ] **Step 4:** Remove the scout logging before final eval. Document the chosen branch in `iter-11/RESEARCH.md` under Class C.

---

## Phase 1 — Class C: per-entity anchor union + diagnostic logging

### Task 2: Per-entity loop in `resolve_anchor_nodes`

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/entity_anchor.py:8-23`
- Test: `tests/unit/rag/retrieval/test_entity_anchor_per_entity.py` (new)

- [ ] **Step 1: Write a failing test asserting per-entity union semantics.**

```python
# tests/unit/rag/retrieval/test_entity_anchor_per_entity.py — new
"""iter-11 Class C: anchor resolution must union per-entity, not require all."""
from unittest.mock import MagicMock
import pytest
from website.features.rag_pipeline.retrieval.entity_anchor import resolve_anchor_nodes


@pytest.mark.asyncio
async def test_partial_resolution_returns_resolved_subset():
    """Two entities, one resolves, one doesn't → union of resolved (= just the
    one that hit). Prior batched-RPC behaviour returned [] for ALL when ONE
    entity poisoned the match (q10 failure mode)."""
    sb = MagicMock()
    calls: list[list[str]] = []

    def _rpc(name, params):
        node = MagicMock()
        ents = params.get("p_entities") or []
        calls.append(list(ents))
        if ents == ["Steve Jobs"]:
            node.execute = MagicMock(return_value=MagicMock(data=[
                {"node_id": "yt-steve-jobs-2005-stanford"},
            ]))
        else:
            node.execute = MagicMock(return_value=MagicMock(data=[]))
        return node

    sb.rpc = _rpc
    out = await resolve_anchor_nodes(
        ["Steve Jobs", "Naval Ravikant"],
        sandbox_id="00000000-0000-0000-0000-000000000001",
        supabase=sb,
    )
    assert "yt-steve-jobs-2005-stanford" in out
    # Per-entity loop hits the RPC twice (once per entity).
    assert calls == [["Steve Jobs"], ["Naval Ravikant"]]


@pytest.mark.asyncio
async def test_all_resolve_returns_full_union():
    sb = MagicMock()

    def _rpc(name, params):
        node = MagicMock()
        ents = params.get("p_entities") or []
        if ents == ["A"]:
            node.execute = MagicMock(return_value=MagicMock(data=[{"node_id": "n1"}]))
        elif ents == ["B"]:
            node.execute = MagicMock(return_value=MagicMock(data=[{"node_id": "n2"}]))
        else:
            node.execute = MagicMock(return_value=MagicMock(data=[]))
        return node

    sb.rpc = _rpc
    out = await resolve_anchor_nodes(
        ["A", "B"], sandbox_id="00000000-0000-0000-0000-000000000001", supabase=sb,
    )
    assert out == {"n1", "n2"}


@pytest.mark.asyncio
async def test_zero_resolve_returns_empty():
    sb = MagicMock()
    sb.rpc = lambda *a, **k: MagicMock(execute=MagicMock(return_value=MagicMock(data=[])))
    out = await resolve_anchor_nodes(
        ["X"], sandbox_id="00000000-0000-0000-0000-000000000001", supabase=sb,
    )
    assert out == set()
```

- [ ] **Step 2: Run test; verify it fails on the first case (calls list mismatch — current impl batches).**

```bash
pytest tests/unit/rag/retrieval/test_entity_anchor_per_entity.py -v
```

- [ ] **Step 3: Implement per-entity loop with structured logging.**

```python
# website/features/rag_pipeline/retrieval/entity_anchor.py
"""iter-08 Phase 6: entity-name → KG anchor node resolver.

iter-11 Class C: switched from batched RPC to per-entity loop with union
semantics. Reason: the iter-09 batched call returns the union via RPC-side
OR, but app-side observability (which entity resolved? which didn't?) was
opaque. Per-entity calls cost one extra RPC round-trip per entity (typically
2-3 entities; ~30-90ms total) but unlock partial-resolve forensics critical
for q10-shape compare/multi-entity queries.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

_log = logging.getLogger("rag.entity_anchor")


async def resolve_anchor_nodes(
    entities: list[str],
    sandbox_id: UUID | str | None,
    supabase: Any,
) -> set[str]:
    """Map entity names to canonical Kasten node_ids via fuzzy title/tag match.

    iter-11 Class C: per-entity loop. Each entity gets its own RPC call;
    non-empty results are unioned. An empty entity list short-circuits early.
    """
    if not entities or sandbox_id is None:
        return set()
    resolved: set[str] = set()
    missing: list[str] = []
    for entity in entities:
        if not entity or not entity.strip():
            continue
        try:
            response = supabase.rpc(
                "rag_resolve_entity_anchors",
                {"p_sandbox_id": str(sandbox_id), "p_entities": [entity]},
            ).execute()
            rows = response.data or []
            if rows:
                resolved.update(row["node_id"] for row in rows)
            else:
                missing.append(entity)
        except Exception as exc:
            _log.debug("entity_anchor rpc_error entity=%r exc=%s", entity, type(exc).__name__)
            missing.append(entity)
    _log.info(
        "entity_anchor_resolve n_entities=%d resolved=%d missing=%r",
        len(entities), len(resolved), missing,
    )
    return resolved
```

- [ ] **Step 4: Run all retrieval tests.**

```bash
pytest tests/unit/rag/retrieval/ -q
```

Expected: all pass (existing batched-RPC tests need to be updated if they assert single-call semantics; check test_entity_anchor.py and adapt).

- [ ] **Step 5: Commit.**

```bash
git add website/features/rag_pipeline/retrieval/entity_anchor.py tests/unit/rag/retrieval/test_entity_anchor_per_entity.py
git commit -m "fix: per entity anchor resolution union semantics"
```

---

## Phase 2 — Class A: entity-anchor exemption on magnet gate

### Task 3: Skip score-rank demote for anchored or name-overlap candidates

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py:_apply_score_rank_demote` (~L195-225) AND its call site to thread `anchor_nodes` parameter
- Test: extend `tests/unit/rag/retrieval/test_score_rank_magnet_gate.py`

- [ ] **Step 1: Write a failing test asserting anchored candidates skip demote.**

```python
# tests/unit/rag/retrieval/test_score_rank_magnet_gate.py — append
def test_anchored_candidate_skips_demote():
    """iter-11 Class A: a candidate whose node_id is in anchor_nodes (the
    resolved-entity set) MUST NOT be demoted by the score-rank gate, even
    if it scores as a statistical magnet. The gate damps ONLY 'unearned'
    magnets; entity-anchored candidates have earned the top-1 slot."""
    cands = [
        _cand("legit-magnet", base_rrf=0.10, final_rrf=0.65),  # would normally be demoted
        _cand("real-a", 0.55, 0.60),
        _cand("real-b", 0.50, 0.55),
        _cand("real-c", 0.45, 0.50),
    ]
    _apply_score_rank_demote(
        cands,
        query_class=QueryClass.THEMATIC,
        query_text="topic",
        anchor_nodes={"legit-magnet"},  # NEW kwarg
    )
    # legit-magnet stays at 0.65 because it's anchored.
    assert cands[0].rrf_score == 0.65


def test_title_overlap_candidate_also_skips_score_rank_demote():
    """A candidate with _title_overlap_boost > 0 (query verbatim names this
    zettel) is exempted from the score-rank demote — title-match is an
    earned signal."""
    cands = [
        _cand("named-magnet", 0.10, 0.65),
        _cand("real-a", 0.55, 0.60),
        _cand("real-b", 0.50, 0.55),
        _cand("real-c", 0.45, 0.50),
    ]
    cands[0].metadata["_title_overlap_boost"] = 0.05  # below the title-demote floor 0.10 but >0
    _apply_score_rank_demote(
        cands,
        query_class=QueryClass.THEMATIC,
        query_text="topic",
        anchor_nodes=set(),
    )
    # Score-rank exempts. Title-overlap secondary demote DOES still apply
    # only when boost >= 0.10, so 0.05 is exempt from BOTH.
    assert cands[0].rrf_score == 0.65


def test_unanchored_magnet_still_gets_demoted():
    """Sanity: with anchor_nodes={} and no title boost, the gate still fires
    on the disproportional candidate (no behaviour change for the iter-10 case)."""
    cands = [
        _cand("magnet", 0.10, 0.65),
        _cand("real-a", 0.55, 0.60),
        _cand("real-b", 0.50, 0.55),
        _cand("real-c", 0.45, 0.50),
    ]
    _apply_score_rank_demote(
        cands,
        query_class=QueryClass.THEMATIC,
        query_text="topic",
        anchor_nodes=set(),
    )
    cands_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    assert cands_sorted[0].node_id != "magnet"
```

- [ ] **Step 2: Run test; verify it fails (current `_apply_score_rank_demote` has no `anchor_nodes` kwarg).**

- [ ] **Step 3: Update `_apply_score_rank_demote` signature + body in `hybrid.py`.**

```python
# In website/features/rag_pipeline/retrieval/hybrid.py
def _apply_score_rank_demote(
    candidates: list[RetrievalCandidate],
    *,
    query_class: QueryClass | None,
    query_text: str = "",
    anchor_nodes: set[str] | None = None,
) -> None:
    """iter-10 P3 + iter-11 Class A: demote magnets in THEMATIC/STEP_BACK,
    BUT skip demote for any candidate whose node_id is in anchor_nodes
    (resolved entity anchors) OR has _title_overlap_boost > 0 (query
    verbatim names this zettel). The 'earned-exemption' carve-out lets
    legit proper-noun winners survive while keeping the gate effective
    against unearned chunk-count magnets.
    """
    del query_text  # signal extension hook
    if query_class not in _SCORE_RANK_GATED_CLASSES:
        return
    if not candidates or len(candidates) < 4:
        return

    anchored = anchor_nodes or set()
    base_scores = [
        float(c.metadata.get("_base_rrf_score", c.rrf_score)) for c in candidates
    ]
    sorted_base = sorted(base_scores)
    n = len(base_scores)

    def _percentile(score: float) -> float:
        return sum(1 for s in sorted_base if s <= score) / n

    current_sorted = sorted(candidates, key=lambda c: c.rrf_score, reverse=True)
    current_rank = {id(c): (n - i) / n for i, c in enumerate(current_sorted)}

    delta_threshold = _SCORE_RANK_DISPROP_QUARTILES * 0.25
    n_demoted = 0
    n_title_demoted = 0
    factor_sum = 0.0
    for c in candidates:
        # iter-11 Class A: earned exemption.
        is_anchored = c.node_id in anchored
        has_title_overlap = float(c.metadata.get("_title_overlap_boost", 0.0)) > 0.0
        if is_anchored or has_title_overlap:
            continue
        base_pct = _percentile(float(c.metadata.get("_base_rrf_score", c.rrf_score)))
        rank_pct = current_rank[id(c)]
        delta = rank_pct - base_pct
        if delta >= delta_threshold:
            c.rrf_score *= _SCORE_RANK_DEMOTE_FACTOR
            n_demoted += 1
            factor_sum += _SCORE_RANK_DEMOTE_FACTOR
        title_boost = float(c.metadata.get("_title_overlap_boost", 0.0))
        if title_boost >= _TITLE_OVERLAP_DEMOTE_FLOOR:
            c.rrf_score *= _TITLE_OVERLAP_DEMOTE_FACTOR
            n_title_demoted += 1

    # iter-11 Class E observability: structured log so iter-12+ can tune
    # demote factor from real distributions.
    mean_factor = (factor_sum / n_demoted) if n_demoted else 0.0
    _log.info(
        "score_rank_demote class=%s n_cands=%d n_demoted=%d title_demoted=%d mean_factor=%.3f anchored_n=%d",
        getattr(query_class, "value", query_class),
        n, n_demoted, n_title_demoted, mean_factor, len(anchored),
    )
```

- [ ] **Step 4: Update the call site in `_dedup_and_fuse` to pass `anchor_nodes`.**

The plan needs `anchor_nodes` available inside `_dedup_and_fuse`. Currently `_dedup_and_fuse` receives `anchor_neighbours` (1-hop) and `anchor_seeds`. Plumb `anchor_nodes` through too — add a kwarg to `_dedup_and_fuse` (`anchor_nodes: set[str] | None = None`) and pass it from `retrieve()` (where it's already in scope at L251).

```python
# In retrieve(), at the _dedup_and_fuse call:
return self._dedup_and_fuse(
    results,
    query_variants=query_variants,
    query_metadata=query_metadata,
    query_class=query_class,
    chunk_counts=chunk_counts,
    effective_nodes=effective_nodes,
    anchor_neighbours=anchor_neighbours,
    anchor_nodes=set(anchor_nodes) if anchor_nodes else None,  # NEW
    anchor_seeds=anchor_seeds,
)

# In _dedup_and_fuse signature, add:
anchor_nodes: set[str] | None = None,

# In _dedup_and_fuse body, where _apply_score_rank_demote is called (L751 area):
_apply_score_rank_demote(
    list(by_key.values()),
    query_class=query_class,
    query_text=(query_variants or [""])[0] if query_variants else "",
    anchor_nodes=anchor_nodes,  # NEW
)
```

- [ ] **Step 5: Run retrieval tests.**

```bash
pytest tests/unit/rag/retrieval/ tests/unit/rag/integration/ -q
```

- [ ] **Step 6: Commit.**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_score_rank_magnet_gate.py
git commit -m "feat: anchor exemption on magnet gate plus log"
```

---

## Phase 3 — Class B: name-overlap override on THEMATIC tiebreaker

### Task 4: Skip THEMATIC chunk-quartile inversion when title overlap > 0

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py:_tiebreak_key` (~L165-190) + call site in `_dedup_and_fuse`
- Test: extend `tests/unit/rag/retrieval/test_chunk_count_tiebreak.py`
- Test: extend `tests/unit/rag/integration/test_class_x_source_matrix.py` with one name-overlap fixture

- [ ] **Step 1: Failing tests.**

```python
# tests/unit/rag/retrieval/test_chunk_count_tiebreak.py — append
def test_thematic_with_name_overlap_prefers_higher_quartile():
    """iter-11 Class B: when query verbatim names a zettel
    (_title_overlap_boost > 0), the THEMATIC chunk-quartile inversion is
    SKIPPED for that candidate — multi-chunk gold wins ties just like LOOKUP."""
    a = _tiebreak_key(0.5, 12, {"a": 12, "b": 2}, QueryClass.THEMATIC, title_overlap_boost=0.1)
    b = _tiebreak_key(0.5,  2, {"a": 12, "b": 2}, QueryClass.THEMATIC, title_overlap_boost=0.0)
    assert a > b  # higher chunk-count wins because "a" has name-overlap


def test_thematic_no_name_overlap_keeps_iter10_inversion():
    """Sanity: when neither candidate has name-overlap, iter-10 THEMATIC
    inversion (prefer LOWER chunk-count) still applies."""
    a = _tiebreak_key(0.5, 12, {"a": 12, "b": 2}, QueryClass.THEMATIC, title_overlap_boost=0.0)
    b = _tiebreak_key(0.5,  2, {"a": 12, "b": 2}, QueryClass.THEMATIC, title_overlap_boost=0.0)
    assert b > a


def test_lookup_with_name_overlap_unchanged():
    """LOOKUP already prefers higher quartile; name-overlap just confirms it."""
    a = _tiebreak_key(0.5, 12, {"a": 12, "b": 2}, QueryClass.LOOKUP, title_overlap_boost=0.1)
    b = _tiebreak_key(0.5,  2, {"a": 12, "b": 2}, QueryClass.LOOKUP, title_overlap_boost=0.0)
    assert a > b
```

- [ ] **Step 2: Run; verify failure on missing kwarg.**

- [ ] **Step 3: Update `_tiebreak_key` to accept `title_overlap_boost`.**

```python
# website/features/rag_pipeline/retrieval/hybrid.py
def _tiebreak_key(
    rrf_score: float,
    chunk_count: int,
    chunk_counts: dict[str, int],
    query_class: QueryClass | None,
    title_overlap_boost: float = 0.0,
) -> tuple[float, float]:
    """iter-10 Item 3 + iter-11 Class B: chunk_count_quartile tie-breaker.

    Class B: when title_overlap_boost > 0 (query verbatim names this zettel),
    the THEMATIC chunk-quartile inversion is bypassed — name-overlap is a
    stronger signal of "this is the user's target" than coverage breadth.
    """
    if not chunk_counts or chunk_count <= 0:
        return (rrf_score, 0.0)
    counts = list(chunk_counts.values())
    n = len(counts)
    rank = sum(1 for c in counts if c <= chunk_count) / n
    invert = (
        query_class in _TIEBREAK_INVERT_CLASSES
        and title_overlap_boost <= 0.0  # NEW: skip inversion on name-overlap
    )
    bias = (1.0 - rank) if invert else rank
    return (rrf_score, bias * 0.0001)
```

- [ ] **Step 4: Update call site in `_dedup_and_fuse` to pass title-overlap.**

```python
# In _dedup_and_fuse, where ordered = sorted(...) by tiebreak (~L745):
_ccs = chunk_counts or {}
ordered = sorted(
    by_key.values(),
    key=lambda candidate: _tiebreak_key(
        candidate.rrf_score,
        _ccs.get(candidate.node_id, 0),
        _ccs,
        query_class,
        title_overlap_boost=float(candidate.metadata.get("_title_overlap_boost", 0.0)),
    ),
    reverse=True,
)
```

- [ ] **Step 5: Add a name-overlap fixture to the cross-class regression net.**

```python
# tests/unit/rag/integration/test_class_x_source_matrix.py — extend _BASELINE
"thematic_named_zettel": {
    "class": "thematic",
    "rows": [
        {**_row("yt-programming-workflow-is", "youtube", 0.50), "name": "Programming Workflow"},
        _row("nl-other-essay", "newsletter", 0.50),
        _row("nl-broad-piece", "newsletter", 0.50),
        _row("nl-scoped-note", "newsletter", 0.50),
    ],
    "chunk_counts": {
        "yt-programming-workflow-is": 12,
        "nl-other-essay": 5,
        "nl-broad-piece": 3,
        "nl-scoped-note": 1,
    },
    # NEW: query mentions "programming workflow" verbatim.
    "query_variants": ["how does the programming workflow zettel describe..."],
    "expected_primary": "yt-programming-workflow-is",
},
```

The fixture will require `_dedup_and_fuse` to compute `_title_overlap_boost` from `query_variants` for the named candidate. Adapt the test's invocation accordingly (run normalized variants through the existing `_normalize_for_match` / `_title_match_boost` path).

- [ ] **Step 6: Run all tests.**

```bash
pytest tests/unit/rag/retrieval/ tests/unit/rag/integration/ -q
```

- [ ] **Step 7: Commit.**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_chunk_count_tiebreak.py tests/unit/rag/integration/test_class_x_source_matrix.py
git commit -m "feat: name overlap override on thematic tiebreak"
```

---

## Phase 4 — Class D: short-query entity-hint expansion in rewriter

### Task 5: Apply VAGUE-style gazetteer + HyDE to short THEMATIC queries

**Files:**
- Modify: `website/features/rag_pipeline/query/transformer.py:transform()` (~L28-58)
- Test: `tests/unit/rag/query/test_short_query_expansion.py` (new)

**Why:** q7 ("Anything about commencement?") is router-classified as THEMATIC, so the iter-07 VAGUE gazetteer expansion (which already maps "commencement" → "stanford 2005 / graduation / valedictory") never fires. iter-11 generalises: any THEMATIC query with `len(query.split()) <= 4` words gets the VAGUE expansion path in addition to its normal paraphrase variants.

- [ ] **Step 1: Failing test.**

```python
# tests/unit/rag/query/test_short_query_expansion.py — new
"""iter-11 Class D: short-THEMATIC queries get gazetteer + HyDE expansion."""
from unittest.mock import AsyncMock

import pytest

from website.features.rag_pipeline.query.transformer import QueryTransformer
from website.features.rag_pipeline.types import QueryClass


@pytest.mark.asyncio
async def test_short_thematic_query_gets_vague_expansion(monkeypatch):
    """A 3-word THEMATIC query like 'Anything about commencement?' must
    receive the iter-07 gazetteer expansion that previously only fired for
    VAGUE class. Verify by checking the variants list includes a known
    gazetteer expansion ('graduation' or 'stanford' for 'commencement')."""
    # Stub the rewriter LLM so we don't hit the network.
    pool = AsyncMock()
    async def _fake_gen(prompt, **kw):
        return "alt: what was said at graduation\nalt: stanford 2005 speech"
    pool.generate_content = _fake_gen
    qt = QueryTransformer(pool=pool)
    variants = await qt.transform("Anything about commencement?", QueryClass.THEMATIC)
    # The gazetteer for 'commencement' should produce at least one expansion.
    joined = " ".join(variants).lower()
    assert "graduation" in joined or "stanford" in joined or "valedictory" in joined


@pytest.mark.asyncio
async def test_long_thematic_query_no_vague_expansion(monkeypatch):
    """A 10-word THEMATIC query stays on the normal multi-query rewriter
    path — gazetteer is gated to len(query.split()) <= RAG_SHORT_THEMATIC_THRESHOLD."""
    pool = AsyncMock()
    async def _fake_gen(prompt, **kw):
        return "alt: paraphrase 1\nalt: paraphrase 2\nalt: paraphrase 3"
    pool.generate_content = _fake_gen
    qt = QueryTransformer(pool=pool)
    long_q = "How does the programming workflow zettel characterise the day-to-day skill of programming?"
    variants = await qt.transform(long_q, QueryClass.THEMATIC)
    # No gazetteer should fire (we don't have a long-query token in the gazetteer).
    assert len(variants) >= 2  # original + at least one paraphrase
```

- [ ] **Step 2: Run; verify it fails (current THEMATIC branch doesn't call expand_vague).**

- [ ] **Step 3: Implement the threshold in `transform()`.**

```python
# website/features/rag_pipeline/query/transformer.py
import os

_SHORT_THEMATIC_THRESHOLD = int(os.environ.get("RAG_SHORT_THEMATIC_THRESHOLD", "4"))


# In transform(), modify the THEMATIC branch:
elif cls is QueryClass.THEMATIC:
    _thematic_n = int(os.environ.get("RAG_THEMATIC_MULTIQUERY_N", "3"))
    base_variants = await self._multi_query(query, n=_thematic_n, entities=ents)
    # iter-11 Class D: short THEMATIC queries get the VAGUE-style gazetteer
    # + HyDE expansion. The router doesn't always catch "Anything about X?"
    # as VAGUE; this lifts the gazetteer floor up to short THEMATIC too.
    short = len(query.split()) <= _SHORT_THEMATIC_THRESHOLD
    if short:
        gazetteer_variants = expand_vague(query)
        hyde_variant = await self._hyde(query)
        variants = [query, hyde_variant, *gazetteer_variants, *base_variants]
    else:
        variants = [query, *base_variants]
```

- [ ] **Step 4: Run all query tests + retrieval regression.**

```bash
pytest tests/unit/rag/query/ tests/unit/rag/retrieval/ -q
```

- [ ] **Step 5: Commit.**

```bash
git add website/features/rag_pipeline/query/transformer.py tests/unit/rag/query/test_short_query_expansion.py
git commit -m "feat: short thematic gets vague expansion path"
```

---

## Phase 5 — Class F: class-conditional critic threshold

### Task 6: Per-class additive offset above the LOOKUP-default floor

**Files:**
- Modify: `website/features/rag_pipeline/orchestrator.py` around L186-220 (the `should_skip_retry` logic)
- Test: `tests/unit/rag/test_orchestrator_critic_threshold.py` (new)

**Why (also CLAUDE.md guardrail interaction):** the `_PARTIAL_NO_RETRY_FLOOR=0.5` and `_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR=0.7` thresholds are calibrated against single-zettel LOOKUP. For cross-corpus THEMATIC queries (q5-shape), no single chunk reaches the floor even when 4-5 zettels collectively support the answer. The fix layers a per-class additive **OFFSET** that LOWERS the effective threshold for THEMATIC/STEP_BACK only — LOOKUP/VAGUE keep the original floor. **Operator chat-confirmed approval recorded; do not lower LOOKUP's floor.**

- [ ] **Step 1: Failing tests.**

```python
# tests/unit/rag/test_orchestrator_critic_threshold.py — new
"""iter-11 Class F: class-conditional critic threshold for thematic refusals."""
from website.features.rag_pipeline.orchestrator import (
    _effective_partial_floor,
    _effective_unsupported_with_gold_skip_floor,
)
from website.features.rag_pipeline.types import QueryClass


def test_lookup_keeps_default_floor():
    assert _effective_partial_floor(QueryClass.LOOKUP) == 0.5
    assert _effective_unsupported_with_gold_skip_floor(QueryClass.LOOKUP) == 0.7


def test_thematic_lowered_by_offset(monkeypatch):
    monkeypatch.setenv("RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC", "-0.1")
    monkeypatch.setenv("RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR_OFFSET_THEMATIC", "-0.1")
    # offset is additive in the lower direction: 0.5 + (-0.1) = 0.4
    assert _effective_partial_floor(QueryClass.THEMATIC) == 0.4
    assert _effective_unsupported_with_gold_skip_floor(QueryClass.THEMATIC) == 0.6


def test_offset_respects_minimum_floor():
    """Even with a large negative offset, never drop below the safety floor
    of 0.3 (hard lower bound — prevents disabling the gate entirely)."""
    import os
    os.environ["RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC"] = "-0.99"
    try:
        # 0.5 + (-0.99) = -0.49 → clamped to 0.3
        assert _effective_partial_floor(QueryClass.THEMATIC) == 0.3
    finally:
        del os.environ["RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC"]


def test_step_back_uses_thematic_offset():
    """STEP_BACK shares the cross-corpus synthesis pattern — apply the
    same offset family."""
    import os
    os.environ["RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC"] = "-0.1"
    try:
        assert _effective_partial_floor(QueryClass.STEP_BACK) == 0.4
    finally:
        del os.environ["RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC"]
```

- [ ] **Step 2: Run; verify failure (functions don't exist yet).**

- [ ] **Step 3: Implement the offset helpers and wire them.**

```python
# website/features/rag_pipeline/orchestrator.py — near the existing floor constants
import os

_CRITIC_FLOOR_HARD_MIN = 0.3  # never go below this regardless of offset
_PARTIAL_NO_RETRY_FLOOR = 0.5  # iter-08 Fix A — LOOKUP/VAGUE default
_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR = float(
    os.environ.get("RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR", "0.7")
)

# iter-11 Class F: per-class additive offsets. THEMATIC/STEP_BACK only.
# Offsets are NEGATIVE (lowering effective floor for cross-corpus synthesis
# where no single chunk grounds the answer). Hard-clamped to >= _CRITIC_FLOOR_HARD_MIN.
def _offset_for_class(query_class: QueryClass | None, env_key: str) -> float:
    if query_class in (QueryClass.THEMATIC, QueryClass.STEP_BACK):
        return float(os.environ.get(env_key, "0.0"))
    return 0.0


def _effective_partial_floor(query_class: QueryClass | None) -> float:
    offset = _offset_for_class(
        query_class, "RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC",
    )
    return max(_CRITIC_FLOOR_HARD_MIN, _PARTIAL_NO_RETRY_FLOOR + offset)


def _effective_unsupported_with_gold_skip_floor(query_class: QueryClass | None) -> float:
    offset = _offset_for_class(
        query_class, "RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR_OFFSET_THEMATIC",
    )
    return max(_CRITIC_FLOOR_HARD_MIN, _UNSUPPORTED_WITH_GOLD_SKIP_FLOOR + offset)
```

- [ ] **Step 4: Replace direct `_PARTIAL_NO_RETRY_FLOOR` and `_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR` references in `should_skip_retry` (~L186-220) with the new helpers, threading the `query_class` parameter through.**

Concrete wiring (one edit, two call sites of the floor inside the function — replace each with the per-class effective floor):

```python
# In should_skip_retry — pseudocode shape:
def should_skip_retry(query_class, used_candidates, ...):
    top_score = _top_candidate_score(used_candidates)
    partial_floor = _effective_partial_floor(query_class)
    skip_floor = _effective_unsupported_with_gold_skip_floor(query_class)
    # Original logic lines remain — substitute the literal floors with
    # partial_floor and skip_floor variables.
    ...
```

- [ ] **Step 5: Run all orchestrator tests.**

```bash
pytest tests/unit/rag/test_orchestrator.py tests/unit/rag/test_orchestrator_critic_threshold.py tests/unit/rag/test_orchestrator_retry_policy.py -q
```

- [ ] **Step 6: Commit.**

```bash
git add website/features/rag_pipeline/orchestrator.py tests/unit/rag/test_orchestrator_critic_threshold.py
git commit -m "feat: class conditional critic threshold offsets"
```

---

## Phase 6 — Class E1: scorer N/A handling for `expected=[]`

### Task 7: `_aggregate_gold_metrics` treats empty-expected as N/A

**Files:**
- Modify: `ops/scripts/score_rag_eval.py:_aggregate_gold_metrics` (helper added in iter-10) AND the `_holistic_metrics` loop
- Test: extend `tests/unit/ops_scripts/test_score_rag_eval_gold_split.py`

- [ ] **Step 1: Failing test.**

```python
# tests/unit/ops_scripts/test_score_rag_eval_gold_split.py — append
def test_expected_empty_treated_as_not_applicable():
    """iter-11 Class E1: rows with expected=[] (refusal-expected adversarial
    queries) must not depress gold@1. They count toward a separate
    'gold_at_1_not_applicable' tally and are EXCLUDED from numerator AND
    denominator of gold@1 ratios."""
    from ops.scripts.score_rag_eval import _aggregate_gold_metrics
    rows = [
        {"gold_at_1": True,  "within_budget": True,  "expected_empty": False},
        {"gold_at_1": True,  "within_budget": False, "expected_empty": False},
        {"gold_at_1": False, "within_budget": True,  "expected_empty": True},   # n/a
        {"gold_at_1": False, "within_budget": False, "expected_empty": False},
    ]
    out = _aggregate_gold_metrics(rows)
    # Denominator excludes the n/a row: 3 scored rows, 2 gold, 1 within-budget gold.
    assert out["gold_at_1_unconditional"] == round(2/3, 4)
    assert out["gold_at_1_within_budget"] == round(1/3, 4)
    assert out["gold_at_1_not_applicable"] == 1
```

- [ ] **Step 2: Run; verify failure.**

- [ ] **Step 3: Implement.**

```python
# ops/scripts/score_rag_eval.py
def _aggregate_gold_metrics(rows: list[dict]) -> dict[str, float]:
    """iter-10 P6 + iter-11 Class E1: split gold@1; exclude refusal-expected."""
    scored = [r for r in rows if not r.get("expected_empty")]
    n_scored = max(len(scored), 1)
    n_na = sum(1 for r in rows if r.get("expected_empty"))
    unc = sum(1 for r in scored if r.get("gold_at_1") is True)
    wb = sum(
        1 for r in scored
        if r.get("gold_at_1") is True and r.get("within_budget") is True
    )
    return {
        "gold_at_1_unconditional": round(unc / n_scored, 4),
        "gold_at_1_within_budget": round(wb / n_scored, 4),
        "gold_at_1_not_applicable": n_na,
    }
```

Also update `_holistic_metrics` to set `r["expected_empty"] = not bool(d.get("expected"))` per row before calling the aggregator.

- [ ] **Step 4: Update `_render_scores_md` template to surface the n/a count.**

```python
lines.append(f"- gold@1 not applicable: {holistic.get('gold_at_1_not_applicable', 0)} (refusal-expected)")
```

- [ ] **Step 5: Run scoring tests.**

```bash
pytest tests/unit/ops_scripts/ -q
```

- [ ] **Step 6: Commit.**

```bash
git add ops/scripts/score_rag_eval.py tests/unit/ops_scripts/test_score_rag_eval_gold_split.py
git commit -m "fix: scorer treats empty expected as not applicable"
```

---

## Phase 7 — Class E2: SSE buffering investigation + p_user accounting

### Task 8: Confirm whether end-user perceives Cloudflare/Caddy SSE buffer wait

**Files:** investigative; possible modify `ops/scripts/eval_iter_03_playwright.py`

**Why:** iter-10 found server-side `latency_ms_server` is 0.9-1.9 s but `p_user_first_token_ms` is 22-37 s. The 25-30 s gap is somewhere between server response-write and JS reader receiving the first token. We need to determine: does a real browser-user actually wait this long, or is the gap an artefact of Playwright's `fetch().getReader()` semantics that a real EventSource consumer doesn't see?

- [ ] **Step 1: Investigation — three candidate hypotheses to disambiguate.**

  - **H1: Cloudflare buffers SSE until upstream finishes.** A real browser `EventSource` would also wait. → Real user-perceived; p_user is honest.
  - **H2: Caddy buffers responses larger than its sse-buffer config.** Same as H1 from user perspective.
  - **H3: Playwright `getReader()` doesn't fire until response is flushed; a real EventSource flushes on each frame.** → Synthetic harness artefact; p_user is overstated.

- [ ] **Step 2: Run a manual smoke from a real Chrome via DevTools `EventSource` against `/api/rag/adhoc` with stream=true:**

```javascript
// In DevTools console while signed in
const es = new EventSource('/api/rag/adhoc?...'); // adapt URL with auth
es.addEventListener('token', (e) => console.log('token@', performance.now(), e.data));
es.addEventListener('done', (e) => console.log('done@', performance.now()));
```

- [ ] **Step 3: Decide based on Step 2 timing:**
  - If first `token` event lands within 2-3 s in a real browser → harness artefact (H3). Document; consider a Playwright fetch-mode workaround (e.g. `EventSource` polyfill via `page.evaluate` with `new EventSource(...)` instead of `fetch().getReader()`); KEEP `p_user` accounting honest by NOT counting the harness artefact.
  - If first `token` event also takes 22-37 s in a real browser → real Cloudflare/Caddy buffering (H1/H2). Document; iter-12 needs a Caddy/Cloudflare config investigation; KEEP `p_user` as the source of truth.

- [ ] **Step 4: Write the finding into `iter-11/RESEARCH.md` under Class E2 with a verdict line.**

- [ ] **Step 5: If H1/H2 (real wait), no harness change needed — `p_user` already reflects user reality. If H3, modify `ops/scripts/eval_iter_03_playwright.py:api_fetch_sse` to use `page.evaluate` with a real `EventSource` so `p_user_first_token_ms` matches what a real browser sees.**

```javascript
// Replacement for api_fetch_sse evaluator (only if H3 confirmed):
async ({ url, body, token, timeout }) => {
    return new Promise((resolve, reject) => {
        const t0 = performance.now();
        let firstTokenAt = null, lastTokenAt = null, doneAt = null;
        // ... use new EventSource(url) with auth header injected via the
        // existing session cookie; collect token / done events; resolve
        // with the same shape the existing evaluator returns.
    });
}
```

- [ ] **Step 6: Commit.**

```bash
git add docs/rag_eval/common/knowledge-management/iter-11/RESEARCH.md
# Plus possibly ops/scripts/eval_iter_03_playwright.py if H3
git commit -m "ops: sse buffering investigation result"
```

---

## Phase 8 — Final: env example, docs, eval, scores

### Task 9: `ops/.env.example` iter-11 block

- [ ] **Step 1:** Append:

```
# ── iter-11 RAG knobs (defaults; see iter-11 RESEARCH.md) ──
# Class A: anchor / title-overlap exemption on score-rank magnet gate
RAG_SCORE_RANK_PROTECT_ANCHORED=true

# Class D: short-query entity-hint expansion (gazetteer + HyDE for short THEMATIC)
RAG_SHORT_THEMATIC_THRESHOLD=4

# Class F: class-conditional critic-threshold offsets (additive; clamped to >= 0.3)
RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC=-0.1
RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR_OFFSET_THEMATIC=-0.1
```

- [ ] **Step 2: Commit.**

```bash
git add ops/.env.example
git commit -m "docs: iter-11 env flags"
```

### Task 10: Full pytest

- [ ] **Step 1:** `pytest -q` — expected: 2075+ passing, plus iter-11 new tests, with the documented 4 pre-existing CI-environment failures (sandbox routes 402, two int8 quantization, fp32-verify-disabled-by-env).

- [ ] **Step 2: Push.** Single push of all iter-11 commits to master.

```bash
git push origin master
```

### Task 11: Deploy + smoke validation + eval

- [ ] **Step 1:** Wait for `deploy-droplet.yml` to land green. If smoke 402 fires (Naruto monthly meter exhausted), run `python ops/scripts/reset_naruto_smoke_meter.py` and re-run via `gh run rerun --failed`.

- [ ] **Step 2:** Operator runs the eval locally (PowerShell):

```powershell
cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault
$env:ZK_BEARER_TOKEN = (python ops/scripts/mint_eval_jwt.py)
$env:EVAL_USE_SSE_HARNESS='true'
python ops\scripts\eval_iter_03_playwright.py --iter iter-11
python ops\scripts\score_rag_eval.py --iter-dir docs\rag_eval\common\knowledge-management\iter-11
```

### Task 12: Write iter-11/scores.md (canonical template — NO fix recommendations)

- [ ] **Step 1:** Use the auto-generated `scores.md` from `score_rag_eval.py`. Match iter-09 / iter-10 canonical layout exactly: composite, components, RAGAS, latency, coverage, holistic, distributions, magnet-spotter, burst pressure, per-query table.

- [ ] **Step 2:** **Do NOT include fix recommendations, root-cause analysis, or carryover tables in scores.md.** Those belong in chat or RESEARCH.md / a separate iter-12 plan, never in scores.md.

- [ ] **Step 3: Commit.**

```bash
git add docs/rag_eval/common/knowledge-management/iter-11/scores.md
git commit -m "docs: iter-11 scores"
git push origin master
```

---

## Self-review checklist (executor: run before claiming done)

- [ ] Each of the 5 user-approved fixes (A, B, C, D, F) AND 2 extras (E1, E2) has at least one task in this plan.
- [ ] No `TBD`, `TODO`, `fill in later` placeholders in any task body.
- [ ] Type/method names consistent across tasks (`_apply_score_rank_demote`, `_tiebreak_key`, `_effective_partial_floor`, `resolve_anchor_nodes`).
- [ ] All env flags added to `ops/.env.example` (Task 9).
- [ ] Cross-class regression fixture passes after every retrieval-stage change in Phases 2-3 (Class B fixture is the new addition).
- [ ] No protected CLAUDE.md knob touched OUTSIDE the explicitly-approved Class F additive-offset path.
- [ ] Phase 0 / Task 2 scout decision recorded BEFORE Phase 1 / Task 2 implementation (or scout deferred to no-op if cheap-path-fix lands first).
- [ ] Final eval shows: composite ≥ 85, gold@1_unconditional ≥ 0.85, gold@1_within_budget ≥ 0.85, burst 502 = 0%, zero worker OOMs.
- [ ] scores.md follows canonical template (no fix recommendations).
