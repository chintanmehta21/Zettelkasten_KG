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
from website.core.supabase_kg import is_supabase_configured, KGRepository, KGNodeCreate

logger = logging.getLogger("website.api")

# Lazy-init Supabase repository + user ID (only when Supabase is configured)
_supabase_repo: KGRepository | None = None
_supabase_user_id: str | None = None


def _get_supabase(user_id_override: str | None = None) -> tuple[KGRepository, str] | None:
    """Return (repo, user_id) if Supabase is configured, else None."""
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
    return {
        "id": user["sub"],
        "email": user.get("email", ""),
        "name": metadata.get("full_name", ""),
        "avatar_url": metadata.get("avatar_url", ""),
    }


@router.get("/graph")
async def graph_data(user: Annotated[dict | None, Depends(get_optional_user)] = None):
    """Return the knowledge graph — cached Supabase if configured, else file store."""
    global _graph_cache, _graph_cache_ts

    now = time.time()
    if _graph_cache is not None and (now - _graph_cache_ts) < _GRAPH_CACHE_TTL:
        return _graph_cache

    sb = _get_supabase(user_id_override=user["sub"] if user else None)
    if sb:
        repo, user_id = sb
        try:
            from uuid import UUID
            graph = repo.get_graph(UUID(user_id))
            result = graph.model_dump()
            _graph_cache = result
            _graph_cache_ts = now
            return result
        except Exception as exc:
            logger.warning("Supabase graph fetch failed, falling back: %s", exc)

    result = get_graph()
    _graph_cache = result
    _graph_cache_ts = now
    return result


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
                    repo.add_node(UUID(user_id), node_create)
                    _graph_cache = None  # invalidate cache
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
