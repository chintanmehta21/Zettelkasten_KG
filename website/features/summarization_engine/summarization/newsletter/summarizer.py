"""Newsletter per-source summarizer."""
from __future__ import annotations

import re
import time

from website.features.summarization_engine.core.models import SummaryMetadata
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.evaluator.numeric_grounding import (
    extract_numeric_tokens,
    ground_numeric_claims,
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
from website.features.summarization_engine.summarization.common.json_utils import (
    parse_json_object,
)
from website.features.summarization_engine.summarization.common.prompts import (
    SYSTEM_PROMPT,
)
from website.features.summarization_engine.summarization.common.structured import (
    _date_or_none,
    _normalize_tags,
)
from website.features.summarization_engine.summarization.newsletter.prompts import (
    STRUCTURED_EXTRACT_INSTRUCTION,
)
from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterDetailedPayload,
    NewsletterSection,
    NewsletterStructuredPayload,
    NewsletterSummaryResult,
)


class NewsletterSummarizer(BaseSummarizer):
    source_type = SourceType.NEWSLETTER

    def __init__(self, gemini_client: TieredGeminiClient, config):
        super().__init__(gemini_client, config)
        from website.features.summarization_engine.core.config import load_config

        self._engine_config = load_config()

    async def summarize(self, ingest: IngestResult) -> NewsletterSummaryResult:
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
        prompt = STRUCTURED_EXTRACT_INSTRUCTION.format(summary_text=patched)
        result = await self._client.generate(
            prompt,
            tier="flash",
            response_schema=NewsletterStructuredPayload,
            system_instruction=SYSTEM_PROMPT,
        )
        flash_tokens = result.input_tokens + result.output_tokens
        is_schema_fallback = False
        try:
            payload = _parse_payload_with_ingest(result.text, ingest)
            if _payload_contains_template_artifacts(payload):
                repair = await self._client.generate(
                    prompt
                    + "\n\nThe previous output contained metadata-template artifacts "
                    "(such as **ID:**/**Title:** or hash-tag bundles). "
                    "Regenerate clean JSON that follows the schema only.",
                    tier="flash",
                    response_schema=NewsletterStructuredPayload,
                    system_instruction=SYSTEM_PROMPT,
                )
                flash_tokens += repair.input_tokens + repair.output_tokens
                payload = _parse_payload_with_ingest(repair.text, ingest)
                if _payload_contains_template_artifacts(payload):
                    raise ValueError("newsletter payload still contains template artifacts")
        except Exception:
            payload = _fallback_payload(ingest, patched, self._engine_config)
            is_schema_fallback = True
        payload = _apply_ingest_guardrails(payload, ingest)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return NewsletterSummaryResult(
            mini_title=payload.mini_title[
                : self._engine_config.structured_extract.mini_title_max_chars
            ],
            brief_summary=_trim_at_sentence_boundary(
                payload.brief_summary,
                self._engine_config.structured_extract.brief_summary_max_chars,
            ),
            tags=_normalize_tags(
                payload.tags,
                self._engine_config.structured_extract.tags_min,
                self._engine_config.structured_extract.tags_max,
                reserved=_brand_reserved(payload),
            ),
            detailed_summary=payload.detailed_summary,
            metadata=SummaryMetadata(
                source_type=ingest.source_type,
                url=ingest.url,
                author=ingest.metadata.get("author"),
                date=_date_or_none(
                    ingest.metadata.get("published") or ingest.metadata.get("date")
                ),
                extraction_confidence=ingest.extraction_confidence,
                confidence_reason=ingest.confidence_reason,
                total_tokens_used=dense.pro_tokens
                + check.pro_tokens
                + patch_tokens
                + flash_tokens,
                gemini_pro_tokens=dense.pro_tokens + check.pro_tokens + patch_tokens,
                gemini_flash_tokens=flash_tokens,
                total_latency_ms=latency_ms,
                cod_iterations_used=dense.iterations_used,
                self_check_missing_count=check.missing_count,
                patch_applied=patch_applied,
                structured_payload=payload.model_dump(mode="json"),
                is_schema_fallback=is_schema_fallback,
            ),
        )


register_summarizer(NewsletterSummarizer)


def _parse_payload_with_ingest(text: str, ingest: IngestResult) -> NewsletterStructuredPayload:
    raw = parse_json_object(text)
    publication = _publication_identity_hint(ingest)
    if publication:
        raw.setdefault("detailed_summary", {})
        raw["detailed_summary"]["publication_identity"] = publication
        title = str(raw.get("mini_title") or "")
        if publication.lower() not in title.lower():
            raw["mini_title"] = f"{publication}: {title}"
    return NewsletterStructuredPayload(**raw)


def _fallback_payload(ingest: IngestResult, summary_text: str, config) -> NewsletterStructuredPayload:
    title = (
        ingest.sections.get("Title")
        or ingest.metadata.get("title")
        or ingest.metadata.get("publication_identity")
        or "Newsletter issue"
    )
    publication = str(ingest.metadata.get("publication_identity") or "").strip()
    brief = _safe_fallback_brief(ingest, summary_text)
    conclusions_section = ingest.sections.get("Conclusions", "")
    conclusions = [
        line.lstrip("- ").strip()
        for line in conclusions_section.splitlines()
        if line.strip()
    ]
    cta_section = ingest.sections.get("CTAs", "")
    cta = ""
    if cta_section:
        cta = cta_section.splitlines()[0].lstrip("- ").strip()
    if cta and re.match(r"^(subscribe|sign up|sign in)\b", cta.lower()):
        cta = ""
    payload = NewsletterStructuredPayload(
        mini_title=_fallback_title(title=str(title), publication=publication),
        brief_summary=brief,
        tags=["newsletter", "publication", "analysis", "issue", "author", "stance", "cta"],
        detailed_summary=NewsletterDetailedPayload(
            publication_identity=publication,
            issue_thesis=str(title),
            sections=[NewsletterSection(heading="Summary", bullets=[brief])],
            conclusions_or_recommendations=conclusions,
            stance=str(ingest.metadata.get("detected_stance") or "neutral"),
            cta=cta or None,
        ),
    )
    payload.tags = _normalize_tags(
        payload.tags,
        config.structured_extract.tags_min,
        config.structured_extract.tags_max,
        reserved=_brand_reserved(payload),
    )
    return payload


def _safe_fallback_brief(ingest: IngestResult, summary_text: str) -> str:
    base_parts = [
        str(ingest.sections.get("Title") or "").strip(),
        str(ingest.sections.get("Subtitle") or "").strip(),
        str(ingest.sections.get("Preheader") or "").strip(),
    ]
    prose = " ".join(part for part in base_parts if part)
    if not prose:
        prose = " ".join((summary_text or "").split())
    prose = re.sub(r"\*\*[^*]+:\*\*\s*", "", prose)
    prose = re.sub(r"\s*#\w[\w-]*", "", prose)
    prose = prose.strip() or "No summary text was available."
    return _trim_at_sentence_boundary(prose, 380)


def _apply_ingest_guardrails(
    payload: NewsletterStructuredPayload,
    ingest: IngestResult,
) -> NewsletterStructuredPayload:
    publication = _publication_identity_hint(ingest)
    if publication:
        payload.detailed_summary.publication_identity = publication
        if publication.lower() not in payload.mini_title.lower():
            payload.mini_title = f"{publication}: {payload.mini_title}"
    _remove_unsupported_numeric_claims(payload, ingest.raw_text)
    return payload


def _brand_reserved(payload: NewsletterStructuredPayload) -> list[str]:
    """Build the reserved-tag list for a newsletter payload from the
    publication identity. Returns ``[]`` when no publication is set so the
    caller falls back to legacy normalization (no forced reservation)."""
    publication = (payload.detailed_summary.publication_identity or "").strip()
    if not publication:
        return []
    slug = re.sub(r"[^a-z0-9+-]+", "-", publication.lower()).strip("-")
    return [slug] if slug else []


def _publication_identity_hint(ingest: IngestResult) -> str:
    url = ingest.url.lower()
    title = str(ingest.sections.get("Title") or ingest.metadata.get("title") or "")
    if "platformer.news" in url:
        return "Platformer"
    if "product.beehiiv.com" in url:
        return "beehiiv"
    if "organicsynthesis.beehiiv.com" in url or "organic synthesis" in title.lower():
        return "Organic Synthesis"
    if "pragmaticengineer.com" in url:
        return "Pragmatic Engineer"
    if "beehiiv.com" in url:
        return "beehiiv"
    return str(ingest.metadata.get("publication_identity") or "").strip()


# Newsletter uses the stricter (all-integer) bare-integer mode so small
# fabricated counts like "42 teams" are also flagged as unsupported. The
# evaluator default (3-digit minimum) is deliberately looser to avoid
# flagging incidental small counts in cross-source scoring.
_NL_MIN_BARE_INT_DIGITS = 1


def _remove_unsupported_numeric_claims(
    payload: NewsletterStructuredPayload,
    source_text: str,
) -> None:
    """Strip any numeric claim in the structured payload that is not
    grounded in ``source_text``. Delegates token extraction / grounding
    to the shared evaluator module so production stripping and
    post-hoc grounding scoring cannot drift apart.

    Behavior contract (preserved from the pre-delegation implementation):
      - No-op when ``source_text`` is empty / whitespace-only.
      - brief_summary: drop each sentence that contains any ungrounded
        token; fall back to the original brief if every sentence gets
        dropped (never return an empty brief).
      - section.bullets: drop ungrounded bullets; if that empties the
        section, keep one number-free bullet as a placeholder.
      - conclusions_or_recommendations: drop any item with an
        ungrounded token.
    """
    if not source_text.strip():
        return

    payload.brief_summary = _filter_unsupported_number_sentences(
        payload.brief_summary, source_text
    )
    for section in payload.detailed_summary.sections:
        filtered = [
            bullet
            for bullet in section.bullets
            if not _has_unsupported_number(bullet, source_text)
        ]
        if filtered:
            section.bullets = filtered
        else:
            number_free = [
                bullet
                for bullet in section.bullets
                if not extract_numeric_tokens(
                    bullet, min_bare_integer_digits=_NL_MIN_BARE_INT_DIGITS
                )
            ]
            section.bullets = number_free[:1]
    payload.detailed_summary.conclusions_or_recommendations = [
        item
        for item in payload.detailed_summary.conclusions_or_recommendations
        if not _has_unsupported_number(item, source_text)
    ]


def _filter_unsupported_number_sentences(text: str, source_text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    kept = [
        sentence
        for sentence in sentences
        if sentence and not _has_unsupported_number(sentence, source_text)
    ]
    return " ".join(kept) or text


def _has_unsupported_number(text: str, source_text: str) -> bool:
    _, ungrounded = ground_numeric_claims(
        text, source_text, min_bare_integer_digits=_NL_MIN_BARE_INT_DIGITS
    )
    return bool(ungrounded)


def _payload_contains_template_artifacts(payload: NewsletterStructuredPayload) -> bool:
    snippets = [payload.mini_title, payload.brief_summary]
    snippets.extend(section.heading for section in payload.detailed_summary.sections)
    for section in payload.detailed_summary.sections:
        snippets.extend(section.bullets)
    joined = " ".join(snippets).lower()
    return bool(
        "**id:**" in joined
        or "**title:**" in joined
        or "**tags:**" in joined
        or "#substack" in joined
    )


def _trim_at_sentence_boundary(text: str, max_chars: int) -> str:
    """Trim public brief text without cutting through words or sentences."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned

    candidate = cleaned[:max_chars].rstrip()
    matches = list(re.finditer(r"[.!?](?=\s|$)", candidate))
    if matches:
        last = matches[-1].end()
        if last >= max_chars * 0.55:
            return candidate[:last].strip()

    boundary = candidate.rfind(" ")
    if boundary >= max_chars * 0.55:
        return candidate[:boundary].rstrip(" ,;:")
    return candidate.rstrip(" ,;:")


def _fallback_title(*, title: str, publication: str) -> str:
    title = title.strip() or "Newsletter issue"
    publication = publication.strip()
    if publication and publication.lower() not in title.lower():
        return f"{publication}: {title}"[:60]
    return title[:60]
