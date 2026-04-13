# Cascade Reranker Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the BGE-reranker-v2-m3 TEI Docker sidecar with an in-process FlashRank MiniLM-L-12-v2 + BGE-reranker-base ONNX INT8 cascade, reducing deploy latency from ~10min to ~2min and rerank latency from ~300ms to ~40-60ms.

**Architecture:**
```
┌──────────────────────────────────────────────┐
│  App (~1024MB)                               │
│                                              │
│  CascadeReranker                             │
│  ┌────────────────────┐                      │
│  │ Stage 1: FlashRank │ MiniLM-L-12 (34MB)  │
│  │ N candidates → 15  │ ~15ms               │
│  └────────┬───────────┘                      │
│           ▼                                  │
│  ┌────────────────────┐                      │
│  │ Stage 2: BGE-base  │ ONNX INT8 (~280MB)  │
│  │ 15 candidates → k  │ ~25-40ms            │
│  └────────────────────┘                      │
│                                              │
│  Models: /opt/zettelkasten/data/models/      │
│  (host-mounted, freshness-checked on deploy) │
└──────────────────────────────────────────────┘
```
Always-cascade: every query runs both stages. Graceful degradation: Stage 2 fails → Stage 1 scores; both fail → RRF-only.

**Tech Stack:** `flashrank` (ONNX MiniLM cross-encoder), `onnxruntime` (CPU), `huggingface_hub` (model download + freshness), `optimum` (one-time ONNX export of BGE-base)

**Spec:** `docs/superpowers/specs/2026-04-13-cascade-reranker-migration-design.md`

---

## File Structure

**New files:**
| File | Responsibility |
|---|---|
| `website/features/rag_pipeline/rerank/cascade.py` | `CascadeReranker` class — two-stage rerank + score fusion |
| `website/features/rag_pipeline/rerank/model_manager.py` | `ModelManager` — download, cache, freshness-check models |
| `website/features/rag_pipeline/rerank/degradation_log.py` | `DegradationLogger` — append JSONL records on fallback |
| `tests/unit/rag/rerank/test_cascade.py` | Core cascade unit tests |
| `tests/unit/rag/rerank/test_cascade_edge_cases.py` | Edge-case tests (content types, multilingual, boundaries) |
| `tests/unit/rag/rerank/test_cascade_e2e.py` | End-to-end pipeline test (replaces test_tei_client.py) |
| `tests/unit/rag/rerank/test_degradation_log.py` | Degradation telemetry tests |
| `tests/unit/rag/rerank/test_model_manager.py` | Model freshness + download tests |
| `tests/integration_tests/test_cascade_live.py` | Live integration test with real models |
| `ops/scripts/export_bge_onnx.py` | One-time script: export BGE-base to ONNX INT8 |

**Modified files:**
| File | Change |
|---|---|
| `website/features/rag_pipeline/rerank/__init__.py` | Export `CascadeReranker` instead of `TEIReranker` |
| `website/features/rag_pipeline/service.py` | Swap factory from `TEIReranker` to `CascadeReranker` |
| `ops/requirements.txt` | Add `flashrank`, `onnxruntime`, `huggingface_hub` |
| `ops/docker-compose.blue.yml` | Remove reranker sidecar, bump memory, add model volume |
| `ops/docker-compose.green.yml` | Same changes as blue |
| `ops/docker-compose.dev.yml` | Add model volume for dev |
| `ops/deploy/deploy.sh` | Add model bootstrap step |
| `tests/unit/rag/test_orchestrator.py` | No changes needed (uses duck-typed `_Reranker` mock) |
| `tests/test_rag_api_routes.py` | No changes needed (uses `_FakeOrchestrator`, never touches reranker) |

**Deleted files:**
| File | Reason |
|---|---|
| `website/features/rag_pipeline/rerank/tei_client.py` | Replaced by `cascade.py` |
| `tests/unit/rag/rerank/test_tei_client.py` | Replaced by `test_cascade_e2e.py` |

---

## Task 1: Add Dependencies

**Files:**
- Modify: `ops/requirements.txt`

- [ ] **Step 1: Add flashrank, onnxruntime, and huggingface_hub to requirements**

Add these three lines at the end of `ops/requirements.txt`, before any comments:

```
# Cascade reranker (FlashRank + BGE-base ONNX)
flashrank>=0.2
onnxruntime>=1.17
huggingface_hub>=0.20
```

`flashrank` brings the MiniLM ONNX cross-encoder. `onnxruntime` is the CPU inference engine for BGE-base ONNX. `huggingface_hub` provides `hf_hub_download` and `model_info` for model freshness checks.

- [ ] **Step 2: Install locally and verify imports**

Run:
```bash
pip install flashrank>=0.2 onnxruntime>=1.17 huggingface_hub>=0.20
python -c "from flashrank import Ranker, RerankRequest; print('flashrank OK')"
python -c "import onnxruntime; print('onnxruntime OK:', onnxruntime.__version__)"
python -c "from huggingface_hub import hf_hub_download, model_info; print('huggingface_hub OK')"
```

Expected: all three print OK with no import errors.

- [ ] **Step 3: Commit**

```bash
git add ops/requirements.txt
git commit -m "chore: add flashrank, onnxruntime, huggingface_hub deps"
```

---

## Task 2: Create DegradationLogger

Build the telemetry module first since `CascadeReranker` will depend on it.

**Files:**
- Create: `website/features/rag_pipeline/rerank/degradation_log.py`
- Create: `tests/unit/rag/rerank/test_degradation_log.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/rag/rerank/test_degradation_log.py`:

```python
"""Tests for degradation telemetry logging."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from website.features.rag_pipeline.rerank.degradation_log import DegradationLogger


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_log_event_creates_jsonl_file(log_dir: Path) -> None:
    logger = DegradationLogger(log_dir)
    logger.log_event(
        query="What is attention?",
        candidate_count=30,
        failed_stage="stage2",
        exception=RuntimeError("ONNX crashed"),
        content_lengths=[10, 200, 3000],
        source_types=["youtube", "reddit"],
    )
    log_path = log_dir / "degradation_events.jsonl"
    assert log_path.exists()
    record = json.loads(log_path.read_text().strip())
    assert record["failed_stage"] == "stage2"
    assert record["candidate_count"] == 30
    assert record["exception_type"] == "RuntimeError"
    assert record["exception_message"] == "ONNX crashed"
    assert record["content_length_stats"]["min"] == 10
    assert record["content_length_stats"]["max"] == 3000
    assert record["source_types"] == ["youtube", "reddit"]


def test_query_content_is_hashed_not_stored_raw(log_dir: Path) -> None:
    logger = DegradationLogger(log_dir)
    logger.log_event(
        query="What is attention?",
        candidate_count=5,
        failed_stage="stage1",
        exception=ValueError("bad input"),
        content_lengths=[100],
        source_types=["web"],
    )
    log_path = log_dir / "degradation_events.jsonl"
    raw = log_path.read_text()
    assert "What is attention?" not in raw
    record = json.loads(raw.strip())
    assert record["query_hash"].startswith("sha256:")
    assert len(record["query_hash"]) > 20


def test_multiple_events_are_appended(log_dir: Path) -> None:
    logger = DegradationLogger(log_dir)
    logger.log_event(
        query="query one",
        candidate_count=10,
        failed_stage="stage2",
        exception=RuntimeError("err1"),
        content_lengths=[50],
        source_types=["web"],
    )
    logger.log_event(
        query="query two",
        candidate_count=20,
        failed_stage="both",
        exception=RuntimeError("err2"),
        content_lengths=[100, 200],
        source_types=["youtube"],
    )
    log_path = log_dir / "degradation_events.jsonl"
    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["failed_stage"] == "stage2"
    assert json.loads(lines[1])["failed_stage"] == "both"


def test_empty_content_lengths_handled(log_dir: Path) -> None:
    logger = DegradationLogger(log_dir)
    logger.log_event(
        query="empty",
        candidate_count=0,
        failed_stage="stage1",
        exception=RuntimeError("no candidates"),
        content_lengths=[],
        source_types=[],
    )
    log_path = log_dir / "degradation_events.jsonl"
    record = json.loads(log_path.read_text().strip())
    assert record["content_length_stats"] == {"min": 0, "max": 0, "mean": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/rag/rerank/test_degradation_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'website.features.rag_pipeline.rerank.degradation_log'`

- [ ] **Step 3: Write the implementation**

Create `website/features/rag_pipeline/rerank/degradation_log.py`:

```python
"""Append-only JSONL logger for cascade reranker degradation events."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class DegradationLogger:
    """Logs structured events when the cascade reranker falls back."""

    def __init__(self, log_dir: str | Path) -> None:
        self._log_path = Path(log_dir) / "degradation_events.jsonl"

    def log_event(
        self,
        *,
        query: str,
        candidate_count: int,
        failed_stage: str,
        exception: BaseException,
        content_lengths: list[int],
        source_types: list[str],
    ) -> None:
        query_hash = "sha256:" + hashlib.sha256(query.encode()).hexdigest()

        if content_lengths:
            length_stats = {
                "min": min(content_lengths),
                "max": max(content_lengths),
                "mean": round(sum(content_lengths) / len(content_lengths)),
            }
        else:
            length_stats = {"min": 0, "max": 0, "mean": 0}

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query_hash": query_hash,
            "candidate_count": candidate_count,
            "failed_stage": failed_stage,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "content_length_stats": length_stats,
            "source_types": list(set(source_types)),
        }

        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            logger.warning("Failed to write degradation event", exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/rag/rerank/test_degradation_log.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/rerank/degradation_log.py tests/unit/rag/rerank/test_degradation_log.py
git commit -m "feat: degradation telemetry for cascade reranker"
```

---

## Task 3: Create ModelManager

**Files:**
- Create: `website/features/rag_pipeline/rerank/model_manager.py`
- Create: `tests/unit/rag/rerank/test_model_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/rag/rerank/test_model_manager.py`:

```python
"""Tests for reranker model download and freshness management."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from website.features.rag_pipeline.rerank.model_manager import ModelManager


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    return tmp_path


def _write_etag(model_dir: Path, model_name: str, etag: str) -> None:
    meta_dir = model_dir / model_name.replace("/", "--")
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "etag.json").write_text(json.dumps({"etag": etag}))
    # Create a dummy model file so "exists" check passes
    (meta_dir / "model.bin").write_bytes(b"fake")


def test_models_exist_returns_false_when_dir_empty(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    assert manager.models_exist() is False


def test_models_exist_returns_true_when_both_present(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    _write_etag(model_dir, "flashrank--ms-marco-MiniLM-L-12-v2", "abc")
    _write_etag(model_dir, "BAAI--bge-reranker-base", "def")
    assert manager.models_exist() is True


def test_is_stale_returns_true_on_etag_mismatch(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    _write_etag(model_dir, "flashrank--ms-marco-MiniLM-L-12-v2", "old-etag")

    with patch.object(manager, "_fetch_remote_etag", return_value="new-etag"):
        assert manager.is_stale("flashrank--ms-marco-MiniLM-L-12-v2") is True


def test_is_stale_returns_false_when_etag_matches(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    _write_etag(model_dir, "flashrank--ms-marco-MiniLM-L-12-v2", "same-etag")

    with patch.object(manager, "_fetch_remote_etag", return_value="same-etag"):
        assert manager.is_stale("flashrank--ms-marco-MiniLM-L-12-v2") is False


def test_is_stale_returns_false_when_hub_unreachable(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    _write_etag(model_dir, "flashrank--ms-marco-MiniLM-L-12-v2", "cached-etag")

    with patch.object(manager, "_fetch_remote_etag", side_effect=OSError("no network")):
        # Cache exists + hub unreachable = not stale (use cached)
        assert manager.is_stale("flashrank--ms-marco-MiniLM-L-12-v2") is False


def test_hub_unreachable_no_cache_raises(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    # No cached models, no network → should raise
    with patch.object(manager, "_fetch_remote_etag", side_effect=OSError("no network")):
        with pytest.raises(OSError):
            manager.is_stale("flashrank--ms-marco-MiniLM-L-12-v2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/rag/rerank/test_model_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `website/features/rag_pipeline/rerank/model_manager.py`:

```python
"""Download, cache, and freshness-check reranker models."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Model identifiers used for directory naming (slashes replaced with --)
FLASHRANK_MODEL = "flashrank--ms-marco-MiniLM-L-12-v2"
BGE_BASE_MODEL = "BAAI--bge-reranker-base"


class ModelManager:
    """Manages model downloads and freshness for the cascade reranker.

    Models are stored in subdirectories of ``model_dir``, named by
    their HuggingFace repo ID with ``/`` replaced by ``--``.
    Each subdirectory contains the model files plus an ``etag.json``
    metadata file for freshness checking.
    """

    def __init__(self, model_dir: str | Path) -> None:
        self._model_dir = Path(model_dir)
        self._model_dir.mkdir(parents=True, exist_ok=True)

    @property
    def model_dir(self) -> Path:
        return self._model_dir

    def _model_path(self, model_name: str) -> Path:
        return self._model_dir / model_name

    def _etag_path(self, model_name: str) -> Path:
        return self._model_path(model_name) / "etag.json"

    def models_exist(self) -> bool:
        """Return True if both FlashRank and BGE-base models are cached."""
        return (
            self._model_path(FLASHRANK_MODEL).exists()
            and self._model_path(BGE_BASE_MODEL).exists()
        )

    def _read_local_etag(self, model_name: str) -> str | None:
        etag_file = self._etag_path(model_name)
        if not etag_file.exists():
            return None
        try:
            data = json.loads(etag_file.read_text(encoding="utf-8"))
            return data.get("etag")
        except (OSError, json.JSONDecodeError):
            return None

    def _write_local_etag(self, model_name: str, etag: str) -> None:
        etag_file = self._etag_path(model_name)
        etag_file.parent.mkdir(parents=True, exist_ok=True)
        etag_file.write_text(json.dumps({"etag": etag}), encoding="utf-8")

    def _fetch_remote_etag(self, model_name: str) -> str:
        """Fetch the latest etag from HuggingFace Hub.

        Raises OSError if the hub is unreachable.
        """
        from huggingface_hub import model_info

        # Convert our naming back to HF repo ID
        repo_id = model_name.replace("--", "/")
        info = model_info(repo_id)
        return info.sha

    def is_stale(self, model_name: str) -> bool:
        """Check if a cached model is outdated compared to HuggingFace Hub.

        Returns True if the remote etag differs from the cached etag.
        If the hub is unreachable and a cache exists, returns False (use cached).
        If the hub is unreachable and no cache exists, raises OSError.
        """
        local_etag = self._read_local_etag(model_name)

        try:
            remote_etag = self._fetch_remote_etag(model_name)
        except OSError:
            if local_etag is not None:
                logger.warning(
                    "HF Hub unreachable for %s; using cached model", model_name,
                )
                return False
            raise

        if local_etag is None:
            return True
        return local_etag != remote_etag

    def download_flashrank_model(self) -> Path:
        """Download or verify FlashRank MiniLM-L-12-v2.

        FlashRank handles its own download internally via ``Ranker()``,
        but we store the etag for freshness tracking.
        Returns the cache directory path.
        """
        cache_dir = self._model_path(FLASHRANK_MODEL)
        cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            remote_etag = self._fetch_remote_etag(FLASHRANK_MODEL)
            self._write_local_etag(FLASHRANK_MODEL, remote_etag)
        except OSError:
            logger.warning("Could not update FlashRank etag; using cached if available")

        return cache_dir

    def download_bge_onnx_model(self) -> Path:
        """Download BGE-reranker-base ONNX model files.

        Uses huggingface_hub to download the ONNX model files.
        Returns the directory containing model files.
        """
        from huggingface_hub import snapshot_download

        cache_dir = self._model_path(BGE_BASE_MODEL)
        cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            snapshot_download(
                repo_id="BAAI/bge-reranker-base",
                local_dir=cache_dir,
                allow_patterns=["onnx/*", "tokenizer*", "config.json", "special_tokens_map.json"],
            )
            remote_etag = self._fetch_remote_etag(BGE_BASE_MODEL)
            self._write_local_etag(BGE_BASE_MODEL, remote_etag)
        except OSError:
            if not (cache_dir / "onnx").exists():
                raise
            logger.warning("Could not refresh BGE-base ONNX; using cached model")

        return cache_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/rag/rerank/test_model_manager.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/rerank/model_manager.py tests/unit/rag/rerank/test_model_manager.py
git commit -m "feat: model manager with freshness checks"
```

---

## Task 4: Create CascadeReranker

This is the core module. It replaces `TEIReranker`.

**Files:**
- Create: `website/features/rag_pipeline/rerank/cascade.py`
- Create: `tests/unit/rag/rerank/test_cascade.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/rag/rerank/test_cascade.py`:

```python
"""Unit tests for the two-stage cascade reranker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from website.features.rag_pipeline.rerank.cascade import CascadeReranker
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _candidate(node_id: str, rrf: float, graph: float = 0.0) -> RetrievalCandidate:
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content=f"Content for {node_id}",
        rrf_score=rrf,
    )
    c.graph_score = graph
    return c


class FakeStage1:
    """Mimics FlashRank: assigns descending scores by index."""

    def rank(self, query, passages):
        scored = []
        for i, p in enumerate(passages):
            scored.append({"id": p["id"], "text": p["text"], "meta": p["meta"], "score": 1.0 - i * 0.05})
        return sorted(scored, key=lambda x: x["score"], reverse=True)


class FakeStage2:
    """Mimics BGE ONNX: assigns descending scores by index."""

    def predict(self, pairs):
        return [0.9 - i * 0.1 for i in range(len(pairs))]


class FailingStage1:
    def rank(self, query, passages):
        raise RuntimeError("Stage 1 ONNX error")


class FailingStage2:
    def predict(self, pairs):
        raise RuntimeError("Stage 2 ONNX error")


def _make_reranker(stage1=None, stage2=None, stage1_k=15, tokenizer=None) -> CascadeReranker:
    reranker = CascadeReranker.__new__(CascadeReranker)
    reranker._stage1 = stage1 or FakeStage1()
    reranker._stage2 = stage2 or FakeStage2()
    reranker._stage2_tokenizer = tokenizer or MagicMock()
    reranker._stage1_k = stage1_k
    reranker._degradation_logger = MagicMock()
    return reranker


@pytest.mark.asyncio
async def test_rerank_returns_empty_for_empty_candidates() -> None:
    reranker = _make_reranker()
    result = await reranker.rerank("query", [])
    assert result == []


@pytest.mark.asyncio
async def test_stage1_filters_to_stage1_k() -> None:
    candidates = [_candidate(f"n{i}", rrf=0.1) for i in range(30)]
    reranker = _make_reranker(stage1_k=10)
    result = await reranker.rerank("query", candidates, top_k=5)
    # Stage 1 filters 30 → 10, Stage 2 reranks 10 → 5
    assert len(result) == 5


@pytest.mark.asyncio
async def test_stage2_populates_rerank_score() -> None:
    candidates = [_candidate("one", 0.1), _candidate("two", 0.2)]
    reranker = _make_reranker(stage1_k=15)
    result = await reranker.rerank("query", candidates, top_k=2)
    assert all(c.rerank_score is not None for c in result)


@pytest.mark.asyncio
async def test_final_score_uses_60_25_15_fusion() -> None:
    candidates = [_candidate("one", rrf=0.2, graph=0.4)]
    reranker = _make_reranker(stage1_k=15)
    result = await reranker.rerank("query", candidates, top_k=1)
    rerank = result[0].rerank_score
    expected = 0.60 * rerank + 0.25 * 0.4 + 0.15 * 0.2
    assert result[0].final_score == pytest.approx(expected)


@pytest.mark.asyncio
async def test_stage2_failure_falls_back_to_stage1_scores() -> None:
    candidates = [_candidate("one", 0.1), _candidate("two", 0.5)]
    reranker = _make_reranker(stage2=FailingStage2(), stage1_k=15)
    result = await reranker.rerank("query", candidates, top_k=2)
    # Should still return results using stage1 scores
    assert len(result) == 2
    assert all(c.rerank_score is not None for c in result)
    reranker._degradation_logger.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_both_stages_fail_falls_back_to_rrf() -> None:
    candidates = [_candidate("one", 0.1), _candidate("two", 0.5)]
    reranker = _make_reranker(stage1=FailingStage1(), stage2=FailingStage2(), stage1_k=15)
    result = await reranker.rerank("query", candidates, top_k=2)
    assert [c.node_id for c in result] == ["two", "one"]
    assert all(c.rerank_score is None for c in result)


@pytest.mark.asyncio
async def test_top_k_respected() -> None:
    candidates = [_candidate(f"n{i}", rrf=0.1) for i in range(20)]
    reranker = _make_reranker(stage1_k=15)
    result = await reranker.rerank("query", candidates, top_k=3)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_fewer_candidates_than_stage1_k_passes_all_through() -> None:
    candidates = [_candidate(f"n{i}", rrf=0.1) for i in range(5)]
    reranker = _make_reranker(stage1_k=15)
    result = await reranker.rerank("query", candidates, top_k=5)
    assert len(result) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/rag/rerank/test_cascade.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'website.features.rag_pipeline.rerank.cascade'`

- [ ] **Step 3: Write the implementation**

Create `website/features/rag_pipeline/rerank/cascade.py`:

```python
"""Two-stage cascade reranker: FlashRank (fast) → BGE-base ONNX (precise)."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from website.features.rag_pipeline.rerank.degradation_log import DegradationLogger
from website.features.rag_pipeline.types import RetrievalCandidate

logger = logging.getLogger(__name__)


class CascadeReranker:
    """Rerank candidates with a two-stage cascade.

    Stage 1: FlashRank ms-marco-MiniLM-L-12-v2 (fast, ONNX).
    Stage 2: BGE-reranker-base ONNX INT8 (precise, cross-encoder).

    Always runs both stages. Graceful degradation:
    - Stage 2 fails → use Stage 1 scores
    - Stage 1 fails → fall back to RRF-only
    """

    def __init__(
        self,
        *,
        model_dir: str | Path,
        stage1_k: int = 15,
    ) -> None:
        self._model_dir = Path(model_dir)
        self._stage1_k = stage1_k
        self._degradation_logger = DegradationLogger(self._model_dir)

        # Lazy-load models on first rerank call
        self._stage1 = None
        self._stage2 = None
        self._stage2_tokenizer = None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Load models on first use (lazy initialization)."""
        if self._loaded:
            return

        try:
            from flashrank import Ranker
            self._stage1 = Ranker(
                model_name="ms-marco-MiniLM-L-12-v2",
                cache_dir=str(self._model_dir / "flashrank--ms-marco-MiniLM-L-12-v2"),
            )
        except Exception:
            logger.warning("Failed to load FlashRank model", exc_info=True)
            self._stage1 = None

        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer

            bge_path = self._model_dir / "BAAI--bge-reranker-base"
            onnx_path = bge_path / "onnx" / "model.onnx"
            if onnx_path.exists():
                self._stage2 = ort.InferenceSession(
                    str(onnx_path),
                    providers=["CPUExecutionProvider"],
                )
                self._stage2_tokenizer = AutoTokenizer.from_pretrained(str(bge_path))
            else:
                logger.warning("BGE-base ONNX model not found at %s", onnx_path)
        except Exception:
            logger.warning("Failed to load BGE-base ONNX model", exc_info=True)
            self._stage2 = None

        self._loaded = True

    def _run_stage1(
        self, query: str, candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        """Score all candidates with FlashRank, return top stage1_k."""
        from flashrank import RerankRequest

        passages = [
            {"id": i, "text": c.content[:4000], "meta": {"idx": i}}
            for i, c in enumerate(candidates)
        ]
        request = RerankRequest(query=query, passages=passages)
        results = self._stage1.rerank(request)

        # Map scores back and pick top stage1_k
        for result in results:
            idx = result["meta"]["idx"]
            candidates[idx].rerank_score = result["score"]

        ranked = sorted(candidates, key=lambda c: c.rerank_score or 0.0, reverse=True)
        return ranked[: self._stage1_k]

    def _run_stage2(
        self, query: str, candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        """Re-score candidates with BGE-base ONNX cross-encoder."""
        import numpy as np

        pairs = [[query, c.content[:4000]] for c in candidates]
        encoded = self._stage2_tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )
        input_feed = {
            name: encoded[name]
            for name in [inp.name for inp in self._stage2.get_inputs()]
            if name in encoded
        }
        logits = self._stage2.run(None, input_feed)[0]
        # BGE cross-encoder outputs logits; apply sigmoid for score
        scores = 1.0 / (1.0 + np.exp(-logits.flatten()))

        for i, candidate in enumerate(candidates):
            candidate.rerank_score = float(scores[i])

        return candidates

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int = 8,
    ) -> list[RetrievalCandidate]:
        """Rerank candidates through the two-stage cascade."""
        if not candidates:
            return []

        self._ensure_loaded()

        content_lengths = [len(c.content) for c in candidates]
        source_types = [c.source_type.value for c in candidates]

        # Stage 1: FlashRank fast filter
        stage1_passed = None
        try:
            if self._stage1 is not None:
                stage1_passed = await asyncio.to_thread(
                    self._run_stage1, query, list(candidates),
                )
            else:
                raise RuntimeError("FlashRank model not loaded")
        except Exception as exc:
            logger.warning("Stage 1 (FlashRank) failed: %s", exc)
            # Both stages will fail — fall back to RRF
            for c in candidates:
                c.rerank_score = None
                c.final_score = c.rrf_score or 0.0
            self._degradation_logger.log_event(
                query=query,
                candidate_count=len(candidates),
                failed_stage="both",
                exception=exc,
                content_lengths=content_lengths,
                source_types=source_types,
            )
            return sorted(
                candidates, key=lambda c: c.rrf_score or 0.0, reverse=True,
            )[:top_k]

        # Stage 2: BGE-base ONNX precision rerank
        try:
            if self._stage2 is not None:
                await asyncio.to_thread(
                    self._run_stage2, query, stage1_passed,
                )
            else:
                raise RuntimeError("BGE-base ONNX model not loaded")
        except Exception as exc:
            logger.warning("Stage 2 (BGE-base) failed, using Stage 1 scores: %s", exc)
            self._degradation_logger.log_event(
                query=query,
                candidate_count=len(stage1_passed),
                failed_stage="stage2",
                exception=exc,
                content_lengths=content_lengths,
                source_types=source_types,
            )
            # Use stage1 scores for fusion

        # Score fusion: 0.60 * rerank + 0.25 * graph + 0.15 * rrf
        for c in stage1_passed:
            c.final_score = (
                0.60 * (c.rerank_score or 0.0)
                + 0.25 * (c.graph_score or 0.0)
                + 0.15 * (c.rrf_score or 0.0)
            )

        return sorted(
            stage1_passed, key=lambda c: c.final_score or 0.0, reverse=True,
        )[:top_k]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/rag/rerank/test_cascade.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/rerank/cascade.py tests/unit/rag/rerank/test_cascade.py
git commit -m "feat: two-stage cascade reranker core"
```

---

## Task 5: Edge-Case Tests

**Files:**
- Create: `tests/unit/rag/rerank/test_cascade_edge_cases.py`

- [ ] **Step 1: Write the edge-case tests**

Create `tests/unit/rag/rerank/test_cascade_edge_cases.py`:

```python
"""Edge-case tests for cascade reranker across diverse content types."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from website.features.rag_pipeline.rerank.cascade import CascadeReranker
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _candidate(
    node_id: str,
    content: str = "default content",
    rrf: float = 0.1,
    graph: float = 0.0,
    source_type: SourceType = SourceType.WEB,
) -> RetrievalCandidate:
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=node_id,
        source_type=source_type,
        url=f"https://example.com/{node_id}",
        content=content,
        rrf_score=rrf,
    )
    c.graph_score = graph
    return c


class FakeStage1:
    def rank(self, query, passages):
        scored = []
        for i, p in enumerate(passages):
            scored.append({"id": p["id"], "text": p["text"], "meta": p["meta"], "score": 1.0 - i * 0.05})
        return sorted(scored, key=lambda x: x["score"], reverse=True)


class FakeStage2:
    def predict(self, pairs):
        return [0.9 - i * 0.1 for i in range(len(pairs))]


def _make_reranker(stage1_k=15) -> CascadeReranker:
    reranker = CascadeReranker.__new__(CascadeReranker)
    reranker._stage1 = FakeStage1()
    reranker._stage2 = FakeStage2()
    reranker._stage2_tokenizer = MagicMock()
    reranker._stage1_k = stage1_k
    reranker._degradation_logger = MagicMock()
    return reranker


# --- Content length extremes ---

@pytest.mark.asyncio
async def test_single_word_content() -> None:
    candidates = [_candidate("short", content="transformers")]
    result = await _make_reranker().rerank("query", candidates, top_k=1)
    assert len(result) == 1
    assert result[0].rerank_score is not None


@pytest.mark.asyncio
async def test_empty_content_field() -> None:
    candidates = [_candidate("empty", content="")]
    result = await _make_reranker().rerank("query", candidates, top_k=1)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_4000_char_truncation_boundary() -> None:
    long_content = "x" * 5000
    candidates = [_candidate("long", content=long_content)]
    result = await _make_reranker().rerank("query", candidates, top_k=1)
    assert len(result) == 1
    assert result[0].rerank_score is not None


# --- Source type diversity ---

@pytest.mark.asyncio
async def test_youtube_transcript_long_conversational() -> None:
    yt_content = "so basically the transformer model works by um using self-attention " * 50
    candidates = [_candidate("yt1", content=yt_content, source_type=SourceType.YOUTUBE)]
    result = await _make_reranker().rerank("how do transformers work?", candidates, top_k=1)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_reddit_short_informal_with_emoji() -> None:
    reddit_content = "lol this is actually fire tho, check out the new llm framework on github"
    candidates = [_candidate("rd1", content=reddit_content, source_type=SourceType.REDDIT)]
    result = await _make_reranker().rerank("llm frameworks", candidates, top_k=1)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_github_readme_with_code() -> None:
    gh_content = "# Installation\n```bash\npip install my-package\n```\n\nUsage: `from my_package import main`"
    candidates = [_candidate("gh1", content=gh_content, source_type=SourceType.GITHUB)]
    result = await _make_reranker().rerank("how to install", candidates, top_k=1)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_mixed_source_types_in_batch() -> None:
    candidates = [
        _candidate("yt", content="video transcript about AI", source_type=SourceType.YOUTUBE, rrf=0.3),
        _candidate("rd", content="reddit post about AI hype", source_type=SourceType.REDDIT, rrf=0.2),
        _candidate("gh", content="# AI Framework\nOpen source tools", source_type=SourceType.GITHUB, rrf=0.4),
        _candidate("web", content="Web article: Introduction to AI", source_type=SourceType.WEB, rrf=0.1),
    ]
    result = await _make_reranker().rerank("AI tools", candidates, top_k=4)
    assert len(result) == 4
    assert all(c.final_score is not None for c in result)


# --- Multilingual input ---

@pytest.mark.asyncio
async def test_chinese_content_does_not_crash() -> None:
    candidates = [_candidate("zh1", content="Transformer 的核心是自注意力机制")]
    result = await _make_reranker().rerank("自注意力", candidates, top_k=1)
    assert len(result) == 1
    assert isinstance(result[0].rerank_score, float)


@pytest.mark.asyncio
async def test_hindi_content_does_not_crash() -> None:
    candidates = [_candidate("hi1", content="ट्रांसफॉर्मर मॉडल एक प्रकार का न्यूरल नेटवर्क है")]
    result = await _make_reranker().rerank("न्यूरल नेटवर्क", candidates, top_k=1)
    assert len(result) == 1
    assert isinstance(result[0].rerank_score, float)


@pytest.mark.asyncio
async def test_mixed_language_content() -> None:
    candidates = [_candidate("mixed", content="This is about Transformer 模型 and attention मैकेनिज़्म")]
    result = await _make_reranker().rerank("attention mechanism", candidates, top_k=1)
    assert len(result) == 1


# --- Score distribution edge cases ---

@pytest.mark.asyncio
async def test_all_identical_rrf_scores() -> None:
    candidates = [_candidate(f"n{i}", rrf=0.5) for i in range(10)]
    result = await _make_reranker().rerank("query", candidates, top_k=5)
    assert len(result) == 5
    # Reranker should break the tie
    assert all(c.final_score is not None for c in result)


@pytest.mark.asyncio
async def test_all_zero_graph_scores() -> None:
    candidates = [_candidate(f"n{i}", rrf=0.3, graph=0.0) for i in range(5)]
    result = await _make_reranker().rerank("query", candidates, top_k=3)
    assert all(c.graph_score == 0.0 for c in result)
    assert all(c.final_score is not None for c in result)


@pytest.mark.asyncio
async def test_single_candidate() -> None:
    candidates = [_candidate("only", rrf=0.5, graph=0.8)]
    result = await _make_reranker().rerank("query", candidates, top_k=1)
    assert len(result) == 1
    assert result[0].node_id == "only"


# --- Candidate count boundaries ---

@pytest.mark.asyncio
async def test_exactly_stage1_k_candidates() -> None:
    candidates = [_candidate(f"n{i}", rrf=0.1) for i in range(15)]
    result = await _make_reranker(stage1_k=15).rerank("query", candidates, top_k=8)
    # stage1_k == len(candidates), Stage 1 is a no-op pass-through
    assert len(result) == 8


@pytest.mark.asyncio
async def test_fewer_candidates_than_top_k() -> None:
    candidates = [_candidate(f"n{i}", rrf=0.1) for i in range(3)]
    result = await _make_reranker().rerank("query", candidates, top_k=8)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_100_plus_candidates_stress() -> None:
    candidates = [_candidate(f"n{i}", rrf=0.01 * i) for i in range(120)]
    result = await _make_reranker(stage1_k=15).rerank("query", candidates, top_k=8)
    assert len(result) == 8
    # Verify ordering is descending by final_score
    scores = [c.final_score for c in result]
    assert scores == sorted(scores, reverse=True)


# --- Determinism ---

@pytest.mark.asyncio
async def test_deterministic_ordering_across_runs() -> None:
    def run():
        candidates = [
            _candidate("a", rrf=0.3, graph=0.5),
            _candidate("b", rrf=0.7, graph=0.1),
            _candidate("c", rrf=0.5, graph=0.3),
        ]
        return _make_reranker().rerank("query", candidates, top_k=3)

    result1 = await run()
    result2 = await run()
    assert [c.node_id for c in result1] == [c.node_id for c in result2]
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/unit/rag/rerank/test_cascade_edge_cases.py -v`
Expected: 18 passed

- [ ] **Step 3: Commit**

```bash
git add tests/unit/rag/rerank/test_cascade_edge_cases.py
git commit -m "test: edge-case tests for cascade reranker"
```

---

## Task 6: End-to-End Pipeline Test + Wire-Up

Replace `TEIReranker` with `CascadeReranker` in the module exports and service factory.

**Files:**
- Modify: `website/features/rag_pipeline/rerank/__init__.py`
- Modify: `website/features/rag_pipeline/service.py`
- Delete: `website/features/rag_pipeline/rerank/tei_client.py`
- Delete: `tests/unit/rag/rerank/test_tei_client.py`
- Create: `tests/unit/rag/rerank/test_cascade_e2e.py`

- [ ] **Step 1: Write the end-to-end test**

Create `tests/unit/rag/rerank/test_cascade_e2e.py`:

```python
"""End-to-end test: CascadeReranker wired into mock orchestrator pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from website.features.rag_pipeline.rerank.cascade import CascadeReranker
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


# Reuse the same fakes from test_cascade.py

class FakeStage1:
    def rank(self, query, passages):
        scored = []
        for i, p in enumerate(passages):
            scored.append({"id": p["id"], "text": p["text"], "meta": p["meta"], "score": 1.0 - i * 0.05})
        return sorted(scored, key=lambda x: x["score"], reverse=True)


class FakeStage2:
    def predict(self, pairs):
        return [0.9 - i * 0.1 for i in range(len(pairs))]


def _candidate(node_id: str, rrf: float = 0.3, graph: float = 0.2) -> RetrievalCandidate:
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=f"Note: {node_id}",
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content=f"Full content for note {node_id} about knowledge graphs and AI",
        rrf_score=rrf,
    )
    c.graph_score = graph
    return c


def _make_reranker() -> CascadeReranker:
    reranker = CascadeReranker.__new__(CascadeReranker)
    reranker._stage1 = FakeStage1()
    reranker._stage2 = FakeStage2()
    reranker._stage2_tokenizer = MagicMock()
    reranker._stage1_k = 15
    reranker._degradation_logger = MagicMock()
    return reranker


@pytest.mark.asyncio
async def test_full_pipeline_retriever_graph_reranker_assembler() -> None:
    """Simulate the orchestrator flow: retrieve → graph score → cascade rerank."""
    # Step 1: Retriever returns candidates with rrf_score
    candidates = [
        _candidate("node-1", rrf=0.4, graph=0.0),
        _candidate("node-2", rrf=0.3, graph=0.0),
        _candidate("node-3", rrf=0.5, graph=0.0),
    ]

    # Step 2: Graph scorer populates graph_score
    for c in candidates:
        c.graph_score = 0.3

    # Step 3: Cascade reranker reranks
    reranker = _make_reranker()
    ranked = await reranker.rerank("What are knowledge graphs?", candidates, top_k=3)

    # Verify all scores populated
    assert all(c.rerank_score is not None for c in ranked)
    assert all(c.graph_score is not None for c in ranked)
    assert all(c.final_score is not None for c in ranked)

    # Verify ordering is descending by final_score
    scores = [c.final_score for c in ranked]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_cascade_reranker_interface_matches_tei_reranker() -> None:
    """Verify CascadeReranker has the same interface as TEIReranker."""
    reranker = _make_reranker()

    # Same method signature: rerank(query: str, candidates: list, top_k: int)
    assert hasattr(reranker, "rerank")
    result = await reranker.rerank("test", [], top_k=8)
    assert result == []


@pytest.mark.asyncio
async def test_score_ordering_deterministic_across_runs() -> None:
    """Verify same input always produces same output ordering."""
    async def run():
        candidates = [
            _candidate("a", rrf=0.2, graph=0.6),
            _candidate("b", rrf=0.8, graph=0.1),
            _candidate("c", rrf=0.5, graph=0.4),
        ]
        reranker = _make_reranker()
        return await reranker.rerank("query", candidates, top_k=3)

    r1 = await run()
    r2 = await run()
    assert [c.node_id for c in r1] == [c.node_id for c in r2]
    assert [c.final_score for c in r1] == [c.final_score for c in r2]


def test_cascade_reranker_importable_from_package() -> None:
    """Verify __init__.py exports CascadeReranker."""
    from website.features.rag_pipeline.rerank import CascadeReranker as Imported
    assert Imported is CascadeReranker
```

- [ ] **Step 2: Update `__init__.py` exports**

Replace the contents of `website/features/rag_pipeline/rerank/__init__.py`:

```python
from .cascade import CascadeReranker

__all__ = ["CascadeReranker"]
```

- [ ] **Step 3: Update `service.py` factory**

In `website/features/rag_pipeline/service.py`, change the import (line 24) from:

```python
from website.features.rag_pipeline.rerank.tei_client import TEIReranker
```

to:

```python
from website.features.rag_pipeline.rerank.cascade import CascadeReranker
```

Then replace the reranker instantiation (lines 66-68) from:

```python
        reranker=TEIReranker(
            base_url=os.environ.get("RAG_RERANKER_URL", "http://reranker:8080"),
        ),
```

to:

```python
        reranker=CascadeReranker(
            model_dir=os.environ.get("RAG_MODEL_DIR", "/app/models"),
            stage1_k=int(os.environ.get("RAG_CASCADE_STAGE1_K", "15")),
        ),
```

- [ ] **Step 4: Delete old files**

```bash
rm website/features/rag_pipeline/rerank/tei_client.py
rm tests/unit/rag/rerank/test_tei_client.py
```

- [ ] **Step 5: Run all rerank tests**

Run: `pytest tests/unit/rag/rerank/ -v`
Expected: all tests pass (test_cascade.py, test_cascade_edge_cases.py, test_cascade_e2e.py, test_degradation_log.py, test_model_manager.py)

- [ ] **Step 6: Run orchestrator tests to verify mock compatibility**

Run: `pytest tests/unit/rag/test_orchestrator.py -v`
Expected: all 7 tests pass (they use duck-typed `_Reranker` mock, no import of TEIReranker)

- [ ] **Step 7: Run API route tests**

Run: `pytest tests/test_rag_api_routes.py -v`
Expected: all 3 tests pass (they use `_FakeOrchestrator`, never import the reranker directly)

- [ ] **Step 8: Commit**

```bash
git add website/features/rag_pipeline/rerank/__init__.py website/features/rag_pipeline/rerank/cascade.py website/features/rag_pipeline/service.py tests/unit/rag/rerank/test_cascade_e2e.py
git add -u  # stages the deleted files
git commit -m "feat: wire cascade reranker, remove TEI client"
```

---

## Task 7: Docker Compose & Deploy Changes

**Files:**
- Modify: `ops/docker-compose.blue.yml`
- Modify: `ops/docker-compose.green.yml`
- Modify: `ops/docker-compose.dev.yml`
- Modify: `ops/deploy/deploy.sh`

- [ ] **Step 1: Update `ops/docker-compose.blue.yml`**

Replace the entire file with:

```yaml
services:
  zettelkasten-blue:
    image: ghcr.io/chintanmehta21/zettelkasten-kg-website:${IMAGE_TAG:-latest}
    container_name: zettelkasten-blue
    hostname: zettelkasten-blue
    restart: unless-stopped
    env_file:
      - /opt/zettelkasten/compose/.env
    environment:
      WEBHOOK_PORT: "10000"
      NEXUS_ENABLED: "true"
      RAG_MODEL_DIR: "/app/models"
    ports:
      - "127.0.0.1:10000:10000"
    networks:
      - zettelnet
    volumes:
      - /opt/zettelkasten/data/kg_output:/app/kg_output
      - /opt/zettelkasten/data/bot_data:/app/bot_data
      - /opt/zettelkasten/data/models:/app/models:rw
    mem_limit: 1024m
    memswap_limit: 1024m
    pids_limit: 512
    stop_grace_period: 20s
    read_only: true
    tmpfs:
      - /tmp:size=64m
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "curl", "--silent", "--fail", "--max-time", "2", "http://127.0.0.1:10000/api/health"]
      interval: 15s
      timeout: 3s
      start_period: 10s
      retries: 3

networks:
  zettelnet:
    external: true
```

Changes from original:
- Removed entire `reranker` service block (lines 1-27 of original)
- Removed `depends_on: reranker: condition: service_healthy`
- Removed `RAG_RERANKER_URL` env var
- Added `RAG_MODEL_DIR: "/app/models"` env var
- Added `/opt/zettelkasten/data/models:/app/models:rw` volume
- Bumped `mem_limit` and `memswap_limit` from `768m` to `1024m`

- [ ] **Step 2: Update `ops/docker-compose.green.yml`**

Replace the entire file with:

```yaml
services:
  zettelkasten-green:
    image: ghcr.io/chintanmehta21/zettelkasten-kg-website:${IMAGE_TAG:-latest}
    container_name: zettelkasten-green
    hostname: zettelkasten-green
    restart: unless-stopped
    env_file:
      - /opt/zettelkasten/compose/.env
    environment:
      WEBHOOK_PORT: "10000"
      NEXUS_ENABLED: "true"
      RAG_MODEL_DIR: "/app/models"
    ports:
      - "127.0.0.1:10001:10000"
    networks:
      - zettelnet
    volumes:
      - /opt/zettelkasten/data/kg_output:/app/kg_output
      - /opt/zettelkasten/data/bot_data:/app/bot_data
      - /opt/zettelkasten/data/models:/app/models:rw
    mem_limit: 1024m
    memswap_limit: 1024m
    pids_limit: 512
    stop_grace_period: 20s
    read_only: true
    tmpfs:
      - /tmp:size=64m
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "curl", "--silent", "--fail", "--max-time", "2", "http://127.0.0.1:10000/api/health"]
      interval: 15s
      timeout: 3s
      start_period: 10s
      retries: 3

networks:
  zettelnet:
    external: true
```

- [ ] **Step 3: Update `ops/docker-compose.dev.yml`**

Add the model volume to the dev compose. Add this line after the `dev-bot-data` volume mount (line 29):

```yaml
      - dev-models:/app/models
```

And add to the `volumes:` section at the bottom:

```yaml
  dev-models:
```

Add this env var to the `environment:` block:

```yaml
      RAG_MODEL_DIR: "/app/models"
```

- [ ] **Step 4: Add model bootstrap to `ops/deploy/deploy.sh`**

Add this block after the `SHA` variable validation (after line 28 `ROOT=/opt/zettelkasten`), before the `ACTIVE_FILE` line:

```bash
# Ensure model directory exists for cascade reranker
MODEL_DIR="$ROOT/data/models"
if [[ ! -d "$MODEL_DIR" ]]; then
    log "Creating model directory at $MODEL_DIR..."
    mkdir -p "$MODEL_DIR"
    chown deploy:deploy "$MODEL_DIR"
fi
```

- [ ] **Step 5: Commit**

```bash
git add ops/docker-compose.blue.yml ops/docker-compose.green.yml ops/docker-compose.dev.yml ops/deploy/deploy.sh
git commit -m "infra: remove TEI sidecar, add model volume"
```

---

## Task 8: ONNX Export Script

One-time script to export BGE-reranker-base to ONNX format for the Stage 2 model.

**Files:**
- Create: `ops/scripts/export_bge_onnx.py`

- [ ] **Step 1: Create the export script**

Create `ops/scripts/export_bge_onnx.py`:

```python
#!/usr/bin/env python3
"""One-time script: export BAAI/bge-reranker-base to ONNX format.

Usage:
    pip install optimum[onnxruntime] transformers
    python ops/scripts/export_bge_onnx.py /opt/zettelkasten/data/models/BAAI--bge-reranker-base

This downloads the model from HuggingFace, exports it to ONNX,
and optionally applies INT8 dynamic quantization.

Run this ONCE on a machine with internet access. The output directory
can then be copied to the production droplet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export BGE-reranker-base to ONNX")
    parser.add_argument("output_dir", type=Path, help="Directory to save the ONNX model")
    parser.add_argument("--quantize", action="store_true", default=True, help="Apply INT8 dynamic quantization (default: True)")
    parser.add_argument("--no-quantize", action="store_false", dest="quantize", help="Skip quantization")
    args = parser.parse_args()

    try:
        from optimum.onnxruntime import ORTModelForSequenceClassification, ORTQuantizer
        from optimum.onnxruntime.configuration import AutoQuantizationConfig
        from transformers import AutoTokenizer
    except ImportError:
        print("ERROR: Install required packages first:")
        print("  pip install optimum[onnxruntime] transformers torch")
        sys.exit(1)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading and exporting BAAI/bge-reranker-base to ONNX...")
    model = ORTModelForSequenceClassification.from_pretrained(
        "BAAI/bge-reranker-base",
        export=True,
    )
    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-reranker-base")

    # Save the base ONNX model
    onnx_dir = output_dir / "onnx"
    onnx_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(onnx_dir)
    tokenizer.save_pretrained(output_dir)

    if args.quantize:
        print("Applying INT8 dynamic quantization...")
        quantizer = ORTQuantizer.from_pretrained(onnx_dir)
        qconfig = AutoQuantizationConfig.avx2(is_static=False)
        quantizer.quantize(save_dir=onnx_dir, quantization_config=qconfig)
        print(f"Quantized model saved to {onnx_dir}")

    print(f"Export complete. Model files at: {output_dir}")
    print(f"Total size: {sum(f.stat().st_size for f in output_dir.rglob('*') if f.is_file()) / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add ops/scripts/export_bge_onnx.py
git commit -m "chore: ONNX export script for BGE-reranker-base"
```

---

## Task 9: Live Integration Test

**Files:**
- Create: `tests/integration_tests/test_cascade_live.py`

- [ ] **Step 1: Write the live integration test**

Create `tests/integration_tests/test_cascade_live.py`:

```python
"""Live integration test: loads real FlashRank + BGE-base ONNX models.

Run with: pytest --live tests/integration_tests/test_cascade_live.py -v
Requires models to be downloaded to a local directory.
"""

from __future__ import annotations

import os
import tempfile
from uuid import uuid4

import pytest

from website.features.rag_pipeline.rerank.cascade import CascadeReranker
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


pytestmark = pytest.mark.live


def _candidate(
    node_id: str,
    content: str,
    rrf: float = 0.3,
    graph: float = 0.2,
    source_type: SourceType = SourceType.WEB,
) -> RetrievalCandidate:
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=f"Note: {node_id}",
        source_type=source_type,
        url=f"https://example.com/{node_id}",
        content=content,
        rrf_score=rrf,
    )
    c.graph_score = graph
    return c


@pytest.fixture(scope="module")
def reranker():
    model_dir = os.environ.get("RAG_MODEL_DIR", tempfile.mkdtemp(prefix="cascade-test-"))
    return CascadeReranker(model_dir=model_dir, stage1_k=15)


@pytest.mark.asyncio
async def test_live_rerank_diverse_source_types(reranker) -> None:
    candidates = [
        _candidate("yt-1", "In this video we explore how attention mechanisms work in transformer models. The key insight is that self-attention allows each token to attend to every other token.", source_type=SourceType.YOUTUBE),
        _candidate("rd-1", "lol just discovered you can use flash attention for 2x speedup. anyone tried it?", source_type=SourceType.REDDIT),
        _candidate("gh-1", "# FlashAttention\n\n```python\nfrom flash_attn import flash_attn_func\n```\n\nFast and memory-efficient exact attention.", source_type=SourceType.GITHUB),
        _candidate("web-1", "Attention Is All You Need introduced the Transformer architecture, replacing recurrence with multi-head self-attention.", source_type=SourceType.WEB),
    ]

    result = await reranker.rerank("How does attention work in transformers?", candidates, top_k=4)

    assert len(result) == 4
    assert all(c.rerank_score is not None for c in result)
    assert all(c.final_score is not None for c in result)
    # Scores should be in descending order
    scores = [c.final_score for c in result]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_live_rerank_score_ordering_is_sane(reranker) -> None:
    relevant = _candidate("relevant", "The transformer model uses self-attention to process sequences in parallel, making it much faster than RNNs for long sequences.", rrf=0.3)
    irrelevant = _candidate("irrelevant", "The weather in Paris is usually mild in spring, with occasional rain showers and temperatures around 15 degrees Celsius.", rrf=0.5)

    result = await reranker.rerank("How do transformers process sequences?", [relevant, irrelevant], top_k=2)

    # Reranker should score the relevant document higher despite lower rrf
    assert result[0].node_id == "relevant"
```

- [ ] **Step 2: Commit**

```bash
git add tests/integration_tests/test_cascade_live.py
git commit -m "test: live integration test for cascade reranker"
```

---

## Task 10: Full Test Suite Verification

- [ ] **Step 1: Run all unit tests**

Run: `pytest tests/unit/rag/rerank/ -v`
Expected: all tests pass across all 5 test files

- [ ] **Step 2: Run orchestrator and API tests**

Run: `pytest tests/unit/rag/test_orchestrator.py tests/test_rag_api_routes.py -v`
Expected: all 10 tests pass

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ --ignore=tests/integration_tests -v`
Expected: all tests pass, no import errors for removed `tei_client`

- [ ] **Step 4: Verify no lingering references to TEIReranker**

Run: `grep -r "TEIReranker\|tei_client\|RAG_RERANKER_URL" website/ tests/ ops/ --include="*.py" --include="*.yml" --include="*.yaml"`
Expected: no matches (all references removed)

- [ ] **Step 5: Commit any fixes if needed**

```bash
git add -A
git commit -m "chore: verify full test suite passes"
```

---

## Task 11: Production Model Bootstrap

This task is run once on the droplet to seed the model directory.

- [ ] **Step 1: SSH to droplet and create model directory**

```bash
# On the droplet (via SSH)
sudo mkdir -p /opt/zettelkasten/data/models
sudo chown deploy:deploy /opt/zettelkasten/data/models
```

- [ ] **Step 2: Export BGE-base ONNX model (run locally or on droplet)**

```bash
# Requires: pip install optimum[onnxruntime] transformers torch
python ops/scripts/export_bge_onnx.py /opt/zettelkasten/data/models/BAAI--bge-reranker-base
```

Expected output: `Export complete. Model files at: /opt/zettelkasten/data/models/BAAI--bge-reranker-base`
Expected size: ~280-320MB

- [ ] **Step 3: Pre-download FlashRank model**

```bash
python -c "
from flashrank import Ranker
import os
cache_dir = '/opt/zettelkasten/data/models/flashrank--ms-marco-MiniLM-L-12-v2'
os.makedirs(cache_dir, exist_ok=True)
Ranker(model_name='ms-marco-MiniLM-L-12-v2', cache_dir=cache_dir)
print('FlashRank model downloaded')
"
```

Expected: model downloaded to cache directory (~34MB)

- [ ] **Step 4: Verify model directory structure**

```bash
ls -la /opt/zettelkasten/data/models/
# Expected:
# flashrank--ms-marco-MiniLM-L-12-v2/   (~34MB)
# BAAI--bge-reranker-base/               (~280MB)
#   ├── onnx/
#   │   └── model.onnx
#   ├── tokenizer.json
#   ├── config.json
#   └── ...
```

- [ ] **Step 5: Stop the old TEI reranker sidecar**

```bash
# After the new app container starts successfully with cascade reranker:
docker stop zettelkasten-reranker-blue zettelkasten-reranker-green 2>/dev/null || true
docker rm zettelkasten-reranker-blue zettelkasten-reranker-green 2>/dev/null || true
```

---

## Summary

| Task | What | Files | Est. Time |
|---|---|---|---|
| 1 | Add dependencies | `ops/requirements.txt` | 2 min |
| 2 | DegradationLogger | `degradation_log.py` + tests | 5 min |
| 3 | ModelManager | `model_manager.py` + tests | 5 min |
| 4 | CascadeReranker core | `cascade.py` + tests | 10 min |
| 5 | Edge-case tests | `test_cascade_edge_cases.py` | 5 min |
| 6 | Wire-up + E2E test | `__init__.py`, `service.py`, delete old, E2E test | 5 min |
| 7 | Docker + deploy changes | 3 compose files + deploy.sh | 5 min |
| 8 | ONNX export script | `export_bge_onnx.py` | 3 min |
| 9 | Live integration test | `test_cascade_live.py` | 3 min |
| 10 | Full verification | Run all tests, grep for stale refs | 5 min |
| 11 | Production bootstrap | Droplet model setup | 10 min |
