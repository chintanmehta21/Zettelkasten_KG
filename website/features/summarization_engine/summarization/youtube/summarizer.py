"""YouTube per-source summarizer."""
from __future__ import annotations

import time

from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
    SummaryResult,
)
from website.features.summarization_engine.summarization import register_summarizer
from website.features.summarization_engine.summarization.base import BaseSummarizer
from website.features.summarization_engine.summarization.common.cod import (
    ChainOfDensityDensifier,
)
from website.features.summarization_engine.summarization.common.patch import SummaryPatcher
from website.features.summarization_engine.summarization.common.self_check import (
    InvertedFactScoreSelfCheck,
)
from website.features.summarization_engine.summarization.common.structured import (
    StructuredExtractor,
)
from website.features.summarization_engine.summarization.youtube.prompts import (
    STRUCTURED_EXTRACT_INSTRUCTION,
)
from website.features.summarization_engine.summarization.youtube.schema import (
    YouTubeStructuredPayload,
)


class YouTubeSummarizer(BaseSummarizer):
    source_type = SourceType.YOUTUBE

    def __init__(self, gemini_client: TieredGeminiClient, config):
        super().__init__(gemini_client, config)
        from website.features.summarization_engine.core.config import load_config

        self._engine_config = load_config()

    async def summarize(self, ingest: IngestResult) -> SummaryResult:
        start = time.perf_counter()
        densifier = ChainOfDensityDensifier(self._client, self._engine_config)
        self_checker = InvertedFactScoreSelfCheck(self._client, self._engine_config)
        patcher = SummaryPatcher(self._client, self._engine_config)
        structured = StructuredExtractor(
            self._client,
            self._engine_config,
            payload_class=YouTubeStructuredPayload,
            prompt_instruction=STRUCTURED_EXTRACT_INSTRUCTION,
        )

        dense = await densifier.densify(ingest)
        check = await self_checker.check(ingest.raw_text, dense.text)
        patched_text, patch_applied, patch_tokens = await patcher.patch(
            dense.text, check
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        return await structured.extract(
            ingest,
            patched_text,
            pro_tokens=dense.pro_tokens + check.pro_tokens + patch_tokens,
            flash_tokens=0,
            latency_ms=latency_ms,
            cod_iterations_used=dense.iterations_used,
            self_check_missing_count=check.missing_count,
            patch_applied=patch_applied,
        )


register_summarizer(YouTubeSummarizer)
