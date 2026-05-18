"""URL-dedup functional gate — the ONE place that decides whether an
Add-Zettel request is a fresh ingest, a same-user no-op, or a cross-user
cache-hit. Reused by every endpoint (website Add Zettel + /api/v2/summarize)
so a change here reflects everywhere. Intentionally free of FastAPI /
engine / entitlement imports: it returns a decision; callers act on it.
"""
from __future__ import annotations

import logging

from website.features.functional_gates.models import DedupDecision

logger = logging.getLogger("website.features.functional_gates.dedup")


class UrlDedupGate:
    """Stateless. ``decide`` does two indexed reads via the provided repo
    (which must expose ``find_canonical_by_url`` and
    ``workspace_links_canonical``) and classifies the request."""

    def decide(self, *, repo, normalized_url: str, workspace_id) -> DedupDecision:
        found = repo.find_canonical_by_url(normalized_url)
        if found is None:
            logger.info("add_zettel dedup branch=fresh")
            return DedupDecision(branch="fresh", found=None)
        if repo.workspace_links_canonical(workspace_id, found.canonical_zettel_id):
            logger.info(
                "add_zettel dedup branch=same_user_noop source_type=%s",
                getattr(found, "source_type", "?"),
            )
            return DedupDecision(branch="same_user_noop", found=found)
        logger.info(
            "add_zettel dedup branch=cross_user_cache_hit source_type=%s",
            getattr(found, "source_type", "?"),
        )
        return DedupDecision(branch="cross_user_hit", found=found)


_singleton: UrlDedupGate | None = None


def get_url_dedup_gate() -> UrlDedupGate:
    """Process-wide singleton (mirrors get_functional_gates())."""
    global _singleton
    if _singleton is None:
        _singleton = UrlDedupGate()
    return _singleton


def _reset_url_dedup_gate_for_tests() -> None:
    global _singleton
    _singleton = None
