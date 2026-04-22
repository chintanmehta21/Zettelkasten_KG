"""Reddit per-source summarizer (iter-09 contract ported to master)."""
from __future__ import annotations

import asyncio
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
    RedditCluster,
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
        try:
            return await self._summarize_inner(ingest)
        except Exception as exc:  # noqa: BLE001
            _log.error(
                "reddit.summarize_unrecoverable type=%s err=%s url=%s",
                type(exc).__name__,
                exc,
                getattr(ingest, "url", None),
                exc_info=True,
            )
            payload = _apply_ingest_enrichments(
                _build_minimum_safe_payload("", ingest), ingest
            )
            return SummaryResult(
                mini_title=payload.mini_title[:60],
                brief_summary=payload.brief_summary[:400],
                tags=payload.tags,
                detailed_summary=_detailed_payload_to_sections(payload.detailed_summary),
                metadata=SummaryMetadata(
                    source_type=ingest.source_type,
                    url=ingest.url,
                    author=ingest.metadata.get("author"),
                    date=None,
                    extraction_confidence=ingest.extraction_confidence,
                    confidence_reason=ingest.confidence_reason,
                    total_tokens_used=0,
                    gemini_pro_tokens=0,
                    gemini_flash_tokens=0,
                    total_latency_ms=0,
                    cod_iterations_used=0,
                    self_check_missing_count=0,
                    patch_applied=False,
                ),
            )

    async def _summarize_inner(self, ingest: IngestResult) -> SummaryResult:
        start = time.perf_counter()
        # Full multi-iteration CoD preserved — quality is non-negotiable.
        dense = await ChainOfDensityDensifier(
            self._client, self._engine_config
        ).densify(ingest)

        # Speculative parallelism: run self-check and the flash structured-
        # extraction concurrently against the CoD output. On the common no-
        # patch path (missing_count < threshold, ~majority of Reddit threads)
        # the speculative extraction is the final answer — we save the whole
        # flash round-trip of user-visible latency. When patching IS needed,
        # we discard the speculative result and re-run extraction against the
        # patched text; quality is identical to the sequential pipeline.
        self_check = InvertedFactScoreSelfCheck(self._client, self._engine_config)
        spec_prompt = STRUCTURED_EXTRACT_INSTRUCTION.format(summary_text=dense.text)
        check, spec_gen = await asyncio.gather(
            self_check.check(ingest.raw_text, dense.text),
            self._client.generate(
                spec_prompt,
                tier="flash",
                response_schema=RedditStructuredPayload,
                system_instruction=SYSTEM_PROMPT,
            ),
        )

        patcher = SummaryPatcher(self._client, self._engine_config)
        needs_patch = check.missing_count >= self._engine_config.self_check.patch_threshold

        pro_tokens = dense.pro_tokens + check.pro_tokens
        flash_tokens = spec_gen.input_tokens + spec_gen.output_tokens

        if needs_patch:
            patched, patch_applied, patch_tokens = await patcher.patch(dense.text, check)
            pro_tokens += patch_tokens
            prompt = STRUCTURED_EXTRACT_INSTRUCTION.format(summary_text=patched)
            gen = await self._client.generate(
                prompt,
                tier="flash",
                response_schema=RedditStructuredPayload,
                system_instruction=SYSTEM_PROMPT,
            )
            flash_tokens += gen.input_tokens + gen.output_tokens
            gen_text = gen.text
        else:
            patched = dense.text
            patch_applied = False
            gen_text = spec_gen.text

        payload = _parse_payload(gen_text, patched, ingest)
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
        sanitized = _sanitize_payload_shape(data) if isinstance(data, dict) else data
        return RedditStructuredPayload(**sanitized)
    except Exception as exc:  # noqa: BLE001 — any drift must fall back, never 500
        _log.warning(
            "reddit.structured_parse_failed type=%s err=%s raw_full=%r",
            type(exc).__name__,
            exc,
            (raw_text or "")[:4096],
        )
        try:
            return _synthesize_fallback_payload(summary_text, ingest)
        except Exception as fb_exc:  # noqa: BLE001
            _log.error(
                "reddit.fallback_synthesis_failed type=%s err=%s",
                type(fb_exc).__name__,
                fb_exc,
                exc_info=True,
            )
            # Last-ditch: build a guaranteed-valid payload bypassing validators.
            # The pipeline MUST never 500 on Reddit — a minimal zettel beats an error.
            return _build_minimum_safe_payload(summary_text, ingest)


def _normalize_keys(obj):
    """Recursively strip stray surrounding quote/whitespace chars from dict keys
    (e.g. ``'"theme"'`` → ``'theme'``) that the flash model occasionally emits
    when it double-escapes JSON."""
    if isinstance(obj, dict):
        return {
            str(k).strip().strip('"').strip("'").strip(): _normalize_keys(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_normalize_keys(v) for v in obj]
    return obj


def _sanitize_payload_shape(data: dict) -> dict:
    """Coerce common LLM drifts in ``detailed_summary.reply_clusters`` into the
    expected list-of-cluster-objects shape before Pydantic validation.

    The flash model occasionally emits a single cluster as a dict with a joined
    key (e.g. ``{"theme, reasoning, examples": "..."}``) or wraps clusters in
    an outer map. Rather than 500, rescue those shapes into a best-effort list
    so the schema can then enforce the contract. Unknown shapes are passed
    through untouched for Pydantic to reject and the ``except`` above to
    catch."""
    data = _normalize_keys(data)
    detailed = data.get("detailed_summary")
    if not isinstance(detailed, dict):
        return data
    clusters = detailed.get("reply_clusters")
    if isinstance(clusters, list):
        repaired: list[dict] = []
        for entry in clusters:
            if isinstance(entry, dict) and {"theme", "reasoning"}.issubset(entry.keys()):
                repaired.append(entry)
                continue
            if isinstance(entry, dict) and len(entry) == 1:
                # {"theme, reasoning, examples": "..."} or similar collapsed key
                only_val = next(iter(entry.values()))
                repaired.append(
                    {"theme": "summary", "reasoning": str(only_val), "examples": []}
                )
                continue
            if isinstance(entry, str):
                repaired.append({"theme": "summary", "reasoning": entry, "examples": []})
                continue
            if isinstance(entry, dict):
                repaired.append(
                    {
                        "theme": str(entry.get("theme") or entry.get("name") or "summary"),
                        "reasoning": str(
                            entry.get("reasoning") or entry.get("description") or ""
                        ),
                        "examples": list(entry.get("examples") or []),
                    }
                )
        detailed["reply_clusters"] = repaired or [
            {"theme": "general discussion", "reasoning": "No discrete clusters detected.", "examples": []}
        ]
    elif isinstance(clusters, dict):
        repaired = []
        for theme_key, body in clusters.items():
            if isinstance(body, dict):
                repaired.append(
                    {
                        "theme": str(body.get("theme") or theme_key),
                        "reasoning": str(body.get("reasoning") or body.get("description") or ""),
                        "examples": list(body.get("examples") or []),
                    }
                )
            else:
                repaired.append({"theme": str(theme_key), "reasoning": str(body), "examples": []})
        detailed["reply_clusters"] = repaired or [
            {"theme": "general discussion", "reasoning": "No discrete clusters detected.", "examples": []}
        ]
    data["detailed_summary"] = detailed
    return data


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


def _build_minimum_safe_payload(
    summary_text: str, ingest: IngestResult
) -> RedditStructuredPayload:
    """Bypass validators and build a minimally-valid payload from ingest metadata.

    Used only when both ``_sanitize_payload_shape`` and
    ``_synthesize_fallback_payload`` have failed. Never raises — the user always
    gets a zettel, even when the LLM drift is catastrophic."""
    subreddit = str(ingest.metadata.get("subreddit") or "reddit").strip() or "reddit"
    title = str(ingest.metadata.get("title") or "thread").strip() or "thread"
    subreddit_tag = f"r-{subreddit.lower().replace('_', '-')}"
    mini_title = f"r/{subreddit} {title}"[:60].rstrip() or f"r/{subreddit} thread"
    brief_sentences = [
        f"OP posted in r/{subreddit} about {title[:120]}.",
        "The thread contained replies that could not be fully clustered by the summarizer.",
        "Consensus stayed around general discussion of the topic.",
        "Dissent was not reliably identified in the visible replies.",
        "Caveat: structured extraction degraded; only minimal metadata is available.",
    ]
    brief = " ".join(brief_sentences)[:400]
    clusters = [
        RedditCluster.model_construct(
            theme="general discussion",
            reasoning=(summary_text or "Replies covered a mix of opinions.")[:500],
            examples=[],
        )
    ]
    detailed = RedditDetailedPayload.model_construct(
        op_intent=(summary_text or f"OP posted in r/{subreddit}.")[:240],
        reply_clusters=clusters,
        counterarguments=[],
        unresolved_questions=[],
        moderation_context=None,
    )
    tags = [
        subreddit_tag,
        "discussion",
        "reddit-thread",
        "community-discussion",
        "user-replies",
        "reddit",
        "thread",
        "capture",
    ]
    return RedditStructuredPayload.model_construct(
        mini_title=mini_title,
        brief_summary=brief,
        tags=tags,
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
