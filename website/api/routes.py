"""API routes for the web summarizer."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from website.core.pipeline import summarize_url
from website.core.graph_store import add_node, get_graph

logger = logging.getLogger("website.api")

router = APIRouter(prefix="/api")

# Simple in-memory rate limiter: {ip: [timestamps]}
_rate_store: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 10  # requests per minute
_RATE_WINDOW = 60  # seconds


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


@router.get("/graph")
async def graph_data():
    """Return the current knowledge graph (includes runtime-added nodes)."""
    return get_graph()


@router.post("/summarize")
async def summarize(body: SummarizeRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please wait a minute before trying again.",
        )

    logger.info("Summarize request from %s: %s", ip, body.url)

    try:
        result = await summarize_url(body.url)

        # Add to knowledge graph
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
            logger.warning("Failed to add node to KG: %s", kg_err)

        return result
    except Exception as exc:
        logger.error("Summarization failed for %s: %s", body.url, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process URL: {exc}",
        )
