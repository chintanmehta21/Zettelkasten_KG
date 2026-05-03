"""iter-09 RES-6: router LRU+TTL classification cache."""
import pytest
from website.features.rag_pipeline.query.router import QueryRouter
from website.features.rag_pipeline.types import QueryClass


class _StubPool:
    def __init__(self, response):
        self._response = response
        self.calls = 0

    async def generate_content(self, *a, **k):
        self.calls += 1
        return self._response


@pytest.mark.asyncio
async def test_classify_caches_repeat_query(monkeypatch):
    monkeypatch.setenv("ROUTER_CACHE_ENABLED", "true")
    pool = _StubPool('{"class":"lookup"}')
    router = QueryRouter(pool=pool, kasten_id="k1")
    cls1 = await router.classify("hello world")
    cls2 = await router.classify("hello world")
    assert cls1 is QueryClass.LOOKUP
    assert cls2 is QueryClass.LOOKUP
    assert pool.calls == 1


@pytest.mark.asyncio
async def test_router_version_bump_invalidates_cache(monkeypatch):
    monkeypatch.setenv("ROUTER_CACHE_ENABLED", "true")
    pool = _StubPool('{"class":"lookup"}')
    router_a = QueryRouter(pool=pool, kasten_id="k1")
    await router_a.classify("hello")
    monkeypatch.setattr(
        "website.features.rag_pipeline.query.router.ROUTER_VERSION",
        "v_test_bump",
    )
    router_b = QueryRouter(pool=pool, kasten_id="k1")
    await router_b.classify("hello")
    assert pool.calls == 2


@pytest.mark.asyncio
async def test_cache_disabled_via_env(monkeypatch):
    monkeypatch.setenv("ROUTER_CACHE_ENABLED", "false")
    pool = _StubPool('{"class":"lookup"}')
    router = QueryRouter(pool=pool, kasten_id="k1")
    await router.classify("hello")
    await router.classify("hello")
    assert pool.calls == 2
