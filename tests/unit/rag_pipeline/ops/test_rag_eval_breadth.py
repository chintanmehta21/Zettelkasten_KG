import pytest

from ops.scripts.lib.rag_eval_breadth import (
    extract_changed_components,
    breadth_gate,
    BreadthError,
)


def test_extract_changed_components():
    diff_stat = """ website/features/rag_pipeline/ingest/chunker.py | 30 +-
 website/features/rag_pipeline/rerank/cascade.py | 12 +-
 website/features/rag_pipeline/generation/prompts.py | 5 +-
 docs/rag_eval/_config/composite_weights.yaml | 2 +-
 5 files changed, 47 insertions(+), 2 deletions(-)
"""
    components, configs = extract_changed_components(diff_stat)
    assert "ingest/chunker.py" in components
    assert "rerank/cascade.py" in components
    assert "generation/prompts.py" in components
    assert len(components) == 3
    assert "composite_weights.yaml" in configs


def test_breadth_gate_passes_with_3_components_and_config():
    breadth_gate(components={"a", "b", "c"}, config_or_weight_changed=True)


def test_breadth_gate_blocks_too_few_components():
    with pytest.raises(BreadthError, match="components"):
        breadth_gate(components={"a", "b"}, config_or_weight_changed=True)


def test_breadth_gate_blocks_no_config_change():
    with pytest.raises(BreadthError, match="config"):
        breadth_gate(components={"a", "b", "c"}, config_or_weight_changed=False)
