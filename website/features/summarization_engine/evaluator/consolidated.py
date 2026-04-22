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
        import asyncio as _asyncio

        t0 = time.perf_counter()
        last_text = ""
        result = None
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                result = await self._client.generate(
                    prompt,
                    tier="pro",
                    system_instruction=CONSOLIDATED_SYSTEM,
                    temperature=0.0,
                    max_output_tokens=32768,
                )
                last_text = (result.text or "").strip()
                if last_text:
                    last_exc = None
                    break
            except Exception as exc:  # noqa: BLE001 — retry on any transient failure
                last_exc = exc
                if attempt < 2:
                    await _asyncio.sleep(2 * (attempt + 1))
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if last_exc is not None and not last_text:
            raise RuntimeError(
                f"Evaluator failed after 3 attempts: {type(last_exc).__name__}: {last_exc}"
            ) from last_exc

        if not last_text:
            raise RuntimeError(
                "Evaluator returned empty text after 3 attempts "
                f"(model={getattr(result, 'model_used', '?')}, "
                f"in={getattr(result, 'input_tokens', 0)}, "
                f"out={getattr(result, 'output_tokens', 0)})"
            )

        try:
            payload = parse_json_object(last_text)
        except Exception as exc:
            preview = last_text[:200].replace("\n", " ")
            raise RuntimeError(
                f"Evaluator returned non-JSON: {exc} | preview={preview!r}"
            ) from exc

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
