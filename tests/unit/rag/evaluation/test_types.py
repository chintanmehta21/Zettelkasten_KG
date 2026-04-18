from datetime import datetime

import pytest

from website.features.rag_pipeline.evaluation.types import (
    AxisScore,
    JudgeResult,
    QuestionResult,
    RunReport,
)


def test_axis_score_total_sums_axes():
    score = AxisScore(faithfulness=5, relevance=4, completeness=3, citation_accuracy=2)
    assert score.total == 14


def test_axis_score_rejects_out_of_range():
    with pytest.raises(ValueError):
        AxisScore(faithfulness=6, relevance=0, completeness=0, citation_accuracy=0)


def test_run_report_mean_excludes_errored_questions():
    score = AxisScore(faithfulness=4, relevance=4, completeness=4, citation_accuracy=4)
    scored = QuestionResult(
        question_id="q1",
        category="single_zettel_factual",
        kasten_id="k1",
        question="Q?",
        answer="A",
        retrieved_chunk_ids=["c1"],
        latency_ms=123,
        judge=JudgeResult(scores=score, rationale={}),
    )
    errored = QuestionResult(
        question_id="q2",
        category="single_zettel_factual",
        kasten_id="k1",
        question="Q?",
        answer="",
        retrieved_chunk_ids=[],
        latency_ms=0,
        error="timeout",
    )
    report = RunReport(
        iteration=0,
        module_under_test="baseline",
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        git_sha="abc",
        rubric="b",
        results=[scored, errored],
    )
    assert report.mean_total() == 16.0
