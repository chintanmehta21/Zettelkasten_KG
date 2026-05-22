"""Unit tests for the operation-id correlation ContextVar."""
from __future__ import annotations

import asyncio

from website.core.request_context import get_operation_id, operation_context


def test_default_is_dash():
    assert get_operation_id() == "-"


def test_context_binds_and_resets():
    assert get_operation_id() == "-"
    with operation_context("zettel:123:abc"):
        assert get_operation_id() == "zettel:123:abc"
    assert get_operation_id() == "-"


def test_empty_operation_id_falls_back_to_dash():
    with operation_context(""):
        assert get_operation_id() == "-"


def test_nested_contexts_restore_outer():
    with operation_context("outer"):
        with operation_context("inner"):
            assert get_operation_id() == "inner"
        assert get_operation_id() == "outer"
    assert get_operation_id() == "-"


def test_id_visible_inside_spawned_task():
    # ContextVar copies into a child task at spawn time — the engine relies on
    # this so asyncio.shield(persist(...)) still sees the operation id.
    async def _run() -> str:
        with operation_context("zettel:xyz"):
            return await asyncio.create_task(_child())

    async def _child() -> str:
        return get_operation_id()

    assert asyncio.run(_run()) == "zettel:xyz"
