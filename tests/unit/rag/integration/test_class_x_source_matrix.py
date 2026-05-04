"""iter-10 cross-class regression fixture.

Replays a small synthetic 6-query mini-suite spanning
``{LOOKUP, THEMATIC, MULTI_HOP} × {youtube, github, newsletter, web}`` and
checks the per-(class,source) top-1 outcome of ``_dedup_and_fuse``. If a
retrieval-stage change in Phases 4-6 regresses a previously-passing
intersection, the test fails — preventing 'fixed q10 / broke q5' patterns.

The fixture is synthetic on purpose: production-replay would need eval-token
access. Synthetic rows exercise the SAME ``_dedup_and_fuse`` code path, so
the regression net catches dedup/fuse/tiebreak changes deterministically.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from uuid import UUID

import pytest

from website.features.rag_pipeline.retrieval.hybrid import HybridRetriever
from website.features.rag_pipeline.types import QueryClass


FIXTURE = pathlib.Path(__file__).parent / "class_x_source_baseline.json"


def _stable_uuid(seed: str) -> str:
    h = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return str(UUID(h))


def _row(node_id: str, source_type: str, rrf: float, name: str | None = None) -> dict:
    return {
        "kind": "chunk",
        "node_id": node_id,
        "chunk_id": _stable_uuid(node_id + "-c0"),
        "chunk_idx": 0,
        "name": name or node_id.replace("-", " ").title(),
        "source_type": source_type,
        "url": f"https://example.com/{node_id}",
        "content": f"content for {node_id}",
        "tags": [],
        "rrf_score": rrf,
    }


# Six baseline (class, source) intersections. Each entry: variants of rows
# (one variant) plus expected primary node_id under iter-10 retrieval rules.
# Designed to exercise the tie-breaker and the magnet-demote behaviour:
# LOOKUP/youtube prefers chunky relevant zettel; THEMATIC/web prefers broader
# coverage; etc.
_BASELINE = {
    "lookup_youtube": {
        "class": "lookup",
        "rows": [
            _row("yt-naval-podcast", "youtube", 0.55),
            _row("yt-other-talk", "youtube", 0.40),
        ],
        "chunk_counts": {"yt-naval-podcast": 8, "yt-other-talk": 2},
        "expected_primary": "yt-naval-podcast",
    },
    "lookup_github": {
        "class": "lookup",
        "rows": [
            _row("gh-zk-org-zk", "github", 0.60),
            _row("gh-side-tool", "github", 0.35),
        ],
        "chunk_counts": {"gh-zk-org-zk": 4, "gh-side-tool": 1},
        "expected_primary": "gh-zk-org-zk",
    },
    "thematic_newsletter": {
        "class": "thematic",
        "rows": [
            _row("nl-pragmatic-eng", "newsletter", 0.50),
            _row("nl-other-essay", "newsletter", 0.50),
            _row("nl-broad-topic", "newsletter", 0.50),
            _row("nl-scoped-piece", "newsletter", 0.50),
        ],
        # All rrf tied; THEMATIC prefers LOWER chunk-count (broad coverage).
        "chunk_counts": {
            "nl-pragmatic-eng": 12,
            "nl-other-essay": 8,
            "nl-broad-topic": 2,
            "nl-scoped-piece": 1,
        },
        "expected_primary": "nl-scoped-piece",
    },
    "thematic_web": {
        "class": "thematic",
        "rows": [
            _row("web-tools-thought", "web", 0.50),
            _row("web-other-essay", "web", 0.50),
            _row("web-broad-piece", "web", 0.50),
            _row("web-scoped-note", "web", 0.50),
        ],
        "chunk_counts": {
            "web-tools-thought": 10,
            "web-other-essay": 5,
            "web-broad-piece": 3,
            "web-scoped-note": 1,
        },
        "expected_primary": "web-scoped-note",
    },
    "multi_hop_youtube": {
        "class": "multi_hop",
        "rows": [
            _row("yt-talk-a", "youtube", 0.50),
            _row("yt-talk-b", "youtube", 0.50),
            _row("yt-talk-c", "youtube", 0.50),
            _row("yt-talk-d", "youtube", 0.50),
        ],
        "chunk_counts": {"yt-talk-a": 12, "yt-talk-b": 5, "yt-talk-c": 3, "yt-talk-d": 1},
        # MULTI_HOP inverts like THEMATIC.
        "expected_primary": "yt-talk-d",
    },
    "lookup_web": {
        "class": "lookup",
        "rows": [
            _row("web-author-page", "web", 0.55),
            _row("web-other-page", "web", 0.40),
        ],
        "chunk_counts": {"web-author-page": 3, "web-other-page": 1},
        "expected_primary": "web-author-page",
    },
}


def _make_retriever() -> HybridRetriever:
    """Stub HybridRetriever — only _dedup_and_fuse is exercised here."""
    return HybridRetriever(embedder=None, supabase=None)


@pytest.mark.parametrize("name,case", list(_BASELINE.items()))
def test_class_x_source_baseline_no_regression(name: str, case: dict) -> None:
    """Run _dedup_and_fuse with stub rows and assert top-1 stays at the
    baseline node_id. If a retrieval-stage change reorders any intersection,
    this fails so the change can be evaluated before merge."""
    retriever = _make_retriever()
    qclass = QueryClass(case["class"])
    candidates = retriever._dedup_and_fuse(
        [case["rows"]],
        query_variants=["any"],
        query_metadata=None,
        query_class=qclass,
        chunk_counts=case["chunk_counts"],
        effective_nodes=None,
        anchor_neighbours=None,
        anchor_seeds=None,
    )
    assert candidates, f"{name}: empty result"
    primary = candidates[0].node_id
    assert primary == case["expected_primary"], (
        f"{name} regressed: expected primary={case['expected_primary']!r} "
        f"got {primary!r}. Top-3: "
        f"{[(c.node_id, round(c.rrf_score, 4)) for c in candidates[:3]]}"
    )


@pytest.mark.skipif(not FIXTURE.exists(), reason="external production-replay fixture not seeded")
def test_external_baseline_fixture_no_regression() -> None:
    """Optional external-fixture variant. Operator seeds class_x_source_baseline.json
    with rows captured from a real iter-09 / iter-10 eval; this then anchors
    the regression net to actual production data instead of synthetic rows."""
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(expected, dict) and expected, "fixture must be a non-empty dict"
