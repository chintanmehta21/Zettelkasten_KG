"""LD-3 / D5: _find_links must persist connection_strength + tier + relation_source."""
from website.core.graph_store import _find_links


def test_find_links_writes_strength_and_tier():
    graph = {"nodes": [{"id": "yt-foo", "tags": ["python", "async"]}]}
    links = _find_links("rd-bar", {"python", "django"}, graph)
    assert len(links) == 1
    link = links[0]
    assert link["connection_strength"] == 1.0
    assert link["tier"] == "strong"
    assert link["relation_source"] == "tag_coincidence"
    assert link["relation"] == "python"


def test_find_links_returns_empty_on_no_overlap():
    graph = {"nodes": [{"id": "yt-foo", "tags": ["ruby"]}]}
    assert _find_links("rd-bar", {"python"}, graph) == []
