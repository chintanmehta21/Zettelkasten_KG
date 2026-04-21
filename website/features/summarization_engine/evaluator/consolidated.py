"""The consolidated Gemini-Pro evaluation call."""
from __future__ import annotations

import json
import time
from typing import Any

import yaml

from website.features.summarization_engine.evaluator.models import EvalResult
from website.features.summarization_engine.evaluator.prompts import (
    CONSOLIDATED_SYSTEM,
    CONSOLIDATED_USER_TEMPLATE,
    PROMPT_VERSION,
)
from website.features.summarization_engine.summarization.common.json_utils import (
    parse_json_object,
)


class ConsolidatedEvaluator:
    def __init__(self, gemini_client: Any) -> None:
        self._client = gemini_client

    async def evaluate(
        self,
        *,
        rubric_yaml: dict,
        atomic_facts: list[dict],
        source_text: str,
        summary_json: dict,
    ) -> EvalResult:
        prompt = CONSOLIDATED_USER_TEMPLATE.format(
            rubric_yaml=yaml.safe_dump(rubric_yaml, sort_keys=False),
            atomic_facts=json.dumps(atomic_facts, indent=2),
            source_text=source_text[:30000],
            summary_json=json.dumps(summary_json, indent=2),
        )
        t0 = time.perf_counter()
        result = await self._client.generate(
            prompt,
            tier="pro",
            system_instruction=CONSOLIDATED_SYSTEM,
            temperature=0.0,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        try:
            if result.text.strip().startswith("{"):
                payload = parse_json_object(result.text)
            else:
                payload = json.loads(result.text)
        except Exception as exc:
            raise RuntimeError(f"Evaluator returned non-JSON: {exc}") from exc

        payload.setdefault("evaluator_metadata", {})
        payload["evaluator_metadata"].setdefault("prompt_version", PROMPT_VERSION)
        payload["evaluator_metadata"].setdefault(
            "rubric_version", rubric_yaml.get("version", "unknown")
        )
        payload["evaluator_metadata"]["total_tokens_in"] = getattr(
            result, "input_tokens", 0
        )
        payload["evaluator_metadata"]["total_tokens_out"] = getattr(
            result, "output_tokens", 0
        )
        payload["evaluator_metadata"]["latency_ms"] = latency_ms
        return EvalResult(**payload)
