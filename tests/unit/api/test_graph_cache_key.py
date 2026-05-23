"""K2: cache bucket label must include limit/offset so paginated requests don't collide.

Also covers LD-7: only the default (5000, 0) page is cacheable; non-default
pagination bypasses cache (asserted via runner-level test in
test_view_graph_pagination.py — this file pins the bucket-label contract).
"""
from __future__ import annotations

import asyncio

import pytest

from website.api.graph_cache import UserGraphCache
from website.api.module_runners.view_graph import (
    _bucket_label_global,
    _bucket_label_my,
    _is_cacheable_page,
)


def test_different_limits_get_separate_cache_slots():
    cache = UserGraphCache()
    calls: list[str] = []

    async def loader_5000():
        calls.append("5000")
        return {"nodes": [{"id": "x"} for _ in range(5000)], "links": []}

    async def loader_10():
        calls.append("10")
        return {"nodes": [{"id": "x"} for _ in range(10)], "links": []}

    async def go():
        r1 = await cache.get_or_load("u1", "my:strong:5000:0", loader_5000)
        r2 = await cache.get_or_load("u1", "my:strong:10:0", loader_10)
        return r1, r2

    r1, r2 = asyncio.run(go())
    assert len(r1["nodes"]) == 5000
    assert len(r2["nodes"]) == 10
    assert calls == ["5000", "10"], "K2: different limits must hit different cache slots"


def test_bucket_label_my_includes_limit_and_offset():
    label = _bucket_label_my(0.3, limit=5000, offset=0)
    assert "5000" in label
    assert ":0" in label
    label2 = _bucket_label_my(0.3, limit=10, offset=20)
    assert label != label2, "K2: different (limit, offset) MUST produce different labels"


def test_bucket_label_global_includes_limit_and_offset():
    label = _bucket_label_global(0.3, limit=5000, offset=0)
    label2 = _bucket_label_global(0.3, limit=10, offset=0)
    assert label != label2


def test_is_cacheable_page_only_default():
    assert _is_cacheable_page(5000, 0) is True
    assert _is_cacheable_page(5000, 100) is False
    assert _is_cacheable_page(100, 0) is False
    assert _is_cacheable_page(10000, 0) is False
