"""Gemini AI summarization and multi-dimensional tagging.

Uses the google-genai SDK (NOT the deprecated google-generativeai) to
send extracted content to Gemini and receive structured summaries with
intelligent tags across 6 axes.

Model fallback hierarchy (best → most available):
  gemini-2.5-flash → gemini-2.0-flash → gemini-2.5-flash-lite

If the primary model hits a rate limit (429), the next model in the
chain is tried automatically.  This maximises summary quality while
ensuring the pipeline never fails just because one model's free-tier
quota is exhausted.

Graceful degradation (R022): if ALL models fail, returns raw content
with status=raw so it can still be saved to Obsidian for manual review.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from google import genai
from google.genai import types
from google.genai.errors import ClientError

# How long (seconds) a model stays on cooldown after a 429 response.
_RATE_LIMIT_COOLDOWN_SECS = 60

from telegram_bot.models.capture import ExtractedContent, SourceType

logger = logging.getLogger(__name__)

# Best-first model fallback chain.  Each entry is tried in order;
# on a 429 rate-limit the next model is attempted.
_MODEL_FALLBACK_CHAIN = [
    "gemini-2.5-flash",       # best quality, 20 RPD free tier
    "gemini-2.0-flash",       # strong quality, 1500 RPD free tier
    "gemini-2.5-flash-lite",  # good quality, generous free tier
]


def _is_rate_limited(exc: Exception) -> bool:
    """Return True if *exc* is a Gemini 429 rate-limit error."""
    if isinstance(exc, ClientError) and getattr(exc, "code", None) == 429:
        return True
    return "429" in str(exc) and "RESOURCE_EXHAUSTED" in str(exc)

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

    Tries models in a best-first fallback chain.  If the configured
    model (or the first model in the chain) hits a 429 rate limit, the
    next model is tried automatically.

    Args:
        api_key: Gemini API key.
        model_name: Primary model to try first.
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for summarization")
        self._client = genai.Client(api_key=api_key)
        self._aio_models = self._client.aio.models
        self._model = model_name
        # model → monotonic timestamp when cooldown expires
        self._cooldowns: dict[str, float] = {}

    def _build_model_chain(self) -> list[str]:
        """Return the fallback chain, skipping models on cooldown.

        The configured model is tried first, followed by the remaining
        models in ``_MODEL_FALLBACK_CHAIN``.  Any model whose cooldown
        has not yet expired is omitted.  If *all* models are on cooldown,
        the full chain is returned anyway (better to retry than to fail
        without trying).
        """
        now = time.monotonic()
        # Purge expired cooldowns
        self._cooldowns = {
            m: exp for m, exp in self._cooldowns.items() if exp > now
        }

        full_chain = [self._model]
        for m in _MODEL_FALLBACK_CHAIN:
            if m not in full_chain:
                full_chain.append(m)

        filtered = [m for m in full_chain if m not in self._cooldowns]
        if not filtered:
            # All models on cooldown — try them all anyway
            logger.warning("All models on cooldown — retrying full chain")
            return full_chain
        return filtered

    # ── Low-level generate with fallback ────────────────────────────────

    async def _generate_with_fallback(
        self,
        contents,
        *,
        label: str = "",
    ):
        """Call ``generate_content`` with automatic model fallback on 429.

        Returns ``(response, model_used)`` on success, raises the last
        exception if every model in the chain fails.
        """
        chain = self._build_model_chain()
        last_exc: Exception | None = None

        for model in chain:
            try:
                response = await self._aio_models.generate_content(
                    model=model,
                    contents=contents,
                    config={
                        "system_instruction": _SYSTEM_PROMPT,
                        "temperature": 0.3,
                        "max_output_tokens": 4096,
                    },
                )
                return response, model
            except Exception as exc:
                last_exc = exc
                if _is_rate_limited(exc):
                    self._cooldowns[model] = (
                        time.monotonic() + _RATE_LIMIT_COOLDOWN_SECS
                    )
                    logger.warning(
                        "%s rate-limited on %s — cooldown %ds, trying next model",
                        label or "Gemini", model, _RATE_LIMIT_COOLDOWN_SECS,
                    )
                    continue
                # Non-rate-limit error → don't try other models
                raise

        # All models exhausted
        raise last_exc  # type: ignore[misc]

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
                contents, label="Video understanding",
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
            response, model_used = await self._generate_with_fallback(
                prompt, label="Summarization",
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
