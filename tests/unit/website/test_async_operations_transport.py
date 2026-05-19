from __future__ import annotations

import asyncio
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from website.app import create_app


def _client():
    return TestClient(create_app())


def test_slow_add_fast_acks_202_for_sync_mode():
    """mode:'sync' (the prod frontend default) must STILL get a 202 when synth
    exceeds N — the gate that previously required mode=='auto' is removed."""
    async def _slow(*_a, **_k):
        await asyncio.sleep(30)
        return {"persistence": {"persisted": False}}

    captured = {}

    def _create_accepted(**kw):
        captured.update(kw)
        return True

    with patch("website.api.zettels_routes._AUTO_ACCEPT_AFTER_SECONDS", 0.05), \
         patch("website.api.zettels_routes._run_add_zettel", _slow), \
         patch("website.api.zettels_routes.operations_repo.create_accepted",
               side_effect=_create_accepted), \
         patch("website.api.zettels_routes.operations_repo.mark_succeeded",
               return_value=True), \
         patch("website.api.zettels_routes.operations_repo.mark_failed",
               return_value=True):
        r = _client().post(
            "/api/zettels/add",
            json={"url": "https://example.com", "client_action_id": "op-sync-1",
                  "surface": "landing", "mode": "sync", "persist": False},
        )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "accepted"
    assert body["operation_id"] == "op-sync-1"
    assert body["status_url"] == "/api/operations/op-sync-1"
    assert r.headers.get("Location") == "/api/operations/op-sync-1"
    assert captured.get("operation_id") == "op-sync-1"  # accepted row written


def test_operation_status_reads_supabase_first_user_scoped():
    succeeded = {"status": "succeeded", "operation_id": "op-2",
                 "summary": {"title": "T"}, "persistence": {"persisted": True}}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "succeeded", "response": succeeded,
                             "error": None}):
        r = _client().get("/api/operations/op-2")
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"
    assert r.json()["summary"]["title"] == "T"


def test_operation_status_202_while_accepted():
    acc = {"status": "accepted", "operation_id": "op-3",
           "status_url": "/api/operations/op-3"}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "accepted", "response": acc, "error": None}):
        r = _client().get("/api/operations/op-3")
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"


def test_operation_status_supabase_miss_falls_back_then_404():
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value=None):
        r = _client().get("/api/operations/nope")
    assert r.status_code == 404
    assert r.json()["type"].endswith("operation-not-found")


def test_failed_operation_returns_200_failed_payload():
    failed = {"status": "failed", "operation_id": "op-4",
              "quality": {"confidence": "failed"}}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "failed", "response": failed,
                             "error": failed}):
        r = _client().get("/api/operations/op-4")
    assert r.status_code == 200
    assert r.json()["status"] == "failed"


def test_run_add_zettel_does_not_block_on_graph_invalidation(monkeypatch):
    """_run_add_zettel must return the pipeline result WITHOUT awaiting graph
    invalidation; invalidation is scheduled as a post-return continuation."""
    import asyncio as _aio

    from website.api import zettels_routes as zr

    calls = {"invalidated": 0}

    async def _fake_pipeline(**_kw):
        return {
            "persistence": {
                "persisted": True, "requested": True,
                "file_store": False, "supabase": True, "duplicate": False,
            },
            "summary": {"title": "X"},
        }

    def _slow_invalidate(_sub, _persisted):
        calls["invalidated"] += 1

    monkeypatch.setattr(zr, "run_add_zettel_pipeline", _fake_pipeline)
    monkeypatch.setattr(zr, "_invalidate_graph", _slow_invalidate)

    async def _go():
        body = zr.AddZettelRequest(
            url="https://example.com", client_action_id="g-1",
            surface="landing", mode="sync",
        )
        res = await zr._run_add_zettel(
            body, user=None, effective_user_id=zr._zoro_user_id()
        )
        # result returned immediately; invalidation deferred to a task
        assert res["persistence"]["persisted"] is True
        await _aio.sleep(0.05)  # let the scheduled continuation run
        assert calls["invalidated"] == 1

    asyncio.run(_go())
