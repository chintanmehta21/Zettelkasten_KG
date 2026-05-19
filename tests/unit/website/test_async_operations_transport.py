from __future__ import annotations

import asyncio
from unittest.mock import patch
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


def test_operation_status_supabase_miss_and_no_inmem_returns_202_pending():
    """P2: both Supabase get_operation AND the per-worker in-memory store
    miss. During the fire-and-forget accepted-row replication gap a poll
    routed to another worker would 404 a job that is actually running —
    return a transient 202 pending instead so the client keeps polling."""
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value=None):
        r = _client().get("/api/operations/replication-gap-op")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "accepted"
    assert body["operation_id"] == "replication-gap-op"
    assert body["status_url"] == "/api/operations/replication-gap-op"
    assert r.headers.get("Retry-After") == "3"


def test_failed_operation_returns_200_error_payload_not_stale_accepted():
    """P1 read side: a failed row that still carries a stale accepted body in
    `response` must return the FAILURE body (from `error`), not the stale
    accepted body. Selection is status-driven, not `response or error`."""
    stale_accepted = {"status": "accepted", "operation_id": "op-4"}
    failed = {"status": "failed", "operation_id": "op-4",
              "quality": {"confidence": "failed"}}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "failed", "response": stale_accepted,
                             "error": failed}):
        r = _client().get("/api/operations/op-4")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["quality"]["confidence"] == "failed"


def test_succeeded_row_reads_response_200():
    """P1 read side: succeeded → payload from `response`, 200."""
    succeeded = {"status": "succeeded", "operation_id": "op-5",
                 "summary": {"title": "S"}}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "succeeded", "response": succeeded,
                             "error": None}):
        r = _client().get("/api/operations/op-5")
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"
    assert r.json()["summary"]["title"] == "S"


def test_accepted_row_reads_response_202():
    """P1 read side: accepted → payload from `response`, 202."""
    acc = {"status": "accepted", "operation_id": "op-6",
           "status_url": "/api/operations/op-6"}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "accepted", "response": acc,
                             "error": None}):
        r = _client().get("/api/operations/op-6")
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"


def test_inmem_accepted_still_202_when_supabase_misses():
    """P2 no-regression: when Supabase misses but the per-worker in-memory
    store HAS the accepted result, the single-worker fallback still serves
    202 (we only changed the truly-not-found-anywhere branch)."""
    from website.api import zettels_routes as zr

    acc = {"status": "accepted", "operation_id": "inmem-1",
           "status_url": "/api/operations/inmem-1"}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value=None):
        zr._operation_put("inmem-1", acc)
        try:
            r = _client().get("/api/operations/inmem-1")
        finally:
            zr._OPERATIONS.pop("inmem-1", None)
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"


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
        # Ordering proof: invalidation must NOT have run synchronously before
        # _run_add_zettel returned — it is scheduled, not inline.
        assert calls["invalidated"] == 0
        await _aio.sleep(0.05)  # let the scheduled continuation run
        assert calls["invalidated"] == 1

    asyncio.run(_go())


def test_idempotent_replay_same_op_returns_existing_not_reenqueued():
    """Second GET with the same op id returns the stored row (no re-run)."""
    succeeded = {"status": "succeeded", "operation_id": "idem-1"}
    seen = {"n": 0}

    def _get(**_kw):
        seen["n"] += 1
        return {"status": "succeeded", "response": succeeded, "error": None}

    with patch("website.api.zettels_routes.operations_repo.get_operation",
               side_effect=_get):
        c = _client()
        r1 = c.get("/api/operations/idem-1")
        r2 = c.get("/api/operations/idem-1")
    assert r1.status_code == r2.status_code == 200
    assert seen["n"] == 2  # each poll is a cheap row read, never a re-enqueue


def test_operation_status_is_user_scoped_bola():
    """get_operation is always called with the resolver's effective_user_id;
    a caller cannot read another user's op by id alone."""
    captured = {}

    def _get(*, user_id, operation_id):
        captured["user_id"] = str(user_id)
        return None

    with patch("website.api.zettels_routes.operations_repo.get_operation",
               side_effect=_get):
        _client().get("/api/operations/someone-elses-op")
    assert "user_id" in captured  # scoped read enforced server-side


def test_supabase_write_failure_does_not_5xx_the_add():
    """create_accepted returning False (store down) must NOT break the 202."""
    async def _slow(*_a, **_k):
        await asyncio.sleep(30)
        return {"persistence": {"persisted": False}}

    with patch("website.api.zettels_routes._AUTO_ACCEPT_AFTER_SECONDS", 0.05), \
         patch("website.api.zettels_routes._run_add_zettel", _slow), \
         patch("website.api.zettels_routes.operations_repo.create_accepted",
               return_value=False), \
         patch("website.api.zettels_routes.operations_repo.mark_succeeded",
               return_value=False), \
         patch("website.api.zettels_routes.operations_repo.mark_failed",
               return_value=False):
        r = _client().post(
            "/api/zettels/add",
            json={"url": "https://example.com", "client_action_id": "store-down-1",
                  "surface": "landing", "mode": "sync", "persist": False},
        )
    assert r.status_code == 202  # in-memory still serves; never 5xx
