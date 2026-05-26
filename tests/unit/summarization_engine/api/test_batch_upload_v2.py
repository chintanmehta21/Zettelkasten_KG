"""Batch-upload v2 size cap + bounds tests.

The `/api/v2/batch/upload` endpoint formerly used ``await file.read()`` with
no upper bound — a 1 GB body would OOM the 2 GB droplet (per audit
2026-05-26). This test pins the size guard so it cannot silently regress.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def batch_client(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    monkeypatch.setenv("GEMINI_API_KEYS", "stub-key-for-batch-tests")

    # Stub the BatchProcessor so the test doesn't reach real Gemini / Supabase.
    # We're only testing the size guard at the entry point.
    import website.features.summarization_engine.api.routes as routes_mod
    monkeypatch.setattr(
        routes_mod, "BatchProcessor", lambda **kw: type(
            "StubProcessor", (), {
                "run": AsyncMock(return_value={"status": "ok", "results": []}),
            },
        )()
    )

    from website.app import create_app

    return TestClient(create_app())


def test_batch_upload_v2_rejects_oversize_body(batch_client):
    """A body exceeding the documented 10 MB cap must return 413, not OOM."""
    oversize = b"x" * (11 * 1024 * 1024)  # 11 MB

    response = batch_client.post(
        "/api/v2/batch/upload",
        files={"file": ("big.csv", oversize, "text/csv")},
    )

    assert response.status_code == 413
    body = response.json()
    # RFC 9457 problem+json shape
    assert body.get("status") == 413
    assert "too large" in (body.get("title") or "").lower() or "too large" in (body.get("detail") or "").lower()


def test_batch_upload_v2_accepts_within_cap(batch_client):
    """A small body must pass the size guard and reach the processor."""
    small = b'[{"url":"https://example.com/a"}]'

    response = batch_client.post(
        "/api/v2/batch/upload",
        files={"file": ("small.json", small, "application/json")},
    )

    # The stub processor returns 200; we only need to verify the size guard
    # didn't reject. Any non-413 status from a successful processor invocation
    # is acceptable for this test's purpose.
    assert response.status_code != 413


def test_batch_upload_v2_rejects_burst_with_429(batch_client, monkeypatch):
    """Per-(user, ip) sliding-window limit must 429 a burst from one tenant.
    Default cap is 5/min (batches are heavier than single docs); the 6th
    request inside one minute must be rejected.
    """
    # Reset the shared limiter so prior tests don't leak state.
    import website.features.summarization_engine.api.routes as routes_mod
    routes_mod._BATCH_UPLOAD_LIMITER = type(routes_mod._BATCH_UPLOAD_LIMITER)(
        limit=5, window_seconds=60
    )

    small = b'[{"url":"https://example.com/a"}]'
    statuses: list[int] = []
    for _ in range(6):
        resp = batch_client.post(
            "/api/v2/batch/upload",
            files={"file": ("small.json", small, "application/json")},
        )
        statuses.append(resp.status_code)

    # First 5 must not be 429; 6th must be 429.
    assert all(s != 429 for s in statuses[:5]), f"first 5 should pass; got {statuses}"
    assert statuses[5] == 429, f"6th call must 429; got {statuses[5]}"
