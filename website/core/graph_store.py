"""In-memory graph store backed by graph.json.

Phase 4 X9+X10 retirement (Task 4.14): Supabase v2 is the canonical source of
truth for user data. ``graph.json`` is a READ-ONLY mirror seed-loaded at
process boot. In-memory ``add_node`` / ``delete_node`` mutations are kept
ONLY for the file-store public/anonymous surface (e.g. curated demo
enrichments) — they DO NOT persist to disk and DO NOT survive a worker
restart. To update the curated demo graph, edit graph.json by hand and run
``ops/scripts/backfill_graph_json_strength.py``; the next deploy will pick
up the changes.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import date
from pathlib import Path

logger = logging.getLogger("website.graph_store")

GRAPH_JSON = Path(__file__).resolve().parent.parent / "features" / "knowledge_graph" / "content" / "graph.json"

_lock = threading.Lock()
_graph: dict | None = None

# Source-type registry: D1+D2+D3 fix (Phase 4 / Task 4.1). The canonical
# data lives in website.core.source_registry; the locals below are
# back-compat shims so existing callers (`_SOURCE_PREFIX.get(...)`,
# `_normalize_source_type(...)`) keep working without per-site rewrites.
from website.core.source_registry import (  # noqa: E402
    SOURCE_REGISTRY as _REGISTRY,
    normalize as _registry_normalize,
)


_SOURCE_PREFIX: dict[str, str] = {
    st.value: meta.prefix for st, meta in _REGISTRY.items()
}
# Legacy alias kept explicit so existing callers passing 'generic' resolve.
_SOURCE_PREFIX["generic"] = "web"


def _normalize_source_type(source_type: str) -> str:
    """Normalize raw input to a registry source-type string."""
    return _registry_normalize(source_type).value


def _load() -> dict:
    """Load graph.json into memory (once)."""
    global _graph
    if _graph is None:
        with _lock:
            if _graph is None:
                _graph = json.loads(GRAPH_JSON.read_text(encoding="utf-8"))
    return _graph


def _slugify(text: str, max_len: int = 24) -> str:
    """Convert text to a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def _normalize_tag(tag: str) -> str:
    """Strip category prefix from pipeline tags (domain/ml -> ml).

    Reddit ``r-foo`` slugs are rewritten to ``r/foo`` at this layer so the
    file-store and Supabase store agree on tag spelling.
    """
    from website.core.text_polish import rewrite_reddit_tag

    cleaned = tag.lower()
    rewritten = rewrite_reddit_tag(cleaned)
    if rewritten != cleaned:
        return rewritten
    return cleaned.split("/", 1)[-1]


def _find_links(node_id: str, tags: set[str], graph: dict) -> list[dict]:
    """Find existing nodes that share tags with the new node.

    LD-3: every auto-link gets `connection_strength=1.0`, `tier="strong"`,
    `relation_source="tag_coincidence"` so the strength-aware render path
    (post-LD-2) treats these the same way as scored v2 edges. The file-store
    is a curated demo surface — render at full strength.
    """
    links = []
    for existing in graph["nodes"]:
        if existing["id"] == node_id:
            continue
        existing_tags = {t.lower() for t in existing.get("tags", [])}
        shared = tags & existing_tags
        if shared:
            relation = max(shared, key=len)
            links.append({
                "source": node_id,
                "target": existing["id"],
                "relation": relation,
                "connection_strength": 1.0,
                "tier": "strong",
                "relation_source": "tag_coincidence",
            })
    return links


def add_node(
    *,
    title: str,
    source_type: str,
    source_url: str,
    summary: str,
    tags: list[str],
) -> str:
    """Add a new node to the graph and return its ID.

    Automatically discovers links to existing nodes based on shared tags.
    """
    from website.core.text_polish import polish
    title = polish(title) if isinstance(title, str) else title
    graph = _load()
    normalized_source = _normalize_source_type(source_type)
    prefix = _SOURCE_PREFIX.get(normalized_source, "web")
    slug = _slugify(title)
    node_id = f"{prefix}-{slug}"

    # Ensure unique ID
    existing_ids = {n["id"] for n in graph["nodes"]}
    if node_id in existing_ids:
        return node_id  # Already exists

    # Normalize tags for matching (strip domain/, keyword/, etc.)
    clean_tags = [_normalize_tag(t) for t in tags if not t.startswith("status/")]
    # Remove source/ prefix tags too
    clean_tags = [
        t for t in clean_tags
        if t not in ("youtube", "reddit", "github", "twitter", "substack", "medium", "web", "generic", "newsletter")
    ]

    node = {
        "id": node_id,
        "name": title,
        "group": prefix if prefix in ("yt", "rd", "gh", "tw", "ss", "md", "web") else "web",
        "summary": summary,
        "tags": clean_tags,
        "url": source_url,
        "date": date.today().isoformat(),
    }

    # Map prefix back to group name used in colors
    group_map = {"yt": "youtube", "rd": "reddit", "gh": "github", "tw": "twitter", "ss": "substack", "md": "medium", "web": "web"}
    node["group"] = group_map.get(prefix, "web")

    with _lock:
        graph["nodes"].append(node)

        # Find and add tag-based links
        tag_set = set(clean_tags)
        new_links = _find_links(node_id, tag_set, graph)
        graph["links"].extend(new_links)
        # X9+X10 (T4.14): no disk write — graph.json is a read-only mirror.

    logger.info(
        "Added node '%s' with %d links to graph",
        node_id,
        len(new_links),
    )
    return node_id


def get_graph() -> dict:
    """Return the current graph data."""
    return _load()


def delete_node(node_id: str) -> bool:
    """Delete a node and all links attached to it from the file-backed graph."""
    graph = _load()

    with _lock:
        node_count_before = len(graph["nodes"])
        graph["nodes"] = [n for n in graph["nodes"] if n.get("id") != node_id]
        if len(graph["nodes"]) == node_count_before:
            return False

        graph["links"] = [
            lk
            for lk in graph["links"]
            if lk.get("source") != node_id and lk.get("target") != node_id
        ]
        # X9+X10 (T4.14): no disk write — graph.json is a read-only mirror.

    logger.info("Deleted node '%s' from file graph store", node_id)
    return True
