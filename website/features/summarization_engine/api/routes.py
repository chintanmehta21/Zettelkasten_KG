"""FastAPI routes for summarization engine v2."""
from __future__ import annotations

import hashlib
import os
from json import dumps
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from website.api._problem import _problem_dict
from website.api.auth import get_optional_user
from website.features.api_key_switching.key_pool import (
    GeminiKeyPool,
    _load_keys_from_file,
    candidate_api_env_paths,
)
from website.features.summarization_engine.api.models import BatchV2Request, SummarizeV2Request
from website.features.summarization_engine.batch.processor import BatchProcessor
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.writers.supabase import SupabaseWriter

router = APIRouter(prefix="/api/v2", tags=["summarization-engine-v2"])

# Size cap on /batch/upload — parity with /api/zettels/add/document. Prior
# behavior was unbounded ``file.read()`` which would OOM the 2 GB droplet on
# a single large POST. App-level guard pairs with Caddy edge enforcement at
# ops/caddy/Caddyfile (request_body max_size). Both layers must agree.
_MAX_BATCH_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/summarize")
async def summarize_v2(
    request: SummarizeV2Request,
    fastapi_request: Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    """Summarize a URL — async-ops (ADR-3).

    Returns ``202 Accepted`` + ``status_url``; the client polls
    ``GET /api/operations/{id}`` for the terminal ``AddZettelResponse``. This
    unifies /api/v2/summarize with /api/zettels/add onto the one durable
    long-running-operation contract — the previous synchronous path was
    timeout-prone for slow YouTube/PDF sources. Anonymous callers map to the
    Zoro sentinel UUID. Refusals (unsupported video, insufficient context)
    surface as a terminal ``failed`` operation with a structured ``error``.
    """
    # Function-level import: the async-ops machinery lives in the website
    # zettels router; importing at module load would risk a cycle.
    from website.api.zettels_routes import (
        AddZettelRequest,
        _accept_and_spawn,
        _compute_auth_intent,
        _run_add_zettel,
    )

    user_id = _user_id(user)
    # operation_id must be UNIQUE per call AND URL-safe. It is the
    # (user_id, operation_id) PK in core.operations and is interpolated into
    # status_url (/api/operations/{id}). A deterministic per-URL id collided
    # on the PK for every repeat URL (raw 23505 -> ADR-2 fail-closed 503).
    # uuid4 hex is collision-free and URL-safe; idempotency for concurrent
    # duplicate requests is enforced separately by request_hash in ops_accept.
    operation_id = f"v2-summarize-{uuid4().hex}"
    request_hash = hashlib.sha256(
        dumps(
            {"url": request.url, "persist": request.write_to_supabase},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    body = AddZettelRequest(
        url=request.url,
        client_action_id=operation_id,
        persist=request.write_to_supabase,
        surface="landing",
    )
    user_payload = user if user else {"sub": str(user_id)}
    return await _accept_and_spawn(
        user_id=user_id,
        operation_id=operation_id,
        request_hash=request_hash,
        persist=request.write_to_supabase,
        pipeline=lambda: _run_add_zettel(
            body, user=user_payload, effective_user_id=user_id
        ),
        auth_intent=_compute_auth_intent(fastapi_request, user),
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
    # Read one byte past the cap so we can distinguish "exactly N" from
    # "more than N" without buffering attacker-controlled gigabytes.
    contents = await file.read(_MAX_BATCH_UPLOAD_BYTES + 1)
    if len(contents) > _MAX_BATCH_UPLOAD_BYTES:
        body = _problem_dict(
            status_code=413,
            title="Batch upload too large",
            detail=f"Upload a file up to {_MAX_BATCH_UPLOAD_BYTES // (1024 * 1024)} MB.",
            type_slug="batch-upload-too-large",
            instance="/api/v2/batch/upload",
        )
        return JSONResponse(
            body, status_code=413, media_type="application/problem+json"
        )
    processor = BatchProcessor(user_id=_user_id(user), gemini_client=_gemini_client())
    return await processor.run(input_bytes=contents, filename=file.filename or "upload.csv")


# ADR-4: the former POST /api/v2/batch/stream returned an EventSourceResponse
# only AFTER the entire batch had already run synchronously — a fake SSE
# facade that delivered zero incremental progress. It was removed rather than
# left misleading. Real incremental batch streaming (async generator backed by
# the running job) is tracked as a separate follow-up. Callers needing batch
# results use POST /api/v2/batch (synchronous) until then.


def _user_id(user: dict | None) -> UUID:
    raw = (user or {}).get("sub")
    if raw:
        try:
            return UUID(str(raw))
        except ValueError:
            pass
    # Anonymous / unparseable sub → canonical Zoro user (a real seeded
    # profile), shared with /api/zettels/add. A fake sentinel UUID has no
    # profiles row and FK-violates the metering gate, failing the op closed.
    from website.api.zettels_routes import _zoro_user_id

    return _zoro_user_id()


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
