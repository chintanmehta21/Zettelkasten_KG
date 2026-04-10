"""Chain-of-Density densification phase."""
from __future__ import annotations

from dataclasses import dataclass

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import IngestResult
from website.features.summarization_engine.summarization.common.prompts import SYSTEM_PROMPT, source_context


@dataclass
class DensifyResult:
    text: str
    iterations_used: int
    pro_tokens: int


class ChainOfDensityDensifier:
    def __init__(self, client: TieredGeminiClient, config: EngineConfig):
        self._client = client
        self._config = config

    async def densify(self, ingest: IngestResult) -> DensifyResult:
        if not self._config.chain_of_density.enabled:
            return DensifyResult(ingest.raw_text, 0, 0)

        current = ingest.raw_text
        total_tokens = 0
        iterations = int(self._config.chain_of_density.iterations)
        for index in range(iterations):
            prompt = (
                f"{source_context(ingest.source_type)}\n\n"
                "Create a denser factual summary without losing entities, numbers, constraints, or caveats.\n"
                f"Iteration: {index + 1}\n\nSOURCE:\n{current}"
            )
            result = await self._client.generate(
                prompt,
                tier="pro",
                system_instruction=SYSTEM_PROMPT,
            )
            current = result.text.strip() or current
            total_tokens += result.input_tokens + result.output_tokens

        return DensifyResult(current, iterations, total_tokens)
