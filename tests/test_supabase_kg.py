"""Tests for the Supabase knowledge-graph integration layer.

Covers client.py (env-var gating), models.py (serialization/defaults),
and repository.py (CRUD operations with a mocked Supabase client).
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from website.core.supabase_kg.models import (
    KGGraph,
    KGGraphLink,
    KGGraphNode,
    KGLink,
    KGLinkCreate,
    KGNode,
    KGNodeCreate,
    KGUser,
    KGUserCreate,
)
from telegram_bot.models.capture import SourceType


# ── Helpers ──────────────────────────────────────────────────────────────────

USER_ID = uuid.uuid4()
RENDER_USER_ID = "render_abc123"


def _mock_supabase_client():
    """Create a MagicMock that supports supabase-py chained API calls."""
    client = MagicMock()
    query = MagicMock()
    query.select.return_value = query
    query.insert.return_value = query
    query.delete.return_value = query
    query.eq.return_value = query
    query.neq.return_value = query
    query.ilike.return_value = query
    query.overlaps.return_value = query
    query.in_.return_value = query
    query.order.return_value = query
    query.range.return_value = query
    query.limit.return_value = query
    client.table.return_value = query
    return client, query


def _make_execute_response(data=None, count=None):
    """Build a mock response object matching supabase-py's APIResponse."""
    resp = MagicMock()
    resp.data = data if data is not None else []
    resp.count = count
    return resp


def _sample_user_row(user_id: UUID | None = None) -> dict:
    uid = user_id or USER_ID
    return {
        "id": str(uid),
        "render_user_id": RENDER_USER_ID,
        "display_name": "Test User",
        "email": "test@example.com",
        "avatar_url": None,
        "is_active": True,
        "created_at": "2026-03-29T00:00:00+00:00",
        "updated_at": "2026-03-29T00:00:00+00:00",
    }


def _sample_node_row(node_id: str = "web-test-node", user_id: UUID | None = None) -> dict:
    uid = user_id or USER_ID
    return {
        "id": node_id,
        "user_id": str(uid),
        "name": "Test Node",
        "source_type": "web",
        "summary": "A test summary",
        "tags": ["python", "testing"],
        "url": "https://example.com/test",
        "node_date": "2026-03-29",
        "metadata": {},
        "created_at": "2026-03-29T00:00:00+00:00",
        "updated_at": "2026-03-29T00:00:00+00:00",
    }


def _sample_link_row(
    link_id: UUID | None = None,
    source: str = "web-node-a",
    target: str = "web-node-b",
) -> dict:
    lid = link_id or uuid.uuid4()
    return {
        "id": str(lid),
        "user_id": str(USER_ID),
        "source_node_id": source,
        "target_node_id": target,
        "relation": "python",
        "created_at": "2026-03-29T00:00:00+00:00",
    }


# ═══════════════════════════════════════════════════════════════════════════
# client.py tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSupabaseClient:
    def test_get_supabase_client_raises_without_env(self) -> None:
        """Without SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, should raise RuntimeError."""
        from website.core.supabase_kg.client import get_supabase_client

        # Clear any cached client
        get_supabase_client.cache_clear()

        env_without = {
            k: v
            for k, v in os.environ.items()
            if k not in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        }
        with patch.dict(os.environ, env_without, clear=True):
            with pytest.raises(RuntimeError, match="SUPABASE_URL"):
                get_supabase_client()

        # Clean up cache so other tests aren't affected
        get_supabase_client.cache_clear()


class TestIsSupabaseConfigured:
    def test_is_supabase_configured_true(self) -> None:
        env = {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "secret-key",
        }
        with patch.dict(os.environ, env):
            from website.core.supabase_kg.client import is_supabase_configured

            assert is_supabase_configured() is True

    def test_is_supabase_configured_false_missing_url(self) -> None:
        env_without = {
            k: v
            for k, v in os.environ.items()
            if k not in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        }
        with patch.dict(os.environ, env_without, clear=True):
            from website.core.supabase_kg.client import is_supabase_configured

            assert is_supabase_configured() is False

    def test_is_supabase_configured_false_missing_key(self) -> None:
        env = {"SUPABASE_URL": "https://test.supabase.co"}
        env_without = {
            k: v
            for k, v in os.environ.items()
            if k != "SUPABASE_SERVICE_ROLE_KEY"
        }
        env_without["SUPABASE_URL"] = "https://test.supabase.co"
        with patch.dict(os.environ, env_without, clear=True):
            from website.core.supabase_kg.client import is_supabase_configured

            assert is_supabase_configured() is False


class TestGetSupabaseEnv:
    def test_get_supabase_env_returns_dict(self) -> None:
        env = {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_ANON_KEY": "anon-key",
            "SUPABASE_SERVICE_ROLE_KEY": "secret-key",
        }
        with patch.dict(os.environ, env):
            from website.core.supabase_kg.client import get_supabase_env

            result = get_supabase_env()

        assert isinstance(result, dict)
        assert set(result.keys()) == {
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        }
        assert result["SUPABASE_URL"] == "https://test.supabase.co"
        assert result["SUPABASE_ANON_KEY"] == "anon-key"
        assert result["SUPABASE_SERVICE_ROLE_KEY"] == "secret-key"

    def test_get_supabase_env_defaults_to_empty_strings(self) -> None:
        env_without = {
            k: v
            for k, v in os.environ.items()
            if k not in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")
        }
        with patch.dict(os.environ, env_without, clear=True):
            from website.core.supabase_kg.client import get_supabase_env

            result = get_supabase_env()

        assert result["SUPABASE_URL"] == ""
        assert result["SUPABASE_ANON_KEY"] == ""
        assert result["SUPABASE_SERVICE_ROLE_KEY"] == ""


# ═══════════════════════════════════════════════════════════════════════════
# models.py tests
# ═══════════════════════════════════════════════════════════════════════════


class TestKGUserModel:
    def test_round_trip(self) -> None:
        uid = uuid.uuid4()
        user = KGUser(
            id=uid,
            render_user_id="render_xyz",
            display_name="Alice",
            email="alice@example.com",
            is_active=True,
        )
        data = user.model_dump()
        restored = KGUser(**data)
        assert restored.id == uid
        assert restored.render_user_id == "render_xyz"
        assert restored.display_name == "Alice"

    def test_defaults(self) -> None:
        uid = uuid.uuid4()
        user = KGUser(id=uid, render_user_id="r1")
        assert user.display_name is None
        assert user.email is None
        assert user.avatar_url is None
        assert user.is_active is True
        assert user.created_at is None
        assert user.updated_at is None


class TestKGUserCreateModel:
    def test_round_trip(self) -> None:
        create = KGUserCreate(
            render_user_id="render_xyz",
            display_name="Bob",
            email="bob@test.com",
        )
        data = create.model_dump()
        restored = KGUserCreate(**data)
        assert restored.render_user_id == "render_xyz"

    def test_defaults(self) -> None:
        create = KGUserCreate(render_user_id="r1")
        assert create.display_name is None
        assert create.email is None
        assert create.avatar_url is None


class TestKGNodeModel:
    def test_round_trip(self) -> None:
        uid = uuid.uuid4()
        node = KGNode(
            id="yt-test",
            user_id=uid,
            name="Test Video",
            source_type="youtube",
            summary="A video summary",
            tags=["python", "ml"],
            url="https://youtube.com/watch?v=abc",
            node_date=date(2026, 3, 29),
            metadata={"duration": 120},
        )
        data = node.model_dump()
        restored = KGNode(**data)
        assert restored.id == "yt-test"
        assert restored.tags == ["python", "ml"]
        assert restored.metadata == {"duration": 120}

    def test_defaults(self) -> None:
        uid = uuid.uuid4()
        node = KGNode(
            id="web-test",
            user_id=uid,
            name="Test",
            source_type="web",
            url="https://example.com",
        )
        assert node.tags == []
        assert node.metadata == {}
        assert node.summary is None
        assert node.node_date is None
        assert node.created_at is None
        assert node.updated_at is None


class TestKGNodeCreateModel:
    def test_round_trip(self) -> None:
        create = KGNodeCreate(
            id="gh-repo",
            name="Repo",
            source_type="github",
            tags=["rust"],
            url="https://github.com/test/repo",
        )
        data = create.model_dump()
        restored = KGNodeCreate(**data)
        assert restored.id == "gh-repo"
        assert restored.source_type == "github"

    def test_defaults(self) -> None:
        create = KGNodeCreate(
            id="web-x",
            name="X",
            source_type="web",
            url="https://example.com",
        )
        assert create.tags == []
        assert create.metadata == {}
        assert create.summary is None
        assert create.node_date is None

    def test_legacy_source_type_is_allowed_and_normalized_by_repo(self) -> None:
        create = KGNodeCreate(
            id="web-generic",
            name="Legacy Web",
            source_type="generic",
            url="https://example.com",
        )
        assert create.source_type == "generic"


class TestKGLinkModel:
    def test_round_trip(self) -> None:
        lid = uuid.uuid4()
        uid = uuid.uuid4()
        link = KGLink(
            id=lid,
            user_id=uid,
            source_node_id="a",
            target_node_id="b",
            relation="shared-tag",
        )
        data = link.model_dump()
        restored = KGLink(**data)
        assert restored.id == lid
        assert restored.source_node_id == "a"
        assert restored.relation == "shared-tag"

    def test_defaults(self) -> None:
        link = KGLink(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            source_node_id="a",
            target_node_id="b",
            relation="r",
        )
        assert link.created_at is None


class TestKGLinkCreateModel:
    def test_round_trip(self) -> None:
        create = KGLinkCreate(
            source_node_id="node-a",
            target_node_id="node-b",
            relation="python",
        )
        data = create.model_dump()
        restored = KGLinkCreate(**data)
        assert restored.source_node_id == "node-a"
        assert restored.relation == "python"


class TestKGGraphModel:
    def test_round_trip(self) -> None:
        graph = KGGraph(
            nodes=[
                KGGraphNode(
                    id="web-a",
                    name="Node A",
                    group="web",
                    summary="summary",
                    tags=["tag1"],
                    url="https://a.com",
                    date="2026-03-29",
                )
            ],
            links=[
                KGGraphLink(source="web-a", target="web-b", relation="shared")
            ],
        )
        data = graph.model_dump()
        restored = KGGraph(**data)
        assert len(restored.nodes) == 1
        assert len(restored.links) == 1
        assert restored.nodes[0].id == "web-a"
        assert restored.links[0].relation == "shared"

    def test_defaults(self) -> None:
        graph = KGGraph()
        assert graph.nodes == []
        assert graph.links == []

    def test_graph_node_defaults(self) -> None:
        node = KGGraphNode(
            id="x", name="X", group="web", url="https://x.com"
        )
        assert node.summary == ""
        assert node.tags == []
        assert node.date == ""


class TestSourceTypeCompatibility:
    def test_legacy_source_type_string_maps_to_web(self) -> None:
        assert SourceType("generic") is SourceType.WEB
        assert SourceType.GENERIC is SourceType.WEB


class TestNormalizeSourceType:
    def test_repository_normalizes_legacy_source_type_to_web(self) -> None:
        from website.core.supabase_kg.repository import _normalize_source_type

        assert _normalize_source_type("generic") == "web"
        assert _normalize_source_type("  GENERIC  ") == "web"

    def test_graph_store_normalizes_legacy_source_type_to_web(self) -> None:
        from website.core.graph_store import _normalize_source_type

        assert _normalize_source_type("generic") == "web"
        assert _normalize_source_type("  GENERIC  ") == "web"


# ═══════════════════════════════════════════════════════════════════════════
# repository.py tests
# ═══════════════════════════════════════════════════════════════════════════

# All repository tests patch get_supabase_client so the KGRepository.__init__
# receives our mock instead of trying to connect to a real Supabase instance.

REPO_CLIENT_PATH = "website.core.supabase_kg.repository.get_supabase_client"


def _make_repo(client_mock):
    """Instantiate KGRepository with a mocked supabase client."""
    with patch(REPO_CLIENT_PATH, return_value=client_mock):
        from website.core.supabase_kg.repository import KGRepository

        return KGRepository()


class TestGetOrCreateUser:
    def test_get_or_create_user_existing(self) -> None:
        """When the user exists in DB, return it without inserting."""
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(
            data=[_sample_user_row()]
        )

        repo = _make_repo(client)
        user = repo.get_or_create_user(RENDER_USER_ID, display_name="Test User")

        assert isinstance(user, KGUser)
        assert user.render_user_id == RENDER_USER_ID
        # insert should NOT have been called (select found the user)
        query.insert.assert_not_called()

    def test_get_or_create_user_new(self) -> None:
        """When the user doesn't exist, select returns empty, then insert is called."""
        client, query = _mock_supabase_client()

        # First execute (select) returns empty, second execute (insert) returns the new user
        new_user_row = _sample_user_row()
        query.execute.side_effect = [
            _make_execute_response(data=[]),         # select returns nothing
            _make_execute_response(data=[new_user_row]),  # insert returns new row
        ]

        repo = _make_repo(client)
        user = repo.get_or_create_user(RENDER_USER_ID, display_name="Test User")

        assert isinstance(user, KGUser)
        assert user.render_user_id == RENDER_USER_ID
        # insert SHOULD have been called since select returned empty
        query.insert.assert_called_once()


class TestAddNode:
    def test_add_node_with_auto_link(self) -> None:
        """When a node is added with tags, _auto_link should find overlapping nodes."""
        client, query = _mock_supabase_client()

        node_row = _sample_node_row("web-new-node")
        overlapping_row = {"id": "web-old-node", "tags": ["python", "testing"]}
        link_row = _sample_link_row(
            source="web-new-node", target="web-old-node"
        )

        # Sequence: insert node -> overlaps query -> insert link
        query.execute.side_effect = [
            _make_execute_response(data=[node_row]),         # insert node
            _make_execute_response(data=[overlapping_row]),  # overlaps select
            _make_execute_response(data=[link_row]),          # insert link
        ]

        repo = _make_repo(client)
        node_create = KGNodeCreate(
            id="web-new-node",
            name="Test Node",
            source_type="web",
            tags=["python", "testing"],
            url="https://example.com/test",
        )
        result = repo.add_node(USER_ID, node_create)

        assert isinstance(result, KGNode)
        assert result.id == "web-new-node"
        # The overlaps query should have been called
        query.overlaps.assert_called()

    def test_add_node_normalizes_legacy_source_type(self) -> None:
        """Legacy source types should be stored as web."""
        client, query = _mock_supabase_client()

        node_row = _sample_node_row("web-generic-node")
        query.execute.return_value = _make_execute_response(data=[node_row])

        repo = _make_repo(client)
        node_create = KGNodeCreate(
            id="web-generic-node",
            name="Generic Node",
            source_type="generic",
            tags=[],
            url="https://example.com/generic",
        )
        result = repo.add_node(USER_ID, node_create)

        assert isinstance(result, KGNode)
        payload = query.insert.call_args.args[0]
        assert payload["source_type"] == "web"

    def test_add_node_no_tags(self) -> None:
        """When tags are empty, _auto_link should NOT be called."""
        client, query = _mock_supabase_client()

        node_row = _sample_node_row("web-no-tags")
        node_row["tags"] = []
        query.execute.return_value = _make_execute_response(data=[node_row])

        repo = _make_repo(client)
        node_create = KGNodeCreate(
            id="web-no-tags",
            name="No Tags Node",
            source_type="web",
            tags=[],
            url="https://example.com/no-tags",
        )
        result = repo.add_node(USER_ID, node_create)

        assert isinstance(result, KGNode)
        # overlaps should NOT have been called (no tags -> no _auto_link)
        query.overlaps.assert_not_called()
        # neq should NOT have been called either (only used inside _auto_link)
        query.neq.assert_not_called()


class TestGetNode:
    def test_get_node_found(self) -> None:
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(
            data=[_sample_node_row("web-found")]
        )

        repo = _make_repo(client)
        node = repo.get_node(USER_ID, "web-found")

        assert node is not None
        assert isinstance(node, KGNode)
        assert node.id == "web-found"

    def test_get_node_not_found(self) -> None:
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(data=[])

        repo = _make_repo(client)
        node = repo.get_node(USER_ID, "web-nonexistent")

        assert node is None


class TestDeleteNode:
    def test_delete_node(self) -> None:
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(
            data=[_sample_node_row("web-del")]
        )

        repo = _make_repo(client)
        result = repo.delete_node(USER_ID, "web-del")

        assert result is True
        query.delete.assert_called_once()

    def test_delete_node_not_found(self) -> None:
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(data=[])

        repo = _make_repo(client)
        result = repo.delete_node(USER_ID, "web-ghost")

        assert result is False


class TestNodeExists:
    def test_node_exists_true(self) -> None:
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(
            data=[{"id": "web-exists"}]
        )

        repo = _make_repo(client)
        assert repo.node_exists(USER_ID, "https://example.com/exists") is True

    def test_node_exists_false(self) -> None:
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(data=[])

        repo = _make_repo(client)
        assert repo.node_exists(USER_ID, "https://example.com/nope") is False


class TestSearchNodes:
    def test_search_nodes_with_filters(self) -> None:
        """Pass query, tags, and source_types -- all filter methods should be called."""
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(
            data=[_sample_node_row("web-match")]
        )

        repo = _make_repo(client)
        results = repo.search_nodes(
            USER_ID,
            query="test",
            tags=["python"],
            source_types=["web", "youtube"],
            limit=50,
            offset=0,
        )

        assert len(results) == 1
        assert isinstance(results[0], KGNode)
        query.ilike.assert_called_once_with("name", r"%test%")
        query.overlaps.assert_called_once_with("tags", ["python"])
        query.in_.assert_called_once_with("source_type", ["web", "youtube"])
        query.order.assert_called_once_with("node_date", desc=True)
        query.range.assert_called_once_with(0, 49)

    def test_search_nodes_no_filters(self) -> None:
        """Only user_id filter -- no ilike/overlaps/in_ should be called."""
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(
            data=[_sample_node_row()]
        )

        repo = _make_repo(client)
        results = repo.search_nodes(USER_ID)

        assert len(results) == 1
        query.ilike.assert_not_called()
        query.overlaps.assert_not_called()
        query.in_.assert_not_called()
        # eq is called for user_id
        query.eq.assert_called_once_with("user_id", str(USER_ID))


class TestAddLink:
    def test_add_link_success(self) -> None:
        client, query = _mock_supabase_client()
        link_row = _sample_link_row(source="web-a", target="web-b")
        query.execute.return_value = _make_execute_response(data=[link_row])

        repo = _make_repo(client)
        link_create = KGLinkCreate(
            source_node_id="web-a",
            target_node_id="web-b",
            relation="python",
        )
        result = repo.add_link(USER_ID, link_create)

        assert result is not None
        assert isinstance(result, KGLink)
        assert result.source_node_id == "web-a"
        assert result.target_node_id == "web-b"

    def test_add_link_duplicate(self) -> None:
        """When insert raises (unique constraint), add_link returns None."""
        client, query = _mock_supabase_client()
        query.execute.side_effect = Exception("duplicate key value violates unique constraint")

        repo = _make_repo(client)
        link_create = KGLinkCreate(
            source_node_id="web-a",
            target_node_id="web-b",
            relation="python",
        )
        result = repo.add_link(USER_ID, link_create)

        assert result is None

    def test_add_link_non_duplicate_error_reraises(self) -> None:
        """Non-duplicate errors should be re-raised, not silently swallowed."""
        client, query = _mock_supabase_client()
        query.execute.side_effect = RuntimeError("network timeout")

        repo = _make_repo(client)
        link_create = KGLinkCreate(
            source_node_id="web-a",
            target_node_id="web-b",
            relation="python",
        )
        with pytest.raises(RuntimeError, match="network timeout"):
            repo.add_link(USER_ID, link_create)


class TestGetGraph:
    def test_get_graph_via_view(self) -> None:
        """get_graph uses kg_graph_view for single-query fetch."""
        client, query = _mock_supabase_client()

        # kg_graph_view returns a single row with graph_data JSONB
        view_data = {
            "graph_data": {
                "nodes": [
                    {"id": "yt-video", "name": "Video Title", "group": "youtube",
                     "summary": "A summary", "tags": ["ml"],
                     "url": "https://youtube.com/watch?v=abc", "date": "2026-03-29"},
                    {"id": "gh-repo", "name": "Repo Name", "group": "github",
                     "summary": "", "tags": ["ml", "python"],
                     "url": "https://github.com/test/repo", "date": ""},
                ],
                "links": [
                    {"source": "yt-video", "target": "gh-repo", "relation": "ml"},
                ],
            }
        }

        query.execute.return_value = _make_execute_response(data=[view_data])

        repo = _make_repo(client)
        graph = repo.get_graph(USER_ID)

        assert isinstance(graph, KGGraph)
        assert len(graph.nodes) == 2
        assert len(graph.links) == 1
        assert graph.nodes[0].id == "yt-video"
        assert graph.links[0].source == "yt-video"

    def test_get_graph_fallback(self) -> None:
        """Falls back to two-query fetch if view query fails."""
        client, query = _mock_supabase_client()

        node_rows = [
            {"id": "yt-video", "name": "Video Title", "source_type": "youtube",
             "summary": "A summary", "tags": ["ml"],
             "url": "https://youtube.com/watch?v=abc", "node_date": "2026-03-29"},
            {"id": "gh-repo", "name": "Repo Title", "source_type": "github",
             "summary": "A repo", "tags": ["ml"],
             "url": "https://github.com/org/repo", "node_date": None},
        ]
        link_rows = [
            {"source_node_id": "yt-video", "target_node_id": "gh-repo", "relation": "ml"},
        ]

        # First call (view) raises, then fallback calls return nodes + links
        query.execute.side_effect = [
            Exception("relation kg_graph_view does not exist"),
            _make_execute_response(data=node_rows),
            _make_execute_response(data=link_rows),
        ]

        repo = _make_repo(client)
        graph = repo.get_graph(USER_ID)

        assert isinstance(graph, KGGraph)
        assert len(graph.nodes) == 2
        assert len(graph.links) == 1

        # Check node conversion
        assert graph.nodes[0].id == "yt-video"
        assert graph.nodes[0].group == "youtube"
        assert graph.nodes[0].date == "2026-03-29"
        assert graph.nodes[1].date == ""  # None -> ""

        # Check link conversion
        assert graph.links[0].source == "yt-video"
        assert graph.links[0].target == "gh-repo"
        assert graph.links[0].relation == "ml"


class TestGetStats:
    def test_get_stats(self) -> None:
        client, query = _mock_supabase_client()

        # First execute for nodes count, second for links count
        query.execute.side_effect = [
            _make_execute_response(data=[], count=42),
            _make_execute_response(data=[], count=17),
        ]

        repo = _make_repo(client)
        stats = repo.get_stats(USER_ID)

        assert stats == {"node_count": 42, "link_count": 17}

    def test_get_stats_none_counts(self) -> None:
        """When count is None (no rows), should default to 0."""
        client, query = _mock_supabase_client()

        query.execute.side_effect = [
            _make_execute_response(data=[], count=None),
            _make_execute_response(data=[], count=None),
        ]

        repo = _make_repo(client)
        stats = repo.get_stats(USER_ID)

        assert stats == {"node_count": 0, "link_count": 0}


class TestNormalizeTag:
    def test_normalize_tag_strips_domain_prefix(self) -> None:
        from website.core.supabase_kg.repository import _normalize_tag

        assert _normalize_tag("domain/machine-learning") == "machine-learning"

    def test_normalize_tag_strips_keyword_prefix(self) -> None:
        from website.core.supabase_kg.repository import _normalize_tag

        assert _normalize_tag("keyword/Python") == "python"

    def test_normalize_tag_strips_status_prefix(self) -> None:
        from website.core.supabase_kg.repository import _normalize_tag

        assert _normalize_tag("status/active") == "active"

    def test_normalize_tag_strips_source_prefix(self) -> None:
        from website.core.supabase_kg.repository import _normalize_tag

        assert _normalize_tag("source/github") == "github"

    def test_normalize_tag_strips_type_prefix(self) -> None:
        from website.core.supabase_kg.repository import _normalize_tag

        assert _normalize_tag("type/tutorial") == "tutorial"

    def test_normalize_tag_passthrough(self) -> None:
        from website.core.supabase_kg.repository import _normalize_tag

        assert _normalize_tag("plain-tag") == "plain-tag"

    def test_normalize_tag_lowercases(self) -> None:
        from website.core.supabase_kg.repository import _normalize_tag

        assert _normalize_tag("UPPERCASE") == "uppercase"

    def test_normalize_tag_strips_whitespace(self) -> None:
        from website.core.supabase_kg.repository import _normalize_tag

        assert _normalize_tag("  keyword/spaced  ") == "spaced"

    def test_normalize_tag_generic_prefix(self) -> None:
        """Any prefix/value should be normalized — not just known prefixes."""
        from website.core.supabase_kg.repository import _normalize_tag

        assert _normalize_tag("custom/my-tag") == "my-tag"


class TestAutoLink:
    def test_auto_link_creates_links(self) -> None:
        """When overlapping nodes exist, _auto_link should create links to them."""
        client, query = _mock_supabase_client()

        overlapping_rows = [
            {"id": "web-old-1", "tags": ["python", "testing"]},
            {"id": "web-old-2", "tags": ["python"]},
        ]
        link_row_1 = _sample_link_row(source="web-new", target="web-old-1")
        link_row_2 = _sample_link_row(source="web-new", target="web-old-2")

        # Sequence: overlaps query -> insert link 1 -> insert link 2
        query.execute.side_effect = [
            _make_execute_response(data=overlapping_rows),  # overlap select
            _make_execute_response(data=[link_row_1]),       # insert link 1
            _make_execute_response(data=[link_row_2]),       # insert link 2
        ]

        repo = _make_repo(client)
        created = repo._auto_link(USER_ID, "web-new", ["python", "testing"])

        assert len(created) == 2
        assert all(isinstance(link, KGLink) for link in created)

    def test_auto_link_no_overlaps(self) -> None:
        """When no overlapping nodes exist, _auto_link returns empty list."""
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(data=[])

        repo = _make_repo(client)
        created = repo._auto_link(USER_ID, "web-new", ["unique-tag"])

        assert created == []

    def test_auto_link_uses_longest_shared_tag_as_relation(self) -> None:
        """The relation should be the longest shared tag."""
        client, query = _mock_supabase_client()

        overlapping_rows = [
            {"id": "web-old", "tags": ["ai", "machine-learning"]},
        ]
        link_row = _sample_link_row(source="web-new", target="web-old")
        link_row["relation"] = "machine-learning"

        query.execute.side_effect = [
            _make_execute_response(data=overlapping_rows),
            _make_execute_response(data=[link_row]),
        ]

        repo = _make_repo(client)

        # Capture what gets passed to add_link
        with patch.object(repo, "add_link", wraps=repo.add_link) as spy:
            repo._auto_link(USER_ID, "web-new", ["ai", "machine-learning"])

            # The relation arg should be "machine-learning" (longest shared tag)
            call_args = spy.call_args
            link_create = call_args[0][1]
            assert link_create.relation == "machine-learning"


class TestGetUser:
    def test_get_user_found(self) -> None:
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(
            data=[_sample_user_row()]
        )

        repo = _make_repo(client)
        user = repo.get_user(USER_ID)

        assert user is not None
        assert isinstance(user, KGUser)
        assert str(user.id) == str(USER_ID)

    def test_get_user_not_found(self) -> None:
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(data=[])

        repo = _make_repo(client)
        user = repo.get_user(USER_ID)

        assert user is None


class TestGetLinksForNode:
    def test_get_links_for_node(self) -> None:
        """Should return links where node is source or target, deduplicated."""
        client, query = _mock_supabase_client()

        link_a = _sample_link_row(source="web-node", target="web-other")
        link_b = _sample_link_row(
            link_id=uuid.uuid4(), source="web-another", target="web-node"
        )

        # First execute: source links, second: target links
        query.execute.side_effect = [
            _make_execute_response(data=[link_a]),
            _make_execute_response(data=[link_b]),
        ]

        repo = _make_repo(client)
        links = repo.get_links_for_node(USER_ID, "web-node")

        assert len(links) == 2
        assert all(isinstance(link, KGLink) for link in links)

    def test_get_links_for_node_deduplicates(self) -> None:
        """If the same link appears in both source and target results, deduplicate."""
        client, query = _mock_supabase_client()

        shared_link = _sample_link_row(source="web-a", target="web-b")

        # Same link returned from both queries
        query.execute.side_effect = [
            _make_execute_response(data=[shared_link]),
            _make_execute_response(data=[shared_link]),
        ]

        repo = _make_repo(client)
        links = repo.get_links_for_node(USER_ID, "web-a")

        assert len(links) == 1


class TestSearchNodesEscaping:
    def test_search_escapes_like_metacharacters(self) -> None:
        """% and _ in query should be escaped before passing to ilike."""
        client, query = _mock_supabase_client()
        query.execute.return_value = _make_execute_response(data=[])

        repo = _make_repo(client)
        repo.search_nodes(USER_ID, query="100%_done")

        query.ilike.assert_called_once_with("name", r"%100\%\_done%")


class TestAddNodeTagFiltering:
    def test_status_tags_filtered(self) -> None:
        """Tags starting with status/ should be excluded."""
        client, query = _mock_supabase_client()

        node_row = _sample_node_row("web-filtered")
        node_row["tags"] = ["python"]

        # Chain: insert node → overlap query (no matches)
        query.execute.side_effect = [
            _make_execute_response(data=[node_row]),  # insert node
            _make_execute_response(data=[]),           # overlap query (no links)
        ]

        repo = _make_repo(client)
        node_create = KGNodeCreate(
            id="web-filtered",
            name="Filtered",
            source_type="web",
            tags=["keyword/python", "status/raw"],
            url="https://example.com/filtered",
        )
        repo.add_node(USER_ID, node_create)

        # Check the payload that was passed to insert
        insert_call = query.insert.call_args[0][0]
        assert "raw" not in insert_call["tags"]
        assert "python" in insert_call["tags"]

    def test_source_type_name_tags_filtered(self) -> None:
        """Tags that are just source-type names (youtube, reddit, etc.) should be excluded."""
        client, query = _mock_supabase_client()

        node_row = _sample_node_row("web-source-filtered")
        node_row["tags"] = ["ml"]

        # Chain: insert node → overlap query (no matches)
        query.execute.side_effect = [
            _make_execute_response(data=[node_row]),  # insert node
            _make_execute_response(data=[]),           # overlap query (no links)
        ]

        repo = _make_repo(client)
        node_create = KGNodeCreate(
            id="web-source-filtered",
            name="Source Filtered",
            source_type="youtube",
            tags=["source/youtube", "keyword/ml"],
            url="https://example.com/src",
        )
        repo.add_node(USER_ID, node_create)

        insert_call = query.insert.call_args[0][0]
        assert "youtube" not in insert_call["tags"]
        assert "ml" in insert_call["tags"]
