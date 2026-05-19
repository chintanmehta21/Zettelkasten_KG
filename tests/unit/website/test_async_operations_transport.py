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
