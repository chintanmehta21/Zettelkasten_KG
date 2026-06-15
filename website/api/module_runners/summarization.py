"""Runner for the website Add Zettel summarization pipeline.

This module is intentionally importable from both FastAPI routes and CLI tools.
It is the API-facing runner that boots the summarization engine, normalizes the
engine output into the website DTO, and then calls canonical persistence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from website.core.persist import PersistenceOutcome

from website.core.request_context import operation_context
from website.core.summary_rendering import render_detailed_summary

if TYPE_CHECKING:
    from website.core.persist import PersistenceOutcome

_SUMMARIZE_SEMAPHORE = asyncio.Semaphore(2)

# Bound per-document vision cost/latency: ~258 tokens/page. 30 pages ≈ 7.7k
# vision tokens — safe for the latency budget and quota.
MAX_VISION_RECOVERY_PAGES = 30


async def _recover_document_text_via_vision(*, content, client, page_count):
    """Recover a verbatim transcript from a no-text/garbage PDF via Gemini vision.

    Sends the PDF bytes inline to ``generate_multimodal`` and returns the
    stripped transcript. Raises ``NoTextLayerError`` when the document exceeds
    ``MAX_VISION_RECOVERY_PAGES`` so the caller surfaces the no-text redirect UX.
    """
    from website.features.summarization_engine.source_ingest.document import NoTextLayerError
    if page_count > MAX_VISION_RECOVERY_PAGES:
        raise NoTextLayerError(
            f"Document has {page_count} pages; too many to read by vision.",
            page_count=page_count,
        )
    from google.genai import types as gtypes
    prompt = (
        "Transcribe ALL readable text from this document verbatim, preserving "
        "reading order and headings. Output only the transcript text — no "
        "commentary. If a page is blank, skip it."
    )
    contents = [
        gtypes.Content(role="user", parts=[
            gtypes.Part(inline_data=gtypes.Blob(mime_type="application/pdf", data=content)),
            gtypes.Part(text=prompt),
        ])
    ]
    result = await client.generate_multimodal(contents, label="document_vision_recovery")
    return (getattr(result, "text", "") or "").strip()


class SummaryDTO(BaseModel):
    title: str
    summary: str
    brief_summary: str
    detailed_summary: str
    tags: list[str]
    source_type: str
    source_url: str
    one_line_summary: str
    tokens_used: int
    latency_ms: int
    metadata: dict[str, Any]
    # P1-7(b): the pre-summary extracted source text (article/transcript/body),
    # carried so persist's _stable_content_hash can key the canonical dedup
    # hash on actual source content, not LLM wording. Optional with a safe
    # default so existing callers/tests constructing SummaryDTO are unaffected;
    # consumed only by _stable_content_hash and stripped before the row is
    # written, so it never widens the persisted DTO or any other consumer.
    # exclude=True: this is an internal dedup-only signal — it MUST NOT
    # serialize into AddZettelResponse (model_dump / model_dump_json), or
    # /api/zettels/add and /api/operations/{id} would leak the full extracted
    # body to every client. The Add Zettel pipeline threads it into the
    # persist payload explicitly (see run_add_zettel), so dedup is unaffected.
    source_fingerprint_text: str | None = Field(default=None, exclude=True)


class PersistenceDTO(BaseModel):
    requested: bool
    persisted: bool
    file_store: bool
    supabase: bool
    duplicate: bool


class QualityDTO(BaseModel):
    confidence: str
    confidence_reason: str | None = None
    quality_signals: dict[str, Any] = Field(default_factory=dict)


class AddZettelPipelineOutput(BaseModel):
    status: Literal["succeeded", "accepted", "failed"]
    operation_id: str
    summary: SummaryDTO | None = None
    persistence: PersistenceDTO
    quality: QualityDTO
    node_id: str | None = None
    workspace_zettel_id: str | None = None
    status_url: str | None = None
    # Additive (P2): structured problem-detail payload for failures that crossed
    # the 20s universal-202 fast-ack boundary. Mirrors the sync route's
    # _problem(...) body keys (type/title/status/detail [+ extras]) so the
    # frontend's `err.detail.code === 'quota_exhausted'` classifier resolves
    # identically whether the failure happened inline or in the background
    # task. None for success/accepted/cancelled/generic-exception paths.
    error: dict[str, Any] | None = None


GeminiClientFactory = Callable[[], Any]


def default_gemini_client() -> Any:
    from website.features.summarization_engine.core.client_factory import (
        build_tiered_gemini_client,
    )

    return build_tiered_gemini_client()


async def require_entitlement(*args: Any, **kwargs: Any) -> Any:
    from website.features.user_pricing.entitlements import require_entitlement as _impl

    return await _impl(*args, **kwargs)


async def consume_entitlement(*args: Any, **kwargs: Any) -> Any:
    from website.features.user_pricing.entitlements import consume_entitlement as _impl

    return await _impl(*args, **kwargs)


async def summarize_url_bundle(*args: Any, **kwargs: Any) -> Any:
    from website.features.summarization_engine.core.orchestrator import (
        summarize_url_bundle as _impl,
    )

    return await _impl(*args, **kwargs)


async def persist_summarized_result(*args: Any, **kwargs: Any) -> Any:
    from website.core.persist import persist_summarized_result as _impl

    return await _impl(*args, **kwargs)


async def resolve_redirects(*args: Any, **kwargs: Any) -> Any:
    from website.core.url_utils import resolve_redirects as _impl

    return await _impl(*args, **kwargs)


def normalize_url(*args: Any, **kwargs: Any) -> Any:
    from website.core.url_utils import normalize_url as _impl

    return _impl(*args, **kwargs)


async def run_add_zettel_pipeline(
    *,
    url: str,
    client_action_id: str,
    persist: bool,
    user: dict | None,
    effective_user_id: UUID,
    gemini_client_factory: GeminiClientFactory = default_gemini_client,
) -> dict[str, Any]:
    """Run Add Zettel end-to-end for API and CLI callers."""

    from website.features.user_pricing.models import Meter

    user_sub = str(effective_user_id)
    resolved = await resolve_redirects(url)
    normalized = normalize_url(resolved)

    from website.core.persist import get_supabase_v2_scope
    from website.features.functional_gates import get_url_dedup_gate
    from website.core.supabase_v2.models import WorkspaceZettelCreate

    _scope = get_supabase_v2_scope(user_sub)
    if _scope is not None:
        repo, _profile_id, workspace_id = _scope
        decision = get_url_dedup_gate().decide(
            repo=repo, normalized_url=normalized, workspace_id=workspace_id,
        )
        if decision.branch == "same_user_noop":
            return _cache_hit_output(decision.found, client_action_id, persist)
        if decision.branch == "cross_user_hit":
            await require_entitlement(Meter.ZETTEL, user, action_id=client_action_id)
            repo.link_existing_canonical(
                decision.found.canonical_zettel_id,
                WorkspaceZettelCreate(
                    workspace_id=workspace_id,
                    ai_summary=decision.found.ai_summary,
                    ai_summary_engine_version=decision.found.ai_summary_engine_version,
                    user_tags=decision.found.user_tags,
                    added_via="website",
                ),
            )
            return _cache_hit_output(decision.found, client_action_id, persist)

    await require_entitlement(Meter.ZETTEL, user, action_id=client_action_id)
    # Bind the operation id so ingest / dense-verify / persist log lines deep
    # in the engine can be correlated to this one Add-Zettel operation.
    with operation_context(client_action_id):
        async with _SUMMARIZE_SEMAPHORE:
            bundle = await summarize_url_bundle(
                normalized,
                user_id=effective_user_id,
                gemini_client=gemini_client_factory(),
            )

        summary = summary_dto(bundle)
        quality = quality_dto(bundle)
        outcome: PersistenceOutcome | None = None
        if persist:
            # asyncio.shield protects the persist write from a mid-flight cancel
            # of the parent _run task. Without this, a DELETE /api/zettels/
            # operations/{id} (or a worker SIGTERM) could inject CancelledError
            # between the canonical_zettel insert and the workspace_zettel /
            # canonical_chunks inserts -> partial write / orphan rows. Per the
            # 2026-05-21 incident review.
            payload = summary.model_dump(mode="json")
            # source_fingerprint_text is exclude=True on SummaryDTO (kept out of
            # the public response). Re-thread it so persist's _stable_content_hash
            # keys the (normalized_url, content_hash) dedup off deterministic
            # source text instead of URL-only — parity with the document path.
            payload["source_fingerprint_text"] = summary.source_fingerprint_text
            outcome = await asyncio.shield(
                persist_summarized_result(payload, user_sub=user_sub)
            )
            # Phase 9: gate consumed atomically in require_entitlement above.

    return AddZettelPipelineOutput(
        status="succeeded",
        operation_id=client_action_id,
        summary=summary,
        persistence=persistence_dto(persist, outcome),
        quality=quality,
        node_id=outcome.file_node_id if outcome else None,
        workspace_zettel_id=outcome.supabase_node_id if outcome else None,
    ).model_dump(mode="json")


async def run_add_document_pipeline(
    *,
    filename: str,
    content: bytes,
    content_type: str | None,
    client_action_id: str,
    persist: bool,
    user: dict | None,
    effective_user_id: UUID,
    gemini_client_factory: GeminiClientFactory = default_gemini_client,
) -> dict[str, Any]:
    """Run Add Zettel end-to-end for an uploaded document."""

    from website.features.summarization_engine.core.budget import budget_scope
    from website.features.summarization_engine.core.config import load_config
    from website.features.summarization_engine.core.models import SourceType
    from website.features.summarization_engine.core.orchestrator import OrchestratedSummary
    from website.features.summarization_engine.source_ingest.document import (
        extract_document_upload,
        NoTextLayerError,
        GarbageTextError,
    )
    from website.features.summarization_engine.summarization import get_summarizer
    from website.features.user_pricing.models import Meter

    try:
        ingest = extract_document_upload(
            filename=filename,
            content=content,
            content_type=content_type,
        )
    except (NoTextLayerError, GarbageTextError) as exc:
        # No-text/garbage PDF: one-shot Gemini vision transcript, re-entered as
        # .txt (suffix load-bearing — .pdf would re-parse). <50ch/over-ceiling=terminal.
        client = gemini_client_factory()
        recovered = await _recover_document_text_via_vision(
            content=content, client=client, page_count=getattr(exc, "page_count", 0),
        )
        if len(recovered) < 50:
            raise
        ingest = extract_document_upload(
            filename=Path(filename).stem + ".txt",
            content=recovered.encode("utf-8"),
            content_type="text/plain",
        )
    user_sub = str(effective_user_id)
    await require_entitlement(Meter.ZETTEL, user, action_id=client_action_id)

    config = load_config()
    source_config = config.sources.get(SourceType.DOCUMENT.value, {})
    summarizer_cls = get_summarizer(SourceType.DOCUMENT)
    with operation_context(client_action_id):
        async with _SUMMARIZE_SEMAPHORE:
            summarizer = summarizer_cls(gemini_client_factory(), source_config)
            async with budget_scope(summarizer=SourceType.DOCUMENT.value):
                summary_result = await summarizer.summarize(ingest)

        bundle = OrchestratedSummary(ingest_result=ingest, summary_result=summary_result)
        summary = summary_dto(bundle)
        quality = quality_dto(bundle)
        outcome: PersistenceOutcome | None = None
        if persist:
            payload = summary.model_dump(mode="json")
            payload["raw_text"] = ingest.raw_text
            # source_fingerprint_text is exclude=True on SummaryDTO (kept out of
            # the public response), so re-thread it here for the dedup hash.
            payload["source_fingerprint_text"] = summary.source_fingerprint_text
            # asyncio.shield: parity with run_add_zettel_pipeline — protect the
            # persist write from a mid-flight cancel (matters once the document
            # path moves onto the async-ops worker).
            outcome = await asyncio.shield(
                persist_summarized_result(payload, user_sub=user_sub)
            )

    return AddZettelPipelineOutput(
        status="succeeded",
        operation_id=client_action_id,
        summary=summary,
        persistence=persistence_dto(persist, outcome),
        quality=quality,
        node_id=outcome.file_node_id if outcome else None,
        workspace_zettel_id=outcome.supabase_node_id if outcome else None,
    ).model_dump(mode="json")


def summary_dto(bundle: Any) -> SummaryDTO:
    result = bundle.summary_result
    ingest = bundle.ingest_result
    metadata = result.metadata.model_dump(mode="json", exclude_none=True)
    detailed = render_detailed_summary(result.detailed_summary) or result.brief_summary
    summary = SummaryDTO(
        title=result.mini_title,
        summary=detailed,
        brief_summary=result.brief_summary,
        detailed_summary=detailed,
        tags=list(result.tags or []),
        source_type=result.metadata.source_type.value,
        source_url=result.metadata.url,
        one_line_summary=result.brief_summary,
        tokens_used=result.metadata.total_tokens_used,
        latency_ms=result.metadata.total_latency_ms,
        metadata=metadata,
        # IngestResult.raw_text is the deterministic pre-summary extracted
        # source (set by the source ingestor before Gemini); None when ingest
        # produced nothing, so persist's hash safely falls back to URL-only.
        source_fingerprint_text=(
            (ingest.raw_text or None) if ingest is not None else None
        ),
    )
    if ingest is not None:
        summary.metadata.setdefault("raw_metadata", dict(ingest.metadata or {}))
    return summary


def quality_dto(bundle: Any) -> QualityDTO:
    from website.features.summarization_engine.core.confidence import grade as grade_confidence

    ingest = bundle.ingest_result
    source_tier = str((ingest.metadata or {}).get("tier_used") or "")
    raw_text_len = len(ingest.raw_text or "")
    confidence, reason = grade_confidence(
        raw_text_len=raw_text_len,
        source_tier=source_tier,
    )
    return QualityDTO(
        confidence=confidence,
        confidence_reason=reason,
        quality_signals={"input_chars": raw_text_len, "source_tier": source_tier},
    )


def _cache_hit_output(found, client_action_id: str, persist: bool) -> dict[str, Any]:
    """Same wire shape as a fresh add, rebuilt from the existing canonical's
    stored summary. No 'cached' indicator (no-infra-disclosure)."""
    from website.core.persist import extract_summary_parts
    brief, detailed = extract_summary_parts(found.ai_summary, None)
    summary = SummaryDTO(
        title=found.title or "",
        summary=detailed or brief,
        brief_summary=brief,
        detailed_summary=detailed or brief,
        tags=list(found.user_tags),
        source_type=found.source_type,
        source_url="",
        one_line_summary=brief,
        tokens_used=0,
        latency_ms=0,
        metadata={},
    )
    return AddZettelPipelineOutput(
        status="succeeded",
        operation_id=client_action_id,
        summary=summary,
        persistence=persistence_dto(persist, None),
        quality=QualityDTO(confidence="succeeded"),
        node_id=None,
        workspace_zettel_id=str(found.canonical_zettel_id),
    ).model_dump(mode="json")


def persistence_dto(requested: bool, outcome: Any | None) -> PersistenceDTO:
    if not requested or outcome is None:
        return PersistenceDTO(
            requested=requested,
            persisted=False,
            file_store=False,
            supabase=False,
            duplicate=False,
        )
    return PersistenceDTO(
        requested=True,
        persisted=outcome.file_saved or outcome.supabase_saved or outcome.supabase_duplicate,
        file_store=outcome.file_saved,
        supabase=outcome.supabase_saved,
        duplicate=outcome.supabase_duplicate,
    )


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if key.strip() and key.strip() not in {"", "#"}:
            os.environ.setdefault(key.strip(), value)


def _load_api_env_file(path: Path) -> None:
    if not path.exists() or os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY"):
        return
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            _, line = line.split("=", 1)
        value = line.strip().strip('"').strip("'")
        if value:
            keys.append(value)
    if keys:
        os.environ.setdefault("GEMINI_API_KEYS", ",".join(keys))


def _load_local_env() -> None:
    root = Path.cwd()
    for candidate in (
        root / ".env",
        root / ".env.v2",
        root / "supabase" / ".env",
    ):
        _load_env_file(candidate)
    _load_api_env_file(root / "api_env")
    os.environ.setdefault("DB_SCHEMA_VERSION", "v2")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Add Zettel summarization engine facade from CLI.",
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--user-id", required=True, help="Supabase Auth UUID to write under")
    parser.add_argument("--client-action-id", default="cli-add-zettel")
    parser.add_argument("--persist", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--load-env", action="store_true", help="Load .env/.env.v2/supabase/.env first")
    return parser.parse_args()


async def _cli() -> int:
    args = _parse_args()
    if args.load_env:
        _load_local_env()
    result = await run_add_zettel_pipeline(
        url=args.url,
        client_action_id=args.client_action_id,
        persist=args.persist,
        user={"sub": args.user_id},
        effective_user_id=UUID(str(args.user_id)),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_cli()))
