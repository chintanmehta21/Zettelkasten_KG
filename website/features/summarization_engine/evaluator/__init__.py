"""Public evaluator API."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from website.features.summarization_engine.evaluator.atomic_facts import (
    extract_atomic_facts,
)
from website.features.summarization_engine.evaluator.consolidated import (
    ConsolidatedEvaluator,
)
from website.features.summarization_engine.evaluator.models import (
    EvalResult,
    composite_score,
)
from website.features.summarization_engine.evaluator.ragas_bridge import RagasBridge
from website.features.summarization_engine.evaluator.rubric_loader import load_rubric


async def evaluate(
    *,
    gemini_client: Any,
    summary_json: dict,
    source_text: str,
    source_type: str,
    url: str,
    ingestor_version: str,
    rubric_path: Path,
    cache_root: Path,
) -> EvalResult:
    """Run the full consolidated evaluation."""
    rubric_yaml = load_rubric(rubric_path)
    facts = await extract_atomic_facts(
        client=gemini_client,
        source_text=source_text,
        cache_root=cache_root,
        url=url,
        ingestor_version=ingestor_version,
    )
    evaluator = ConsolidatedEvaluator(gemini_client)
    result = await evaluator.evaluate(
        rubric_yaml=rubric_yaml,
        atomic_facts=facts,
        source_text=source_text,
        summary_json=summary_json,
    )
    if result.finesure.faithfulness.score < 0.9:
        bridge = RagasBridge(gemini_client)
        ragas_score = await bridge.faithfulness(
            summary=str(summary_json),
            source=source_text,
        )
        result.evaluator_metadata["ragas_faithfulness"] = ragas_score
    return result


__all__ = ["evaluate", "EvalResult", "composite_score"]
