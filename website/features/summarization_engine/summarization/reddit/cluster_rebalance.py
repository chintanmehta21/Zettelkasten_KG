"""Reddit cluster-rebalance loader and pure-function rebalancer.

Driven by ``docs/summary_eval/_config/reddit_cluster_rebalance.yaml``. When a
detailed Reddit payload collapses into a single dominant cluster while the
upstream summarizer has emitted a non-trivial counterargument list, this
module synthesises a second dissent cluster so the brief / detailed views
honour the iter-09 multi-cluster contract.

Pure functions: ``rebalance_clusters`` returns a NEW
``RedditDetailedPayload``; the input instance is never mutated. When the YAML
is missing or empty, behaviour collapses to a no-op so production output is
byte-identical to the pre-feature baseline.
"""
from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
)


_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[5]
    / "docs"
    / "summary_eval"
    / "_config"
    / "reddit_cluster_rebalance.yaml"
)


# Defaults applied when YAML is missing — keep the rebalancer dormant by
# requiring an unreachable counterargument count.
_NOOP_CONFIG: dict[str, Any] = {}


def _config_path() -> Path:
    override = os.environ.get("REDDIT_CLUSTER_REBALANCE_YAML")
    return Path(override) if override else _DEFAULT_CONFIG_PATH


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        return dict(_NOOP_CONFIG)
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ValueError(
            f"reddit_cluster_rebalance.yaml is not valid YAML: {exc}"
        ) from exc
    if data is None:
        return dict(_NOOP_CONFIG)
    if not isinstance(data, dict):
        raise ValueError(
            "reddit_cluster_rebalance.yaml must deserialise to a mapping at "
            f"the top level (got {type(data).__name__})."
        )
    _validate_config_shape(data)
    return data


def _validate_config_shape(data: dict[str, Any]) -> None:
    """Fail loud on malformed config to surface eval-harness misedits early."""
    min_clusters = data.get("min_clusters", 2)
    if not isinstance(min_clusters, int) or min_clusters < 1:
        raise ValueError(
            "reddit_cluster_rebalance.yaml: 'min_clusters' must be a positive int."
        )
    required = data.get("required_clusters", [])
    if not isinstance(required, list):
        raise ValueError(
            "reddit_cluster_rebalance.yaml: 'required_clusters' must be a list."
        )
    for entry in required:
        if not isinstance(entry, dict) or "id" not in entry:
            raise ValueError(
                "reddit_cluster_rebalance.yaml: each required_clusters entry "
                "must be a mapping with an 'id' field."
            )
    global_rules = data.get("global_rules", {})
    if not isinstance(global_rules, dict):
        raise ValueError(
            "reddit_cluster_rebalance.yaml: 'global_rules' must be a mapping."
        )


def load_rebalance_config() -> dict[str, Any]:
    """Load the rebalance YAML once. Returns ``{}`` when the file is missing.

    The ``REDDIT_CLUSTER_REBALANCE_YAML`` env var overrides the default path
    (used by tests). Cached per-path; safe to call repeatedly. Raises
    ``ValueError`` on malformed YAML so config drift is loud, never silent.
    """
    return _load_cached(str(_config_path()))


def _dissent_min_count(config: dict[str, Any]) -> int:
    """Resolve the minimum counterargument count needed to synthesize dissent.

    Sourced from ``required_clusters[id == 'dissent_or_minority']
    .min_replies_represented`` if present; otherwise falls back to 3 to match
    the iter-09 scorecard expectation.
    """
    for entry in config.get("required_clusters", []) or []:
        if isinstance(entry, dict) and entry.get("id") == "dissent_or_minority":
            value = entry.get("min_replies_represented", 3)
            if isinstance(value, int) and value >= 1:
                return value
    return 3


def should_rebalance(
    detailed_payload: RedditDetailedPayload, config: dict[str, Any]
) -> bool:
    """Return True when a single dominant cluster + sufficient dissent exists.

    Logic intentionally conservative — only triggers when:
      * config is non-empty AND ``global_rules.rebalance_when_any_trigger`` is True
      * payload has exactly one ``reply_clusters`` entry (the "collapsed" case)
      * ``counterarguments`` count >= dissent threshold from config

    These align with the YAML's ``single_cluster_when_triggered`` anti-pattern
    and the ``dissent_or_minority`` required cluster (min 3 replies).
    """
    if not config:
        return False
    global_rules = config.get("global_rules") or {}
    if not global_rules.get("rebalance_when_any_trigger", False):
        return False
    if len(detailed_payload.reply_clusters) != 1:
        return False
    if len(detailed_payload.counterarguments) < _dissent_min_count(config):
        return False
    max_clusters = config.get("max_clusters", 4)
    if isinstance(max_clusters, int) and max_clusters < 2:
        return False
    return True


def _build_dissent_cluster(counterarguments: list[str]) -> RedditCluster:
    """Synthesize a dissent cluster from the counterargument list.

    Theme is fixed ("Dissenting views"); reasoning summarises the count;
    examples preserve the verbatim counterargument strings (capped at 3 to
    keep the cluster scannable). Pure: never mutates the input list.
    """
    examples = list(counterarguments[:3])
    reasoning = (
        f"A minority of replies pushed back with {len(counterarguments)} "
        "distinct counterarguments against the dominant cluster."
    )
    return RedditCluster(
        theme="Dissenting views",
        reasoning=reasoning,
        examples=examples,
    )


def rebalance_clusters(
    detailed_payload: RedditDetailedPayload, config: dict[str, Any]
) -> RedditDetailedPayload:
    """Return a NEW payload with the dominant cluster split into 2.

    Pure function — ``detailed_payload`` is never mutated. The original
    cluster is preserved intact at index 0; a synthesized dissent cluster is
    appended at index 1 using ``counterarguments`` as the split axis.
    Counterarguments / unresolved_questions / moderation_context / op_intent
    are deep-copied verbatim. If ``should_rebalance`` would return False, the
    original payload is round-tripped through ``model_copy(deep=True)`` to
    keep the no-mutation contract regardless of caller behaviour.
    """
    if not should_rebalance(detailed_payload, config):
        return detailed_payload.model_copy(deep=True)

    original_cluster = detailed_payload.reply_clusters[0]
    preserved_cluster = RedditCluster(
        theme=original_cluster.theme,
        reasoning=original_cluster.reasoning,
        examples=list(original_cluster.examples),
    )
    dissent_cluster = _build_dissent_cluster(detailed_payload.counterarguments)
    return RedditDetailedPayload(
        op_intent=detailed_payload.op_intent,
        reply_clusters=[preserved_cluster, dissent_cluster],
        counterarguments=copy.deepcopy(detailed_payload.counterarguments),
        unresolved_questions=copy.deepcopy(detailed_payload.unresolved_questions),
        moderation_context=detailed_payload.moderation_context,
    )


def reset_config_cache() -> None:
    """Test helper: drop the lru_cache so a new YAML path takes effect."""
    _load_cached.cache_clear()
