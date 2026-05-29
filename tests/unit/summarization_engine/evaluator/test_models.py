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


def test_g_eval_scores_legacy_float_coerced_into_ternary():
    """Back-compat: legacy 0-5 float fixtures map into the new {1,2,3} band."""
    scores = GEvalScores(
        coherence=4.5,   # legacy float -> 3
        fluency=2.0,     # legacy float -> 2
    )

    assert scores.coherence.score == 3
    assert scores.fluency.score == 2


def test_composite_score_hallucination_cap_overrides_high_scores():
    result = EvalResult(
        g_eval=GEvalScores(
            coherence={"score": 3, "anchor": "", "reasoning": ""},
            fluency={"score": 3, "anchor": "", "reasoning": ""},
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


def test_eval_result_tolerates_missing_summac_lite():
    """Regression: judges occasionally omit summac_lite under token pressure on
    very long summaries (observed iter-001-baseline 2026-05-28 on wz=1c0af8ec,
    6828-char summary). EvalResult must parse the partial payload to None
    instead of raising ValidationError, so the rest of the eval is salvageable.
    """
    payload = {
        "g_eval": {
            "coherence": {"score": 2, "anchor": "", "reasoning": ""},
            "fluency": {"score": 3, "anchor": "", "reasoning": ""},
        },
        "finesure": {
            "faithfulness": {"score": 0.9, "items": []},
            "completeness": {"score": 0.8, "items": []},
            "conciseness": {"score": 0.85, "items": []},
        },
        # summac_lite intentionally omitted (judge dropped it under length pressure).
        "rubric": {
            "components": [],
            "caps_applied": {"hallucination_cap": None, "omission_cap": None, "generic_cap": None},
            "anti_patterns_triggered": [],
        },
        "maps_to_metric_summary": {"g_eval": 80.0, "finesure": 85.0, "qafact": 0.0, "summac": 0.0},
        "evaluator_metadata": {},
    }
    result = EvalResult.model_validate(payload)
    assert result.summac_lite is None
    # composite_score does not reference summac_lite → must still compute cleanly
    assert isinstance(composite_score(result), float)


def test_eval_result_summac_lite_present_validates_normally():
    """Happy path: when summac_lite IS present (the common case), it validates
    as SummaCLite — the Optional change must not regress existing behavior."""
    summac = SummaCLite(score=0.9, contradicted_sentences=[], neutral_sentences=[])
    payload = {
        "g_eval": {
            "coherence": {"score": 2, "anchor": "", "reasoning": ""},
            "fluency": {"score": 3, "anchor": "", "reasoning": ""},
        },
        "finesure": {
            "faithfulness": {"score": 0.9, "items": []},
            "completeness": {"score": 0.8, "items": []},
            "conciseness": {"score": 0.85, "items": []},
        },
        "summac_lite": summac.model_dump(),
        "rubric": {
            "components": [],
            "caps_applied": {"hallucination_cap": None, "omission_cap": None, "generic_cap": None},
            "anti_patterns_triggered": [],
        },
        "maps_to_metric_summary": {"g_eval": 80.0, "finesure": 85.0, "qafact": 0.0, "summac": 90.0},
        "evaluator_metadata": {},
    }
    result = EvalResult.model_validate(payload)
    assert result.summac_lite is not None
    assert result.summac_lite.score == 0.9
