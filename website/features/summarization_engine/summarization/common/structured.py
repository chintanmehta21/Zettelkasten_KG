"""Structured extraction phase.

Routes payload_class-specific schemas end-to-end: the prompt is built from the
payload class's JSON schema so Gemini emits source-shaped output that matches
`response_schema` exactly. Source-specific rich fields are preserved in
`metadata.structured_payload`; the `detailed_summary` list surface is
back-filled from the rich payload so downstream SummaryResult consumers stay
compatible.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from pydantic import BaseModel

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    IngestResult,
    SummaryMetadata,
    SummaryResult,
)
from website.features.summarization_engine.summarization.common.json_utils import parse_json_object
from website.features.summarization_engine.summarization.common.prompts import SYSTEM_PROMPT, source_context

_log = logging.getLogger(__name__)


class StructuredSummaryPayload(BaseModel):
    mini_title: str
    brief_summary: str
    tags: list[str]
    detailed_summary: list[DetailedSummarySection]


class StructuredExtractor:
    def __init__(
        self,
        client: TieredGeminiClient,
        config: EngineConfig,
        payload_class: type[BaseModel] = StructuredSummaryPayload,
    ):
        self._client = client
        self._config = config
        self._payload_class = payload_class

    def _schema_snippet(self) -> str:
        """Compact JSON-schema hint included in the prompt.

        Gemini honors `response_schema` most reliably when the prompt ALSO
        describes the shape it should emit. A bare prompt that contradicts
        `response_schema` produces confused output and pydantic fallbacks.
        """
        schema = self._payload_class.model_json_schema()
        return json.dumps(schema, separators=(",", ":"))[:3000]

    async def extract(
        self,
        ingest: IngestResult,
        summary_text: str,
        *,
        pro_tokens: int,
        flash_tokens: int,
        latency_ms: int,
        cod_iterations_used: int,
        self_check_missing_count: int,
        patch_applied: bool,
    ) -> SummaryResult:
        schema_json = self._schema_snippet()
        prompt = (
            f"{source_context(ingest.source_type)}\n\n"
            f"Return a JSON object that EXACTLY matches the following JSON schema "
            f"for class {self._payload_class.__name__}. Populate every required field "
            f"from the SUMMARY below — do not invent facts. Use temperature 0 judgment.\n\n"
            f"SCHEMA:\n{schema_json}\n\n"
            "Do NOT wrap in markdown code blocks. Return raw JSON only.\n\n"
            f"SUMMARY:\n{summary_text}"
        )
        result = await self._client.generate(
            prompt,
            tier="flash",
            response_schema=self._payload_class,
            system_instruction=SYSTEM_PROMPT,
        )
        flash_tokens += result.input_tokens + result.output_tokens

        is_fallback = False
        structured_payload: dict | None = None
        try:
            raw = parse_json_object(result.text)
            payload = self._payload_class(**raw)
            structured_payload = payload.model_dump(mode="json")
        except Exception as exc:
            _log.warning(
                "structured.extract schema_fallback payload_class=%s err=%s preview=%s",
                self._payload_class.__name__,
                type(exc).__name__,
                (result.text or "")[:160].replace("\n", " "),
            )
            payload = _fallback_payload(ingest, summary_text, self._config)
            is_fallback = True
            structured_payload = None

        detailed_list = _coerce_detailed_summary(payload)
        tags = _normalize_tags(
            getattr(payload, "tags", []) or [],
            self._config.structured_extract.tags_min,
            self._config.structured_extract.tags_max,
            allow_boilerplate_pad=is_fallback,
            source_type_value=ingest.source_type.value,
        )

        return SummaryResult(
            mini_title=str(getattr(payload, "mini_title", ""))[:60],
            brief_summary=str(getattr(payload, "brief_summary", ""))[:400],
            tags=tags,
            detailed_summary=detailed_list,
            metadata=SummaryMetadata(
                source_type=ingest.source_type,
                url=ingest.url,
                author=ingest.metadata.get("author"),
                date=_date_or_none(ingest.metadata.get("published") or ingest.metadata.get("date")),
                extraction_confidence=ingest.extraction_confidence,
                confidence_reason=ingest.confidence_reason,
                total_tokens_used=pro_tokens + flash_tokens,
                gemini_pro_tokens=pro_tokens,
                gemini_flash_tokens=flash_tokens,
                total_latency_ms=latency_ms,
                cod_iterations_used=cod_iterations_used,
                self_check_missing_count=self_check_missing_count,
                patch_applied=patch_applied,
                structured_payload=structured_payload,
                is_schema_fallback=is_fallback,
            ),
        )


def _coerce_detailed_summary(payload: BaseModel) -> list[DetailedSummarySection]:
    """Convert a source-specific or generic detailed_summary into a list of sections."""
    raw = getattr(payload, "detailed_summary", None)
    if raw is None:
        return [DetailedSummarySection(heading="Summary", bullets=[""])]

    if isinstance(raw, list):
        out: list[DetailedSummarySection] = []
        for item in raw:
            if isinstance(item, DetailedSummarySection):
                out.append(item)
            elif isinstance(item, BaseModel):
                data = item.model_dump(mode="json")
                heading = str(data.get("heading") or data.get("title") or data.get("timestamp") or "Section")
                bullets = data.get("bullets") or []
                if not bullets:
                    bullets = [f"{k}: {v}" for k, v in data.items() if k not in {"heading", "bullets", "sub_sections"} and v]
                bullets = [str(b) for b in bullets if b]
                if not bullets:
                    bullets = [heading]
                out.append(DetailedSummarySection(heading=heading, bullets=bullets, sub_sections=data.get("sub_sections") or {}))
            elif isinstance(item, dict):
                heading = str(item.get("heading") or item.get("title") or "Section")
                bullets = [str(b) for b in (item.get("bullets") or []) if b]
                if not bullets:
                    bullets = [heading]
                out.append(DetailedSummarySection(heading=heading, bullets=bullets, sub_sections=item.get("sub_sections") or {}))
        return out or [DetailedSummarySection(heading="Summary", bullets=["(empty)"])]

    if isinstance(raw, BaseModel):
        data = raw.model_dump(mode="json")
        sections: list[DetailedSummarySection] = []
        for key, value in data.items():
            if value is None or value == [] or value == {}:
                continue
            if isinstance(value, str):
                sections.append(DetailedSummarySection(heading=key, bullets=[value]))
            elif isinstance(value, list):
                bullets: list[str] = []
                for item in value:
                    if isinstance(item, dict):
                        bullets.append(json.dumps(item, ensure_ascii=False))
                    else:
                        bullets.append(str(item))
                if bullets:
                    sections.append(DetailedSummarySection(heading=key, bullets=bullets))
            elif isinstance(value, dict):
                sections.append(
                    DetailedSummarySection(
                        heading=key,
                        bullets=[json.dumps(value, ensure_ascii=False)],
                    )
                )
            else:
                sections.append(DetailedSummarySection(heading=key, bullets=[str(value)]))
        return sections or [DetailedSummarySection(heading="Summary", bullets=["(empty)"])]

    return [DetailedSummarySection(heading="Summary", bullets=[str(raw)])]


def _fallback_payload(ingest: IngestResult, summary_text: str, config: EngineConfig) -> StructuredSummaryPayload:
    """Explicit schema-fallback marker. Never silently pads with boilerplate tags.

    The `_schema_fallback_` tag is intentional: downstream gates / eval loop
    detect this and treat the iteration as a routing bug, not a real summary.
    """
    title = ingest.metadata.get("title") or ingest.metadata.get("full_name") or "Captured source"
    words = summary_text.split()
    brief = " ".join(words[:50]) or "No summary text was available."
    return StructuredSummaryPayload(
        mini_title=str(title)[: config.structured_extract.mini_title_max_chars],
        brief_summary=brief,
        tags=["_schema_fallback_"],
        detailed_summary=[
            DetailedSummarySection(
                heading="schema_fallback",
                bullets=[
                    "structured extractor fell back; see metadata.is_schema_fallback",
                    brief,
                ],
            )
        ],
    )


_BOILERPLATE_TAGS = frozenset({"zettelkasten", "summary", "capture", "research", "source", "notes", "ai", "knowledge"})


def _normalize_tags(
    tags: list[str],
    tags_min: int,
    tags_max: int,
    *,
    allow_boilerplate_pad: bool = False,
    source_type_value: str | None = None,
) -> list[str]:
    """Normalize tags. Does NOT pad with boilerplate unless explicitly allowed
    (schema-fallback path only). Boilerplate tags ('zettelkasten', 'summary',
    'capture', ...) are masking real routing bugs when they appear on a
    supposedly-successful summary.
    """
    normalized: list[str] = []
    for tag in tags:
        cleaned = str(tag).strip().lower().replace(" ", "-")
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    if allow_boilerplate_pad and source_type_value:
        for fallback in (source_type_value, *_BOILERPLATE_TAGS):
            if len(normalized) >= tags_min:
                break
            if fallback not in normalized:
                normalized.append(fallback)
    return normalized[:tags_max]


def _date_or_none(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
