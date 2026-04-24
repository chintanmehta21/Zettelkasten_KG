"""Tests for the Reddit cluster-rebalance loader and pure-function rebalancer.

Covers:
  * YAML loader happy path + missing-file fallback (returns {}).
  * ``should_rebalance`` True / False decision matrix.
  * ``rebalance_clusters`` purity (no input mutation) and structural shape.
  * End-to-end ``RedditStructuredPayload`` integration (1 cluster -> 2).
  * Held-out preservation: iter-09 reference payload stays at 5 clusters and
    the composite-relevant fields (mini_title prefix, reserved tags,
    5-7-sentence brief) are unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import re

from website.features.summarization_engine.summarization.reddit.cluster_rebalance import (
    _build_dissent_cluster,
    load_rebalance_config,
    rebalance_clusters,
    reset_config_cache,
    should_rebalance,
)
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)


_REPO_ROOT = Path(__file__).resolve().parents[5]
_REAL_YAML = (
    _REPO_ROOT
    / "docs"
    / "summary_eval"
    / "_config"
    / "reddit_cluster_rebalance.yaml"
)
_ITER09_HELD_OUT = (
    _REPO_ROOT
    / "docs"
    / "summary_eval"
    / "reddit"
    / "iter-09"
    / "held_out"
    / "cab54dd841fd3c7d"
    / "summary.json"
)


@pytest.fixture(autouse=True)
def _clear_rebalance_cache(monkeypatch):
    """Make every test see a fresh config cache (and explicit YAML path)."""
    monkeypatch.setenv("REDDIT_CLUSTER_REBALANCE_YAML", str(_REAL_YAML))
    reset_config_cache()
    yield
    reset_config_cache()


def _one_cluster_payload(counterarg_count: int) -> RedditDetailedPayload:
    return RedditDetailedPayload(
        op_intent="OP wants advice on first-time stock purchases.",
        reply_clusters=[
            RedditCluster(
                theme="Index funds for beginners",
                reasoning="Most replies pointed at low-fee index funds.",
                examples=["VTI", "VOO"],
            )
        ],
        counterarguments=[
            f"Counterpoint #{idx + 1}: a minority disagreed with index funds."
            for idx in range(counterarg_count)
        ],
        unresolved_questions=["What about international diversification?"],
        moderation_context="Some replies were removed by mods.",
    )


# --- Config loader -----------------------------------------------------------

def test_load_rebalance_config_happy_path_reads_yaml():
    config = load_rebalance_config()
    assert config["version"] == "reddit_cluster_rebalance.v1"
    assert config["min_clusters"] == 2
    assert config["max_clusters"] == 4
    assert config["global_rules"]["rebalance_when_any_trigger"] is True


def test_load_rebalance_config_missing_file_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "REDDIT_CLUSTER_REBALANCE_YAML", str(tmp_path / "does_not_exist.yaml")
    )
    reset_config_cache()
    assert load_rebalance_config() == {}


def test_load_rebalance_config_malformed_yaml_raises(monkeypatch, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("min_clusters: not-an-int\n", encoding="utf-8")
    monkeypatch.setenv("REDDIT_CLUSTER_REBALANCE_YAML", str(bad))
    reset_config_cache()
    with pytest.raises(ValueError, match="min_clusters"):
        load_rebalance_config()


# --- should_rebalance --------------------------------------------------------

def test_should_rebalance_true_when_one_cluster_and_three_counterarguments():
    config = load_rebalance_config()
    payload = _one_cluster_payload(counterarg_count=3)
    assert should_rebalance(payload, config) is True


def test_should_rebalance_false_when_already_balanced():
    config = load_rebalance_config()
    payload = RedditDetailedPayload(
        op_intent="OP asks about X.",
        reply_clusters=[
            RedditCluster(theme="A", reasoning="aa", examples=[]),
            RedditCluster(theme="B", reasoning="bb", examples=[]),
        ],
        counterarguments=["c1", "c2", "c3", "c4"],
        unresolved_questions=[],
        moderation_context=None,
    )
    assert should_rebalance(payload, config) is False


def test_should_rebalance_false_when_too_few_counterarguments():
    config = load_rebalance_config()
    payload = _one_cluster_payload(counterarg_count=1)
    assert should_rebalance(payload, config) is False


def test_should_rebalance_false_when_config_empty():
    payload = _one_cluster_payload(counterarg_count=5)
    assert should_rebalance(payload, {}) is False


# --- rebalance_clusters ------------------------------------------------------

def test_rebalance_clusters_produces_two_clusters_and_does_not_mutate_input():
    config = load_rebalance_config()
    payload = _one_cluster_payload(counterarg_count=3)
    original_cluster_count = len(payload.reply_clusters)
    original_cluster_theme = payload.reply_clusters[0].theme
    original_counterarg_count = len(payload.counterarguments)

    new_payload = rebalance_clusters(payload, config)

    # Input untouched.
    assert len(payload.reply_clusters) == original_cluster_count == 1
    assert payload.reply_clusters[0].theme == original_cluster_theme
    assert len(payload.counterarguments) == original_counterarg_count
    # Output has exactly 2 clusters; counterarguments preserved verbatim.
    assert len(new_payload.reply_clusters) == 2
    assert new_payload.reply_clusters[0].theme == original_cluster_theme
    assert new_payload.reply_clusters[1].theme == "Dissenting views"
    assert new_payload.counterarguments == payload.counterarguments
    # New cluster examples come from counterarguments (capped at 3).
    assert len(new_payload.reply_clusters[1].examples) == min(3, original_counterarg_count)


def test_rebalance_clusters_noop_returns_deep_copy_when_should_not_trigger():
    config = load_rebalance_config()
    payload = _one_cluster_payload(counterarg_count=1)  # below threshold
    out = rebalance_clusters(payload, config)
    assert out is not payload
    assert len(out.reply_clusters) == 1
    assert out.reply_clusters[0] is not payload.reply_clusters[0]


def test_build_dissent_cluster_caps_examples_at_three():
    cluster = _build_dissent_cluster(
        ["a", "b", "c", "d", "e"]
    )
    assert cluster.theme == "Dissenting views"
    assert cluster.examples == ["a", "b", "c"]


# --- End-to-end: RedditStructuredPayload integration -------------------------

def test_structured_payload_rebalances_one_cluster_with_three_counterarguments():
    payload = RedditStructuredPayload(
        mini_title="r/personalfinance index fund advice",
        brief_summary="One short fragment",
        tags=[
            "investing",
            "index-funds",
            "vti",
            "voo",
            "beginner-advice",
            "reddit",
            "personal-finance",
        ],
        detailed_summary=_one_cluster_payload(counterarg_count=3),
    )
    assert len(payload.detailed_summary.reply_clusters) == 2
    assert payload.detailed_summary.reply_clusters[1].theme == "Dissenting views"
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", payload.brief_summary) if s.strip()]
    assert 5 <= len(sentences) <= 7


def test_structured_payload_does_not_rebalance_when_only_one_counterargument():
    payload = RedditStructuredPayload(
        mini_title="r/personalfinance index fund advice",
        brief_summary="One short fragment",
        tags=[
            "investing",
            "index-funds",
            "vti",
            "voo",
            "beginner-advice",
            "reddit",
            "personal-finance",
        ],
        detailed_summary=_one_cluster_payload(counterarg_count=1),
    )
    assert len(payload.detailed_summary.reply_clusters) == 1


# --- Held-out iter-09 preservation ------------------------------------------

def test_iter09_held_out_payload_preserves_composite_relevant_fields():
    """iter-09 fixture has 5 clusters + 4 counterarguments; rebalance must
    NOT trigger (cluster count != 1), and re-validating the structured
    payload must keep the iter-09 contract intact (subreddit prefix, reserved
    tag, 5-7-sentence brief)."""
    raw = json.loads(_ITER09_HELD_OUT.read_text(encoding="utf-8"))
    structured_dict = raw["metadata"]["structured_payload"]

    payload = RedditStructuredPayload(**structured_dict)

    # Cluster count untouched (5 in fixture).
    assert len(payload.detailed_summary.reply_clusters) == 5
    # Subreddit prefix preserved.
    assert payload.mini_title.startswith("r/hinduism")
    # Canonical reserved tag and inferred thread-type tag preserved.
    assert payload.tags[0] == "r-hinduism"
    assert "experience-report" in payload.tags
    # Brief is 5-7 sentences (iter-09 contract).
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", payload.brief_summary) if s.strip()]
    assert 5 <= len(sentences) <= 7
