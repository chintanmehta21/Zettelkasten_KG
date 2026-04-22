"""YouTube transcript fallback chain scaffold."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable


class TierName(str, Enum):
    YTDLP_PLAYER_ROTATION = "ytdlp_player_rotation"
    TRANSCRIPT_API_DIRECT = "transcript_api_direct"
    PIPED_POOL = "piped_pool"
    INVIDIOUS_POOL = "invidious_pool"
    GEMINI_AUDIO = "gemini_audio"
    METADATA_ONLY = "metadata_only"


@dataclass
class TierResult:
    tier: TierName
    transcript: str
    success: bool
    confidence: str = "low"
    latency_ms: int = 0
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


TierFn = Callable[[str, dict], Awaitable[TierResult]]


class TranscriptChain:
    def __init__(self, tiers: list[TierFn], budget_ms: int = 90000) -> None:
        self._tiers = tiers
        self._budget_ms = budget_ms

    async def run(self, *, video_id: str, config: dict) -> TierResult:
        start = time.monotonic()
        last_result: TierResult | None = None

        for tier in self._tiers:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if elapsed_ms >= self._budget_ms:
                break
            last_result = await tier(video_id, config)
            if last_result.success:
                return last_result

        return last_result or TierResult(
            tier=TierName.METADATA_ONLY,
            transcript="",
            success=False,
        )
