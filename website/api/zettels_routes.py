"""Website Add Zettel API facade."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from website.api._problem import _problem_dict
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
from website.features.functional_gates.async_backpressure import (
    check_async_backpressure,
)
from website.features.summarization_engine.core.errors import (
    ExtractionConfidenceError,
    RoutingError,
    UnsupportedVideoError,
)
from website.features.summarization_engine.post_summary_transformation import registry as _pst
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
# PR #39 / Wave-1 A1: `_AUTO_ACCEPT_AFTER_SECONDS` retired. The URL Add Zettel
# route now always returns 202 immediately; the inline 20s wait/race was the
# root cause of the doubled-pipeline bug class (see add_zettel docstring).
# The document-upload path is still synchronous and unchanged.
_OPERATION_TTL_SECONDS = 15 * 60
# SCOPE: these two in-memory dicts back the SYNCHRONOUS document upload
# path ONLY (`/api/zettels/add/document` -> _run_add_document). The
# asynchronous URL path migrated to the DB-backed core.operations state
# machine in PR #30 / Phase 2; do NOT use these for URL idempotency.
#
# Why kept: document uploads are an inherently synchronous request/response
# (the user expects the parsed document content back inline) and the doc
# extraction is fast enough that a 202-fallback would be UX regression.
# These caps bound per-process memory for the doc endpoint only.
#
# PR #39 / Wave-4 A6 (2026-05-20): re-scoped + renamed comments to kill
# the "dead code" misnomer in the prior copy.
_MAX_DOCUMENT_OPERATION_RECORDS = 128
_MAX_DOCUMENT_IDEMPOTENCY_RECORDS = 128
# Legacy aliases — kept to avoid touching the document path's call sites
# in this PR (rename is mechanical and would conflict with concurrent
# document-path work). Same semantics as the *_DOCUMENT_* names above.
_MAX_OPERATION_RECORDS = _MAX_DOCUMENT_OPERATION_RECORDS
_MAX_IDEMPOTENCY_RECORDS = _MAX_DOCUMENT_IDEMPOTENCY_RECORDS

_IDEMPOTENCY_CACHE: "OrderedDict[tuple[str, str], tuple[float, str, dict[str, Any]]]" = OrderedDict()
_OPERATIONS: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()
_BG_TASKS: set[asyncio.Task] = set()

# Phase 2 (async-ops redesign): canonical strong-ref + cancel target for the
# per-process background worker coroutines spawned by the accept path. The
# core.operations DB row is the cross-worker truth; _LIVE_TASKS only keeps
# the local coroutine reachable so the event loop does not GC it and so
# DELETE /api/zettels/operations/{id} can cooperatively cancel it.
_LIVE_TASKS: dict[str, asyncio.Task] = {}


def _spawn_bg(coro) -> None:
    """Fire-and-forget a coroutine without blocking the caller, keeping a
    strong ref so the event loop doesn't GC it mid-flight."""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


class AddZettelRequest(BaseModel):
    # PR #39 / Wave-1 A2 (2026-05-20): `mode` field retired. The route is
    # always-async now (always 202 + polling) per the single-pipeline-path
    # refactor in A1. The historical `mode: Literal["sync","auto"]` was
    # declared but ignored by the handler; the frontend's `mode:"sync"`
    # claim was a contract lie. Pydantic still ignores extra fields by
    # default for forward compatibility with old clients sending mode.
    url: str
    client_action_id: str = Field(min_length=1, max_length=160)
    persist: bool = True
    surface: Literal["landing", "home", "zettels"]

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


def _present_title(raw: str, source_type: str | None) -> str:
    """Presentation-only title normalization (registry). Stored raw title is
    NEVER mutated; this shapes the DTO/response only."""
    return _pst.apply_text_quality(raw, source_type=source_type, field_kind="title")


def _problem(
    *,
    status_code: int,
    title: str,
    detail: Any,
    operation_id: str | None = None,
    type_slug: str = "add-zettel-failed",
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Sync 4xx/5xx problem+json response. Delegates body construction to the
    shared ``_problem_dict()`` builder so the sync and async paths emit
    physically identical RFC 9457 dicts for the same exception (Phase 3)."""
    body = _problem_dict(
        status_code=status_code,
        title=title,
        detail=detail,
        type_slug=type_slug,
        operation_id=operation_id,
        extra=extra,
    )
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


def _cache_get(key: tuple[str, str], request_hash: str) -> dict[str, Any] | JSONResponse | None:
    """Synchronous-only idempotency cache lookup for the document-upload path.

    Returns the cached body on a hash hit; a 409 problem response on hash
    mismatch (same client_action_id with a different document); None on miss
    or TTL expiry. The async URL path uses ``operations_repo`` (DB row) for
    idempotency since Phase 2 of the async-ops redesign.
    """
    record = _IDEMPOTENCY_CACHE.get(key)
    if not record:
        return None
    ts, cached_hash, value = record
    if time.monotonic() - ts > _OPERATION_TTL_SECONDS:
        _IDEMPOTENCY_CACHE.pop(key, None)
        return None
    if cached_hash != request_hash:
        return _problem(
            status_code=409,
            title="Idempotency key reused with a different request",
            detail="Generate a new client_action_id when changing the document or Add Zettel options.",
            operation_id=key[1],
            type_slug="idempotency-conflict",
        )
    _IDEMPOTENCY_CACHE.move_to_end(key)
    return value


def _cache_put(key: tuple[str, str], request_hash: str, value: dict[str, Any]) -> None:
    _IDEMPOTENCY_CACHE[key] = (time.monotonic(), request_hash, value)
    _IDEMPOTENCY_CACHE.move_to_end(key)
    while len(_IDEMPOTENCY_CACHE) > _MAX_IDEMPOTENCY_RECORDS:
        _IDEMPOTENCY_CACHE.popitem(last=False)


def _operation_put(operation_id: str, value: dict[str, Any]) -> None:
    """Synchronous-only idempotency result cache for the document-upload path.

    The async URL path persists terminal results to the ``core.operations`` DB
    row (Phase 2 of the async-ops redesign); only the synchronous document
    endpoint still needs the per-process body cache for fast cache-hit replays.
    """
    _OPERATIONS[operation_id] = (time.monotonic(), value)
    _OPERATIONS.move_to_end(operation_id)
    while len(_OPERATIONS) > _MAX_OPERATION_RECORDS:
        _OPERATIONS.popitem(last=False)


def _async_failure_error_payload(
    exc: BaseException, *, operation_id: str | None = None,
) -> dict[str, Any] | None:
    """Map a background-task exception to an RFC 9457 problem-detail dict
    physically identical to the sync ``_problem(...)`` body for the same
    exception, so a failure that crossed the 20s universal-202 fast-ack
    boundary surfaces the SAME structured payload to the frontend as the
    inline sync path. Both paths funnel through ``_problem_dict(...)`` —
    Phase 3 of the async-ops redesign. Returns None for generic exceptions
    (no structured detail available — frontend falls back to the existing
    confidence_reason-only generic UI)."""
    if isinstance(exc, HTTPException):
        detail = exc.detail
        title = "Add Zettel request rejected"
        type_slug = "request-rejected"
        if isinstance(detail, dict):
            title = str(detail.get("message") or detail.get("error") or title)
            if detail.get("code") == "quota_exhausted":
                type_slug = "quota-exhausted"
        return _problem_dict(
            status_code=exc.status_code,
            title=title,
            detail=detail,
            type_slug=type_slug,
            operation_id=operation_id,
        )
    if isinstance(exc, UnsupportedVideoError):
        return _problem_dict(
            status_code=422,
            title="Unsupported video",
            detail=f"Video type cannot be ingested: {exc.reason}",
            type_slug="unsupported-video",
            operation_id=operation_id,
        )
    if isinstance(exc, ExtractionConfidenceError):
        return _problem_dict(
            status_code=422,
            title="Insufficient content",
            detail=(
                "Could not extract enough content from this URL to "
                "produce a reliable summary."
            ),
            type_slug="insufficient-content",
            operation_id=operation_id,
            extra={"reason": exc.reason, "tier_results": list(exc.tier_results)},
        )
    if isinstance(exc, (RoutingError, ValueError)):
        return _problem_dict(
            status_code=422,
            title="Invalid Add Zettel request",
            detail=str(exc),
            type_slug="invalid-url",
            operation_id=operation_id,
        )
    if isinstance(exc, SupabaseV2PersistError):
        return _problem_dict(
            status_code=502,
            title="Knowledge-graph write failed",
            detail=exc.detail,
            type_slug="kg-write-failed",
            operation_id=operation_id,
        )
    return None


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


def _schedule_graph_invalidation(user_sub: str | None, persisted: bool) -> None:
    """Run _invalidate_graph as a fire-and-forget continuation, off the
    Add Zettel critical path. Falls back to inline if no running loop."""
    if not persisted:
        return

    async def _run() -> None:
        await asyncio.to_thread(_invalidate_graph, user_sub, persisted)

    try:
        _spawn_bg(_run())
    except RuntimeError:
        _invalidate_graph(user_sub, persisted)


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
    # Off the critical path: graph-cache invalidation is eventually
    # consistent. Schedule it as a post-return continuation so it never
    # adds to the summary's TTFB / the operation's time-to-succeeded.
    _schedule_graph_invalidation(
        user_sub if user else None, persistence.persisted
    )
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


def _failed_response_for(
    exc: BaseException, *, operation_id: str, persist_requested: bool
) -> dict[str, Any]:
    """Build the AddZettelResponse(status='failed', ...) body for an async-
    background-worker exception. Used by `_run` on the failed / cancelled paths
    so the GET handler can return a coherent failed shape with structured
    `.error` for the frontend's class-specific UI (`err.detail.code` keying)."""
    if isinstance(exc, asyncio.CancelledError):
        reason = "operation cancelled"
        # Phase 3: route the cancel shape through the unified builder so it
        # matches the rest of the RFC 9457 family byte-for-byte.
        error_payload: dict[str, Any] | None = _problem_dict(
            status_code=499,
            title="Operation cancelled",
            detail="The operation was cancelled by the client.",
            type_slug="operation_cancelled",
            operation_id=operation_id,
            instance=f"/api/zettels/operations/{operation_id}",
        )
    else:
        reason = str(exc) or exc.__class__.__name__
        error_payload = _async_failure_error_payload(
            exc, operation_id=operation_id,
        )
    return AddZettelResponse(
        status="failed",
        operation_id=operation_id,
        persistence=persistence_dto(persist_requested, None),
        quality=QualityDTO(
            confidence="failed",
            confidence_reason=reason,
        ),
        error=error_payload,
    ).model_dump(mode="json")


async def _run(
    *,
    user_id: UUID,
    operation_id: str,
    body: AddZettelRequest,
    user: dict | None,
) -> None:
    """Phase-2 background worker coroutine.

    Wraps the existing summarize-and-persist pipeline; transitions the canonical
    DB row through the state machine via ops.start / ops.finalize. Strong-ref
    held by `_LIVE_TASKS[operation_id]` until the done-callback pops it.

    The state-guarded RPCs make every transition idempotent: a stale finalize
    against an already-terminal row is a silent no-op (kills the duplicate-
    finalize / blind-update bug class by construction — migration 51).
    """
    # queued -> running. No-op if the row is already terminal (e.g. a cancel
    # raced us); the try/finally below still attempts a terminal write but
    # ops.finalize is also state-guarded, so a second no-op is harmless.
    try:
        await asyncio.to_thread(
            operations_repo.start, user_id=user_id, operation_id=operation_id
        )
    except Exception:
        logger.exception(
            "operations_repo.start raised in _run (op=%s)", operation_id
        )

    try:
        result = await _run_add_zettel(
            body, user=user, effective_user_id=user_id
        )
    except asyncio.CancelledError:
        # Cooperative cancellation (DELETE /api/zettels/operations/{id} or
        # task.cancel() from the local LIVE_TASKS map).
        failed_body = _failed_response_for(
            asyncio.CancelledError(),
            operation_id=operation_id,
            persist_requested=body.persist,
        )
        try:
            await asyncio.to_thread(
                operations_repo.finalize,
                user_id=user_id,
                operation_id=operation_id,
                target="cancelled",
                response=failed_body,
                error=failed_body.get("error"),
            )
        except Exception:
            logger.exception(
                "operations_repo.finalize(cancelled) raised (op=%s)", operation_id
            )
        raise
    except Exception as exc:
        logger.exception("Background Add Zettel operation failed (op=%s)", operation_id)
        failed_body = _failed_response_for(
            exc, operation_id=operation_id, persist_requested=body.persist
        )
        try:
            await asyncio.to_thread(
                operations_repo.finalize,
                user_id=user_id,
                operation_id=operation_id,
                target="failed",
                response=failed_body,
                error=failed_body.get("error"),
            )
        except Exception:
            logger.exception(
                "operations_repo.finalize(failed) raised (op=%s)", operation_id
            )
        return

    # Success path. response = the full AddZettelResponse payload.
    try:
        await asyncio.to_thread(
            operations_repo.finalize,
            user_id=user_id,
            operation_id=operation_id,
            target="succeeded",
            response=result,
            error=None,
        )
    except Exception:
        logger.exception(
            "operations_repo.finalize(succeeded) raised (op=%s)", operation_id
        )


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
    # Phase 2 (async-ops redesign): honor IETF-draft `Idempotency-Key` header
    # (https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/)
    # as the operation_id when present; fall back to the legacy client_action_id.
    # The header takes precedence so a client retrying with the same key gets
    # the same canonical op even if it forgot to reuse client_action_id.
    idempotency_header = (request.headers.get("Idempotency-Key") or "").strip()
    operation_id = idempotency_header or body.client_action_id
    request_hash = _request_hash(body)
    # Phase 4: per-user async backpressure gate. DB-backed in-flight count is
    # the cross-worker source of truth (replaces the per-worker in-memory
    # accounting deleted in Phase 5). Fail-open inside the gate so a transient
    # DB hiccup never 5xxs accept. Runs AFTER auth + rate-limit and BEFORE the
    # accept RPC; uniform 429 regardless of dedup hit — protects against poll-
    # cache thrash. Same-key duplicates are throttled identically; if the user
    # really is over the per-user cap, the duplicate is still a backpressure
    # signal worth shedding before any DB work happens.
    backpressure_response = await check_async_backpressure(user_id=effective_user_id)
    if backpressure_response is not None:
        return backpressure_response

    # PR #39 / Wave-1 A1 (2026-05-20): single-pipeline path.
    # The previous design wrapped `_run_add_zettel` in a `work` probe + a
    # 20s `wait_for(shield)` race that, on timeout, spawned a SECOND copy of
    # the pipeline via `_run(...)` while cancelling the first. That doubled
    # the pipeline work for any URL exceeding the fast-ack window (20s wasted
    # + full re-run), and left the `_SUMMARIZE_SEMAPHORE` held by the
    # cancelled probe until cooperative cancellation propagated through the
    # Gemini SDK. The route now always 202s immediately: ops_accept records
    # the queued row, _run takes the canonical pipeline lane, and the client
    # polls `/api/operations/{id}` for terminal state. Fast cached results
    # (duplicate request_hash on a succeeded row) resolve in one extra poll
    # rather than inline-200, accepted as the price of correctness.
    try:
        accepted = AddZettelResponse(
            status="accepted",
            operation_id=operation_id,
            persistence=persistence_dto(body.persist, None),
            quality=QualityDTO(confidence="pending"),
            status_url=f"/api/operations/{operation_id}",
        ).model_dump(mode="json")
        # State-guarded accept via core.ops_accept RPC (migration 51).
        # Returns the CANONICAL op_id + is_new flag. Per Stripe/Brandur
        # idempotency: duplicate (user_id, request_hash) for an active
        # row returns the existing canonical op rather than creating a
        # new one — the client's poll resolves to the same result.
        try:
            canonical_op_id, is_new = await asyncio.to_thread(
                operations_repo.accept,
                user_id=effective_user_id,
                operation_id=operation_id,
                request_hash=request_hash,
                accepted_body=accepted,
                ttl_seconds=86400,
            )
        except Exception:
            logger.exception(
                "operations_repo.accept raised (op=%s); falling back to local op_id",
                operation_id,
            )
            canonical_op_id, is_new = operation_id, True

        if is_new:
            # Spawn the background worker holding the canonical op id.
            # _LIVE_TASKS is the strong-ref + cancel target for the local
            # process; the DB row is the cross-worker truth.
            run_task = asyncio.create_task(
                _run(
                    user_id=effective_user_id,
                    operation_id=canonical_op_id,
                    body=body,
                    user=user,
                )
            )
            _LIVE_TASKS[canonical_op_id] = run_task
            run_task.add_done_callback(
                lambda _t, _op=canonical_op_id: _LIVE_TASKS.pop(_op, None)
            )
        else:
            # Duplicate active request: an existing canonical op already owns
            # this work. The client polls the canonical op id and resolves to
            # the same result. Realign the response so 202 body + Location
            # header agree on the canonical id.
            accepted["operation_id"] = canonical_op_id
            accepted["status_url"] = f"/api/operations/{canonical_op_id}"

        return JSONResponse(
            accepted,
            status_code=202,
            headers={
                "Location": f"/api/operations/{canonical_op_id}",
                "Retry-After": "2",
            },
        )
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
            operation_id=body.client_action_id,
            type_slug=type_slug,
        )
    except UnsupportedVideoError as exc:
        return _problem(
            status_code=422,
            title="Unsupported video",
            detail=f"Video type cannot be ingested: {exc.reason}",
            operation_id=body.client_action_id,
            type_slug="unsupported-video",
        )
    except ExtractionConfidenceError as exc:
        return _problem(
            status_code=422,
            title="Insufficient content",
            detail="Could not extract enough content from this URL to produce a reliable summary.",
            operation_id=body.client_action_id,
            type_slug="insufficient-content",
            extra={"reason": exc.reason, "tier_results": exc.tier_results},
        )
    except (RoutingError, ValueError) as exc:
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
        logger.error("Add Zettel v2 persist failed for %s: %s", body.url, exc.detail)
        return _problem(
            status_code=502,
            title="Knowledge-graph write failed",
            detail=exc.detail,
            operation_id=body.client_action_id,
            type_slug="kg-write-failed",
        )
    except Exception as exc:
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


def _terminal_cache_headers(operation_id: str, status: str, updated_at: Any) -> dict[str, str]:
    """PR #40 L3' (2026-05-21): cache-control for terminal operations
    responses. Terminal rows (succeeded/failed/cancelled/expired) are
    IMMUTABLE — once finalize fires the row never mutates — so it's safe
    for the browser to cache the response for 5 minutes. Saves a
    PostgREST hit on every tab refresh / repeat poll after terminal.

    `private` = browser-only cache (no CDN/Cloudflare share — this body
    is per-user-scoped, must not leak across tenants). `max-age=300` is
    a conservative 5-minute window; aligned with the polling budget.
    ETag is derived from operation_id + status + updated_at so any
    re-write (e.g., reaper backfill) invalidates client caches."""
    import hashlib

    etag_input = f"{operation_id}|{status}|{updated_at or ''}".encode("utf-8")
    etag = '"' + hashlib.sha256(etag_input).hexdigest()[:16] + '"'
    return {
        "Cache-Control": "private, max-age=300",
        "ETag": etag,
    }


_NO_STORE_HEADERS: dict[str, str] = {"Cache-Control": "no-store"}


@router.get("/operations/{operation_id}", response_model=AddZettelResponse)
async def operation_status(
    operation_id: str,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    """Phase-2 (async-ops redesign): DB-only read.

    The `core.operations` row is the sole source of truth. The legacy
    in-memory fallback was removed in Phase 5 of the async-ops redesign; the
    DB CHECK + state-guarded RPCs (migration 51) ensure the row always
    reflects the canonical state across all workers.

    PR #40 L3' (2026-05-21): terminal responses (succeeded/failed/cancelled/
    expired) carry `Cache-Control: private, max-age=300` + ETag so a tab
    refresh after terminal hits the browser cache rather than re-querying
    PostgREST. Active responses (queued/running/accepted) keep
    `Cache-Control: no-store` since their content evolves with each poll.
    """
    effective_user_id = _effective_user_id(user)
    row = await asyncio.to_thread(
        operations_repo.get_operation,
        user_id=effective_user_id,
        operation_id=operation_id,
    )

    if row is None:
        # Cross-worker replication gap during accept: the accepted row may
        # not yet be visible to this worker's read replica. A hard 404 would
        # fail a job that is actually queued/running on another worker.
        # Return a transient 202 pending — bounded by the client's 180s
        # poll budget, after which a genuinely-bogus id falls out client-side.
        pending = AddZettelResponse(
            status="accepted",
            operation_id=operation_id,
            persistence=persistence_dto(True, None),
            quality=QualityDTO(confidence="pending"),
            status_url=f"/api/operations/{operation_id}",
        ).model_dump(mode="json")
        return JSONResponse(
            pending,
            status_code=202,
            headers={
                "Location": f"/api/operations/{operation_id}",
                "Retry-After": "2",
                **_NO_STORE_HEADERS,
            },
        )

    status = row.get("status")

    # Active states -> 202 + Retry-After. The accepted body lives in
    # `response` (written by ops_accept/_run on the queued INSERT or the
    # `accepted` legacy lexicon backfilled by migration 51).
    # PR #39 / Wave-2 (2026-05-20): surface the DB-level row status as
    # `phase` so the frontend skeleton typewriter can show
    # stage-appropriate quirky messages (queued = "warming up",
    # running = "in progress"). Kept separate from the legacy
    # body.status="accepted" lexicon so existing clients are unaffected.
    if status in ("queued", "running", "accepted"):
        payload = dict(row.get("response") or {})
        payload["phase"] = status if status in ("queued", "running") else "queued"
        return JSONResponse(
            payload,
            status_code=202,
            headers={
                "Location": f"/api/operations/{operation_id}",
                "Retry-After": "2",
                **_NO_STORE_HEADERS,
            },
        )

    # Succeeded: 200 + full AddZettelResponse from `response`.
    if status == "succeeded":
        payload = row.get("response") or {}
        return JSONResponse(
            payload,
            status_code=200,
            headers=_terminal_cache_headers(
                operation_id, status, row.get("updated_at")
            ),
        )

    # Failed / cancelled: 200 + body containing status + operation_id + the
    # RFC 9457 `error` dict. Prefer the full AddZettelResponse-shaped body
    # written by _run (carries quality.confidence_reason + .error); fall
    # back to a minimal envelope if only the `error` column was populated
    # (legacy / reaper-set rows).
    if status in ("failed", "cancelled"):
        cache_headers = _terminal_cache_headers(
            operation_id, status, row.get("updated_at")
        )
        body_resp = row.get("response")
        if isinstance(body_resp, dict) and body_resp:
            return JSONResponse(body_resp, status_code=200, headers=cache_headers)
        envelope = {
            "status": status,
            "operation_id": operation_id,
            "error": row.get("error") or {},
        }
        return JSONResponse(envelope, status_code=200, headers=cache_headers)

    # Expired: 410 Gone + RFC 9457 envelope.
    if status == "expired":
        envelope = {
            "status": "expired",
            "operation_id": operation_id,
            "error": row.get("error")
            or _problem_dict(
                status_code=410,
                title="Operation expired",
                detail="This operation's TTL elapsed before it could be retrieved.",
                type_slug="operation_expired",
                operation_id=operation_id,
                instance=f"/api/zettels/operations/{operation_id}",
            ),
        }
        return JSONResponse(
            envelope,
            status_code=410,
            headers=_terminal_cache_headers(
                operation_id, status, row.get("updated_at")
            ),
        )

    # Unknown status (defensive — CHECK constraint should make this
    # unreachable). Treat as pending 202 rather than 5xx.
    return JSONResponse(
        row.get("response") or {},
        status_code=202,
        headers={"Retry-After": "2"},
    )


@router.delete("/zettels/operations/{operation_id}")
async def cancel_operation(
    operation_id: str,
    request: Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    """Phase-2 (async-ops redesign): cooperative cancellation.

    Auth model (hardened 2026-05-21):
        * Caller must be authenticated AND must supply an `Idempotency-Key`
          header that exactly matches the path `operation_id`. This is the
          client-action-id-bound auth: only the originating client (which
          minted and remembers the op_id at POST time) can cancel.
        * BOLA scoping is enforced inside the RPC: ops_finalize WHERE
          user_id = $1 AND operation_id = $2; a JWT for a different user
          silently no-ops.

    Behaviour:
        * Flips the DB row to `cancelled` via the state-guarded RPC. If the
          row is already terminal the RPC is a silent no-op.
        * Does NOT hard-cancel the in-flight asyncio task (removed
          2026-05-21). The persist phase is shielded; injecting CancelledError
          mid-PostgREST would risk partial writes (canonical_zettel without
          workspace_zettel siblings). Letting the task finish naturally is
          bounded by GUNICORN_TIMEOUT, and its eventual `finalize(succeeded)`
          is a no-op because the state guard in `ops_finalize` only matches
          status IN ('queued', 'running').

    Caller attribution: this endpoint has no JS caller in this repo (verified
    2026-05-21 audit). The 2026-05-21 phantom DELETE came from an external
    actor (stale cached JS, second tab, devtools, extension). Log every
    request's identifying headers so the next phantom is traceable.
    """
    effective_user_id = _effective_user_id(user)
    h = request.headers
    attribution = {
        "user_agent": h.get("user-agent"),
        "referer": h.get("referer"),
        "origin": h.get("origin"),
        "x_forwarded_for": h.get("x-forwarded-for"),
        "cf_connecting_ip": h.get("cf-connecting-ip"),
        "cf_ray": h.get("cf-ray"),
        "cf_ipcountry": h.get("cf-ipcountry"),
        "sec_fetch_site": h.get("sec-fetch-site"),
        "sec_fetch_mode": h.get("sec-fetch-mode"),
        "idempotency_key": h.get("idempotency-key"),
    }
    logger.warning(
        "cancel_operation caller-attribution op=%s user=%s %s",
        operation_id,
        effective_user_id,
        attribution,
    )

    # Client-action-id-bound auth: the originating client minted the op_id
    # and remembers it; an external actor without that knowledge cannot
    # produce a matching Idempotency-Key. This is defense-in-depth on top
    # of the existing user_id scoping inside the RPC.
    idem = h.get("idempotency-key")
    if not idem or idem != operation_id:
        logger.warning(
            "cancel_operation rejected: idempotency-key mismatch op=%s key=%r",
            operation_id,
            idem,
        )
        return JSONResponse(
            {
                "type": "https://zettelkasten.in/problems/errors/forbidden",
                "title": "Forbidden",
                "detail": (
                    "DELETE /api/zettels/operations/{id} requires the "
                    "Idempotency-Key header to match the path operation_id "
                    "(client-action-id-bound cancellation)."
                ),
                "status": 403,
                "code": "operation_cancel_idempotency_mismatch",
                "operation_id": operation_id,
            },
            status_code=403,
        )

    try:
        cancelled = await asyncio.to_thread(
            operations_repo.cancel,
            user_id=effective_user_id,
            operation_id=operation_id,
        )
    except Exception:
        logger.exception(
            "operations_repo.cancel raised (op=%s)", operation_id
        )
        cancelled = False

    # Diagnostic only: report whether a local in-flight task is still running.
    # We DO NOT cancel it -- per 2026-05-21 redesign, the shielded persist
    # must run to completion. The task's eventual finalize(succeeded) is a
    # no-op because the row is now in the cancelled terminal state.
    local_task = _LIVE_TASKS.get(operation_id)
    if local_task is not None and not local_task.done():
        logger.info(
            "cancel_operation: in-flight task left running (shielded persist) op=%s",
            operation_id,
        )

    return JSONResponse(
        {
            "status": "cancelled" if cancelled else "noop",
            "operation_id": operation_id,
        },
        status_code=200,
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
                        "title": _present_title(
                            str(canonical.get("title") or "Untitled"),
                            str(canonical.get("source_type") or "").lower(),
                        ),
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
