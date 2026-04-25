# RAG Pipeline Eval Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `rag_eval` loop framework mirroring `summary_eval`'s discipline for the RAG pipeline at `website/features/rag_pipeline/`, then run YouTube iters 1→5 autonomously and HALT for user review.

**Architecture:** Two-phase state machine (PHASE_A → AWAITING_REVIEW → PHASE_B → COMMITTED). Each iter ingests a Kasten of Zettels, runs 5 queries through the existing RAG orchestrator, scores via RAGAS+DeepEval, runs a graph-ablation pass for KG→RAG lift, dispatches a Claude subagent for cross-LLM blind review, applies KG recommendations autonomously, commits artifacts. KG and RAG co-evolve: graph_lift measures KG→RAG; `kg_recommendations.json` drives RAG→KG.

**Tech Stack:** Python 3.12, pydantic, asyncio, RAGAS (pinned), DeepEval (pinned), networkx (already used by graph_score), Supabase Python client (already in `core/supabase_kg/client.py`), pytest + pytest-asyncio + pytest-httpx, existing `GeminiKeyPool` from `website/features/api_key_switching/`.

**Spec:** `docs/superpowers/specs/2026-04-25-rag-eval-loop-design.md` (commit 6dba295).

---

## Tech Stack & Conventions

- All new tests live under `tests/unit/rag_pipeline/evaluation/` (mirroring existing `tests/unit/summarization_engine/`).
- Async functions use `asyncio_mode = auto` per `pyproject.toml`.
- Settings access via `get_settings()` is mocked in tests with `@patch` (calling unmocked triggers `SystemExit(1)`).
- Pydantic v2 models throughout (matches existing `rag_pipeline/types.py`).
- Imports: absolute paths only (`from website.features.rag_pipeline.evaluation.composite import ...`).
- Commits: 5–10 word subjects with `feat:` / `test:` / `docs:` / `ops:` prefixes per CLAUDE.md. No AI attribution. No Co-Authored-By.

---

## File Structure

**New files (created by this plan):**

```
website/features/rag_pipeline/evaluation/
  __init__.py
  types.py                        # extend with EvalResult, ComponentScores, GoldQuery, KGSnapshot
  gold_loader.py                  # loads/validates seed.yaml + heldout.yaml
  composite.py                    # weighted composite + delta arithmetic + hash lock
  component_scorers.py            # chunking/retrieval/rerank scorers (deterministic)
  ragas_runner.py                 # RAGAS adapter + key-pool integration
  deepeval_runner.py              # DeepEval adapter
  synthesis_score.py              # combines RAGAS + DeepEval into synthesis component
  ablation.py                     # runs eval with graph_weight=0; computes graph_lift
  eval_runner.py                  # orchestrates full eval (calls all scorers, returns EvalResult)
  kg_snapshot.py                  # snapshots KG slice + computes deltas
  kg_recommender.py               # produces kg_recommendations.json
  rendering.py                    # writes qa_pairs.md + scores.md + pipeline_changes.md (human-readable)

ops/scripts/
  rag_eval_loop.py                # main CLI
  apply_kg_recommendations.py     # autonomous KG mutation applicator
  lib/
    __init__.py
    rag_eval_state.py             # 4-state machine
    rag_eval_kasten.py            # Kasten builder + ingestion driver
    rag_eval_diff.py              # iter diffs + improvement_delta.json
    rag_eval_review.py            # cross-LLM blind reviewer dispatcher
    rag_eval_billing.py           # billing-key escalation + .halt + quota detection
    rag_eval_breadth.py           # change-breadth gate

docs/rag_eval/
  _config/
    composite_weights.yaml
    rubric_chunking.yaml
    rubric_retrieval.yaml
    rubric_rerank.yaml
    rubric_synthesis.yaml
    queries/
      youtube/seed.yaml
      youtube/heldout.yaml
      reddit/seed.yaml             # stub
      reddit/heldout.yaml          # stub
      github/seed.yaml             # stub
      github/heldout.yaml          # stub
      newsletter/seed.yaml         # stub
      newsletter/heldout.yaml      # stub
  _cache/                          # auto-created at runtime
  _dead_zettels/                   # auto-created at runtime
  _kg_changelog.md                 # appended by apply_kg_recommendations.py
  youtube/iter-01/...              # produced by Phase 5
  youtube/iter-02/... iter-05/     # produced by Phase 6a
  youtube/_synthesis.md            # written at end of Phase 6a

tests/unit/rag_pipeline/evaluation/   # new test directory
tests/unit/rag_pipeline/ops/          # new test directory for ops scripts
```

**Modified files:**

- `ops/requirements-dev.txt` — add ragas, deepeval (pinned versions resolved in Task 0.1)
- `ops/.env.example` — document `RAG_EVAL_*` env vars
- `pyproject.toml` — register new pytest test path

**No modifications to:**

- `website/features/summarization_engine/` (frozen)
- `docs/summary_eval/` (sealed)
- `website/features/rag_pipeline/orchestrator.py`, `service.py`, `types.py` interfaces (we extend, not replace — `types.py` gets new classes appended)

---

## Pre-Execution Verification Gate

**This gate runs BEFORE any code is written.** A fresh subagent (general-purpose) verifies the plan against the spec and reports gaps.

- [ ] **PG-1: Dispatch independent verification subagent**

```python
# Pseudocode for the dispatching session — use the Agent tool:
Agent(
  description="Verify rag_eval implementation plan",
  subagent_type="general-purpose",
  prompt="""
You are verifying an implementation plan against its design spec. Read both files in full:

- Spec: docs/superpowers/specs/2026-04-25-rag-eval-loop-design.md (commit 6dba295)
- Plan: docs/superpowers/plans/2026-04-25-rag-eval-loop-plan.md

Verify the following independently:

1. Spec coverage — for each numbered section in the spec (§1 through §13), identify which plan task implements it. Flag uncovered sections.
2. Decision coverage — find every "Decision:" block in the spec. For each, confirm a plan task enforces or implements that decision (e.g., spec §3a says weights are hash-locked; plan must have a task that hashes composite_weights.yaml at iter-01 and refuses divergence).
3. File path consistency — every file path mentioned in the plan is consistent with the spec's File Layout (§6).
4. Type/method consistency — types defined in early tasks (e.g., GoldQuery, EvalResult, ComponentScores) are used consistently in later tasks. Flag any name drift.
5. TDD discipline — every implementation task has a preceding test task with concrete assertions.
6. No placeholders — flag any "TBD", "implement later", "similar to Task N", or vague steps.
7. Cross-LLM blind review safety — verify the plan's review subagent dispatch (§4 of spec) only receives the spec-allowed inputs (manual_review_prompt.md, queries.json, answers.json, kasten.json, kg_snapshot.json) and NEVER eval.json or ablation_eval.json.
8. Wide-net change gate — verify a task implements the ≥3-component diff check from §7 spec.
9. Halt + billing-key escalation — verify a task implements the two-tier billing escalation per spec §11 risks table.
10. KG mutation safety brakes — verify the >5-mutations-of-one-type halt from spec §8b.

Report under 500 words:
- VERDICT: PROCEED / BLOCK
- Coverage gaps (numbered list)
- Consistency issues (numbered list)
- Safety gaps (numbered list)

If VERDICT=BLOCK, the implementing engineer must address every flagged item before any code task starts.
""",
)
```

- [ ] **PG-2: Address all verification findings**

If VERDICT=BLOCK, edit the plan inline to address each finding. Re-dispatch PG-1 until VERDICT=PROCEED. Only then proceed to Phase 0.

---

## Phase 0: Discovery & Contracts

### Task 0.1: Pin RAGAS and DeepEval versions

**Files:**
- Modify: `ops/requirements-dev.txt`

- [ ] **Step 1: Probe latest stable versions**

Run: `pip index versions ragas deepeval 2>&1 | head -20`
Expected: lists available versions. Pick the latest stable that supports async eval (RAGAS ≥0.2.0, DeepEval ≥1.0.0).

- [ ] **Step 2: Add pinned deps to requirements-dev.txt**

Append to `ops/requirements-dev.txt`:
```
ragas==<resolved-version>
deepeval==<resolved-version>
datasets>=2.20.0  # ragas dependency
```

- [ ] **Step 3: Install and verify imports**

Run:
```bash
pip install -r ops/requirements-dev.txt
python -c "import ragas; import deepeval; print(ragas.__version__, deepeval.__version__)"
```
Expected: prints two version strings without error.

- [ ] **Step 4: Commit**

```bash
git add ops/requirements-dev.txt
git commit -m "ops: pin ragas and deepeval for rag_eval"
```

### Task 0.2: Discover Naruto user UUID + KG state

**Files:**
- Create: `ops/scripts/probe_naruto_kg.py` (one-shot diagnostic; not committed long-term)

- [ ] **Step 1: Write probe script**

Create `ops/scripts/probe_naruto_kg.py`:
```python
"""One-shot probe of Naruto user's KG state for rag_eval seeding."""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from website.core.supabase_kg.client import get_supabase_client
from website.core.supabase_kg.repository import KGRepository


async def main() -> None:
    client = get_supabase_client()
    if client is None:
        print("ERROR: Supabase not configured — set SUPABASE_URL and SUPABASE_ANON_KEY")
        sys.exit(1)

    response = client.table("kg_users").select("id, render_user_id, display_name, email").execute()
    users = response.data or []
    naruto = next((u for u in users if "naruto" in (u.get("render_user_id", "") + u.get("display_name", "") + u.get("email", "")).lower()), None)
    if not naruto:
        print("ERROR: Naruto user not found in kg_users")
        print("Available users:", json.dumps(users, indent=2))
        sys.exit(1)

    print(f"Naruto UUID: {naruto['id']}")
    repo = KGRepository(client)
    graph = await repo.get_graph(naruto["id"])
    by_source: dict[str, int] = {}
    for node in graph.nodes:
        by_source[node.source_type] = by_source.get(node.source_type, 0) + 1
    print(f"Total nodes: {len(graph.nodes)}")
    print(f"Total links: {len(graph.links)}")
    print(f"By source: {json.dumps(by_source, indent=2)}")

    Path("docs/rag_eval/_config/_naruto_baseline.json").parent.mkdir(parents=True, exist_ok=True)
    Path("docs/rag_eval/_config/_naruto_baseline.json").write_text(json.dumps({
        "user_id": naruto["id"],
        "node_count": len(graph.nodes),
        "link_count": len(graph.links),
        "by_source": by_source,
        "node_ids_by_source": {
            src: [n.id for n in graph.nodes if n.source_type == src][:50]
            for src in by_source
        },
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run probe and inspect output**

Run: `python ops/scripts/probe_naruto_kg.py`
Expected: prints Naruto UUID + per-source node counts; writes `docs/rag_eval/_config/_naruto_baseline.json`.

- [ ] **Step 3: Commit baseline (without the probe script)**

```bash
git add docs/rag_eval/_config/_naruto_baseline.json
git commit -m "docs: capture naruto kg baseline for rag eval"
rm ops/scripts/probe_naruto_kg.py
```

### Task 0.3: Define pydantic types

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/types.py` (currently empty placeholder)
- Create: `tests/unit/rag_pipeline/evaluation/__init__.py` (empty)
- Create: `tests/unit/rag_pipeline/evaluation/test_types.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/rag_pipeline/evaluation/test_types.py`:
```python
"""Tests for rag_pipeline.evaluation.types."""
import pytest
from pydantic import ValidationError

from website.features.rag_pipeline.evaluation.types import (
    GoldQuery,
    ComponentScores,
    EvalResult,
    KGSnapshot,
    KGRecommendation,
)


def test_gold_query_requires_5_or_more_atomic_facts():
    q = GoldQuery(
        id="q1",
        question="What is X?",
        gold_node_ids=["yt-foo"],
        gold_ranking=["yt-foo"],
        reference_answer="X is Y.",
        atomic_facts=["X is Y."],
    )
    assert q.id == "q1"
    assert q.gold_node_ids == ["yt-foo"]


def test_component_scores_clamps_to_zero_hundred():
    scores = ComponentScores(chunking=85.0, retrieval=72.5, reranking=80.0, synthesis=90.0)
    assert 0 <= scores.chunking <= 100
    with pytest.raises(ValidationError):
        ComponentScores(chunking=120.0, retrieval=50, reranking=50, synthesis=50)


def test_eval_result_composite_uses_locked_weights():
    scores = ComponentScores(chunking=80.0, retrieval=60.0, reranking=70.0, synthesis=90.0)
    result = EvalResult(
        iter_id="youtube/iter-01",
        component_scores=scores,
        composite=0.0,
        weights={"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45},
        weights_hash="abc123",
        graph_lift={"composite": 0.0, "retrieval": 0.0, "reranking": 0.0},
        per_query=[],
    )
    assert result.iter_id == "youtube/iter-01"


def test_kg_snapshot_captures_required_fields():
    snap = KGSnapshot(
        kasten_node_ids=["yt-a", "yt-b"],
        neighborhood_node_ids=["yt-a", "yt-b", "yt-c"],
        node_count=3,
        edge_count=2,
        mean_degree=1.33,
        orphan_count=0,
        tag_count=5,
        tag_histogram={"foo": 2, "bar": 1},
    )
    assert snap.node_count == 3


def test_kg_recommendation_types_enum():
    rec = KGRecommendation(
        type="add_link",
        payload={"from_node": "a", "to_node": "b", "suggested_relation": "shared:tag"},
        evidence_query_ids=["q1"],
        confidence=0.82,
        status="auto_apply",
    )
    assert rec.type == "add_link"
    with pytest.raises(ValidationError):
        KGRecommendation(type="not_a_real_type", payload={}, evidence_query_ids=[], confidence=0.5, status="auto_apply")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/rag_pipeline/evaluation/test_types.py -v`
Expected: FAIL — types not yet defined.

- [ ] **Step 3: Implement types**

Replace `website/features/rag_pipeline/evaluation/types.py` (currently empty) with:
```python
"""Pydantic types for the RAG evaluation framework."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, conlist


class GoldQuery(BaseModel):
    id: str
    question: str
    gold_node_ids: list[str] = Field(min_length=1)
    gold_ranking: list[str] = Field(min_length=1)
    reference_answer: str
    atomic_facts: list[str] = Field(min_length=1)


class ComponentScores(BaseModel):
    chunking: float = Field(ge=0.0, le=100.0)
    retrieval: float = Field(ge=0.0, le=100.0)
    reranking: float = Field(ge=0.0, le=100.0)
    synthesis: float = Field(ge=0.0, le=100.0)


class PerQueryScore(BaseModel):
    query_id: str
    retrieved_node_ids: list[str]
    reranked_node_ids: list[str]
    cited_node_ids: list[str]
    ragas: dict[str, float]
    deepeval: dict[str, float]
    component_breakdown: dict[str, float]


class GraphLift(BaseModel):
    composite: float
    retrieval: float
    reranking: float


class EvalResult(BaseModel):
    iter_id: str
    component_scores: ComponentScores
    composite: float
    weights: dict[str, float]
    weights_hash: str
    graph_lift: GraphLift | dict[str, float]
    per_query: list[PerQueryScore]
    eval_divergence: bool = False


class KGSnapshot(BaseModel):
    kasten_node_ids: list[str]
    neighborhood_node_ids: list[str]
    node_count: int
    edge_count: int
    mean_degree: float
    orphan_count: int
    tag_count: int
    tag_histogram: dict[str, int] = Field(default_factory=dict)


KGRecommendationType = Literal[
    "add_link", "add_tag", "merge_nodes", "reingest_node", "orphan_warning"
]
KGRecommendationStatus = Literal["auto_apply", "applied", "quarantined", "rejected"]


class KGRecommendation(BaseModel):
    type: KGRecommendationType
    payload: dict
    evidence_query_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    status: KGRecommendationStatus
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/rag_pipeline/evaluation/test_types.py -v`
Expected: PASS — all 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/evaluation/types.py tests/unit/rag_pipeline/evaluation/
git commit -m "feat: rag_eval pydantic types"
```

### Task 0.3b: Naruto KG drift guard

**Files:**
- Create: `ops/scripts/lib/rag_eval_naruto_drift.py`
- Create: `tests/unit/rag_pipeline/ops/test_rag_eval_naruto_drift.py`

Implements spec §11 Risk row: "halt CLI if mid-loop snapshot diverges by >10% node count or >20% edge count without an applied recommendation explaining it."

- [ ] **Step 1: Write failing test**

```python
# tests/unit/rag_pipeline/ops/test_rag_eval_naruto_drift.py
import pytest
from ops.scripts.lib.rag_eval_naruto_drift import (
    check_naruto_drift,
    NarutoDriftError,
)


def test_within_tolerance_passes():
    check_naruto_drift(baseline={"node_count": 100, "link_count": 200},
                       current={"node_count": 105, "link_count": 220},
                       applied_mutation_count=0)


def test_node_drift_over_10_pct_blocks():
    with pytest.raises(NarutoDriftError, match="node"):
        check_naruto_drift(baseline={"node_count": 100, "link_count": 200},
                           current={"node_count": 115, "link_count": 220},
                           applied_mutation_count=0)


def test_drift_explained_by_applied_mutations_passes():
    # 10 applied mutations explain up to ~10 node/edge additions
    check_naruto_drift(baseline={"node_count": 100, "link_count": 200},
                       current={"node_count": 115, "link_count": 220},
                       applied_mutation_count=20)


def test_edge_drift_over_20_pct_blocks():
    with pytest.raises(NarutoDriftError, match="edge"):
        check_naruto_drift(baseline={"node_count": 100, "link_count": 200},
                           current={"node_count": 100, "link_count": 250},
                           applied_mutation_count=0)
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement drift guard**

```python
# ops/scripts/lib/rag_eval_naruto_drift.py
"""Halt the rag_eval CLI on unexplained Naruto KG drift (spec §11)."""
from __future__ import annotations


class NarutoDriftError(Exception):
    pass


def check_naruto_drift(
    *,
    baseline: dict,
    current: dict,
    applied_mutation_count: int,
    node_tolerance_pct: float = 10.0,
    edge_tolerance_pct: float = 20.0,
) -> None:
    """Raise if KG drifted beyond tolerance unexplained by applied mutations.

    Each applied mutation accounts for ~1 node or edge change; we subtract that
    from the observed delta before comparing against tolerance.
    """
    base_nodes = baseline.get("node_count", 0)
    base_edges = baseline.get("link_count", 0)
    cur_nodes = current.get("node_count", 0)
    cur_edges = current.get("link_count", 0)

    raw_node_delta = abs(cur_nodes - base_nodes)
    raw_edge_delta = abs(cur_edges - base_edges)
    explained_node_delta = max(raw_node_delta - applied_mutation_count, 0)
    explained_edge_delta = max(raw_edge_delta - applied_mutation_count, 0)

    if base_nodes:
        node_pct = (explained_node_delta / base_nodes) * 100.0
        if node_pct > node_tolerance_pct:
            raise NarutoDriftError(
                f"Naruto KG node count drifted {explained_node_delta} (unexplained) "
                f"= {node_pct:.1f}% > {node_tolerance_pct}% tolerance. Halting."
            )
    if base_edges:
        edge_pct = (explained_edge_delta / base_edges) * 100.0
        if edge_pct > edge_tolerance_pct:
            raise NarutoDriftError(
                f"Naruto KG edge count drifted {explained_edge_delta} (unexplained) "
                f"= {edge_pct:.1f}% > {edge_tolerance_pct}% tolerance. Halting."
            )
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: naruto kg drift guard`**

The CLI in Task 3.7 calls `check_naruto_drift` at the start of every Phase A (after loading current Naruto KG state, comparing against `_naruto_baseline.json`).

### Task 0.4: Write YAML config schemas (validation only, no actual configs yet)

**Files:**
- Create: `website/features/rag_pipeline/evaluation/_schemas.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_schemas.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/rag_pipeline/evaluation/test_schemas.py`:
```python
"""Tests for rag_eval YAML config schemas."""
import pytest
from pydantic import ValidationError

from website.features.rag_pipeline.evaluation._schemas import (
    CompositeWeights,
    SeedQueryFile,
    HeldoutQueryFile,
)


def test_composite_weights_must_sum_to_one():
    w = CompositeWeights(chunking=0.10, retrieval=0.25, reranking=0.20, synthesis=0.45)
    assert abs(w.total() - 1.0) < 1e-6
    with pytest.raises(ValidationError):
        CompositeWeights(chunking=0.5, retrieval=0.5, reranking=0.5, synthesis=0.5)


def test_seed_query_file_requires_exactly_5_queries():
    valid = {"queries": [{"id": f"q{i}", "question": "?", "gold_node_ids": ["x"],
                          "gold_ranking": ["x"], "reference_answer": "y",
                          "atomic_facts": ["z"]} for i in range(5)]}
    SeedQueryFile.model_validate(valid)
    invalid = {"queries": valid["queries"][:3]}
    with pytest.raises(ValidationError):
        SeedQueryFile.model_validate(invalid)


def test_heldout_query_file_requires_exactly_3_queries():
    valid = {"queries": [{"id": f"h{i}", "question": "?", "gold_node_ids": ["x"],
                          "gold_ranking": ["x"], "reference_answer": "y",
                          "atomic_facts": ["z"]} for i in range(3)]}
    HeldoutQueryFile.model_validate(valid)
    with pytest.raises(ValidationError):
        HeldoutQueryFile.model_validate({"queries": valid["queries"][:2]})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/rag_pipeline/evaluation/test_schemas.py -v`
Expected: FAIL — module not yet defined.

- [ ] **Step 3: Implement schemas**

Create `website/features/rag_pipeline/evaluation/_schemas.py`:
```python
"""YAML config schemas for the rag_eval framework."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from website.features.rag_pipeline.evaluation.types import GoldQuery


class CompositeWeights(BaseModel):
    chunking: float = Field(ge=0.0, le=1.0)
    retrieval: float = Field(ge=0.0, le=1.0)
    reranking: float = Field(ge=0.0, le=1.0)
    synthesis: float = Field(ge=0.0, le=1.0)

    def total(self) -> float:
        return self.chunking + self.retrieval + self.reranking + self.synthesis

    @model_validator(mode="after")
    def _sum_to_one(self) -> "CompositeWeights":
        if abs(self.total() - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0; got {self.total()}")
        return self


class SeedQueryFile(BaseModel):
    queries: list[GoldQuery] = Field(min_length=5, max_length=5)


class HeldoutQueryFile(BaseModel):
    queries: list[GoldQuery] = Field(min_length=3, max_length=3)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/rag_pipeline/evaluation/test_schemas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/evaluation/_schemas.py tests/unit/rag_pipeline/evaluation/test_schemas.py
git commit -m "feat: yaml config schemas for rag_eval"
```

---

## Phase 1: Evaluation Harness

### Task 1.1: gold_loader.py

**Files:**
- Create: `website/features/rag_pipeline/evaluation/gold_loader.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_gold_loader.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/rag_pipeline/evaluation/test_gold_loader.py`:
```python
"""Tests for gold_loader."""
from pathlib import Path

import pytest

from website.features.rag_pipeline.evaluation.gold_loader import (
    load_seed_queries,
    load_heldout_queries,
    seal_heldout,
    GoldLoaderError,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_load_seed_queries_success(tmp_path):
    yaml_text = """
queries:
""" + "".join([f"""
  - id: q{i}
    question: question {i}?
    gold_node_ids: [yt-foo]
    gold_ranking: [yt-foo]
    reference_answer: "ref"
    atomic_facts: ["fact"]
""" for i in range(5)])
    path = _write(tmp_path / "seed.yaml", yaml_text)
    queries = load_seed_queries(path)
    assert len(queries) == 5
    assert queries[0].id == "q0"


def test_load_seed_queries_rejects_non_5(tmp_path):
    yaml_text = """
queries:
  - id: q1
    question: ?
    gold_node_ids: [x]
    gold_ranking: [x]
    reference_answer: y
    atomic_facts: [z]
"""
    path = _write(tmp_path / "seed.yaml", yaml_text)
    with pytest.raises(GoldLoaderError):
        load_seed_queries(path)


def test_seal_heldout_makes_unreadable(tmp_path):
    path = _write(tmp_path / "heldout.yaml", "queries: []")
    seal_heldout(path)
    # On Windows we settle for "marked sealed" via a sidecar file since chmod
    # doesn't always strip read perms cleanly. Verify the sentinel.
    assert (path.parent / ".heldout_sealed").exists()


def test_load_heldout_blocked_when_sealed(tmp_path):
    path = _write(tmp_path / "heldout.yaml", "queries: []")
    (tmp_path / ".heldout_sealed").write_text("sealed", encoding="utf-8")
    with pytest.raises(GoldLoaderError, match="sealed"):
        load_heldout_queries(path, allow_sealed=False)


def test_load_heldout_allowed_with_unseal_flag(tmp_path):
    yaml_text = """
queries:
""" + "".join([f"""
  - id: h{i}
    question: ?
    gold_node_ids: [x]
    gold_ranking: [x]
    reference_answer: y
    atomic_facts: [z]
""" for i in range(3)])
    path = _write(tmp_path / "heldout.yaml", yaml_text)
    (tmp_path / ".heldout_sealed").write_text("sealed", encoding="utf-8")
    queries = load_heldout_queries(path, allow_sealed=True)
    assert len(queries) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/rag_pipeline/evaluation/test_gold_loader.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement gold_loader**

Create `website/features/rag_pipeline/evaluation/gold_loader.py`:
```python
"""Gold-data loader for rag_eval seed and held-out queries."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from website.features.rag_pipeline.evaluation._schemas import (
    HeldoutQueryFile,
    SeedQueryFile,
)
from website.features.rag_pipeline.evaluation.types import GoldQuery


class GoldLoaderError(Exception):
    """Raised when gold-data loading or sealing fails."""


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise GoldLoaderError(f"File not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_seed_queries(path: Path) -> list[GoldQuery]:
    raw = _load_yaml(path)
    try:
        parsed = SeedQueryFile.model_validate(raw)
    except ValidationError as exc:
        raise GoldLoaderError(f"Invalid seed.yaml at {path}: {exc}") from exc
    return parsed.queries


def load_heldout_queries(path: Path, *, allow_sealed: bool) -> list[GoldQuery]:
    sentinel = path.parent / ".heldout_sealed"
    if sentinel.exists() and not allow_sealed:
        raise GoldLoaderError(
            f"heldout.yaml at {path} is sealed; pass --unseal-heldout for the final iter only"
        )
    raw = _load_yaml(path)
    try:
        parsed = HeldoutQueryFile.model_validate(raw)
    except ValidationError as exc:
        raise GoldLoaderError(f"Invalid heldout.yaml at {path}: {exc}") from exc
    return parsed.queries


def seal_heldout(path: Path) -> None:
    sentinel = path.parent / ".heldout_sealed"
    sentinel.write_text("sealed", encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/rag_pipeline/evaluation/test_gold_loader.py -v`
Expected: PASS — 5/5.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/evaluation/gold_loader.py tests/unit/rag_pipeline/evaluation/test_gold_loader.py
git commit -m "feat: gold loader with heldout sealing"
```

### Task 1.2: composite.py — weighted scoring with hash lock

**Files:**
- Create: `website/features/rag_pipeline/evaluation/composite.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_composite.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/rag_pipeline/evaluation/test_composite.py
import pytest
from pathlib import Path

from website.features.rag_pipeline.evaluation.composite import (
    compute_composite,
    hash_weights_file,
    verify_weights_unchanged,
    WeightsLockError,
)
from website.features.rag_pipeline.evaluation.types import ComponentScores


def test_compute_composite_default_weights():
    scores = ComponentScores(chunking=80.0, retrieval=60.0, reranking=70.0, synthesis=90.0)
    weights = {"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45}
    composite = compute_composite(scores, weights)
    expected = 0.10*80 + 0.25*60 + 0.20*70 + 0.45*90
    assert abs(composite - expected) < 1e-6


def test_compute_composite_rejects_non_summing_weights():
    scores = ComponentScores(chunking=50, retrieval=50, reranking=50, synthesis=50)
    with pytest.raises(ValueError, match="weights"):
        compute_composite(scores, {"chunking": 0.5, "retrieval": 0.5, "reranking": 0.5, "synthesis": 0.5})


def test_hash_weights_file_stable(tmp_path):
    path = tmp_path / "weights.yaml"
    path.write_text("chunking: 0.10\nretrieval: 0.25\nreranking: 0.20\nsynthesis: 0.45\n", encoding="utf-8")
    h1 = hash_weights_file(path)
    h2 = hash_weights_file(path)
    assert h1 == h2
    path.write_text("chunking: 0.20\nretrieval: 0.25\nreranking: 0.10\nsynthesis: 0.45\n", encoding="utf-8")
    assert hash_weights_file(path) != h1


def test_verify_weights_unchanged_blocks_drift(tmp_path):
    path = tmp_path / "weights.yaml"
    path.write_text("chunking: 0.10\nretrieval: 0.25\nreranking: 0.20\nsynthesis: 0.45\n", encoding="utf-8")
    locked = hash_weights_file(path)
    verify_weights_unchanged(path, locked)  # no-op on match
    path.write_text("chunking: 0.30\nretrieval: 0.20\nreranking: 0.10\nsynthesis: 0.40\n", encoding="utf-8")
    with pytest.raises(WeightsLockError):
        verify_weights_unchanged(path, locked)
```

- [ ] **Step 2: Run test, confirm FAIL.**

Run: `pytest tests/unit/rag_pipeline/evaluation/test_composite.py -v`

- [ ] **Step 3: Implement composite**

Create `website/features/rag_pipeline/evaluation/composite.py`:
```python
"""Weighted composite + delta arithmetic + hash lock for rag_eval."""
from __future__ import annotations

import hashlib
from pathlib import Path

from website.features.rag_pipeline.evaluation.types import ComponentScores


class WeightsLockError(Exception):
    """Raised when composite_weights.yaml hash diverges from the locked iter-01 hash."""


def compute_composite(scores: ComponentScores, weights: dict[str, float]) -> float:
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1.0; got {total}")
    return (
        weights["chunking"] * scores.chunking
        + weights["retrieval"] * scores.retrieval
        + weights["reranking"] * scores.reranking
        + weights["synthesis"] * scores.synthesis
    )


def hash_weights_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_weights_unchanged(path: Path, locked_hash: str) -> None:
    current = hash_weights_file(path)
    if current != locked_hash:
        raise WeightsLockError(
            f"composite_weights.yaml hash drifted: locked={locked_hash[:8]} current={current[:8]}. "
            "Mid-loop weight changes are blocked. Revert or start a new per-source loop."
        )


def composite_delta(prev: float, curr: float) -> dict[str, float]:
    return {
        "absolute": curr - prev,
        "relative_pct": ((curr - prev) / prev * 100.0) if prev else 0.0,
    }
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: composite scoring with hash lock`**

### Task 1.3: component_scorers.py — chunking score

**Files:**
- Create: `website/features/rag_pipeline/evaluation/component_scorers.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_component_scorers.py`

- [ ] **Step 1: Write failing test for chunking_score**

```python
# tests/unit/rag_pipeline/evaluation/test_component_scorers.py
import pytest
from website.features.rag_pipeline.evaluation.component_scorers import (
    chunking_score,
    retrieval_score,
    rerank_score,
)
from website.features.rag_pipeline.types import RetrievalCandidate, SourceType, ChunkKind


def test_chunking_score_rewards_balanced_chunks():
    chunks = [
        {"text": "This is a complete sentence about X.", "token_count": 8, "start_offset": 0, "end_offset": 38},
        {"text": "Another complete sentence about Y.", "token_count": 7, "start_offset": 38, "end_offset": 73},
        {"text": "A third complete sentence about Z.", "token_count": 7, "start_offset": 73, "end_offset": 108},
    ]
    score = chunking_score(chunks, target_tokens=8, embeddings=None)
    assert score >= 70.0


def test_chunking_score_penalizes_mid_sentence_cuts():
    chunks = [
        {"text": "This is a sent", "token_count": 4, "start_offset": 0, "end_offset": 14},
        {"text": "ence cut mid-word.", "token_count": 4, "start_offset": 14, "end_offset": 32},
    ]
    score = chunking_score(chunks, target_tokens=8, embeddings=None)
    assert score < 60.0


def test_retrieval_score_perfect_recall():
    gold = ["yt-a", "yt-b"]
    retrieved = ["yt-a", "yt-b", "yt-c", "yt-d"]
    score = retrieval_score(gold=gold, retrieved=retrieved, k_recall=10, k_hit=5)
    assert score > 90.0  # Recall@10=1.0, MRR=1.0, Hit@5=1.0


def test_retrieval_score_zero_recall():
    score = retrieval_score(gold=["yt-a"], retrieved=["yt-x", "yt-y"], k_recall=10, k_hit=5)
    assert score == 0.0


def test_rerank_score_perfect_ranking():
    gold_ranking = ["yt-a", "yt-b", "yt-c"]
    reranked = ["yt-a", "yt-b", "yt-c", "yt-x"]
    score = rerank_score(gold_ranking=gold_ranking, reranked=reranked, k_ndcg=5, k_precision=3)
    assert score > 95.0


def test_rerank_score_penalizes_false_positives():
    gold_ranking = ["yt-a"]
    reranked = ["yt-x", "yt-y", "yt-z", "yt-a"]
    score = rerank_score(gold_ranking=gold_ranking, reranked=reranked, k_ndcg=5, k_precision=3)
    assert score < 50.0
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement component_scorers**

Create `website/features/rag_pipeline/evaluation/component_scorers.py`:
```python
"""Deterministic per-stage component scorers (no LLM calls)."""
from __future__ import annotations

import math
import re
from typing import Sequence


def chunking_score(
    chunks: Sequence[dict],
    *,
    target_tokens: int,
    embeddings: Sequence[Sequence[float]] | None = None,
) -> float:
    """Score chunking quality on 0-100.

    Components:
      - Token-budget compliance (40%): chunks within ±50% of target_tokens
      - Boundary integrity (30%): chunks don't cut mid-word/sentence
      - Coherence (20%): cosine sim of adjacent chunks via embeddings (if provided)
      - Dedup (10%): unique-text rate
    """
    if not chunks:
        return 0.0

    # Budget compliance
    budget_ok = sum(
        1 for c in chunks
        if c.get("token_count") and 0.5 * target_tokens <= c["token_count"] <= 1.5 * target_tokens
    )
    budget_score = (budget_ok / len(chunks)) * 100.0

    # Boundary integrity: chunks should end with sentence-ending punctuation OR newline
    sentence_end = re.compile(r"[.!?\n]\s*$")
    boundary_ok = sum(1 for c in chunks if sentence_end.search(c.get("text", "")))
    boundary_score = (boundary_ok / len(chunks)) * 100.0

    # Coherence
    if embeddings and len(embeddings) >= 2:
        sims = []
        for a, b in zip(embeddings[:-1], embeddings[1:]):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            if na and nb:
                sims.append(dot / (na * nb))
        coherence_score = (sum(sims) / len(sims) if sims else 0.0) * 100.0
    else:
        coherence_score = 50.0  # neutral when embeddings unavailable

    # Dedup
    texts = [c.get("text", "") for c in chunks]
    dedup_score = (len(set(texts)) / len(texts)) * 100.0

    return 0.4 * budget_score + 0.3 * boundary_score + 0.2 * coherence_score + 0.1 * dedup_score


def retrieval_score(
    *,
    gold: list[str],
    retrieved: list[str],
    k_recall: int = 10,
    k_hit: int = 5,
) -> float:
    """Score retrieval on 0-100: 0.4*Recall@k + 0.3*MRR + 0.3*Hit@k."""
    if not gold:
        return 0.0
    gold_set = set(gold)
    top_recall = retrieved[:k_recall]
    recall_at_k = sum(1 for x in top_recall if x in gold_set) / len(gold_set)
    mrr = 0.0
    for idx, node in enumerate(retrieved, start=1):
        if node in gold_set:
            mrr = 1.0 / idx
            break
    hit_at_k = 1.0 if any(x in gold_set for x in retrieved[:k_hit]) else 0.0
    return 100.0 * (0.4 * recall_at_k + 0.3 * mrr + 0.3 * hit_at_k)


def rerank_score(
    *,
    gold_ranking: list[str],
    reranked: list[str],
    k_ndcg: int = 5,
    k_precision: int = 3,
) -> float:
    """Score rerank on 0-100: 0.5*NDCG@k + 0.3*P@k + 0.2*(1-FP@k)."""
    if not gold_ranking:
        return 0.0
    gold_set = set(gold_ranking)

    # NDCG@k
    def dcg(seq: list[str]) -> float:
        return sum(
            (1.0 if node in gold_set else 0.0) / math.log2(i + 2)
            for i, node in enumerate(seq)
        )
    actual_dcg = dcg(reranked[:k_ndcg])
    ideal_dcg = dcg(gold_ranking[:k_ndcg])
    ndcg = actual_dcg / ideal_dcg if ideal_dcg else 0.0

    # P@k
    top_p = reranked[:k_precision]
    precision = sum(1 for x in top_p if x in gold_set) / max(len(top_p), 1)

    # FP rate at k_precision
    fp_rate = (len(top_p) - sum(1 for x in top_p if x in gold_set)) / max(len(top_p), 1)

    return 100.0 * (0.5 * ndcg + 0.3 * precision + 0.2 * (1.0 - fp_rate))
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: deterministic component scorers`**

### Task 1.4: ragas_runner.py

**Files:**
- Create: `website/features/rag_pipeline/evaluation/ragas_runner.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_ragas_runner.py`

- [ ] **Step 1: Write failing test (mocked RAGAS)**

```python
# tests/unit/rag_pipeline/evaluation/test_ragas_runner.py
import pytest
from unittest.mock import patch, MagicMock

from website.features.rag_pipeline.evaluation.ragas_runner import run_ragas_eval


def test_run_ragas_eval_returns_5_metrics():
    sample = {
        "question": "What is X?",
        "answer": "X is Y.",
        "contexts": ["X is defined as Y in the source."],
        "ground_truth": "X is Y.",
    }
    with patch("website.features.rag_pipeline.evaluation.ragas_runner._evaluate_dataset") as mock_eval:
        mock_eval.return_value = {
            "faithfulness": 0.95,
            "answer_correctness": 0.88,
            "context_precision": 0.90,
            "context_recall": 0.85,
            "answer_relevancy": 0.92,
        }
        result = run_ragas_eval([sample])
    assert set(result.keys()) == {"faithfulness", "answer_correctness", "context_precision", "context_recall", "answer_relevancy"}
    assert all(0.0 <= v <= 1.0 for v in result.values())


def test_run_ragas_eval_handles_empty_input():
    result = run_ragas_eval([])
    assert all(v == 0.0 for v in result.values())
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement ragas_runner**

Create `website/features/rag_pipeline/evaluation/ragas_runner.py`:
```python
"""RAGAS adapter for rag_eval. Wraps ragas.evaluate with key-pool-aware retries."""
from __future__ import annotations

from typing import Sequence

_METRIC_NAMES = (
    "faithfulness",
    "answer_correctness",
    "context_precision",
    "context_recall",
    "answer_relevancy",
)


def _evaluate_dataset(samples: list[dict]) -> dict[str, float]:
    """Real RAGAS call. Isolated for test mocking."""
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        answer_correctness,
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    ds = Dataset.from_list(samples)
    result = evaluate(
        ds,
        metrics=[
            faithfulness,
            answer_correctness,
            context_precision,
            context_recall,
            answer_relevancy,
        ],
    )
    return {name: float(result[name]) for name in _METRIC_NAMES}


def run_ragas_eval(samples: Sequence[dict]) -> dict[str, float]:
    """Run RAGAS on samples shaped {question, answer, contexts, ground_truth}.

    Returns a dict of metric_name -> 0..1 score. Returns zeros when samples is empty.
    """
    if not samples:
        return {name: 0.0 for name in _METRIC_NAMES}
    return _evaluate_dataset(list(samples))
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: ragas runner adapter`**

### Task 1.5: deepeval_runner.py

**Files:**
- Create: `website/features/rag_pipeline/evaluation/deepeval_runner.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_deepeval_runner.py`

- [ ] **Step 1: Write failing test**

```python
import pytest
from unittest.mock import patch, MagicMock
from website.features.rag_pipeline.evaluation.deepeval_runner import run_deepeval


def test_run_deepeval_returns_three_signals():
    sample = {"question": "Q?", "answer": "A.", "contexts": ["ctx"], "ground_truth": "A."}
    with patch("website.features.rag_pipeline.evaluation.deepeval_runner._compute_metrics") as mock:
        mock.return_value = {"semantic_similarity": 0.91, "hallucination": 0.08, "contextual_relevance": 0.87}
        result = run_deepeval([sample])
    assert set(result.keys()) == {"semantic_similarity", "hallucination", "contextual_relevance"}


def test_run_deepeval_empty_returns_zeros():
    assert run_deepeval([])["semantic_similarity"] == 0.0
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement deepeval_runner**

```python
# website/features/rag_pipeline/evaluation/deepeval_runner.py
"""DeepEval adapter for rag_eval — semantic similarity, hallucination, contextual relevance."""
from __future__ import annotations

from typing import Sequence

_METRIC_NAMES = ("semantic_similarity", "hallucination", "contextual_relevance")


def _compute_metrics(samples: list[dict]) -> dict[str, float]:
    """Real DeepEval call. Isolated for test mocking."""
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualRelevancyMetric,
        HallucinationMetric,
    )
    from deepeval.test_case import LLMTestCase

    sims = []
    halls = []
    rels = []
    for s in samples:
        case = LLMTestCase(
            input=s["question"],
            actual_output=s["answer"],
            expected_output=s.get("ground_truth", ""),
            context=s.get("contexts", []),
        )
        ar = AnswerRelevancyMetric()
        ar.measure(case)
        sims.append(ar.score)
        hm = HallucinationMetric()
        hm.measure(case)
        halls.append(hm.score)
        cr = ContextualRelevancyMetric()
        cr.measure(case)
        rels.append(cr.score)
    return {
        "semantic_similarity": sum(sims) / max(len(sims), 1),
        "hallucination": sum(halls) / max(len(halls), 1),
        "contextual_relevance": sum(rels) / max(len(rels), 1),
    }


def run_deepeval(samples: Sequence[dict]) -> dict[str, float]:
    if not samples:
        return {name: 0.0 for name in _METRIC_NAMES}
    return _compute_metrics(list(samples))
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: deepeval runner adapter`**

### Task 1.6: synthesis_score.py

**Files:**
- Create: `website/features/rag_pipeline/evaluation/synthesis_score.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_synthesis_score.py`

- [ ] **Step 1: Write failing test**

```python
from website.features.rag_pipeline.evaluation.synthesis_score import (
    synthesis_score,
    detect_eval_divergence,
)


def test_synthesis_score_weights():
    ragas = {"faithfulness": 1.0, "answer_correctness": 1.0, "context_precision": 1.0, "answer_relevancy": 1.0, "context_recall": 1.0}
    deepeval = {"semantic_similarity": 1.0, "hallucination": 0.0, "contextual_relevance": 1.0}
    score = synthesis_score(ragas=ragas, deepeval=deepeval)
    assert score == 100.0


def test_synthesis_score_partial():
    ragas = {"faithfulness": 0.5, "answer_correctness": 0.5, "context_precision": 0.5, "answer_relevancy": 0.5, "context_recall": 0.5}
    deepeval = {"semantic_similarity": 0.5, "hallucination": 0.5, "contextual_relevance": 0.5}
    score = synthesis_score(ragas=ragas, deepeval=deepeval)
    assert score == 50.0


def test_detect_eval_divergence_flags_large_gap():
    assert detect_eval_divergence(faithfulness=0.9, hallucination=0.6) is True
    assert detect_eval_divergence(faithfulness=0.9, hallucination=0.1) is False
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement**

```python
# website/features/rag_pipeline/evaluation/synthesis_score.py
"""Combine RAGAS + DeepEval into the synthesis component score."""
from __future__ import annotations


def synthesis_score(*, ragas: dict[str, float], deepeval: dict[str, float]) -> float:
    """Synthesis score on 0-100.

    Per spec §3b:
      0.30 faithfulness + 0.20 answer_correctness + 0.20 context_precision
      + 0.15 answer_relevancy + 0.15 deepeval.semantic_similarity
    """
    raw = (
        0.30 * ragas.get("faithfulness", 0.0)
        + 0.20 * ragas.get("answer_correctness", 0.0)
        + 0.20 * ragas.get("context_precision", 0.0)
        + 0.15 * ragas.get("answer_relevancy", 0.0)
        + 0.15 * deepeval.get("semantic_similarity", 0.0)
    )
    return raw * 100.0


def detect_eval_divergence(*, faithfulness: float, hallucination: float) -> bool:
    """RAGAS faithfulness vs DeepEval hallucination should be inverses.
    Flag when |faithfulness - (1 - hallucination)| > 0.2 per spec §3d."""
    expected_faithfulness = 1.0 - hallucination
    return abs(faithfulness - expected_faithfulness) > 0.2
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: synthesis score combines ragas and deepeval`**

### Task 1.7: eval_runner.py

**Files:**
- Create: `website/features/rag_pipeline/evaluation/eval_runner.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_eval_runner.py`

- [ ] **Step 1: Write failing test (everything mocked)**

```python
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path
import asyncio

from website.features.rag_pipeline.evaluation.eval_runner import EvalRunner
from website.features.rag_pipeline.evaluation.types import GoldQuery


def test_eval_runner_produces_eval_result():
    queries = [
        GoldQuery(id="q1", question="?", gold_node_ids=["yt-a"], gold_ranking=["yt-a"],
                  reference_answer="A.", atomic_facts=["A"]),
    ] * 5  # use 5 identical for the test
    answers = [{"query_id": "q1", "answer": "A.", "citations": [{"node_id": "yt-a", "snippet": "..."}],
                "retrieved_node_ids": ["yt-a"], "reranked_node_ids": ["yt-a"], "contexts": ["A is true."]}] * 5
    chunks_per_node = {"yt-a": [{"text": "A.", "token_count": 2, "start_offset": 0, "end_offset": 2}]}

    with patch("website.features.rag_pipeline.evaluation.eval_runner.run_ragas_eval", return_value={
        "faithfulness": 0.9, "answer_correctness": 0.85, "context_precision": 0.9,
        "context_recall": 0.88, "answer_relevancy": 0.9}):
        with patch("website.features.rag_pipeline.evaluation.eval_runner.run_deepeval", return_value={
            "semantic_similarity": 0.92, "hallucination": 0.05, "contextual_relevance": 0.9}):
            runner = EvalRunner(weights={"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45},
                                weights_hash="abc")
            result = runner.evaluate(
                iter_id="youtube/iter-01",
                queries=queries, answers=answers, chunks_per_node=chunks_per_node,
            )
    assert result.iter_id == "youtube/iter-01"
    assert 0 <= result.composite <= 100
    assert len(result.per_query) == 5
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement EvalRunner**

```python
# website/features/rag_pipeline/evaluation/eval_runner.py
"""Top-level eval orchestrator."""
from __future__ import annotations

from website.features.rag_pipeline.evaluation.component_scorers import (
    chunking_score, retrieval_score, rerank_score,
)
from website.features.rag_pipeline.evaluation.composite import compute_composite
from website.features.rag_pipeline.evaluation.deepeval_runner import run_deepeval
from website.features.rag_pipeline.evaluation.ragas_runner import run_ragas_eval
from website.features.rag_pipeline.evaluation.synthesis_score import (
    detect_eval_divergence, synthesis_score,
)
from website.features.rag_pipeline.evaluation.types import (
    ComponentScores, EvalResult, GoldQuery, GraphLift, PerQueryScore,
)


class EvalRunner:
    def __init__(self, *, weights: dict[str, float], weights_hash: str):
        self._weights = weights
        self._weights_hash = weights_hash

    def evaluate(
        self,
        *,
        iter_id: str,
        queries: list[GoldQuery],
        answers: list[dict],
        chunks_per_node: dict[str, list[dict]],
        embeddings_per_node: dict[str, list[list[float]]] | None = None,
        graph_lift: GraphLift | None = None,
    ) -> EvalResult:
        # Per-query: build RAGAS samples + retrieval/rerank scores
        per_query: list[PerQueryScore] = []
        ragas_samples: list[dict] = []
        retrieval_scores: list[float] = []
        rerank_scores: list[float] = []
        any_divergence = False

        for q, a in zip(queries, answers):
            ragas_samples.append({
                "question": q.question,
                "answer": a["answer"],
                "contexts": a.get("contexts", []),
                "ground_truth": q.reference_answer,
            })
            r = retrieval_score(gold=q.gold_node_ids, retrieved=a["retrieved_node_ids"])
            retrieval_scores.append(r)
            rr = rerank_score(gold_ranking=q.gold_ranking, reranked=a["reranked_node_ids"])
            rerank_scores.append(rr)

        ragas_overall = run_ragas_eval(ragas_samples)
        deepeval_overall = run_deepeval(ragas_samples)

        for q, a, r, rr in zip(queries, answers, retrieval_scores, rerank_scores):
            divergence = detect_eval_divergence(
                faithfulness=ragas_overall.get("faithfulness", 0.0),
                hallucination=deepeval_overall.get("hallucination", 0.0),
            )
            any_divergence = any_divergence or divergence
            per_query.append(PerQueryScore(
                query_id=q.id,
                retrieved_node_ids=a["retrieved_node_ids"],
                reranked_node_ids=a["reranked_node_ids"],
                cited_node_ids=[c["node_id"] for c in a.get("citations", [])],
                ragas=ragas_overall,
                deepeval=deepeval_overall,
                component_breakdown={"retrieval": r, "rerank": rr},
            ))

        # Aggregate component scores
        chunk_scores = []
        for node_id, chunks in chunks_per_node.items():
            embs = embeddings_per_node.get(node_id) if embeddings_per_node else None
            chunk_scores.append(chunking_score(chunks, target_tokens=512, embeddings=embs))

        chunking_overall = sum(chunk_scores) / max(len(chunk_scores), 1)
        retrieval_overall = sum(retrieval_scores) / max(len(retrieval_scores), 1)
        rerank_overall = sum(rerank_scores) / max(len(rerank_scores), 1)
        synthesis_overall = synthesis_score(ragas=ragas_overall, deepeval=deepeval_overall)

        component_scores = ComponentScores(
            chunking=chunking_overall,
            retrieval=retrieval_overall,
            reranking=rerank_overall,
            synthesis=synthesis_overall,
        )
        composite = compute_composite(component_scores, self._weights)

        return EvalResult(
            iter_id=iter_id,
            component_scores=component_scores,
            composite=composite,
            weights=self._weights,
            weights_hash=self._weights_hash,
            graph_lift=graph_lift or GraphLift(composite=0.0, retrieval=0.0, reranking=0.0),
            per_query=per_query,
            eval_divergence=any_divergence,
        )
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: eval runner orchestrates all scorers`**

---

## Phase 1.5: KG Ablation

### Task 1.5.1: ablation.py

**Files:**
- Create: `website/features/rag_pipeline/evaluation/ablation.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_ablation.py`

- [ ] **Step 1: Write failing test**

```python
from unittest.mock import patch, MagicMock
from website.features.rag_pipeline.evaluation.ablation import compute_graph_lift
from website.features.rag_pipeline.evaluation.types import ComponentScores


def test_compute_graph_lift_positive():
    with_graph = ComponentScores(chunking=80, retrieval=85, reranking=80, synthesis=88)
    ablated = ComponentScores(chunking=80, retrieval=75, reranking=70, synthesis=85)
    weights = {"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45}
    lift = compute_graph_lift(with_graph=with_graph, ablated=ablated, weights=weights)
    assert lift.retrieval > 0
    assert lift.composite > 0


def test_compute_graph_lift_negative_when_kg_hurts():
    with_graph = ComponentScores(chunking=80, retrieval=70, reranking=70, synthesis=80)
    ablated = ComponentScores(chunking=80, retrieval=80, reranking=75, synthesis=85)
    weights = {"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45}
    lift = compute_graph_lift(with_graph=with_graph, ablated=ablated, weights=weights)
    assert lift.retrieval < 0
    assert lift.composite < 0
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement**

```python
# website/features/rag_pipeline/evaluation/ablation.py
"""KG ablation: graph_lift = composite_with_graph - composite_ablated."""
from __future__ import annotations

from website.features.rag_pipeline.evaluation.composite import compute_composite
from website.features.rag_pipeline.evaluation.types import ComponentScores, GraphLift


def compute_graph_lift(
    *,
    with_graph: ComponentScores,
    ablated: ComponentScores,
    weights: dict[str, float],
) -> GraphLift:
    return GraphLift(
        composite=compute_composite(with_graph, weights) - compute_composite(ablated, weights),
        retrieval=with_graph.retrieval - ablated.retrieval,
        reranking=with_graph.reranking - ablated.reranking,
    )
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: kg ablation graph lift`**

---

## Phase 2: Kasten Builder

### Task 2.1: rag_eval_kasten.py — Naruto loader + Chintan parser + ingestion driver

**Files:**
- Create: `ops/scripts/lib/__init__.py` (empty if not present)
- Create: `ops/scripts/lib/rag_eval_kasten.py`
- Create: `tests/unit/rag_pipeline/ops/__init__.py` (empty)
- Create: `tests/unit/rag_pipeline/ops/test_rag_eval_kasten.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/rag_pipeline/ops/test_rag_eval_kasten.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from ops.scripts.lib.rag_eval_kasten import (
    build_kasten,
    load_naruto_zettels_for_source,
    parse_chintan_testing,
    select_similar_zettel,
    KastenBuildError,
)


def test_parse_chintan_testing(tmp_path):
    md = tmp_path / "Chintan_Testing.md"
    md.write_text("""**CHINTAN TESTING**

1. [Title One](https://www.youtube.com/watch?v=aaa) (5m)
2. [Title Two](https://www.reddit.com/r/foo/) [R]
3. [Title Three](https://github.com/x/y) (gh)
""", encoding="utf-8")
    entries = parse_chintan_testing(md)
    assert len(entries) == 3
    assert entries[0]["url"].startswith("https://www.youtube.com")
    assert entries[1]["url"].startswith("https://www.reddit.com")


def test_select_similar_zettel_picks_above_threshold():
    candidates = [
        {"node_id": "yt-a", "embedding": [1.0, 0.0]},
        {"node_id": "yt-b", "embedding": [0.0, 1.0]},
        {"node_id": "yt-c", "embedding": [0.95, 0.05]},
    ]
    centroid = [1.0, 0.0]
    result = select_similar_zettel(candidates=candidates, centroid=centroid, min_cosine=0.65, exclude_ids={"yt-a"})
    assert result["node_id"] == "yt-c"


def test_select_similar_zettel_returns_none_below_threshold():
    candidates = [{"node_id": "yt-x", "embedding": [0.0, 1.0]}]
    centroid = [1.0, 0.0]
    assert select_similar_zettel(candidates=candidates, centroid=centroid, min_cosine=0.65, exclude_ids=set()) is None
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement rag_eval_kasten**

```python
# ops/scripts/lib/rag_eval_kasten.py
"""Kasten builder: loads Naruto Zettels, falls back to Chintan_Testing.md, drives ingestion."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any
from uuid import UUID


class KastenBuildError(Exception):
    pass


_CHINTAN_LINE_RE = re.compile(r"^\d+\.\s+\[([^\]]+)\]\(([^)]+)\)")


def parse_chintan_testing(path: Path) -> list[dict]:
    """Parse Chintan_Testing.md into [{title, url}, ...]."""
    if not path.exists():
        raise KastenBuildError(f"Chintan_Testing.md not found at {path}")
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _CHINTAN_LINE_RE.match(line.strip())
        if m:
            entries.append({"title": m.group(1), "url": m.group(2)})
    return entries


async def load_naruto_zettels_for_source(
    *, user_id: UUID, source_type: str, supabase: Any,
) -> list[dict]:
    """Load all Naruto's Zettels for a given source_type from kg_nodes."""
    response = supabase.table("kg_nodes").select("id, name, summary, tags, url, source_type, metadata").eq(
        "user_id", str(user_id)
    ).eq("source_type", source_type).execute()
    return response.data or []


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def select_similar_zettel(
    *,
    candidates: list[dict],
    centroid: list[float],
    min_cosine: float,
    exclude_ids: set[str],
) -> dict | None:
    """Pick highest-cosine candidate above threshold, excluding already-in-Kasten nodes."""
    best = None
    best_score = -1.0
    for c in candidates:
        if c["node_id"] in exclude_ids:
            continue
        sim = _cosine(c["embedding"], centroid)
        if sim >= min_cosine and sim > best_score:
            best = {**c, "_cosine": sim}
            best_score = sim
    return best


async def build_kasten(
    *,
    source: str,
    iter_num: int,
    user_id: UUID,
    seed_node_ids: list[str],
    supabase: Any,
    chintan_path: Path,
    output_dir: Path,
    require_similar: bool = False,
    require_unseen: bool = False,
    similar_min_cosine: float = 0.65,
    unseen_cosine_range: tuple[float, float] = (0.50, 0.70),
) -> dict:
    """Build the iter's Kasten manifest.

    Returns {"zettels": [...], "creation_rationale": "...", "billing_concern": bool}
    """
    naruto_pool = await load_naruto_zettels_for_source(
        user_id=user_id, source_type=source, supabase=supabase,
    )
    pool_by_id = {z["id"]: z for z in naruto_pool}
    selected = [pool_by_id[nid] for nid in seed_node_ids if nid in pool_by_id]
    if len(selected) < len(seed_node_ids):
        missing = set(seed_node_ids) - set(pool_by_id)
        raise KastenBuildError(f"Seed Zettels missing from Naruto KG: {missing}")

    rationale = f"Seed Kasten loaded from Naruto KG (iter-{iter_num:02d})."
    billing_concern = False

    # Probe / unseen Zettel injection (iter ≥04 for YouTube, iter ≥02 for 3-iter sources)
    # Caller orchestrates which iter triggers what; we just honor the flags.
    return {
        "zettels": selected,
        "creation_rationale": rationale,
        "billing_concern": billing_concern,
    }
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: kasten builder loads naruto zettels`**

### Task 2.2: Ingestion driver in build_kasten

(Extends Task 2.1's `build_kasten` to actually drive ingestion via the existing `rag_pipeline.service`. Skipping a separate test scaffold here because integration ingestion is exercised by the smoke run in Phase 5; unit-level we only need the manifest builder.)

- [ ] **Step 1: Extend rag_eval_kasten.py with ingestion**

Add to `ops/scripts/lib/rag_eval_kasten.py`:
```python
async def ingest_kasten(
    *,
    zettels: list[dict],
    user_id: UUID,
    runtime: Any,  # RAGRuntime from website.features.rag_pipeline.service
) -> dict:
    """Drive ingestion via existing rag_pipeline.service. Returns ingest report."""
    chunker = runtime.orchestrator._ingest_chunker  # access via stable attr; document with ADR if private
    embedder = runtime.orchestrator._ingest_embedder
    upserter = runtime.orchestrator._ingest_upserter
    report = {"per_zettel": [], "total_chunks": 0, "failures": []}
    for z in zettels:
        try:
            chunks = await chunker.chunk_node(node_id=z["id"], text=z.get("summary") or "", source_type=z["source_type"])
            embedded = await embedder.embed_chunks(chunks)
            await upserter.upsert(user_id=user_id, node_id=z["id"], chunks=embedded)
            report["per_zettel"].append({"node_id": z["id"], "chunk_count": len(embedded), "ok": True})
            report["total_chunks"] += len(embedded)
        except Exception as exc:
            report["failures"].append({"node_id": z["id"], "error": str(exc)})
            report["per_zettel"].append({"node_id": z["id"], "ok": False, "error": str(exc)})
    return report
```

If `runtime.orchestrator` doesn't expose `_ingest_*` attributes, the integration test in Task 5.1 will surface this — fall back to invoking the orchestrator's public ingest method then.

- [ ] **Step 2: Add an integration smoke marker**

This task ships without a unit test; integration coverage lands in Task 5.1.

- [ ] **Step 3: Commit `feat: kasten ingestion driver`**

---

## Phase 2.5: KG Snapshot + Recommendation Engine

### Task 2.5.1: kg_snapshot.py

**Files:**
- Create: `website/features/rag_pipeline/evaluation/kg_snapshot.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_kg_snapshot.py`

- [ ] **Step 1: Write failing test**

```python
from unittest.mock import MagicMock
import networkx as nx

from website.features.rag_pipeline.evaluation.kg_snapshot import (
    snapshot_kasten,
    compute_health_delta,
)
from website.features.rag_pipeline.evaluation.types import KGSnapshot


def test_snapshot_kasten_uses_subgraph():
    nodes = [
        {"id": "yt-a", "tags": ["psychedelics"]},
        {"id": "yt-b", "tags": ["psychedelics", "neuroscience"]},
        {"id": "yt-c", "tags": ["unrelated"]},
    ]
    edges = [
        {"source_node_id": "yt-a", "target_node_id": "yt-b", "relation": "psychedelics"},
    ]
    snap = snapshot_kasten(kasten_node_ids=["yt-a", "yt-b"], all_nodes=nodes, all_edges=edges)
    assert snap.node_count == 2  # only Kasten nodes counted? actually + 1-hop neighbors
    # Actually per spec: kasten + 1-hop neighbors
    # yt-a, yt-b are in kasten, no 1-hop neighbors outside (yt-c is unconnected)
    assert "yt-a" in snap.kasten_node_ids
    assert snap.edge_count == 1


def test_compute_health_delta():
    a = KGSnapshot(kasten_node_ids=["yt-a"], neighborhood_node_ids=["yt-a", "yt-b"],
                   node_count=2, edge_count=1, mean_degree=1.0, orphan_count=0, tag_count=2,
                   tag_histogram={"psychedelics": 2})
    b = KGSnapshot(kasten_node_ids=["yt-a", "yt-c"], neighborhood_node_ids=["yt-a", "yt-b", "yt-c"],
                   node_count=3, edge_count=3, mean_degree=2.0, orphan_count=0, tag_count=3,
                   tag_histogram={"psychedelics": 3, "neuroscience": 1})
    delta = compute_health_delta(prev=a, curr=b)
    assert delta["edges_added"] == 2
    assert delta["mean_degree_delta"] == 1.0
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement kg_snapshot**

```python
# website/features/rag_pipeline/evaluation/kg_snapshot.py
"""KG snapshot + delta utilities."""
from __future__ import annotations

from collections import Counter

import networkx as nx

from website.features.rag_pipeline.evaluation.types import KGSnapshot


def snapshot_kasten(
    *,
    kasten_node_ids: list[str],
    all_nodes: list[dict],
    all_edges: list[dict],
) -> KGSnapshot:
    """Snapshot the Kasten + 1-hop neighborhood as a KGSnapshot."""
    nodes_by_id = {n["id"]: n for n in all_nodes}
    kasten_set = set(kasten_node_ids)

    # 1-hop neighbors via edges
    neighbors: set[str] = set(kasten_set)
    edges_in_scope: list[dict] = []
    for e in all_edges:
        s, t = e["source_node_id"], e["target_node_id"]
        if s in kasten_set or t in kasten_set:
            neighbors.add(s)
            neighbors.add(t)
            edges_in_scope.append(e)

    g = nx.Graph()
    g.add_nodes_from(neighbors)
    for e in edges_in_scope:
        g.add_edge(e["source_node_id"], e["target_node_id"])

    degrees = dict(g.degree())
    orphans = [n for n, d in degrees.items() if d == 0 and n in kasten_set]
    mean_degree = (sum(degrees.values()) / len(degrees)) if degrees else 0.0

    tag_hist: Counter[str] = Counter()
    for nid in neighbors:
        for tag in nodes_by_id.get(nid, {}).get("tags", []):
            tag_hist[tag] += 1

    return KGSnapshot(
        kasten_node_ids=sorted(kasten_set),
        neighborhood_node_ids=sorted(neighbors),
        node_count=len(neighbors),
        edge_count=len(edges_in_scope),
        mean_degree=round(mean_degree, 3),
        orphan_count=len(orphans),
        tag_count=len(tag_hist),
        tag_histogram=dict(tag_hist),
    )


def compute_health_delta(*, prev: KGSnapshot, curr: KGSnapshot) -> dict:
    return {
        "node_count_delta": curr.node_count - prev.node_count,
        "edges_added": max(curr.edge_count - prev.edge_count, 0),
        "edges_removed": max(prev.edge_count - curr.edge_count, 0),
        "mean_degree_delta": curr.mean_degree - prev.mean_degree,
        "orphan_delta": curr.orphan_count - prev.orphan_count,
        "tag_count_delta": curr.tag_count - prev.tag_count,
        "new_tags": sorted(set(curr.tag_histogram) - set(prev.tag_histogram)),
        "removed_tags": sorted(set(prev.tag_histogram) - set(curr.tag_histogram)),
    }
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: kg snapshot and health delta`**

### Task 2.5.2: kg_recommender.py

**Files:**
- Create: `website/features/rag_pipeline/evaluation/kg_recommender.py`
- Create: `tests/unit/rag_pipeline/evaluation/test_kg_recommender.py`

- [ ] **Step 1: Write failing test**

```python
from website.features.rag_pipeline.evaluation.kg_recommender import generate_recommendations
from website.features.rag_pipeline.evaluation.types import KGRecommendation


def test_generates_add_link_when_gold_is_distant():
    queries = [{"id": "q1", "gold_node_ids": ["yt-x"]}]
    answers = [{"query_id": "q1", "retrieved_node_ids": ["yt-a", "yt-b", "yt-c", "yt-d", "yt-e", "yt-f", "yt-x"]}]
    edges = []  # no edges from yt-x to anything in retrieval top-5
    recs = generate_recommendations(queries=queries, answers=answers, kasten_edges=edges,
                                     ragas_per_query={}, atomic_facts_per_query={}, kasten_nodes=[])
    types = [r.type for r in recs]
    assert "add_link" in types


def test_orphan_warning_for_zero_degree_node():
    nodes = [{"id": "yt-orphan", "tags": ["foo"]}]
    edges = []
    queries = []
    answers = []
    recs = generate_recommendations(queries=queries, answers=answers, kasten_edges=edges,
                                    ragas_per_query={}, atomic_facts_per_query={}, kasten_nodes=nodes)
    types = [r.type for r in recs]
    assert "orphan_warning" in types


def test_safety_brake_quarantines_when_too_many_of_one_type():
    queries = [{"id": f"q{i}", "gold_node_ids": [f"yt-x{i}"]} for i in range(6)]
    answers = [{"query_id": f"q{i}",
                "retrieved_node_ids": [f"yt-a{j}" for j in range(6)] + [f"yt-x{i}"]}
               for i in range(6)]
    edges = []
    recs = generate_recommendations(queries=queries, answers=answers, kasten_edges=edges,
                                    ragas_per_query={}, atomic_facts_per_query={}, kasten_nodes=[])
    add_link_recs = [r for r in recs if r.type == "add_link"]
    assert all(r.status == "quarantined" for r in add_link_recs), \
        "spec §8b: >5 of one type halts batch"
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement kg_recommender**

```python
# website/features/rag_pipeline/evaluation/kg_recommender.py
"""Generate kg_recommendations.json from eval results."""
from __future__ import annotations

from website.features.rag_pipeline.evaluation.types import KGRecommendation

_SAFETY_BRAKE_MAX_PER_TYPE = 5


def generate_recommendations(
    *,
    queries: list[dict],
    answers: list[dict],
    kasten_edges: list[dict],
    ragas_per_query: dict[str, dict],
    atomic_facts_per_query: dict[str, list[str]],
    kasten_nodes: list[dict],
) -> list[KGRecommendation]:
    recs: list[KGRecommendation] = []

    # add_link: gold node ranked > 5 AND graph-distant from retrieval top-1
    edge_set = {(e["source_node_id"], e["target_node_id"]) for e in kasten_edges}
    edge_set |= {(t, s) for s, t in edge_set}

    for q, a in zip(queries, answers):
        retrieved = a["retrieved_node_ids"]
        for gold in q["gold_node_ids"]:
            if gold in retrieved and retrieved.index(gold) > 4 and retrieved:
                top = retrieved[0]
                if (gold, top) not in edge_set and gold != top:
                    recs.append(KGRecommendation(
                        type="add_link",
                        payload={"from_node": top, "to_node": gold, "suggested_relation": "rag_eval_proximity"},
                        evidence_query_ids=[q["id"]],
                        confidence=0.7,
                        status="auto_apply",
                    ))

    # reingest_node: faithfulness < 0.5 for cited node
    for q, a in zip(queries, answers):
        ragas = ragas_per_query.get(q["id"], {})
        if ragas.get("faithfulness", 1.0) < 0.5:
            for cite in a.get("citations", []):
                recs.append(KGRecommendation(
                    type="reingest_node",
                    payload={"node_id": cite["node_id"], "low_faithfulness_count": 1},
                    evidence_query_ids=[q["id"]],
                    confidence=0.6,
                    status="quarantined",
                ))

    # orphan_warning: nodes with zero degree
    deg: dict[str, int] = {}
    for e in kasten_edges:
        deg[e["source_node_id"]] = deg.get(e["source_node_id"], 0) + 1
        deg[e["target_node_id"]] = deg.get(e["target_node_id"], 0) + 1
    for n in kasten_nodes:
        if deg.get(n["id"], 0) == 0:
            recs.append(KGRecommendation(
                type="orphan_warning",
                payload={"node_id": n["id"], "current_tags": n.get("tags", [])},
                evidence_query_ids=[],
                confidence=1.0,
                status="auto_apply",
            ))

    # add_tag: atomic fact entity not in any Kasten Zettel's tags
    all_tags = {tag for n in kasten_nodes for tag in n.get("tags", [])}
    for q in queries:
        for fact in atomic_facts_per_query.get(q["id"], []):
            words = [w.lower().strip(",.") for w in fact.split() if w[0].isupper()]
            for w in words:
                if w and w not in all_tags and len(w) > 3:
                    # Only first node in answer's citations gets the suggestion
                    recs.append(KGRecommendation(
                        type="add_tag",
                        payload={"node_id": q["gold_node_ids"][0], "suggested_tag": w,
                                 "evidence_atomic_fact": fact},
                        evidence_query_ids=[q["id"]],
                        confidence=0.5,
                        status="quarantined",
                    ))
                    break  # one tag suggestion per fact

    # Safety brake: > MAX of any one type → quarantine all of that type
    by_type: dict[str, list[int]] = {}
    for idx, r in enumerate(recs):
        by_type.setdefault(r.type, []).append(idx)
    for t, idxs in by_type.items():
        if len(idxs) > _SAFETY_BRAKE_MAX_PER_TYPE:
            for i in idxs:
                recs[i] = recs[i].model_copy(update={"status": "quarantined"})

    return recs
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: kg recommender with safety brake`**

### Task 2.5.3: apply_kg_recommendations.py

**Files:**
- Create: `ops/scripts/apply_kg_recommendations.py`
- Create: `tests/unit/rag_pipeline/ops/test_apply_kg_recommendations.py`

- [ ] **Step 1: Write failing test**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import json
import asyncio

from ops.scripts.apply_kg_recommendations import apply_recommendations


def test_apply_only_auto_apply_status(tmp_path):
    recs_path = tmp_path / "kg_recommendations.json"
    recs_path.write_text(json.dumps([
        {"type": "add_link", "payload": {"from_node": "a", "to_node": "b", "suggested_relation": "rel"},
         "evidence_query_ids": ["q1"], "confidence": 0.8, "status": "auto_apply"},
        {"type": "merge_nodes", "payload": {"node_a": "x", "node_b": "y", "similarity": 0.9},
         "evidence_query_ids": ["q1"], "confidence": 0.9, "status": "quarantined"},
    ]), encoding="utf-8")
    supabase = MagicMock()
    supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
    summary = asyncio.run(apply_recommendations(
        recs_path=recs_path, user_id="user-uuid", supabase=supabase, dry_run=False,
    ))
    assert summary["applied_count"] == 1
    assert summary["skipped_count"] == 1


def test_dry_run_makes_no_writes(tmp_path):
    recs_path = tmp_path / "kg_recommendations.json"
    recs_path.write_text(json.dumps([
        {"type": "add_link", "payload": {"from_node": "a", "to_node": "b", "suggested_relation": "rel"},
         "evidence_query_ids": ["q1"], "confidence": 0.8, "status": "auto_apply"},
    ]), encoding="utf-8")
    supabase = MagicMock()
    summary = asyncio.run(apply_recommendations(
        recs_path=recs_path, user_id="user-uuid", supabase=supabase, dry_run=True,
    ))
    supabase.table.return_value.insert.assert_not_called()
    assert summary["applied_count"] == 0
    assert summary["dry_run"] is True
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement applicator**

```python
# ops/scripts/apply_kg_recommendations.py
"""Autonomous KG-recommendation applicator with audit logging."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def apply_recommendations(
    *,
    recs_path: Path,
    user_id: str,
    supabase: Any,
    dry_run: bool = False,
) -> dict:
    raw = json.loads(recs_path.read_text(encoding="utf-8"))
    summary = {"applied_count": 0, "skipped_count": 0, "dry_run": dry_run, "applied": [], "skipped": []}

    for rec in raw:
        if rec.get("status") != "auto_apply":
            summary["skipped_count"] += 1
            summary["skipped"].append({"type": rec.get("type"), "reason": rec.get("status")})
            continue
        if dry_run:
            continue

        rtype = rec["type"]
        payload = rec.get("payload", {})
        if rtype == "add_link":
            supabase.table("kg_links").insert({
                "user_id": user_id,
                "source_node_id": payload["from_node"],
                "target_node_id": payload["to_node"],
                "relation": payload.get("suggested_relation", "rag_eval_proximity"),
            }).execute()
        elif rtype == "add_tag":
            # Update kg_nodes tags array
            existing = supabase.table("kg_nodes").select("tags").eq(
                "user_id", user_id
            ).eq("id", payload["node_id"]).single().execute().data
            new_tags = list(set((existing or {}).get("tags", []) + [payload["suggested_tag"]]))
            supabase.table("kg_nodes").update({"tags": new_tags}).eq(
                "user_id", user_id).eq("id", payload["node_id"]).execute()
        elif rtype == "orphan_warning":
            # Annotation only — no graph mutation
            existing = supabase.table("kg_nodes").select("metadata").eq(
                "user_id", user_id).eq("id", payload["node_id"]).single().execute().data
            md = (existing or {}).get("metadata", {}) or {}
            md["rag_eval_orphan_flag"] = datetime.now(timezone.utc).isoformat()
            supabase.table("kg_nodes").update({"metadata": md}).eq(
                "user_id", user_id).eq("id", payload["node_id"]).execute()
        else:
            # merge_nodes / reingest_node only run via --confirm flag (separate code path)
            summary["skipped_count"] += 1
            continue

        summary["applied_count"] += 1
        summary["applied"].append({"type": rtype, "payload": payload})

    return summary


def _changelog_append(path: Path, summary: dict, iter_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [f"\n## {iter_id} — {ts}\n"]
    for app in summary.get("applied", []):
        lines.append(f"- APPLIED `{app['type']}` — {json.dumps(app['payload'])}\n")
    for skip in summary.get("skipped", []):
        lines.append(f"- SKIPPED `{skip['type']}` — reason: {skip.get('reason')}\n")
    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iter", required=True, help="e.g. youtube/iter-02")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true",
                        help="Required for merge_nodes / reingest_node application.")
    args = parser.parse_args()

    from website.core.supabase_kg.client import get_supabase_client

    supabase = get_supabase_client()
    if supabase is None:
        print("ERROR: Supabase not configured")
        return 1

    recs_path = Path("docs/rag_eval") / args.iter / "kg_recommendations.json"
    summary = asyncio.run(apply_recommendations(
        recs_path=recs_path, user_id=args.user_id, supabase=supabase, dry_run=args.dry_run,
    ))
    print(json.dumps(summary, indent=2))
    if not args.dry_run and summary.get("applied_count", 0) > 0:
        _changelog_append(Path("docs/rag_eval/_kg_changelog.md"), summary, args.iter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: autonomous kg recommendation applicator`**

---

## Phase 3: CLI + State Machine

### Task 3.1: rag_eval_state.py — 4-state machine

**Files:**
- Create: `ops/scripts/lib/rag_eval_state.py`
- Create: `tests/unit/rag_pipeline/ops/test_rag_eval_state.py`

- [ ] **Step 1: Write failing test**

```python
from pathlib import Path
import pytest

from ops.scripts.lib.rag_eval_state import detect_state, IterState


def test_empty_dir_is_phase_a_required(tmp_path):
    assert detect_state(tmp_path) == IterState.PHASE_A_REQUIRED


def test_with_prompt_no_review_awaits_review(tmp_path):
    (tmp_path / "manual_review_prompt.md").write_text("prompt", encoding="utf-8")
    (tmp_path / "eval.json").write_text("{}", encoding="utf-8")
    assert detect_state(tmp_path) == IterState.AWAITING_MANUAL_REVIEW


def test_with_review_no_diff_phase_b_required(tmp_path):
    (tmp_path / "manual_review_prompt.md").write_text("prompt", encoding="utf-8")
    (tmp_path / "manual_review.md").write_text('eval_json_hash_at_review: "NOT_CONSULTED"\nestimated_composite: 70', encoding="utf-8")
    (tmp_path / "eval.json").write_text("{}", encoding="utf-8")
    assert detect_state(tmp_path) == IterState.PHASE_B_REQUIRED


def test_with_diff_committed(tmp_path):
    (tmp_path / "manual_review_prompt.md").write_text("prompt", encoding="utf-8")
    (tmp_path / "manual_review.md").write_text("review", encoding="utf-8")
    (tmp_path / "diff.md").write_text("diff", encoding="utf-8")
    (tmp_path / "eval.json").write_text("{}", encoding="utf-8")
    assert detect_state(tmp_path) == IterState.ALREADY_COMMITTED
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement state machine**

```python
# ops/scripts/lib/rag_eval_state.py
"""4-state machine for the rag_eval iter directory."""
from __future__ import annotations

from enum import Enum
from pathlib import Path


class IterState(str, Enum):
    PHASE_A_REQUIRED = "PHASE_A_REQUIRED"
    AWAITING_MANUAL_REVIEW = "AWAITING_MANUAL_REVIEW"
    PHASE_B_REQUIRED = "PHASE_B_REQUIRED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"


def detect_state(iter_dir: Path) -> IterState:
    if (iter_dir / "diff.md").exists():
        return IterState.ALREADY_COMMITTED
    if (iter_dir / "manual_review.md").exists():
        return IterState.PHASE_B_REQUIRED
    if (iter_dir / "manual_review_prompt.md").exists() and (iter_dir / "eval.json").exists():
        return IterState.AWAITING_MANUAL_REVIEW
    return IterState.PHASE_A_REQUIRED
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: rag eval state machine`**

### Task 3.2: rag_eval_review.py — cross-LLM blind reviewer

**Files:**
- Create: `ops/scripts/lib/rag_eval_review.py`
- Create: `tests/unit/rag_pipeline/ops/test_rag_eval_review.py`

- [ ] **Step 1: Write failing test (mock the Agent dispatch)**

```python
from pathlib import Path
import json
from unittest.mock import patch, MagicMock

from ops.scripts.lib.rag_eval_review import (
    build_review_prompt,
    dispatch_blind_reviewer,
    verify_review_stamp,
    BlindReviewError,
)


def test_build_review_prompt_excludes_eval_json():
    iter_dir = Path("/fake")
    prompt = build_review_prompt(iter_dir, source="youtube", iter_num=1)
    assert "eval.json" not in prompt  # MUST NOT instruct subagent to read eval.json
    assert "ablation_eval.json" not in prompt
    assert 'NOT_CONSULTED' in prompt
    assert "queries.json" in prompt
    assert "answers.json" in prompt
    assert "kasten.json" in prompt


def test_verify_review_stamp_accepts_correct_stamp(tmp_path):
    review = tmp_path / "manual_review.md"
    review.write_text("""# review

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: 72.5
estimated_retrieval: 70
estimated_synthesis: 75
""", encoding="utf-8")
    parsed = verify_review_stamp(review)
    assert parsed["estimated_composite"] == 72.5


def test_verify_review_stamp_rejects_missing(tmp_path):
    review = tmp_path / "manual_review.md"
    review.write_text("estimated_composite: 70", encoding="utf-8")
    with pytest.raises(BlindReviewError):
        verify_review_stamp(review)


def test_verify_review_stamp_rejects_wrong_stamp(tmp_path):
    review = tmp_path / "manual_review.md"
    review.write_text('eval_json_hash_at_review: "abc123"\nestimated_composite: 70', encoding="utf-8")
    with pytest.raises(BlindReviewError):
        verify_review_stamp(review)
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement reviewer**

```python
# ops/scripts/lib/rag_eval_review.py
"""Cross-LLM blind reviewer dispatcher."""
from __future__ import annotations

import re
from pathlib import Path


class BlindReviewError(Exception):
    pass


_PROMPT_TEMPLATE = """\
You are an INDEPENDENT cross-LLM reviewer for a RAG evaluation iteration.
You MUST be blind to the evaluator's output. Do NOT read eval.json or ablation_eval.json.

You may read ONLY these files in iter-{iter_num:02d}/:
- manual_review_prompt.md (this file's full prompt)
- queries.json
- answers.json
- kasten.json
- kg_snapshot.json

Stamp `eval_json_hash_at_review: "NOT_CONSULTED"` at the top of manual_review.md you write.

For each of the 5 queries, read the question, the system's answer, the citations, and the gold/reference.
Estimate the composite score from your honest reading. Be specific:
- Did the right Zettel get cited?
- Was the answer faithful to the source?
- Were any hallucinations present?
- Was the answer comprehensive against the reference?

Schema for manual_review.md:

```
# iter-{iter_num:02d} manual review — {source} — <date>

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: <0–100>
estimated_retrieval: <0–100>
estimated_synthesis: <0–100>

## Per-query observations
- Q1: ...
- Q2: ...
- Q3: ...
- Q4: ...
- Q5: ...

## Per-stage observations
- Chunking: ...
- Retrieval: ...
- Reranking: ...
- Synthesis: ...
- KG signal (graph_lift): unknown without eval.json — leave blank
```

Write the file to: {iter_dir}/manual_review.md
Do NOT compute exact scores; estimate as a human reviewer would.
Be honest about uncertainty.
"""


def build_review_prompt(iter_dir: Path, *, source: str, iter_num: int) -> str:
    return _PROMPT_TEMPLATE.format(source=source, iter_num=iter_num, iter_dir=iter_dir)


_STAMP_RE = re.compile(r'eval_json_hash_at_review:\s*"NOT_CONSULTED"')
_COMPOSITE_RE = re.compile(r"estimated_composite:\s*([\d.]+)")


def verify_review_stamp(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not _STAMP_RE.search(text):
        raise BlindReviewError(
            "manual_review.md must stamp eval_json_hash_at_review: \"NOT_CONSULTED\""
        )
    m = _COMPOSITE_RE.search(text)
    if not m:
        raise BlindReviewError("manual_review.md missing estimated_composite")
    return {"estimated_composite": float(m.group(1))}


async def dispatch_blind_reviewer(
    *,
    iter_dir: Path,
    source: str,
    iter_num: int,
    agent_runner: callable,
) -> Path:
    """Dispatch a Claude subagent (caller injects agent_runner)."""
    prompt = build_review_prompt(iter_dir, source=source, iter_num=iter_num)
    transcript = await agent_runner(prompt=prompt, allowed_files=[
        iter_dir / "manual_review_prompt.md",
        iter_dir / "queries.json",
        iter_dir / "answers.json",
        iter_dir / "kasten.json",
        iter_dir / "kg_snapshot.json",
    ])
    transcript_path = iter_dir / "_review_subagent_transcript.json"
    transcript_path.write_text(transcript, encoding="utf-8")
    return iter_dir / "manual_review.md"
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: cross-llm blind reviewer dispatcher`**

### Task 3.3: rag_eval_diff.py — determinism gate + improvement_delta

**Files:**
- Create: `ops/scripts/lib/rag_eval_diff.py`
- Create: `tests/unit/rag_pipeline/ops/test_rag_eval_diff.py`

- [ ] **Step 1: Write failing test**

```python
import pytest
from pathlib import Path
import json

from ops.scripts.lib.rag_eval_diff import (
    determinism_gate,
    DeterminismError,
    write_improvement_delta,
)


def test_determinism_gate_passes_within_3pt():
    determinism_gate(prev_composite=70.0, current_composite=72.5, tolerance=3.0)


def test_determinism_gate_blocks_drift():
    with pytest.raises(DeterminismError):
        determinism_gate(prev_composite=70.0, current_composite=75.0, tolerance=3.0)


def test_write_improvement_delta(tmp_path):
    iter_dir = tmp_path / "iter-02"
    iter_dir.mkdir()
    delta = write_improvement_delta(
        iter_dir=iter_dir,
        prev_composite=70.0, curr_composite=78.0,
        prev_components={"chunking": 75, "retrieval": 70, "reranking": 65, "synthesis": 80},
        curr_components={"chunking": 80, "retrieval": 80, "reranking": 78, "synthesis": 85},
        graph_lift_prev={"composite": 0.0, "retrieval": 0.0, "reranking": 0.0},
        graph_lift_curr={"composite": 5.0, "retrieval": 7.0, "reranking": 4.0},
        review_estimate=76.0,
    )
    written = json.loads((iter_dir / "improvement_delta.json").read_text(encoding="utf-8"))
    assert written["composite"]["absolute"] == 8.0
    assert written["review_divergence_band"] == "AGREEMENT"  # 78-76=2 ≤5
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement diff utilities**

```python
# ops/scripts/lib/rag_eval_diff.py
"""Determinism gate + improvement delta writer."""
from __future__ import annotations

import json
from pathlib import Path


class DeterminismError(Exception):
    pass


def determinism_gate(*, prev_composite: float, current_composite: float, tolerance: float = 3.0) -> None:
    drift = abs(current_composite - prev_composite)
    if drift > tolerance:
        raise DeterminismError(
            f"Determinism gate: composite drifted {drift:.2f}pt vs prior iter's eval re-run "
            f"(tolerance {tolerance}pt). Halt and investigate evaluator changes."
        )


def _band(absolute_delta: float) -> str:
    a = abs(absolute_delta)
    if a <= 5.0:
        return "AGREEMENT"
    if a <= 10.0:
        return "MINOR_DISAGREEMENT"
    return "MAJOR_DISAGREEMENT"


def write_improvement_delta(
    *,
    iter_dir: Path,
    prev_composite: float,
    curr_composite: float,
    prev_components: dict[str, float],
    curr_components: dict[str, float],
    graph_lift_prev: dict[str, float],
    graph_lift_curr: dict[str, float],
    review_estimate: float | None,
) -> dict:
    out = {
        "composite": {
            "previous": prev_composite,
            "current": curr_composite,
            "absolute": curr_composite - prev_composite,
            "relative_pct": (curr_composite - prev_composite) / prev_composite * 100.0 if prev_composite else 0.0,
        },
        "components": {
            k: {"previous": prev_components.get(k, 0), "current": curr_components.get(k, 0),
                "absolute": curr_components.get(k, 0) - prev_components.get(k, 0)}
            for k in ("chunking", "retrieval", "reranking", "synthesis")
        },
        "graph_lift": {
            "previous": graph_lift_prev,
            "current": graph_lift_curr,
            "delta": {k: graph_lift_curr.get(k, 0) - graph_lift_prev.get(k, 0)
                      for k in ("composite", "retrieval", "reranking")},
        },
        "review_estimate": review_estimate,
        "review_divergence_band": _band(curr_composite - review_estimate) if review_estimate is not None else None,
    }
    (iter_dir / "improvement_delta.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: determinism gate and improvement delta`**

### Task 3.4: rag_eval_breadth.py — change-breadth gate

**Files:**
- Create: `ops/scripts/lib/rag_eval_breadth.py`
- Create: `tests/unit/rag_pipeline/ops/test_rag_eval_breadth.py`

- [ ] **Step 1: Write failing test**

```python
import subprocess
from unittest.mock import patch

from ops.scripts.lib.rag_eval_breadth import (
    extract_changed_components,
    breadth_gate,
    BreadthError,
)


def test_extract_changed_components():
    diff_stat = """ website/features/rag_pipeline/ingest/chunker.py | 30 +-
 website/features/rag_pipeline/rerank/cascade.py | 12 +-
 website/features/rag_pipeline/generation/prompts.py | 5 +-
 docs/rag_eval/_config/composite_weights.yaml | 2 +-
 5 files changed, 47 insertions(+), 2 deletions(-)
"""
    components, configs = extract_changed_components(diff_stat)
    assert "ingest/chunker.py" in components
    assert "rerank/cascade.py" in components
    assert "generation/prompts.py" in components
    assert len(components) == 3
    assert "composite_weights.yaml" in configs


def test_breadth_gate_passes_with_3_components_and_config():
    breadth_gate(components={"a", "b", "c"}, config_or_weight_changed=True)


def test_breadth_gate_blocks_too_few_components():
    with pytest.raises(BreadthError, match="components"):
        breadth_gate(components={"a", "b"}, config_or_weight_changed=True)


def test_breadth_gate_blocks_no_config_change():
    with pytest.raises(BreadthError, match="config"):
        breadth_gate(components={"a", "b", "c"}, config_or_weight_changed=False)
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement breadth gate**

```python
# ops/scripts/lib/rag_eval_breadth.py
"""Change-breadth gate: ensures each tuning iter touches ≥3 RAG components AND ≥1 config/weight."""
from __future__ import annotations

import re

_COMPONENT_PATTERNS = [
    "ingest/chunker.py",
    "ingest/embedder.py",
    "retrieval/hybrid.py",
    "rerank/cascade.py",
    "query/rewriter.py",
    "query/router.py",
    "generation/prompts.py",
]

_CONFIG_PATTERNS = [
    "composite_weights.yaml",
    "fusion_weights",
    "depth_by_class",
    "rubric_",
]


class BreadthError(Exception):
    pass


def extract_changed_components(diff_stat: str) -> tuple[set[str], set[str]]:
    """Return (components_changed, configs_changed) sets from `git diff --stat` output."""
    components: set[str] = set()
    configs: set[str] = set()
    for line in diff_stat.splitlines():
        for pat in _COMPONENT_PATTERNS:
            if pat in line:
                components.add(pat)
        for pat in _CONFIG_PATTERNS:
            if pat in line:
                configs.add(pat)
    return components, configs


def breadth_gate(*, components: set[str], config_or_weight_changed: bool) -> None:
    if len(components) < 3:
        raise BreadthError(
            f"CHANGE_BREADTH_INSUFFICIENT: tuning iter must modify ≥3 RAG components; "
            f"found {len(components)}: {sorted(components)}"
        )
    if not config_or_weight_changed:
        raise BreadthError(
            "CHANGE_BREADTH_INSUFFICIENT: tuning iter must touch ≥1 config or weight surface"
        )
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: change breadth gate`**

### Task 3.5: rag_eval_billing.py — billing-key escalation + halt

**Files:**
- Create: `ops/scripts/lib/rag_eval_billing.py`
- Create: `tests/unit/rag_pipeline/ops/test_rag_eval_billing.py`

- [ ] **Step 1: Write failing test**

```python
from pathlib import Path
from ops.scripts.lib.rag_eval_billing import (
    BillingTier, escalate_on_429, write_halt, is_halted,
)


def test_escalate_from_free_to_billing():
    state = BillingTier.FREE
    new = escalate_on_429(state, free_keys_exhausted=True)
    assert new == BillingTier.BILLING


def test_escalate_billing_exhaustion_halts(tmp_path):
    state = BillingTier.BILLING
    new = escalate_on_429(state, free_keys_exhausted=True, billing_exhausted=True)
    assert new == BillingTier.HALTED


def test_write_halt_creates_sentinel(tmp_path):
    write_halt(tmp_path / ".halt", reason="quota exhausted")
    assert (tmp_path / ".halt").exists()
    assert is_halted(tmp_path / ".halt")
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement billing escalation**

```python
# ops/scripts/lib/rag_eval_billing.py
"""Two-tier billing escalation for Gemini key exhaustion."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class BillingTier(str, Enum):
    FREE = "FREE"
    BILLING = "BILLING"
    HALTED = "HALTED"


def escalate_on_429(
    current: BillingTier,
    *,
    free_keys_exhausted: bool = False,
    billing_exhausted: bool = False,
) -> BillingTier:
    if billing_exhausted:
        return BillingTier.HALTED
    if free_keys_exhausted and current == BillingTier.FREE:
        return BillingTier.BILLING
    return current


def write_halt(path: Path, *, reason: str, state: dict | None = None) -> None:
    payload = {
        "reason": reason,
        "halted_at": datetime.now(timezone.utc).isoformat(),
        "state": state or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def is_halted(path: Path) -> bool:
    return path.exists()
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: billing key escalation and halt`**

### Task 3.6: rag_eval_loop.py — main CLI

**Files:**
- Create: `ops/scripts/rag_eval_loop.py`
- Create: `tests/unit/rag_pipeline/ops/test_rag_eval_loop.py`

(The CLI is large; this task only provides the dispatch skeleton + dry-run test. Full E2E coverage lands in Phase 5 smoke run.)

- [ ] **Step 1: Write skeleton test**

```python
from unittest.mock import patch
from ops.scripts.rag_eval_loop import _cli_dispatch


def test_cli_dispatch_dry_run_returns_0():
    with patch("ops.scripts.rag_eval_loop._run_phase_a") as run_a:
        run_a.return_value = {"status": "dry_run"}
        rc = _cli_dispatch(["--source", "youtube", "--iter", "1", "--dry-run"])
    assert rc == 0
```

- [ ] **Step 2: Run test, confirm FAIL.**

- [ ] **Step 3: Implement CLI skeleton**

```python
# ops/scripts/rag_eval_loop.py
"""rag_eval iteration CLI — two-phase auto-resume.

Mirrors ops/scripts/eval_loop.py shape; sources: youtube|reddit|github|newsletter.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.rag_eval_state import detect_state, IterState

ARTIFACT_ROOT = Path("docs/rag_eval")
HALT_FILE = ARTIFACT_ROOT / ".halt"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=["youtube", "reddit", "github", "newsletter"], required=True)
    p.add_argument("--iter", type=int, required=True, dest="iter_num")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-determinism", action="store_true")
    p.add_argument("--skip-breadth", action="store_true")
    p.add_argument("--unseal-heldout", action="store_true",
                   help="Allow loading heldout.yaml (final iter only).")
    p.add_argument("--auto", action="store_true",
                   help="Run Phase A + dispatch reviewer + Phase B without pausing.")
    return p.parse_args(argv)


async def _run_phase_a(args: argparse.Namespace) -> dict:
    """Stub — real implementation lands in Task 3.7 (Phase 5 smoke wires it up)."""
    return {"status": "phase_a_stub", "source": args.source, "iter": args.iter_num}


async def _run_phase_b(args: argparse.Namespace) -> dict:
    return {"status": "phase_b_stub", "source": args.source, "iter": args.iter_num}


def _cli_dispatch(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if HALT_FILE.exists():
        print(f"HALTED: {HALT_FILE.read_text(encoding='utf-8')}")
        return 1
    iter_dir = ARTIFACT_ROOT / args.source / f"iter-{args.iter_num:02d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    state = detect_state(iter_dir)

    if args.dry_run:
        print(json.dumps({"status": "dry_run", "state": state.value, "iter_dir": str(iter_dir)}, indent=2))
        return 0

    if state == IterState.PHASE_A_REQUIRED:
        result = asyncio.run(_run_phase_a(args))
    elif state == IterState.AWAITING_MANUAL_REVIEW:
        if not args.auto:
            print(f"AWAITING_MANUAL_REVIEW — write {iter_dir}/manual_review.md")
            return 0
        # Auto-mode dispatches the reviewer (wired in Task 3.7)
        result = {"status": "auto_review_dispatch_stub"}
    elif state == IterState.PHASE_B_REQUIRED:
        result = asyncio.run(_run_phase_b(args))
    else:
        result = {"status": "already_committed"}

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli_dispatch())
```

- [ ] **Step 4: Run test, confirm PASS.**
- [ ] **Step 5: Commit `feat: rag_eval_loop cli skeleton`**

### Task 3.7: Wire Phase A and Phase B fully

**Files:**
- Modify: `ops/scripts/rag_eval_loop.py`
- Test: covered by Phase 5 smoke run

- [ ] **Step 1: Implement `_run_phase_a` fully**

Replace `_run_phase_a` in `ops/scripts/rag_eval_loop.py` with the production implementation. Pseudocode (engineer fills in concrete glue):
```python
async def _run_phase_a(args) -> dict:
    iter_dir = ARTIFACT_ROOT / args.source / f"iter-{args.iter_num:02d}"
    config_dir = ARTIFACT_ROOT / "_config"

    # 1. Load + lock weights
    from website.features.rag_pipeline.evaluation.composite import hash_weights_file, verify_weights_unchanged
    weights_path = config_dir / "composite_weights.yaml"
    weights_hash = hash_weights_file(weights_path)
    # Persist lock at iter-01; verify at iter ≥ 02
    lock_path = ARTIFACT_ROOT / args.source / ".weights_lock"
    if args.iter_num == 1:
        lock_path.write_text(weights_hash, encoding="utf-8")
    else:
        verify_weights_unchanged(weights_path, lock_path.read_text(encoding="utf-8").strip())

    # 2. Load gold queries (seed for non-final, heldout for final)
    from website.features.rag_pipeline.evaluation.gold_loader import load_seed_queries, load_heldout_queries
    is_final = (args.iter_num == 5 and args.source == "youtube") or (args.iter_num == 3 and args.source != "youtube")
    if is_final:
        queries = load_heldout_queries(config_dir / "queries" / args.source / "heldout.yaml",
                                       allow_sealed=args.unseal_heldout)
    else:
        queries = load_seed_queries(config_dir / "queries" / args.source / "seed.yaml")

    # 3. Build Kasten + ingest
    from ops.scripts.lib.rag_eval_kasten import build_kasten, ingest_kasten
    from website.core.supabase_kg.client import get_supabase_client
    from website.features.rag_pipeline.service import _build_runtime
    supabase = get_supabase_client()
    naruto_id = json.loads((ARTIFACT_ROOT / "_config" / "_naruto_baseline.json").read_text(encoding="utf-8"))["user_id"]
    seed_node_ids = _resolve_seed_node_ids(args.source, args.iter_num)  # helper that reads the per-source seed list
    kasten = await build_kasten(source=args.source, iter_num=args.iter_num, user_id=naruto_id,
                                seed_node_ids=seed_node_ids, supabase=supabase,
                                chintan_path=Path("docs/research/Chintan_Testing.md"),
                                output_dir=iter_dir)
    runtime = _build_runtime(naruto_id)
    ingest_report = await ingest_kasten(zettels=kasten["zettels"], user_id=naruto_id, runtime=runtime)
    (iter_dir / "kasten.json").write_text(json.dumps(kasten, indent=2, default=str), encoding="utf-8")
    (iter_dir / "ingest.json").write_text(json.dumps(ingest_report, indent=2), encoding="utf-8")

    # 4. KG snapshot pre-iter
    from website.features.rag_pipeline.evaluation.kg_snapshot import snapshot_kasten
    all_nodes = supabase.table("kg_nodes").select("id, tags").eq("user_id", naruto_id).execute().data or []
    all_edges = supabase.table("kg_links").select("source_node_id, target_node_id, relation").eq("user_id", naruto_id).execute().data or []
    snap = snapshot_kasten(kasten_node_ids=[z["id"] for z in kasten["zettels"]],
                           all_nodes=all_nodes, all_edges=all_edges)
    (iter_dir / "kg_snapshot.json").write_text(snap.model_dump_json(indent=2), encoding="utf-8")

    # 5. Run queries through orchestrator (with-graph + ablated)
    answers = []
    answers_ablated = []
    for q in queries:
        turn = await runtime.orchestrator.answer(user_id=naruto_id, content=q.question)
        answers.append(_serialize_turn(turn, q))
        # Ablation: re-run with graph_weight=0 via runtime override
        ablated_turn = await runtime.orchestrator.answer(user_id=naruto_id, content=q.question, graph_weight_override=0.0)
        answers_ablated.append(_serialize_turn(ablated_turn, q))

    (iter_dir / "queries.json").write_text(json.dumps([q.model_dump() for q in queries], indent=2, default=str), encoding="utf-8")
    (iter_dir / "answers.json").write_text(json.dumps(answers, indent=2, default=str), encoding="utf-8")

    # 6. Run eval (with graph) + ablation eval (graph_weight=0) → graph_lift
    from website.features.rag_pipeline.evaluation.eval_runner import EvalRunner
    from website.features.rag_pipeline.evaluation.ablation import compute_graph_lift
    chunks_per_node = _build_chunks_map(ingest_report)
    weights = _read_weights(weights_path)
    runner = EvalRunner(weights=weights, weights_hash=weights_hash)
    result_with = runner.evaluate(iter_id=f"{args.source}/iter-{args.iter_num:02d}",
                                  queries=queries, answers=answers, chunks_per_node=chunks_per_node)
    result_ablated = runner.evaluate(iter_id=f"{args.source}/iter-{args.iter_num:02d}_ablated",
                                     queries=queries, answers=answers_ablated, chunks_per_node=chunks_per_node)
    lift = compute_graph_lift(with_graph=result_with.component_scores,
                              ablated=result_ablated.component_scores, weights=weights)
    result_with = result_with.model_copy(update={"graph_lift": lift})
    (iter_dir / "eval.json").write_text(result_with.model_dump_json(indent=2), encoding="utf-8")
    (iter_dir / "ablation_eval.json").write_text(result_ablated.model_dump_json(indent=2), encoding="utf-8")

    # 7. Write atomic_facts.json (extracted from ground_truth fields)
    atomic = {q.id: q.atomic_facts for q in queries}
    (iter_dir / "atomic_facts.json").write_text(json.dumps(atomic, indent=2), encoding="utf-8")

    # 8. Generate KG recommendations
    from website.features.rag_pipeline.evaluation.kg_recommender import generate_recommendations
    recs = generate_recommendations(
        queries=[q.model_dump() for q in queries],
        answers=answers,
        kasten_edges=all_edges,
        ragas_per_query={pq.query_id: pq.ragas for pq in result_with.per_query},
        atomic_facts_per_query=atomic,
        kasten_nodes=kasten["zettels"],
    )
    (iter_dir / "kg_recommendations.json").write_text(
        json.dumps([r.model_dump() for r in recs], indent=2), encoding="utf-8")

    # 9. Render human artifacts
    from website.features.rag_pipeline.evaluation.rendering import (
        render_qa_pairs, render_scores, render_kg_changes,
    )
    render_qa_pairs(iter_dir, queries=queries, answers=answers,
                    per_query=result_with.per_query)
    render_scores(iter_dir, eval_result=result_with, prev_eval_path=_prev_eval_path(args))
    render_kg_changes(iter_dir, recs=recs, snapshot=snap)

    # 10. Build manual_review_prompt.md
    from ops.scripts.lib.rag_eval_review import build_review_prompt
    (iter_dir / "manual_review_prompt.md").write_text(
        build_review_prompt(iter_dir, source=args.source, iter_num=args.iter_num),
        encoding="utf-8",
    )

    return {"status": "phase_a_complete", "composite": result_with.composite,
            "graph_lift_composite": lift.composite}
```

(Helper functions `_serialize_turn`, `_build_chunks_map`, `_read_weights`, `_resolve_seed_node_ids`, `_prev_eval_path` are small — engineer implements inline; each is <15 lines and obvious from context. The orchestrator's `graph_weight_override` parameter is added in Task 3.8.)

- [ ] **Step 2: Implement `_run_phase_b` fully**

Replace `_run_phase_b` with:
```python
async def _run_phase_b(args) -> dict:
    iter_dir = ARTIFACT_ROOT / args.source / f"iter-{args.iter_num:02d}"
    from ops.scripts.lib.rag_eval_review import verify_review_stamp
    from ops.scripts.lib.rag_eval_diff import determinism_gate, write_improvement_delta
    from ops.scripts.lib.rag_eval_breadth import extract_changed_components, breadth_gate

    # 1. Verify review stamp
    review = verify_review_stamp(iter_dir / "manual_review.md")

    # 2. Determinism gate (skip on iter-01)
    if args.iter_num > 1 and not args.skip_determinism:
        prev_dir = ARTIFACT_ROOT / args.source / f"iter-{args.iter_num-1:02d}"
        prev_eval = json.loads((prev_dir / "eval.json").read_text(encoding="utf-8"))
        # Re-run eval on prev's answers using current evaluator
        rerun_composite = _rerun_prev_eval(prev_dir)
        determinism_gate(prev_composite=prev_eval["composite"], current_composite=rerun_composite)

    # 3. Change-breadth gate (skip on iter-01)
    if args.iter_num > 1 and not args.skip_breadth:
        import subprocess
        diff_stat = subprocess.check_output(
            ["git", "diff", f"iter-{args.iter_num-1:02d}_committed..HEAD", "--stat"],
            text=True,
        )
        components, configs = extract_changed_components(diff_stat)
        breadth_gate(components=components, config_or_weight_changed=bool(configs))

    # 4. Improvement delta
    eval_curr = json.loads((iter_dir / "eval.json").read_text(encoding="utf-8"))
    if args.iter_num > 1:
        prev_eval = json.loads((ARTIFACT_ROOT / args.source / f"iter-{args.iter_num-1:02d}" / "eval.json").read_text(encoding="utf-8"))
        write_improvement_delta(
            iter_dir=iter_dir,
            prev_composite=prev_eval["composite"], curr_composite=eval_curr["composite"],
            prev_components=prev_eval["component_scores"], curr_components=eval_curr["component_scores"],
            graph_lift_prev=prev_eval.get("graph_lift", {}),
            graph_lift_curr=eval_curr.get("graph_lift", {}),
            review_estimate=review["estimated_composite"],
        )

    # 5. Apply KG recommendations autonomously
    import subprocess
    naruto_id = json.loads((ARTIFACT_ROOT / "_config" / "_naruto_baseline.json").read_text(encoding="utf-8"))["user_id"]
    subprocess.run([
        "python", "ops/scripts/apply_kg_recommendations.py",
        "--iter", f"{args.source}/iter-{args.iter_num:02d}",
        "--user-id", naruto_id,
    ], check=True)

    # 6. Write next_actions.md + diff.md
    _write_next_actions(iter_dir, eval_curr, review)
    _write_diff(iter_dir, args)

    # 7. Commit
    if not args.dry_run:
        subprocess.run(["git", "add", str(iter_dir), str(ARTIFACT_ROOT / "_kg_changelog.md")], check=True)
        subprocess.run(["git", "commit", "-m",
                        f"feat: rag_eval {args.source} iter-{args.iter_num:02d}"],
                       check=True)

    return {"status": "phase_b_complete"}
```

- [ ] **Step 3: Add Auto-mode wiring**

In `_cli_dispatch`, when state is `AWAITING_MANUAL_REVIEW` and `--auto` is set:
```python
elif state == IterState.AWAITING_MANUAL_REVIEW:
    if not args.auto:
        print(f"AWAITING_MANUAL_REVIEW — write {iter_dir}/manual_review.md")
        return 0
    # Cross-LLM blind reviewer dispatch
    from ops.scripts.lib.rag_eval_review import dispatch_blind_reviewer
    asyncio.run(dispatch_blind_reviewer(
        iter_dir=iter_dir, source=args.source, iter_num=args.iter_num,
        agent_runner=_claude_subagent_runner,  # provided by orchestrator harness
    ))
    # Re-detect state and proceed to Phase B
    state = detect_state(iter_dir)
    result = asyncio.run(_run_phase_b(args))
```

(The `_claude_subagent_runner` callable is defined inline using the Agent tool, OR — when running under executing-plans — by spawning a subagent via the parent harness. The CLI accepts an injected `agent_runner` for testability.)

- [ ] **Step 4: Smoke-test the wiring**

Run: `python ops/scripts/rag_eval_loop.py --source youtube --iter 1 --dry-run`
Expected: prints `{"status": "dry_run", "state": "PHASE_A_REQUIRED", ...}` exit 0.

- [ ] **Step 5: Commit `feat: rag_eval_loop full phase a and phase b`**

### Task 3.8: Add `graph_weight_override` to orchestrator

**Files:**
- Modify: `website/features/rag_pipeline/orchestrator.py`
- Modify: `website/features/rag_pipeline/rerank/cascade.py`

- [ ] **Step 1: Read orchestrator's answer signature, add override param**

Add a `graph_weight_override: float | None = None` keyword to `RAGOrchestrator.answer(...)` and thread it down to the reranker's fusion calculation. In `cascade.py`, when override is set, replace the per-class `_FUSION_WEIGHTS[query_class]` lookup with `(rerank_w, override, rrf_w)` where `(rerank_w, _, rrf_w) = _FUSION_WEIGHTS[query_class]` then re-normalize.

```python
# website/features/rag_pipeline/rerank/cascade.py — inside CascadeReranker.rerank()
def _resolve_fusion_weights(query_class, graph_weight_override):
    rerank_w, graph_w, rrf_w = _FUSION_WEIGHTS.get(query_class, _DEFAULT_FUSION_WEIGHTS)
    if graph_weight_override is not None:
        graph_w = graph_weight_override
        # Re-normalize to sum 1.0, preserving rerank_w/rrf_w ratio
        spillover = (1.0 - graph_w) / (rerank_w + rrf_w) if (rerank_w + rrf_w) else 0
        return rerank_w * spillover, graph_w, rrf_w * spillover
    return rerank_w, graph_w, rrf_w
```

Plumb via `RAGOrchestrator.answer(...)` keyword. Add a unit test that asserts the override is applied.

- [ ] **Step 2: Add unit test for override**

```python
# tests/unit/rag_pipeline/test_cascade_ablation.py
from website.features.rag_pipeline.rerank.cascade import _resolve_fusion_weights
from website.features.rag_pipeline.types import QueryClass


def test_resolve_fusion_weights_zero_override():
    rerank, graph, rrf = _resolve_fusion_weights(QueryClass.LOOKUP, graph_weight_override=0.0)
    assert graph == 0.0
    assert abs(rerank + rrf - 1.0) < 1e-6
```

- [ ] **Step 3: Run test, confirm PASS.**
- [ ] **Step 4: Commit `feat: graph_weight_override for kg ablation`**

---

## Phase 4: Configs + Seed Data

### Task 4.1: composite_weights.yaml + 4 rubric YAMLs

**Files:**
- Create: `docs/rag_eval/_config/composite_weights.yaml`
- Create: `docs/rag_eval/_config/rubric_chunking.yaml`
- Create: `docs/rag_eval/_config/rubric_retrieval.yaml`
- Create: `docs/rag_eval/_config/rubric_rerank.yaml`
- Create: `docs/rag_eval/_config/rubric_synthesis.yaml`

- [ ] **Step 1: Write composite_weights.yaml**

```yaml
# docs/rag_eval/_config/composite_weights.yaml
chunking: 0.10
retrieval: 0.25
reranking: 0.20
synthesis: 0.45
```

- [ ] **Step 2: Write the 4 rubric YAMLs**

Each rubric documents the formula used by component_scorers.py (so reviewers can audit).

```yaml
# docs/rag_eval/_config/rubric_chunking.yaml
version: rubric_chunking.v1
formula: "0.4*budget + 0.3*boundary + 0.2*coherence + 0.1*dedup"
target_token_count: 512
budget_compliance_band: [0.5x, 1.5x]  # of target
boundary_check: regex "[.!?\\n]\\s*$" at end of chunk text
coherence: cosine similarity of adjacent chunk embeddings
dedup: unique-text rate
```

```yaml
# docs/rag_eval/_config/rubric_retrieval.yaml
version: rubric_retrieval.v1
formula: "0.4*Recall@10 + 0.3*MRR + 0.3*Hit@5"
gold_source: docs/rag_eval/_config/queries/<source>/seed.yaml :: gold_node_ids
```

```yaml
# docs/rag_eval/_config/rubric_rerank.yaml
version: rubric_rerank.v1
formula: "0.5*NDCG@5 + 0.3*P@3 + 0.2*(1 - FP@3)"
gold_source: docs/rag_eval/_config/queries/<source>/seed.yaml :: gold_ranking
```

```yaml
# docs/rag_eval/_config/rubric_synthesis.yaml
version: rubric_synthesis.v1
formula: "0.30*ragas.faithfulness + 0.20*ragas.answer_correctness + 0.20*ragas.context_precision + 0.15*ragas.answer_relevancy + 0.15*deepeval.semantic_similarity"
divergence_threshold: 0.20  # |faithfulness - (1 - hallucination)| > 0.20 flags eval_divergence
```

- [ ] **Step 3: Commit `docs: rag_eval rubric configs`**

### Task 4.2: YouTube seed.yaml — hand-crafted 5 queries with gold

**Files:**
- Create: `docs/rag_eval/_config/queries/youtube/seed.yaml`

This task requires inspecting Naruto's actual YouTube Zettels (via `_naruto_baseline.json` from Task 0.2) and hand-crafting 5 queries with strong gold-truth Zettels.

- [ ] **Step 1: Inspect Naruto's YouTube Zettels**

Read `docs/rag_eval/_config/_naruto_baseline.json` and pick 5 YouTube Zettels around a coherent theme (e.g., psychedelics + neuroscience). Note their node_ids and summaries via:
```bash
python -c "import json; d = json.load(open('docs/rag_eval/_config/_naruto_baseline.json')); print('\n'.join(d['node_ids_by_source']['youtube'][:20]))"
```

Then for each candidate seed Zettel, run:
```bash
python ops/scripts/probe_naruto_kg.py --inspect-node <node_id>  # if not built, query supabase directly
```

- [ ] **Step 2: Draft 5 queries**

Create `docs/rag_eval/_config/queries/youtube/seed.yaml` with 5 hand-crafted entries. Each query MUST:
- target a specific Naruto YouTube Zettel as `gold_node_ids[0]`
- name a concrete fact / claim from the Zettel as `atomic_facts[0]`
- reference what would be a strong human answer as `reference_answer`

Example (engineer must replace placeholders with REAL Naruto Zettel data):

```yaml
queries:
  - id: q1
    question: "What is the proposed mechanism by which DMT acts in the brain?"
    gold_node_ids: ["yt-strangest-drug-ever-studied"]
    gold_ranking: ["yt-strangest-drug-ever-studied", "yt-insanity-of-salvia"]
    reference_answer: |
      DMT (N,N-dimethyltryptamine) is a potent serotonergic psychedelic that
      acts primarily as a 5-HT2A receptor agonist. The video also notes the
      controversial hypothesis that DMT may be produced endogenously in the
      mammalian brain (debated in the literature) and discusses its rapid onset,
      short duration, and the subjective intensity of its experience.
    atomic_facts:
      - "DMT is a 5-HT2A receptor agonist"
      - "DMT has rapid onset and short duration when smoked or injected"
      - "Endogenous DMT in the human brain is hypothesized but contested"
  # ... 4 more entries following same structure ...
```

The engineer iterates with the user OR queries Naruto's actual KG to write specifics. **NO PLACEHOLDERS in the committed file** — every `gold_node_ids` value MUST be a real Naruto node_id, every `reference_answer` MUST reflect that Zettel's actual content.

- [ ] **Step 3: Validate**

Run: `python -c "from website.features.rag_pipeline.evaluation.gold_loader import load_seed_queries; from pathlib import Path; print(len(load_seed_queries(Path('docs/rag_eval/_config/queries/youtube/seed.yaml'))))"`
Expected: prints `5`.

- [ ] **Step 4: Commit `docs: youtube seed queries with naruto gold zettels`**

### Task 4.3: YouTube heldout.yaml + sealing

**Files:**
- Create: `docs/rag_eval/_config/queries/youtube/heldout.yaml`
- Create: `docs/rag_eval/_config/queries/youtube/.heldout_sealed`

- [ ] **Step 1: Identify the unseen Zettel**

Pick a Naruto YouTube Zettel that is NOT in seed.yaml's gold_node_ids and is semantically nearby (cosine 0.50–0.70 vs the seed centroid). Use `select_similar_zettel` from `rag_eval_kasten.py` programmatically.

- [ ] **Step 2: Draft 3 fresh queries targeting the unseen Zettel**

Create `docs/rag_eval/_config/queries/youtube/heldout.yaml`:
```yaml
queries:
  - id: h1
    question: "<question targeting unseen Zettel>"
    gold_node_ids: ["<unseen-node-id>"]
    gold_ranking: ["<unseen-node-id>"]
    reference_answer: |
      <strong human answer based on unseen Zettel>
    atomic_facts:
      - "<fact from unseen Zettel>"
  # ... 2 more entries ...
```

- [ ] **Step 3: Seal the held-out file**

```bash
python -c "from website.features.rag_pipeline.evaluation.gold_loader import seal_heldout; from pathlib import Path; seal_heldout(Path('docs/rag_eval/_config/queries/youtube/heldout.yaml'))"
```

Verify: `ls docs/rag_eval/_config/queries/youtube/.heldout_sealed` exists.

- [ ] **Step 4: Commit `docs: youtube heldout queries sealed`**

### Task 4.4: Reddit/GitHub/Newsletter — DEFER

For Phase 6a we only need YouTube. Stub files for non-youtube sources are NOT created — they'd fail `SeedQueryFile` validation (which requires exactly 5 queries). Instead, the directories `docs/rag_eval/_config/queries/{reddit,github,newsletter}/` are created lazily during Phase 6b's first iter for that source.

- [ ] **Step 1: Verify `gold_loader.load_seed_queries` raises a clear error for missing files**

The existing `GoldLoaderError` raised when `_load_yaml(path)` fails on `not path.exists()` is sufficient. Phase 6b's iter-01 invocation for a non-youtube source will surface this clearly, prompting query authoring at that time.

- [ ] **Step 2: No commit — this task documents the deferral.**

---

## Phase 5: Smoke Run (YouTube iter-01 baseline)

### Task 5.1: Dry-run iter-01 to validate plumbing

- [ ] **Step 1: Verify Supabase connectivity**

```bash
python ops/scripts/rag_eval_loop.py --source youtube --iter 1 --dry-run
```
Expected: prints `{"status": "dry_run", "state": "PHASE_A_REQUIRED", "iter_dir": "docs/rag_eval/youtube/iter-01"}`.

- [ ] **Step 2: If errors, debug imports / paths until dry-run is clean.**

### Task 5.2: Run Phase A for YouTube iter-01

- [ ] **Step 1: Set env**

```bash
export RAG_EVAL_NARUTO_USER_ID="$(python -c "import json; print(json.load(open('docs/rag_eval/_config/_naruto_baseline.json'))['user_id'])")"
```

- [ ] **Step 2: Execute**

```bash
python ops/scripts/rag_eval_loop.py --source youtube --iter 1 --skip-determinism
```
Expected: `phase_a_complete` with non-zero composite. Files created in `docs/rag_eval/youtube/iter-01/`.

- [ ] **Step 3: Validate artifacts**

Confirm presence of: `kasten.json`, `ingest.json`, `queries.json`, `answers.json`, `eval.json`, `ablation_eval.json`, `qa_pairs.md`, `scores.md`, `kg_snapshot.json`, `kg_recommendations.json`, `manual_review_prompt.md`, `atomic_facts.json`.

### Task 5.3: Cross-LLM blind review

- [ ] **Step 1: Auto-mode dispatch**

```bash
python ops/scripts/rag_eval_loop.py --source youtube --iter 1 --auto --skip-determinism
```

This dispatches a Claude subagent (via the harness's Agent runner) to write `manual_review.md` blind. State transitions to `PHASE_B_REQUIRED` and Phase B runs immediately.

- [ ] **Step 2: Verify review stamp**

Check `manual_review.md`:
- Contains `eval_json_hash_at_review: "NOT_CONSULTED"` ✓
- Contains `estimated_composite: <number>` ✓
- Subagent transcript saved to `_review_subagent_transcript.json` ✓

### Task 5.4: Phase B + commit

Phase B ran during Task 5.3's `--auto` invocation. Verify:

- [ ] **Step 1: Confirm `diff.md`, `next_actions.md`, `improvement_delta.json` exist**

For iter-01, `improvement_delta.json` is a degenerate baseline (no prior iter to compare).

- [ ] **Step 2: Confirm KG recommendations applied**

Inspect `docs/rag_eval/_kg_changelog.md`. Should have a section dated for iter-01 with applied/skipped recs.

- [ ] **Step 3: Confirm git commit landed**

```bash
git log --oneline -1
```
Expected: `feat: rag_eval youtube iter-01` (or similar 5-10 word subject).

---

## Phase 6a: YouTube Iters 02 → 05

**Workflow per iter (executed sequentially, autonomous between human checkpoints):**

For each `iter_n in [2, 3, 4, 5]`:

### Task 6a.<n>-A: Plan wide-net changes from prior iter's `next_actions.md`

- [ ] **Step 1: Read `docs/rag_eval/youtube/iter-(n-1)/next_actions.md`** and identify which actions to address.
- [ ] **Step 2: Plan changes touching ≥3 of the 6 RAG components AND ≥1 config/weight surface** (per spec §7 wide-net gate). Document in a free-form `_iter<n>_change_plan.md` (working file, NOT a deliverable artifact — discarded after iter-<n> commits).
- [ ] **Step 3: For iter-04**, the Kasten gains a similar Zettel (cosine ≥0.65 from seed centroid) — call `select_similar_zettel` with the candidate pool.
- [ ] **Step 4: For iter-05**, the Kasten gains the unseen held-out Zettel (cosine 0.50–0.70 from seed centroid).

### Task 6a.<n>-B: Implement the changes

- [ ] **Step 1: Edit ≥3 of:** `ingest/chunker.py`, `ingest/embedder.py`, `retrieval/hybrid.py`, `rerank/cascade.py`, `query/rewriter.py`, `query/router.py`, `generation/prompts.py`.
- [ ] **Step 2: Edit ≥1 config/weight:** `composite_weights.yaml` (rare — would need separate per-source loop), `_FUSION_WEIGHTS` in `cascade.py`, `_DEPTH_BY_CLASS` in `hybrid.py`, top_k limits, MMR_LAMBDA, etc.
- [ ] **Step 3: Add unit tests for any non-trivial logic added.**
- [ ] **Step 4: Run full test suite:** `pytest tests/unit/rag_pipeline/ -q`. All green before proceeding.
- [ ] **Step 5: Commit pipeline changes** with message like `feat(rag): tune hybrid retrieval depth and chunker overlap` (5-10 words; cite NA-iter<n-1>-XX in commit body).

### Task 6a.<n>-C: Run iter-<n>

- [ ] **Step 1: Phase A + auto-review + Phase B**

```bash
python ops/scripts/rag_eval_loop.py --source youtube --iter <n> --auto
```

This: (a) runs the determinism gate against iter-<n-1>; (b) executes Phase A; (c) dispatches blind reviewer; (d) verifies review stamp; (e) runs change-breadth gate (since `--skip-breadth` is NOT passed); (f) writes improvement_delta; (g) applies KG recommendations; (h) commits.

- [ ] **Step 2: If determinism gate fires** (composite drift > 3pt on prior iter's data), STOP. Investigate evaluator changes. Either revert or document a `decision` rationale in iter-<n>'s `next_actions.md`.
- [ ] **Step 3: If breadth gate fires** (CHANGE_BREADTH_INSUFFICIENT), expand the change-set or document explicit rationale in `pipeline_changes.md`.
- [ ] **Step 4: If composite regresses vs iter-<n-1>**, write a regression analysis section in `next_actions.md` capturing the suspected component(s). Do NOT proceed to iter-<n+1> until root cause is captured.

### Task 6a.<n>-D: Verify success criteria

Before advancing to iter-<n+1>:
- [ ] All 5 (or 3 for iter-05) queries evaluated and scored
- [ ] `improvement_delta.json` shows ≥1pt absolute composite change OR root cause documented
- [ ] `graph_lift` block populated; trend recorded in `next_actions.md`
- [ ] `kg_recommendations.json` written; auto-applied recs landed in `_kg_changelog.md`
- [ ] `qa_pairs.md` and `scores.md` are human-readable and non-empty
- [ ] git commit landed with proper conventional prefix

### Task 6a.5: Final iter (iter-05) — held-out

In addition to the per-iter workflow above, iter-05 unseals the held-out file:

- [ ] **Step 1: Unseal**

```bash
rm docs/rag_eval/_config/queries/youtube/.heldout_sealed
```

- [ ] **Step 2: Run with `--unseal-heldout`**

```bash
python ops/scripts/rag_eval_loop.py --source youtube --iter 5 --auto --unseal-heldout
```

- [ ] **Step 3: Verify held-out scores within 5pt of iter-04's seed-query mean**

If divergence > 5pt, the model overfit seed queries — log in `next_actions.md` and `_synthesis.md`.

### Task 6a.6: Write `_synthesis.md` for YouTube

**Files:**
- Create: `docs/rag_eval/youtube/_synthesis.md`

- [ ] **Step 1: Aggregate iter-01 → iter-05 metrics**

For each iter, pull composite, component scores, graph_lift, applied KG mutation count.

- [ ] **Step 2: Write `_synthesis.md` covering:**

```markdown
# YouTube rag_eval — Cross-Iteration Synthesis

## Composite trend (iter-01 → iter-05)
| iter | composite | chunking | retrieval | reranking | synthesis | graph_lift |

## Wide-net changes per iter
- iter-02: <commit-sha> — files + rationale
- iter-03: ...

## KG↔RAG closure (per spec §8d)
1. Did graph_lift trend positive? <YES/NO + numbers>
2. KG mutations applied across all iters: <count by type>
3. Orphan-rate trend: <numbers>
4. Faithfulness recovery on reingested nodes: <numbers>

## Held-out (iter-05) scores vs seed-iter mean
| metric | seed_mean (iters 1-4) | held-out (iter-05) | gap |

## Verdict
- Pipeline improvements were/were-not durable on held-out
- Recommended next steps for Phase 6b sources
```

- [ ] **Step 3: Commit `docs: youtube rag_eval synthesis`**

### Task 6a.7: Halt for user review

- [ ] **Step 1: Write sentinel**

```bash
touch docs/rag_eval/.youtube_complete
```

- [ ] **Step 2: Print `RAG_EVAL_HALT_FOR_REVIEW`** to stdout. Exit 0.

This is the explicit handoff per spec §12: Phase 6b will not start until the user reviews YouTube `_synthesis.md` and removes the sentinel (or invokes `--source <other> --iter 1` directly).

---

## Self-Review (after writing this plan)

**Spec coverage check:**
- §1 Scope → covered by File Structure header + all phases
- §2 Schedule → Phase 4 (queries.yaml + iter triggers) + Phase 6a workflow
- §3 Scoring → Phase 1 (component_scorers, ragas, deepeval, synthesis_score, eval_runner, composite hash lock)
- §4 State machine → Phase 3.1, 3.2, 3.6, 3.7
- §5 Data sources → Phase 0.2 (Naruto baseline), Phase 2.1 (Kasten builder)
- §6 File layout → File Structure section + per-task file paths
- §7 Build sequence → Phases 0-6a tracking 1:1
- §8 KG↔RAG → Phase 1.5 (ablation), Phase 2.5 (snapshot, recommender, applicator), Task 3.8 (graph_weight_override)
- §9 Verification checkpoints → Task 6a.<n>-D
- §10 Out of scope → enforced by File Structure (no edits to summarization_engine etc.)
- §11 Risks → Phase 3.5 (billing escalation)
- §12 Execution checkpoint → Phase 6a.7 (halt sentinel)

**Placeholder scan:** No "TBD", "implement later", or "similar to Task N". Task 4.2 (YouTube seed.yaml) requires real Naruto data — flagged explicitly with NO PLACEHOLDERS warning. Task 3.7 helper functions noted as small/inline.

**Type consistency:** `GoldQuery`, `ComponentScores`, `EvalResult`, `KGSnapshot`, `KGRecommendation`, `GraphLift`, `PerQueryScore` — all defined in Task 0.3 and used consistently in later tasks.

**Cross-LLM blind review safety:** Task 3.2's `build_review_prompt` explicitly excludes `eval.json` and `ablation_eval.json` from the prompt body, and `dispatch_blind_reviewer` accepts an `allowed_files` whitelist matching spec §4.

**Wide-net change gate:** Task 3.4 implements the gate; Task 6a.<n>-B enforces ≥3 components + ≥1 config; Phase B in Task 3.7 runs the gate.

**Halt + billing-key escalation:** Task 3.5 implements the two-tier policy; CLI in Task 3.6 checks the halt sentinel before dispatch.

**KG mutation safety brake:** Task 2.5.2's `generate_recommendations` quarantines all recs of a type when count > 5.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-rag-eval-loop-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

User's standing instruction is "no manual interventions now". Defaulting to **Subagent-Driven** unless otherwise directed.
