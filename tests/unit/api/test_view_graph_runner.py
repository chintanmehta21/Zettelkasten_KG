"""Unit tests for the ``view_graph`` module runner (new_apis_1a).

Fully mocked — no live Supabase, no real Gemini. Patches the routes-side
assembler / enricher (where the heavy graph logic lives) and the
graph_cache so the runner's routing rules are exercised in isolation.

Covers: view inference (anonymous → global, authenticated → my),
strict ``view=my`` semantics (no fallthrough to global per new_apis1.md),
D1 verdict (anonymous NEVER serves Zoro's personal graph), kasten BOLA
gate, kasten subgraph filtering, and input validation.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from website.api.module_runners.view_graph import (
    KastenNotFoundError,
    run_view_graph,
)

NARUTO = uuid.UUID("f2105544-b73d-4946-8329-096d82f070d3")
WS_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
KASTEN_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def _passthrough_cache():
    """Replace the per-user cache with a pass-through that always calls loader."""
    async def _loader_passthrough(user_id, bucket, loader):
        del user_id, bucket
        return await loader()

    cache = MagicMock()
    cache.get_or_load = AsyncMock(side_effect=_loader_passthrough)
    with patch(
        "website.api.graph_cache.get_default_cache", return_value=cache
    ):
        yield cache


@pytest.fixture
def _stub_routes_helpers(monkeypatch):
    """Stub the heavy routes.py helpers with identity behaviour."""
    from website.api import routes as _routes

    monkeypatch.setattr(
        _routes,
        "_enrich_graph_with_analytics",
        lambda payload, min_strength=None: dict(payload),
    )
    monkeypatch.setattr(
        _routes,
        "_apply_min_strength_filter",
        lambda payload, ms: dict(payload),
    )
    monkeypatch.setattr(_routes, "_trim_graph_response", lambda payload: dict(payload))
    return _routes


def _v2_graph_dump(canonical_ids: list[str]) -> dict:
    """Build a fake _v2_assemble_graph return-value dict.

    Node ids end in ``-{canonical[:8]}`` so the Kasten filter can match.
    """
    nodes = [
        {"id": f"web-slug-{cid[:8]}", "name": cid, "group": "web"}
        for cid in canonical_ids
    ]
    # Link first two nodes if we have ≥2.
    links = []
    if len(nodes) >= 2:
        links.append({
            "source": nodes[0]["id"],
            "target": nodes[1]["id"],
            "relation": "shared_tag",
            "connection_strength": 0.8,
        })
    return {"nodes": nodes, "links": links, "total_nodes": len(nodes)}


def _v2_graph_kg(canonical_ids: list[str]):
    """A mock KGGraph-shaped object whose .model_dump() returns the dict above."""
    m = MagicMock()
    m.model_dump = lambda: _v2_graph_dump(canonical_ids)
    return m


# ─────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_view_literal_raises(_stub_routes_helpers):
    with pytest.raises(ValueError, match="view must be"):
        await run_view_graph(user=None, view="wrong")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_invalid_limit_raises(_stub_routes_helpers):
    with pytest.raises(ValueError, match="limit"):
        await run_view_graph(user=None, view="global", limit=0)


@pytest.mark.asyncio
async def test_kasten_view_requires_kasten_id(_stub_routes_helpers):
    with pytest.raises(ValueError, match="requires a kasten_id"):
        await run_view_graph(
            user={"sub": str(NARUTO)},
            view="kasten",
            kasten_id=None,
        )


# ─────────────────────────────────────────────────────────────────────────
# Anonymous → global, NEVER Zoro (D1)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_default_serves_global_file_store(_stub_routes_helpers):
    """No user + no view → file-store global (NEVER Zoro per D1)."""
    file_store = {"nodes": [{"id": "global-1"}], "links": [], "total_nodes": 1}
    with patch(
        "website.core.graph_store.get_graph", return_value=file_store
    ):
        result = await run_view_graph(user=None, view=None)
    assert result["meta"]["view"] == "global"
    assert result["meta"]["source"] == "file-store"
    assert result["nodes"] == [{"id": "global-1"}]


@pytest.mark.asyncio
async def test_explicit_global_view_serves_file_store(_stub_routes_helpers):
    """Authenticated user with view='global' STILL gets file-store (not their own)."""
    file_store = {"nodes": [], "links": [], "total_nodes": 0}
    with patch(
        "website.core.graph_store.get_graph", return_value=file_store
    ):
        result = await run_view_graph(
            user={"sub": str(NARUTO)}, view="global"
        )
    assert result["meta"]["view"] == "global"
    assert result["meta"]["source"] == "file-store"


@pytest.mark.asyncio
async def test_anonymous_view_my_returns_empty_not_zoro(_stub_routes_helpers):
    """D1 LOCKED VERDICT: anonymous + view='my' MUST NOT fall through to
    Zoro's personal graph (BOLA). Returns explicit empty personal graph."""
    result = await run_view_graph(user=None, view="my")
    assert result["nodes"] == []
    assert result["links"] == []
    assert result["total_nodes"] == 0
    # Meta indicates the strict empty path was taken.
    assert result["meta"]["source"] == "no-scope"


# ─────────────────────────────────────────────────────────────────────────
# view='my' (strict semantics per new_apis1.md tightening)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_view_my_uses_v2_assembler_when_scope_resolves(
    _stub_routes_helpers, _passthrough_cache
):
    """Authenticated user + v2 scope → _v2_assemble_graph result."""
    canonical_ids = ["aaaaaaaa-0000", "bbbbbbbb-0000"]
    with patch.object(
        _stub_routes_helpers, "_v2_assemble_graph",
        return_value=_v2_graph_kg(canonical_ids),
    ), patch(
        "website.core.db_version.use_supabase_v2", return_value=True
    ):
        result = await run_view_graph(
            user={"sub": str(NARUTO)}, view="my"
        )
    assert result["meta"]["view"] == "my"
    assert result["meta"]["source"] == "v2"
    assert len(result["nodes"]) == 2


@pytest.mark.asyncio
async def test_view_my_strict_no_fallthrough_when_no_v2_scope(
    _stub_routes_helpers, _passthrough_cache
):
    """new_apis1.md tightening: ``view=my`` with no v2 scope → empty graph,
    NEVER fall through to global file-store."""
    with patch.object(
        _stub_routes_helpers, "_v2_assemble_graph", return_value=None,
    ), patch(
        "website.core.db_version.use_supabase_v2", return_value=True
    ):
        result = await run_view_graph(
            user={"sub": str(NARUTO)}, view="my"
        )
    assert result["nodes"] == []
    assert result["meta"]["source"] == "no-scope"


@pytest.mark.asyncio
async def test_view_my_strict_when_v2_disabled(_stub_routes_helpers):
    """``view=my`` with ``use_supabase_v2() = False`` → empty graph (no fallthrough)."""
    with patch(
        "website.core.db_version.use_supabase_v2", return_value=False
    ):
        result = await run_view_graph(
            user={"sub": str(NARUTO)}, view="my"
        )
    assert result["nodes"] == []
    assert result["meta"]["source"] == "no-scope"


@pytest.mark.asyncio
async def test_view_inferred_to_my_when_authenticated(
    _stub_routes_helpers, _passthrough_cache
):
    """Authenticated user with view omitted → infer 'my'."""
    with patch.object(
        _stub_routes_helpers, "_v2_assemble_graph", return_value=_v2_graph_kg([]),
    ), patch(
        "website.core.db_version.use_supabase_v2", return_value=True
    ):
        result = await run_view_graph(
            user={"sub": str(NARUTO)}, view=None
        )
    assert result["meta"]["view"] == "my"


# ─────────────────────────────────────────────────────────────────────────
# view='kasten' (D6 + BOLA gate)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_view_kasten_no_v2_scope_is_kasten_not_found(_stub_routes_helpers):
    """Caller without a v2 scope cannot own any kasten → BOLA error."""
    with patch(
        "website.core.persist.get_supabase_v2_scope", return_value=None,
    ):
        with pytest.raises(KastenNotFoundError):
            await run_view_graph(
                user={"sub": str(NARUTO)},
                view="kasten",
                kasten_id=KASTEN_ID,
            )


@pytest.mark.asyncio
async def test_view_kasten_cross_tenant_is_kasten_not_found(_stub_routes_helpers):
    """``rag_repo.get_kasten`` returning None → cross-tenant or missing."""
    content_repo = MagicMock()
    rag_repo = MagicMock()
    rag_repo.get_kasten.return_value = None

    with patch(
        "website.core.persist.get_supabase_v2_scope",
        return_value=(content_repo, uuid.uuid4(), WS_ID),
    ), patch(
        "website.core.supabase_v2.repositories.rag_repository.RAGRepository",
        return_value=rag_repo,
    ):
        with pytest.raises(KastenNotFoundError) as excinfo:
            await run_view_graph(
                user={"sub": str(NARUTO)},
                view="kasten",
                kasten_id=KASTEN_ID,
            )
        assert excinfo.value.kasten_id == str(KASTEN_ID)


@pytest.mark.asyncio
async def test_view_kasten_filters_to_member_subgraph(
    _stub_routes_helpers, _passthrough_cache
):
    """``view=kasten`` intersects the v2 graph with rag.list_kasten_zettels."""
    content_repo = MagicMock()
    rag_repo = MagicMock()
    rag_repo.get_kasten.return_value = {"id": str(KASTEN_ID)}
    # Kasten owns canonical ids whose first 8 chars match node-id suffixes.
    rag_repo.list_kasten_zettels.return_value = [
        {"canonical_zettel_id": "aaaaaaaa-1111-1111-1111-111111111111"},
    ]

    full_graph = _v2_graph_kg([
        "aaaaaaaa-1111-1111-1111-111111111111",
        "bbbbbbbb-2222-2222-2222-222222222222",  # NOT in Kasten — must be filtered out
    ])

    with patch(
        "website.core.persist.get_supabase_v2_scope",
        return_value=(content_repo, uuid.uuid4(), WS_ID),
    ), patch(
        "website.core.supabase_v2.repositories.rag_repository.RAGRepository",
        return_value=rag_repo,
    ), patch.object(
        _stub_routes_helpers, "_v2_assemble_graph", return_value=full_graph,
    ):
        result = await run_view_graph(
            user={"sub": str(NARUTO)},
            view="kasten",
            kasten_id=KASTEN_ID,
        )

    assert result["meta"]["view"] == "kasten"
    assert result["meta"]["kasten_id"] == str(KASTEN_ID)
    # Only the aaaaaaaa-prefixed node survived the intersection.
    node_ids = [n["id"] for n in result["nodes"]]
    assert any("aaaaaaaa" in nid for nid in node_ids)
    assert not any("bbbbbbbb" in nid for nid in node_ids)


def test_runner_has_cli_entrypoint_and_conventions():
    """Module runner convention check — same as ask_kasten / create_kasten."""
    source = open(
        "website/api/module_runners/view_graph.py", encoding="utf-8"
    ).read()
    assert "argparse.ArgumentParser" in source
    assert 'if __name__ == "__main__"' in source
    # D1 evidence in source: explicit "NEVER served to anonymous" reasoning.
    assert "Zoro" in source
