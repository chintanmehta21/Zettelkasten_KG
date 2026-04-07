"""Gemini AI summarization and multi-dimensional tagging.

Delegates to the centralized GeminiKeyPool for key rotation and model
fallback.  The pool handles all 429 rate-limit retries and key switching.

Graceful degradation (R022): if ALL models/keys fail, returns raw content
with status=raw so it can still be saved to Obsidian for manual review.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from google.genai import types

from telegram_bot.models.capture import ExtractedContent, SourceType
from website.features.api_key_switching import get_key_pool
from website.features.api_key_switching.routing import select_starting_model

logger = logging.getLogger(__name__)
_DEFAULT_SUMMARIZATION_MODEL = "gemini-2.5-flash"

# ── Prompt template ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a knowledge management assistant. Your job is to analyze content and produce:
1. A structured summary organized by topic/section
2. Multi-dimensional tags for a Zettelkasten knowledge graph

RULES:
- Preserve technical precision, specific metrics, names, claims, code snippets
- Flag unverified or speculative claims with [unverified]
- Keep the source's original perspective and nuance
- Group bullet points by section/topic hierarchy with sub-bullets for details
- Be concise but don't lose important details
"""

_USER_PROMPT_TEMPLATE = """\
Analyze this {source_type} content and produce a structured response.

TITLE: {title}
URL: {url}

CONTENT:
{body}

Respond with ONLY a JSON object (no markdown fences) with these fields:
{{
  "brief_summary": "Concise bullet-point summary under 200 words. Use bullet points (• ) to capture only the key takeaways. No headings, no sub-bullets.",
  "detailed_summary": "Comprehensive structured summary with markdown ## headings for major sections, then bullet points with sub-bullets for details. Capture ALL major points — do not omit important information.",
  "tags": {{
    "domain": ["list of domain tags like AI, ML, Finance, Security, WebDev, etc."],
    "type": ["content type: Tutorial, Research, Opinion, News, Discussion, Tool, Reference"],
    "difficulty": ["one of: Beginner, Intermediate, Advanced"],
    "keywords": ["3-7 specific keywords from the content"]
  }},
  "one_line_summary": "A single sentence capturing the key takeaway"
}}
"""


@dataclass
class SummarizationResult:
    """Result from the Gemini summarization pipeline."""

    summary: str
    brief_summary: str = ""
    tags: dict[str, list[str]] = field(default_factory=dict)
    one_line_summary: str = ""
    tokens_used: int = 0
    latency_ms: int = 0
    is_raw_fallback: bool = False


class GeminiSummarizer:
    """Summarize and tag content using Google Gemini.

    Delegates to the centralized GeminiKeyPool for key rotation,
    model fallback, and rate-limit handling.

    Args:
        api_key: Deprecated — keys are managed by GeminiKeyPool.
        model_name: Primary model to try first.
    """

    def __init__(self, api_key: str = "", model_name: str = _DEFAULT_SUMMARIZATION_MODEL) -> None:
        if api_key:
            logger.debug("api_key parameter is deprecated — keys are managed by GeminiKeyPool")
        self._pool = get_key_pool()
        self._model = model_name

    # ── Low-level generate with fallback ────────────────────────────────

    async def _generate_with_fallback(
        self,
        contents,
        *,
        starting_model: str | None = None,
        config: dict | None = None,
        label: str = "",
    ):
        """Call generate_content via the key pool with automatic fallback.

        Returns (response, model_used) on success, raises on total failure.
        """
        if config is None:
            config = {
                "system_instruction": _SYSTEM_PROMPT,
                "temperature": 0.3,
                "max_output_tokens": 4096,
            }
        response, model_used, _key_idx = await self._pool.generate_content(
            contents,
            config=config,
            starting_model=starting_model or self._model,
            label=label,
        )
        return response, model_used

    # ── YouTube video understanding ─────────────────────────────────────

    def _is_youtube_without_transcript(self, content: ExtractedContent) -> bool:
        """Check if this is a YouTube video where transcript extraction failed."""
        return (
            content.source_type == SourceType.YOUTUBE
            and not content.metadata.get("has_transcript", True)
        )

    async def _summarize_youtube_video(self, content: ExtractedContent) -> SummarizationResult | None:
        """Summarize a YouTube video using Gemini's video understanding.

        Passes the YouTube URL directly to Gemini as a video reference.
        Google's servers can access YouTube (no IP blocking), so this
        bypasses the cloud-IP blocking that kills youtube-transcript-api
        and yt-dlp on services like Render, AWS, GCP.
        """
        video_id = content.metadata.get("video_id", "")
        watch_url = f"https://www.youtube.com/watch?v={video_id}"

        prompt = _USER_PROMPT_TEMPLATE.format(
            source_type="youtube",
            title=content.title,
            url=content.url,
            body="(Video content — analyze from the video directly)",
        )

        contents = [
            types.Part.from_uri(file_uri=watch_url, mime_type="video/mp4"),
            prompt,
        ]

        start = time.monotonic()
        try:
            response, model_used = await self._generate_with_fallback(
                contents,
                starting_model=(
                    self._model
                    if self._model and self._model != _DEFAULT_SUMMARIZATION_MODEL
                    else _DEFAULT_SUMMARIZATION_MODEL
                ),
                label="Video understanding",
            )

            latency_ms = int((time.monotonic() - start) * 1000)
            raw_text = response.text or ""
            if not raw_text.strip():
                raise ValueError("Gemini returned empty response for YouTube video")

            tokens_used = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                tokens_used = getattr(response.usage_metadata, "total_token_count", 0)

            logger.info(
                "Gemini video understanding (%s) for %s: %d tokens, %dms",
                model_used, watch_url, tokens_used, latency_ms,
            )

            result = self._parse_response(raw_text)
            result.tokens_used = tokens_used
            result.latency_ms = latency_ms
            return result

        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "Gemini video understanding failed for %s after %dms: %s",
                watch_url, latency_ms, exc,
            )
            return None

    # ── Main summarize entry point ──────────────────────────────────────

    async def summarize(self, content: ExtractedContent) -> SummarizationResult:
        """Summarize extracted content via Gemini.

        For YouTube videos without transcripts (cloud IP blocking),
        uses Gemini's video understanding to analyze the video directly.

        Models are tried best-first; on 429 rate-limit the next model
        in the chain is attempted automatically.

        On failure, returns a raw fallback result (R022) so the content
        is preserved even if summarization fails.
        """
        # YouTube without transcript: try Gemini video understanding first
        if self._is_youtube_without_transcript(content):
            logger.info("YouTube video without transcript — trying Gemini video understanding")
            video_result = await self._summarize_youtube_video(content)
            if video_result is not None:
                return video_result
            logger.warning("Gemini video understanding failed — falling back to text summarization")

        prompt = _USER_PROMPT_TEMPLATE.format(
            source_type=content.source_type.value,
            title=content.title,
            url=content.url,
            body=content.body[:15000],
        )

        start = time.monotonic()
        try:
            if self._model and self._model != _DEFAULT_SUMMARIZATION_MODEL:
                starting_model = self._model
            else:
                starting_model = select_starting_model(
                    content_length=len(content.body),
                    source_type=content.source_type.value,
                )
            response, model_used = await self._generate_with_fallback(
                prompt,
                starting_model=starting_model,
                label="Summarization",
            )

            latency_ms = int((time.monotonic() - start) * 1000)
            raw_text = response.text or ""
            if not raw_text.strip():
                raise ValueError("Gemini returned empty response (possible safety block)")

            tokens_used = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                tokens_used = getattr(response.usage_metadata, "total_token_count", 0)

            logger.info(
                "Gemini response (%s) for %s: %d tokens, %dms",
                model_used, content.url, tokens_used, latency_ms,
            )

            result = self._parse_response(raw_text)
            result.tokens_used = tokens_used
            result.latency_ms = latency_ms
            return result

        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "Gemini summarization failed for %s after %dms: %s",
                content.url, latency_ms, exc,
            )
            return SummarizationResult(
                summary=content.body[:5000],
                tags={},
                one_line_summary="(Summarization failed — raw content preserved)",
                tokens_used=0,
                latency_ms=latency_ms,
                is_raw_fallback=True,
            )

    def _parse_response(self, raw_text: str) -> SummarizationResult:
        """Parse Gemini's JSON response into a SummarizationResult."""
        # Strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = text.index("\n") if "\n" in text else len(text)
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            data = json.loads(text)
            # Support both new dual-summary and legacy single-summary format
            detailed = data.get("detailed_summary")
            if detailed is None:
                detailed = data.get("summary", raw_text)
            brief = data.get("brief_summary", "")
            return SummarizationResult(
                summary=detailed,
                brief_summary=brief,
                tags=data.get("tags", {}),
                one_line_summary=data.get("one_line_summary", ""),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to parse Gemini JSON response: %s", exc)
            # Fall back to using raw text as summary
            return SummarizationResult(
                summary=raw_text,
                brief_summary="",
                tags={},
                one_line_summary="",
            )


def _ensure_list(value) -> list[str]:
    """Normalize a tag value to a list of strings.

    Gemini sometimes returns a bare string instead of a list for single-value
    fields (e.g. ``"difficulty": "Intermediate"``).  Iterating over a string
    yields individual characters, so we wrap it first.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    return []


def build_tag_list(
    source_type: SourceType,
    ai_tags: dict[str, list[str]],
) -> list[str]:
    """Build the full multi-dimensional tag list (R009).

    Combines the auto-detected source tag with AI-generated tags across
    6 axes: source, domain, type, difficulty, status, keywords.

    Returns tags in hierarchical format: ``source/reddit``, ``domain/AI``, etc.
    """
    tags: list[str] = []

    # Axis 1: Source (auto-detected, not from AI)
    tags.append(f"source/{source_type.value}")

    # Axis 2: Domain
    for domain in _ensure_list(ai_tags.get("domain", [])):
        tags.append(f"domain/{domain}")

    # Axis 3: Type
    for content_type in _ensure_list(ai_tags.get("type", [])):
        tags.append(f"type/{content_type}")

    # Axis 4: Difficulty
    for diff in _ensure_list(ai_tags.get("difficulty", [])):
        tags.append(f"difficulty/{diff}")

    # Axis 5: Status (set programmatically, not by AI)
    tags.append("status/Processed")

    # Axis 6: Keywords
    for kw in _ensure_list(ai_tags.get("keywords", [])):
        tags.append(f"keyword/{kw}")

    return tags
