"""Iter-03 §7: DegradationLogger writes to RAG_DEGRADATION_LOG_DIR (default
/app/runtime), NOT to model_dir. /app/models is read-only post-bake.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from website.features.rag_pipeline.rerank import cascade
from website.features.rag_pipeline.rerank.degradation_log import DegradationLogger


def test_cascade_passes_runtime_dir_to_degradation_logger(tmp_path, monkeypatch):
    # Use tmp_path for both env override AND model_dir - ModelManager mkdir's
    # the model_dir on init; passing a real-looking root path like
    # "/some/model/dir" perms-fails on Linux CI.
    log_path = tmp_path / "logs"
    model_path = tmp_path / "models"
    monkeypatch.setenv("RAG_DEGRADATION_LOG_DIR", str(log_path))
    captured = {}

    def _capture_init(self, log_dir):
        captured["log_dir"] = str(log_dir)
        self._log_path = Path(log_dir) / "degradation_events.jsonl"

    with patch.object(DegradationLogger, "__init__", _capture_init):
        reranker = cascade.CascadeReranker(model_dir=str(model_path))

    assert captured["log_dir"] == str(log_path), (
        "CascadeReranker must pass RAG_DEGRADATION_LOG_DIR to DegradationLogger, "
        "NOT model_dir. /app/models is read-only at runtime."
    )


def test_cascade_default_log_dir_is_app_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("RAG_DEGRADATION_LOG_DIR", raising=False)
    model_path = tmp_path / "models"
    captured = {}

    def _capture_init(self, log_dir):
        captured["log_dir"] = str(log_dir)
        self._log_path = Path(log_dir) / "degradation_events.jsonl"

    with patch.object(DegradationLogger, "__init__", _capture_init):
        reranker = cascade.CascadeReranker(model_dir=str(model_path))

    assert captured["log_dir"] == "/app/runtime", (
        "Default log_dir when RAG_DEGRADATION_LOG_DIR unset must be /app/runtime."
    )
