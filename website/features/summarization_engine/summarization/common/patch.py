"""Conditional summary patching phase."""
from __future__ import annotations

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.summarization.common.prompts import SYSTEM_PROMPT
from website.features.summarization_engine.summarization.common.self_check import SelfCheckResult


class SummaryPatcher:
    def __init__(self, client: TieredGeminiClient, config: EngineConfig):
        self._client = client
        self._config = config

    async def patch(self, summary_text: str, check: SelfCheckResult) -> tuple[str, bool, int]:
        if check.missing_count < self._config.self_check.patch_threshold:
            return summary_text, False, 0
        missing = "\n".join(f"- {item.claim}" for item in check.missing)
        prompt = (
            "Patch SUMMARY to include the missing claims. Keep it concise and factual.\n\n"
            f"SUMMARY:\n{summary_text}\n\nMISSING:\n{missing}"
        )
        result = await self._client.generate(prompt, tier="pro", system_instruction=SYSTEM_PROMPT)
        return result.text.strip() or summary_text, True, result.input_tokens + result.output_tokens
