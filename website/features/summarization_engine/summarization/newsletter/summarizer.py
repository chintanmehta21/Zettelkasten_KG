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
            payload = NewsletterStructuredPayload(**parse_json_object(result.text))
        except Exception:
            payload = _fallback_payload(ingest, patched, self._engine_config)
            is_schema_fallback = True
        latency_ms = int((time.perf_counter() - start) * 1000)
        return NewsletterSummaryResult(
            mini_title=payload.mini_title[:60],
            brief_summary=_trim_at_sentence_boundary(
                payload.brief_summary,
                self._engine_config.structured_extract.brief_summary_max_chars,
            ),
            tags=_normalize_tags(
                payload.tags,
                self._engine_config.structured_extract.tags_min,
                self._engine_config.structured_extract.tags_max,
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


def _fallback_payload(ingest: IngestResult, summary_text: str, config) -> NewsletterStructuredPayload:
    title = (
        ingest.sections.get("Title")
        or ingest.metadata.get("title")
        or ingest.metadata.get("publication_identity")
        or "Newsletter issue"
    )
    publication = str(ingest.metadata.get("publication_identity") or "").strip()
    brief = " ".join(summary_text.split()[:60]) or "No summary text was available."
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
    )
    return payload


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
