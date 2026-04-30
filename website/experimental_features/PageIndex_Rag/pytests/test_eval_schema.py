from website.experimental_features.PageIndex_Rag.config import REPO_ROOT, PageIndexRagConfig, load_config
from website.experimental_features.PageIndex_Rag.eval_runner import build_eval_payload
from website.experimental_features.PageIndex_Rag.generator import build_answer_prompt
from website.experimental_features.PageIndex_Rag.types import AnswerCandidate, EvidenceItem, PageIndexQueryResult
from website.experimental_features.PageIndex_Rag.cli import run_eval

import pytest


def test_answer_prompt_requires_json_and_citations():
    prompt = build_answer_prompt(
        query="What is this?",
        style="direct",
        evidence=[EvidenceItem("n", "d", "Title", "https://x", "Summary", "1", "Evidence", 1.0)],
    )
    assert "Return JSON" in prompt
    assert "cited_node_ids" in prompt
    assert "n" in prompt


def test_eval_payload_records_three_answers_and_metrics():
    answers = (
        AnswerCandidate("a1", "direct", "one", ("n",), ({"node_id": "n"},)),
        AnswerCandidate("a2", "comparative", "two", ("n",), ({"node_id": "n"},)),
        AnswerCandidate("a3", "exploratory", "three", ("n",), ({"node_id": "n"},)),
    )
    result = PageIndexQueryResult(
        query_id="q1",
        query="question",
        retrieved_node_ids=("n",),
        reranked_node_ids=("n",),
        evidence=(),
        answers=answers,
        timings_ms={"total_ms": 12.0},
        memory_rss_mb={},
    )
    payload = build_eval_payload(
        queries=[{"qid": "q1", "expected_primary_citation": "n"}],
        results=[result],
    )
    assert payload["total_queries"] == 1
    assert payload["per_query"][0]["answer_count"] == 3
    assert payload["summary"]["recall_at_5"] == 1.0


def test_eval_payload_records_production_fields_and_counts_infra_failures():
    answers = (
        AnswerCandidate("a1", "direct", "one", ("n",), ({"node_id": "n"},)),
        AnswerCandidate("a2", "comparative", "two", ("n",), ({"node_id": "n"},)),
        AnswerCandidate("a3", "exploratory", "three", ("n",), ({"node_id": "n"},)),
    )
    result = PageIndexQueryResult(
        query_id="q1",
        query="question",
        retrieved_node_ids=("n",),
        reranked_node_ids=("n",),
        evidence=(),
        answers=answers,
        timings_ms={"total_ms": 100.0},
        memory_rss_mb={},
    )
    payload = build_eval_payload(
        queries=[
            {"qid": "q1", "expected_primary_citation": "n"},
            {"qid": "q2", "expected_primary_citation": "m"},
        ],
        results=[result],
        failures=[{"query_id": "q2", "http_status": 500, "elapsed_ms": 250.0, "error": "boom"}],
        iter_id="PageIndex/knowledge-management/iter-02",
    )
    assert payload["iter_id"] == "PageIndex/knowledge-management/iter-02"
    assert payload["per_query"][0]["http_status"] == 200
    assert payload["per_query"][0]["elapsed_ms"] == 100.0
    assert payload["per_query"][0]["gold_at_1"] is True
    assert payload["per_query"][0]["primary_citation"] == "n"
    assert payload["per_query"][0]["critic_verdict"] == "supported"
    assert payload["per_query"][1]["infra_failure"] is True
    assert payload["summary"]["infra_failures"] == 1
    assert payload["summary"]["end_to_end_gold_at_1"] == 0.5
    assert payload["summary"]["p95_latency_ms"] >= 100.0


def test_config_accepts_iter_02_env_overrides(monkeypatch, tmp_path):
    queries = tmp_path / "queries.json"
    eval_dir = tmp_path / "iter-02"
    monkeypatch.setenv("PAGEINDEX_RAG_ITER_ID", "iter-02")
    monkeypatch.setenv("PAGEINDEX_RAG_EVAL_DIR", str(eval_dir))
    monkeypatch.setenv("PAGEINDEX_RAG_QUERIES_PATH", str(queries))
    config = load_config()
    assert config.iter_id == "iter-02"
    assert config.eval_dir == eval_dir
    assert config.queries_path == queries
    assert str(REPO_ROOT) in str(config.login_details_path)


@pytest.mark.asyncio
async def test_eval_cli_exits_cleanly_when_login_details_missing(tmp_path, monkeypatch):
    config = PageIndexRagConfig(
        enabled=True,
        mode="local",
        iter_id="iter-02",
        workspace=tmp_path / "workspace",
        eval_dir=tmp_path / "eval",
        queries_path=tmp_path / "queries.json",
        login_details_path=tmp_path / "login_details.txt",
        kasten_slug="knowledge-management",
        kasten_name="Knowledge Management",
        candidate_limit=7,
    )
    monkeypatch.setattr("website.experimental_features.PageIndex_Rag.cli.load_config", lambda: config)
    with pytest.raises(SystemExit) as exc:
        await run_eval()
    assert "Missing" in str(exc.value)
    assert "password" not in str(exc.value).lower()
