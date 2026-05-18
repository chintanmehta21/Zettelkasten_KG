"""Runner for the canonical create-Kasten pipeline.

Phase C. Importable from both the FastAPI route (``POST /api/rag/sandboxes``)
and CLI / Phase-E tooling. Creates (or idempotently reuses) a Kasten, ingests
zero or more links through the *same* Add Zettel pipeline (summarize → persist
→ fire-and-forget Phase-B KG population), resolves each link's true
``content.workspace_zettels.id`` (handling the dedup caveat), bulk-adds the
resolved overlay ids to the Kasten, and invalidates the per-user graph cache.

Conventions mirrored from ``summarization.py``: entitlement gate before work
is the *route's* responsibility (single ``Meter.KASTEN`` charge, exactly like
``create_sandbox`` today); per-link ``Meter.ZETTEL`` is enforced *inside*
``run_add_zettel_pipeline`` — this runner never touches pricing. Module-level
``asyncio.Semaphore(2)``; Pydantic ``.model_dump(mode="json")`` return; lazy
heavy imports; ``__main__`` argparse CLI.

Idempotency is mirrored from ``zettels_routes`` (the route machinery there
returns ``JSONResponse`` objects and is not cleanly importable as a pure
function, so the pattern is replicated minimally and consistently here):
key ``(str(effective_user_id), client_action_id)`` + sha256(body) + 900s TTL
``OrderedDict`` + in-flight ``asyncio.shield`` dedup + a structured 409-class
conflict on hash mismatch.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

_CREATE_KASTEN_SEMAPHORE = asyncio.Semaphore(2)

_OPERATION_TTL_SECONDS = 15 * 60
_MAX_IDEMPOTENCY_RECORDS = 128

# Mirrors zettels_routes._IDEMPOTENCY_CACHE / _IN_FLIGHT (pattern replicated;
# state is independent so a create_kasten re-submit cannot collide with an
# add_zettel re-submit even if both share a client_action_id).
_IDEMPOTENCY_CACHE: "OrderedDict[tuple[str, str], tuple[float, str, dict[str, Any]]]" = OrderedDict()
_IN_FLIGHT: dict[tuple[str, str], tuple[str, asyncio.Task]] = {}


class IdempotencyConflict(Exception):
    """Raised when a client_action_id is reused with a different request body.

    The route maps this to HTTP 409 (mirrors ``zettels_routes``'
    ``_idempotency_conflict``). Carries the offending ``client_action_id`` so
    the caller can surface a precise problem+json instance.
    """

    def __init__(self, client_action_id: str) -> None:
        super().__init__("client_action_id reused with a different request body")
        self.client_action_id = client_action_id


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


class CreateKastenOutput(BaseModel):
    status: Literal["succeeded", "failed"]
    kasten: KastenDTO | None = None
    ingested: list[IngestedLink] = Field(default_factory=list)
    failed: list[FailedLink] = Field(default_factory=list)
    operation_id: str


# ---------------------------------------------------------------------------
# Lazy facades (mirror summarization.py — keep heavy imports out of import time)
# ---------------------------------------------------------------------------


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


def _serialize_kasten(row: dict) -> KastenDTO:
    """Serialise a ``rag.kastens`` row into the Kasten DTO.

    Field-for-field identical to ``sandbox_routes._serialize_kasten_v2`` so the
    route can wrap it as ``{"sandbox": kasten}`` byte-identically to the legacy
    create path.
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


def _request_hash(
    *,
    name: str,
    links: list[str],
    description: str,
    icon: str,
    color: str,
    default_quality: str,
    persist: bool,
) -> str:
    """Stable sha256 over the semantically-significant request fields.

    Mirrors ``zettels_routes._request_hash``: a re-submit with the same
    client_action_id but a different body is an idempotency conflict. ``links``
    order is preserved (re-ordering is a different request — conservative, and
    membership is union-merged on the server via ON CONFLICT regardless).
    """
    fingerprint = {
        "name": name,
        "links": list(links),
        "description": description,
        "icon": icon,
        "color": color,
        "default_quality": default_quality,
        "persist": persist,
    }
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cache_get(
    key: tuple[str, str], request_hash: str, client_action_id: str
) -> dict[str, Any] | None:
    record = _IDEMPOTENCY_CACHE.get(key)
    if not record:
        return None
    ts, cached_hash, value = record
    if time.monotonic() - ts > _OPERATION_TTL_SECONDS:
        _IDEMPOTENCY_CACHE.pop(key, None)
        return None
    if cached_hash != request_hash:
        raise IdempotencyConflict(client_action_id)
    _IDEMPOTENCY_CACHE.move_to_end(key)
    return value


def _cache_put(key: tuple[str, str], request_hash: str, value: dict[str, Any]) -> None:
    _IDEMPOTENCY_CACHE[key] = (time.monotonic(), request_hash, value)
    _IDEMPOTENCY_CACHE.move_to_end(key)
    while len(_IDEMPOTENCY_CACHE) > _MAX_IDEMPOTENCY_RECORDS:
        _IDEMPOTENCY_CACHE.popitem(last=False)


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
        routes_mod._graph_cache_global = None
        routes_mod._graph_cache_global_ts = 0
    except Exception:  # noqa: BLE001 — best-effort; logged, never fatal
        import logging

        logging.getLogger("website.api.module_runners.create_kasten").exception(
            "Failed to invalidate graph cache after create_kasten"
        )


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

    ``rag.kastens`` has a UNIQUE(workspace_id, name); a duplicate INSERT raises
    a unique/duplicate-key driver error. Per locked decision D2 a benign
    re-submit (same name) must reuse the existing Kasten, not 409 — so on a
    dup-key error we fetch it back via ``list_kastens`` and return it. Any
    other driver error propagates (the route maps it to 5xx).
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
            for existing in rag_repo.list_kastens(workspace_id, limit=200):
                if existing.get("name") == name:
                    return existing
            # Raced away (created then deleted between INSERT and SELECT) or a
            # name-normalisation mismatch — re-raise the original so the failure
            # is visible rather than silently returning a wrong Kasten.
            raise
        raise


async def run_create_kasten_pipeline(
    *,
    name: str,
    links: list[str],
    user: dict | None,
    effective_user_id: UUID,
    client_action_id: str,
    description: str = "",
    icon: str = "stack",
    color: str = "#14b8a6",
    default_quality: str = "fast",
    persist: bool = True,
    drain_enrichment: bool = True,
) -> dict[str, Any]:
    """Create (or idempotently reuse) a Kasten and ingest ``links`` into it.

    Synchronous end-to-end (awaits every link) so CLI / Phase-E callers get a
    deterministic, fully-resolved result. The HTTP route runs this as a
    background operation when ``links`` is non-empty (D3); with ``links == []``
    it is a pure create and the route returns the result inline.

    Returns ``CreateKastenOutput(...).model_dump(mode="json")``.

    Raises:
        IdempotencyConflict: same ``client_action_id``, different body.
        ValueError: empty/oversize name or a malformed/blocked URL (validated
            with the *same* ``validate_url`` Add Zettel uses).
    """
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("name is required")
    if len(cleaned_name) > 80:
        raise ValueError("name is too long")

    normalized_quality = (default_quality or "fast").strip().lower()
    if normalized_quality not in {"fast", "high"}:
        raise ValueError("default_quality must be fast or high")

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

    cache_key = (str(effective_user_id), client_action_id)
    request_hash = _request_hash(
        name=cleaned_name,
        links=cleaned_links,
        description=description or "",
        icon=icon or "stack",
        color=color or "#14b8a6",
        default_quality=normalized_quality,
        persist=persist,
    )

    cached = _cache_get(cache_key, request_hash, client_action_id)
    if cached is not None:
        return cached

    in_flight = _IN_FLIGHT.get(cache_key)
    if in_flight is not None:
        running_hash, running_task = in_flight
        if running_hash != request_hash:
            raise IdempotencyConflict(client_action_id)
        result = await asyncio.shield(running_task)
        _cache_put(cache_key, request_hash, result)
        return result

    task = asyncio.ensure_future(
        _execute_create_kasten(
            name=cleaned_name,
            links=cleaned_links,
            user=user,
            effective_user_id=effective_user_id,
            client_action_id=client_action_id,
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
        result = await asyncio.shield(task)
    except BaseException:
        # The build failed/was cancelled: drop the in-flight marker so a
        # retry with the same client_action_id can start fresh (a failed
        # build must NOT be cached as a successful idempotent result).
        _IN_FLIGHT.pop(cache_key, None)
        raise
    # Cache BEFORE clearing the in-flight marker. Mirrors
    # ``zettels_routes._await_in_flight`` ordering (``_cache_put`` then
    # ``_IN_FLIGHT.pop``): closes the handoff window where a third concurrent
    # caller arriving after the pop but before the cache write would see both
    # the idempotency cache AND _IN_FLIGHT empty and wrongly start a duplicate
    # build (duplicate Kasten + double Add-Zettel run + double ZETTEL charge).
    _cache_put(cache_key, request_hash, result)
    _IN_FLIGHT.pop(cache_key, None)
    return result


async def _execute_create_kasten(
    *,
    name: str,
    links: list[str],
    user: dict | None,
    effective_user_id: UUID,
    client_action_id: str,
    description: str,
    icon: str,
    color: str,
    default_quality: str,
    persist: bool,
    drain_enrichment: bool = True,
) -> dict[str, Any]:
    user_sub = str(effective_user_id)
    scope = get_supabase_v2_scope(user_sub)
    if scope is None:
        raise ValueError(
            "create_kasten requires a DB v2 workspace scope for the user"
        )
    content_repo, _profile_id, workspace_id = scope

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
    resolved_wz_ids: list[UUID] = []

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
                # One bad link MUST NOT abort the build (locked requirement).
                failed.append(FailedLink(url=link, error=str(exc)))
                return

        summary = pipeline_out.get("summary") or {}
        persistence = pipeline_out.get("persistence") or {}
        # ``workspace_zettel_id`` from the pipeline is the canonical id (NOT the
        # workspace overlay id) on a dedup hit (was_new=False) — never feed it
        # straight to rag.bulk_add_to_kasten. Re-resolve the true overlay id by
        # the normalized URL + workspace compound key.
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
            except Exception as exc:  # noqa: BLE001 — resolution failure is a per-link failure
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
            resolved_wz_ids.append(resolved_wz)

        ingested.append(
            IngestedLink(
                url=link,
                workspace_zettel_id=str(resolved_wz) if resolved_wz else None,
                node_id=pipeline_out.get("node_id"),
                was_new=was_new,
            )
        )

    if links:
        # Bounded by _CREATE_KASTEN_SEMAPHORE inside _ingest_one; gather keeps
        # the runner synchronous (await all) for deterministic CLI/Phase-E use.
        await asyncio.gather(
            *(_ingest_one(idx, link) for idx, link in enumerate(links))
        )

    if resolved_wz_ids:
        # ON CONFLICT DO NOTHING in rag.bulk_add_to_kasten → re-submitting the
        # same links is a no-op membership-wise (D2 idempotency holds end-to-end).
        try:
            await asyncio.to_thread(
                rag_repo.add_zettels_to_kasten,
                kasten_id=kasten_id,
                workspace_zettel_ids=resolved_wz_ids,
            )
        except Exception as exc:  # noqa: BLE001 — surface, but Kasten already exists
            # The Kasten + zettels are persisted; only the join failed. Record
            # it as a build-wide failure marker without losing the created
            # Kasten in the response (callers can retry the add).
            failed.append(
                FailedLink(url="<bulk_add_to_kasten>", error=str(exc))
            )

    # Phase-B KG population + RAG chunk ingest are scheduled fire-and-forget
    # inside the Add-Zettel persist path so the *website* route returns without
    # waiting. This runner, however, is short-lived (CLI / Phase-E: the loop is
    # torn down by ``asyncio.run`` the moment we return) — pending kg-populate
    # tasks would be cancelled before they create any kg_edges (observed:
    # 0 edges after a real CLI ingest). Deterministically drain them here so KG
    # population is GUARANTEED to complete for every ingested zettel before the
    # runner returns. Idempotent + best-effort: a task failure is already
    # logged/swallowed at its own site (Phase-B contract); the
    # pipelines.pipeline_runs(kind='kg_extract') gate keeps it idempotent and
    # workspace-scoped.
    #
    # P2 (Codex review #3261952504): this drain is PROCESS-WIDE
    # (persist._PENDING_ENRICHMENT_TASKS), so calling it from the long-lived
    # FastAPI background create-with-links path made one user's operation
    # block on UNRELATED traffic's enrichment tasks (up to the 120s timeout)
    # — cross-request latency coupling. It is only needed for short-lived
    # callers (CLI / Phase-E) whose event loop is torn down by ``asyncio.run``
    # before fire-and-forget tasks finish. The route passes
    # ``drain_enrichment=False`` (the server loop persists the tasks; no drain
    # needed and a global drain is harmful); CLI keeps the default True.
    if drain_enrichment:
        await _drain_pending_enrichment_tasks()

    _invalidate_graph(user_sub)

    return CreateKastenOutput(
        status="succeeded",
        kasten=_serialize_kasten(kasten_row),
        ingested=ingested,
        failed=failed,
        operation_id=client_action_id,
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# CLI (mirrors summarization.py _cli — used by Phase E to seed Naruto Kastens)
# ---------------------------------------------------------------------------


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
        description="Create a Kasten and ingest links through the Add Zettel pipeline.",
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
