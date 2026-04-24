"""Default summarizer (3-call DenseVerify pipeline).

Call budget (<=3 per zettel):
  1. DenseVerifier (pro) — dense + verify.
  2. StructuredExtractor (flash) — schema-shaped payload, guided by DV's
     ``missing_facts`` via ``missing_facts_hint``.
  3. Optional flash patch — only when the structured brief still omits a
     DV-flagged fact (pragmatic substring probe).

Registered once per polish-phase source (HN/LinkedIn/Arxiv/Podcast/Twitter/Web)
so auto-discovery finds a summarizer for every :class:`SourceType` without a
dedicated per-source implementation.
"""
from __future__ import annotations

import json as _json
import time

from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import IngestResult, SourceType, SummaryResult
from website.features.summarization_engine.summarization import register_summarizer
from website.features.summarization_engine.summarization.base import BaseSummarizer
from website.features.summarization_engine.summarization.common.dense_verify_runner import (
    maybe_patch_structured_brief,
    run_dense_verify,
)
from website.features.summarization_engine.summarization.common.structured import StructuredExtractor


class DefaultSummarizer(BaseSummarizer):
    """Run DenseVerify, structured extraction, and optional flash patch."""

    source_type = SourceType.WEB

    def __init__(self, gemini_client: TieredGeminiClient, config):
        super().__init__(gemini_client, config)
        from website.features.summarization_engine.core.config import load_config

        self._engine_config = load_config()

    async def summarize(self, ingest: IngestResult) -> SummaryResult:
        start = time.perf_counter()

        # Call 1 — DenseVerify (pro). Produces dense_text + missing_facts for
        # the downstream extractor to absorb.
        dv = await run_dense_verify(client=self._client, ingest=ingest)

        structured = StructuredExtractor(
            self._client,
            self._engine_config,
            missing_facts_hint=list(dv.missing_facts),
        )

        latency_ms = int((time.perf_counter() - start) * 1000)

        # Call 2 — structured extraction (flash).
        result = await structured.extract(
            ingest,
            dv.dense_text or ingest.raw_text or "",
            pro_tokens=0,
            flash_tokens=0,
            latency_ms=latency_ms,
            cod_iterations_used=0,
            self_check_missing_count=len(dv.missing_facts),
            patch_applied=False,
        )

        # Call 3 (optional) — flash patch when DV-flagged facts remain omitted
        # from the structured payload.
        payload_json = ""
        if result.metadata is not None and result.metadata.structured_payload:
            try:
                payload_json = _json.dumps(result.metadata.structured_payload)
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

        return result


# Register one DefaultSummarizer subclass per polish-phase source so
# auto-discovery finds a summarizer for every SourceType not covered by a
# dedicated source-specific implementation.
for _st in (
    SourceType.HACKERNEWS,
    SourceType.LINKEDIN,
    SourceType.ARXIV,
    SourceType.PODCAST,
    SourceType.TWITTER,
    SourceType.WEB,
):
    _cls = type(
        f"{_st.value.title()}DefaultSummarizer",
        (DefaultSummarizer,),
        {"source_type": _st, "__module__": __name__},
    )
    register_summarizer(_cls)
