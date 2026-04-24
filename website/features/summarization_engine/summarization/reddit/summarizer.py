"""Reddit per-source summarizer (3-call DenseVerify pipeline).

Call budget (<=3 per zettel):
  1. DenseVerifier (pro) — dense + verify, yields ``missing_facts`` for patch
     detection. Runs CONCURRENTLY with the structured extract below so the
     user-visible latency is max(DV, structured) rather than DV+structured.
  2. StructuredExtractor (flash) — schema-shaped Reddit payload.
  3. Optional flash patch — only when the structured brief still omits a
     DV-flagged fact (pragmatic substring probe in the helper).

Rationale for preserving ``asyncio.gather``: Reddit's CoD phase was the
latency bottleneck in iter-09. DenseVerifier keeps a pro call, but by
speculatively running the structured-extract flash concurrently we keep
the happy-path user latency at max(pro, flash) instead of pro+flash.
Quality is preserved because the patch helper catches any DV-flagged
fact that the structured payload dropped.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy

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
from website.features.summarization_engine.summarization.common.dense_verify_runner import (
    maybe_patch_structured_brief,
    run_dense_verify,
)
from website.features.summarization_engine.summarization.common.json_utils import (
    parse_json_object,
)
from website.features.summarization_engine.summarization.common.structured import (
    StructuredExtractor,
    _normalize_tags,
)
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)

_log = logging.getLogger(__name__)


class RedditSummarizer(BaseSummarizer):
    """Reddit summarizer on the 3-call DenseVerify pipeline.

    Contract preserved from iter-09:
    - label format ``r/<subreddit> ...`` via schema validator.
    - 8-10 tags reserving subreddit + thread_type slots.
    - Rich detailed payload (op_intent, reply_clusters, counterarguments,
      unresolved_questions, moderation_context) preserved in
      ``metadata`` as the source of truth.
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
                mini_title=payload.mini_title[
                    : self._engine_config.structured_extract.mini_title_max_chars
                ],
                brief_summary=payload.brief_summary[
                    : self._engine_config.structured_extract.brief_summary_max_chars
                ],
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
                    structured_payload=payload.model_dump(mode="json"),
                ),
            )

    async def _summarize_inner(self, ingest: IngestResult) -> SummaryResult:
        start = time.perf_counter()

        # Calls 1 + 2 in parallel — DenseVerify (pro) races with the
        # structured extract (flash). The structured call can't see DV's
        # ``missing_facts`` on the speculative path, but the optional patch
        # (call 3) covers any DV-flagged fact the payload dropped.
        extractor = StructuredExtractor(
            self._client,
            self._engine_config,
            payload_class=RedditStructuredPayload,
            missing_facts_hint=None,
        )

        dv_task = asyncio.create_task(
            run_dense_verify(client=self._client, ingest=ingest)
        )
        extract_task = asyncio.create_task(
            extractor.extract(
                ingest,
                ingest.raw_text or "",
                pro_tokens=0,
                flash_tokens=0,
                latency_ms=0,
                cod_iterations_used=0,
                self_check_missing_count=0,
                patch_applied=False,
            )
        )
        dv, result = await asyncio.gather(dv_task, extract_task)

        # Ingest-time enrichments (subreddit tag + moderation context note)
        # replicate the iter-09 behavior — they inject signals the LLM can't
        # see from the summary alone. Applied on top of StructuredExtractor's
        # output.
        structured_payload_dict = (
            result.metadata.structured_payload if result.metadata is not None else None
        )
        if isinstance(structured_payload_dict, dict):
            try:
                validated = RedditStructuredPayload.model_validate(
                    structured_payload_dict
                )
                enriched = _apply_ingest_enrichments(validated, ingest)
                if result.metadata is not None:
                    result.metadata.structured_payload = enriched.model_dump(mode="json")
                    # Propagate enriched tags back to the user-visible surface.
                    result.tags = _normalize_tags(
                        enriched.tags,
                        self._engine_config.structured_extract.tags_min,
                        self._engine_config.structured_extract.tags_max,
                    )
                    # Refresh detailed_summary bullets from the enriched payload
                    # so moderation_context surfaces on the rendered note.
                    result.detailed_summary = _detailed_payload_to_sections(
                        enriched.detailed_summary
                    )
            except Exception as exc:  # noqa: BLE001 — enrichment must never 500
                _log.info(
                    "reddit.enrichment_skipped type=%s err=%s",
                    type(exc).__name__,
                    exc,
                )

        # Call 3 (optional) — flash patch when DV-flagged facts remain omitted.
        payload_json = ""
        if result.metadata is not None and result.metadata.structured_payload:
            try:
                payload_json = json.dumps(result.metadata.structured_payload)
            except Exception:  # noqa: BLE001
                payload_json = str(result.metadata.structured_payload)
        new_brief, patch_applied, patch_tokens = await maybe_patch_structured_brief(
            client=self._client,
            current_brief=result.brief_summary,
            dv=dv,
            extracted_payload_json=payload_json,
        )
        if patch_applied:
            result.brief_summary = new_brief
            if result.metadata is not None:
                result.metadata.patch_applied = True
                result.metadata.gemini_flash_tokens = (
                    int(result.metadata.gemini_flash_tokens or 0) + patch_tokens
                )
                result.metadata.total_tokens_used = (
                    int(result.metadata.total_tokens_used or 0) + patch_tokens
                )

        # Annotate DV's self_check_missing_count for downstream eval.
        if result.metadata is not None:
            result.metadata.self_check_missing_count = len(dv.missing_facts)
            result.metadata.total_latency_ms = int((time.perf_counter() - start) * 1000)

        return result


register_summarizer(RedditSummarizer)


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


def _build_minimum_safe_payload(
    summary_text: str, ingest: IngestResult
) -> RedditStructuredPayload:
    """Bypass validators and build a minimally-valid payload from ingest metadata.

    Used only when the summarizer hits an unrecoverable exception. Never
    raises — the user always gets a zettel, even when the LLM drift is
    catastrophic."""
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
