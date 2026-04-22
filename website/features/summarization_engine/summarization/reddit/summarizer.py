"""Reddit per-source summarizer."""
from __future__ import annotations

import time
from copy import deepcopy

from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
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
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditStructuredPayload,
)


class RedditSummarizer(BaseSummarizer):
    source_type = SourceType.REDDIT

    def __init__(self, gemini_client: TieredGeminiClient, config):
        super().__init__(gemini_client, config)
        from website.features.summarization_engine.core.config import load_config

        self._engine_config = load_config()

    async def summarize(self, ingest: IngestResult) -> SummaryResult:
        start = time.perf_counter()
        dense = await ChainOfDensityDensifier(
            self._client, self._engine_config
        ).densify(ingest)
        check = await InvertedFactScoreSelfCheck(
            self._client, self._engine_config
        ).check(ingest.raw_text, dense.text)
        patched, patch_applied, patch_tokens = await SummaryPatcher(
            self._client, self._engine_config
        ).patch(dense.text, check)
        extractor = StructuredExtractor(
            self._client,
            self._engine_config,
            payload_class=RedditStructuredPayload,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        result = await extractor.extract(
            ingest,
            patched,
            pro_tokens=dense.pro_tokens + check.pro_tokens + patch_tokens,
            flash_tokens=0,
            latency_ms=latency_ms,
            cod_iterations_used=dense.iterations_used,
            self_check_missing_count=check.missing_count,
            patch_applied=patch_applied,
        )
        return _enrich_reddit_result(result, ingest)


register_summarizer(RedditSummarizer)


def _enrich_reddit_result(result: SummaryResult, ingest: IngestResult) -> SummaryResult:
    payload = deepcopy(result.metadata.structured_payload or {})
    detailed = deepcopy(payload.get("detailed_summary") or {})
    tags = [str(tag) for tag in (payload.get("tags") or result.tags)]
    subreddit = str(ingest.metadata.get("subreddit") or "").strip()
    divergence = float(ingest.metadata.get("comment_divergence_pct") or 0.0)
    pullpush_fetched = int(ingest.metadata.get("pullpush_fetched") or 0)

    if subreddit:
        subreddit_tag = f"r-{subreddit.lower().replace('_', '-')}"
        if subreddit_tag not in tags:
            tags.insert(0, subreddit_tag)

    if divergence >= 20:
        note = (
            f"Rendered comments covered only part of the thread "
            f"({ingest.metadata.get('rendered_comment_count', 0)}/"
            f"{ingest.metadata.get('num_comments', 0)} visible; "
            f"divergence {divergence:.2f}%)."
        )
        if pullpush_fetched > 0:
            note += f" {pullpush_fetched} removed comments were recovered from pullpush.io."
        detailed["moderation_context"] = note

    payload["tags"] = tags[:10]
    payload["detailed_summary"] = detailed
    sections = _rebuild_sections(result.detailed_summary, detailed)
    updated = result.model_copy(deep=True)
    updated.tags = tags[:10]
    updated.detailed_summary = sections
    updated.metadata.structured_payload = payload
    return updated


def _rebuild_sections(
    existing: list[DetailedSummarySection],
    detailed_payload: dict,
) -> list[DetailedSummarySection]:
    sections = list(existing)
    moderation = detailed_payload.get("moderation_context")
    if not moderation:
        return sections
    for section in sections:
        if section.heading == "moderation_context":
            section.bullets = [str(moderation)]
            return sections
    sections.append(
        DetailedSummarySection(heading="moderation_context", bullets=[str(moderation)])
    )
    return sections
