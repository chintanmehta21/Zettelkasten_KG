"""Inverted FactScore self-check phase."""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.summarization.common.json_utils import parse_json_object
from website.features.summarization_engine.summarization.common.prompts import SYSTEM_PROMPT


class MissingClaim(BaseModel):
    claim: str
    importance: int = Field(default=1, ge=1, le=5)


@dataclass
class SelfCheckResult:
    missing: list[MissingClaim] = field(default_factory=list)
    pro_tokens: int = 0

    @property
    def missing_count(self) -> int:
        return len(self.missing)


class InvertedFactScoreSelfCheck:
    def __init__(self, client: TieredGeminiClient, config: EngineConfig):
        self._client = client
        self._config = config

    async def check(self, source_text: str, summary_text: str) -> SelfCheckResult:
        if not self._config.self_check.enabled:
            return SelfCheckResult()
        prompt = (
            "Compare SOURCE to SUMMARY. Return JSON with key missing, a list of "
            "important source claims absent from summary. Each item: claim, importance.\n\n"
            f"SOURCE:\n{source_text}\n\nSUMMARY:\n{summary_text}"
        )
        result = await self._client.generate(prompt, tier="pro", system_instruction=SYSTEM_PROMPT)
        tokens = result.input_tokens + result.output_tokens
        try:
            payload = parse_json_object(result.text)
        except Exception:
            return SelfCheckResult(pro_tokens=tokens)
        missing = [MissingClaim(**item) for item in payload.get("missing", [])[: self._config.self_check.max_atomic_claims]]
        return SelfCheckResult(missing=missing, pro_tokens=tokens)
