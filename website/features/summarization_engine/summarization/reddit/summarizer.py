"""Reddit per-source summarizer (iter-09 contract ported to master)."""
from __future__ import annotations

import json
import logging
import time
from copy import deepcopy

from pydantic import ValidationError

from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    IngestResult,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)
from website.features.summarization_engine.summarization import register_summarizer
from website.features.summarization_engine.summarization.base import BaseSummarizer
from website.features.summarization_engine.summarization.common.cod import (
    ChainOfDensityDensifier,
)
from website.features.summarization_engine.summarization.common.json_utils import (
    parse_json_object,
)
from website.features.summarization_engine.summarization.common.patch import SummaryPatcher
from website.features.summarization_engine.summarization.common.prompts import SYSTEM_PROMPT
from website.features.summarization_engine.summarization.common.self_check import (
    InvertedFactScoreSelfCheck,
)
from website.features.summarization_engine.summarization.reddit.prompts import (
    STRUCTURED_EXTRACT_INSTRUCTION,
)
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditDetailedPayload,
    RedditStructuredPayload,
)

_log = logging.getLogger(__name__)


class RedditSummarizer(BaseSummarizer):
    """Reddit summarizer enforcing the iter-09 rubric contract.

    - label format ``r/<subreddit> ...`` via schema validator.
    - 8-10 tags reserving subreddit + thread_type slots.
    - 5-7 sentence neutral brief, rebuilt deterministically if the model
      under-delivers the contract.
    - Rich detailed payload (op_intent, reply_clusters, counterarguments,
      unresolved_questions, moderation_context) preserved in
      ``metadata`` as the source of truth and back-filled into the
      SummaryResult ``detailed_summary`` section surface.
    """

    source_type = SourceType.REDDIT

    def __init__(self, gemini_client: TieredGeminiClient, config):
        super().__init__(gemini_client, config)
        from website.features.summarization_engine.core.config import load_config

        self._engine_config = load_config()

    async def summarize(self, ingest: IngestResult) -> SummaryResult:
        start = time.perf_counter()
        dense = await ChainOfDensityDensifier(self._client, self._engine_config).densify(ingest)
        check = await InvertedFactScoreSelfCheck(self._client, self._engine_config).check(
            ingest.raw_text, dense.text
        )
        patched, patch_applied, patch_tokens = await SummaryPatcher(
            self._client, self._engine_config
        ).patch(dense.text, check)

        pro_tokens = dense.pro_tokens + check.pro_tokens + patch_tokens
        flash_tokens = 0

        prompt = STRUCTURED_EXTRACT_INSTRUCTION.format(summary_text=patched)
        gen = await self._client.generate(
            prompt,
            tier="flash",
            response_schema=RedditStructuredPayload,
            system_instruction=SYSTEM_PROMPT,
        )
        flash_tokens += gen.input_tokens + gen.output_tokens

        payload = _parse_payload(gen.text, patched, ingest)
        payload = _apply_ingest_enrichments(payload, ingest)

        latency_ms = int((time.perf_counter() - start) * 1000)

        detailed_sections = _detailed_payload_to_sections(payload.detailed_summary)

        return SummaryResult(
            mini_title=payload.mini_title[:60],
            brief_summary=payload.brief_summary[:400],
            tags=payload.tags,
            detailed_summary=detailed_sections,
            metadata=SummaryMetadata(
                source_type=ingest.source_type,
                url=ingest.url,
                author=ingest.metadata.get("author"),
                date=None,
                extraction_confidence=ingest.extraction_confidence,
                confidence_reason=ingest.confidence_reason,
                total_tokens_used=pro_tokens + flash_tokens,
                gemini_pro_tokens=pro_tokens,
                gemini_flash_tokens=flash_tokens,
                total_latency_ms=latency_ms,
                cod_iterations_used=dense.iterations_used,
                self_check_missing_count=check.missing_count,
                patch_applied=patch_applied,
            ),
        )


register_summarizer(RedditSummarizer)


def _parse_payload(
    raw_text: str, summary_text: str, ingest: IngestResult
) -> RedditStructuredPayload:
    """Parse Gemini JSON into the Reddit schema, falling back to a synthesized
    payload if the model drifts off-schema. The schema's validators enforce the
    brief/label/tag contracts even on the fallback."""
    try:
        data = parse_json_object(raw_text)
        return RedditStructuredPayload(**data)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        _log.warning("reddit.structured_parse_failed: %s", exc)
        return _synthesize_fallback_payload(summary_text, ingest)


def _synthesize_fallback_payload(
    summary_text: str, ingest: IngestResult
) -> RedditStructuredPayload:
    subreddit = str(ingest.metadata.get("subreddit") or "reddit").strip() or "reddit"
    title = str(ingest.metadata.get("title") or "thread").strip()
    op_intent = (summary_text or title)[:240]
    detailed = RedditDetailedPayload(
        op_intent=op_intent or f"OP posted in r/{subreddit}.",
        reply_clusters=[
            {
                "theme": "general discussion",
                "reasoning": "Replies covered a mix of opinions on the original post.",
                "examples": [],
            }
        ],
        counterarguments=[],
        unresolved_questions=[],
        moderation_context=None,
    )
    return RedditStructuredPayload(
        mini_title=f"r/{subreddit} {title}"[:60] or f"r/{subreddit} thread",
        brief_summary="",  # schema validator rebuilds from detailed
        tags=[
            f"r-{subreddit.lower().replace('_', '-')}",
            "discussion",
            "reddit-thread",
            "community-discussion",
            "user-replies",
            "reddit",
            "thread",
            "capture",
        ],
        detailed_summary=detailed,
    )


def _apply_ingest_enrichments(
    payload: RedditStructuredPayload, ingest: IngestResult
) -> RedditStructuredPayload:
    """Inject ingest-time signals (subreddit tag + moderation context) that the
    LLM cannot know from the summary alone."""
    subreddit = str(ingest.metadata.get("subreddit") or "").strip()
    if subreddit:
        canonical_tag = f"r-{subreddit.lower().replace('_', '-')}"
        if canonical_tag not in payload.tags:
            payload.tags = [canonical_tag, *payload.tags][:10]

    divergence = _safe_float(ingest.metadata.get("comment_divergence_pct"))
    pullpush_fetched = _safe_int(ingest.metadata.get("pullpush_fetched"))
    if divergence >= 20:
        rendered = _safe_int(ingest.metadata.get("rendered_comment_count"))
        total = _safe_int(ingest.metadata.get("num_comments"))
        note = (
            f"Rendered comments covered only part of the thread "
            f"({rendered}/{total} visible; divergence {divergence:.2f}%)."
        )
        if pullpush_fetched > 0:
            note += f" {pullpush_fetched} removed comments were recovered from pullpush.io."
        detailed = deepcopy(payload.detailed_summary)
        detailed.moderation_context = note
        payload.detailed_summary = detailed
    return payload


def _detailed_payload_to_sections(
    detailed: RedditDetailedPayload,
) -> list[DetailedSummarySection]:
    sections: list[DetailedSummarySection] = []
    if detailed.op_intent:
        sections.append(
            DetailedSummarySection(heading="OP Intent", bullets=[detailed.op_intent])
        )
    if detailed.reply_clusters:
        cluster_sub_sections: dict[str, list[str]] = {}
        bullets: list[str] = []
        for cluster in detailed.reply_clusters:
            bullets.append(f"{cluster.theme}: {cluster.reasoning}".strip(": "))
            if cluster.examples:
                cluster_sub_sections[cluster.theme or "examples"] = list(cluster.examples)
        sections.append(
            DetailedSummarySection(
                heading="Reply Clusters",
                bullets=bullets,
                sub_sections=cluster_sub_sections,
            )
        )
    if detailed.counterarguments:
        sections.append(
            DetailedSummarySection(
                heading="Counterarguments", bullets=list(detailed.counterarguments)
            )
        )
    if detailed.unresolved_questions:
        sections.append(
            DetailedSummarySection(
                heading="Unresolved Questions",
                bullets=list(detailed.unresolved_questions),
            )
        )
    if detailed.moderation_context:
        sections.append(
            DetailedSummarySection(
                heading="Moderation Context",
                bullets=[detailed.moderation_context],
            )
        )
    return sections or [
        DetailedSummarySection(heading="Summary", bullets=["No detailed content was extracted."])
    ]


def _safe_float(value: object) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: object) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0
