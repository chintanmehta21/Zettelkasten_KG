"""Website Add Zettel API facade."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from website.api.auth import get_optional_user
from website.api.module_runners.summarization import (
    AddZettelPipelineOutput as AddZettelResponse,
    PersistenceDTO,
    QualityDTO,
    default_gemini_client,
    persistence_dto,
    run_add_document_pipeline,
    run_add_zettel_pipeline,
)
from website.core import operations_repo
from website.core.persist import (
    SupabaseV2PersistError,
    extract_summary_parts,
    get_supabase_v2_scope_for_read,
)
from website.core.url_utils import validate_url
from website.features.summarization_engine.core.errors import (
    ExtractionConfidenceError,
    RoutingError,
    UnsupportedVideoError,
)
from website.features.summarization_engine.source_ingest.document import DocumentUploadError

logger = logging.getLogger("website.api.zettels")
router = APIRouter(prefix="/api")

_EXPECTED_USERS_PATH = Path(__file__).resolve().parents[2] / "ops" / "deploy" / "expected_users.json"
_SENTINEL_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
_ZORO_USER_ID: UUID | None = None

_RATE_STORE: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 10
_RATE_WINDOW_SECONDS = 60
_MAX_DOCUMENT_UPLOAD_BYTES = 10 * 1024 * 1024
# Raised 8 -> 20 (approved): fast jobs still return inline 200 within 20s;
# anything slower fast-acks 202 well before Cloudflare's ~100s edge timeout.
_AUTO_ACCEPT_AFTER_SECONDS = 20.0
_OPERATION_TTL_SECONDS = 15 * 60
_MAX_OPERATION_RECORDS = 128
_MAX_IDEMPOTENCY_RECORDS = 128

_IDEMPOTENCY_CACHE: "OrderedDict[tuple[str, str], tuple[float, str, dict[str, Any]]]" = OrderedDict()
_OPERATIONS: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()
_OPERATION_TASKS: dict[str, asyncio.Task] = {}
_IN_FLIGHT: dict[tuple[str, str], tuple[str, str, asyncio.Task]] = {}


class AddZettelRequest(BaseModel):
    url: str
    client_action_id: str = Field(min_length=1, max_length=160)
    persist: bool = True
    surface: Literal["landing", "home", "zettels"]
    mode: Literal["sync", "auto"] = "sync"

    @field_validator("url")
    @classmethod
    def validate_url_field(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("URL is required")
        if len(value) > 2048:
            raise ValueError("URL too long (max 2048 characters)")
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        if not validate_url(value):
            raise ValueError("URL is invalid or blocked")
        return value


def _problem(
    *,
    status_code: int,
    title: str,
    detail: Any,
    operation_id: str | None = None,
    type_slug: str = "add-zettel-failed",
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://zettelkasten.in/problems/errors/{type_slug}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": f"/api/zettels/add/{operation_id}" if operation_id else "/api/zettels/add",
    }
    if operation_id:
        body["operation_id"] = operation_id
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status_code, media_type="application/problem+json")


def _check_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    _RATE_STORE[ip] = [t for t in _RATE_STORE[ip] if now - t < _RATE_WINDOW_SECONDS]
    if len(_RATE_STORE[ip]) >= _RATE_LIMIT:
        return False
    _RATE_STORE[ip].append(now)
    return True


def _zoro_user_id() -> UUID:
    global _ZORO_USER_ID
    if _ZORO_USER_ID is not None:
        return _ZORO_USER_ID
    try:
        raw = json.loads(_EXPECTED_USERS_PATH.read_text(encoding="utf-8"))
        _ZORO_USER_ID = UUID(str(raw["_canonical_zoro"]))
    except Exception:
        logger.exception("Failed to load Zoro auth UUID; falling back to sentinel user")
        _ZORO_USER_ID = _SENTINEL_USER_ID
    return _ZORO_USER_ID


def _effective_user_id(user: dict | None) -> UUID:
    raw = (user or {}).get("sub")
    if raw:
        try:
            return UUID(str(raw))
        except ValueError:
            logger.warning("Ignoring non-UUID auth sub for Add Zettel")
    return _zoro_user_id()


_gemini_client = default_gemini_client


def _request_hash(body: AddZettelRequest) -> str:
    import hashlib

    fingerprint = body.model_dump(mode="json")
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _document_request_hash(
    *,
    filename: str,
    content: bytes,
    persist: bool,
    surface: str,
) -> str:
    import hashlib

    fingerprint = {
        "filename": filename,
        "sha256": hashlib.sha256(content).hexdigest(),
        "persist": persist,
        "surface": surface,
    }
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _idempotency_conflict(operation_id: str) -> JSONResponse:
    return _problem(
        status_code=409,
        title="Idempotency key reused with a different request",
        detail="Generate a new client_action_id when changing the URL or Add Zettel options.",
        operation_id=operation_id,
        type_slug="idempotency-conflict",
    )


def _cache_get(key: tuple[str, str], request_hash: str) -> dict[str, Any] | JSONResponse | None:
    record = _IDEMPOTENCY_CACHE.get(key)
    if not record:
        return None
    ts, cached_hash, value = record
    if time.monotonic() - ts > _OPERATION_TTL_SECONDS:
        _IDEMPOTENCY_CACHE.pop(key, None)
        return None
    if cached_hash != request_hash:
        return _idempotency_conflict(key[1])
    _IDEMPOTENCY_CACHE.move_to_end(key)
    return value


def _cache_put(key: tuple[str, str], request_hash: str, value: dict[str, Any]) -> None:
    _IDEMPOTENCY_CACHE[key] = (time.monotonic(), request_hash, value)
    _IDEMPOTENCY_CACHE.move_to_end(key)
    while len(_IDEMPOTENCY_CACHE) > _MAX_IDEMPOTENCY_RECORDS:
        _IDEMPOTENCY_CACHE.popitem(last=False)


def _operation_put(operation_id: str, value: dict[str, Any]) -> None:
    _OPERATIONS[operation_id] = (time.monotonic(), value)
    _OPERATIONS.move_to_end(operation_id)
    while len(_OPERATIONS) > _MAX_OPERATION_RECORDS:
        old_id, _ = _OPERATIONS.popitem(last=False)
        old_task = _OPERATION_TASKS.pop(old_id, None)
        if old_task and not old_task.done():
            old_task.cancel()


def _operation_get(operation_id: str) -> dict[str, Any] | None:
    record = _OPERATIONS.get(operation_id)
    if not record:
        return None
    ts, value = record
    if time.monotonic() - ts > _OPERATION_TTL_SECONDS:
        _OPERATIONS.pop(operation_id, None)
        _OPERATION_TASKS.pop(operation_id, None)
        return None
    _OPERATIONS.move_to_end(operation_id)
    return value


def _store_operation_result(
    task: asyncio.Task,
    *,
    operation_id: str,
    cache_key: tuple[str, str],
    request_hash: str,
    persist_requested: bool,
    user_id: UUID | None = None,
) -> None:
    failed = False
    try:
        result = task.result()
    except Exception as exc:
        logger.exception("Background Add Zettel operation failed")
        failed = True
        result = AddZettelResponse(
            status="failed",
            operation_id=operation_id,
            persistence=persistence_dto(persist_requested, None),
            quality=QualityDTO(
                confidence="failed",
                confidence_reason=str(exc),
            ),
        ).model_dump(mode="json")
    else:
        _cache_put(cache_key, request_hash, result)
    _operation_put(operation_id, result)
    _OPERATION_TASKS.pop(operation_id, None)
    _IN_FLIGHT.pop(cache_key, None)
    if user_id is not None:
        # Persist terminal state to the shared store so cross-worker polls
        # resolve. Scheduled on the loop, DB call in a thread; never fatal.
        async def _persist_terminal() -> None:
            fn = operations_repo.mark_failed if failed else operations_repo.mark_succeeded
            await asyncio.to_thread(
                fn, user_id=user_id, operation_id=operation_id, response=result
            )
        try:
            asyncio.get_running_loop().create_task(_persist_terminal())
        except RuntimeError:
            # No running loop (callback fired post-loop, e.g. tests): best
            # effort synchronous write.
            (operations_repo.mark_failed if failed else operations_repo.mark_succeeded)(
                user_id=user_id, operation_id=operation_id, response=result
            )


async def _await_in_flight(
    *,
    cache_key: tuple[str, str],
    request_hash: str,
    operation_id: str,
    task: asyncio.Task,
) -> dict[str, Any]:
    result = await asyncio.shield(task)
    _cache_put(cache_key, request_hash, result)
    _operation_put(operation_id, result)
    _IN_FLIGHT.pop(cache_key, None)
    return result


def _invalidate_graph(user_sub: str | None, persisted: bool) -> None:
    if not persisted:
        return
    try:
        from website.api import routes as routes_mod

        routes_mod.invalidate_user_graph(user_sub)
        routes_mod._graph_cache_global = None
        routes_mod._graph_cache_global_ts = 0
    except Exception:
        logger.exception("Failed to invalidate graph cache after Add Zettel")


async def _run_add_zettel(
    body: AddZettelRequest,
    *,
    user: dict | None,
    effective_user_id: UUID,
) -> dict[str, Any]:
    user_sub = str(effective_user_id)
    result = await run_add_zettel_pipeline(
        url=body.url,
        client_action_id=body.client_action_id,
        persist=body.persist,
        user=user,
        effective_user_id=effective_user_id,
        gemini_client_factory=_gemini_client,
    )
    persistence = PersistenceDTO.model_validate(result["persistence"])
    _invalidate_graph(user_sub if user else None, persistence.persisted)
    return result


async def _run_add_document(
    *,
    filename: str,
    content: bytes,
    content_type: str | None,
    client_action_id: str,
    persist: bool,
    user: dict | None,
    effective_user_id: UUID,
) -> dict[str, Any]:
    user_sub = str(effective_user_id)
    result = await run_add_document_pipeline(
        filename=filename,
        content=content,
        content_type=content_type,
        client_action_id=client_action_id,
        persist=persist,
        user=user,
        effective_user_id=effective_user_id,
        gemini_client_factory=_gemini_client,
    )
    persistence = PersistenceDTO.model_validate(result["persistence"])
    _invalidate_graph(user_sub if user else None, persistence.persisted)
    return result


@router.post("/zettels/add", response_model=AddZettelResponse)
async def add_zettel(
    body: AddZettelRequest,
    request: Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        return _problem(
            status_code=429,
            title="Too many Add Zettel requests",
            detail="Please wait a minute before trying again.",
            operation_id=body.client_action_id,
            type_slug="rate-limited",
        )

    effective_user_id = _effective_user_id(user)
    cache_key = (str(effective_user_id), body.client_action_id)
    request_hash = _request_hash(body)
    cached = _cache_get(cache_key, request_hash)
    if cached is not None:
        return cached
    in_flight = _IN_FLIGHT.get(cache_key)
    if in_flight is not None:
        running_hash, operation_id, running_task = in_flight
        if running_hash != request_hash:
            return _idempotency_conflict(body.client_action_id)
        # Universal async: return existing accepted response for in-flight ops.
        existing = _operation_get(operation_id)
        if existing is None:
            existing = AddZettelResponse(
                status="accepted",
                operation_id=operation_id,
                persistence=persistence_dto(body.persist, None),
                quality=QualityDTO(confidence="pending"),
                status_url=f"/api/operations/{operation_id}",
            ).model_dump(mode="json")
        return JSONResponse(
            existing,
            status_code=202 if existing.get("status") == "accepted" else 200,
            headers={
                "Location": f"/api/operations/{operation_id}",
                "Retry-After": "3",
            },
        )

    try:
        work = asyncio.create_task(
            _run_add_zettel(body, user=user, effective_user_id=effective_user_id)
        )
        _IN_FLIGHT[cache_key] = (request_hash, body.client_action_id, work)
        try:
            # Inline-return path: fast jobs (<= N s) still get a synchronous
            # 200 with the full result, exactly as before.
            result = await asyncio.wait_for(
                asyncio.shield(work), timeout=_AUTO_ACCEPT_AFTER_SECONDS
            )
        except TimeoutError:
            # Universal 202 fast-ack (ALL modes, incl. the prod 'sync'
            # frontend default). Cloudflare-524 fix: never hold the
            # connection past N; the client polls /api/operations/{id}.
            accepted = AddZettelResponse(
                status="accepted",
                operation_id=body.client_action_id,
                persistence=persistence_dto(body.persist, None),
                quality=QualityDTO(confidence="pending"),
                status_url=f"/api/operations/{body.client_action_id}",
            ).model_dump(mode="json")
            _operation_put(body.client_action_id, accepted)
            _OPERATION_TASKS[body.client_action_id] = work
            # Shared store so any worker can answer the poll + it survives
            # worker recycle. Off the event loop; never fatal.
            await asyncio.to_thread(
                operations_repo.create_accepted,
                user_id=effective_user_id,
                operation_id=body.client_action_id,
                request_hash=request_hash,
                accepted_body=accepted,
            )
            work.add_done_callback(
                lambda task: _store_operation_result(
                    task,
                    operation_id=body.client_action_id,
                    cache_key=cache_key,
                    request_hash=request_hash,
                    persist_requested=body.persist,
                    user_id=effective_user_id,
                )
            )
            return JSONResponse(
                accepted,
                status_code=202,
                headers={
                    "Location": f"/api/operations/{body.client_action_id}",
                    "Retry-After": "3",
                },
            )
        _cache_put(cache_key, request_hash, result)
        _operation_put(body.client_action_id, result)
        _IN_FLIGHT.pop(cache_key, None)
        return result
    except HTTPException as exc:
        _IN_FLIGHT.pop(cache_key, None)
        detail = exc.detail
        problem_title = "Add Zettel request rejected"
        type_slug = "request-rejected"
        if isinstance(detail, dict):
            problem_title = str(detail.get("message") or detail.get("error") or problem_title)
            if detail.get("code") == "quota_exhausted":
                type_slug = "quota-exhausted"
        return _problem(
            status_code=exc.status_code,
            title=problem_title,
            detail=detail,
            operation_id=body.client_action_id,
            type_slug=type_slug,
        )
    except UnsupportedVideoError as exc:
        _IN_FLIGHT.pop(cache_key, None)
        return _problem(
            status_code=422,
            title="Unsupported video",
            detail=f"Video type cannot be ingested: {exc.reason}",
            operation_id=body.client_action_id,
            type_slug="unsupported-video",
        )
    except ExtractionConfidenceError as exc:
        _IN_FLIGHT.pop(cache_key, None)
        return _problem(
            status_code=422,
            title="Insufficient content",
            detail="Could not extract enough content from this URL to produce a reliable summary.",
            operation_id=body.client_action_id,
            type_slug="insufficient-content",
            extra={"reason": exc.reason, "tier_results": exc.tier_results},
        )
    except (RoutingError, ValueError) as exc:
        _IN_FLIGHT.pop(cache_key, None)
        return _problem(
            status_code=422,
            title="Invalid Add Zettel request",
            detail=str(exc),
            operation_id=body.client_action_id,
            type_slug="invalid-url",
        )
    except SupabaseV2PersistError as exc:
        # P1-2: v2 was configured + attempted but the KG write failed (broken
        # RPC, schema-cache miss, RLS denial, empty RPC result). Surface a
        # non-200 problem+json instead of the old silent 200 + supabase=false.
        _IN_FLIGHT.pop(cache_key, None)
        logger.error("Add Zettel v2 persist failed for %s: %s", body.url, exc.detail)
        return _problem(
            status_code=502,
            title="Knowledge-graph write failed",
            detail=exc.detail,
            operation_id=body.client_action_id,
            type_slug="kg-write-failed",
        )
    except Exception as exc:
        _IN_FLIGHT.pop(cache_key, None)
        logger.exception("Add Zettel failed for %s", body.url)
        return _problem(
            status_code=500,
            title="Add Zettel failed",
            detail=f"Failed to process URL: {exc}",
            operation_id=body.client_action_id,
        )


@router.post("/zettels/add/document", response_model=AddZettelResponse)
async def add_zettel_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    client_action_id: Annotated[str, Form(min_length=1, max_length=160)],
    persist: Annotated[bool, Form()] = True,
    surface: Annotated[Literal["landing", "home", "zettels"], Form()] = "landing",
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    _ = surface
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        return _problem(
            status_code=429,
            title="Too many Add Zettel requests",
            detail="Please wait a minute before trying again.",
            operation_id=client_action_id,
            type_slug="rate-limited",
        )

    content = await file.read(_MAX_DOCUMENT_UPLOAD_BYTES + 1)
    if len(content) > _MAX_DOCUMENT_UPLOAD_BYTES:
        return _problem(
            status_code=413,
            title="Document too large",
            detail="Upload a document up to 10 MB.",
            operation_id=client_action_id,
            type_slug="document-too-large",
        )

    effective_user_id = _effective_user_id(user)
    filename = file.filename or "uploaded-document"
    cache_key = (str(effective_user_id), client_action_id)
    request_hash = _document_request_hash(
        filename=filename,
        content=content,
        persist=persist,
        surface=surface,
    )
    cached = _cache_get(cache_key, request_hash)
    if cached is not None:
        return cached

    try:
        result = await _run_add_document(
            filename=filename,
            content=content,
            content_type=file.content_type,
            client_action_id=client_action_id,
            persist=persist,
            user=user,
            effective_user_id=effective_user_id,
        )
        _cache_put(cache_key, request_hash, result)
        _operation_put(client_action_id, result)
        return result
    except HTTPException as exc:
        detail = exc.detail
        problem_title = "Add Zettel request rejected"
        type_slug = "request-rejected"
        if isinstance(detail, dict):
            problem_title = str(detail.get("message") or detail.get("error") or problem_title)
            if detail.get("code") == "quota_exhausted":
                type_slug = "quota-exhausted"
        return _problem(
            status_code=exc.status_code,
            title=problem_title,
            detail=detail,
            operation_id=client_action_id,
            type_slug=type_slug,
        )
    except DocumentUploadError as exc:
        return _problem(
            status_code=422,
            title="Invalid document upload",
            detail=str(exc),
            operation_id=client_action_id,
            type_slug="invalid-document",
        )
    except Exception as exc:
        logger.exception("Document Add Zettel failed for %s", filename)
        return _problem(
            status_code=500,
            title="Add Zettel failed",
            detail=f"Failed to process document: {exc}",
            operation_id=client_action_id,
        )


@router.get("/operations/{operation_id}", response_model=AddZettelResponse)
async def operation_status(
    operation_id: str,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    effective_user_id = _effective_user_id(user)
    row = await asyncio.to_thread(
        operations_repo.get_operation,
        user_id=effective_user_id,
        operation_id=operation_id,
    )
    if row is not None:
        status = row.get("status")
        payload = row.get("response") or row.get("error") or {}
        if status == "accepted":
            return JSONResponse(payload, status_code=202)
        return JSONResponse(payload, status_code=200)
    # Single-worker / dev fallback: in-memory store.
    result = _operation_get(operation_id)
    if result is None:
        return _problem(
            status_code=404,
            title="Operation not found",
            detail="The operation is unknown or expired.",
            operation_id=operation_id,
            type_slug="operation-not-found",
        )
    return JSONResponse(
        result, status_code=202 if result.get("status") == "accepted" else 200
    )


class ZettelListItem(BaseModel):
    id: str
    title: str
    brief_summary: str
    detailed_summary: str
    tags: list[str]
    source_type: str
    source_url: str
    added_at: str
    published_at: str


class ZettelListResponse(BaseModel):
    zettels: list[ZettelListItem]
    total: int
    limit: int
    offset: int


@router.get("/zettels", response_model=ZettelListResponse)
async def list_zettels(
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
    limit: int = 5000,
    offset: int = 0,
):
    """Dedicated per-user Zettel list (v2). Distinct from /api/graph?view=my
    (the 3D knowledge-graph). ``id`` is the workspace_zettel UUID so the
    existing DELETE/PATCH /api/zettels/{id} contract works directly.

    Known v1 limitations (plan-accepted, YAGNI):
    - ``limit`` and ``offset`` are applied PER WORKSPACE — each
      ``list_workspace_zettels(ws_id, limit=limit, offset=offset)`` call is
      sliced independently, not over a single cross-workspace window. Users with
      one personal workspace (the typical production case) are unaffected.
    - ``total`` in the response equals ``len(items)`` — the number of items
      returned in this response after per-workspace slicing and canonical
      dedupe, NOT the user's grand total of zettels in the database.
    """
    if user is None:
        return _problem(
            status_code=401,
            title="Authentication required",
            detail="Sign in to view your Zettels.",
            operation_id="",
            type_slug="unauthenticated",
        )

    limit = max(1, min(int(limit), 10000))
    offset = max(0, int(offset))

    scope = get_supabase_v2_scope_for_read(user.get("sub"))
    if scope is None:
        return JSONResponse(
            {"zettels": [], "total": 0, "limit": limit, "offset": offset}
        )
    content_repo, _profile_id, workspace_ids = scope

    items: list[dict] = []
    seen_canonical: set[str] = set()
    try:
        for ws_id in workspace_ids:
            rows = content_repo.list_workspace_zettels(
                ws_id, limit=limit, offset=offset
            )
            for row in rows:
                canonical = row.get("canonical") or {}
                canonical_id = str(
                    canonical.get("id") or row.get("canonical_zettel_id") or ""
                )
                if not canonical_id or canonical_id in seen_canonical:
                    continue
                seen_canonical.add(canonical_id)
                brief, detailed = extract_summary_parts(
                    row.get("ai_summary"), None
                )
                items.append(
                    {
                        "id": str(row.get("id") or ""),
                        "title": str(canonical.get("title") or "Untitled"),
                        "brief_summary": brief or "",
                        "detailed_summary": detailed or "",
                        "tags": list(row.get("user_tags") or []),
                        "source_type": str(
                            canonical.get("source_type") or "web"
                        ).lower(),
                        "source_url": str(
                            canonical.get("normalized_url") or ""
                        ),
                        "added_at": str(row.get("created_at") or ""),
                        "published_at": str(
                            canonical.get("publication_date") or ""
                        ),
                    }
                )
    except Exception:
        logger.exception("list_zettels failed; returning empty list")
        return JSONResponse(
            {"zettels": [], "total": 0, "limit": limit, "offset": offset}
        )

    return JSONResponse(
        {
            "zettels": items,
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }
    )
