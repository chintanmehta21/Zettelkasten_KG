"""C5: cross-overlay edges sharing a canonical zettel must NOT be dropped.

Two distinct kg_nodes resolving to the same overlay used to be dropped as
self-loops. They MUST now be preserved with relation='co_mention' and
link_type='cooccurrence'. True self-loops (same kg_node on both ends) are
still dropped.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from website.api.routes import _v2_assemble_graph


def _build_scope(ws_id: uuid.UUID, overlay_rows: list[dict]):
    content_repo = MagicMock()
    # C4 inversion: assembler now calls list_workspace_zettels_by_canonical_ids.
    content_repo.list_workspace_zettels_by_canonical_ids.return_value = overlay_rows
    content_repo.list_workspace_zettels.return_value = overlay_rows
    profile_id = uuid.uuid4()
    return content_repo, profile_id, [ws_id]


def _build_kg_repo(
    *, edges: list[dict], node_to_zettels: dict[int, list[str]], metadata: dict[int, list[str]]
):
    kg_repo = MagicMock()
    kg_repo.list_workspace_edges.return_value = edges
    kg_repo.list_node_zettel_mapping.return_value = node_to_zettels
    kg_repo.list_node_canonical_zettel_metadata.return_value = metadata
    return kg_repo


def test_cross_kgnode_same_overlay_promoted_to_comention():
    """Two distinct kg_nodes (1, 2) both map to the same canonical zettel.
    With C5 the resulting same-overlay edge MUST appear as a co_mention link,
    not be silently dropped."""
    ws_id = uuid.uuid4()
    canonical_id = "11111111-1111-1111-1111-111111111111"
    overlay_rows = [
        {
            "id": str(uuid.uuid4()),
            "canonical_zettel_id": canonical_id,
            "ai_summary": "Test summary",
            "user_tags": [],
            "canonical": {
                "id": canonical_id,
                "title": "Test Zettel",
                "source_type": "web",
                "publication_date": "2026-05-23",
                "normalized_url": "https://example.com/x",
            },
        }
    ]
    edges = [
        {
            "id": 1,
            "src_node_id": 1,
            "dst_node_id": 2,
            "relation_type": "shared_tag",
            "shared_tag_label": "python",
            "weight": 0.9,
            "workspace_strength": 0.75,
            "connection_strength": 0.75,
            "evidence_canonical_zettel_id": canonical_id,
        }
    ]
    node_to_zettels = {1: [canonical_id], 2: [canonical_id]}
    scope = _build_scope(ws_id, overlay_rows)
    kg_repo = _build_kg_repo(edges=edges, node_to_zettels=node_to_zettels, metadata={})

    with patch("website.api.routes.get_supabase_v2_scope_for_read", return_value=scope), \
         patch("website.api.routes.V2KGRepository", return_value=kg_repo):
        graph = _v2_assemble_graph(user_sub=str(uuid.uuid4()), limit=100, offset=0)

    assert graph is not None
    assert len(graph.nodes) == 1
    assert len(graph.links) == 1, "C5: cross-overlay edge must be preserved"
    link = graph.links[0]
    assert link.relation == "co_mention"
    assert link.link_type == "cooccurrence"


def test_true_self_loop_still_dropped():
    """When the same kg_node id appears on both ends (true self-loop), drop it."""
    ws_id = uuid.uuid4()
    canonical_id = "22222222-2222-2222-2222-222222222222"
    overlay_rows = [
        {
            "id": str(uuid.uuid4()),
            "canonical_zettel_id": canonical_id,
            "ai_summary": "",
            "user_tags": [],
            "canonical": {
                "id": canonical_id,
                "title": "Solo",
                "source_type": "web",
                "publication_date": "2026-05-23",
                "normalized_url": "https://example.com/y",
            },
        }
    ]
    edges = [
        {
            "id": 1,
            "src_node_id": 5,
            "dst_node_id": 5,
            "relation_type": "shared_tag",
            "shared_tag_label": "self",
            "weight": None,
            "workspace_strength": 0.6,
            "connection_strength": 0.6,
            "evidence_canonical_zettel_id": canonical_id,
        }
    ]
    node_to_zettels = {5: [canonical_id]}
    scope = _build_scope(ws_id, overlay_rows)
    kg_repo = _build_kg_repo(edges=edges, node_to_zettels=node_to_zettels, metadata={})

    with patch("website.api.routes.get_supabase_v2_scope_for_read", return_value=scope), \
         patch("website.api.routes.V2KGRepository", return_value=kg_repo):
        graph = _v2_assemble_graph(user_sub=str(uuid.uuid4()), limit=100, offset=0)

    assert graph is not None
    assert len(graph.links) == 0, "True self-loop (src_id == dst_id) must be dropped"


def test_nodes_emit_workspace_zettel_id_and_privacy_flag():
    """I1: each Personal-view node MUST carry ``workspace_zettel_id`` (the
    overlay UUID) and ``is_private`` so the /knowledge-graph make-private toggle
    has a target. Without these the app.js guard `if (!node.workspace_zettel_id)`
    trips on every click and the privacy control is dead."""
    ws_id = uuid.uuid4()
    canonical_id = "33333333-3333-3333-3333-333333333333"
    overlay_id = str(uuid.uuid4())
    overlay_rows = [
        {
            "id": overlay_id,
            "canonical_zettel_id": canonical_id,
            "ai_summary": "Test summary",
            "user_tags": [],
            "is_private": True,
            "canonical": {
                "id": canonical_id,
                "title": "Private Zettel",
                "source_type": "web",
                "publication_date": "2026-06-16",
                "normalized_url": "https://example.com/p",
            },
        }
    ]
    edges = [
        {
            "id": 1,
            "src_node_id": 1,
            "dst_node_id": 2,
            "relation_type": "shared_tag",
            "shared_tag_label": "python",
            "weight": 0.9,
            "workspace_strength": 0.75,
            "connection_strength": 0.75,
            "evidence_canonical_zettel_id": canonical_id,
        }
    ]
    node_to_zettels = {1: [canonical_id], 2: [canonical_id]}
    scope = _build_scope(ws_id, overlay_rows)
    kg_repo = _build_kg_repo(edges=edges, node_to_zettels=node_to_zettels, metadata={})

    with patch("website.api.routes.get_supabase_v2_scope_for_read", return_value=scope), \
         patch("website.api.routes.V2KGRepository", return_value=kg_repo):
        graph = _v2_assemble_graph(user_sub=str(uuid.uuid4()), limit=100, offset=0)

    assert graph is not None
    assert len(graph.nodes) == 1
    node = graph.nodes[0]
    # The overlay UUID the toggle POSTs to /api/zettels/{id}/private must survive
    # KGGraphNode coercion (default extra="ignore" would drop an undeclared key).
    assert node.workspace_zettel_id == overlay_id
    assert node.is_private is True


def test_distinct_overlay_distinct_kgnode_emits_regular_tag_link():
    """Sanity: two kg_nodes mapping to DIFFERENT overlays emit the normal
    tag link (not co_mention)."""
    ws_id = uuid.uuid4()
    canon_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    canon_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    overlay_rows = [
        {
            "id": str(uuid.uuid4()),
            "canonical_zettel_id": canon_a,
            "ai_summary": "",
            "user_tags": [],
            "canonical": {
                "id": canon_a,
                "title": "A",
                "source_type": "web",
                "publication_date": "2026-05-23",
                "normalized_url": "https://example.com/a",
            },
        },
        {
            "id": str(uuid.uuid4()),
            "canonical_zettel_id": canon_b,
            "ai_summary": "",
            "user_tags": [],
            "canonical": {
                "id": canon_b,
                "title": "B",
                "source_type": "web",
                "publication_date": "2026-05-23",
                "normalized_url": "https://example.com/b",
            },
        },
    ]
    edges = [
        {
            "id": 1,
            "src_node_id": 10,
            "dst_node_id": 11,
            "relation_type": "shared_tag",
            "shared_tag_label": "python",
            "weight": None,
            "workspace_strength": 0.8,
            "connection_strength": 0.8,
            "evidence_canonical_zettel_id": canon_a,
        }
    ]
    node_to_zettels = {10: [canon_a], 11: [canon_b]}
    scope = _build_scope(ws_id, overlay_rows)
    kg_repo = _build_kg_repo(edges=edges, node_to_zettels=node_to_zettels, metadata={})

    with patch("website.api.routes.get_supabase_v2_scope_for_read", return_value=scope), \
         patch("website.api.routes.V2KGRepository", return_value=kg_repo):
        graph = _v2_assemble_graph(user_sub=str(uuid.uuid4()), limit=100, offset=0)

    assert graph is not None
    assert len(graph.links) == 1
    link = graph.links[0]
    assert link.relation == "shared_tag"
    assert link.link_type == "tag"
