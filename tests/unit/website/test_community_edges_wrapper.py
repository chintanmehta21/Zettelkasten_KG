"""CommunityGraphRepository tag-backbone edge wiring (no DB — fully stubbed).

Covers the app-side contract of migration 90: link shape, the node-set edge
invariant, and graceful degradation when the edge RPC is absent (code may deploy
before the migration is applied).
"""
from __future__ import annotations

import pytest

from website.core.supabase_v2.repositories.community_repository import (
    CommunityGraphRepository,
)

NODE_ROWS = [
    {
        "canonical_zettel_id": "aaaaaaa1-0000-4000-8000-000000000001",
        "node_id": "web-aaaaaaa1-000",
        "title": "Async Python",
        "source_type": "web",
        "url": "https://example.test/1",
        "author_display_name": "Naruto",
        "contributor_count": 2,
    },
    {
        "canonical_zettel_id": "aaaaaaa2-0000-4000-8000-000000000002",
        "node_id": "web-aaaaaaa2-000",
        "title": "Pydantic Models",
        "source_type": "web",
        "url": "https://example.test/2",
        "author_display_name": "Sasuke",
        "contributor_count": 1,
    },
]

EDGE_ROWS = [
    {
        "source_node_id": "web-aaaaaaa1-000",
        "target_node_id": "web-aaaaaaa2-000",
        "strength": 0.432,
        "shared_tags": 2,
    }
]


class _Resp:
    def __init__(self, data):
        self.data = data


class _Rpc:
    def __init__(self, data, raises=False):
        self._data = data
        self._raises = raises

    def execute(self):
        if self._raises:
            raise RuntimeError('function content.community_graph_edges_v1 does not exist')
        return _Resp(self._data)


class _Schema:
    def __init__(self, node_rows, edge_rows, edges_raise=False):
        self._node_rows = node_rows
        self._edge_rows = edge_rows
        self._edges_raise = edges_raise
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        if name == "community_graph_edges_v1":
            return _Rpc(self._edge_rows, raises=self._edges_raise)
        return _Rpc(self._node_rows)


class _Client:
    def __init__(self, node_rows, edge_rows, edges_raise=False):
        self._schema = _Schema(node_rows, edge_rows, edges_raise)

    def schema(self, _name):
        return self._schema


def _repo(node_rows=NODE_ROWS, edge_rows=EDGE_ROWS, edges_raise=False):
    return CommunityGraphRepository(client=_Client(node_rows, edge_rows, edges_raise))


def test_edges_are_returned_with_frontend_link_shape():
    graph = _repo().get_community_graph()
    assert len(graph["links"]) == 1
    link = graph["links"][0]
    assert link["source"] == "web-aaaaaaa1-000"
    assert link["target"] == "web-aaaaaaa2-000"
    assert link["link_type"] == "tag"
    assert link["relation"] == "shared_tags"
    assert link["connection_strength"] == pytest.approx(0.432)
    assert link["description"] == "2 shared tags"


def test_single_shared_tag_description_is_singular():
    rows = [dict(EDGE_ROWS[0], shared_tags=1)]
    links = _repo(edge_rows=rows).get_community_edges()
    assert links[0]["description"] == "1 shared tag"


def test_links_referencing_missing_nodes_are_dropped():
    """Edge invariant: a link endpoint absent from nodes would break the viz."""
    orphan = {
        "source_node_id": "web-aaaaaaa1-000",
        "target_node_id": "web-zzzzzzzz-999",  # not in NODE_ROWS
        "strength": 0.9,
        "shared_tags": 3,
    }
    graph = _repo(edge_rows=EDGE_ROWS + [orphan]).get_community_graph()
    node_ids = {n["id"] for n in graph["nodes"]}
    assert len(graph["links"]) == 1
    for link in graph["links"]:
        assert link["source"] in node_ids and link["target"] in node_ids


def test_missing_edge_rpc_degrades_to_node_only_graph():
    """Code may deploy before migration 90 is applied — must not 500."""
    graph = _repo(edges_raise=True).get_community_graph()
    assert graph["links"] == []
    assert len(graph["nodes"]) == 2
    assert graph["total_nodes"] == 2


def test_no_edge_rpc_call_when_there_are_no_nodes():
    repo = _repo(node_rows=[])
    graph = repo.get_community_graph()
    assert graph == {"nodes": [], "links": [], "total_nodes": 0}
    called = [name for name, _ in repo._client.schema("content").calls]
    assert "community_graph_edges_v1" not in called


def test_edge_rpc_is_called_with_calibrated_defaults():
    repo = _repo()
    repo.get_community_graph()
    params = dict(
        (name, p) for name, p in repo._client.schema("content").calls
    )["community_graph_edges_v1"]
    assert params["p_min_shared"] == 1
    assert params["p_top_k"] == 10
    assert params["p_min_strength"] == pytest.approx(0.05)


def test_nodes_never_leak_user_identifiers():
    graph = _repo().get_community_graph()
    for node in graph["nodes"]:
        assert "user_id" not in node
        assert "owner_profile_id" not in node
