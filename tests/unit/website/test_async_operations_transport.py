from __future__ import annotations

import asyncio
from unittest.mock import patch
from fastapi.testclient import TestClient

from website.app import create_app


def _client():
    return TestClient(create_app())


def test_slow_add_fast_acks_202_for_sync_mode():
    """mode:'sync' (the prod frontend default) must STILL get a 202 when synth
    exceeds the auto-accept window — the gate that previously required
    mode=='auto' is removed. Phase 2 (async-ops redesign): the route now calls
    operations_repo.accept (state-guarded RPC) instead of legacy create_accepted."""
    async def _slow(*_a, **_k):
        await asyncio.sleep(30)
        return {"persistence": {"persisted": False}}

    captured = {}

    def _accept(**kw):
        captured.update(kw)
        return (kw.get("operation_id"), True)  # canonical_op_id, is_new

    with patch("website.api.zettels_routes._AUTO_ACCEPT_AFTER_SECONDS", 0.05), \
         patch("website.api.zettels_routes._run_add_zettel", _slow), \
         patch("website.api.zettels_routes.operations_repo.accept",
               side_effect=_accept), \
         patch("website.api.zettels_routes.operations_repo.start",
               return_value=True), \
         patch("website.api.zettels_routes.operations_repo.finalize",
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
    assert captured.get("operation_id") == "op-sync-1"  # accept RPC called


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
    # Phase 2 (async-ops redesign): Retry-After tightened from 3s to 2s
    # (the DB row is faster than the legacy in-memory fallback).
    assert r.headers.get("Retry-After") == "2"


def test_failed_operation_returns_200_failed_body_from_response_column():
    """Phase 2 (async-ops redesign): `_run` writes the full AddZettelResponse
    (status='failed', ...) into the `response` column on the failed path. The
    GET handler returns that body verbatim with HTTP 200. (The legacy concern
    of a stale `accepted` body in `response` is dead: the new state-guarded
    finalize RPC writes status + response atomically — never split.)"""
    failed_body = {"status": "failed", "operation_id": "op-4",
                   "quality": {"confidence": "failed"},
                   "error": {"code": "kg-write-failed", "status": 502}}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "failed", "response": failed_body,
                             "error": failed_body["error"]}):
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


def test_failed_op_GET_returns_body_including_structured_error_field():
    """Phase 2 (async-ops redesign): the full failed AddZettelResponse (with a
    nested RFC 9457 `error` dict) lives in the `response` column; the GET
    returns it verbatim. Frontend polls then see `next.error.detail.code`
    after the F1 reject and route into UI classifiers."""
    failed_with_struct = {
        "status": "failed",
        "operation_id": "op-struct-1",
        "quality": {"confidence": "failed",
                    "confidence_reason": "402: quota exhausted"},
        "error": {
            "type": "https://zettelkasten.in/problems/errors/quota-exhausted",
            "title": "Quota exhausted",
            "status": 402,
            "detail": {"code": "quota_exhausted", "message": "Quota exhausted"},
        },
    }
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "failed", "response": failed_with_struct,
                             "error": failed_with_struct["error"]}):
        r = _client().get("/api/operations/op-struct-1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    # Structured detail survives the GET handler verbatim.
    assert body["error"]["detail"]["code"] == "quota_exhausted"
    assert body["error"]["status"] == 402


def test_supabase_write_failure_does_not_5xx_the_add():
    """Phase 2 (async-ops redesign): accept RPC raising (store down) must NOT
    break the 202. The defensive fallback in operations_repo.accept returns
    (operation_id, True) so the request path still spawns a background task
    and returns the 202 envelope to the client."""
    async def _slow(*_a, **_k):
        await asyncio.sleep(30)
        return {"persistence": {"persisted": False}}

    with patch("website.api.zettels_routes._AUTO_ACCEPT_AFTER_SECONDS", 0.05), \
         patch("website.api.zettels_routes._run_add_zettel", _slow), \
         patch("website.api.zettels_routes.operations_repo.accept",
               side_effect=RuntimeError("supabase down")), \
         patch("website.api.zettels_routes.operations_repo.start",
               return_value=False), \
         patch("website.api.zettels_routes.operations_repo.finalize",
               return_value=False):
        r = _client().post(
            "/api/zettels/add",
            json={"url": "https://example.com", "client_action_id": "store-down-1",
                  "surface": "landing", "mode": "sync", "persist": False},
        )
    assert r.status_code == 202  # accept fail-open; never 5xx


# ---------------------------------------------------------------------------
# Phase 2 (async-ops redesign): new transport tests exercising the ops.*
# RPC-backed accept/get/delete path. The legacy tests above remain green
# until Phase 5 deletes the in-memory machinery.
# ---------------------------------------------------------------------------


def test_accept_path_calls_ops_accept_rpc_and_returns_202_with_location():
    """The new accept path calls operations_repo.accept and returns 202 with
    a Location header pointing at the canonical op id + Retry-After: 2."""
    async def _slow(*_a, **_k):
        await asyncio.sleep(30)
        return {"persistence": {"persisted": False}}

    accept_calls: list[dict] = []

    def _accept(**kw):
        accept_calls.append(kw)
        return (kw.get("operation_id"), True)

    with patch("website.api.zettels_routes._AUTO_ACCEPT_AFTER_SECONDS", 0.05), \
         patch("website.api.zettels_routes._run_add_zettel", _slow), \
         patch("website.api.zettels_routes.operations_repo.accept",
               side_effect=_accept), \
         patch("website.api.zettels_routes.operations_repo.start",
               return_value=True), \
         patch("website.api.zettels_routes.operations_repo.finalize",
               return_value=True):
        r = _client().post(
            "/api/zettels/add",
            json={"url": "https://example.com", "client_action_id": "ph2-accept",
                  "surface": "landing", "mode": "sync", "persist": False},
        )
    assert r.status_code == 202
    assert r.headers.get("Location") == "/api/operations/ph2-accept"
    assert r.headers.get("Retry-After") == "2"
    assert len(accept_calls) == 1
    assert accept_calls[0]["operation_id"] == "ph2-accept"
    assert "request_hash" in accept_calls[0]
    assert accept_calls[0]["ttl_seconds"] == 86400


def test_accept_returns_existing_op_id_when_not_new():
    """Duplicate active (user_id, request_hash): ops.accept returns is_new=False
    and the canonical (existing) op id. The route must NOT spawn a duplicate
    background task, and the 202 body/headers must point at the canonical op."""
    spawn_count = {"n": 0}

    async def _slow(*_a, **_k):
        spawn_count["n"] += 1
        await asyncio.sleep(30)
        return {"persistence": {"persisted": False}}

    def _accept(**_kw):
        return ("canonical-existing", False)

    with patch("website.api.zettels_routes._AUTO_ACCEPT_AFTER_SECONDS", 0.05), \
         patch("website.api.zettels_routes._run_add_zettel", _slow), \
         patch("website.api.zettels_routes.operations_repo.accept",
               side_effect=_accept), \
         patch("website.api.zettels_routes.operations_repo.start",
               return_value=True), \
         patch("website.api.zettels_routes.operations_repo.finalize",
               return_value=True):
        from website.api import zettels_routes as zr
        before_live = set(zr._LIVE_TASKS.keys())
        r = _client().post(
            "/api/zettels/add",
            json={"url": "https://example.com", "client_action_id": "client-attempt",
                  "surface": "landing", "mode": "sync", "persist": False},
        )
        after_live = set(zr._LIVE_TASKS.keys())
    assert r.status_code == 202
    body = r.json()
    assert body["operation_id"] == "canonical-existing"
    assert body["status_url"] == "/api/operations/canonical-existing"
    assert r.headers.get("Location") == "/api/operations/canonical-existing"
    # The probe task spawned by the route is cancelled in the !is_new path;
    # NO new _LIVE_TASKS entry for the canonical op (already owned elsewhere).
    assert "canonical-existing" not in after_live - before_live


def test_accept_honors_idempotency_key_header():
    """`Idempotency-Key` HTTP header (IETF draft) overrides client_action_id as
    the operation_id passed to ops.accept and surfaced in the 202 envelope."""
    async def _slow(*_a, **_k):
        await asyncio.sleep(30)
        return {"persistence": {"persisted": False}}

    captured: dict = {}

    def _accept(**kw):
        captured.update(kw)
        return (kw.get("operation_id"), True)

    with patch("website.api.zettels_routes._AUTO_ACCEPT_AFTER_SECONDS", 0.05), \
         patch("website.api.zettels_routes._run_add_zettel", _slow), \
         patch("website.api.zettels_routes.operations_repo.accept",
               side_effect=_accept), \
         patch("website.api.zettels_routes.operations_repo.start",
               return_value=True), \
         patch("website.api.zettels_routes.operations_repo.finalize",
               return_value=True):
        r = _client().post(
            "/api/zettels/add",
            json={"url": "https://example.com", "client_action_id": "client-id",
                  "surface": "landing", "mode": "sync", "persist": False},
            headers={"Idempotency-Key": "header-key-wins"},
        )
    assert r.status_code == 202
    body = r.json()
    assert body["operation_id"] == "header-key-wins"
    assert captured["operation_id"] == "header-key-wins"
    assert r.headers.get("Location") == "/api/operations/header-key-wins"


def test_get_operation_reads_db_only_returns_202_pending_when_missing():
    """DB-only read: when get_operation returns None (replication gap), the GET
    handler returns 202 + pending body + Retry-After to keep the client polling."""
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value=None):
        r = _client().get("/api/operations/missing-op")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "accepted"
    assert body["operation_id"] == "missing-op"
    assert r.headers.get("Retry-After") == "2"
    assert r.headers.get("Location") == "/api/operations/missing-op"


def test_get_operation_queued_returns_202():
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "queued",
                             "response": {"status": "accepted", "operation_id": "q1"},
                             "error": None}):
        r = _client().get("/api/operations/q1")
    assert r.status_code == 202
    assert r.headers.get("Retry-After") == "2"


def test_get_operation_running_returns_202():
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "running",
                             "response": {"status": "accepted", "operation_id": "r1"},
                             "error": None}):
        r = _client().get("/api/operations/r1")
    assert r.status_code == 202
    assert r.headers.get("Retry-After") == "2"


def test_get_operation_succeeded_returns_200_with_response_body():
    succeeded = {"status": "succeeded", "operation_id": "s1",
                 "summary": {"title": "T"}, "persistence": {"persisted": True}}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "succeeded", "response": succeeded,
                             "error": None}):
        r = _client().get("/api/operations/s1")
    assert r.status_code == 200
    assert r.json() == succeeded


def test_get_operation_failed_returns_200_with_error_dict_envelope():
    """When `response` is empty/None on a failed row, GET builds the envelope
    {status, operation_id, error} from the RFC 9457 dict in `error`."""
    err_dict = {
        "type": "https://zettelkasten.in/problems/kg-write-failed",
        "title": "KG write failed", "status": 502, "code": "kg-write-failed",
    }
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "failed", "response": None,
                             "error": err_dict}):
        r = _client().get("/api/operations/f1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["operation_id"] == "f1"
    assert body["error"] == err_dict


def test_get_operation_cancelled_returns_200():
    err_dict = {"code": "operation_cancelled", "status": 499}
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "cancelled", "response": None,
                             "error": err_dict}):
        r = _client().get("/api/operations/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["error"] == err_dict


def test_get_operation_expired_returns_410():
    with patch("website.api.zettels_routes.operations_repo.get_operation",
               return_value={"status": "expired", "response": None, "error": None}):
        r = _client().get("/api/operations/e1")
    assert r.status_code == 410
    body = r.json()
    assert body["status"] == "expired"
    assert body["operation_id"] == "e1"
    assert body["error"]["code"] == "operation_expired"


def test_delete_operation_calls_ops_cancel_and_cancels_local_task():
    """DELETE /api/zettels/operations/{id} invokes ops.cancel and also
    cancels the local _LIVE_TASKS entry when present (cooperative cancel)."""
    from website.api import zettels_routes as zr

    cancel_calls: list[dict] = []

    def _cancel(**kw):
        cancel_calls.append(kw)
        return True

    async def _sleep_forever():
        await asyncio.sleep(3600)

    async def _go():
        local = asyncio.create_task(_sleep_forever())
        zr._LIVE_TASKS["op-cancel-1"] = local
        try:
            with patch("website.api.zettels_routes.operations_repo.cancel",
                       side_effect=_cancel):
                r = _client().delete("/api/zettels/operations/op-cancel-1")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "cancelled"
            assert body["operation_id"] == "op-cancel-1"
            assert len(cancel_calls) == 1
            assert cancel_calls[0]["operation_id"] == "op-cancel-1"
            # Local task popped + cancelled.
            assert "op-cancel-1" not in zr._LIVE_TASKS
            # Give the loop a tick to register the cancellation.
            try:
                await asyncio.wait_for(local, timeout=0.5)
            except (asyncio.CancelledError, TimeoutError):
                pass
            assert local.cancelled() or local.done()
        finally:
            zr._LIVE_TASKS.pop("op-cancel-1", None)
            if not local.done():
                local.cancel()

    asyncio.run(_go())


def test_delete_operation_returns_noop_when_already_terminal():
    """ops.cancel returns False on already-terminal row -> status=noop."""
    with patch("website.api.zettels_routes.operations_repo.cancel",
               return_value=False):
        r = _client().delete("/api/zettels/operations/already-done")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "noop"
    assert body["operation_id"] == "already-done"
