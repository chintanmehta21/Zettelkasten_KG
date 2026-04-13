"""Tests for degradation telemetry logging."""

from __future__ import annotations

import json
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

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
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
    raw = log_path.read_text(encoding="utf-8")

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
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()

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
    record = json.loads(log_path.read_text(encoding="utf-8").strip())

    assert record["content_length_stats"] == {"min": 0, "max": 0, "mean": 0}
