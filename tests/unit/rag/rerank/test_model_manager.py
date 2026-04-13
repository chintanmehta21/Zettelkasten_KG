"""Tests for reranker model download and freshness management."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from website.features.rag_pipeline.errors import RerankerUnavailable
from website.features.rag_pipeline.rerank.model_manager import (
    BGE_DIR_NAME,
    FLASHRANK_MODEL_NAME,
    ModelManager,
)


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    return tmp_path


def _write_flashrank_cache(model_dir: Path) -> None:
    (model_dir / FLASHRANK_MODEL_NAME).mkdir(parents=True, exist_ok=True)


def _write_bge_export(model_dir: Path, *, sha: str = "sha-1") -> None:
    export_dir = model_dir / BGE_DIR_NAME
    (export_dir / "onnx").mkdir(parents=True, exist_ok=True)
    (export_dir / "onnx" / "model.onnx").write_bytes(b"fake")
    (export_dir / "config.json").write_text("{}", encoding="utf-8")
    (export_dir / "export_metadata.json").write_text(
        json.dumps({"source_sha": sha}),
        encoding="utf-8",
    )


def test_models_exist_returns_false_when_dir_empty(model_dir: Path) -> None:
    manager = ModelManager(model_dir)

    assert manager.models_exist() is False


def test_models_exist_returns_true_when_flashrank_and_bge_present(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    _write_flashrank_cache(model_dir)
    _write_bge_export(model_dir)

    assert manager.models_exist() is True


def test_is_bge_stale_returns_true_on_sha_mismatch(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    _write_bge_export(model_dir, sha="old-sha")

    with patch.object(manager, "_fetch_remote_bge_sha", return_value="new-sha"):
        assert manager.is_bge_stale() is True


def test_is_bge_stale_returns_false_when_sha_matches(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    _write_bge_export(model_dir, sha="same-sha")

    with patch.object(manager, "_fetch_remote_bge_sha", return_value="same-sha"):
        assert manager.is_bge_stale() is False


def test_is_bge_stale_returns_false_when_hub_unreachable_and_cache_exists(model_dir: Path) -> None:
    manager = ModelManager(model_dir)
    _write_bge_export(model_dir, sha="cached-sha")

    with patch.object(manager, "_fetch_remote_bge_sha", side_effect=OSError("no network")):
        assert manager.is_bge_stale() is False


def test_is_bge_stale_raises_when_hub_unreachable_and_no_cache(model_dir: Path) -> None:
    manager = ModelManager(model_dir)

    with patch.object(manager, "_fetch_remote_bge_sha", side_effect=OSError("no network")):
        with pytest.raises(OSError):
            manager.is_bge_stale()


def test_ensure_flashrank_model_bootstraps_cache(model_dir: Path) -> None:
    manager = ModelManager(model_dir)

    with patch("website.features.rag_pipeline.rerank.model_manager.Ranker") as ranker_cls:
        path = manager.ensure_flashrank_model()

    ranker_cls.assert_called_once_with(
        model_name=FLASHRANK_MODEL_NAME,
        cache_dir=str(model_dir),
    )
    assert path == model_dir / FLASHRANK_MODEL_NAME


def test_ensure_bge_onnx_model_raises_when_export_missing(model_dir: Path) -> None:
    manager = ModelManager(model_dir)

    with pytest.raises(RerankerUnavailable):
        manager.ensure_bge_onnx_model()
