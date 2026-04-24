"""YouTube per-source summarizer (3-call DenseVerify pipeline).

Call budget (<=3 per zettel):
  1. DenseVerifier (pro) — dense + verify + format classification signal.
  2. StructuredExtractor (flash) — schema-shaped payload, guided by DV's
     ``missing_facts`` via ``missing_facts_hint``.
  3. Optional flash patch — only when the structured brief still omits a
     DV-flagged fact (pragmatic substring probe).
"""
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
from website.features.summarization_engine.summarization.common.dense_verify_runner import (
    maybe_patch_structured_brief,
    run_dense_verify,
)
from website.features.summarization_engine.summarization.common.model_trace import (
    aggregate_fallback_reason,
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

        # Call 1 — DenseVerify (pro). If the ingest already carried a dense
        # video-understanding transcript (metadata flag), we still run DV to
        # gather missing_facts / format_label; the "dense" half is cheap
        # because the content is already dense. Pre-computed dense is not
        # currently surfaced from the ingestor; the hook is retained for the
        # tiers.py "gemini_audio" path to wire in without schema churn.
        precomputed_dense = None
        if isinstance(meta.get("dense_text"), str) and meta.get("dense_text"):
            precomputed_dense = str(meta["dense_text"])
        dv = await run_dense_verify(
            client=self._client,
            ingest=ingest,
            precomputed_dense=precomputed_dense,
        )

        # Seed the call trace with the DV entry. DV carries its model_used /
        # fallback_reason from dense_verify.run() -> TieredGeminiClient so a
        # silent pro->flash-lite downgrade is visible in summary.json without
        # scraping run.log. Cache-hit DVs contribute a synthetic entry with
        # model=None — caller sees "no new Gemini call" instead of missing DV.
        call_trace: list[dict[str, Any]] = [{
            "role": "dense_verify",
            "model": dv.model_used,
            "starting_model": dv.starting_model,
            "fallback_reason": dv.fallback_reason,
        }]

        structured = StructuredExtractor(
            self._client,
            self._engine_config,
            payload_class=YouTubeStructuredPayload,
            prompt_instruction=select_youtube_prompt(format_label),
            missing_facts_hint=list(dv.missing_facts),
        )

        latency_ms = int((time.perf_counter() - start) * 1000)

        # Call 2 — structured extraction (flash). Any internal schema-retry
        # loops inside StructuredExtractor stay bounded by its own
        # validation_retries config; the budget test asserts <=3 total.
        result = await structured.extract(
            ingest,
            dv.dense_text or ingest.raw_text or "",
            pro_tokens=0,  # DV pro tokens are attributed downstream if needed
            flash_tokens=0,
            latency_ms=latency_ms,
            cod_iterations_used=0,
            self_check_missing_count=len(dv.missing_facts),
            patch_applied=False,
            telemetry_sink=call_trace,
        )

        # Call 3 (optional) — flash patch when DV-flagged facts remain omitted
        # from the structured payload. A no-op when DV had no missing_facts.
        payload_json = ""
        if result.metadata is not None and result.metadata.structured_payload:
            try:
                import json as _json

                payload_json = _json.dumps(result.metadata.structured_payload)
            except Exception:  # noqa: BLE001
                payload_json = str(result.metadata.structured_payload)
        new_brief, patch_applied, patch_tokens = await maybe_patch_structured_brief(
            client=self._client,
            current_brief=result.brief_summary,
            dv=dv,
            extracted_payload_json=payload_json,
            telemetry_sink=call_trace,
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

        # Positive-evidence speaker detection. Runs on transcript + title +
        # uploader (all already in hand — no new API call). If the detector
        # confirms ≥1 real speaker from ≥2 independent signals, override the
        # LLM-proposed speaker list. Prevents "Strait of Hormuz"-class
        # hallucinations from surviving even when the model echoes a
        # prominent phrase from the transcript.
        try:
            from website.features.summarization_engine.summarization.common.speaker_detector import (
                detect_youtube_speakers,
            )
            detected = detect_youtube_speakers(
                title=str(getattr(meta, "title", "") or meta.get("title") if isinstance(meta, dict) else "") if meta else "",
                uploader=(
                    str(getattr(meta, "uploader", "") or meta.get("uploader") if isinstance(meta, dict) else "")
                    if meta else ""
                ),
                transcript=str(ingest.raw_text or ""),
            )
            if detected and detected != ["The speaker"]:
                if result.metadata is not None and result.metadata.structured_payload:
                    sp = dict(result.metadata.structured_payload)
                    sp["speakers"] = detected
                    result.metadata.structured_payload = sp
        except Exception as exc:  # noqa: BLE001
            _log.debug("speaker_detector failed (non-fatal): %s", exc)

        # Cross-source reserved-tag normalization (channel slug + format).
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
            # DV-reported format hint is informational; format_classifier is
            # authoritative because it folds chapter/speaker signals the LLM
            # cannot see from raw_text alone.
            if dv.format_label:
                extras.setdefault("_dense_verify", {
                    "format_label": dv.format_label,
                    "missing_fact_count": len(dv.missing_facts),
                })
            result.metadata.structured_payload = extras
            # Surface the call trace + aggregate fallback reason so eval
            # tooling can detect silent pro->flash-lite downgrades without
            # scraping run.log.
            result.metadata.model_used = call_trace
            result.metadata.fallback_reason = aggregate_fallback_reason(call_trace)
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
