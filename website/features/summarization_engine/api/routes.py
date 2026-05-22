"""FastAPI routes for summarization engine v2."""
from __future__ import annotations

import os
from json import dumps
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from website.api.auth import get_optional_user
from website.api.module_runners.summarization import run_add_zettel_pipeline
from website.features.api_key_switching.key_pool import (
    GeminiKeyPool,
    _load_keys_from_file,
    candidate_api_env_paths,
)
from website.features.summarization_engine.api.models import BatchV2Request, SummarizeV2Request, SummarizeV2Response
from website.features.summarization_engine.batch.processor import BatchProcessor
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.errors import UnsupportedVideoError
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.writers.supabase import SupabaseWriter

router = APIRouter(prefix="/api/v2", tags=["summarization-engine-v2"])


@router.post("/summarize", response_model=SummarizeV2Response)
async def summarize_v2(
    request: SummarizeV2Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    user_id = _user_id(user)
    # Single dedup gate + entitlement + engine + persistence all live in the
    # shared runner so /api/zettels/add and /api/v2/summarize cannot diverge.
    # Anonymous callers map to the Zoro sentinel UUID via _user_id.
    try:
        out = await run_add_zettel_pipeline(
            url=request.url,
            client_action_id=f"v2-summarize-{request.url}",
            persist=request.write_to_supabase,
            user=user if user else {"sub": str(user_id)},
            effective_user_id=user_id,
        )
    except UnsupportedVideoError as exc:
        # H4/T7: preflight hard-fail (private/removed/livestream/premiere/members-only).
        # Distinct from H2's post-chain 422 (metadata_only + <500 chars).
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_video_type",
                "reason": exc.reason,
                "confidence": "insufficient",
                "confidence_reason": f"Video type cannot be ingested: {exc.reason}",
                "quality_signals": {"input_chars": 0, "source_tier": "preflight_refused"},
            },
        )

    quality = out.get("quality") or {}
    conf = quality.get("confidence")
    reason = quality.get("confidence_reason")
    quality_signals = quality.get("quality_signals") or {}
    # H2/C4: two-tier hallucination prevention. Insufficient content + metadata-only
    # tier -> HTTP 422 refusal (mirrors OpenAI structured-outputs refusal pattern).
    if conf == "insufficient":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "insufficient_context",
                "confidence": "insufficient",
                "confidence_reason": reason,
                "quality_signals": quality_signals,
            },
        )

    persistence = out.get("persistence") or {}
    writers: list[dict] = []
    if request.write_to_supabase:
        writers.append(persistence)
    return SummarizeV2Response(
        summary=out.get("summary") or {},
        writers=writers,
        confidence="high" if conf == "high" else "low",
        confidence_reason=reason or None,
        quality_signals=quality_signals,
    )


@router.post("/batch")
async def batch_v2(
    request: BatchV2Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    user_id = _user_id(user)
    writers = [SupabaseWriter()] if request.write_to_supabase else []
    processor = BatchProcessor(user_id=user_id, gemini_client=_gemini_client(), writers=writers)
    payload = {"urls": [{"url": url} for url in request.urls]}
    return await processor.run(input_bytes=dumps(payload).encode(), filename="request.json")


@router.post("/batch/upload")
async def batch_upload_v2(
    file: UploadFile,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    contents = await file.read()
    processor = BatchProcessor(user_id=_user_id(user), gemini_client=_gemini_client())
    return await processor.run(input_bytes=contents, filename=file.filename or "upload.csv")


# ADR-4: the former POST /api/v2/batch/stream returned an EventSourceResponse
# only AFTER the entire batch had already run synchronously — a fake SSE
# facade that delivered zero incremental progress. It was removed rather than
# left misleading. Real incremental batch streaming (async generator backed by
# the running job) is tracked as a separate follow-up. Callers needing batch
# results use POST /api/v2/batch (synchronous) until then.


def _user_id(user: dict | None) -> UUID:
    raw = (user or {}).get("sub") or "00000000-0000-0000-0000-000000000001"
    try:
        return UUID(str(raw))
    except ValueError:
        return UUID("00000000-0000-0000-0000-000000000001")


def _gemini_client() -> TieredGeminiClient:
    keys: list[str | tuple[str, str]] = []
    keys.extend(
        (os.environ[name], "free")
        for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2")
        if os.environ.get(name)
    )
    if os.environ.get("GEMINI_API_KEYS"):
        keys.extend(
            (key.strip(), "free")
            for key in os.environ["GEMINI_API_KEYS"].split(",")
            if key.strip()
        )
    if not keys:
        for path in candidate_api_env_paths():
            loaded = _load_keys_from_file(str(path))
            if loaded:
                keys.extend(loaded)
                break
    if not keys:
        raise HTTPException(status_code=503, detail="Gemini API key not configured")
    return TieredGeminiClient(GeminiKeyPool(keys), load_config())
