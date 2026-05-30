import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.api.auth import get_current_user


class _FakeSnap:
    def __init__(self, effective_available, remaining_plan, remaining_wallet):
        self.feature = "zettel"
        self.effective_available = effective_available
        self.remaining_plan = remaining_plan
        self.remaining_wallet = remaining_wallet


class _FakeGates:
    def __init__(self, snap):
        self._snap = snap
        self.consume_called = False

    async def quota_snapshot(self, *, profile_id, feature, plan=None):
        return self._snap

    async def reserve_and_consume(self, *args, **kwargs):  # must never be called
        self.consume_called = True
        raise AssertionError("snapshot endpoint must not consume")


def _client(monkeypatch, snap, sub="11111111-1111-1111-1111-111111111111"):
    import website.api.quota_routes as qr
    gates = _FakeGates(snap)
    monkeypatch.setattr(qr, "get_functional_gates", lambda: gates)
    app = FastAPI()
    app.include_router(qr.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": sub}
    return TestClient(app), gates


def test_returns_effective_available(monkeypatch):
    client, gates = _client(monkeypatch, _FakeSnap(7, 5, 2))
    r = client.get("/api/quota/snapshot?feature=zettel")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "feature": "zettel", "effective_available": 7,
        "remaining_plan": 5, "remaining_wallet": 2,
    }
    assert gates.consume_called is False
    assert r.headers["cache-control"] == "private, no-store"


def test_invalid_feature_422(monkeypatch):
    client, _ = _client(monkeypatch, _FakeSnap(7, 5, 2))
    r = client.get("/api/quota/snapshot?feature=bogus")
    assert r.status_code == 422


def test_non_uuid_sub_returns_null(monkeypatch):
    client, _ = _client(monkeypatch, _FakeSnap(7, 5, 2), sub="zoro")
    r = client.get("/api/quota/snapshot?feature=zettel")
    assert r.status_code == 200
    assert r.json()["effective_available"] is None


def test_auth_required_401(monkeypatch):
    import website.api.quota_routes as qr
    monkeypatch.setattr(qr, "get_functional_gates", lambda: _FakeGates(_FakeSnap(1, 1, 0)))
    app = FastAPI()
    app.include_router(qr.router)
    r = TestClient(app).get("/api/quota/snapshot?feature=zettel")
    assert r.status_code == 401


def test_payload_has_no_extra_fields(monkeypatch):
    client, _ = _client(monkeypatch, _FakeSnap(0, 0, 0))
    body = client.get("/api/quota/snapshot?feature=zettel").json()
    assert set(body.keys()) == {"feature", "effective_available", "remaining_plan", "remaining_wallet"}
