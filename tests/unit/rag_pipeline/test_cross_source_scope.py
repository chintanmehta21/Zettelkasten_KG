"""ScopeFilter must accept heterogeneous source-type node ids in node_ids."""

from website.features.rag_pipeline.types import ScopeFilter


def test_scope_filter_accepts_mixed_source_type_node_ids():
    """A user's Kasten can include youtube + github + reddit + newsletter +
    web nodes simultaneously. ScopeFilter must not reject the heterogeneous
    list — node_ids is validated as plain strings, source-type is inferred
    downstream from each node's prefix.
    """
    mixed = [
        "yt-andrej-karpathy-s-llm-in",
        "gh-pydantic-pydantic",
        "nl-the-pragmatic-engineer-t",
        "rd-sample-reddit-thread",
        "web-some-article",
    ]
    f = ScopeFilter(node_ids=mixed)
    assert f.node_ids == mixed
    # Round-trip through pydantic v2 model_dump for safety
    assert ScopeFilter.model_validate(f.model_dump()).node_ids == mixed
