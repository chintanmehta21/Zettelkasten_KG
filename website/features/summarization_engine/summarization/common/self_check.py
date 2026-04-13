"""Inverted FactScore self-check phase."""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.summarization.common.json_utils import parse_json_object
from website.features.summarization_engine.summarization.common.prompts import SYSTEM_PROMPT

_IMPORTANCE_MAP = {"low": 1, "medium": 2, "mid": 2, "high": 3, "very high": 4, "critical": 5}


class MissingClaim(BaseModel):
    claim: str
    importance: int = Field(default=1, ge=1, le=5)

    @field_validator("importance", mode="before")
    @classmethod
    def coerce_importance(cls, v):
        if isinstance(v, int):
            return max(1, min(v, 5))
        if isinstance(v, str):
            s = v.strip().lower().split(".")[0].split(",")[0].strip()
            try:
                return max(1, min(int(s), 5))
            except ValueError:
                return _IMPORTANCE_MAP.get(s, 3)
        return 1


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
        missing = []
        for item in payload.get("missing", [])[: self._config.self_check.max_atomic_claims]:
            try:
                missing.append(MissingClaim(**item))
            except Exception:
                continue
        return SelfCheckResult(missing=missing, pro_tokens=tokens)
