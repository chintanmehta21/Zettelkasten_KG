"""API routes for the web summarizer."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from website.api.auth import get_current_user, get_optional_user
from website.core.pipeline import summarize_url
from website.core.graph_store import add_node, get_graph
from website.core.supabase_kg import is_supabase_configured, KGRepository, KGNodeCreate, KGGraph

logger = logging.getLogger("website.api")

# Lazy-init Supabase repository + user ID (only when Supabase is configured)
_supabase_repo: KGRepository | None = None
_supabase_user_id: str | None = None


def _get_supabase(user_id_override: str | None = None) -> tuple[KGRepository, str] | None:
    """Return (repo, user_id) if Supabase is configured, else None.

    When ``user_id_override`` is the Supabase Auth UUID of an
    authenticated user, we first look for an existing kg_users row
    with that ID.  If none exists, we check whether the legacy
    default user ("naruto") can be claimed — i.e. its render_user_id
    is updated to the real Auth UUID so all existing zettels become
    accessible under the authenticated identity.
    """
    global _supabase_repo, _supabase_user_id
    if not is_supabase_configured():
        return None
    if _supabase_repo is None:
        try:
            _supabase_repo = KGRepository()
        except Exception as exc:
            logger.warning("Supabase init failed, falling back to file store: %s", exc)
            return None
    if user_id_override:
        try:
            # Fast path: user already exists with this Auth UUID
            existing = _supabase_repo.get_user_by_render_id(user_id_override)
            if existing:
                return _supabase_repo, str(existing.id)

            # Claim the legacy default user if it still has the
            # placeholder render_user_id ("naruto")
            legacy = _supabase_repo.get_user_by_render_id("naruto")
            if legacy:
                claimed = _supabase_repo.claim_user("naruto", user_id_override)
                if claimed:
                    # Invalidate cached default user_id
                    _supabase_user_id = None
                    return _supabase_repo, str(claimed.id)

            # No legacy user to claim — create fresh
            user = _supabase_repo.get_or_create_user(user_id_override, display_name="Web User")
            return _supabase_repo, str(user.id)
        except Exception as exc:
            logger.warning("Supabase user lookup failed: %s", exc)
            return None
    if _supabase_user_id is None:
        try:
            user = _supabase_repo.get_or_create_user("naruto", display_name="Naruto")
            _supabase_user_id = str(user.id)
        except Exception as exc:
            logger.warning("Supabase default user init failed: %s", exc)
            return None
    return _supabase_repo, _supabase_user_id

router = APIRouter(prefix="/api")

# Simple in-memory rate limiter: {ip: [timestamps]}
_rate_store: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 10  # requests per minute
_RATE_WINDOW = 60  # seconds

# In-memory graph cache (30-second TTL)
_graph_cache: dict | None = None
_graph_cache_ts: float = 0
_GRAPH_CACHE_TTL = 30  # seconds


def _enrich_graph_with_analytics(graph_dict: dict) -> dict:
    """Add PageRank, community, and centrality metrics to graph nodes."""
    try:
        from website.features.kg_features.analytics import compute_graph_metrics
        kg_graph = KGGraph(**graph_dict)
        metrics = compute_graph_metrics(kg_graph)

        for node in graph_dict.get("nodes", []):
            nid = node["id"]
            node["pagerank"] = metrics.pagerank.get(nid, 0)
            node["community"] = metrics.communities.get(nid, 0)
            node["betweenness"] = metrics.betweenness.get(nid, 0)
            node["closeness"] = metrics.closeness.get(nid, 0)

        graph_dict["meta"] = {
            "communities": metrics.num_communities,
            "components": metrics.num_components,
            "computed_at": metrics.computed_at,
        }
    except Exception as exc:
        logger.warning("Graph analytics enrichment failed: %s", exc)
    return graph_dict


class SummarizeRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL is required")
        if len(v) > 2048:
            raise ValueError("URL too long (max 2048 characters)")
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class AvatarUpdateRequest(BaseModel):
    avatar_id: int

    @field_validator("avatar_id")
    @classmethod
    def validate_avatar_id(cls, v: int) -> int:
        if not (0 <= v <= 59):
            raise ValueError("avatar_id must be between 0 and 29")
        return v


def _check_rate_limit(ip: str) -> bool:
    """Return True if the request is allowed."""
    now = time.time()
    # Prune old timestamps
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < _RATE_WINDOW]
    if len(_rate_store[ip]) >= _RATE_LIMIT:
        return False
    _rate_store[ip].append(now)
    return True


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/auth/config")
async def auth_config():
    """Return public Supabase config for client-side auth init."""
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
    }


@router.get("/me")
async def me(user: Annotated[dict, Depends(get_current_user)]):
    """Return the authenticated user's profile."""
    metadata = user.get("user_metadata", {})
    avatar_url = metadata.get("avatar_url", "")

    # Prefer avatar from kg_users table (set via PUT /api/me/avatar)
    sb = _get_supabase(user_id_override=user["sub"])
    if sb:
        repo, _ = sb
        kg_user = repo.get_user_by_render_id(user["sub"])
        if kg_user and kg_user.avatar_url:
            avatar_url = kg_user.avatar_url

    return {
        "id": user["sub"],
        "email": user.get("email", ""),
        "name": metadata.get("full_name", ""),
        "avatar_url": avatar_url,
    }


@router.put("/me/avatar")
async def update_avatar(
    body: AvatarUpdateRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Update the authenticated user's avatar."""
    avatar_url = f"/artifacts/avatars/avatar_{body.avatar_id:02d}.svg"

    sb = _get_supabase(user_id_override=user["sub"])
    if not sb:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    repo, _ = sb
    updated = repo.update_user_avatar(user["sub"], avatar_url)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    return {"avatar_url": avatar_url}


# Separate caches for global vs per-user views
_graph_cache_global: dict | None = None
_graph_cache_global_ts: float = 0


@router.get("/graph")
async def graph_data(
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
    view: str | None = None,
):
    """Return the knowledge graph.

    - Default (no view param, or unauthenticated): global graph
    - ?view=my: authenticated user's personal graph
    - ?view=global: explicit global graph (all users combined)
    """
    global _graph_cache, _graph_cache_ts, _graph_cache_global, _graph_cache_global_ts

    now = time.time()
    is_personal = view == "my" and user is not None

    if is_personal:
        # Per-user graph — no global cache, always fresh per user
        sb = _get_supabase(user_id_override=user["sub"])
        if sb:
            repo, user_id = sb
            try:
                from uuid import UUID
                graph = repo.get_graph(UUID(user_id))
                return _enrich_graph_with_analytics(graph.model_dump())
            except Exception as exc:
                logger.warning("Supabase user graph fetch failed, falling back: %s", exc)
        return _enrich_graph_with_analytics(get_graph())

    # Global graph (default for all users including anonymous)
    if _graph_cache_global is not None and (now - _graph_cache_global_ts) < _GRAPH_CACHE_TTL:
        return _graph_cache_global

    sb = _get_supabase()
    if sb:
        repo, _ = sb
        try:
            graph = repo.get_global_graph()
            result = _enrich_graph_with_analytics(graph.model_dump())
            _graph_cache_global = result
            _graph_cache_global_ts = now
            return result
        except Exception as exc:
            logger.warning("Supabase global graph fetch failed, falling back: %s", exc)

    result = _enrich_graph_with_analytics(get_graph())
    _graph_cache_global = result
    _graph_cache_global_ts = now
    return result


@router.post("/graph/rebuild-links")
async def rebuild_links(user: Annotated[dict | None, Depends(get_optional_user)] = None):
    """Rebuild all tag-based links for a user (or default user).

    Deletes existing links and re-creates them from shared tags.
    """
    global _graph_cache_global, _graph_cache_global_ts

    sb = _get_supabase(user_id_override=user["sub"] if user else None)
    if not sb:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    repo, user_id = sb
    try:
        from uuid import UUID
        count = repo.rebuild_links(UUID(user_id))
        _graph_cache_global = None
        _graph_cache_global_ts = 0
        return {"status": "ok", "links_created": count, "user_id": user_id}
    except Exception as exc:
        logger.error("Rebuild links failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to rebuild links: {exc}")


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
    """Natural-language query against the knowledge graph (M4)."""
    ip = request.client.host if request.client else "unknown"
    if not _check_query_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many queries. Wait a minute.")

    sb = _get_supabase(user_id_override=user["sub"] if user else None)
    if not sb:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    repo, user_id = sb
    try:
        from uuid import UUID
        from website.features.kg_features.nl_query import NLGraphQuery, NLQueryError

        query_engine = NLGraphQuery(repo._client)
        result = await query_engine.ask(body.question, UUID(user_id))
        return result.model_dump()
    except Exception as exc:
        if hasattr(exc, "status_code"):
            raise HTTPException(status_code=exc.status_code, detail=exc.user_message)
        logger.error("Graph query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Query failed. Try rephrasing.")


@router.post("/graph/search")
async def graph_search(
    body: GraphSearchRequest,
    request: Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
):
    """Hybrid search across the knowledge graph (M6)."""
    ip = request.client.host if request.client else "unknown"
    if not _check_query_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many queries. Wait a minute.")

    sb = _get_supabase(user_id_override=user["sub"] if user else None)
    if not sb:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    repo, user_id = sb
    try:
        from website.features.kg_features.retrieval import hybrid_search

        results = hybrid_search(
            supabase_client=repo._client,
            user_id=user_id,
            query=body.query,
            seed_node_id=body.seed_node_id,
            limit=body.limit,
        )
        return {"results": [r.model_dump() for r in results]}
    except Exception as exc:
        logger.error("Graph search failed: %s", exc)
        raise HTTPException(status_code=500, detail="Search failed.")


@router.post("/summarize")
async def summarize(body: SummarizeRequest, request: Request, user: Annotated[dict | None, Depends(get_optional_user)] = None):
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please wait a minute before trying again.",
        )

    logger.info("Summarize request from %s: %s", ip, body.url)

    try:
        result = await summarize_url(body.url)

        # Add to knowledge graph — file store (always) + Supabase (if configured)
        try:
            node_id = add_node(
                title=result["title"],
                source_type=result["source_type"],
                source_url=result["source_url"],
                summary=result.get("brief_summary") or result["summary"][:200],
                tags=result.get("tags", []),
            )
            result["node_id"] = node_id
        except Exception as kg_err:
            logger.warning("Failed to add node to file KG: %s", kg_err)

        # Dual-write to Supabase
        sb = _get_supabase(user_id_override=user["sub"] if user else None)
        if sb:
            repo, user_id = sb
            try:
                import re
                from uuid import UUID
                from website.core.graph_store import _SOURCE_PREFIX

                prefix = _SOURCE_PREFIX.get(result["source_type"], "web")
                slug = re.sub(r"[^a-z0-9]+", "-", result["title"].lower()).strip("-")[:24].rstrip("-")
                sb_node_id = f"{prefix}-{slug}"

                node_create = KGNodeCreate(
                    id=sb_node_id,
                    name=result["title"],
                    source_type=result["source_type"],
                    tags=result.get("tags", []),
                    url=result["source_url"],
                    summary=result.get("brief_summary") or result["summary"][:200],
                )
                if not repo.node_exists(UUID(user_id), result["source_url"]):
                    # Generate embedding for the summary (M2)
                    try:
                        from website.features.kg_features.embeddings import generate_embedding
                        brief = result.get("brief_summary") or result["summary"][:500]
                        embedding = generate_embedding(brief)
                        if embedding:
                            node_create.metadata["embedding_model"] = "gemini-embedding-001"
                    except Exception as emb_err:
                        logger.warning("Embedding generation failed: %s", emb_err)
                        embedding = []

                    repo.add_node(UUID(user_id), node_create)

                    # Store embedding if generated
                    if embedding:
                        try:
                            repo._client.table("kg_nodes").update(
                                {"embedding": embedding}
                            ).eq("user_id", str(user_id)).eq("id", sb_node_id).execute()
                        except Exception as emb_store_err:
                            logger.warning("Embedding storage failed: %s", emb_store_err)

                    # Entity extraction (M1) — async, non-blocking
                    try:
                        import asyncio
                        from website.features.kg_features.entity_extractor import EntityExtractor

                        async def _extract_entities():
                            try:
                                extractor = EntityExtractor()
                                brief = result.get("brief_summary") or result["summary"][:500]
                                extraction = await extractor.extract(brief, result["title"])
                                if extraction.entities:
                                    # Store entities in node metadata
                                    entities_data = [e.model_dump() for e in extraction.entities]
                                    repo._client.table("kg_nodes").update(
                                        {"metadata": {**node_create.metadata, "entities": entities_data}}
                                    ).eq("user_id", str(user_id)).eq("id", sb_node_id).execute()
                                    logger.info("Extracted %d entities for %s", len(extraction.entities), sb_node_id)
                            except Exception as ext_err:
                                logger.warning("Entity extraction failed: %s", ext_err)

                        asyncio.create_task(_extract_entities())
                    except Exception as m1_err:
                        logger.warning("Entity extraction setup failed: %s", m1_err)

                    _graph_cache_global = None  # invalidate global cache
                    _graph_cache_global_ts = 0
                    logger.info("Added node %s to Supabase", sb_node_id)
            except Exception as sb_err:
                logger.warning("Failed to add node to Supabase: %s", sb_err)

        return result
    except Exception as exc:
        logger.error("Summarization failed for %s: %s", body.url, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process URL: {exc}",
        )
