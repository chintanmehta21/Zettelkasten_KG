"""Gemini AI summarization and multi-dimensional tagging.

Uses the google-genai SDK (NOT the deprecated google-generativeai) to
send extracted content to Gemini 2.5 Flash and receive structured
summaries with intelligent tags across 6 axes.

Graceful degradation (R022): if Gemini fails, returns raw content with
status=raw so it can still be saved to Obsidian for manual review.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from google import genai

from zettelkasten_bot.models.capture import ExtractedContent, ProcessedNote, SourceType

logger = logging.getLogger(__name__)

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
  "summary": "Structured summary with markdown bullet points grouped by topic. Use ## headings for major sections, then bullet points with sub-bullets.",
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
    tags: dict[str, list[str]] = field(default_factory=dict)
    one_line_summary: str = ""
    tokens_used: int = 0
    latency_ms: int = 0
    is_raw_fallback: bool = False


class GeminiSummarizer:
    """Summarize and tag content using Google Gemini.

    Args:
        api_key: Gemini API key.
        model_name: Model to use (default: gemini-2.5-flash).
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for summarization")
        self._client = genai.Client(api_key=api_key)
        self._aio_models = self._client.aio.models
        self._model = model_name

    async def summarize(self, content: ExtractedContent) -> SummarizationResult:
        """Summarize extracted content via Gemini.

        On failure, returns a raw fallback result (R022) so the content
        is preserved even if summarization fails.
        """
        prompt = _USER_PROMPT_TEMPLATE.format(
            source_type=content.source_type.value,
            title=content.title,
            url=content.url,
            body=content.body[:15000],  # Cap input to avoid token limits
        )

        start = time.monotonic()
        try:
            response = await self._aio_models.generate_content(
                model=self._model,
                contents=prompt,
                config={
                    "system_instruction": _SYSTEM_PROMPT,
                    "temperature": 0.3,
                    "max_output_tokens": 4096,
                },
            )

            latency_ms = int((time.monotonic() - start) * 1000)
            raw_text = response.text or ""
            if not raw_text.strip():
                raise ValueError("Gemini returned empty response (possible safety block)")

            # Parse token usage from response
            tokens_used = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                tokens_used = getattr(response.usage_metadata, "total_token_count", 0)

            logger.info(
                "Gemini response for %s: %d tokens, %dms",
                content.url,
                tokens_used,
                latency_ms,
            )

            # Parse JSON response
            result = self._parse_response(raw_text)
            result.tokens_used = tokens_used
            result.latency_ms = latency_ms
            return result

        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "Gemini summarization failed for %s after %dms: %s",
                content.url,
                latency_ms,
                exc,
            )
            # Graceful degradation (R022): return raw content
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
            return SummarizationResult(
                summary=data.get("summary", raw_text),
                tags=data.get("tags", {}),
                one_line_summary=data.get("one_line_summary", ""),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to parse Gemini JSON response: %s", exc)
            # Fall back to using raw text as summary
            return SummarizationResult(
                summary=raw_text,
                tags={},
                one_line_summary="",
            )


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
    for domain in ai_tags.get("domain", []):
        tags.append(f"domain/{domain}")

    # Axis 3: Type
    for content_type in ai_tags.get("type", []):
        tags.append(f"type/{content_type}")

    # Axis 4: Difficulty
    for diff in ai_tags.get("difficulty", []):
        tags.append(f"difficulty/{diff}")

    # Axis 5: Status (set programmatically, not by AI)
    tags.append("status/Processed")

    # Axis 6: Keywords
    for kw in ai_tags.get("keywords", []):
        tags.append(f"keyword/{kw}")

    return tags
