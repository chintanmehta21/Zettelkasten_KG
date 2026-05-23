"""Sandbox and node-picker routes for the user-level RAG experience.

Phase 4.4 (DB v2 purge) — kasten CRUD dual-path:
 * list/create/delete kastens, list-zettels-in-kasten, and add-zettels-to-kasten
   route to ``rag.kastens`` + ``rag.kasten_zettels`` (via ``bulk_add_to_kasten``
   / ``list_kasten_zettels`` RPCs) when DB v2 is on AND the JWT subject is a
   Supabase Auth UUID with a default workspace.
 * Tag- or source-type-filtered ``add_members`` requests intentionally fall
   back to the v1 path because the v2 ``bulk_add_to_kasten`` RPC only accepts
   an explicit ``workspace_zettel_id`` array.
 * Kasten member-sharing (inviting other workspaces to a kasten via
   ``rag.kasten_members``) is wired through the v2-only POST /share endpoint
   (Phase 7.2-deferred). RLS on ``rag.kastens`` + ``rag.kasten_zettels`` is
   extended through the ``kasten_members`` join in ``_v2/29``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, model_validator

from website.api._async_ops import (
    accept_and_spawn,
    render_operation_status,
)
from website.api._problem import _problem_dict
from website.api.auth import get_current_user
from website.api.module_runners.create_kasten import (
    IdempotencyConflict,
    run_create_kasten_pipeline,
)
from website.core import operations_repo
from website.core.db_version import use_supabase_v2
from website.core.persist import get_supabase_v2_scope
from website.core.request_context import operation_context
from website.core.supabase_v2.repositories.rag_repository import RAGRepository as V2RAGRepository
from website.features.functional_gates.async_backpressure import (
    check_async_backpressure,
)
from website.features.rag_pipeline.service import get_rag_runtime
from website.features.rag_pipeline.types import SourceType
from website.features.user_pricing.entitlements import require_entitlement
from website.features.user_pricing.models import Meter

logger = logging.getLogger("website.api.sandbox_routes")

router = APIRouter(prefix="/api/rag", tags=["rag-sandboxes"])

# ─────────────────────────────────────────────────────────────────────────
# Async create-Kasten machinery (D3 + D4 + gap punch-list, locked 2026-05-23).
#
# Replaces the per-process _KASTEN_OPERATIONS in-memory store with the
# DB-backed core.operations row (cross-worker source of truth via
# operations_repo). _LIVE_TASKS_KASTEN is the per-process strong-ref + cancel
# target so the worker coroutine is not GC'd by the event loop and DELETE
# /api/rag/sandboxes/operations/{id} can cooperatively cancel it.
#
# Generic accept / worker / poll-status machinery lives in
# website.api._async_ops (shared with /api/operations/{id}); this module
# supplies only the kasten-specific failure mapper.
# ─────────────────────────────────────────────────────────────────────────

_KASTEN_POLL_URL_BASE = "/api/rag/sandboxes/operations"
_LIVE_TASKS_KASTEN: dict[str, asyncio.Task] = {}


def _kasten_failure_mapper(
    exc: BaseException, operation_id: str
) -> dict[str, Any]:
    """Shape a kasten-build exception into the failed-state envelope body.

    Mirrors ``zettels_routes._failed_response_for`` — HTTPException,
    IdempotencyConflict, ValueError, and CancelledError get specific
    titles/type_slugs/status codes; everything else falls back to a generic
    build-failed envelope. The body's ``error`` field is the RFC 9457
    problem+json dict the frontend keys off (``err.detail.code``).
    """
    instance = f"{_KASTEN_POLL_URL_BASE}/{operation_id}"

    if isinstance(exc, asyncio.CancelledError):
        return {
            "status": "failed",
            "operation_id": operation_id,
            "error": _problem_dict(
                status_code=499,
                title="Operation cancelled",
                detail="The operation was cancelled by the client.",
                type_slug="operation_cancelled",
                operation_id=operation_id,
                instance=instance,
            ),
        }
    if isinstance(exc, IdempotencyConflict):
        return {
            "status": "failed",
            "operation_id": operation_id,
            "error": _problem_dict(
                status_code=409,
                title="Idempotency conflict",
                detail=(
                    "client_action_id reused with a different request body "
                    "on the same worker."
                ),
                type_slug="idempotency-conflict",
                operation_id=operation_id,
                instance=instance,
            ),
        }
    if isinstance(exc, HTTPException):
        detail = exc.detail
        title = "Create Kasten request rejected"
        type_slug = "request-rejected"
        if isinstance(detail, dict):
            title = str(detail.get("message") or detail.get("error") or title)
            if detail.get("code") == "quota_exhausted":
                type_slug = "quota-exhausted"
        return {
            "status": "failed",
            "operation_id": operation_id,
            "error": _problem_dict(
                status_code=exc.status_code,
                title=title,
                detail=detail,
                type_slug=type_slug,
                operation_id=operation_id,
                instance=instance,
            ),
        }
    if isinstance(exc, ValueError):
        return {
            "status": "failed",
            "operation_id": operation_id,
            "error": _problem_dict(
                status_code=422,
                title="Invalid Create Kasten request",
                detail=str(exc),
                type_slug="invalid-create-kasten",
                operation_id=operation_id,
                instance=instance,
            ),
        }
    return {
        "status": "failed",
        "operation_id": operation_id,
        "error": _problem_dict(
            status_code=500,
            title="Create Kasten failed",
            detail=str(exc) or exc.__class__.__name__,
            type_slug="create-kasten-failed",
            operation_id=operation_id,
            instance=instance,
        ),
    }


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _v2_scope_for(user: dict) -> tuple[V2RAGRepository, UUID, UUID] | None:
    """Return ``(rag_repo, profile_id, workspace_id)`` when v2 dual-path applies.

    Phase 4.4 dual-path gate: requires DB v2 ON + UUID auth subject + a default
    workspace via the standard ``get_supabase_v2_scope`` lookup. Returns None
    otherwise so callers fall back to the legacy v1 path unchanged.
    """
    if not use_supabase_v2() or user is None:
        return None
    if not _is_uuid(user.get("sub")):
        return None
    scope = get_supabase_v2_scope(user["sub"])
    if scope is None:
        return None
    _content_repo, profile_id, workspace_id = scope
    return V2RAGRepository(), profile_id, workspace_id


def _resolve_caller_workspace_for_kasten(
    user: dict, kasten_id: UUID
) -> tuple[V2RAGRepository, UUID]:
    """Resolve caller's workspace_id and assert kasten ownership.

    BOLA-mitigation helper used by the kasten member-mutation endpoints
    (remove_member, bulk_remove_members). The auth subject's default
    workspace is treated as the caller's acting workspace; ownership is
    proven by ``rag_repo.get_kasten`` (workspace_id-keyed read returns None
    when the workspace does not own the kasten — equivalent to the share
    handler's ownership check). Raises 403 in any failure mode so the
    response cannot reveal whether the kasten exists in another tenant.

    Returns ``(rag_repo, workspace_id)`` on success.
    """
    scope = _v2_scope_for(user)
    if scope is None:
        # Caller has no v2 workspace; the v2-only delete paths cannot proceed
        # safely. 403 (vs. 404) keeps the response identical for "kasten does
        # not exist" and "caller is not the owner" — the share handler uses
        # the same conservative pattern.
        raise HTTPException(status_code=403, detail="Forbidden")
    rag_repo, _profile_id, workspace_id = scope
    if rag_repo.get_kasten(kasten_id, workspace_id) is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    return rag_repo, workspace_id


def _serialize_kasten_zettel_v2(row: dict) -> dict:
    """Map a row from ``rag.list_kasten_zettels`` RPC into the legacy member shape.

    The RPC returns a JOIN of workspace_zettels + canonical_zettels; the v1
    client surface expects ``{node_id, added_via, added_filter, added_at, node:{...}}``
    so we reshape conservatively. Any column the RPC doesn't return defaults to
    a safe empty value rather than a 500.
    """
    wz_id = str(row.get("workspace_zettel_id") or row.get("id") or "")
    return {
        "node_id": wz_id,
        "added_via": row.get("added_via") or "manual",
        "added_filter": row.get("added_filter") or {},
        "added_at": row.get("added_at"),
        "node": {
            "id": wz_id,
            "name": row.get("title") or wz_id,
            "source_type": row.get("source_type") or "web",
            "url": row.get("normalized_url") or row.get("url") or "",
            "summary": row.get("ai_summary") or row.get("summary") or "",
            "tags": row.get("user_tags") or row.get("tags") or [],
            "node_date": row.get("publication_date") or row.get("node_date"),
        },
    }


def _serialize_kasten_v2(row: dict) -> dict:
    """Serialise a ``rag.kastens`` row in the legacy sandbox shape.

    Member count is not part of the v2 row — it is computed lazily by
    :func:`_kasten_member_count_v2` only when the response shape requires it
    (the list endpoint surfaces ``member_count`` in the UI).
    """
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row.get("description") or "",
        "icon": row.get("icon") or "stack",
        "color": row.get("color") or "#14b8a6",
        "default_quality": row.get("default_quality", "fast"),
        "member_count": row.get("member_count", 0),
        "last_used_at": row.get("last_used_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


class SandboxCreateRequest(BaseModel):
    """Consolidated Create-Kasten request (new_apis1.md reconciliation).

    ``selection_mode`` is the explicit membership-resolution mode:

    * ``all``: every workspace_zettel the caller owns.
    * ``source``: overlays whose source_type is in ``source_types``.
    * ``specific``: caller-supplied ``workspace_zettel_ids``.
    * ``links``: ingest each URL through Add Zettel pipeline.
    * ``mixed``: any combination of links + source_types + workspace_zettel_ids.

    Backward compatible: if ``selection_mode`` is omitted the runner infers
    it from the non-empty input list(s). ``links`` defaulting to ``[]`` keeps
    the legacy create-only response shape byte-identical for existing callers.
    """

    name: str
    description: str | None = None
    icon: str | None = "stack"
    color: str | None = "#14b8a6"
    default_quality: str = "fast"
    client_action_id: str | None = None
    # Phase C (D1): optional link list. Empty (the default) → create-only,
    # response byte-identical to the legacy create_sandbox. Non-empty → the
    # consolidated runner ingests each link through the Add Zettel pipeline
    # (async + poll, D3). Backward compatible: existing callers omit it.
    links: list[str] = []
    # new_apis_1a (locked 2026-05-23): explicit selection enum + auxiliary
    # input lists. None = back-compat inference (route bypasses the async
    # runner for all-empty inputs, mirroring the legacy create-only behaviour).
    selection_mode: Literal["all", "source", "specific", "links", "mixed"] | None = None
    source_types: list[SourceType] = []
    workspace_zettel_ids: list[UUID] = []

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        if len(cleaned) > 80:
            raise ValueError("name is too long")
        return cleaned

    @field_validator("default_quality")
    @classmethod
    def validate_quality(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"fast", "high"}:
            raise ValueError("default_quality must be fast or high")
        return normalized

    @field_validator("links")
    @classmethod
    def validate_links(cls, value: list[str]) -> list[str]:
        # Same URL validation Add Zettel applies (AddZettelRequest.validate_url
        # field): scheme allow-list + length cap + SSRF-blocking validate_url.
        # Lazy import keeps url_utils out of module import time.
        from website.core.url_utils import validate_url

        cleaned: list[str] = []
        for raw in value or []:
            link = (raw or "").strip()
            if not link:
                raise ValueError("links must not contain empty entries")
            if len(link) > 2048:
                raise ValueError("URL too long (max 2048 characters)")
            if not link.startswith(("http://", "https://")):
                raise ValueError("URL must start with http:// or https://")
            if not validate_url(link):
                raise ValueError(f"URL is invalid or blocked: {link}")
            cleaned.append(link)
        return cleaned

    @model_validator(mode="after")
    def _validate_selection(self) -> "SandboxCreateRequest":
        """Per-mode constraint check (new_apis1.md spec).

        Aggregates field-level errors into a single ValueError whose message
        encodes each violation; the route layer catches and emits RFC 9457
        problem+json with the ``errors[]`` extension (one entry per field).
        """
        # When selection_mode is omitted AND every input list is empty, this
        # is the legacy create-only path — pass through; the route returns the
        # byte-identical legacy response without invoking the async runner.
        if self.selection_mode is None and not (
            self.links or self.source_types or self.workspace_zettel_ids
        ):
            return self

        # Otherwise infer mode the same way the runner does for back-compat.
        from website.api.module_runners.create_kasten import (
            _normalize_selection_mode,
            _validate_selection_payload,
        )

        resolved = _normalize_selection_mode(
            selection_mode=self.selection_mode,
            links=self.links,
            source_types=[s.value for s in self.source_types],
            workspace_zettel_ids=[str(wz) for wz in self.workspace_zettel_ids],
        )
        errors = _validate_selection_payload(
            selection_mode=resolved,
            links=self.links,
            source_types=[s.value for s in self.source_types],
            workspace_zettel_ids=[str(wz) for wz in self.workspace_zettel_ids],
        )
        if errors:
            details = "; ".join(
                f"{err['field']}: {err['detail']}" for err in errors
            )
            raise ValueError(
                f"Invalid selection payload for mode={resolved}: {details}"
            )
        return self


class SandboxUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    default_quality: str | None = None


class KastenShareRequest(BaseModel):
    """Request body for POST /api/rag/sandboxes/{id}/share — v2 kasten member-sharing.

    Phase 7.2-deferred: workspace-keyed sharing (rag.kasten_members is keyed
    by workspace_id, not profile_id, per the v2 design — sharing a kasten with
    another tenant means adding their workspace as a member). Defaults role to
    'viewer' if omitted.
    """

    workspace_id: UUID
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"viewer", "editor", "owner"}:
            raise ValueError("role must be viewer, editor, or owner")
        return normalized


class SandboxMemberAddRequest(BaseModel):
    node_ids: list[str] | None = None
    tags: list[str] | None = None
    tag_mode: str = "all"
    source_types: list[SourceType] | None = None
    added_via: str = "manual"

    @field_validator("tag_mode")
    @classmethod
    def validate_tag_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"all", "any"}:
            raise ValueError("tag_mode must be all or any")
        return normalized


class SandboxMemberRemoveRequest(BaseModel):
    node_ids: list[str] | None = None
    tags: list[str] | None = None
    tag_mode: str = "all"
    source_types: list[SourceType] | None = None

    @field_validator("tag_mode")
    @classmethod
    def validate_tag_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"all", "any"}:
            raise ValueError("tag_mode must be all or any")
        return normalized


def _kasten_request_hash(body: SandboxCreateRequest) -> str:
    """Stable sha256 over the semantically-significant request fields.

    Includes selection_mode + source_types + workspace_zettel_ids alongside
    name/description/icon/color/default_quality/links so a re-submit that
    changes the selection (e.g. same name, different source filter) is
    correctly detected as a different request by the route-level cross-
    worker pre-check before operations_repo.accept.
    """
    import hashlib
    import json

    fingerprint = {
        "name": body.name,
        "description": body.description or "",
        "icon": body.icon or "stack",
        "color": body.color or "#14b8a6",
        "default_quality": body.default_quality,
        "links": list(body.links),
        "selection_mode": body.selection_mode,
        "source_types": sorted(s.value for s in body.source_types),
        "workspace_zettel_ids": sorted(str(wz) for wz in body.workspace_zettel_ids),
    }
    encoded = json.dumps(
        fingerprint, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_for_user(user: dict):
    try:
        return get_rag_runtime(user["sub"])
    except Exception as exc:
        logger.warning("Sandbox runtime unavailable for %s: %s", user.get("sub"), exc)
        raise HTTPException(status_code=503, detail="RAG runtime is not available")


def _serialize_sandbox(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "icon": row.get("icon") or "stack",
        "color": row.get("color") or "#14b8a6",
        "default_quality": row.get("default_quality", "fast"),
        "member_count": row.get("member_count", 0),
        "last_used_at": row.get("last_used_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _serialize_member(row: dict) -> dict:
    # v2 shape: rag.list_kasten_zettels returns a flat row with
    # workspace_zettel_id, canonical_zettel_id, title, source_type,
    # user_tags, ai_summary, added_at. The legacy nested ``kg_nodes``
    # embed (Phase 8.0 H9) is gone; map flat columns into the
    # response envelope clients still expect.
    member_id = row.get("workspace_zettel_id") or row.get("node_id") or ""
    return {
        "node_id": member_id,
        "added_via": row.get("added_via", "manual"),
        "added_filter": row.get("added_filter") or {},
        "added_at": row.get("added_at"),
        "node": {
            "id": member_id,
            "name": row.get("title") or member_id,
            "source_type": row.get("source_type") or "web",
            "url": row.get("url") or "",
            "summary": row.get("ai_summary") or "",
            "tags": row.get("user_tags") or [],
            "node_date": row.get("node_date"),
        },
    }


def _serialize_node(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "source_type": row.source_type,
        "summary": row.summary,
        "tags": row.tags,
        "url": row.url,
        "node_date": str(row.node_date or ""),
    }


def _member_matches_filters(row: dict, body: SandboxMemberRemoveRequest) -> bool:
    # v2: rag.list_kasten_zettels returns flat columns; the legacy
    # nested ``kg_nodes`` embed (Phase 8.0 H9) is gone. Filters now
    # match against workspace_zettel_id, user_tags, source_type
    # directly off the row.
    member_id = row.get("workspace_zettel_id") or row.get("node_id")
    if body.node_ids and member_id not in body.node_ids:
        return False

    node_tags = {tag.lower() for tag in row.get("user_tags") or []}
    requested_tags = [tag.lower() for tag in body.tags or []]
    if requested_tags:
        if body.tag_mode == "all":
            if not all(tag in node_tags for tag in requested_tags):
                return False
        elif not any(tag in node_tags for tag in requested_tags):
            return False

    if body.source_types:
        allowed = {item.value for item in body.source_types}
        if (row.get("source_type") or "").lower() not in allowed:
            return False

    return True


@router.get("/nodes")
async def list_user_nodes(
    user: Annotated[dict, Depends(get_current_user)],
    query: str | None = None,
    tags: list[str] = Query(default=[]),
    source_types: list[SourceType] = Query(default=[]),
    limit: int = 100,
    offset: int = 0,
):
    runtime = _runtime_for_user(user)
    rows = runtime.repo.search_nodes(
        runtime.kg_user_id,
        query=query,
        tags=tags or None,
        source_types=[item.value for item in source_types] or None,
        limit=limit,
        offset=offset,
    )
    return {"nodes": [_serialize_node(row) for row in rows]}


@router.get("/sandboxes")
async def list_sandboxes(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = 50,
):
    # Phase 4.4 v2 dual-path: read kastens from rag.kastens scoped to the
    # authenticated user's default workspace.
    v2 = _v2_scope_for(user)
    if v2 is not None:
        rag_repo, _profile_id, workspace_id = v2
        try:
            rows = rag_repo.list_kastens(workspace_id, limit=limit)
            return {"sandboxes": [_serialize_kasten_v2(row) for row in rows]}
        except Exception as exc:  # noqa: BLE001 — surface to logs, fall back to v1
            logger.warning("v2 list_kastens failed, falling back to v1: %s", exc)

    runtime = _runtime_for_user(user)
    rows = await runtime.sandboxes.list_sandboxes(runtime.kg_user_id, limit=limit)
    return {"sandboxes": [_serialize_sandbox(row) for row in rows]}


@router.post("/sandboxes")
async def create_sandbox(
    body: SandboxCreateRequest,
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
):
    action_id = body.client_action_id or body.name

    # Determine whether this submission populates membership at all. The
    # legacy create-only path stays byte-identical for the all-empty
    # default; any non-empty input list flips us into the async runner.
    has_members = bool(
        body.links or body.source_types or body.workspace_zettel_ids
    )
    explicit_async = body.selection_mode is not None

    # ── Phase C (D1 + D3 + new_apis_1a): membership present → async runner ─
    # All non-trivial selection modes require a resolvable DB v2 workspace
    # scope (the runner reads + writes via v2 repos exclusively); without
    # one, a clear 501 is correct rather than a misleading v1 fall-through.
    if (has_members or explicit_async) and get_supabase_v2_scope(user.get("sub")) is None:
        raise HTTPException(
            status_code=501,
            detail="Populating a Kasten with members requires DB v2",
        )

    # Single Meter.KASTEN charge — exactly like the legacy path (one call,
    # same args). Per-link Meter.ZETTEL is enforced INSIDE
    # run_add_zettel_pipeline (not here) so links never double-charge.
    await require_entitlement(Meter.KASTEN, user, action_id=action_id)

    if has_members or explicit_async:
        effective_user_id = UUID(str(user["sub"]))

        # Per-user backpressure: shed beyond the per-user in-flight cap with
        # a 429 + Retry-After (same gate the Add Zettel path uses). Runs
        # BEFORE the accept RPC so a backpressured user never even occupies
        # an ops row.
        backpressure_response = await check_async_backpressure(
            user_id=effective_user_id
        )
        if backpressure_response is not None:
            return backpressure_response

        # Honor IETF-draft Idempotency-Key header as the canonical op id
        # when present; fall back to client_action_id, then to a fresh uuid.
        # The header takes precedence so a client retrying with the same key
        # gets the same canonical op even if it omitted client_action_id.
        idempotency_header = (request.headers.get("Idempotency-Key") or "").strip()
        operation_id = (
            idempotency_header
            or body.client_action_id
            or uuid4().hex
        )
        # URL-encode the op id for the Location/status_url path segment —
        # client-supplied values may include reserved characters.
        op_path = quote(operation_id, safe="")
        request_hash = _kasten_request_hash(body)

        # Pre-check for same-key-different-body across workers (replaces the
        # runner-level result cache dropped in D4). The DB has no unique
        # constraint on (user_id, operation_id) — only on (user_id,
        # request_hash) — so without this check a retry with the SAME op id
        # but DIFFERENT body would silently insert a parallel row. Surface
        # the conflict as 409 the same way the runner's IdempotencyConflict
        # used to (now only fires for same-worker concurrent races).
        existing_row = await asyncio.to_thread(
            operations_repo.get_operation,
            user_id=effective_user_id,
            operation_id=operation_id,
        )
        if existing_row is not None:
            existing_hash = ""
            existing_body = existing_row.get("response")
            if isinstance(existing_body, dict):
                existing_hash = str(
                    existing_body.get("request_hash") or ""
                )
            if existing_hash and existing_hash != request_hash:
                body_err = _problem_dict(
                    status_code=409,
                    title="Idempotency conflict",
                    detail=(
                        "operation_id reused with a different request body."
                    ),
                    type_slug="idempotency-conflict",
                    operation_id=operation_id,
                    instance=f"{_KASTEN_POLL_URL_BASE}/{op_path}",
                )
                return JSONResponse(
                    body_err,
                    status_code=409,
                    media_type="application/problem+json",
                )

        accept_body = {
            "status": "accepted",
            "operation_id": operation_id,
            "status_url": f"{_KASTEN_POLL_URL_BASE}/{op_path}",
            # Carry the request_hash inside the accept_body so future cross-
            # worker pre-checks (above) can detect same-key-different-body
            # without a separate column.
            "request_hash": request_hash,
        }

        async def _pipeline() -> dict[str, Any]:
            return await run_create_kasten_pipeline(
                name=body.name,
                user=user,
                effective_user_id=effective_user_id,
                client_action_id=operation_id,
                links=body.links,
                selection_mode=body.selection_mode,
                source_types=[s.value for s in body.source_types],
                workspace_zettel_ids=[str(wz) for wz in body.workspace_zettel_ids],
                description=body.description or "",
                icon=body.icon or "stack",
                color=body.color or "#14b8a6",
                default_quality=body.default_quality,
                persist=True,
                # HTTP background path: don't drain the PROCESS-WIDE
                # enrichment queue (would couple this op to unrelated
                # traffic). Only short-lived CLI callers need the drain.
                drain_enrichment=False,
            )

        return await accept_and_spawn(
            user_id=effective_user_id,
            operation_id=operation_id,
            request_hash=request_hash,
            accept_body=accept_body,
            pipeline=_pipeline,
            failure_mapper=_kasten_failure_mapper,
            poll_url_base=_KASTEN_POLL_URL_BASE,
            live_tasks=_LIVE_TASKS_KASTEN,
            operation_context_cm=operation_context,
        )

    # Phase 4.4 v2 dual-path: write to rag.kastens via the v2 RAGRepository.
    # The repo does not accept owner_profile_id — the workspace_id IS the
    # tenancy boundary; kasten ownership is handled at the schema layer.
    v2 = _v2_scope_for(user)
    if v2 is not None:
        rag_repo, _profile_id, workspace_id = v2
        try:
            row = rag_repo.create_kasten(
                workspace_id=workspace_id,
                name=body.name,
                description=body.description,
                icon=body.icon,
                color=body.color,
                default_quality=body.default_quality,
            )
        except Exception as exc:  # noqa: BLE001 — surface real driver error to logs + client
            detail_str = str(exc)
            logger.exception(
                "v2 create_kasten failed for workspace=%s name=%s: %s",
                workspace_id,
                body.name,
                detail_str,
            )
            lower = detail_str.lower()
            if "duplicate key" in lower or "unique" in lower:
                raise HTTPException(status_code=409, detail="A kasten with that name already exists") from exc
            raise HTTPException(status_code=500, detail="Create sandbox failed. Please try again.") from exc

        if row is None:
            logger.error("v2 create_kasten returned None for workspace=%s name=%s", workspace_id, body.name)
            raise HTTPException(status_code=500, detail="Create sandbox returned no row")

        # Phase 9: gate consumed atomically in require_entitlement above.
        return {"sandbox": _serialize_kasten_v2(row)}

    # new_apis_1b (operator decision A, locked 2026-05-23): the v1
    # sandbox-store fallback (``runtime.sandboxes.create_sandbox``) has
    # been removed — DB v2 is the only supported creation path. Without
    # a resolvable v2 scope we surface a clear 501 (matching the
    # create-with-members branch above) instead of falling through to
    # the retired v1 store.
    raise HTTPException(
        status_code=501,
        detail="Creating a Kasten requires DB v2",
    )


@router.get("/sandboxes/operations/{operation_id}")
async def create_kasten_operation_status(
    operation_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Poll a create-Kasten-with-members operation (D3).

    Reads from the DB-backed ``core.operations`` row (single source of
    truth across workers). Active states return 202 + Retry-After tuned to
    operation age; terminal succeeded/failed/cancelled return 200 + ETag +
    private cache-control; expired returns 410 + RFC 9457 envelope.

    SECURITY: ``operations_repo.get_operation`` filters on
    ``(user_id, operation_id)`` — a foreign id resolves to None →
    transient 202 pending (cross-worker replication gap), never a cross-
    tenant payload read.
    """
    return await render_operation_status(
        operation_id=operation_id,
        user_id=UUID(str(user["sub"])),
        poll_url_base=_KASTEN_POLL_URL_BASE,
        expired_instance=f"{_KASTEN_POLL_URL_BASE}/{operation_id}",
    )


@router.delete("/sandboxes/operations/{operation_id}")
async def cancel_create_kasten_operation(
    operation_id: str,
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Cooperative cancellation for a create-Kasten async op.

    Mirrors ``zettels_routes.cancel_operation``:

    * **Auth model** — caller must be authenticated AND must supply an
      ``Idempotency-Key`` header that EXACTLY matches the path
      ``operation_id``. This is client-action-id-bound auth: only the
      originating client (which minted and remembers the op_id at POST
      time) can cancel. Defense-in-depth on top of the user_id scoping
      inside the RPC.
    * **Behaviour** — flips the DB row to ``cancelled`` via the state-
      guarded RPC. Does NOT hard-cancel the in-flight asyncio task; the
      persist phase is shielded and CancelledError mid-PostgREST risks
      partial writes. Letting the task finish naturally is bounded by
      GUNICORN_TIMEOUT; its eventual ``finalize(succeeded)`` is a no-op
      because ``ops_finalize`` only matches active states.

    Caller attribution headers are logged so future phantom DELETEs are
    traceable.
    """
    effective_user_id = UUID(str(user["sub"]))
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
        "cancel_create_kasten_operation caller-attribution op=%s user=%s %s",
        operation_id,
        effective_user_id,
        attribution,
    )

    idem = h.get("idempotency-key")
    if not idem or idem != operation_id:
        logger.warning(
            "cancel_create_kasten_operation rejected: idempotency-key "
            "mismatch op=%s key=%r",
            operation_id,
            idem,
        )
        body = _problem_dict(
            status_code=403,
            title="Forbidden",
            detail=(
                "DELETE /api/rag/sandboxes/operations/{id} requires the "
                "Idempotency-Key header to match the path operation_id "
                "(client-action-id-bound cancellation)."
            ),
            type_slug="operation_cancel_idempotency_mismatch",
            operation_id=operation_id,
            instance=f"{_KASTEN_POLL_URL_BASE}/{operation_id}",
        )
        return JSONResponse(
            body,
            status_code=403,
            media_type="application/problem+json",
        )

    try:
        cancelled = await asyncio.to_thread(
            operations_repo.cancel,
            user_id=effective_user_id,
            operation_id=operation_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "operations_repo.cancel raised in cancel_create_kasten_operation "
            "(op=%s)",
            operation_id,
        )
        cancelled = False

    local_task = _LIVE_TASKS_KASTEN.get(operation_id)
    if local_task is not None and not local_task.done():
        logger.info(
            "cancel_create_kasten_operation: in-flight task left running "
            "(shielded persist) op=%s",
            operation_id,
        )

    return JSONResponse(
        {
            "status": "cancelled" if cancelled else "noop",
            "operation_id": operation_id,
        },
        status_code=200,
    )


@router.get("/sandboxes/{sandbox_id}")
async def get_sandbox(
    sandbox_id: UUID,
    user: Annotated[dict, Depends(get_current_user)],
):
    runtime = _runtime_for_user(user)
    row = await runtime.sandboxes.get_sandbox(sandbox_id, runtime.kg_user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    members = await runtime.sandboxes.list_members(sandbox_id, runtime.kg_user_id)
    return {
        "sandbox": _serialize_sandbox(row),
        "members": [_serialize_member(member) for member in members],
    }


@router.get("/sandboxes/{sandbox_id}/members")
async def list_members(
    sandbox_id: UUID,
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = 500,
):
    # Phase 4.4 v2 dual-path: list zettels via rag.list_kasten_zettels RPC.
    v2 = _v2_scope_for(user)
    if v2 is not None:
        rag_repo, _profile_id, workspace_id = v2
        try:
            kasten = rag_repo.get_kasten(sandbox_id, workspace_id)
            if kasten is None:
                raise HTTPException(status_code=404, detail="Sandbox not found")
            rows = rag_repo.list_kasten_zettels(sandbox_id)
            return {"members": [_serialize_kasten_zettel_v2(row) for row in rows]}
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — surface to logs, fall back to v1
            logger.warning("v2 list_kasten_zettels failed, falling back to v1: %s", exc)

    runtime = _runtime_for_user(user)
    sandbox = await runtime.sandboxes.get_sandbox(sandbox_id, runtime.kg_user_id)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    members = await runtime.sandboxes.list_members(sandbox_id, runtime.kg_user_id, limit=limit)
    return {"members": [_serialize_member(member) for member in members]}


@router.patch("/sandboxes/{sandbox_id}")
async def update_sandbox(
    sandbox_id: UUID,
    body: SandboxUpdateRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    runtime = _runtime_for_user(user)
    row = await runtime.sandboxes.update_sandbox(
        sandbox_id,
        runtime.kg_user_id,
        name=body.name,
        description=body.description,
        icon=body.icon,
        color=body.color,
        default_quality=body.default_quality,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return {"sandbox": _serialize_sandbox(row)}


@router.delete("/sandboxes/{sandbox_id}")
async def delete_sandbox(
    sandbox_id: UUID,
    user: Annotated[dict, Depends(get_current_user)],
):
    # Phase 4.4 v2 dual-path: delete from rag.kastens scoped to workspace_id;
    # cascading FKs in the schema clean up rag.kasten_zettels / kasten_members.
    v2 = _v2_scope_for(user)
    if v2 is not None:
        rag_repo, _profile_id, workspace_id = v2
        try:
            deleted = rag_repo.delete_kasten(sandbox_id, workspace_id)
        except Exception as exc:  # noqa: BLE001 — surface to logs, fall back to v1
            logger.warning("v2 delete_kasten failed, falling back to v1: %s", exc)
        else:
            if not deleted:
                raise HTTPException(status_code=404, detail="Sandbox not found")
            return {"status": "ok", "sandbox_id": str(sandbox_id)}

    runtime = _runtime_for_user(user)
    deleted = await runtime.sandboxes.delete_sandbox(sandbox_id, runtime.kg_user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return {"status": "ok", "sandbox_id": str(sandbox_id)}


@router.post("/sandboxes/{sandbox_id}/share")
async def share_kasten(
    sandbox_id: UUID,
    body: KastenShareRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Add a recipient workspace as a member of a kasten (v2-only).

    Phase 7.2-deferred (closes the deferral from Phase 4.4): kasten member-
    sharing routes through ``rag.kasten_members``. The granter must be acting
    from a workspace that holds the kasten's owner row — enforced by the
    ``rag.assert_kasten_owner_can_grant`` trigger; recipient SELECT access is
    granted by the ``kastens_member_or_owner_select`` /
    ``kasten_zettels_member_or_owner_select`` policies in ``_v2/29``.
    """
    v2 = _v2_scope_for(user)
    if v2 is None:
        # v2-only feature (workspace-keyed sharing has no v1 equivalent — v1
        # rag_sandbox_members was profile-keyed). Surface a clear 501 rather
        # than a misleading fall-through to a non-existent v1 path.
        raise HTTPException(
            status_code=501,
            detail="Kasten sharing requires DB v2",
        )
    rag_repo, _profile_id, workspace_id = v2
    kasten = rag_repo.get_kasten(sandbox_id, workspace_id)
    if kasten is None:
        # 404 covers both 'kasten does not exist' and 'caller's workspace does
        # not own the kasten'. Either way, the caller cannot grant.
        raise HTTPException(status_code=404, detail="Sandbox not found")
    try:
        rag_repo.add_kasten_member(
            kasten_id=sandbox_id,
            workspace_id=body.workspace_id,
            role=body.role,
        )
    except Exception as exc:  # noqa: BLE001 — surface real driver error to logs + client
        logger.exception(
            "v2 add_kasten_member failed for kasten=%s recipient_workspace=%s role=%s: %s",
            sandbox_id,
            body.workspace_id,
            body.role,
            exc,
        )
        # The trigger raises 'only kasten owners can grant memberships' (P0001)
        # for non-owner granters; surface as 403 so callers can distinguish
        # auth failures from generic 500s.
        msg = str(exc).lower()
        if "only kasten owners" in msg or "p0001" in msg:
            raise HTTPException(status_code=403, detail="Only kasten owners can grant memberships") from exc
        raise HTTPException(status_code=500, detail="Share kasten failed.") from exc
    return {
        "status": "ok",
        "kasten_id": str(sandbox_id),
        "workspace_id": str(body.workspace_id),
        "role": body.role,
    }


@router.post("/sandboxes/{sandbox_id}/members")
async def add_members(
    sandbox_id: UUID,
    body: SandboxMemberAddRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    # Phase 4.4 v2 dual-path: branches on the input shape.
    #   * EXPLICIT node_ids — pass straight to bulk_add_to_kasten.
    #   * source_types only — server-side resolve to workspace_zettel_ids
    #     (necessary because PR #63 retired the v1 sandbox-store create path;
    #     a freshly-created Kasten lives ONLY in rag.kastens, so the v1
    #     fallback's `runtime.sandboxes.get_sandbox(...)` returns None and
    #     yields a 404 even though the row exists. Closes the 2026-05-23
    #     incident where /home create-kasten "All" flow lost members.)
    # The "tags" filter still falls back to v1; resolving tag set semantics
    # via v2 is a follow-up.
    v2 = _v2_scope_for(user)
    use_v2_explicit_ids = (
        v2 is not None
        and bool(body.node_ids)
        and not body.tags
        and not body.source_types
        and all(_is_uuid(nid) for nid in body.node_ids)
    )
    use_v2_source_types = (
        v2 is not None
        and not body.node_ids
        and not body.tags
        and bool(body.source_types)
    )
    if use_v2_explicit_ids:
        rag_repo, _profile_id, workspace_id = v2  # type: ignore[misc]
        kasten = rag_repo.get_kasten(sandbox_id, workspace_id)
        if kasten is None:
            raise HTTPException(status_code=404, detail="Sandbox not found")
        try:
            wz_ids = [UUID(nid) for nid in body.node_ids]
            added = rag_repo.add_zettels_to_kasten(
                kasten_id=sandbox_id,
                workspace_zettel_ids=wz_ids,
            )
        except Exception as exc:  # noqa: BLE001 — surface real driver error to logs + client
            logger.exception(
                "v2 bulk_add_to_kasten failed for kasten=%s workspace=%s: %s",
                sandbox_id,
                workspace_id,
                exc,
            )
            raise HTTPException(status_code=500, detail="Add to kasten failed.") from exc
        rows = rag_repo.list_kasten_zettels(sandbox_id)
        return {
            "status": "ok",
            "added_count": added,
            "members": [_serialize_kasten_zettel_v2(row) for row in rows],
        }

    if use_v2_source_types:
        from website.core.supabase_v2.repositories.content_repository import (
            ContentRepository,
        )

        rag_repo, _profile_id, workspace_id = v2  # type: ignore[misc]
        kasten = rag_repo.get_kasten(sandbox_id, workspace_id)
        if kasten is None:
            raise HTTPException(status_code=404, detail="Sandbox not found")
        content_repo = ContentRepository()
        # 5000-row cap is the existing list_workspace_zettels default; matches
        # the scale target for a single-workspace bulk-add (10k+ Zettels would
        # need pagination — file an issue when a tenant approaches that).
        rows_all = content_repo.list_workspace_zettels(workspace_id, limit=5000)
        wanted = {item.value for item in body.source_types}
        wz_ids = [
            UUID(row["id"])
            for row in rows_all
            if (row.get("canonical") or {}).get("source_type") in wanted
            and row.get("id")
        ]
        if not wz_ids:
            members = rag_repo.list_kasten_zettels(sandbox_id)
            return {
                "status": "ok",
                "added_count": 0,
                "members": [_serialize_kasten_zettel_v2(row) for row in members],
            }
        try:
            added = rag_repo.add_zettels_to_kasten(
                kasten_id=sandbox_id,
                workspace_zettel_ids=wz_ids,
            )
        except Exception as exc:  # noqa: BLE001 — surface real driver error to logs + client
            logger.exception(
                "v2 bulk_add_to_kasten (source_types) failed kasten=%s workspace=%s: %s",
                sandbox_id,
                workspace_id,
                exc,
            )
            raise HTTPException(status_code=500, detail="Add to kasten failed.") from exc
        members = rag_repo.list_kasten_zettels(sandbox_id)
        return {
            "status": "ok",
            "added_count": added,
            "members": [_serialize_kasten_zettel_v2(row) for row in members],
        }

    runtime = _runtime_for_user(user)
    sandbox = await runtime.sandboxes.get_sandbox(sandbox_id, runtime.kg_user_id)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    added = await runtime.sandboxes.add_members(
        sandbox_id=sandbox_id,
        user_id=runtime.kg_user_id,
        node_ids=body.node_ids,
        tags=body.tags,
        tag_mode=body.tag_mode,
        source_types=[item.value for item in body.source_types] if body.source_types else None,
        added_via=body.added_via,
    )
    # Post-iter-06 guard: when the caller passes explicit node_ids, every id
    # must land in rag_sandbox_members. A short count signals the silent-no-op
    # regression fixed by 2026-04-26_fix_rag_bulk_add_to_sandbox.sql.
    if body.node_ids:
        requested_node_ids = body.node_ids
        if added != len(requested_node_ids):
            raise HTTPException(
                500,
                detail=f"Sandbox bulk-add silently dropped rows: requested={len(requested_node_ids)} added={added}",
            )
    members = await runtime.sandboxes.list_members(sandbox_id, runtime.kg_user_id)
    return {
        "status": "ok",
        "added_count": added,
        "members": [_serialize_member(member) for member in members],
    }


@router.delete("/sandboxes/{sandbox_id}/members/{node_id}")
async def remove_member(
    sandbox_id: UUID,
    node_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    # BOLA fix: resolve caller's workspace + verify kasten ownership BEFORE
    # the delete. Without this, the legacy ``runtime.kg_user_id`` (auth UUID,
    # NOT workspace_id) was forwarded to a service-role DELETE keyed only on
    # (kasten_id, workspace_zettel_id) — letting any authenticated user
    # remove members from any kasten.
    if _v2_scope_for(user) is not None:
        rag_repo, workspace_id = _resolve_caller_workspace_for_kasten(user, sandbox_id)
        try:
            wz_id = UUID(node_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid node_id") from exc
        removed = rag_repo.remove_zettel_from_kasten(
            kasten_id=sandbox_id,
            workspace_zettel_id=wz_id,
            workspace_id=workspace_id,
        )
        if not removed:
            raise HTTPException(status_code=404, detail="Sandbox member not found")
        return {"status": "ok", "node_id": node_id}

    runtime = _runtime_for_user(user)
    removed = await runtime.sandboxes.remove_member(sandbox_id, runtime.kg_user_id, node_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Sandbox member not found")
    return {"status": "ok", "node_id": node_id}


@router.delete("/sandboxes/{sandbox_id}/members")
async def bulk_remove_members(
    sandbox_id: UUID,
    body: SandboxMemberRemoveRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    if not any([body.node_ids, body.tags, body.source_types]):
        raise HTTPException(status_code=400, detail="At least one filter is required")

    # BOLA fix: same as remove_member above. Resolve real workspace_id and
    # verify ownership before any delete; never trust ``runtime.kg_user_id``
    # as a workspace key.
    if _v2_scope_for(user) is not None:
        rag_repo, workspace_id = _resolve_caller_workspace_for_kasten(user, sandbox_id)
        # Use the v2 store wired with workspace_id so the BOLA gate fires
        # inside the repo as well (defense in depth).
        runtime = _runtime_for_user(user)
        members = await runtime.sandboxes.list_members(sandbox_id, workspace_id, limit=1000)
        matched_node_ids = [
            member.get("workspace_zettel_id") or member.get("node_id")
            for member in members
            if _member_matches_filters(member, body)
        ]
        matched_wz_ids: list[UUID] = []
        for mid in matched_node_ids:
            if not mid:
                continue
            try:
                matched_wz_ids.append(UUID(str(mid)))
            except (TypeError, ValueError):
                continue
        removed_count = rag_repo.remove_zettels_from_kasten(
            kasten_id=sandbox_id,
            workspace_zettel_ids=matched_wz_ids,
            workspace_id=workspace_id,
        )
        updated_members = await runtime.sandboxes.list_members(sandbox_id, workspace_id, limit=1000)
        return {
            "status": "ok",
            "removed_count": removed_count,
            "members": [_serialize_member(member) for member in updated_members],
        }

    runtime = _runtime_for_user(user)
    sandbox = await runtime.sandboxes.get_sandbox(sandbox_id, runtime.kg_user_id)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    members = await runtime.sandboxes.list_members(sandbox_id, runtime.kg_user_id, limit=1000)
    # v2 (Phase 8.0 H9): membership rows expose ``workspace_zettel_id``;
    # fall back to legacy ``node_id`` if a future caller still emits it.
    matched_node_ids = [
        member.get("workspace_zettel_id") or member.get("node_id")
        for member in members
        if _member_matches_filters(member, body)
    ]
    matched_node_ids = [mid for mid in matched_node_ids if mid]
    removed_count = await runtime.sandboxes.remove_members(sandbox_id, runtime.kg_user_id, matched_node_ids)
    updated_members = await runtime.sandboxes.list_members(sandbox_id, runtime.kg_user_id, limit=1000)
    return {
        "status": "ok",
        "removed_count": removed_count,
        "members": [_serialize_member(member) for member in updated_members],
    }

