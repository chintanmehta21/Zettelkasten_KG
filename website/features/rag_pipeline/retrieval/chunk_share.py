"""iter-08 Phase 4: per-Kasten chunk-share anti-magnet.

Replaces the dead kasten_freq prior (RES-2: floor=50, never crossed).
Normalisation: rrf_score *= 1/sqrt(chunk_count_per_node). Punishes
chunk-count-rich magnets (yt-effective-public-speakin = 16 chunks)
while leaving small zettels untouched.
"""
from __future__ import annotations

import math
import os
from typing import Any
from uuid import UUID

from cachetools import TTLCache


class ChunkShareStore:
    def __init__(
        self,
        supabase: Any | None = None,
        *,
        ttl_seconds: float = 60.0,
    ):
        if supabase is None:
            from website.core.supabase_kg.client import get_supabase_client
            supabase = get_supabase_client()
        self._supabase = supabase
        # iter-08 G4: TTLCache so stale chunk-counts auto-recover within ttl.
        # Mirrors cachetools usage in query/metadata.py:71.
        self._cache: TTLCache = TTLCache(maxsize=128, ttl=ttl_seconds)

    async def get_chunk_counts(self, sandbox_id: UUID | str | None) -> dict[str, int]:
        if sandbox_id is None:
            return {}
        key = str(sandbox_id)
        if key in self._cache:
            return self._cache[key]
        try:
            response = self._supabase.rpc(
                "rag_kasten_chunk_counts",
                {"p_sandbox_id": key},
            ).execute()
            data = response.data or []
        except Exception:
            data = []
        counts = {row["node_id"]: int(row.get("chunk_count", 0)) for row in data}
        self._cache[key] = counts
        return counts


def compute_chunk_share_penalty(chunk_count: int) -> float:
    """Multiplicative damping factor in (0, 1].

    1-chunk node → 1.0 (no penalty)
    16-chunk node → 0.25
    """
    if chunk_count <= 1:
        return 1.0
    return 1.0 / math.sqrt(chunk_count)
