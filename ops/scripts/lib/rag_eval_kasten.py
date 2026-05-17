# ops/scripts/lib/rag_eval_kasten.py
"""Kasten builder: loads Naruto Zettels, falls back to Chintan_Testing.md, drives ingestion."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any
from uuid import UUID


class KastenBuildError(Exception):
    pass


_CHINTAN_LINE_RE = re.compile(r"^\d+\.\s+\[([^\]]+)\]\(([^)]+)\)")


def parse_chintan_testing(path: Path) -> list[dict]:
    """Parse Chintan_Testing.md into [{title, url}, ...]."""
    if not path.exists():
        raise KastenBuildError(f"Chintan_Testing.md not found at {path}")
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _CHINTAN_LINE_RE.match(line.strip())
        if m:
            entries.append({"title": m.group(1), "url": m.group(2)})
    return entries


async def load_naruto_zettels_for_source(
    *, user_id: UUID, source_type: str, supabase: Any,
) -> list[dict]:
    """Load all Naruto's Zettels for a given source_type.

    Legacy slug-keyed ``public.kg_nodes`` query purged with DB v2 (table
    dropped; v2 splits into UUID-keyed content.canonical_zettels +
    workspace_zettels with no slug/user_id surface). A v2 port must reshape
    callers around workspace_id + canonical/workspace UUIDs.
    """
    del user_id, source_type, supabase  # contract parity; no v2 slug surface
    raise NotImplementedError(
        "rag_eval_kasten.load_naruto_zettels_for_source: v2 eval-driver "
        "rebuild pending — legacy slug-keyed kg_nodes path purged; see "
        "rag_eval_v2 (Phase E)"
    )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def select_similar_zettel(
    *,
    candidates: list[dict],
    centroid: list[float],
    min_cosine: float,
    exclude_ids: set[str],
) -> dict | None:
    """Pick highest-cosine candidate above threshold, excluding already-in-Kasten nodes."""
    best = None
    best_score = -1.0
    for c in candidates:
        if c["node_id"] in exclude_ids:
            continue
        sim = _cosine(c["embedding"], centroid)
        if sim >= min_cosine and sim > best_score:
            best = {**c, "_cosine": sim}
            best_score = sim
    return best


async def build_kasten(
    *,
    source: str,
    iter_num: int,
    user_id: UUID,
    seed_node_ids: list[str],
    supabase: Any,
    chintan_path: Path,
    output_dir: Path,
    require_similar: bool = False,
    require_unseen: bool = False,
    similar_min_cosine: float = 0.65,
    unseen_cosine_range: tuple[float, float] = (0.50, 0.70),
) -> dict:
    """Build the iter's Kasten manifest.

    Delegates Zettel loading to ``load_naruto_zettels_for_source``, whose
    legacy slug-keyed path was purged with DB v2 — so this raises until the
    v2 eval-driver rebuild lands. Args are retained for call-contract
    stability.
    """
    del (
        source, iter_num, user_id, seed_node_ids, supabase, chintan_path,
        output_dir, require_similar, require_unseen, similar_min_cosine,
        unseen_cosine_range,
    )
    raise NotImplementedError(
        "rag_eval_kasten.build_kasten: v2 eval-driver rebuild pending — "
        "legacy slug-keyed Kasten path purged; see rag_eval_v2 (Phase E)"
    )


async def ingest_kasten(
    *,
    zettels: list[dict],
    user_id: UUID,
    runtime: Any = None,  # accepted for plan compatibility; not used
    supabase: Any = None,
) -> dict:
    """Ensure each Kasten Zettel has RAG chunks.

    The legacy implementation probed/wrote slug-keyed ``kg_node_chunks`` via
    a ``(user_id, slug)`` ``ingest_node_chunks`` entry point, both purged
    with DB v2 (table dropped; v2 ingest requires workspace/canonical UUIDs
    with no slug entry point). A v2 eval-ingest driver must build
    canonical/workspace rows first and key everything on UUIDs — a redesign,
    not a client swap. Args are retained for call-contract stability.
    """
    del zettels, user_id, runtime, supabase  # contract parity
    raise NotImplementedError(
        "rag_eval_kasten.ingest_kasten: v2 eval-driver rebuild pending — "
        "legacy slug-keyed kg_node_chunks/ingest_node_chunks path purged; "
        "see rag_eval_v2 (Phase E)"
    )
