"""Test that ops.scripts.rag_eval_loop._serialize_turn attaches per_stage
to every answer record (Task 4A.1 wiring)."""
from __future__ import annotations

from ops.scripts.rag_eval_loop import _serialize_turn


class _FakeCitation:
    def __init__(self, node_id: str, score: float, snippet: str = "") -> None:
        self._d = {"node_id": node_id, "rerank_score": score, "snippet": snippet}

    def model_dump(self) -> dict:
        return dict(self._d)


class _FakeTurn:
    def __init__(self) -> None:
        self.content = "Go and Markdown."
        self.citations = [
            _FakeCitation("gh-zk-org-zk", 0.94, "zk is written in Go"),
            _FakeCitation("yt-effective-public-speakin", 0.62, "verbal punctuation"),
        ]
        self.query_class = "lookup"
        self.critic_verdict = "supported"
        self.latency_ms = 12_000
        self.llm_model = "gemini-2.5-flash"
        self.retrieved_node_ids = ["gh-zk-org-zk", "yt-effective-public-speakin"]


class _FakeQuery:
    id = "q1"
    gold_node_ids = ["gh-zk-org-zk"]


def test_serialize_turn_attaches_per_stage():
    rec = _serialize_turn(_FakeTurn(), _FakeQuery())
    assert "per_stage" in rec
    ps = rec["per_stage"]
    assert ps["query_class"] == "lookup"
    assert ps["critic_verdict"] == "supported"
    assert ps["synthesizer_grounding_pct"] == 1.0
    assert ps["retrieval_recall_at_10"] == 1.0
    assert ps["model_chain_used"] == ["gemini-2.5-flash"]
    assert ps["latency_ms"]["total"] == 12_000


def test_serialize_turn_no_gold_attribute_falls_back_to_empty_list():
    class _NoGold:
        id = "qX"

    rec = _serialize_turn(_FakeTurn(), _NoGold())
    # No gold means recall is undefined (None) — should not blow up.
    assert rec["per_stage"]["retrieval_recall_at_10"] is None
