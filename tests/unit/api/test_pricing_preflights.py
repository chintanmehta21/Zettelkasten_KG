from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from website.api import routes


@pytest.mark.asyncio
async def test_summarize_checks_entitlement_before_expensive_work(monkeypatch) -> None:
    called = {"entitlement": False, "summarize": False}

    async def deny(*args, **kwargs):
        called["entitlement"] = True
        raise HTTPException(status_code=402, detail={"code": "quota_exhausted", "meter": "zettel"})

    async def expensive(url: str):
        called["summarize"] = True
        return {"url": url}

    monkeypatch.setattr(routes, "require_entitlement", deny)
    monkeypatch.setattr(routes, "summarize_url", expensive)
    routes._rate_store.clear()

    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    with pytest.raises(HTTPException) as exc:
        await routes.summarize(routes.SummarizeRequest(url="https://example.com"), request, {"sub": "user-1"})

    assert exc.value.status_code == 402
    assert called == {"entitlement": True, "summarize": False}

