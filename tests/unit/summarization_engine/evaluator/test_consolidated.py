import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.evaluator.consolidated import (
    ConsolidatedEvaluator,
)
from website.features.summarization_engine.evaluator.models import EvalResult


_GOOD_RESPONSE = {
    "g_eval": {
        "coherence": 4.5,
        "consistency": 4.2,
        "fluency": 4.8,
        "relevance": 4.0,
        "reasoning": "ok",
    },
    "finesure": {
        "faithfulness": {"score": 0.95, "items": []},
        "completeness": {"score": 0.88, "items": []},
        "conciseness": {"score": 0.9, "items": []},
    },
    "summac_lite": {
        "score": 0.93,
        "contradicted_sentences": [],
        "neutral_sentences": [],
    },
    "rubric": {
        "components": [
            {
                "id": "brief_summary",
                "score": 22,
                "max_points": 25,
                "criteria_fired": [],
                "criteria_missed": [],
            },
            {
                "id": "detailed_summary",
                "score": 40,
                "max_points": 45,
                "criteria_fired": [],
                "criteria_missed": [],
            },
            {
                "id": "tags",
                "score": 13,
                "max_points": 15,
                "criteria_fired": [],
                "criteria_missed": [],
            },
            {
                "id": "label",
                "score": 14,
                "max_points": 15,
                "criteria_fired": [],
                "criteria_missed": [],
            },
        ],
        "caps_applied": {
            "hallucination_cap": None,
            "omission_cap": None,
            "generic_cap": None,
        },
        "anti_patterns_triggered": [],
    },
    "maps_to_metric_summary": {
        "g_eval_composite": 90,
        "finesure_composite": 91,
        "qafact_composite": 90,
        "summac_composite": 93,
    },
    "editorialization_flags": [],
    "evaluator_metadata": {
        "prompt_version": "evaluator.v1",
        "rubric_version": "rubric_youtube.v1",
        "atomic_facts_hash": "abc",
        "model_used": "gemini-2.5-pro",
        "total_tokens_in": 100,
        "total_tokens_out": 50,
        "latency_ms": 1500,
    },
}


@pytest.mark.asyncio
async def test_consolidated_evaluator_parses_response():
    client = MagicMock()
    client.generate = AsyncMock(
        return_value=MagicMock(
            text=json.dumps(_GOOD_RESPONSE),
            input_tokens=100,
            output_tokens=50,
        )
    )

    evaluator = ConsolidatedEvaluator(client)
    result = await evaluator.evaluate(
        rubric_yaml={
            "version": "rubric_youtube.v1",
            "composite_max_points": 100,
            "source_type": "youtube",
            "components": [],
        },
        atomic_facts=[{"claim": "x", "importance": 3}],
        source_text="source",
        summary_json={"mini_title": "t"},
    )

    assert isinstance(result, EvalResult)
    assert result.rubric.total_of_100 == 89
