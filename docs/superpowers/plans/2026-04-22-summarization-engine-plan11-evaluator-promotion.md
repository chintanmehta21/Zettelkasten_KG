# Summarization Engine Plan 11 — Evaluator Promotion for Cross-Feature Reuse

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the evaluator module from `website/features/summarization_engine/evaluator/` (narrow: summary scoring) to `website/features/evaluation/` (broad: also scores RAG responses + chat replies). Preserve all existing summary-scoring callers via a thin shim; add new abstractions so RAG/chat evaluators can share rubric-loader + consolidated-LLM-judge infrastructure.

**Architecture:** Three-layer refactor:
1. `website/features/evaluation/core/` — source-agnostic primitives: `RubricLoader`, `ConsolidatedLLMJudge`, `CompositeScorer`, `RagasBridge`, `BaseEvalResult`. Each accepts a generic payload (summary / RAG citation list / chat turn) instead of a hardcoded SummaryResult.
2. `website/features/evaluation/summarization/` — summarization-specific subclasses of the core. Thin re-exports so `from website.features.summarization_engine.evaluator import evaluate` keeps working via an alias module.
3. `website/features/evaluation/rag/` — RAG response evaluator stub + first working metric (answer-faithfulness against citations).

**Tech Stack:** Python 3.12, Pydantic v2, existing `ragas` dep, Gemini via the existing `TieredGeminiClient`. Pure refactor + extension; no new runtime deps.

**Reference spec:** `docs/superpowers/specs/2026-04-21-summarization-engine-scoring-optimization-design.md` §12 item 3 (post-program follow-up).

**Branch:** `feat/evaluator-promotion`, off `master` AFTER Plan 10's PR merges + deploy verified.

**Precondition:** Plan 10 merged. `website/features/summarization_engine/evaluator/` exists from Plans 1 & 6-9. Existing RAG evaluator at `docs/superpowers/plans/2026-04-18-rag-e2e-eval.md` is a separate plan — read its current state before starting to avoid collision.

**Deploy discipline:** Pure refactor with a shim for backward compat. Mergeable with low risk. Still: draft PR + human approval before merge.

---

## Critical safety constraints

### 1. Backward compat of imports
Every existing caller of `from website.features.summarization_engine.evaluator import evaluate, EvalResult, composite_score` MUST continue to work unchanged. A shim module at the old path re-exports the new API.

### 2. No on-wire behavior change
Evaluator output schema stays identical (spec §3.2). Callers receive the same `EvalResult` Pydantic object. The `evaluator/prompts.py` PROMPT_VERSION stays at `"evaluator.v1"` (bumping would force re-scoring of every historical iter-NN/eval.json).

### 3. No iteration-loop regression
After the refactor, `python ops/scripts/eval_loop.py --source youtube --iter 1 --replay` must reproduce the existing iter-01 composite within ±1 pt. If not, the refactor changed evaluator behavior accidentally — halt and investigate.

### 4. No evaluator config duplication
`docs/summary_eval/_config/rubric_*.yaml` stays the canonical rubric location. RAG + chat evaluators add their own rubric YAMLs (e.g., `docs/rag_eval/_config/rubric_rag_response.yaml`) — the shared `RubricLoader` handles both.

---

## File structure summary

### Files to CREATE
- `website/features/evaluation/__init__.py` (public package)
- `website/features/evaluation/core/__init__.py`
- `website/features/evaluation/core/models.py` — `BaseEvalResult`, `BaseRubricBreakdown`, `CompositeScorer`, generic `apply_caps`
- `website/features/evaluation/core/rubric_loader.py` — source-agnostic YAML loader
- `website/features/evaluation/core/llm_judge.py` — generic `ConsolidatedLLMJudge` (takes prompt template + payload)
- `website/features/evaluation/core/ragas_bridge.py` — moved unchanged from summarization_engine
- `website/features/evaluation/core/cache.py` — moved unchanged
- `website/features/evaluation/summarization/__init__.py`
- `website/features/evaluation/summarization/consolidated.py` — `SummarizationLLMJudge(ConsolidatedLLMJudge)` subclass
- `website/features/evaluation/summarization/models.py` — `SummaryEvalResult(BaseEvalResult)` with summary-specific fields
- `website/features/evaluation/summarization/atomic_facts.py` — moved unchanged
- `website/features/evaluation/summarization/manual_review_writer.py` — moved unchanged
- `website/features/evaluation/summarization/next_actions.py` — moved unchanged
- `website/features/evaluation/summarization/prompts.py` — moved unchanged (PROMPT_VERSION stays "evaluator.v1")
- `website/features/evaluation/rag/__init__.py`
- `website/features/evaluation/rag/models.py` — `RagEvalResult` with citation-faithfulness fields
- `website/features/evaluation/rag/faithfulness.py` — RAG answer-vs-citations faithfulness metric
- `tests/unit/evaluation/core/test_models.py`
- `tests/unit/evaluation/core/test_rubric_loader.py`
- `tests/unit/evaluation/core/test_llm_judge.py`
- `tests/unit/evaluation/summarization/test_backward_compat.py`
- `tests/unit/evaluation/rag/test_faithfulness.py`

### Files to CREATE as shims (backward compat)
- `website/features/summarization_engine/evaluator/__init__.py` (rewritten as re-export shim)
- `website/features/summarization_engine/evaluator/models.py` (shim)
- `website/features/summarization_engine/evaluator/rubric_loader.py` (shim)
- `website/features/summarization_engine/evaluator/consolidated.py` (shim)
- `website/features/summarization_engine/evaluator/ragas_bridge.py` (shim)
- `website/features/summarization_engine/evaluator/atomic_facts.py` (shim)
- `website/features/summarization_engine/evaluator/manual_review_writer.py` (shim)
- `website/features/summarization_engine/evaluator/next_actions.py` (shim)
- `website/features/summarization_engine/evaluator/prompts.py` (shim)
- `website/features/summarization_engine/evaluator/cache.py` (shim)

---

## Task 0: Branch + preconditions

- [ ] **Step 1: Preconditions**

```bash
cd /c/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault
git checkout master && git pull
python -c "from website.features.summarization_engine.evaluator import evaluate; print('import OK')"
python ops/scripts/eval_loop.py --source youtube --iter 1 --replay 2>&1 | tail -3
```
If replay fails OR import fails, previous plans haven't fully landed. Abort.

- [ ] **Step 2: Record baseline replay composite**

```bash
python -c "
import json
from pathlib import Path
e = json.loads(Path('docs/summary_eval/youtube/iter-01/eval.json').read_text())
if isinstance(e, list): e = e[0]
print('baseline_iter01_composite:', e.get('composite_score_cached', 'inspect eval.json manually'))
"
```
Save this number; Task 6 compares against it.

- [ ] **Step 3: Create branch**

```bash
git checkout -b feat/evaluator-promotion
git push -u origin feat/evaluator-promotion
```

---

## Task 1: Create `evaluation/core` — generic primitives

**Files:**
- Create: `website/features/evaluation/__init__.py`, `website/features/evaluation/core/__init__.py`
- Create: `website/features/evaluation/core/models.py`
- Test: `tests/unit/evaluation/core/test_models.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/evaluation/core/test_models.py
from website.features.evaluation.core.models import (
    BaseRubricComponent, BaseRubricBreakdown, AntiPatternTrigger,
    CapsApplied, apply_caps,
)


def test_apply_caps_hallucination_dominates():
    caps = CapsApplied(hallucination_cap=60, omission_cap=None, generic_cap=None)
    assert apply_caps(95.0, caps) == 60.0


def test_apply_caps_omission_second_priority():
    caps = CapsApplied(hallucination_cap=None, omission_cap=75, generic_cap=None)
    assert apply_caps(95.0, caps) == 75.0


def test_apply_caps_generic_last_priority():
    caps = CapsApplied(hallucination_cap=None, omission_cap=None, generic_cap=90)
    assert apply_caps(95.0, caps) == 90.0


def test_apply_caps_no_caps_passthrough():
    caps = CapsApplied(hallucination_cap=None, omission_cap=None, generic_cap=None)
    assert apply_caps(87.5, caps) == 87.5


def test_rubric_breakdown_total_of_100_sums_components():
    br = BaseRubricBreakdown(
        components=[
            BaseRubricComponent(id="a", score=20, max_points=25),
            BaseRubricComponent(id="b", score=40, max_points=45),
            BaseRubricComponent(id="c", score=12, max_points=15),
            BaseRubricComponent(id="d", score=14, max_points=15),
        ],
        caps_applied=CapsApplied(hallucination_cap=None, omission_cap=None, generic_cap=None),
        anti_patterns_triggered=[],
    )
    assert br.total_of_100 == 86
```

- [ ] **Step 2: Create `website/features/evaluation/__init__.py`**

```python
"""Evaluation package — shared primitives for summarization, RAG, chat evaluators."""
```

- [ ] **Step 3: Create `core/__init__.py`**

```python
"""Core primitives: rubric loader, consolidated LLM judge, composite scorer, caps, cache."""
```

- [ ] **Step 4: Create `core/models.py`**

```python
"""Source-agnostic eval primitives."""
from __future__ import annotations

from pydantic import BaseModel, Field


class BaseRubricComponent(BaseModel):
    id: str
    score: float
    max_points: int
    criteria_fired: list[str] = Field(default_factory=list)
    criteria_missed: list[str] = Field(default_factory=list)


class AntiPatternTrigger(BaseModel):
    id: str
    source_region: str = ""
    auto_cap: int | None = None


class CapsApplied(BaseModel):
    hallucination_cap: int | None = None
    omission_cap: int | None = None
    generic_cap: int | None = None


class BaseRubricBreakdown(BaseModel):
    components: list[BaseRubricComponent]
    caps_applied: CapsApplied
    anti_patterns_triggered: list[AntiPatternTrigger] = Field(default_factory=list)

    @property
    def total_of_100(self) -> float:
        return sum(c.score for c in self.components)


class BaseEvalResult(BaseModel):
    """Common shape every evaluator returns. Subclasses add domain-specific fields."""
    rubric: BaseRubricBreakdown
    evaluator_metadata: dict = Field(default_factory=dict)


def apply_caps(score: float, caps: CapsApplied) -> float:
    """First-match-wins cap dominance, per spec §3.6."""
    if caps.hallucination_cap is not None:
        return min(score, float(caps.hallucination_cap))
    if caps.omission_cap is not None:
        return min(score, float(caps.omission_cap))
    if caps.generic_cap is not None:
        return min(score, float(caps.generic_cap))
    return score
```

- [ ] **Step 5: Run test + commit**

```bash
pytest tests/unit/evaluation/core/test_models.py -v
git add website/features/evaluation/__init__.py website/features/evaluation/core/ tests/unit/evaluation/core/test_models.py
git commit -m "feat: evaluation core primitives"
```

---

## Task 2: Move + generalize `RubricLoader`

**Files:**
- Create: `website/features/evaluation/core/rubric_loader.py`
- Test: `tests/unit/evaluation/core/test_rubric_loader.py`

- [ ] **Step 1: Write test**

```python
# tests/unit/evaluation/core/test_rubric_loader.py
from pathlib import Path
import pytest
from website.features.evaluation.core.rubric_loader import load_rubric, RubricSchemaError


def test_load_rubric_validates_version_and_total(tmp_path):
    good = tmp_path / "rubric.yaml"
    good.write_text("""
version: rubric.v1
source_type: any
composite_max_points: 100
components:
  - id: a
    max_points: 60
  - id: b
    max_points: 40
""", encoding="utf-8")
    rubric = load_rubric(good)
    assert rubric["version"] == "rubric.v1"


def test_load_rubric_rejects_mismatched_total(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("""
version: rubric.v1
source_type: any
composite_max_points: 100
components:
  - id: a
    max_points: 50
""", encoding="utf-8")
    with pytest.raises(RubricSchemaError):
        load_rubric(bad)
```

- [ ] **Step 2: Create `core/rubric_loader.py`** (generalized from summarization version):

```python
"""Generic rubric YAML loader — works for any eval source."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class RubricSchemaError(ValueError):
    """Raised when a rubric YAML is malformed."""


_REQUIRED_KEYS = {"version", "source_type", "composite_max_points", "components"}


def load_rubric(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    missing = _REQUIRED_KEYS - set(data.keys())
    if missing:
        raise RubricSchemaError(f"rubric {path} missing required keys: {sorted(missing)}")
    total = sum(c.get("max_points", 0) for c in data.get("components", []))
    if total != data.get("composite_max_points", 100):
        raise RubricSchemaError(
            f"rubric {path} component max_points sum {total} != composite_max_points {data['composite_max_points']}"
        )
    return data
```

- [ ] **Step 3: Run test + commit**

```bash
pytest tests/unit/evaluation/core/test_rubric_loader.py -v
git add website/features/evaluation/core/rubric_loader.py tests/unit/evaluation/core/test_rubric_loader.py
git commit -m "feat: evaluation core rubric loader generic"
```

---

## Task 3: Create generic `ConsolidatedLLMJudge`

**Files:**
- Create: `website/features/evaluation/core/llm_judge.py`
- Test: `tests/unit/evaluation/core/test_llm_judge.py`

- [ ] **Step 1: Write test**

```python
# tests/unit/evaluation/core/test_llm_judge.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from website.features.evaluation.core.llm_judge import ConsolidatedLLMJudge


@pytest.mark.asyncio
async def test_judge_parses_json_response_and_stamps_metadata():
    client = MagicMock()
    client.generate = AsyncMock(return_value=MagicMock(
        text='{"rubric": {"components": [{"id": "a", "score": 20, "max_points": 25}], "caps_applied": {"hallucination_cap": null, "omission_cap": null, "generic_cap": null}, "anti_patterns_triggered": []}, "custom": "ok"}',
        input_tokens=100, output_tokens=50,
    ))
    judge = ConsolidatedLLMJudge(client=client, prompt_version="test.v1")
    payload = await judge.run(prompt="test prompt", tier="pro", system_instruction="test sys")
    assert payload["custom"] == "ok"
    assert "evaluator_metadata" in payload
    assert payload["evaluator_metadata"]["prompt_version"] == "test.v1"
    assert payload["evaluator_metadata"]["total_tokens_in"] == 100
```

- [ ] **Step 2: Create `core/llm_judge.py`**

```python
"""Generic consolidated LLM judge — prompt-in, JSON-out, metadata-stamped."""
from __future__ import annotations

import json
import time
from typing import Any

from website.features.summarization_engine.summarization.common.json_utils import parse_json_object


class ConsolidatedLLMJudge:
    def __init__(self, *, client: Any, prompt_version: str) -> None:
        self._client = client
        self._prompt_version = prompt_version

    async def run(self, *, prompt: str, tier: str = "pro",
                  system_instruction: str | None = None,
                  temperature: float = 0.0) -> dict:
        t0 = time.perf_counter()
        result = await self._client.generate(
            prompt, tier=tier,
            system_instruction=system_instruction or "",
            temperature=temperature,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        text = (result.text or "").strip()
        try:
            payload = parse_json_object(text) if text.startswith("{") else json.loads(text)
        except Exception as exc:
            raise RuntimeError(f"LLM judge returned non-JSON: {exc}")
        payload.setdefault("evaluator_metadata", {})
        payload["evaluator_metadata"].setdefault("prompt_version", self._prompt_version)
        payload["evaluator_metadata"]["total_tokens_in"] = getattr(result, "input_tokens", 0)
        payload["evaluator_metadata"]["total_tokens_out"] = getattr(result, "output_tokens", 0)
        payload["evaluator_metadata"]["latency_ms"] = latency_ms
        return payload
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/evaluation/core/test_llm_judge.py -v
git add website/features/evaluation/core/llm_judge.py tests/unit/evaluation/core/test_llm_judge.py
git commit -m "feat: evaluation core consolidated llm judge"
```

---

## Task 4: Move RAGAS bridge + cache from summarization_engine

**Files:**
- Move: `website/features/summarization_engine/evaluator/ragas_bridge.py` → `website/features/evaluation/core/ragas_bridge.py`
- Move: `website/features/summarization_engine/evaluator/cache.py` → `website/features/evaluation/core/cache.py` (if cache.py exists there; else `core/cache.py` created fresh matching `summarization_engine/core/cache.py`)

- [ ] **Step 1: Copy files**

```bash
cp website/features/summarization_engine/evaluator/ragas_bridge.py website/features/evaluation/core/ragas_bridge.py
cp website/features/summarization_engine/evaluator/cache.py website/features/evaluation/core/cache.py 2>/dev/null || cp website/features/summarization_engine/core/cache.py website/features/evaluation/core/cache.py
```

- [ ] **Step 2: Run any tests that touch these**

```bash
pytest tests/unit/summarization_engine/evaluator/ -v
```
Expected: all pass (nothing broken yet because we haven't modified the old location).

- [ ] **Step 3: Commit**

```bash
git add website/features/evaluation/core/ragas_bridge.py website/features/evaluation/core/cache.py
git commit -m "feat: move ragas bridge and cache to evaluation core"
```

---

## Task 5: Move summarization-specific files into `evaluation/summarization/`

**Files:**
- Move the following from `website/features/summarization_engine/evaluator/` to `website/features/evaluation/summarization/`:
  - `atomic_facts.py`
  - `manual_review_writer.py`
  - `next_actions.py`
  - `prompts.py` (PROMPT_VERSION must stay `"evaluator.v1"`)

- [ ] **Step 1: Create `evaluation/summarization/__init__.py`**

```python
"""Summarization-specific evaluator: subclasses of evaluation/core primitives."""
```

- [ ] **Step 2: Copy files + update internal imports**

```bash
cp website/features/summarization_engine/evaluator/atomic_facts.py website/features/evaluation/summarization/atomic_facts.py
cp website/features/summarization_engine/evaluator/manual_review_writer.py website/features/evaluation/summarization/manual_review_writer.py
cp website/features/summarization_engine/evaluator/next_actions.py website/features/evaluation/summarization/next_actions.py
cp website/features/summarization_engine/evaluator/prompts.py website/features/evaluation/summarization/prompts.py
```

Then, in each moved file, update imports like:
- `from website.features.summarization_engine.core.cache import FsContentCache` → unchanged (core/cache.py lives in summarization_engine; don't touch that)
- `from website.features.summarization_engine.evaluator.prompts import ...` → `from website.features.evaluation.summarization.prompts import ...`

Keep PROMPT_VERSION = "evaluator.v1" verbatim in prompts.py.

- [ ] **Step 3: Create `evaluation/summarization/consolidated.py`** as a subclass using `ConsolidatedLLMJudge`:

```python
"""Summarization evaluator using generic ConsolidatedLLMJudge."""
from __future__ import annotations

import json
from typing import Any

import yaml

from website.features.evaluation.core.llm_judge import ConsolidatedLLMJudge
from website.features.evaluation.summarization.prompts import (
    CONSOLIDATED_SYSTEM, CONSOLIDATED_USER_TEMPLATE, PROMPT_VERSION,
)


class SummarizationLLMJudge:
    """Summarization-specific wrapper around ConsolidatedLLMJudge."""

    def __init__(self, gemini_client: Any) -> None:
        self._judge = ConsolidatedLLMJudge(client=gemini_client, prompt_version=PROMPT_VERSION)

    async def evaluate(
        self, *, rubric_yaml: dict, atomic_facts: list[dict],
        source_text: str, summary_json: dict,
    ) -> dict:
        prompt = CONSOLIDATED_USER_TEMPLATE.format(
            rubric_yaml=yaml.safe_dump(rubric_yaml, sort_keys=False),
            atomic_facts=json.dumps(atomic_facts, indent=2),
            source_text=source_text[:30000],
            summary_json=json.dumps(summary_json, indent=2),
        )
        payload = await self._judge.run(
            prompt=prompt, tier="pro",
            system_instruction=CONSOLIDATED_SYSTEM, temperature=0.0,
        )
        payload["evaluator_metadata"].setdefault("rubric_version", rubric_yaml.get("version", "unknown"))
        return payload
```

- [ ] **Step 4: Create `evaluation/summarization/models.py`** — re-exports `SummaryEvalResult`:

```python
"""Summarization-specific EvalResult. Re-uses base + adds domain fields."""
from __future__ import annotations

# For now, re-export the existing summarization EvalResult shape for 1:1 compat.
# Later, this module can diverge (add RAG-shared fields, strip unused ones, etc.) without
# breaking the summarization_engine/evaluator shim.
from website.features.summarization_engine.evaluator.models import (  # noqa: F401
    EvalResult as SummaryEvalResult,
    GEvalScores,
    FineSurEScores,
    FineSurEDimension,
    FineSurEItem,
    SummaCLite,
    SummaCLiteSentence,
    RubricComponent,
    RubricBreakdown,
    AntiPatternTrigger,
    EditorializationFlag,
    composite_score,
    apply_caps,
)
```

- [ ] **Step 5: Commit**

```bash
git add website/features/evaluation/summarization/
git commit -m "feat: evaluation summarization subpackage"
```

---

## Task 6: Rewrite old locations as import shims (backward compat)

**Files:**
- Replace: `website/features/summarization_engine/evaluator/__init__.py`
- Replace: `website/features/summarization_engine/evaluator/models.py` → shim
- Replace: `website/features/summarization_engine/evaluator/rubric_loader.py` → shim
- Replace: `website/features/summarization_engine/evaluator/consolidated.py` → shim
- Replace: `website/features/summarization_engine/evaluator/ragas_bridge.py` → shim
- Replace: `website/features/summarization_engine/evaluator/atomic_facts.py` → shim
- Replace: `website/features/summarization_engine/evaluator/manual_review_writer.py` → shim
- Replace: `website/features/summarization_engine/evaluator/next_actions.py` → shim
- Replace: `website/features/summarization_engine/evaluator/prompts.py` → shim
- Replace: `website/features/summarization_engine/evaluator/cache.py` → shim

- [ ] **Step 1: Rewrite each module as re-export shim**

Example for `website/features/summarization_engine/evaluator/atomic_facts.py`:

```python
"""BACKWARD-COMPAT SHIM: moved to website.features.evaluation.summarization.atomic_facts.

New code should import from the new location. This shim stays indefinitely so old
artifacts and iter-loop scripts continue to work without edits.
"""
from website.features.evaluation.summarization.atomic_facts import *  # noqa: F401,F403
from website.features.evaluation.summarization.atomic_facts import extract_atomic_facts  # noqa: F401
```

Repeat the `from ... import *` pattern for every shim module. Each shim file is 5-10 lines.

For `evaluator/__init__.py`:

```python
"""BACKWARD-COMPAT SHIM: contents promoted to website.features.evaluation.

All new work uses `from website.features.evaluation.summarization import ...`.
"""
from website.features.evaluation.summarization.models import (  # noqa: F401
    SummaryEvalResult as EvalResult,
    composite_score,
)
from website.features.evaluation.summarization.atomic_facts import extract_atomic_facts  # noqa: F401


async def evaluate(**kwargs):
    """Shim — delegates to the new location's SummarizationLLMJudge pipeline."""
    # Preserve exact existing signature; see new implementation in
    # website/features/evaluation/summarization/__init__.py's `evaluate` if moved.
    from website.features.summarization_engine.evaluator._legacy_pipeline import evaluate as _evaluate
    return await _evaluate(**kwargs)
```

(If `_legacy_pipeline` doesn't exist, keep the original `__init__.py` body inline in the shim until Task 8 fully migrates it.)

- [ ] **Step 2: Write backward-compat test**

```python
# tests/unit/evaluation/summarization/test_backward_compat.py
def test_legacy_summary_evaluator_imports_still_work():
    from website.features.summarization_engine.evaluator import evaluate, EvalResult, composite_score  # noqa: F401
    from website.features.summarization_engine.evaluator.models import EvalResult as ER2  # noqa: F401
    from website.features.summarization_engine.evaluator.atomic_facts import extract_atomic_facts  # noqa: F401
    from website.features.summarization_engine.evaluator.manual_review_writer import verify_manual_review  # noqa: F401
    from website.features.summarization_engine.evaluator.prompts import PROMPT_VERSION  # noqa: F401
    assert PROMPT_VERSION == "evaluator.v1"
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/unit/ website/features/summarization_engine/tests/unit/ -q
```
Expected: all green. Old tests + new evaluation tests both pass.

- [ ] **Step 4: Run replay regression**

```bash
python ops/scripts/eval_loop.py --source youtube --iter 1 --replay
```
Expected: composite matches baseline (Task 0 Step 2) within ±1 pt. If not, imports went wrong somewhere.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/evaluator/ tests/unit/evaluation/summarization/test_backward_compat.py
git commit -m "refactor: evaluator shims for backward compat"
```

---

## Task 7: Add RAG response evaluator (new capability)

**Files:**
- Create: `website/features/evaluation/rag/__init__.py`
- Create: `website/features/evaluation/rag/models.py`
- Create: `website/features/evaluation/rag/faithfulness.py`
- Test: `tests/unit/evaluation/rag/test_faithfulness.py`

- [ ] **Step 1: Write test**

```python
# tests/unit/evaluation/rag/test_faithfulness.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from website.features.evaluation.rag.faithfulness import RagFaithfulnessEvaluator


@pytest.mark.asyncio
async def test_faithfulness_returns_score_and_violations():
    client = MagicMock()
    client.generate = AsyncMock(return_value=MagicMock(
        text='{"score": 0.85, "unsupported_claims": ["Answer said X but no citation supports"], "evaluator_metadata": {}}',
        input_tokens=200, output_tokens=40,
    ))
    evaluator = RagFaithfulnessEvaluator(gemini_client=client)
    result = await evaluator.evaluate(
        question="What is X?",
        answer="X is Y. Also Z.",
        citations=[{"chunk_id": "c1", "text": "X is Y."}],
    )
    assert result.score == 0.85
    assert len(result.unsupported_claims) == 1
```

- [ ] **Step 2: Create `rag/__init__.py`**

```python
"""RAG response evaluator — source-agnostic infrastructure, RAG-specific metrics."""
```

- [ ] **Step 3: Create `rag/models.py`**

```python
"""RAG evaluator result models."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RagFaithfulnessResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    unsupported_claims: list[str] = Field(default_factory=list)
    evaluator_metadata: dict = Field(default_factory=dict)
```

- [ ] **Step 4: Create `rag/faithfulness.py`**

```python
"""RAG answer-vs-citations faithfulness — each answer sentence must be entailed by ≥ 1 citation."""
from __future__ import annotations

import json
from typing import Any

from website.features.evaluation.core.llm_judge import ConsolidatedLLMJudge
from website.features.evaluation.rag.models import RagFaithfulnessResult


_PROMPT_VERSION = "rag_faithfulness.v1"

_SYSTEM = (
    "You evaluate RAG answer faithfulness. For each claim in the answer, check if it is entailed "
    "by at least one citation. Return JSON with keys 'score' (0-1) = entailed_claims/total_claims, "
    "and 'unsupported_claims' (array of unsupported claim strings). Temperature 0.0 judgment."
)

_TEMPLATE = """\
QUESTION:
{question}

ANSWER:
{answer}

CITATIONS:
{citations_json}

Evaluate every claim in ANSWER. Mark claims not entailed by any citation as unsupported.
"""


class RagFaithfulnessEvaluator:
    def __init__(self, *, gemini_client: Any) -> None:
        self._judge = ConsolidatedLLMJudge(client=gemini_client, prompt_version=_PROMPT_VERSION)

    async def evaluate(
        self, *, question: str, answer: str, citations: list[dict],
    ) -> RagFaithfulnessResult:
        prompt = _TEMPLATE.format(
            question=question, answer=answer,
            citations_json=json.dumps(citations, indent=2),
        )
        payload = await self._judge.run(
            prompt=prompt, tier="pro", system_instruction=_SYSTEM, temperature=0.0,
        )
        return RagFaithfulnessResult(
            score=float(payload.get("score", 0.0)),
            unsupported_claims=payload.get("unsupported_claims", []),
            evaluator_metadata=payload.get("evaluator_metadata", {}),
        )
```

- [ ] **Step 5: Run test + commit**

```bash
pytest tests/unit/evaluation/rag/test_faithfulness.py -v
git add website/features/evaluation/rag/ tests/unit/evaluation/rag/
git commit -m "feat: rag response faithfulness evaluator"
```

---

## Task 8: Update iteration-loop scripts to optionally use new imports

**Files:**
- Modify: `ops/scripts/eval_loop.py` (optional — can stay with shims)

- [ ] **Step 1: Add new-style import alongside old-style**

In `ops/scripts/eval_loop.py`, near the existing imports, add:

```python
# New-style imports (preferred going forward). Old-style still works via shims.
try:
    from website.features.evaluation.summarization import (  # noqa: F401
        SummaryEvalResult as EvalResult,
    )
    from website.features.evaluation.summarization.atomic_facts import extract_atomic_facts  # noqa: F401
except ImportError:
    from website.features.summarization_engine.evaluator.models import EvalResult  # noqa: F401
    from website.features.summarization_engine.evaluator.atomic_facts import extract_atomic_facts  # noqa: F401
```

- [ ] **Step 2: Run replay for all 4 major sources**

```bash
for source in youtube reddit github newsletter; do
    if [ -d "docs/summary_eval/$source/iter-01" ]; then
        python ops/scripts/eval_loop.py --source $source --iter 1 --replay
    fi
done
```

Expected: all composites match stored baselines within ±1 pt.

- [ ] **Step 3: Commit**

```bash
git add ops/scripts/eval_loop.py
git commit -m "refactor: eval loop prefers new imports with shim fallback"
```

---

## Task 9: Push + draft PR

- [ ] **Step 1: Push**

```bash
git push origin feat/evaluator-promotion
```

- [ ] **Step 2: Create draft PR**

```bash
gh pr create --draft --title "refactor: promote evaluator to website features evaluation" \
  --body "Plan 11. Promotes evaluator/ to website/features/evaluation/ with core/summarization/rag sub-packages. Backward-compat shims preserve all existing imports. New RagFaithfulnessEvaluator ships for RAG response scoring. All 4 major-source iter-01 replays pass ±1 pt.

### Deploy gate
Pure refactor with shims. Zero runtime behavior change. Verify:
- [ ] CI green
- [ ] tests/unit/evaluation/ + existing tests all pass
- [ ] \`python ops/scripts/eval_loop.py --source youtube --iter 1 --replay\` produces composite within ±1 pt of stored baseline (youtube iter-01)
- [ ] PROMPT_VERSION unchanged at \"evaluator.v1\"

Mergeable with low risk; deploy triggered by merge. No follow-up plan blocks on this one."
```

- [ ] **Step 3: STOP + handoff**

Report:
> Plan 11 complete. Draft PR ready. Backward-compat shims in place; replay regression passed. New RAG faithfulness evaluator scaffolded. Awaiting human review + merge.

---

## Self-review checklist
- [ ] Backward-compat imports all work (tested via test_backward_compat.py)
- [ ] PROMPT_VERSION stays `"evaluator.v1"` — no forced rescoring of historical artifacts
- [ ] Replay regression passes for all 4 major sources (±1 pt)
- [ ] `website/features/evaluation/core/` holds generic primitives only — no summarization-specific logic
- [ ] `website/features/evaluation/summarization/` imports from core + from summarization-specific modules only
- [ ] `website/features/evaluation/rag/` is additive — new capability, doesn't touch old code
- [ ] All old `website/features/summarization_engine/evaluator/*.py` files are now one-line shims
- [ ] New `RagFaithfulnessEvaluator` has working unit test (mocked Gemini)
- [ ] NO merge, NO push to master
