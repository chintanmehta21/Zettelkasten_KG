from __future__ import annotations

import json
from pathlib import Path


FIXTURES_DIR = Path("tests/eval/ragas/fixtures")


def _load(name: str) -> list[dict]:
    path = FIXTURES_DIR / name
    assert path.exists(), f"Missing fixture file: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_synthetic_corpus_fixture_has_expected_shape() -> None:
    data = _load("synthetic_corpus.json")

    assert len(data) == 50

    required = {
        "id",
        "user_id",
        "name",
        "source_type",
        "summary",
        "tags",
        "url",
        "node_date",
        "metadata",
    }
    for row in data:
        assert required.issubset(row)
        assert isinstance(row["tags"], list)
        assert isinstance(row["metadata"], dict)
        assert row["summary"]


def test_golden_qa_fixture_has_expected_shape() -> None:
    data = _load("golden_qa.json")

    assert len(data) == 30

    required = {
        "user_input",
        "retrieved_contexts",
        "response",
        "reference",
        "ground_truth_support",
    }
    for row in data:
        assert required.issubset(row)
        assert row["user_input"]
        assert isinstance(row["retrieved_contexts"], list)
        assert isinstance(row["ground_truth_support"], list)
        assert row["ground_truth_support"]
