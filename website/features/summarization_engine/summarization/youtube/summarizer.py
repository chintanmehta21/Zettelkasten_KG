"""YouTube per-source summarizer."""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Mapping

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
    _normalize_tags,
)
from website.features.summarization_engine.summarization.youtube.format_classifier import (
    classify_format,
)
from website.features.summarization_engine.summarization.youtube.prompts import (
    select_youtube_prompt,
)
from website.features.summarization_engine.summarization.youtube.schema import (
    YouTubeStructuredPayload,
)

_log = logging.getLogger(__name__)


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

        meta = ingest.metadata or {}
        chapters_meta = meta.get("chapters") or []
        chapter_titles: list[str] = []
        for chapter in chapters_meta:
            if isinstance(chapter, dict):
                title = chapter.get("title") or chapter.get("name")
                if isinstance(title, str):
                    chapter_titles.append(title)
            elif isinstance(chapter, str):
                chapter_titles.append(chapter)
        speakers_meta = meta.get("speakers") or []
        speakers = [s for s in speakers_meta if isinstance(s, str)]
        format_label, format_confidence = classify_format(
            title=str(meta.get("title") or ""),
            description=str(meta.get("description") or ingest.raw_text or ""),
            chapter_titles=chapter_titles,
            speakers=speakers,
        )
        _log.info(
            "youtube.summarizer format=%s confidence=%.3f",
            format_label,
            format_confidence,
        )

        structured = StructuredExtractor(
            self._client,
            self._engine_config,
            payload_class=YouTubeStructuredPayload,
            prompt_instruction=select_youtube_prompt(format_label),
        )

        dense = await densifier.densify(ingest)
        check = await self_checker.check(ingest.raw_text, dense.text)
        patched_text, patch_applied, patch_tokens = await patcher.patch(
            dense.text, check
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        result = await structured.extract(
            ingest,
            patched_text,
            pro_tokens=dense.pro_tokens + check.pro_tokens + patch_tokens,
            flash_tokens=0,
            latency_ms=latency_ms,
            cod_iterations_used=dense.iterations_used,
            self_check_missing_count=check.missing_count,
            patch_applied=patch_applied,
        )
        # Plumb the channel-slug / format reserved-tag set through the
        # cross-source tag-normalization pipeline. The schema-layer
        # ``model_validator`` cannot see ``ingest.metadata`` (channel lives
        # there, not in the payload), so we re-normalize the already-cleaned
        # tags here with ``reserved=`` to guarantee ``yt-<channel-slug>``
        # survives truncation. Backward compat: when neither channel nor
        # format is present, ``_yt_reserved`` returns ``[]`` and the call is
        # byte-identical to today's behavior.
        structured_payload_dict = (
            result.metadata.structured_payload
            if result.metadata is not None
            else None
        )
        reserved = _yt_reserved(
            payload=structured_payload_dict,
            ingest_metadata=meta,
        )
        if reserved:
            result.tags = _normalize_tags(
                result.tags,
                self._engine_config.structured_extract.tags_min,
                self._engine_config.structured_extract.tags_max,
                reserved=reserved,
            )
        # Stash format verdict in metadata so eval/debug can see routing
        # decisions made by the format classifier (mirrors GitHub archetype).
        if result.metadata is not None:
            extras = dict(result.metadata.structured_payload or {}) if result.metadata.structured_payload else {}
            extras.setdefault("_youtube_format", {
                "format": format_label,
                "confidence": round(float(format_confidence), 3),
            })
            result.metadata.structured_payload = extras
        return result


register_summarizer(YouTubeSummarizer)


_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SLUG_DASH_RUN = re.compile(r"-+")


def _slugify_channel(value: str) -> str:
    """Lowercase + ASCII-dash slug for YouTube channel names.

    Rules: lowercase, replace whitespace and any non-``[a-z0-9]`` characters
    with ``-``, collapse repeated dashes, strip edge dashes. Returns ``""``
    when the input collapses to nothing (e.g. non-ASCII-only channel names),
    which lets the caller drop the slug rather than emit a bare ``yt-``.
    """
    if not value:
        return ""
    lowered = value.lower()
    dashed = _SLUG_NON_ALNUM.sub("-", lowered)
    collapsed = _SLUG_DASH_RUN.sub("-", dashed)
    return collapsed.strip("-")


def _yt_reserved(
    payload: Mapping[str, Any] | None,
    ingest_metadata: Mapping[str, Any] | None,
) -> list[str]:
    """Build the cross-source reserved-tag list for a YouTube summary.

    Returns ``["yt-<channel-slug>", "<format>"]`` when both signals are
    present; emits whichever subset is available, in that order; and returns
    ``[]`` when neither is available so legacy callers stay byte-identical
    to today.

    ``payload`` is the already-validated structured payload dict (the
    ``model_dump`` output of :class:`YouTubeStructuredPayload`). The format
    label lives at ``payload["detailed_summary"]["format"]`` after the
    schema-layer ``_normalize_format_name`` runs. ``ingest_metadata`` is
    ``ingest.metadata`` and exposes the channel name under any of the
    standard YouTube ingest keys.
    """
    out: list[str] = []
    meta = ingest_metadata or {}
    channel_raw = (
        meta.get("channel")
        or meta.get("uploader")
        or meta.get("channel_name")
        or meta.get("author")
        or ""
    )
    if isinstance(channel_raw, str):
        slug = _slugify_channel(channel_raw)
        if slug:
            out.append(f"yt-{slug}")

    format_label = ""
    if isinstance(payload, Mapping):
        detailed = payload.get("detailed_summary")
        if isinstance(detailed, Mapping):
            raw_format = detailed.get("format")
            if isinstance(raw_format, str):
                format_label = raw_format.strip().lower()
    if format_label:
        out.append(format_label)

    return out
