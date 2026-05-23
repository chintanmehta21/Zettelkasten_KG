"""Runner for the Kasten-scoped RAG query pipeline.

Strangler-fig refactor (D2 locked 2026-05-23): wraps the existing
``RAGOrchestrator`` into an importable, route-and-CLI-friendly facade.
The existing chat routes (``POST /api/rag/sessions/{id}/messages`` and
``POST /api/rag/adhoc``) dispatch through this runner; URLs are unchanged
so no frontend churn (decision D2 — refactor existing only; do NOT add
``POST /api/rag/sandboxes/{id}/ask``).

Two entry points per new_apis1.md reconciliation:

* ``run_ask_kasten_once`` — synchronous, returns a flat ``AskKastenOutput``
  DTO. Use for ``stream=False`` requests and the CLI.
* ``stream_ask_kasten`` — async iterator yielding the raw SSE event dicts
  the orchestrator produces (``status`` / ``citations`` / ``token`` /
  ``done`` / ``error``). The route wraps them in SSE encoding +
  heartbeats; this runner stays transport-agnostic.

Both share:

* Module-level ``asyncio.Semaphore(2)`` (matches ``summarization.py`` /
  ``create_kasten.py``).
* BOLA gate via ``RAGRepository.get_kasten(kasten_id, workspace_id)`` —
  cross-tenant ids resolve to ``None`` and raise ``KastenNotFoundError``
  so the route maps to 403 without leaking existence.
* ``Meter.RAG_QUESTION`` entitlement (NEVER seeded, NEVER invented per
  the pricing-module-authority rule).
* ``operation_context`` binding so deep log lines correlate to the
  ``client_action_id``.

Auth: callers MUST supply the parsed ``effective_user_id`` (UUID from the
JWT ``sub``). Anonymous → Zoro fallback is NOT applied here — chat
requires real auth at the route layer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from website.core.request_context import operation_context

logger = logging.getLogger("website.api.module_runners.ask_kasten")

_ASK_KASTEN_SEMAPHORE = asyncio.Semaphore(2)


class KastenNotFoundError(Exception):
    """Raised when a ``kasten_id`` doesn't belong to the caller's workspace.

    Distinct from a generic 404 so the route can map to **403** following
    the BOLA pattern: never reveal whether the kasten exists in another
    tenant (the canonical 4xx for "cross-tenant or non-existent" — see
    OWASP API1:2023).
    """

    def __init__(self, kasten_id: str) -> None:
        super().__init__(f"Kasten {kasten_id} not found in caller's workspace")
        self.kasten_id = kasten_id


# ───────────────────────────────────────────────────────────────────────────
# DTOs
# ───────────────────────────────────────────────────────────────────────────


class AskKastenCitationDTO(BaseModel):
    id: str
    node_id: str
    title: str
    source_type: str = "web"
    url: str = ""
    snippet: str = ""
    timestamp: str | None = None
    rerank_score: float = 0.0


class AskKastenOutput(BaseModel):
    """Flattened AnswerTurn + operation context.

    Mirrors ``summarization.AddZettelPipelineOutput`` shape (status,
    operation_id, content, citations, error). Pulls every AnswerTurn field
    so callers don't need a second roundtrip for citations or trace_id.
    """

    status: Literal["succeeded", "failed"]
    operation_id: str
    session_id: str | None = None
    kasten_id: str | None = None
    content: str = ""
    citations: list[AskKastenCitationDTO] = Field(default_factory=list)
    query_class: str | None = None
    critic_verdict: str | None = None
    critic_notes: str | None = None
    trace_id: str = ""
    latency_ms: int = 0
    token_counts: dict = Field(default_factory=dict)
    llm_model: str = ""
    retrieved_node_ids: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    error: dict | None = None


# ───────────────────────────────────────────────────────────────────────────
# Lazy facades (heavy imports deferred to call time, matches summarization.py)
# ───────────────────────────────────────────────────────────────────────────


def _get_runtime(user_sub: str) -> Any:
    from website.features.rag_pipeline.service import get_rag_runtime

    return get_rag_runtime(user_sub)


def _rag_repository() -> Any:
    from website.core.supabase_v2.repositories.rag_repository import (
        RAGRepository,
    )

    return RAGRepository()


async def _require_entitlement(
    user: dict, *, action_id: str
) -> None:
    from website.features.user_pricing.entitlements import require_entitlement
    from website.features.user_pricing.models import Meter

    await require_entitlement(Meter.RAG_QUESTION, user, action_id=action_id)


def _build_chat_query(
    *,
    content: str,
    kasten_id: UUID | None,
    session_id: UUID | None,
    quality: str,
    scope_filter: dict | None,
    stream: bool,
) -> Any:
    """Construct a ``ChatQuery`` DTO from runner inputs.

    The orchestrator's retriever joins ``rag.kasten_zettels`` server-side via
    the ``content.hybrid_search_chunks_kasten`` RPC when ``sandbox_id`` is
    set — so the runner does NOT expand the Kasten to ``node_ids`` itself.
    Empty-list ``scope_filter`` values are normalised to ``None`` by the
    ScopeFilter validator (an empty list means "no filter", not "match
    nothing").
    """
    from website.features.rag_pipeline.types import ChatQuery, ScopeFilter

    sf = ScopeFilter(**(scope_filter or {}))
    return ChatQuery(
        session_id=session_id,
        sandbox_id=kasten_id,
        content=content,
        scope_filter=sf,
        quality=quality,  # type: ignore[arg-type]
        stream=stream,
    )


def _serialize_turn(
    turn: Any,
    *,
    operation_id: str,
    session_id: UUID | None,
    kasten_id: UUID | None,
) -> AskKastenOutput:
    """Flatten an ``AnswerTurn`` into the runner's wire DTO."""
    citations: list[AskKastenCitationDTO] = []
    for c in getattr(turn, "citations", []) or []:
        cd = c.model_dump() if hasattr(c, "model_dump") else dict(c)
        citations.append(
            AskKastenCitationDTO(
                id=str(cd.get("id", "")),
                node_id=str(cd.get("node_id", "")),
                title=str(cd.get("title", "")),
                source_type=str(cd.get("source_type") or "web"),
                url=str(cd.get("url") or ""),
                snippet=str(cd.get("snippet") or ""),
                timestamp=cd.get("timestamp"),
                rerank_score=float(cd.get("rerank_score") or 0.0),
            )
        )
    query_class = getattr(turn, "query_class", None)
    if query_class is not None and hasattr(query_class, "value"):
        query_class_str: str | None = str(query_class.value)
    elif query_class is not None:
        query_class_str = str(query_class)
    else:
        query_class_str = None
    return AskKastenOutput(
        status="succeeded",
        operation_id=operation_id,
        session_id=str(session_id) if session_id else None,
        kasten_id=str(kasten_id) if kasten_id else None,
        content=str(getattr(turn, "content", "") or ""),
        citations=citations,
        query_class=query_class_str,
        critic_verdict=(
            str(getattr(turn, "critic_verdict", "") or "") or None
        ),
        critic_notes=getattr(turn, "critic_notes", None),
        trace_id=str(getattr(turn, "trace_id", "") or ""),
        latency_ms=int(getattr(turn, "latency_ms", 0) or 0),
        token_counts=dict(getattr(turn, "token_counts", {}) or {}),
        llm_model=str(getattr(turn, "llm_model", "") or ""),
        retrieved_node_ids=[
            str(n) for n in (getattr(turn, "retrieved_node_ids", []) or [])
        ],
        retrieved_chunk_ids=[
            str(c) for c in (getattr(turn, "retrieved_chunk_ids", []) or [])
        ],
    )


def _validate_inputs(
    *, content: str, quality: str
) -> tuple[str, str]:
    cleaned = (content or "").strip()
    if not cleaned:
        raise ValueError("content is required")
    if len(cleaned) > 5000:
        raise ValueError("content is too long (max 5000 characters)")
    normalized_quality = (quality or "fast").strip().lower()
    if normalized_quality not in {"fast", "high"}:
        raise ValueError("quality must be fast or high")
    return cleaned, normalized_quality


def _gate_kasten_ownership(
    *, kasten_id: UUID | None, runtime: Any
) -> None:
    """Raise ``KastenNotFoundError`` if ``kasten_id`` isn't owned.

    ``runtime.workspace_id`` may be ``None`` for callers without a default
    workspace; in that case ownership cannot be proved and the gate trips
    closed (treat as not-found) — same posture as the existing
    ``sandbox_routes._resolve_caller_workspace_for_kasten`` BOLA helper.
    """
    if kasten_id is None:
        return
    workspace_id = getattr(runtime, "workspace_id", None)
    if workspace_id is None:
        raise KastenNotFoundError(str(kasten_id))
    rag_repo = _rag_repository()
    if rag_repo.get_kasten(kasten_id, workspace_id) is None:
        raise KastenNotFoundError(str(kasten_id))


# ───────────────────────────────────────────────────────────────────────────
# Public coroutines
# ───────────────────────────────────────────────────────────────────────────


async def run_ask_kasten_once(
    *,
    content: str,
    user: dict,
    effective_user_id: UUID,
    client_action_id: str,
    kasten_id: UUID | None = None,
    session_id: UUID | None = None,
    quality: Literal["fast", "high"] = "fast",
    scope_filter: dict | None = None,
) -> dict[str, Any]:
    """Run a single (non-stream) RAG turn against a Kasten and return DTO.

    Returns ``AskKastenOutput.model_dump(mode="json")``. Raises:

    * ``ValueError`` for malformed inputs (empty content, oversize content,
      invalid quality).
    * ``KastenNotFoundError`` if ``kasten_id`` is supplied but the kasten
      isn't owned by the caller's workspace (route → 403).
    * ``HTTPException(402)`` from ``require_entitlement`` when the user is
      out of RAG_QUESTION quota.
    * Whatever ``orchestrator.answer`` raises (network errors, LLM failures,
      ``EmptyScopeError``, etc.) — the route layer maps these to the
      structured error envelope.
    """
    cleaned, normalized_quality = _validate_inputs(
        content=content, quality=quality
    )

    with operation_context(client_action_id):
        async with _ASK_KASTEN_SEMAPHORE:
            # Pricing gate first — fail-fast on 402 before any orchestrator
            # work (matches chat_routes ordering).
            await _require_entitlement(user, action_id=client_action_id)

            runtime = _get_runtime(str(effective_user_id))

            # BOLA gate: cross-tenant kasten_id → 403 without leaking
            # existence. ``runtime.workspace_id`` may be ``None`` if the
            # caller has no default workspace — treat as not-found.
            _gate_kasten_ownership(kasten_id=kasten_id, runtime=runtime)

            query = _build_chat_query(
                content=cleaned,
                kasten_id=kasten_id,
                session_id=session_id,
                quality=normalized_quality,
                scope_filter=scope_filter,
                stream=False,
            )

            turn = await runtime.orchestrator.answer(
                query=query, user_id=effective_user_id
            )

        out = _serialize_turn(
            turn,
            operation_id=client_action_id,
            session_id=session_id,
            kasten_id=kasten_id,
        )
        return out.model_dump(mode="json")


async def stream_ask_kasten(
    *,
    content: str,
    user: dict,
    effective_user_id: UUID,
    client_action_id: str,
    kasten_id: UUID | None = None,
    session_id: UUID | None = None,
    quality: Literal["fast", "high"] = "fast",
    scope_filter: dict | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream RAG SSE event dicts for a Kasten-scoped query.

    Yields the raw events the orchestrator produces (``status`` /
    ``citations`` / ``token`` / ``replace`` / ``done`` / ``error``); the
    route wraps them in SSE encoding + Cloudflare-keepalive heartbeats.

    Validation, pricing, and BOLA happen BEFORE the first yield so failures
    surface as exceptions the route can translate into HTTPException — never
    as a mid-stream connection drop (which browsers render as the generic
    "network error" the user has been seeing).
    """
    cleaned, normalized_quality = _validate_inputs(
        content=content, quality=quality
    )

    with operation_context(client_action_id):
        async with _ASK_KASTEN_SEMAPHORE:
            await _require_entitlement(user, action_id=client_action_id)

            runtime = _get_runtime(str(effective_user_id))
            _gate_kasten_ownership(kasten_id=kasten_id, runtime=runtime)

            query = _build_chat_query(
                content=cleaned,
                kasten_id=kasten_id,
                session_id=session_id,
                quality=normalized_quality,
                scope_filter=scope_filter,
                stream=True,
            )

            async for event in runtime.orchestrator.answer_stream(
                query=query, user_id=effective_user_id
            ):
                yield event


# ───────────────────────────────────────────────────────────────────────────
# CLI (mirrors summarization.py _cli — debugging + Phase-E seeding)
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
        if key.strip():
            os.environ.setdefault(key.strip(), value)


def _load_local_env() -> None:
    root = Path.cwd()
    for candidate in (root / ".env", root / ".env.v2", root / "supabase" / ".env"):
        _load_env_file(candidate)
    os.environ.setdefault("DB_SCHEMA_VERSION", "v2")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Kasten-scoped RAG question and print the JSON answer.",
    )
    parser.add_argument("--content", required=True)
    parser.add_argument("--user-id", required=True, help="Supabase Auth UUID")
    parser.add_argument("--kasten-id", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument(
        "--quality", default="fast", choices=["fast", "high"]
    )
    parser.add_argument("--client-action-id", default="cli-ask-kasten")
    parser.add_argument(
        "--load-env", action="store_true", help="Load .env files first"
    )
    return parser.parse_args()


async def _cli() -> int:
    args = _parse_args()
    if args.load_env:
        _load_local_env()
    result = await run_ask_kasten_once(
        content=args.content,
        user={"sub": args.user_id},
        effective_user_id=UUID(str(args.user_id)),
        client_action_id=args.client_action_id,
        kasten_id=UUID(args.kasten_id) if args.kasten_id else None,
        session_id=UUID(args.session_id) if args.session_id else None,
        quality=args.quality,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_cli()))
