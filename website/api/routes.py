"""API routes for the web summarizer."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from website.api.auth import get_current_user, get_optional_user
from website.api.graph_cache import get_default_cache
from website.core.db_version import get_db_schema_version, use_supabase_v2
from website.core.graph_store import _SOURCE_PREFIX, get_graph  # noqa: F401  # patched by tests/integration/v2/test_kg_payload.py via monkeypatch
from website.core.graph_models import KGGraph
from website.core.persist import (
    extract_summary_parts,
    get_supabase_v2_scope,
    get_supabase_v2_scope_for_read,
)
from website.core.supabase_v2.repositories.kg_repository import KGRepository as V2KGRepository

logger = logging.getLogger("website.api")

router = APIRouter(prefix="/api")
_RATE_WINDOW = 60  # seconds
_rate_store: dict[str, list[float]] = defaultdict(list)

# In-memory graph cache (30-second TTL).
# WAVE-C 1c-A.3: the legacy ``_graph_cache`` global was dead code (never
# populated by the read path; only nulled in mutation handlers). Replaced
# by a per-user LRU + single-flight wrapper in ``website.api.graph_cache``.
# K1 (Phase 2 KG render+correctness overhaul): the anonymous file-store
# branch was retro-fitted to share the SAME UserGraphCache via the synthetic
# ``__anon__`` user id sentinel, so the dead ``_graph_cache_global`` /
# ``_graph_cache_global_ts`` globals and their mutation-handler null-sets
# were deleted. Mutation handlers now drop the ``__anon__`` cache slot
# explicitly via ``invalidate_user_graph("__anon__")``.

# WAVE-C 1c-A.4 — fields dropped from the wire payload (D-KG-9).
# Keep node ids, names, summaries, urls, tags, and the trimmed analytics
# (community, pagerank rounded). Drop verbose/internal fields the frontend
# does not render, plus everything that could leak embeddings / model info.
_TRIMMED_NODE_FIELDS: frozenset[str] = frozenset({
    "embedding",
    "embedding_model_version",
    "embedding_dim",
    "model_version",
    "score_breakdown",
    "betweenness",        # raw; expose via /api/graph/expensive only
    "closeness",          # raw; expose via /api/graph/expensive only
    "harmonic_centrality",  # S5 (T4.15): never read by the frontend
    "created_at_microseconds",
})
_TRIMMED_EDGE_FIELDS: frozenset[str] = frozenset({
    "embedding_distance",
    "raw_score",
    "score_breakdown",
    # m3 (Phase 4 audit): the file-store path (graph_store._find_links)
    # writes `tier="strong"` on every auto-link, while the v2 assembler
    # does NOT emit tier (LD-5 — client computes it from connection_strength).
    # Strip on the wire so anonymous + logged-in payloads have a single
    # consistent shape; the frontend tier-bucket is the source of truth.
    "tier",
})


def _apply_min_strength_filter(payload: dict, min_strength: float | None) -> dict:
    """Filter graph links by edge ``connection_strength`` (LD-2).

    LD-2: links whose ``connection_strength`` is ``None`` (legacy / unscored)
    PASS the filter. The threshold ONLY culls links with a numeric strength
    BELOW it. This is the NetworkX ``weight or 1.0`` convention — an unscored
    edge is visible by default, not implicitly weak.

    No-op when ``min_strength`` is None or 0.0 (return all edges).
    Pure: returns a new dict; does not mutate inputs.
    """
    if min_strength is None:
        return payload
    try:
        threshold = float(min_strength)
    except (TypeError, ValueError):
        return payload
    if threshold <= 0.0:
        return payload
    out = dict(payload)
    out["links"] = [
        link for link in payload.get("links", [])
        if link.get("connection_strength") is None
        or float(link["connection_strength"]) >= threshold
    ]
    return out


def _normalize_summary_for_wire(raw) -> dict:
    """S3 (T4.15): parse the AI-summary JSON envelope ONCE at the API boundary.

    Today the wire payload ships ``summary`` as a JSON-encoded string that the
    frontend must re-parse for every node card open. Returning a parsed dict
    with stable keys (``brief`` / ``detailed`` / ``closing``) lets the client
    short-circuit. Already-parsed dicts and plain-text fallbacks pass through
    unchanged so legacy file-store entries keep rendering.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {"brief": "", "detailed": [], "closing": ""}
    text = raw.strip()
    if not text.startswith("{"):
        return {"brief": text[:800], "detailed": [], "closing": ""}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {
                "brief": parsed.get("brief_summary", parsed.get("brief", "")),
                "detailed": parsed.get("detailed_summary", []),
                "closing": parsed.get("closing_remarks", ""),
            }
    except (TypeError, ValueError):
        pass
    return {"brief": text[:800], "detailed": [], "closing": ""}


def _trim_graph_response(payload: dict) -> dict:
    """Strip internal/verbose fields from /api/graph payload (D-KG-9).

    KEEP on nodes: id, name, group, summary, tags, url, date, node_date,
                   pagerank (rounded), community, owner, contributors.
    KEEP on links: source, target, relation, weight, link_type, description,
                   connection_strength.

    DROP everything else listed in ``_TRIMMED_*_FIELDS``.
    """
    out: dict = {}
    for key, value in payload.items():
        if key in ("nodes", "links"):
            continue
        out[key] = value

    nodes_out = []
    for node in payload.get("nodes", []) or []:
        if not isinstance(node, dict):
            nodes_out.append(node)
            continue
        nd = {k: v for k, v in node.items() if k not in _TRIMMED_NODE_FIELDS}
        # Round pagerank to 6 sig figs to compress repr without losing rank.
        if isinstance(nd.get("pagerank"), float):
            nd["pagerank"] = round(nd["pagerank"], 6)
        # S3 (T4.15): parse the AI-summary envelope at the wire boundary so the
        # client doesn't re-parse it for every panel open.
        if "summary" in nd and isinstance(nd["summary"], (str, dict)):
            nd["summary"] = _normalize_summary_for_wire(nd["summary"])
        nodes_out.append(nd)
    out["nodes"] = nodes_out

    links_out = []
    for link in payload.get("links", []) or []:
        if not isinstance(link, dict):
            links_out.append(link)
            continue
        ld = {k: v for k, v in link.items() if k not in _TRIMMED_EDGE_FIELDS}
        if isinstance(ld.get("connection_strength"), float):
            ld["connection_strength"] = round(ld["connection_strength"], 3)
        links_out.append(ld)
    out["links"] = links_out
    return out


def _enrich_graph_with_analytics(
    graph_dict: dict,
    min_strength: float | None = None,
) -> dict:
    """Add PageRank, community, and centrality metrics to graph nodes.

    Also normalizes every node's ``summary`` into the canonical JSON envelope
    so the frontend never has to defend against mixed historical shapes.

    LD-10: compute metrics on the FULL graph (NOT the strength-filtered
    subgraph) so node-importance values stay stable as the user moves the
    slider. The wire-level link cull happens AFTER enrichment, outside this
    function. ``min_strength`` is retained as a parameter for backwards
    compatibility but is ignored at the metric-input stage.

    LD-9 / A1: results memoized by BLAKE3 content hash. Two requests on the
    same topology (different sliders, different users) share one compute.
    """
    from website.core.summary_normalizer import normalize_graph_nodes
    normalize_graph_nodes(graph_dict)
    del min_strength  # LD-10: deliberately unused at metric-input stage.

    try:
        from website.core.graph_content_hash import (
            compute_graph_hash,
            get_cached_metrics,
            put_cached_metrics,
        )
        graph_hash = compute_graph_hash(graph_dict)
        metrics = get_cached_metrics(graph_hash)
        if metrics is None:
            from website.features.kg_features.analytics import compute_graph_metrics
            kg_graph = KGGraph(**graph_dict)
            metrics = compute_graph_metrics(kg_graph)
            put_cached_metrics(graph_hash, metrics)

        for node in graph_dict.get("nodes", []):
            nid = node["id"]
            node["pagerank"] = metrics.pagerank.get(nid, 0)
            node["community"] = metrics.communities.get(nid, 0)
            node["betweenness"] = metrics.betweenness.get(nid, 0)
            # C3-d: harmonic_centrality replaces closeness on the wire.
            # Closeness still emitted as 0 for back-compat (also trimmed).
            node["closeness"] = metrics.closeness.get(nid, 0)
            node["harmonic_centrality"] = metrics.harmonic.get(nid, 0)

        # A2: detect Louvain fallback (analytics.py returns num_communities=0
        # when community_multilevel raised). The frontend reads this flag to
        # show a "Community detection degraded" banner.
        node_count = len(graph_dict.get("nodes", []))
        louvain_fallback = (metrics.num_communities <= 0 and node_count > 1)
        graph_dict["meta"] = {
            **graph_dict.get("meta", {}),
            "communities": metrics.num_communities,
            "components": metrics.num_components,
            "computed_at": metrics.computed_at,
            "analytics_status": "ok",
            "louvain_fallback": louvain_fallback,
            "graph_hash": graph_hash[:16] if graph_hash else "",
        }
    except Exception as exc:
        logger.warning("Graph analytics enrichment failed: %s", exc)
        graph_dict.setdefault("meta", {})["analytics_status"] = "failed"
    return graph_dict


class AvatarUpdateRequest(BaseModel):
    avatar_id: int

    @field_validator("avatar_id")
    @classmethod
    def validate_avatar_id(cls, v: int) -> int:
        if not (0 <= v <= 59):
            raise ValueError("avatar_id must be between 0 and 59")
        return v


@router.get("/health")
async def health(request: Request):
    payload: dict = {"status": "ok"}
    monitor = getattr(request.app.state, "event_loop_monitor", None)
    if monitor is not None:
        payload["event_loop_lag"] = monitor.snapshot()

    # iter-12 T31 R4: bandit pathology metrics (5 ops-dashboard fields).
    # All collected from in-process telemetry; never expose model/score internals.
    bandit_state = getattr(request.app.state, "bandit_telemetry_snapshot", None)
    if bandit_state is not None:
        payload["bandit"] = {
            # Stuck-arm detection: argmax(α/(α+β)) switches over rolling 24h.
            # Alert if >3 after 50 pulls.
            "posterior_mode_flips_24h": bandit_state.get("posterior_mode_flips_24h"),
            # Near-uniform posterior = no learning. Alert if >1.3 after 200 pulls.
            "posterior_entropy_nats": bandit_state.get("posterior_entropy_nats"),
            # Starvation flag. Alert if <0.05 after 100 total pulls.
            "arm_pull_ratio_min_max": bandit_state.get("arm_pull_ratio_min_max"),
            # Sampling overhead. Alert if >5ms.
            "bandit_decision_latency_p99_ms": bandit_state.get("bandit_decision_latency_p99_ms"),
            # Concurrent-write health. Alert if >5%.
            "db_upsert_conflict_rate": bandit_state.get("db_upsert_conflict_rate"),
        }
    return payload


@router.get("/health/warm")
async def warm():
    """Pre-warm endpoint: triggers reranker first inference + tokenizer load.

    Called by ``ops/deploy/deploy.sh`` after the new color comes up so the
    first user request doesn't pay the BGE cold-start tax (~1-3s on a 1 vCPU
    droplet). Returns 200 with a small JSON payload regardless of whether the
    int8 model is present -- in the no-model case ``rerank_ms`` is 0 and the
    body still carries ``warmed=True`` so the deploy script's healthcheck
    succeeds.
    """
    import time as _time

    rerank_ms = 0.0
    detail = "ok"
    try:
        from website.features.rag_pipeline.rerank import cascade as cascade_mod
        from website.features.rag_pipeline.rerank.cascade import CascadeReranker

        if cascade_mod._STAGE2_SESSION is not None:
            cr = CascadeReranker()
            t0 = _time.perf_counter()
            cr.score_batch(
                "warmup query",
                [{"id": "w", "text": "warmup chunk"}],
                mode="fast",
            )
            rerank_ms = round((_time.perf_counter() - t0) * 1000, 1)
        else:
            detail = "int8_model_absent"
    except Exception as exc:  # pragma: no cover - logged for ops
        logger.warning("warm endpoint encountered %r", exc)
        detail = f"warmup_failed: {type(exc).__name__}"

    return {"warmed": True, "rerank_ms": rerank_ms, "detail": detail}


@router.get("/auth/config")
async def auth_config():
    """Return public Supabase config for client-side auth init."""
    if get_db_schema_version() == "v2":
        # β: prefer V2_* names; fall back to canonical when v1 namespace gone.
        return {
            "supabase_url": os.environ.get("SUPABASE_V2_URL", "") or os.environ.get("SUPABASE_URL", ""),
            "supabase_anon_key": os.environ.get("SUPABASE_V2_ANON_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", ""),
        }
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
    }


@router.get("/me")
async def me(
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Return the authenticated user's profile.

    v2-only: when the JWT subject is a UUID with a valid v2 scope, read profile
    fields from ``core.profiles`` via :class:`CoreRepository`. On any miss
    (no v2 scope, lookup failure, v2 not configured) fall back to the JWT
    metadata claims so the wire shape ``{id, email, name, avatar_url}`` is
    stable. Phase 8.0.4: v1 ``kg_users`` fallback removed (table dropped in
    Phase 6).

    Side-effect (best-effort): if the profile row is freshly created (per
    ``core.profiles.created_at``), schedule a ``notify_new_signup`` Slack
    alert. Idempotent across rapid /api/me retries via an in-memory dedup
    set in ``User_Activity``. Never blocks the response.
    """
    metadata = user.get("user_metadata", {})
    avatar_url = metadata.get("avatar_url", "")

    # v2 path: read profile from core.profiles via CoreRepository.
    if use_supabase_v2():
        scope = get_supabase_v2_scope_for_read(user["sub"])
        if scope is not None:
            from website.core.supabase_v2.client import get_v2_client
            from website.core.supabase_v2.repositories.core_repository import CoreRepository
            from website.features.web_monitor import maybe_fire_signup_alert

            _content_repo, profile_id, _workspace_ids = scope
            try:
                profile = CoreRepository(get_v2_client()).get_profile(profile_id)
            except Exception as exc:  # noqa: BLE001 — graceful fallback on v2 hiccup
                logger.warning("v2 /api/me profile lookup failed for %s: %s", profile_id, exc)
                profile = None

            if profile:
                try:
                    maybe_fire_signup_alert(
                        user_id=user["sub"],
                        display_name=profile.get("display_name") or metadata.get("full_name") or metadata.get("name"),
                        email=profile.get("email") or user.get("email"),
                        created_at=profile.get("created_at"),
                        country_code=request.headers.get("cf-ipcountry"),
                    )
                except Exception:  # noqa: BLE001 — signup alert must not break /api/me
                    logger.exception("maybe_fire_signup_alert raised")
                return {
                    "id": user["sub"],
                    "email": profile.get("email") or user.get("email", "") or "",
                    "name": profile.get("display_name") or metadata.get("full_name", "") or "",
                    "avatar_url": profile.get("avatar_url") or avatar_url or "",
                    "profile_source": "v2",  # Y3 (T4.9)
                }

    # Phase 8.0.3 B+: v1 ``kg_users``-backed avatar fallback removed —
    # ``public.kg_users`` was dropped in Phase 6, the get_supabase_scope
    # helper retired, and the live PUT /api/me/avatar handler writes to
    # ``core.profiles.avatar_url`` (covered by the v2 branch above).
    # Y3 (T4.9): expose profile_source so the frontend can banner when the
    # v2 lookup missed (jwt_fallback = v2 disabled or scope/profile lookup
    # failed; the user's display fields come from the JWT claims, not the DB).
    return {
        "id": user["sub"],
        "email": user.get("email", ""),
        "name": metadata.get("full_name", ""),
        "avatar_url": avatar_url,
        "profile_source": "jwt_fallback",
    }


@router.put("/me/avatar")
async def update_avatar(
    body: AvatarUpdateRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Update the authenticated user's avatar.

    Phase 8.5.R3 v2 port: writes to ``core.profiles.avatar_url`` via the
    authenticated profile id (resolved from JWT ``sub``). The product surface
    is a preset-picker (avatar_id ∈ [0, 59]) mapping to pre-built SVG assets
    under ``/artifacts/avatars/``. No file upload, no Pillow re-encode — the
    R-B research's full upload pipeline is overkill for this product shape.

    v1 fallback retired: pre-v2, this called ``KGRepository.update_user_avatar``
    against ``public.kg_users``. That table was dropped in Phase 6.
    """
    avatar_url = f"/artifacts/avatars/avatar_{body.avatar_id:02d}.svg"

    if not _is_supabase_uuid(user.get("sub")):
        raise HTTPException(status_code=400, detail="v2 avatar update requires UUID auth subject")

    scope = get_supabase_v2_scope(user["sub"])
    if scope is None:
        raise HTTPException(status_code=404, detail="No v2 profile scope")
    _content_repo, profile_id, _workspace_id = scope

    from website.core.supabase_v2.repositories.core_repository import CoreRepository
    core_repo = CoreRepository()
    updated = core_repo.update_avatar(profile_id, avatar_url)
    if not updated:
        raise HTTPException(status_code=404, detail="Profile not found")

    return {"avatar_url": avatar_url}




# Phase B read-path strength constants.
#
# Strength column precedence (per design + verified migrations): the Phase B
# scorer writes ``workspace_strength`` (_v2/46) which DRIVES RENDERING; the
# 42-era ``connection_strength`` composite is the read-path fallback for rows
# the scorer has not reached yet; the legacy ``weight`` column is ALWAYS NULL
# post-migration and is only kept as a last resort. ``None`` everywhere → a
# neutral sentinel so an unscored edge never renders as "strong".
_UNSCORED_STRENGTH_SENTINEL = 0.5  # mid-bucket; matches 42_*.sql backfill intent

# Percentile cutoffs (fraction of the workspace's weighted-edge distribution).
# Top 25% → strong, next 35% → medium, bottom 40% → weak. Mirrors both
# improvement reports' "use the workspace distribution, not fixed global
# cutoffs" guidance.
_TIER_STRONG_PCTL = 0.75
_TIER_MEDIUM_PCTL = 0.40

# Small-n fallback: with fewer than this many *weighted* edges a percentile is
# statistically unstable, so fall back to the fixed D-KG-3 cutoffs referenced
# in the kg index comment (0.7 strong / 0.4 medium).
_TIER_MIN_SAMPLE = 20
_TIER_STRONG_FIXED = 0.7
_TIER_MEDIUM_FIXED = 0.4


def _resolve_edge_strength(edge: dict) -> tuple[float, bool]:
    """Return ``(strength, was_scored)`` for one kg_edges row.

    Precedence: ``workspace_strength`` (Phase B render driver) →
    ``connection_strength`` (42-era composite fallback) → legacy ``weight``
    (always NULL post-migration) → unscored sentinel. ``was_scored`` is
    ``True`` only when a real per-workspace/composite score was present, so
    the percentile distribution is built from genuinely-scored edges and an
    unscored edge can never be tiered "strong".
    """
    for col in ("workspace_strength", "connection_strength", "weight"):
        raw = edge.get(col)
        if raw is None:
            continue
        try:
            numeric = float(raw)
        except (TypeError, ValueError):
            continue
        if numeric < 0:
            numeric = 0.0
        # workspace_strength / connection_strength are [0,1] by CHECK
        # constraint; legacy weight may be 1-10 → normalise like the prior
        # _normalize_connection_strength did so behaviour is unchanged.
        if numeric > 1.0:
            numeric = min(numeric / 10.0, 1.0)
        return numeric, col != "weight"
    return _UNSCORED_STRENGTH_SENTINEL, False


def _percentile_threshold(sorted_vals: list[float], fraction: float) -> float:
    """Value at ``fraction`` quantile of an ascending ``sorted_vals``.

    ``fraction`` in [0,1]; nearest-rank style on the sorted list. Caller
    guarantees ``sorted_vals`` is non-empty.
    """
    if fraction <= 0:
        return sorted_vals[0]
    if fraction >= 1:
        return sorted_vals[-1]
    idx = int(round(fraction * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


def _build_tier_classifier(scored_strengths: list[float]):
    """Build a ``strength -> 'strong'|'medium'|'weak'`` classifier.

    Computed ONLY from ``scored_strengths`` — the genuinely-scored edges of
    ONE workspace (BOLA: the caller passes a single workspace's edges, so the
    distribution can never leak another tenant's strengths). With < 20
    scored edges the percentile is unstable → fixed D-KG-3 cutoffs.
    """
    n = len(scored_strengths)
    if n >= _TIER_MIN_SAMPLE:
        ordered = sorted(scored_strengths)
        strong_cut = _percentile_threshold(ordered, _TIER_STRONG_PCTL)
        medium_cut = _percentile_threshold(ordered, _TIER_MEDIUM_PCTL)
        # Guard degenerate distributions (all-equal) so medium <= strong.
        if medium_cut > strong_cut:
            medium_cut = strong_cut
    else:
        strong_cut = _TIER_STRONG_FIXED
        medium_cut = _TIER_MEDIUM_FIXED

    def _classify(strength: float, was_scored: bool) -> str:
        # An unscored edge is never "strong": it did not participate in the
        # distribution and its sentinel must not masquerade as a real score.
        if not was_scored:
            return "weak"
        if strength >= strong_cut:
            return "strong"
        if strength >= medium_cut:
            return "medium"
        return "weak"

    return _classify


def _v2_assemble_graph(
    *,
    user_sub: str,
    limit: int,
    offset: int,
) -> KGGraph | None:
    """C4: edge-driven KG assembly across the caller's workspaces.

    Order of operations (C4 inversion vs the legacy page-driven path):
      1. Resolve scope (workspaces).
      2. For each workspace, fetch ALL edges (deterministic ORDER BY from B1
         fix). Collect endpoint kg_node_id set.
      3. Resolve endpoint kg_node_ids → canonical_zettel_id sets via
         chunk_node_mentions (primary) + metadata fallback (B8 fix).
      4. Batch-fetch overlay rows by canonical id (C4 new repo method).
      5. Build canonical_to_overlay from the actually-needed canonical set;
         emit nodes + links from the resolved overlays.

    LD-5: ``tier`` is NOT emitted on the wire; frontend computes it from
    ``connection_strength`` via ``tierForStrength``.

    Returns ``None`` when the user lacks a v2 scope (not configured, non-UUID
    sub, or no workspace memberships). Soft-deleted overlays are filtered by
    the repository.
    """
    scope = get_supabase_v2_scope_for_read(user_sub)
    if scope is None:
        return None
    content_repo, _profile_id, workspace_ids = scope
    kg_repo = V2KGRepository()

    nodes: list[dict] = []
    links: list[dict] = []
    canonical_to_overlay: dict[str, str] = {}
    seen_links: set[tuple[str, str, str]] = set()

    for ws_id in workspace_ids:
        # 1. Fetch edges first (deterministic order; up to `limit` per ws).
        edge_rows = kg_repo.list_workspace_edges(ws_id, limit=limit)
        if not edge_rows:
            continue
        # Phase B: resolve each edge's render strength (workspace_strength ->
        # connection_strength -> legacy weight -> sentinel) and build the
        # strong/medium/weak tier classifier from THIS workspace's scored
        # edges only. The classifier never sees another workspace's
        # strengths — BOLA isolation by construction (one ws per iteration).
        edge_strengths: dict[int, tuple[float, bool]] = {}
        for idx, edge in enumerate(edge_rows):
            strength, was_scored = _resolve_edge_strength(edge)
            edge_strengths[idx] = (strength, was_scored)
        # Resolve the bigint kg_node ids on each edge endpoint to overlay
        # node ids via kg.chunk_node_mentions -> content.canonical_chunks ->
        # canonical_zettel_id. Without this join we'd emit self-loops
        # (PR #7 C1: the prior code resolved only the evidence canonical and
        # used it for both source and target, so igraph dropped every edge
        # at analytics.py and the D-KG-1 strength filter was inert).
        endpoint_ids: set[int] = set()
        for edge in edge_rows:
            for col in ("src_node_id", "dst_node_id"):
                try:
                    endpoint_ids.add(int(edge.get(col)))
                except (TypeError, ValueError):
                    continue
        sorted_endpoint_ids = sorted(endpoint_ids)
        node_to_zettels = kg_repo.list_node_zettel_mapping(
            ws_id, sorted_endpoint_ids
        )

        # B1 FALLBACK: a workspace whose kg_nodes were upserted WITHOUT
        # kg.chunk_node_mentions rows (observed live for Naruto: 58 kg_edges,
        # 20 kg_nodes, 0 mentions) yields an EMPTY ``node_to_zettels`` for
        # every endpoint, so the primary join below resolves nothing and ALL
        # edges are dropped (the KG renders as isolated nodes). For exactly
        # the endpoint nodes the mention join did NOT resolve, recover the
        # node->canonical-zettel link from ``kg_nodes.metadata`` (the
        # ``canonical_zettel_id`` key kg_population writes at node upsert via
        # ``_node_metadata``). One extra bounded, workspace-scoped select
        # keyed by the still-unresolved endpoint ids — BOLA-safe (fenced to
        # ws_id; a foreign-tenant canonical id can never key into
        # ``canonical_to_overlay``, which only holds THIS workspace's loaded
        # overlays). Edges render when EITHER chunk_node_mentions OR this
        # metadata fallback resolves both endpoints.
        unresolved_endpoints = [
            nid for nid in sorted_endpoint_ids if not node_to_zettels.get(nid)
        ]
        node_to_canonical_meta: dict[int, list[str]] = {}
        if unresolved_endpoints:
            try:
                node_to_canonical_meta = (
                    kg_repo.list_node_canonical_zettel_metadata(
                        ws_id, unresolved_endpoints
                    )
                )
            except Exception as exc:  # noqa: BLE001 — degrade, never 500
                logger.warning(
                    "v2 graph B1 metadata fallback failed for ws=%s: %s",
                    ws_id,
                    exc,
                )
                node_to_canonical_meta = {}

        # C4: Union of canonical ids referenced by ANY edge endpoint (either
        # mention path or metadata fallback). Batch-fetch overlays by canonical
        # id — replaces the page-driven first-N-zettels approach that silently
        # dropped edges whose endpoint sat outside the first page.
        needed_canonicals: set[str] = set()
        for nid in sorted_endpoint_ids:
            for z in node_to_zettels.get(nid, []):
                needed_canonicals.add(str(z))
            for z in node_to_canonical_meta.get(nid, []):
                needed_canonicals.add(str(z))
        overlay_rows = content_repo.list_workspace_zettels_by_canonical_ids(
            ws_id, sorted(needed_canonicals)
        )
        for row in overlay_rows:
            canonical = row.get("canonical") or {}
            canonical_id = str(canonical.get("id") or row.get("canonical_zettel_id") or "")
            if not canonical_id or canonical_id in canonical_to_overlay:
                continue
            source_type = str(canonical.get("source_type") or "web").lower()
            prefix = _SOURCE_PREFIX.get(source_type, "web")
            # M6 (Phase 4 audit): NFKC-normalize the title BEFORE slug
            # derivation. Without it, a canonical title typed as NFD vs NFC
            # (or with full-width chars / ligatures) produces a different
            # slug across re-renders, which would change ``node_id`` and
            # silently desynchronise frontend ownership maps. NFKC is the
            # same canonical form as ``text_polish.normalize_tag`` (X5).
            _title_norm = unicodedata.normalize(
                "NFKC", str(canonical.get("title") or "")
            ).lower()
            slug = re.sub(r"[^a-z0-9]+", "-", _title_norm).strip("-")[:24].rstrip("-") or "untitled"
            # D4 fix: 16-hex canonical suffix for 64-bit collision space.
            # Task 4.2: detect REAL collisions (same node_id from a different
            # canonical id) and widen to [:24] (96-bit). The cheap O(n) scan
            # is bounded by the per-workspace overlay count (<5k typical) and
            # only runs at assemble time, not at request peak.
            node_id = f"{prefix}-{slug}-{canonical_id[:16]}"
            collision = next(
                (c for c, n in canonical_to_overlay.items() if n == node_id),
                None,
            )
            if collision is not None and collision != canonical_id:
                widened = f"{prefix}-{slug}-{canonical_id[:24]}"
                logger.warning(
                    "D4 node_id collision in workspace=%s; widening hash. "
                    "existing_canonical=%s new_canonical=%s old_id=%s new_id=%s",
                    ws_id, collision, canonical_id, node_id, widened,
                )
                node_id = widened
            canonical_to_overlay[canonical_id] = node_id

            brief, _detailed = extract_summary_parts(row.get("ai_summary"), None)
            pub_date = canonical.get("publication_date") or ""
            nodes.append(
                {
                    "id": node_id,
                    "name": str(canonical.get("title") or "Untitled"),
                    "group": source_type,
                    "summary": row.get("ai_summary") or "",
                    "tags": list(row.get("user_tags") or []),
                    # B7 (Phase 4 / Task 4.3): surface derived tags separately so
                    # the frontend's tag panel + filter never see them. Scorer
                    # already used both via the union baked into kg_population.
                    "derived_tags": list(row.get("derived_tags") or []),
                    "url": str(canonical.get("normalized_url") or ""),
                    "date": str(pub_date),
                    "node_date": str(pub_date),
                }
            )

        def _resolve_overlay_ids(kg_node_id: int) -> list[str]:
            ids: list[str] = []
            for zettel_id in node_to_zettels.get(kg_node_id, ()):  # type: ignore[arg-type]
                overlay = canonical_to_overlay.get(str(zettel_id))
                if overlay and overlay not in ids:
                    ids.append(overlay)
            if ids:
                return ids
            # B8 fallback: mention join resolved nothing for this node — try
            # EVERY canonical_zettel_id the metadata fallback returned (now
            # plural). Still gated by canonical_to_overlay (THIS workspace's
            # loaded overlays), so a foreign canonical id resolves to nothing.
            for meta_zettel in node_to_canonical_meta.get(kg_node_id, ()):
                overlay = canonical_to_overlay.get(str(meta_zettel))
                if overlay and overlay not in ids:
                    ids.append(overlay)
            return ids

        edges_dropped_unresolved = 0
        edges_demoted_to_comention = 0
        for idx, edge in enumerate(edge_rows):
            try:
                src_id = int(edge.get("src_node_id"))
                dst_id = int(edge.get("dst_node_id"))
            except (TypeError, ValueError):
                continue
            strength, _was_scored = edge_strengths[idx]
            # LD-5: tier is no longer emitted on the wire; frontend computes it
            # from connection_strength. _classify_tier is retained for Phase 4
            # cleanup which deletes the whole tier-classification path.
            src_overlays = _resolve_overlay_ids(src_id)
            dst_overlays = _resolve_overlay_ids(dst_id)
            if not src_overlays or not dst_overlays:
                # Endpoint resolved via NEITHER chunk_node_mentions NOR the
                # B1 metadata fallback (e.g. an orphan kg_node with no chunk
                # rows and no canonical_zettel_id in metadata) — skip rather
                # than fake a self-loop, and COUNT it so silent edge loss is
                # observable in the ops log (B1 telemetry) + Prometheus
                # (Phase 4 / Task 4.6 + 4.7).
                edges_dropped_unresolved += 1
                try:
                    from website.core.kg_metrics import kg_edge_drops_total
                    kg_edge_drops_total.labels(reason="unresolved_endpoint").inc()
                except Exception:  # noqa: BLE001 — never block on telemetry.
                    pass
                # Y1 (T4.7): 1% sampled warning so a drop storm is visible in
                # ops logs while keeping volume bounded under burst. Sample is
                # SHA-256 deterministic per (ws, src, dst): the same drop logs
                # at most once across the cluster for that triplet (sampling
                # is identical in every worker), not per process — even
                # stronger volume bound than per-process sampling.
                sample_key = f"{ws_id}:{src_id}:{dst_id}".encode()
                if int(hashlib.sha256(sample_key).hexdigest(), 16) % 100 == 0:
                    logger.warning(
                        "Y1 cross-workspace edge drop ws=%s src_kg_node=%d dst_kg_node=%d",
                        ws_id, src_id, dst_id,
                    )
                continue
            relation = str(edge.get("relation_type") or "shared_tag")
            description = edge.get("shared_tag_label")
            for src in src_overlays:
                for dst in dst_overlays:
                    if src == dst:
                        if src_id == dst_id:
                            # True self-loop (same kg_node on both ends);
                            # drop silently — no semantic meaning.
                            continue
                        # C5: two DIFFERENT kg_nodes happen to share an overlay
                        # (multi-mention chunk case). This is a legitimate
                        # cross-mention signal — preserve as co_mention link.
                        key = (src, dst, "co_mention")
                        if key in seen_links:
                            continue
                        seen_links.add(key)
                        links.append(
                            {
                                "source": src,
                                "target": dst,
                                "relation": "co_mention",
                                "weight": None,
                                "link_type": "cooccurrence",
                                "description": description,
                                "connection_strength": strength,
                            }
                        )
                        edges_demoted_to_comention += 1
                        continue
                    key = (src, dst, relation)
                    if key in seen_links:
                        continue
                    seen_links.add(key)
                    links.append(
                        {
                            "source": src,
                            "target": dst,
                            "relation": relation,
                            "weight": None,
                            "link_type": "tag",
                            "description": description,
                            "connection_strength": strength,
                        }
                    )

        # B1 telemetry: surface how many edges were dropped because NEITHER
        # the chunk_node_mentions join NOR the metadata fallback resolved an
        # endpoint, so silent edge loss (the original Naruto symptom) is
        # observable in the ops log instead of an invisibly edgeless graph.
        if edges_dropped_unresolved:
            logger.warning(
                "v2 graph edge_drop_unresolved ws=%s dropped=%d of=%d "
                "(endpoints unresolved via chunk_node_mentions + metadata "
                "fallback)",
                ws_id,
                edges_dropped_unresolved,
                len(edge_rows),
            )
        # C5 telemetry: edges promoted to co_mention (shared canonical
        # overlay across distinct kg_nodes — multi-mention chunk case).
        if edges_demoted_to_comention:
            logger.info(
                "v2 graph edges_demoted_to_comention ws=%s count=%d",
                ws_id,
                edges_demoted_to_comention,
            )

    # Use Pydantic to enforce the shape; total_nodes mirrors v1 conventions.
    try:
        return KGGraph(nodes=nodes, links=links, total_nodes=len(nodes))
    except Exception as exc:
        logger.warning("v2 graph assembly produced invalid KGGraph: %s", exc)
        return KGGraph(nodes=[], links=[], total_nodes=0)


def invalidate_user_graph(user_sub: str | None) -> int:
    """Drop all per-user /api/graph cache entries for ``user_sub``.

    D-KG-7: full-invalidate on summarize / zettel mutation. Safe to call
    with ``None`` (anonymous mutation; no-op). Returns the number of
    entries removed.
    """
    if not user_sub:
        return 0
    return get_default_cache().invalidate(user_sub)


@router.get("/graph")
async def graph_data(
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
    view: str | None = None,
    kasten_id: str | None = None,
    limit: int = 5000,
    offset: int = 0,
    min_strength: float | None = None,
):
    """Return the knowledge graph.

    Delegates to ``website.api.module_runners.view_graph.run_view_graph``
    (D6 locked 2026-05-23 — single runner is the source of truth so HTTP,
    CLI, and Phase-E callers all share the same routing).

    Query parameters:

    * ``view`` — ``my`` / ``kasten`` / ``global``. Omitted → inferred from
      auth (logged-in → ``my``, anonymous → ``global``).
    * ``kasten_id`` — UUID; required when ``view=kasten``.
    * ``limit`` / ``offset`` — pagination (1..10000 / 0..).
    * ``min_strength`` — drop links below this ``connection_strength``;
      buckets used for cache key alignment per ``graph_cache.bucket_for_strength``
      (strong ≥ 0.7, medium ≥ 0.5, weak < 0.5).

    Strict ``view=my`` semantics (new_apis1.md tightening): authenticated
    user with no v2 scope receives an explicit empty personal graph —
    NEVER silently falls through to the global file-store. Anonymous
    callers are served the file-store graph and **never** Zoro's personal
    graph (D1 locked verdict).
    """
    from uuid import UUID as _UUID

    from website.api.module_runners.view_graph import (
        KastenNotFoundError,
        run_view_graph,
    )

    limit = max(1, min(int(limit), 10000))
    offset = max(0, int(offset))

    if view is not None and view not in ("my", "kasten", "global"):
        raise HTTPException(
            status_code=400,
            detail=f"view must be one of 'my', 'kasten', 'global'; got {view!r}",
        )

    parsed_kasten_id: _UUID | None = None
    if kasten_id is not None:
        try:
            parsed_kasten_id = _UUID(str(kasten_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="kasten_id must be a valid UUID",
            ) from exc

    if view == "kasten" and parsed_kasten_id is None:
        raise HTTPException(
            status_code=400,
            detail="view=kasten requires a kasten_id query parameter",
        )

    try:
        return await run_view_graph(
            user=user,
            view=view,  # type: ignore[arg-type]
            kasten_id=parsed_kasten_id,
            limit=limit,
            offset=offset,
            min_strength=min_strength,
        )
    except KastenNotFoundError:
        # BOLA mitigation: 403 (never reveal whether the kasten exists in
        # another tenant; mirrors ask_kasten / sandbox_routes pattern).
        raise HTTPException(status_code=403, detail="Forbidden") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Phase 8.5.R3 / Phase 8 Task 4d: /api/graph/rebuild-links — HARD DELETED.
# Admin endpoint with no external callers; production link maintenance is
# event-driven (Supabase triggers, pg_cron), not REST-triggered. FastAPI's
# default 404 handles unknown URLs. If ever needed again, ship as
# ops/scripts/rebuild_links.py — one-shot ops script, never an HTTP route.
# Industry pattern: Sitecore Content Hub graph-rebuild-tracking, Neo4j LLM
# Knowledge Graph Builder, Microsoft GraphRAG — all event-driven.


def _is_supabase_uuid(value: str | None) -> bool:
    """Return True when ``value`` parses as a canonical UUID.

    Used by the v2 dual-path branches to gate v2 routing on a UUID-shaped
    auth subject / path parameter. v2 IDs are UUIDs (workspace_zettel_id);
    v1 node_ids are slug-prefixed strings (``yt-...``, ``web-...``) and
    intentionally fail this check so they fall through to the v1 path.
    """
    if not value:
        return False
    try:
        from uuid import UUID

        UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


@router.delete("/zettels/{node_id}")
async def delete_zettel(
    node_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a zettel from the authenticated user's graph.

    v2-only: requires DB v2 + UUID auth subject + UUID-shaped path parameter
    (treated as ``workspace_zettel_id``). Soft-delete flows via
    :class:`ContentRepository` so the reaper trigger handles canonical shred
    at last reference. Hard delete is intentionally NEVER performed in this
    handler (see audit fix A.3). Phase 8.0.4: v1 ``KGRepository.delete_node``
    AND the file-store fallback both removed — ``public.kg_nodes`` was
    dropped in Phase 6 and the file-store graph is the public/anonymous
    surface, not a user-owned write target. Non-UUID path params get 400.
    """
    from uuid import UUID

    if not (use_supabase_v2() and _is_supabase_uuid(user.get("sub")) and _is_supabase_uuid(node_id)):
        raise HTTPException(status_code=400, detail="Zettel delete requires v2 UUID path")

    scope = get_supabase_v2_scope(user["sub"])
    if scope is None:
        raise HTTPException(status_code=404, detail="No v2 workspace scope")
    content_repo, _profile_id, _workspace_id = scope

    try:
        # Phase 8.5.R3 SECURITY FIX: pass workspace_id so the repo's
        # compound-key match gates B-from-A cross-tenant deletion.
        ok = content_repo.soft_delete_workspace_zettel(
            UUID(node_id), workspace_id=_workspace_id,
        )
    except Exception as exc:
        logger.warning("v2 soft-delete failed for %s: %s", node_id, exc)
        ok = False
    if not ok:
        raise HTTPException(status_code=404, detail="Zettel not found")

    # D-KG-7: full-invalidate per-user cache + anon global cache.
    invalidate_user_graph(user.get("sub"))
    invalidate_user_graph("__anon__")  # K1: drop anon file-store cache slot too.
    return {"status": "ok", "workspace_zettel_id": node_id}


@router.get("/zettels/trash")
async def list_trash(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = 5000,
    offset: int = 0,
):
    """Return the authenticated user's soft-deleted zettels (trash window).

    Powers the visible Trash UI introduced by exec/DB_delete_zettel_refine--1a.
    Within the 30-day grace window (per migration 67) every previously
    soft-deleted overlay row in this user's workspace is returned with its
    canonical join so the UI can render the same card shape as the live
    list. Backed by the partial index ``idx_workspace_zettels_trash``
    (migration 66) so listing is index-supported regardless of corpus size.

    BOLA: scope is the caller's workspace only — the repo's compound-key
    query plus the v2 auth scope resolution gates cross-tenant reads.
    """
    if not (use_supabase_v2() and _is_supabase_uuid(user.get("sub"))):
        raise HTTPException(status_code=400, detail="Trash list requires v2 UUID auth")

    scope = get_supabase_v2_scope(user["sub"])
    if scope is None:
        raise HTTPException(status_code=404, detail="No v2 workspace scope")
    content_repo, _profile_id, workspace_id = scope

    limit = max(1, min(int(limit), 10000))
    offset = max(0, int(offset))

    try:
        rows = content_repo.list_workspace_zettels_trash(
            workspace_id, limit=limit, offset=offset,
        )
    except Exception as exc:
        logger.exception("list_workspace_zettels_trash failed for %s", user.get("sub"))
        raise HTTPException(status_code=500, detail="Trash list failed") from exc

    items: list[dict] = []
    for row in rows:
        canonical = row.get("canonical") or {}
        brief, detailed = extract_summary_parts(row.get("ai_summary"), None)
        items.append(
            {
                "id": str(row.get("id") or ""),
                "title": str(canonical.get("title") or "Untitled"),
                "brief_summary": brief or "",
                "detailed_summary": detailed or "",
                "tags": list(row.get("user_tags") or []),
                "source_type": str(canonical.get("source_type") or "web").lower(),
                "source_url": str(canonical.get("normalized_url") or ""),
                "added_at": str(row.get("created_at") or ""),
                "deleted_at": str(row.get("deleted_at") or ""),
                "published_at": str(canonical.get("publication_date") or ""),
            }
        )
    return JSONResponse(
        {"zettels": items, "total": len(items), "limit": limit, "offset": offset}
    )


@router.post("/zettels/{node_id}/restore")
async def restore_zettel(
    node_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Restore a soft-deleted zettel from the user's trash.

    Inverse of ``delete_zettel``. Idempotency: restoring an already-live row
    returns 404 (the row isn't in trash). BOLA: same compound-key
    (id + workspace_id) gate as soft-delete — service-role bypasses RLS, so
    we cannot rely on RLS for tenant scoping.

    The canonical may still have a row sitting in ``core.soft_delete_queue``
    from the prior soft-delete trigger. That's harmless: the reaper checks
    the orphan condition again at shred time, and now this restored zettel
    re-protects its canonical, so the reaper will skip the shred and the
    queue row eventually expires.
    """
    from uuid import UUID

    if not (use_supabase_v2() and _is_supabase_uuid(user.get("sub")) and _is_supabase_uuid(node_id)):
        raise HTTPException(status_code=400, detail="Zettel restore requires v2 UUID path")

    scope = get_supabase_v2_scope(user["sub"])
    if scope is None:
        raise HTTPException(status_code=404, detail="No v2 workspace scope")
    content_repo, _profile_id, workspace_id = scope

    try:
        ok = content_repo.restore_workspace_zettel(
            UUID(node_id), workspace_id=workspace_id,
        )
    except Exception as exc:
        logger.warning("v2 restore failed for %s: %s", node_id, exc)
        ok = False
    if not ok:
        raise HTTPException(status_code=404, detail="Zettel not found in trash")

    invalidate_user_graph(user.get("sub"))
    invalidate_user_graph("__anon__")  # K1: drop anon file-store cache slot too.
    return {"status": "ok", "workspace_zettel_id": node_id}


@router.delete("/zettels/{node_id}/forever")
async def hard_delete_zettel(
    node_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Permanently delete a zettel that is already in the trash.

    User-facing "Delete forever" affordance from the Trash UI. Distinct from
    the casual ``DELETE /api/zettels/{node_id}`` which soft-deletes a LIVE
    row. This endpoint hard-deletes a row that is already soft-deleted —
    skipping the remaining trash grace window. Refuses to hard-delete a
    live row (return 404), so a UI bug cannot bypass the soft-delete
    contract via this endpoint.

    BOLA: compound-key (id + workspace_id) gate inside the repo method.

    The repo's hard-delete fires ``trg_workspace_zettel_after_delete`` which
    re-runs the orphan check and may enqueue a canonical shred. The queue
    insert is idempotent (``ON CONFLICT DO NOTHING``).
    """
    from uuid import UUID

    if not (use_supabase_v2() and _is_supabase_uuid(user.get("sub")) and _is_supabase_uuid(node_id)):
        raise HTTPException(status_code=400, detail="Zettel hard-delete requires v2 UUID path")

    scope = get_supabase_v2_scope(user["sub"])
    if scope is None:
        raise HTTPException(status_code=404, detail="No v2 workspace scope")
    content_repo, _profile_id, workspace_id = scope

    try:
        ok = content_repo.hard_delete_workspace_zettel(
            UUID(node_id), workspace_id=workspace_id,
        )
    except Exception as exc:
        logger.warning("v2 hard-delete failed for %s: %s", node_id, exc)
        ok = False
    if not ok:
        raise HTTPException(status_code=404, detail="Zettel not found in trash")

    invalidate_user_graph(user.get("sub"))
    invalidate_user_graph("__anon__")  # K1: drop anon file-store cache slot too.
    return {"status": "ok", "workspace_zettel_id": node_id}


class ZettelUpdateRequest(BaseModel):
    """User-editable fields on a workspace overlay (v2 only).

    ``user_tags``, ``user_note``, and ``pinned`` are user-owned. ``ai_summary``
    is engine-owned; if a client sends ``ai_summary`` (legacy frontend), the
    text is rerouted to ``user_note`` so it lands in a user-editable surface
    instead of clobbering the AI-generated summary.
    """

    user_tags: list[str] | None = None
    user_note: str | None = None
    pinned: bool | None = None
    ai_summary: str | None = None  # rerouted to user_note in handler


@router.patch("/zettels/{node_id}")
async def update_zettel(
    node_id: str,
    body: ZettelUpdateRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Update user-editable fields on a workspace zettel overlay (v2 path).

    Phase 4.3 dual-path: requires DB v2 + UUID auth subject + UUID path param.
    The v1 path has no PATCH endpoint — for non-v2 callers this returns 404.
    ``ai_summary`` in the payload is intentionally redirected into
    ``user_note`` (engine-owned vs user-owned separation).
    """
    from uuid import UUID

    if not (
        use_supabase_v2()
        and _is_supabase_uuid(user.get("sub"))
        and _is_supabase_uuid(node_id)
    ):
        raise HTTPException(status_code=404, detail="Zettel update requires v2 path")

    scope = get_supabase_v2_scope(user["sub"])
    if scope is None:
        raise HTTPException(status_code=404, detail="No v2 workspace scope")
    content_repo, _profile_id, _workspace_id = scope

    # ai_summary -> user_note redirect (engine-owned vs user-owned).
    user_note = body.user_note
    if body.ai_summary is not None and user_note is None:
        user_note = body.ai_summary

    try:
        # Phase 8.5.R3 SECURITY FIX: workspace_id gates compound-key match so
        # B's PATCH against A's zettel by id no longer succeeds.
        ok = content_repo.update_workspace_zettel(
            UUID(node_id),
            workspace_id=_workspace_id,
            user_tags=body.user_tags,
            user_note=user_note,
            pinned=body.pinned,
        )
    except Exception as exc:
        logger.warning("v2 update_workspace_zettel failed for %s: %s", node_id, exc)
        raise HTTPException(status_code=500, detail="Update failed") from exc

    if not ok:
        raise HTTPException(status_code=404, detail="Zettel not found")

    # D-KG-7: full-invalidate per-user cache + anon global cache.
    invalidate_user_graph(user.get("sub"))
    invalidate_user_graph("__anon__")  # K1: drop anon file-store cache slot too.
    return {"status": "ok", "workspace_zettel_id": node_id}


class GraphQueryRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question is required")
        if len(v) > 500:
            raise ValueError("Question too long (max 500 characters)")
        return v


class GraphSearchRequest(BaseModel):
    query: str
    seed_node_id: str | None = None
    limit: int = 20

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Query is required")
        return v


# Rate limit bucket for NL queries (separate from summarize)
_query_rate_store: dict[str, list[float]] = defaultdict(list)
_QUERY_RATE_LIMIT = 5  # per minute


def _check_query_rate_limit(ip: str) -> bool:
    now = time.time()
    _query_rate_store[ip] = [t for t in _query_rate_store[ip] if now - t < _RATE_WINDOW]
    if len(_query_rate_store[ip]) >= _QUERY_RATE_LIMIT:
        return False
    _query_rate_store[ip].append(now)
    return True


@router.post("/graph/query")
async def graph_query(
    body: GraphQueryRequest,
    request: Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    """RETIRED: NL→SQL surface. 410 Gone per Phase 8.5.C-defer.

    The NL→SQL prompt vocabulary in `website.features.kg_features.nl_query`
    references the v1 schema (`public.kg_users / kg_nodes / kg_links`) — every
    table dropped in Phase 6 commit e168b38. Any successful prompt completion
    would fail at psql execution against missing tables.

    Re-enable when the prompt is ported to the v2 schema (content.canonical_*,
    kg.kg_* with proper RLS guardrails). Tracked in:
      * docs/superpowers/plans/2026-05-10-phase-8.5-hardening-additions.md (8.5.C-defer)
      * memory/project_kg_intelligence_remaining.md

    Returns 410 with RFC 8594 Sunset header + IETF Deprecation draft-09 header
    so clients can distinguish "intentionally retired" from "404 not found".
    """
    return JSONResponse(
        status_code=410,
        content={
            "error": "gone",
            "message": (
                "/api/graph/query NL→SQL surface is retired pending v2 schema "
                "port. Use /api/graph for the structured KG, or /api/rag/adhoc "
                "for free-form questions over your Kasten content."
            ),
            "v2_endpoint": None,
            "docs": "docs/db-v2/cutover-runbook.md",
        },
        headers={
            "Sunset": "Sat, 10 May 2026 00:00:00 GMT",
            "Deprecation": "@1715299200",
        },
    )
@router.post("/graph/search")
async def graph_search(
    body: GraphSearchRequest,
    request: Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    """RETIRED: 410 Gone per Phase 8.5.R3 / Phase 8 Task 4c.

    Graph search is either a frontend filter over the already-loaded /api/graph
    payload (Obsidian/Roam/Logseq pattern) or subsumed by RAG retrieval
    (/api/rag/adhoc — Tana/Mem.ai/Microsoft GraphRAG pattern). No v2 successor
    today; if a real product surface ever needs it, ship as a scope filter on
    the existing RAG endpoint, not by un-deprecating this v1 route.

    Industry pattern (2026): Notion/Zalando/Sentry deprecation conventions —
    410 with RFC 8594 Sunset + IETF Deprecation header so clients can
    distinguish intentional retirement from 404 not-found.
    """
    return JSONResponse(
        status_code=410,
        content={
            "error": "gone",
            "message": (
                "/api/graph/search is retired. Use /api/rag/adhoc for query-"
                "driven retrieval over your Kasten content, or filter the "
                "/api/graph payload client-side."
            ),
            "v2_endpoint": None,
            "docs": "docs/db-v2/cutover-runbook.md",
        },
        headers={
            "Sunset": "Sat, 10 May 2026 00:00:00 GMT",
            "Deprecation": "@1715299200",
        },
    )
