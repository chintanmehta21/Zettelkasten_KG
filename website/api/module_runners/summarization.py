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

from website.core.summary_rendering import render_detailed_summary

if TYPE_CHECKING:
    from website.core.persist import PersistenceOutcome

_SUMMARIZE_SEMAPHORE = asyncio.Semaphore(2)


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
        outcome = await persist_summarized_result(
            summary.model_dump(mode="json"),
            user_sub=user_sub,
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
    )
    from website.features.summarization_engine.summarization import get_summarizer
    from website.features.user_pricing.models import Meter

    ingest = extract_document_upload(
        filename=filename,
        content=content,
        content_type=content_type,
    )
    user_sub = str(effective_user_id)
    await require_entitlement(Meter.ZETTEL, user, action_id=client_action_id)

    config = load_config()
    source_config = config.sources.get(SourceType.DOCUMENT.value, {})
    summarizer_cls = get_summarizer(SourceType.DOCUMENT)
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
        outcome = await persist_summarized_result(payload, user_sub=user_sub)

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
