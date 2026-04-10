"""FastAPI routes for summarization engine v2."""
from __future__ import annotations

import os
from json import dumps
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sse_starlette.sse import EventSourceResponse

from website.api.auth import get_optional_user
from website.features.api_key_switching.key_pool import GeminiKeyPool
from website.features.summarization_engine.api.models import BatchV2Request, SummarizeV2Request, SummarizeV2Response
from website.features.summarization_engine.batch.processor import BatchProcessor, progress_stream
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.orchestrator import summarize_url
from website.features.summarization_engine.writers.supabase import SupabaseWriter

router = APIRouter(prefix="/api/v2", tags=["summarization-engine-v2"])


@router.post("/summarize", response_model=SummarizeV2Response)
async def summarize_v2(
    request: SummarizeV2Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    user_id = _user_id(user)
    client = _gemini_client()
    result = await summarize_url(request.url, user_id=user_id, gemini_client=client)
    writers = []
    if request.write_to_supabase:
        writers.append(await SupabaseWriter().write(result, user_id=user_id))
    return SummarizeV2Response(summary=result.model_dump(mode="json"), writers=writers)


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


@router.post("/batch/stream")
async def batch_stream_v2(
    request: BatchV2Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    result = await batch_v2(request, user)
    return EventSourceResponse(progress_stream(result))


def _user_id(user: dict | None) -> UUID:
    raw = (user or {}).get("sub") or "00000000-0000-0000-0000-000000000001"
    try:
        return UUID(str(raw))
    except ValueError:
        return UUID("00000000-0000-0000-0000-000000000001")


def _gemini_client() -> TieredGeminiClient:
    keys = [os.environ[name] for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2") if os.environ.get(name)]
    if os.environ.get("GEMINI_API_KEYS"):
        keys.extend(key.strip() for key in os.environ["GEMINI_API_KEYS"].split(",") if key.strip())
    if not keys and os.path.exists("api_env"):
        keys = [line.strip() for line in open("api_env", encoding="utf-8") if line.strip() and not line.startswith("#")]
    if not keys:
        raise HTTPException(status_code=503, detail="Gemini API key not configured")
    return TieredGeminiClient(GeminiKeyPool(keys), load_config())
