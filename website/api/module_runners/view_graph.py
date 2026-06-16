"""Runner for the knowledge-graph view pipeline.

Wraps the existing ``/api/graph`` assembly so the same logic is callable from
HTTP routes, CLI debugging tools, and (future) batch / Phase-E pre-warm
scripts. Adds two pieces the existing route does not yet have:

* **Kasten-scoped subgraph (D6)**: filter the assembled graph down to the
  members of one Kasten. Implemented by intersecting the canonical →
  workspace-overlay map with ``rag.list_kasten_zettels(kasten_id)``.
* **Strict ``view=my`` semantics (new_apis1.md tightening)**: when the
  caller is authenticated but has no v2 workspace scope, return an
  EXPLICIT empty personal graph rather than silently falling through to
  the anonymous file-store. Stops UI bugs that would otherwise show the
  global dataset to a user who explicitly asked for their own.

Routing (per D1 + D6, locked 2026-05-23):

* ``view='global'`` OR (``user is None`` AND ``view != 'kasten'``):
  file-store global graph (the canonical public/anonymous surface).
  **Anonymous reads NEVER receive Zoro's personal v2 graph** — Zoro is the
  write-side anonymous-capture sentinel only (D1 locked verdict; reading
  it for anonymous viewers would be a textbook BOLA breach).
* ``view='my'``: ``_v2_assemble_graph`` keyed by the caller's
  ``user["sub"]``. No v2 scope → empty graph with ``source='no-scope'``.
* ``view='kasten'``: requires ``user`` + ``kasten_id``. BOLA gate via
  ``rag_repo.get_kasten`` before assembly; subgraph filtered to the
  Kasten's overlay members.
* ``view`` omitted: infer ``'my'`` when authenticated, ``'global'``
  otherwise.

All cached paths flow through ``graph_cache.get_default_cache().
get_or_load`` so concurrent reads coalesce per (user, view, kasten, bucket).
The bucket cutoffs were aligned to the frontend palette (``0.7 / 0.5 /
0.3``) per the new_apis1.md reconciliation — see ``graph_cache.
bucket_for_strength``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

logger = logging.getLogger("website.api.module_runners.view_graph")


ViewKind = Literal["my", "kasten", "global"]


class KastenNotFoundError(Exception):
    """Cross-tenant / non-existent ``kasten_id`` for ``view='kasten'``.

    Route maps to **403** (BOLA pattern — never reveal whether the kasten
    exists in another tenant; same posture as
    ``ask_kasten.KastenNotFoundError``).
    """

    def __init__(self, kasten_id: str) -> None:
        super().__init__(f"Kasten {kasten_id} not found in caller's workspace")
        self.kasten_id = kasten_id


# ───────────────────────────────────────────────────────────────────────────
# Lazy facades (heavy imports deferred to call time)
# ───────────────────────────────────────────────────────────────────────────


def _routes_module():
    """Import the routes module once; reused for v2 assembly + enrichment.

    Single source of truth — the assembler / enricher / filter live next to
    the existing ``/api/graph`` handler so changes there are immediately
    visible here. (Future iteration may move these to
    ``website/api/_graph_assembly.py`` to avoid the route→runner import.)
    """
    from website.api import routes as _routes

    return _routes


def _file_store_graph() -> dict[str, Any]:
    from website.core.graph_store import get_graph as _get

    return _get()


def _community_repository() -> Any:
    from website.core.supabase_v2.repositories.community_repository import (
        CommunityGraphRepository,
    )

    return CommunityGraphRepository()


def _rag_repository() -> Any:
    from website.core.supabase_v2.repositories.rag_repository import (
        RAGRepository,
    )

    return RAGRepository()


def _get_v2_scope(user_sub: str) -> Any:
    from website.core.persist import get_supabase_v2_scope as _impl

    return _impl(user_sub)


def _use_supabase_v2() -> bool:
    from website.core.db_version import use_supabase_v2 as _impl

    return _impl()


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────


def _empty_personal_graph(user_sub: str | None) -> dict[str, Any]:
    """Explicit empty graph for authenticated users without a v2 scope.

    new_apis1.md tightening: this is what we return INSTEAD of silently
    falling through to the global file-store when the user asked for
    ``view=my``. The frontend renders an empty state ("No zettels yet — add
    one to see your graph") rather than showing strangers' data.
    """
    return {
        "nodes": [],
        "links": [],
        "total_nodes": 0,
        "meta": {
            "view": "my",
            "source": "no-scope",
            "user_sub": user_sub,
        },
    }


def _resolve_view(user: dict | None, view: ViewKind | None) -> ViewKind:
    """Infer the view kind for back-compat callers that don't pass it."""
    if view in ("my", "kasten", "global"):
        return view
    if view is not None:
        raise ValueError(
            f"view must be one of 'my', 'kasten', 'global'; got {view!r}"
        )
    return "my" if user is not None else "global"


# ───────────────────────────────────────────────────────────────────────────
# Subgraph filter — Kasten-scoped (new)
# ───────────────────────────────────────────────────────────────────────────


def _filter_graph_to_kasten_members(
    *,
    payload: dict[str, Any],
    kasten_members: set[str],
) -> dict[str, Any]:
    """Intersect a v2 graph payload with a Kasten's overlay membership set.

    ``kasten_members`` is the set of ``workspace_zettel_id`` strings the
    Kasten owns. Node ids in the assembler include the canonical-id
    suffix; we filter on ``node['id']`` directly against the overlay-id-
    derived node ids that ``_v2_assemble_graph`` produces.

    Returns a NEW dict; never mutates the input.
    """
    # _v2_assemble_graph emits node ids of shape ``{prefix}-{slug}-{canonical[:8]}``
    # — we can't match by overlay id directly. The caller passes the set of
    # canonical_zettel_ids the Kasten owns instead (re-derived via the RPC
    # join below).
    surviving_node_ids: set[str] = set()
    nodes_out: list[dict[str, Any]] = []
    for node in payload.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id", ""))
        # node ids end in "-{canonical[:8]}" — match by suffix against the
        # 8-char canonical-id prefix set.
        canonical_suffix = nid.rsplit("-", 1)[-1]
        if canonical_suffix in kasten_members:
            surviving_node_ids.add(nid)
            nodes_out.append(node)

    links_out: list[dict[str, Any]] = []
    for link in payload.get("links", []) or []:
        if not isinstance(link, dict):
            continue
        src = str(link.get("source", ""))
        dst = str(link.get("target", ""))
        if src in surviving_node_ids and dst in surviving_node_ids:
            links_out.append(link)

    out = dict(payload)
    out["nodes"] = nodes_out
    out["links"] = links_out
    out["total_nodes"] = len(nodes_out)
    return out


def _kasten_canonical_prefixes(
    *, rag_repo: Any, kasten_id: UUID
) -> set[str]:
    """Return the 8-char canonical-id prefix set for a Kasten's members.

    ``rag.list_kasten_zettels`` (Phase 1.A RPC) returns the workspace_zettel
    + canonical join — we extract ``canonical_zettel_id`` and keep just the
    first 8 chars (matching the suffix ``_v2_assemble_graph`` embeds in
    every node id). Lossless: canonical ids are full UUIDs and 8 hex chars
    have ~4 billion-entry collision space, comfortably above expected
    Kasten sizes.
    """
    rows = rag_repo.list_kasten_zettels(kasten_id) or []
    prefixes: set[str] = set()
    for row in rows:
        cz = row.get("canonical_zettel_id") or row.get("canonical_id")
        if not cz:
            continue
        # _v2_assemble_graph uses canonical_id[:8] of the dashed UUID form, so
        # we match the dashed-form first 8 chars to keep Kasten membership keys
        # aligned with the assembler's node-id derivation.
        prefixes.add(str(cz)[:8])
    return prefixes


# ───────────────────────────────────────────────────────────────────────────
# Public coroutine
# ───────────────────────────────────────────────────────────────────────────


async def run_view_graph(
    *,
    user: dict | None,
    view: ViewKind | None = None,
    kasten_id: UUID | None = None,
    limit: int = 5000,
    offset: int = 0,
    min_strength: float | None = None,
) -> dict[str, Any]:
    """Render the knowledge-graph view per the routing rules in the module docstring.

    Returns a dict with at minimum ``nodes``, ``links``, ``total_nodes``,
    ``meta`` (matches the existing ``/api/graph`` wire shape). ``meta`` is
    extended with ``view`` and (for ``view='kasten'``) ``kasten_id`` so the
    frontend can confirm what it received.

    Raises:
        ``KastenNotFoundError`` when ``view='kasten'`` and the kasten_id
            isn't owned by the caller's workspace (route → 403).
        ``ValueError`` for malformed view literals or limit/offset bounds.
    """
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    # Clamp to the same bounds the route uses (1..10000) so a runner caller
    # cannot bypass scale guards by passing limit=10**9.
    limit = min(limit, 10000)

    resolved_view = _resolve_view(user, view)
    routes_mod = _routes_module()

    if resolved_view == "kasten" and kasten_id is None:
        raise ValueError("view='kasten' requires a kasten_id")

    # ── view='global' ──────────────────────────────────────────────────
    # Part B (Phase 1, opt-OUT, Rev 3): Global IS the PUBLIC community graph,
    # built from the forced-predicate wrapper (is_private=false workspace_zettels
    # only, no user_id, deduped by canonical). The file-store seed is RETIRED
    # from the live path — there is real community data. An empty community
    # surfaces the empty-state overlay client-side (Task 1.6); we NEVER fall
    # back to the file-store. Zoro's personal v2 graph is still NEVER served
    # to anonymous viewers (D1 verdict unchanged; the community RPC strips
    # user_id at the DB layer so no BOLA breach is possible).
    if resolved_view == "global":
        async def _load_global() -> dict[str, Any]:
            community = await asyncio.to_thread(
                _community_repository().get_community_graph,
                limit=limit,
                min_strength=0.0 if min_strength is None else min_strength,
            )
            payload = routes_mod._enrich_graph_with_analytics(community, min_strength=None)
            payload = routes_mod._trim_graph_response(payload)
            payload.setdefault("meta", {})["view"] = "global"
            payload["meta"]["source"] = "community"
            return payload

        if not _is_cacheable_page(limit, offset):
            uncached = await _load_global()
            return routes_mod._apply_min_strength_filter(uncached, min_strength)
        cache = _get_default_cache()
        # Fold the cross-worker version counter into the bucket so a make-private/
        # make-public bump invalidates every worker's per-process cache. Reading
        # the counter is one tiny indexed SELECT (TTL-bounded by the cache).
        try:
            version = await asyncio.to_thread(_community_repository().read_cache_version)
        except Exception:  # noqa: BLE001 — counter read must never break serving
            version = 0
        bucket = _bucket_label_global(min_strength) + f":v{version}"
        cached = await cache.get_or_load("__community__", bucket, _load_global)
        return routes_mod._apply_min_strength_filter(cached, min_strength)

    # Beyond this point we need an authenticated user. Anonymous +
    # view='my' (or 'kasten') → explicit empty personal graph per the
    # D1 verdict + new_apis1.md strict semantics. We deliberately do NOT
    # fall through to the global file-store here: callers who asked for
    # "my" must not silently receive a broader set than they requested.
    if user is None:
        return _empty_personal_graph(None)

    user_sub = str(user.get("sub") or "")

    # ── view='my' — strict semantics per new_apis1.md ───────────────────
    if resolved_view == "my":
        if not _use_supabase_v2():
            return _empty_personal_graph(user_sub)

        # LD-10: enrich on the FULL graph (no min_strength inside the cached
        # loader) so different exact thresholds within the same bucket can't
        # stale-bind. The per-request exact filter is applied AFTER the cache
        # lookup. Matches the global anon branch's K1+LD-10 wiring.
        async def _load_my() -> dict[str, Any]:
            v2_graph = routes_mod._v2_assemble_graph(
                user_sub=user_sub, limit=limit, offset=offset
            )
            if v2_graph is None:
                # Strict: no v2 scope → empty personal graph, NOT global.
                return _empty_personal_graph(user_sub)
            payload = routes_mod._enrich_graph_with_analytics(
                v2_graph.model_dump(), min_strength=None
            )
            payload = routes_mod._trim_graph_response(payload)
            payload.setdefault("meta", {})["view"] = "my"
            payload["meta"]["source"] = "v2"
            return payload

        # LD-7: bypass cache for non-default pagination.
        if not _is_cacheable_page(limit, offset):
            uncached = await _load_my()
            return routes_mod._apply_min_strength_filter(uncached, min_strength)
        cache = _get_default_cache()
        bucket = _bucket_label_my(min_strength, limit=limit, offset=offset)
        cached = await cache.get_or_load(user_sub, bucket, _load_my)
        return routes_mod._apply_min_strength_filter(cached, min_strength)

    # ── view='kasten' — BOLA gate + assemble + filter ────────────────────
    # Resolve caller's workspace first; without it, no kasten can possibly
    # belong to them (treat as not-found per BOLA pattern).
    scope = _get_v2_scope(user_sub)
    if scope is None:
        raise KastenNotFoundError(str(kasten_id))
    _content_repo, _profile_id, workspace_id = scope

    rag_repo = _rag_repository()
    kasten_row = await asyncio.to_thread(
        rag_repo.get_kasten, kasten_id, workspace_id
    )
    if kasten_row is None:
        raise KastenNotFoundError(str(kasten_id))

    # LD-10: enrich on the FULL graph (no min_strength inside the cached
    # loader) so different exact thresholds within the same bucket can't
    # stale-bind. The kasten-subgraph intersection still happens inside the
    # loader (it's an identity-preserving filter on canonical-id prefixes,
    # not a strength filter). The per-request strength filter is applied
    # AFTER the cache lookup.
    async def _load_kasten() -> dict[str, Any]:
        v2_graph = routes_mod._v2_assemble_graph(
            user_sub=user_sub, limit=limit, offset=offset
        )
        if v2_graph is None:
            return {
                "nodes": [],
                "links": [],
                "total_nodes": 0,
                "meta": {
                    "view": "kasten",
                    "source": "no-scope",
                    "kasten_id": str(kasten_id),
                },
            }
        # Re-derive the Kasten's overlay canonical prefixes (cheap RPC).
        kasten_members = await asyncio.to_thread(
            _kasten_canonical_prefixes,
            rag_repo=rag_repo,
            kasten_id=kasten_id,
        )
        # Enrich first (analytics on the per-user graph), THEN intersect to
        # the Kasten subgraph — that way pagerank/community ids reflect the
        # workspace context the Kasten lives in.
        payload = routes_mod._enrich_graph_with_analytics(
            v2_graph.model_dump(), min_strength=None
        )
        payload = _filter_graph_to_kasten_members(
            payload=payload, kasten_members=kasten_members
        )
        payload = routes_mod._trim_graph_response(payload)
        payload.setdefault("meta", {})["view"] = "kasten"
        payload["meta"]["source"] = "v2"
        payload["meta"]["kasten_id"] = str(kasten_id)
        return payload

    # LD-7: bypass cache for non-default pagination.
    if not _is_cacheable_page(limit, offset):
        uncached = await _load_kasten()
        return routes_mod._apply_min_strength_filter(uncached, min_strength)
    cache = _get_default_cache()
    bucket = _bucket_label_kasten(min_strength, kasten_id, limit=limit, offset=offset)
    cached = await cache.get_or_load(user_sub, bucket, _load_kasten)
    return routes_mod._apply_min_strength_filter(cached, min_strength)


def _get_default_cache() -> Any:
    from website.api.graph_cache import get_default_cache

    return get_default_cache()


# K2 + LD-7: only the canonical default page is cached. Non-default pagination
# bypasses cache entirely to avoid cardinality explosion (every distinct
# limit/offset would otherwise occupy a slot in the per-user LRU).
_DEFAULT_LIMIT = 5000
_DEFAULT_OFFSET = 0


def _is_cacheable_page(limit: int, offset: int) -> bool:
    """LD-7: only the default (5000, 0) page is cacheable."""
    return limit == _DEFAULT_LIMIT and offset == _DEFAULT_OFFSET


def _bucket_label_my(
    min_strength: float | None, *, limit: int = _DEFAULT_LIMIT, offset: int = _DEFAULT_OFFSET
) -> str:
    from website.api.graph_cache import bucket_for_strength

    return f"my:{bucket_for_strength(min_strength)}:{limit}:{offset}"


def _bucket_label_kasten(
    min_strength: float | None,
    kasten_id: UUID,
    *,
    limit: int = _DEFAULT_LIMIT,
    offset: int = _DEFAULT_OFFSET,
) -> str:
    from website.api.graph_cache import bucket_for_strength

    return f"kasten:{kasten_id}:{bucket_for_strength(min_strength)}:{limit}:{offset}"


def _bucket_label_global(
    min_strength: float | None, *, limit: int = _DEFAULT_LIMIT, offset: int = _DEFAULT_OFFSET
) -> str:
    """Base bucket key for the community global branch (versioned suffix appended at call site)."""
    from website.api.graph_cache import bucket_for_strength

    return f"global:{bucket_for_strength(min_strength)}:{limit}:{offset}"


# ───────────────────────────────────────────────────────────────────────────
# CLI (debugging + Phase-E pre-warm scripts)
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
        description="Render a knowledge-graph view (global / my / kasten).",
    )
    parser.add_argument(
        "--view", default=None, choices=["my", "kasten", "global"]
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Supabase Auth UUID (omit for anonymous → global)",
    )
    parser.add_argument(
        "--kasten-id", default=None, help="Required when --view=kasten"
    )
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--min-strength", type=float, default=None,
        help="Drop links below this connection_strength (0..1)",
    )
    parser.add_argument(
        "--load-env", action="store_true", help="Load .env files first"
    )
    return parser.parse_args()


async def _cli() -> int:
    args = _parse_args()
    if args.load_env:
        _load_local_env()
    user = {"sub": args.user_id} if args.user_id else None
    result = await run_view_graph(
        user=user,
        view=args.view,
        kasten_id=UUID(args.kasten_id) if args.kasten_id else None,
        limit=args.limit,
        offset=args.offset,
        min_strength=args.min_strength,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_cli()))
