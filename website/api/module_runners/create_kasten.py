"""Runner for the canonical create-Kasten pipeline.

Phase C + new_apis_1a (locked 2026-05-23). Importable from both the FastAPI
route (``POST /api/rag/sandboxes``) and CLI / Phase-E tooling. Creates (or
idempotently reuses) a Kasten, populates it according to an explicit
``selection_mode`` (``all`` / ``source`` / ``specific`` / ``links`` /
``mixed``), and invalidates the per-user graph cache.

Selection modes (per new_apis1.md reconciliation):

* ``all``: every non-deleted workspace_zettel the caller's workspace owns.
* ``source``: overlays whose canonical.source_type is in ``source_types``.
* ``specific``: caller-supplied ``workspace_zettel_ids`` (validated server-side
  for workspace membership — cross-tenant or canonical_id values are
  surfaced as ``FailedLink`` entries, never silently dropped).
* ``links``: ingest each URL through the Add Zettel pipeline, then add the
  resulting overlay ids.
* ``mixed``: any combination of the three input lists.

Conventions mirrored from ``summarization.py``:

* Module-level ``asyncio.Semaphore(2)`` to bound concurrent per-link ingest.
* Pydantic DTOs returned via ``.model_dump(mode="json")``.
* Lazy heavy imports.
* ``with operation_context(client_action_id):`` so deep ingest log lines
  correlate to a single op id (zettels_routes pattern).
* CLI parity entrypoint via ``argparse``.

Idempotency (D4 locked 2026-05-23 — web-research verdict):

* The per-process **result** cache was removed. The DB-backed
  ``core.operations`` row is the cross-worker single source of truth; a
  per-worker ``OrderedDict`` was invisible to other gunicorn workers and
  produced a 50%+ miss rate on the 2-worker droplet.
* ``_IN_FLIGHT`` stays — it is the same-worker **singleflight** layer that
  coalesces concurrent same-key requests on ONE worker before they reach
  the DB (Future hand-off; microsecond overhead). Different concern,
  complementary to the DB layer. Reference: Stripe / Shopify / Adyen
  engineering posts + IETF draft-ietf-httpapi-idempotency-key-header-07.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from website.core.request_context import operation_context
from website.features.rag_pipeline.types import SourceType

logger = logging.getLogger("website.api.module_runners.create_kasten")

_CREATE_KASTEN_SEMAPHORE = asyncio.Semaphore(2)

# Same-worker singleflight (D4). Keyed on (effective_user_id, client_action_id).
# Cleared in the run_create_kasten_pipeline finally block whether the task
# succeeded or failed — the DB layer owns cross-call result dedup.
_IN_FLIGHT: dict[tuple[str, str], tuple[str, asyncio.Task]] = {}

# Off-critical-path tasks (graph cache invalidation). Strong-ref so the event
# loop does not GC mid-flight; discarded on completion.
_BG_TASKS: set[asyncio.Task] = set()


# Explicit selection-mode enum (per new_apis1.md reconciliation — replaces the
# implicit-via-field-presence shape from new_apis2.md). Self-documents the wire
# contract and lets the route layer emit RFC 9457 errors[] for per-mode
# validation failures.
SelectionMode = Literal["all", "source", "specific", "links", "mixed"]


class IdempotencyConflict(Exception):
    """Raised by the per-worker singleflight gate when two concurrent same-key
    requests on ONE worker carry different bodies.

    Cross-worker same-key-different-body detection is now the route layer's
    responsibility (pre-check against ``core.operations`` before calling
    ``operations_repo.accept``).
    """

    def __init__(self, client_action_id: str) -> None:
        super().__init__("client_action_id reused with a different request body")
        self.client_action_id = client_action_id


# ───────────────────────────────────────────────────────────────────────────
# DTOs
# ───────────────────────────────────────────────────────────────────────────


class IngestedLink(BaseModel):
    url: str
    workspace_zettel_id: str | None = None
    node_id: str | None = None
    was_new: bool = True


class FailedLink(BaseModel):
    url: str
    error: str


class KastenDTO(BaseModel):
    id: str
    name: str
    description: str = ""
    icon: str = "stack"
    color: str = "#14b8a6"
    default_quality: str = "fast"
    member_count: int = 0
    last_used_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SelectionSummaryDTO(BaseModel):
    """Per new_apis1.md spec: the response surfaces the resolved selection so
    the UI can confirm what membership shape was actually created.

    ``resolved_member_count`` is the count of unique workspace_zettel ids
    actually bulk-added to the Kasten (post-dedup across links + source
    filter + specific picks + 'all' fan-out).
    """

    selection_mode: SelectionMode
    resolved_member_count: int = 0
    source_types: list[str] = Field(default_factory=list)
    workspace_zettel_ids_supplied: int = 0
    links_supplied: int = 0


class CreateKastenOutput(BaseModel):
    status: Literal["succeeded", "failed"]
    kasten: KastenDTO | None = None
    selection: SelectionSummaryDTO | None = None
    ingested: list[IngestedLink] = Field(default_factory=list)
    failed: list[FailedLink] = Field(default_factory=list)
    operation_id: str


# ───────────────────────────────────────────────────────────────────────────
# Lazy facades (heavy imports deferred to call time, matches summarization.py)
# ───────────────────────────────────────────────────────────────────────────


async def run_add_zettel_pipeline(*args: Any, **kwargs: Any) -> Any:
    from website.api.module_runners.summarization import (
        run_add_zettel_pipeline as _impl,
    )

    return await _impl(*args, **kwargs)


def get_supabase_v2_scope(*args: Any, **kwargs: Any) -> Any:
    from website.core.persist import get_supabase_v2_scope as _impl

    return _impl(*args, **kwargs)


async def _drain_pending_enrichment_tasks(*args: Any, **kwargs: Any) -> Any:
    from website.core.persist import drain_pending_enrichment_tasks as _impl

    return await _impl(*args, **kwargs)


def RAGRepository(*args: Any, **kwargs: Any) -> Any:  # noqa: N802 — factory facade
    from website.core.supabase_v2.repositories.rag_repository import (
        RAGRepository as _impl,
    )

    return _impl(*args, **kwargs)


def _validate_url(value: str) -> bool:
    from website.core.url_utils import validate_url as _impl

    return _impl(value)


async def _functional_gate_kasten_quota(
    effective_user_id: UUID, client_action_id: str
) -> None:
    """Single quick RPC to ``billing.pricing_reserve_and_consume`` via the
    ``functional_gates`` module — the user-locked 2026-05-23 directive:
    every quota-bearing runner explicitly invokes the gate, even when
    called standalone (CLI / Phase-E). Idempotent on
    ``(profile_id, feature, action_id)`` so a route-level
    ``require_entitlement`` with the same ``action_id`` collapses to the
    same decision (no double-charge). Fail-open on infra error.
    """
    try:
        from website.features.functional_gates import get_functional_gates

        decision = await get_functional_gates().reserve_and_consume(
            profile_id=effective_user_id,
            feature="kasten",
            action_id=client_action_id,
        )
        if not decision.allowed:
            # Don't raise here — operator-locked fail-open posture; the
            # route's ``require_entitlement`` remains the canonical 402
            # enforcement point. Log the denial for telemetry.
            logger.info(
                "functional_gates denied kasten quota for %s: %s",
                effective_user_id, decision.reason,
            )
    except Exception as exc:  # noqa: BLE001 — fail-open on gate infra failure
        logger.warning(
            "functional_gates pre-check raised for kasten/%s: %s",
            client_action_id, exc,
        )


def _serialize_kasten(row: dict) -> KastenDTO:
    """Serialise a ``rag.kastens`` row into the Kasten DTO.

    Field-for-field identical to ``sandbox_routes._serialize_kasten_v2`` so the
    route can wrap it as ``{"sandbox": kasten}`` byte-identically to the legacy
    create-only path.
    """
    return KastenDTO(
        id=str(row["id"]),
        name=row["name"],
        description=row.get("description") or "",
        icon=row.get("icon") or "stack",
        color=row.get("color") or "#14b8a6",
        default_quality=row.get("default_quality", "fast"),
        member_count=row.get("member_count", 0),
        last_used_at=row.get("last_used_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# ───────────────────────────────────────────────────────────────────────────
# Selection-mode helpers
# ───────────────────────────────────────────────────────────────────────────


def _normalize_selection_mode(
    *,
    selection_mode: SelectionMode | None,
    links: list[str],
    source_types: list[str],
    workspace_zettel_ids: list[str],
) -> SelectionMode:
    """Infer selection_mode for backward-compat callers that don't pass it.

    Explicit ``selection_mode`` always wins. Otherwise: count non-empty input
    lists; 2+ → ``mixed``; exactly 1 → match the singleton input; 0 → ``all``
    (the route should bypass this runner entirely for create-only Kastens —
    if we get here with all-empty inputs the Kasten exists empty).
    """
    if selection_mode is not None:
        return selection_mode
    nonempty = sum(1 for v in (links, source_types, workspace_zettel_ids) if v)
    if nonempty >= 2:
        return "mixed"
    if links:
        return "links"
    if source_types:
        return "source"
    if workspace_zettel_ids:
        return "specific"
    return "all"


def _validate_selection_payload(
    *,
    selection_mode: SelectionMode,
    links: list[str],
    source_types: list[str],
    workspace_zettel_ids: list[str],
) -> list[dict[str, str]]:
    """Per-mode validation. Returns a list of field-level errors (empty if OK).

    Each error dict shape: ``{"field": <name>, "detail": <msg>}`` — usable as
    the RFC 9457 ``errors[]`` extension at the route layer. The route's
    Pydantic model is the primary validator; this is defense-in-depth for
    CLI / non-route callers.
    """
    errors: list[dict[str, str]] = []

    def _expect_empty(field_name: str, value: list) -> None:
        if value:
            errors.append(
                {
                    "field": field_name,
                    "detail": f"{field_name} must be empty for selection_mode={selection_mode}",
                }
            )

    def _expect_nonempty(field_name: str, value: list) -> None:
        if not value:
            errors.append(
                {
                    "field": field_name,
                    "detail": f"{field_name} is required for selection_mode={selection_mode}",
                }
            )

    if selection_mode == "all":
        _expect_empty("source_types", source_types)
        _expect_empty("workspace_zettel_ids", workspace_zettel_ids)
        _expect_empty("links", links)
    elif selection_mode == "source":
        _expect_nonempty("source_types", source_types)
        _expect_empty("workspace_zettel_ids", workspace_zettel_ids)
        _expect_empty("links", links)
    elif selection_mode == "specific":
        _expect_nonempty("workspace_zettel_ids", workspace_zettel_ids)
        _expect_empty("source_types", source_types)
        _expect_empty("links", links)
    elif selection_mode == "links":
        _expect_nonempty("links", links)
        _expect_empty("source_types", source_types)
        _expect_empty("workspace_zettel_ids", workspace_zettel_ids)
    elif selection_mode == "mixed":
        nonempty = sum(1 for v in (links, source_types, workspace_zettel_ids) if v)
        if nonempty < 2:
            errors.append(
                {
                    "field": "selection_mode",
                    "detail": (
                        "selection_mode=mixed requires at least two of "
                        "{links, source_types, workspace_zettel_ids} to be non-empty"
                    ),
                }
            )

    return errors


def _request_hash(
    *,
    name: str,
    links: list[str],
    description: str,
    icon: str,
    color: str,
    default_quality: str,
    persist: bool,
    selection_mode: SelectionMode,
    source_types: list[str],
    workspace_zettel_ids: list[str],
) -> str:
    """Stable sha256 over the semantically-significant request fields.

    Includes selection_mode + source_types + workspace_zettel_ids so a
    re-submit that changes the selection (e.g. same name, different source
    filter) is correctly detected as a different request by the singleflight
    gate (and by the route-level pre-check against ``core.operations``).
    """
    fingerprint = {
        "name": name,
        "links": list(links),  # order-preserving — link order is a meaningful difference
        "description": description,
        "icon": icon,
        "color": color,
        "default_quality": default_quality,
        "persist": persist,
        "selection_mode": selection_mode,
        "source_types": sorted(source_types),  # order-insensitive
        "workspace_zettel_ids": sorted(workspace_zettel_ids),  # order-insensitive
    }
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _invalidate_graph(user_sub: str | None) -> None:
    """Drop the per-user + global /api/graph cache.

    Mirrors ``zettels_routes._invalidate_graph`` so a freshly-built Kasten's
    zettels are visible via ``GET /api/graph?view=my`` immediately. Best-effort:
    a cache-invalidation failure must never fail the build.
    """
    if not user_sub:
        return
    try:
        from website.api import routes as routes_mod

        routes_mod.invalidate_user_graph(user_sub)
        # K1: anon cache now lives in UserGraphCache via the "__anon__"
        # sentinel (replaces the deleted _graph_cache_global module globals).
        routes_mod.invalidate_user_graph("__anon__")
    except Exception:  # noqa: BLE001 — best-effort; logged, never fatal
        logger.exception("Failed to invalidate graph cache after create_kasten")


def _schedule_graph_invalidation(user_sub: str | None) -> None:
    """Schedule ``_invalidate_graph`` off the critical path.

    Mirrors ``zettels_routes._schedule_graph_invalidation``: the invalidation
    runs as a fire-and-forget continuation so the runner's TTFB is unaffected.
    Falls back to inline if no running loop (CLI tear-down scenarios).
    """
    if not user_sub:
        return

    async def _run() -> None:
        await asyncio.to_thread(_invalidate_graph, user_sub)

    try:
        task = asyncio.create_task(_run())
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)
    except RuntimeError:
        _invalidate_graph(user_sub)


# ───────────────────────────────────────────────────────────────────────────
# Workspace-zettel resolution helpers
# ───────────────────────────────────────────────────────────────────────────


def _list_all_workspace_zettel_ids(
    *, content_repo: Any, workspace_id: UUID
) -> list[UUID]:
    """Paginate ``list_workspace_zettels`` to gather every overlay id.

    Page size matches the repo default (5000); walks pages until the returned
    batch is shorter than the page size (final page). Scale-proof for
    workspaces with up to ~50k zettels (10 PostgREST calls of 5000 each).
    """
    page_size = 5000
    offset = 0
    ids: list[UUID] = []
    while True:
        rows = content_repo.list_workspace_zettels(
            workspace_id, limit=page_size, offset=offset
        )
        if not rows:
            break
        for row in rows:
            wz_id_raw = row.get("id")
            if not wz_id_raw:
                continue
            try:
                ids.append(UUID(str(wz_id_raw)))
            except (TypeError, ValueError):
                continue
        if len(rows) < page_size:
            break
        offset += page_size
    return ids


def _list_workspace_zettel_ids_by_source_types(
    *, content_repo: Any, workspace_id: UUID, source_types: list[str]
) -> list[UUID]:
    """Source-filtered overlay ids.

    Python-side filter over the paginated overlay list (no source-filter RPC
    today). For typical workspace sizes (<10k zettels) this is a single
    5000-row PostgREST call followed by an O(n) filter — cheaper than
    introducing a per-source-type RPC migration for current scale.
    """
    if not source_types:
        return []
    wanted = {s.lower() for s in source_types}
    page_size = 5000
    offset = 0
    ids: list[UUID] = []
    while True:
        rows = content_repo.list_workspace_zettels(
            workspace_id, limit=page_size, offset=offset
        )
        if not rows:
            break
        for row in rows:
            canonical = row.get("canonical") or {}
            source_type = str(canonical.get("source_type") or "").lower()
            if source_type and source_type in wanted:
                wz_id_raw = row.get("id")
                if wz_id_raw:
                    try:
                        ids.append(UUID(str(wz_id_raw)))
                    except (TypeError, ValueError):
                        continue
        if len(rows) < page_size:
            break
        offset += page_size
    return ids


def _validate_workspace_zettel_ownership(
    *,
    content_repo: Any,
    workspace_id: UUID,
    workspace_zettel_ids: list[UUID],
) -> tuple[list[UUID], list[UUID]]:
    """Partition supplied ids into ``(owned, orphan)``.

    'Owned' = present in the caller's workspace and non-deleted. 'Orphan' =
    everything else: cross-tenant ids, canonical_zettel_id values (the
    new_apis1.md hard rule — clients MUST send workspace_zettel_id), soft-
    deleted overlays, or non-existent ids. Orphans are surfaced via
    ``FailedLink`` entries so the UI never silently drops a selection.
    """
    if not workspace_zettel_ids:
        return [], []
    supplied = {wz_id for wz_id in workspace_zettel_ids}
    all_ids = set(
        _list_all_workspace_zettel_ids(
            content_repo=content_repo, workspace_id=workspace_id
        )
    )
    owned = sorted(supplied & all_ids)
    orphan = sorted(supplied - all_ids)
    return list(owned), list(orphan)


def _create_or_get_kasten(
    *,
    rag_repo: Any,
    workspace_id: UUID,
    name: str,
    description: str,
    icon: str,
    color: str,
    default_quality: str,
) -> dict:
    """Create the Kasten, or reuse the existing same-name one (D2 idempotency).

    Direct indexed lookup on the UNIQUE(workspace_id, name) key on dup-key —
    scale-proof. The prior ``list_kastens(limit=200)`` scan missed older
    same-name rows in workspaces with >200 kastens, turning a benign
    re-submit into a 5xx (Codex review #3262317336).
    """
    try:
        return rag_repo.create_kasten(
            workspace_id=workspace_id,
            name=name,
            description=description or None,
            icon=icon,
            color=color,
            default_quality=default_quality,
        )
    except Exception as exc:  # noqa: BLE001 — only dup-name is recoverable here
        lower = str(exc).lower()
        if "duplicate key" in lower or "unique" in lower:
            existing = rag_repo.get_kasten_by_name(workspace_id, name)
            if existing is not None:
                return existing
            raise
        raise


# ───────────────────────────────────────────────────────────────────────────
# Public coroutine
# ───────────────────────────────────────────────────────────────────────────


async def run_create_kasten_pipeline(
    *,
    name: str,
    user: dict | None,
    effective_user_id: UUID,
    client_action_id: str,
    links: list[str] | None = None,
    selection_mode: SelectionMode | None = None,
    source_types: list[str] | None = None,
    workspace_zettel_ids: list[str] | None = None,
    description: str = "",
    icon: str = "stack",
    color: str = "#14b8a6",
    default_quality: str = "fast",
    persist: bool = True,
    drain_enrichment: bool = True,
) -> dict[str, Any]:
    """Create (or idempotently reuse) a Kasten and populate per selection_mode.

    Returns ``CreateKastenOutput(...).model_dump(mode="json")`` including a
    ``selection`` summary with ``resolved_member_count``.

    Raises:
        IdempotencyConflict: same ``client_action_id`` is in flight on this
            worker with a different request hash.
        ValueError: any structural validation failure (name length, URL shape,
            per-mode constraint violation, non-UUID workspace_zettel_ids,
            unknown source_type).
    """
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("name is required")
    if len(cleaned_name) > 80:
        raise ValueError("name is too long")

    normalized_quality = (default_quality or "fast").strip().lower()
    if normalized_quality not in {"fast", "high"}:
        raise ValueError("default_quality must be fast or high")

    # Normalize inputs to non-None lists; preserve order for links (semantic),
    # de-whitespace + lower-case for source_types (lookup keys).
    cleaned_source_types: list[str] = [
        str(s).strip().lower() for s in (source_types or []) if str(s).strip()
    ]
    cleaned_wz_ids_in: list[str] = [
        str(wz).strip() for wz in (workspace_zettel_ids or []) if str(wz).strip()
    ]

    # URL validation: scheme allow-list + length cap + SSRF block (same gate
    # AddZettelRequest applies).
    cleaned_links: list[str] = []
    for raw in links or []:
        link = (raw or "").strip()
        if not link:
            raise ValueError("links must not contain empty entries")
        if len(link) > 2048:
            raise ValueError("URL too long (max 2048 characters)")
        if not link.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        if not _validate_url(link):
            raise ValueError(f"URL is invalid or blocked: {link}")
        cleaned_links.append(link)

    # UUID parse — defer ownership check to server side (needs the scope).
    parsed_wz_ids: list[UUID] = []
    for wz_raw in cleaned_wz_ids_in:
        try:
            parsed_wz_ids.append(UUID(wz_raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"workspace_zettel_ids contains malformed UUID: {wz_raw!r}"
            ) from exc

    # source_type membership in the canonical enum (rejects typos / arbitrary
    # strings that would silently match nothing).
    for stype in cleaned_source_types:
        try:
            SourceType(stype)
        except ValueError as exc:
            raise ValueError(
                f"source_types contains unknown source: {stype!r}"
            ) from exc

    # Resolve final selection mode (back-compat: infer for callers that pass
    # only the input lists).
    resolved_mode = _normalize_selection_mode(
        selection_mode=selection_mode,
        links=cleaned_links,
        source_types=cleaned_source_types,
        workspace_zettel_ids=cleaned_wz_ids_in,
    )

    # Defense-in-depth per-mode validation. The route's Pydantic model is the
    # primary validator (and emits RFC 9457 errors[] cleanly); this catches
    # CLI / direct-runner misuse.
    field_errors = _validate_selection_payload(
        selection_mode=resolved_mode,
        links=cleaned_links,
        source_types=cleaned_source_types,
        workspace_zettel_ids=cleaned_wz_ids_in,
    )
    if field_errors:
        details = "; ".join(
            f"{err['field']}: {err['detail']}" for err in field_errors
        )
        raise ValueError(
            f"Invalid selection payload for mode={resolved_mode}: {details}"
        )

    cache_key = (str(effective_user_id), client_action_id)
    request_hash = _request_hash(
        name=cleaned_name,
        links=cleaned_links,
        description=description or "",
        icon=icon or "stack",
        color=color or "#14b8a6",
        default_quality=normalized_quality,
        persist=persist,
        selection_mode=resolved_mode,
        source_types=cleaned_source_types,
        workspace_zettel_ids=cleaned_wz_ids_in,
    )

    # D4 (locked 2026-05-23): singleflight only — the per-process result cache
    # was removed in favour of the DB-backed core.operations row at the route
    # layer. Two concurrent same-key callers on this worker share the Future
    # via _IN_FLIGHT (microsecond cost); cross-worker dedup is the route's job.
    in_flight = _IN_FLIGHT.get(cache_key)
    if in_flight is not None:
        running_hash, running_task = in_flight
        if running_hash != request_hash:
            raise IdempotencyConflict(client_action_id)
        return await asyncio.shield(running_task)

    task = asyncio.ensure_future(
        _execute_create_kasten(
            name=cleaned_name,
            links=cleaned_links,
            user=user,
            effective_user_id=effective_user_id,
            client_action_id=client_action_id,
            selection_mode=resolved_mode,
            source_types=cleaned_source_types,
            workspace_zettel_ids=parsed_wz_ids,
            description=description or "",
            icon=icon or "stack",
            color=color or "#14b8a6",
            default_quality=normalized_quality,
            persist=persist,
            drain_enrichment=drain_enrichment,
        )
    )
    _IN_FLIGHT[cache_key] = (request_hash, task)
    try:
        return await asyncio.shield(task)
    finally:
        # Always clear the in-flight marker — success OR failure. The DB layer
        # is the cross-worker idempotency truth; this is purely same-worker
        # singleflight cleanup.
        _IN_FLIGHT.pop(cache_key, None)


async def _execute_create_kasten(
    *,
    name: str,
    links: list[str],
    user: dict | None,
    effective_user_id: UUID,
    client_action_id: str,
    selection_mode: SelectionMode,
    source_types: list[str],
    workspace_zettel_ids: list[UUID],
    description: str,
    icon: str,
    color: str,
    default_quality: str,
    persist: bool,
    drain_enrichment: bool = True,
) -> dict[str, Any]:
    """Build the Kasten and populate per ``selection_mode``.

    Wrapped in ``operation_context`` so deep ingest log lines tie back to a
    single op id (mirrors ``summarization.py`` / ``zettels_routes`` pattern).
    """
    with operation_context(client_action_id):
        user_sub = str(effective_user_id)
        scope = get_supabase_v2_scope(user_sub)
        if scope is None:
            raise ValueError(
                "create_kasten requires a DB v2 workspace scope for the user"
            )
        content_repo, _profile_id, workspace_id = scope

        # Functional-gates pre-check (user-locked 2026-05-23): single quick
        # RPC that lets the runner enforce the kasten quota explicitly —
        # also fires for CLI / Phase-E callers that never go through the
        # route's ``require_entitlement``. Idempotent on
        # ``(profile_id, feature, action_id)``: when the HTTP route has
        # already charged with the SAME ``client_action_id`` upstream, this
        # is a free replay returning the same decision. Fail-open on infra
        # error — the route's ``require_entitlement`` remains the canonical
        # 402 enforcer (operator-locked design per pricing-module-authority).
        await _functional_gate_kasten_quota(effective_user_id, client_action_id)

        rag_repo = RAGRepository()

        kasten_row = await asyncio.to_thread(
            _create_or_get_kasten,
            rag_repo=rag_repo,
            workspace_id=workspace_id,
            name=name,
            description=description,
            icon=icon,
            color=color,
            default_quality=default_quality,
        )
        kasten_id = UUID(str(kasten_row["id"]))

        ingested: list[IngestedLink] = []
        failed: list[FailedLink] = []
        resolved_wz_ids: set[UUID] = set()

        # Step 1: link ingest (modes including 'links').
        if selection_mode in ("links", "mixed") and links:
            await _ingest_links(
                links=links,
                user=user,
                effective_user_id=effective_user_id,
                client_action_id=client_action_id,
                persist=persist,
                content_repo=content_repo,
                workspace_id=workspace_id,
                ingested=ingested,
                failed=failed,
                resolved_wz_ids=resolved_wz_ids,
            )

        # Step 2: source-type filter (modes including 'source').
        if selection_mode in ("source", "mixed") and source_types:
            source_ids = await asyncio.to_thread(
                _list_workspace_zettel_ids_by_source_types,
                content_repo=content_repo,
                workspace_id=workspace_id,
                source_types=source_types,
            )
            resolved_wz_ids.update(source_ids)

        # Step 3: caller-supplied overlay ids (modes including 'specific').
        # Cross-tenant / canonical_id / soft-deleted entries flow into FailedLink
        # so the UI surfaces the rejection rather than silently dropping ids.
        if selection_mode in ("specific", "mixed") and workspace_zettel_ids:
            owned, orphan = await asyncio.to_thread(
                _validate_workspace_zettel_ownership,
                content_repo=content_repo,
                workspace_id=workspace_id,
                workspace_zettel_ids=workspace_zettel_ids,
            )
            resolved_wz_ids.update(owned)
            for orphan_id in orphan:
                failed.append(
                    FailedLink(
                        url=f"workspace_zettel:{orphan_id}",
                        error=(
                            "workspace_zettel_id does not belong to caller's "
                            "workspace (cross-tenant, canonical_id, or "
                            "soft-deleted)"
                        ),
                    )
                )

        # Step 4: 'all' fans out to the entire workspace overlay set.
        if selection_mode == "all":
            all_ids = await asyncio.to_thread(
                _list_all_workspace_zettel_ids,
                content_repo=content_repo,
                workspace_id=workspace_id,
            )
            resolved_wz_ids.update(all_ids)

        # Step 5: bulk-add. Chunked (1000) for scale predictability —
        # PostgREST round-trip latency stays bounded for very large 'all'
        # selections on workspaces with many thousands of zettels.
        if resolved_wz_ids:
            wz_list = sorted(resolved_wz_ids)
            try:
                chunk = 1000
                for i in range(0, len(wz_list), chunk):
                    await asyncio.to_thread(
                        rag_repo.add_zettels_to_kasten,
                        kasten_id=kasten_id,
                        workspace_zettel_ids=wz_list[i : i + chunk],
                    )
            except Exception as exc:  # noqa: BLE001 — surface but keep Kasten
                # A4 — bulk-add catastrophic failure alert. The FailedLink
                # entry preserves the user-visible signal, but ops needs a
                # separate alert: a single bulk error means the Kasten was
                # built with 0–N members instead of the claimed count (AWS
                # snowball anti-pattern + the Naruto-E2E "0 zettels" class).
                try:
                    from website.features.web_monitor import (
                        _hash_id,
                        maybe_fire_app_error,
                    )

                    maybe_fire_app_error(
                        dedup_key=f"kasten_bulk_add:{_hash_id(str(kasten_id))}",
                        route="create_kasten.bulk_add_zettels",
                        exc_type=type(exc).__name__,
                        message=str(exc)[:400],
                        request_id=client_action_id,
                        fields={
                            "kasten_hash": _hash_id(str(kasten_id)),
                            "chunk_offset": str(i),
                            "total_members": str(len(wz_list)),
                            "user_hash": _hash_id(str(effective_user_id)),
                        },
                        severity="critical",
                    )
                except Exception:  # noqa: BLE001 — alert must never block return
                    logger.exception("create_kasten bulk_add alert dispatch failed")
                failed.append(
                    FailedLink(
                        url="<bulk_add_to_kasten>",
                        error=str(exc),
                    )
                )

        # Phase-B KG population + RAG chunk ingest are scheduled fire-and-forget
        # inside Add-Zettel persist. Short-lived callers (CLI / Phase-E whose
        # event loop is torn down by ``asyncio.run``) must drain so those tasks
        # complete before return; HTTP routes pass drain_enrichment=False to
        # avoid coupling unrelated traffic to one request's enrichment queue.
        if drain_enrichment:
            await _drain_pending_enrichment_tasks()

        # Off the critical path: graph cache invalidation. Mirrors the
        # ``_schedule_graph_invalidation`` pattern in ``zettels_routes``.
        _schedule_graph_invalidation(user_sub)

        selection = SelectionSummaryDTO(
            selection_mode=selection_mode,
            resolved_member_count=len(resolved_wz_ids),
            source_types=list(source_types),
            workspace_zettel_ids_supplied=len(workspace_zettel_ids),
            links_supplied=len(links),
        )

        return CreateKastenOutput(
            status="succeeded",
            kasten=_serialize_kasten(kasten_row),
            selection=selection,
            ingested=ingested,
            failed=failed,
            operation_id=client_action_id,
        ).model_dump(mode="json")


async def _ingest_links(
    *,
    links: list[str],
    user: dict | None,
    effective_user_id: UUID,
    client_action_id: str,
    persist: bool,
    content_repo: Any,
    workspace_id: UUID,
    ingested: list[IngestedLink],
    failed: list[FailedLink],
    resolved_wz_ids: set[UUID],
) -> None:
    """Per-link Add Zettel ingest + workspace_zettel resolution.

    Each link is bounded by ``_CREATE_KASTEN_SEMAPHORE``; failures isolate
    per-link — one bad link must not abort the build (locked acceptance
    criterion).
    """

    async def _ingest_one(idx: int, link: str) -> None:
        async with _CREATE_KASTEN_SEMAPHORE:
            try:
                pipeline_out = await run_add_zettel_pipeline(
                    url=link,
                    client_action_id=f"{client_action_id}:zettel:{idx}",
                    persist=persist,
                    user=user,
                    effective_user_id=effective_user_id,
                )
            except Exception as exc:  # noqa: BLE001 — per-link isolation
                failed.append(FailedLink(url=link, error=str(exc)))
                return

        summary = pipeline_out.get("summary") or {}
        persistence = pipeline_out.get("persistence") or {}
        normalized_url = str(summary.get("source_url") or link)
        was_new = not bool(persistence.get("duplicate"))
        resolved_wz: UUID | None = None
        if persist:
            try:
                resolved_wz = await asyncio.to_thread(
                    content_repo.resolve_workspace_zettel_id_by_url,
                    normalized_url=normalized_url,
                    workspace_id=workspace_id,
                )
            except Exception as exc:  # noqa: BLE001 — per-link resolution failure
                failed.append(
                    FailedLink(
                        url=link,
                        error=f"workspace_zettel resolution failed: {exc}",
                    )
                )
                return
            if resolved_wz is None:
                failed.append(
                    FailedLink(
                        url=link,
                        error="workspace_zettel not found after persist",
                    )
                )
                return
            resolved_wz_ids.add(resolved_wz)

        ingested.append(
            IngestedLink(
                url=link,
                workspace_zettel_id=str(resolved_wz) if resolved_wz else None,
                node_id=pipeline_out.get("node_id"),
                was_new=was_new,
            )
        )

    failed_before = len(failed)
    await asyncio.gather(
        *(_ingest_one(idx, link) for idx, link in enumerate(links))
    )

    # C15 — per-link failure rate alert. A user-visible FailedLink per link
    # is correct UX surface, but a 50%+ failure rate across a multi-link
    # build is operator-actionable (Gemini quota outage, all-URLs-blocked,
    # regex regression). Stripe + Datadog burn-rate guidance: aggregate
    # breach is the trigger, not per-item failure. Only check when batch
    # size is ≥ 3 so a single bad link in a 2-link build doesn't page.
    link_failures = len(failed) - failed_before
    if links and len(links) >= 3 and (link_failures / max(len(links), 1)) > 0.5:
        try:
            from website.features.web_monitor import (
                _hash_id,
                maybe_fire_app_error,
            )

            maybe_fire_app_error(
                dedup_key=f"create_kasten_link_failure_rate:{_hash_id(client_action_id)}",
                route="create_kasten._ingest_links",
                exc_type="LinkFailureRateBreached",
                message=f"{link_failures}/{len(links)} links failed in create_kasten",
                request_id=client_action_id,
                fields={
                    "link_failures": str(link_failures),
                    "links_total": str(len(links)),
                    "user_hash": _hash_id(str(effective_user_id)),
                    "workspace_hash": _hash_id(str(workspace_id)),
                },
                severity="warning",
                dedup_seconds=15 * 60,
            )
        except Exception:  # noqa: BLE001 — never break the runner return
            logger.debug("create_kasten link-failure-rate alert dispatch failed", exc_info=True)


# ───────────────────────────────────────────────────────────────────────────
# CLI (mirrors summarization.py _cli — used by Phase E to seed Naruto Kastens)
# ───────────────────────────────────────────────────────────────────────────


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
    for candidate in (root / ".env", root / ".env.v2", root / "supabase" / ".env"):
        _load_env_file(candidate)
    _load_api_env_file(root / "api_env")
    os.environ.setdefault("DB_SCHEMA_VERSION", "v2")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Kasten and populate it (links / source / specific / all / mixed).",
    )
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--links",
        action="append",
        default=[],
        help="A link to ingest (repeatable).",
    )
    parser.add_argument(
        "--links-file",
        default=None,
        help="Path to a newline-delimited file of links (merged with --links).",
    )
    parser.add_argument(
        "--selection-mode",
        default=None,
        choices=["all", "source", "specific", "links", "mixed"],
        help="Explicit selection mode (inferred from other flags if omitted).",
    )
    parser.add_argument(
        "--source-type",
        action="append",
        default=[],
        help="Source-type to include (repeatable, e.g. --source-type web --source-type youtube).",
    )
    parser.add_argument(
        "--workspace-zettel-id",
        action="append",
        default=[],
        help="An explicit workspace_zettel UUID to include (repeatable).",
    )
    parser.add_argument("--user-id", required=True, help="Supabase Auth UUID to write under")
    parser.add_argument("--client-action-id", default="cli-create-kasten")
    parser.add_argument("--description", default="")
    parser.add_argument("--icon", default="stack")
    parser.add_argument("--color", default="#14b8a6")
    parser.add_argument("--default-quality", default="fast", choices=["fast", "high"])
    parser.add_argument("--persist", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--load-env", action="store_true", help="Load .env/.env.v2/supabase/.env first")
    return parser.parse_args()


async def _cli() -> int:
    args = _parse_args()
    if args.load_env:
        _load_local_env()
    links: list[str] = list(args.links or [])
    if args.links_file:
        file_path = Path(args.links_file)
        if not file_path.exists():
            raise SystemExit(f"--links-file not found: {file_path}")
        for line in file_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                links.append(stripped)
    result = await run_create_kasten_pipeline(
        name=args.name,
        links=links,
        user={"sub": args.user_id},
        effective_user_id=UUID(str(args.user_id)),
        client_action_id=args.client_action_id,
        selection_mode=args.selection_mode,
        source_types=args.source_type,
        workspace_zettel_ids=args.workspace_zettel_id,
        description=args.description,
        icon=args.icon,
        color=args.color,
        default_quality=args.default_quality,
        persist=args.persist,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_cli()))
