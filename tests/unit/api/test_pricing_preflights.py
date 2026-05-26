from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from website.api import zettels_routes
from website.api.module_runners import summarization as runner


@pytest.mark.asyncio
async def test_add_zettel_checks_entitlement_before_expensive_work(monkeypatch) -> None:
    """PR #39 / Wave-1 A1: the route now always returns 202 and runs the
    pipeline in a background _run task. Entitlement still gates the
    expensive work — assert that require_entitlement fires AND that
    summarize_url_bundle never runs, by inspecting the spawned _run task
    after it settles. The 402 surfaces via the failed operations row on
    the subsequent GET /api/operations/{id} (covered in
    test_async_operations_transport.py)."""

    called = {"entitlement": False, "summarize": False}

    async def deny(*args, **kwargs):
        called["entitlement"] = True
        raise HTTPException(
            status_code=402, detail={"code": "quota_exhausted", "meter": "zettel"}
        )

    async def expensive(*args, **kwargs):
        called["summarize"] = True
        return {"url": args[0] if args else kwargs.get("url")}

    monkeypatch.setattr(runner, "require_entitlement", deny)
    monkeypatch.setattr(runner, "summarize_url_bundle", expensive)
    # Stub the operations RPC layer so the test doesn't hit real Supabase.
    monkeypatch.setattr(
        zettels_routes.operations_repo,
        "accept",
        lambda **kw: (kw["operation_id"], True),
    )
    monkeypatch.setattr(zettels_routes.operations_repo, "start", lambda **kw: True)
    monkeypatch.setattr(zettels_routes.operations_repo, "finalize", lambda **kw: True)
    # Backpressure gate: fail-open.
    monkeypatch.setattr(
        zettels_routes,
        "check_async_backpressure",
        lambda **kw: _none_coro(),
    )
    zettels_routes._RATE_STORE.clear()
    zettels_routes._LIVE_TASKS.pop("quota-preflight", None)

    # PR #109: route reads request.state.auth_status via _compute_auth_intent.
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
        state=SimpleNamespace(),
    )

    response = await zettels_routes.add_zettel(
        zettels_routes.AddZettelRequest(
            url="https://example.com",
            client_action_id="quota-preflight",
            persist=True,
            surface="home",
        ),
        request,
        {"sub": "00000000-0000-0000-0000-000000000001"},
    )

    # Route always 202s now (A1: single-pipeline-path refactor).
    assert response.status_code == 202

    # Let the spawned _run task settle so the entitlement deny fires before
    # we assert on `called`. The task is registered in _LIVE_TASKS and
    # naturally completes once require_entitlement raises 402.
    task = zettels_routes._LIVE_TASKS.get("quota-preflight")
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except Exception:
            pass  # the task raised — that's the deny path we wanted

    # Critical invariant: entitlement check fired BEFORE summarize.
    assert called == {"entitlement": True, "summarize": False}


async def _none_coro():
    """Helper: async lambda placeholder for backpressure mock (always
    returns None = no backpressure)."""
    return None
