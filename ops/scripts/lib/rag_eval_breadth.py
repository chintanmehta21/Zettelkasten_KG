"""Change-breadth gate: ensures each tuning iter touches >=3 RAG components AND >=1 config/weight."""
from __future__ import annotations


_COMPONENT_PATTERNS = [
    "ingest/chunker.py",
    "ingest/embedder.py",
    "retrieval/hybrid.py",
    "rerank/cascade.py",
    "query/rewriter.py",
    "query/router.py",
    "generation/prompts.py",
]

_CONFIG_PATTERNS = [
    "composite_weights.yaml",
    "fusion_weights",
    "depth_by_class",
    "rubric_",
]


class BreadthError(Exception):
    pass


def extract_changed_components(diff_stat: str) -> tuple[set[str], set[str]]:
    """Return (components_changed, configs_changed) sets from `git diff --stat` output."""
    components: set[str] = set()
    configs: set[str] = set()
    for line in diff_stat.splitlines():
        for pat in _COMPONENT_PATTERNS:
            if pat in line:
                components.add(pat)
        for pat in _CONFIG_PATTERNS:
            if pat in line:
                configs.add(pat)
    return components, configs


def breadth_gate(*, components: set[str], config_or_weight_changed: bool) -> None:
    if len(components) < 3:
        raise BreadthError(
            f"CHANGE_BREADTH_INSUFFICIENT: tuning iter must modify >=3 RAG components; "
            f"found {len(components)}: {sorted(components)}"
        )
    if not config_or_weight_changed:
        raise BreadthError(
            "CHANGE_BREADTH_INSUFFICIENT: tuning iter must touch >=1 config or weight surface"
        )
