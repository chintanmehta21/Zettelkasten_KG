from website.features.summarization_engine.evaluator.models import (
    AntiPatternTrigger,
    EvalResult,
    FineSurEDimension,
    FineSurEScores,
    GEvalScores,
    RubricBreakdown,
    RubricComponent,
    SummaCLite,
    apply_caps,
    composite_score,
)


def test_g_eval_scores_coerce_percent_scale():
    scores = GEvalScores(
        coherence=71.11,
        consistency=100,
        fluency=4.5,
        relevance=65.21,
    )

    assert scores.coherence == 71.11 / 20
    assert scores.consistency == 5.0
    assert scores.fluency == 4.5
    assert scores.relevance == 65.21 / 20


def test_composite_score_hallucination_cap_overrides_high_scores():
    result = EvalResult(
        g_eval=GEvalScores(
            coherence=5,
            consistency=5,
            fluency=5,
            relevance=5,
            reasoning="",
        ),
        finesure=FineSurEScores(
            faithfulness=FineSurEDimension(score=1.0, items=[]),
            completeness=FineSurEDimension(score=1.0, items=[]),
            conciseness=FineSurEDimension(score=1.0, items=[]),
        ),
        summac_lite=SummaCLite(
            score=1.0,
            contradicted_sentences=[],
            neutral_sentences=[],
        ),
        rubric=RubricBreakdown(
            components=[
                RubricComponent(
                    id="brief_summary",
                    score=25,
                    max_points=25,
                    criteria_fired=[],
                    criteria_missed=[],
                ),
                RubricComponent(
                    id="detailed_summary",
                    score=45,
                    max_points=45,
                    criteria_fired=[],
                    criteria_missed=[],
                ),
                RubricComponent(
                    id="tags",
                    score=15,
                    max_points=15,
                    criteria_fired=[],
                    criteria_missed=[],
                ),
                RubricComponent(
                    id="label",
                    score=15,
                    max_points=15,
                    criteria_fired=[],
                    criteria_missed=[],
                ),
            ],
            caps_applied={
                "hallucination_cap": 60,
                "omission_cap": None,
                "generic_cap": None,
            },
            anti_patterns_triggered=[
                AntiPatternTrigger(
                    id="production_ready_claim_no_evidence",
                    source_region="",
                    auto_cap=60,
                )
            ],
        ),
        maps_to_metric_summary={
            "g_eval_composite": 100.0,
            "finesure_composite": 100.0,
            "qafact_composite": 100.0,
            "summac_composite": 100.0,
        },
        editorialization_flags=[],
        evaluator_metadata={
            "prompt_version": "evaluator.v1",
            "rubric_version": "rubric_youtube.v1",
            "atomic_facts_hash": "",
            "model_used": "gemini-2.5-pro",
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "latency_ms": 0,
        },
    )

    assert composite_score(result) == 60.0


def test_apply_caps_returns_original_score_without_caps():
    assert apply_caps(87.5, {}) == 87.5
