"""Quality-gate CLI: blocks promotion when an iter's eval scores regress."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


GATE = Path(__file__).resolve().parents[4] / "ops" / "scripts" / "rag_eval_quality_gate.py"


def _write_eval(tmp_path: Path, source: str, iter_num: int, eval_json: dict) -> Path:
    iter_dir = tmp_path / "docs" / "rag_eval" / source / f"iter-{iter_num:02d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "eval.json").write_text(json.dumps(eval_json), encoding="utf-8")
    return iter_dir


def _happy_eval() -> dict:
    return {
        "iter_id": "youtube/iter-99",
        "component_scores": {
            "chunking": 70.0, "retrieval": 100.0, "reranking": 90.0, "synthesis": 88.0,
        },
        "composite": 89.0,
        "weights": {"chunking": 0.1, "retrieval": 0.25, "reranking": 0.2, "synthesis": 0.45},
        "weights_hash": "x",
        "graph_lift": {"composite": 0.0, "retrieval": 0.0, "reranking": 0.0},
        "per_query": [],
        "faithfulness_score": 85.0,
        "answer_relevancy_score": 91.0,
    }


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), "--docs-root", str(tmp_path / "docs"), *args],
        capture_output=True, text=True,
    )


def test_happy_path_passes(tmp_path):
    _write_eval(tmp_path, "youtube", 7, _happy_eval())
    proc = _run(tmp_path, "--source", "youtube", "--iter", "7")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout


def test_composite_below_threshold_blocks(tmp_path):
    bad = _happy_eval()
    bad["composite"] = 87.99
    _write_eval(tmp_path, "youtube", 7, bad)
    proc = _run(tmp_path, "--source", "youtube", "--iter", "7")
    assert proc.returncode == 1
    assert "composite" in proc.stdout.lower() or "composite" in proc.stderr.lower()


def test_faithfulness_below_threshold_blocks(tmp_path):
    bad = _happy_eval()
    bad["faithfulness_score"] = 79.9
    _write_eval(tmp_path, "youtube", 7, bad)
    proc = _run(tmp_path, "--source", "youtube", "--iter", "7")
    assert proc.returncode == 1
    assert "faithfulness" in proc.stdout.lower() or "faithfulness" in proc.stderr.lower()


def test_retrieval_below_threshold_blocks(tmp_path):
    bad = _happy_eval()
    bad["component_scores"]["retrieval"] = 94.9
    _write_eval(tmp_path, "youtube", 7, bad)
    proc = _run(tmp_path, "--source", "youtube", "--iter", "7")
    assert proc.returncode == 1
    assert "retrieval" in proc.stdout.lower() or "retrieval" in proc.stderr.lower()


def test_iter_defaults_to_most_recent(tmp_path):
    _write_eval(tmp_path, "youtube", 5, _happy_eval())
    bad = _happy_eval()
    bad["composite"] = 50.0
    _write_eval(tmp_path, "youtube", 6, bad)  # most recent
    proc = _run(tmp_path, "--source", "youtube")
    assert proc.returncode == 1
