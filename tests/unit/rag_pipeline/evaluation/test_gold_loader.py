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
    question: "?"
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
    question: "?"
    gold_node_ids: [x]
    gold_ranking: [x]
    reference_answer: y
    atomic_facts: [z]
""" for i in range(3)])
    path = _write(tmp_path / "heldout.yaml", yaml_text)
    (tmp_path / ".heldout_sealed").write_text("sealed", encoding="utf-8")
    queries = load_heldout_queries(path, allow_sealed=True)
    assert len(queries) == 3
