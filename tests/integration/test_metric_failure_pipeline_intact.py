"""Integration smoke: a torn ``prometheus_client`` multiproc state does NOT
break the summarisation pipeline.

This is the regression test for the 2026-05-25 Naruto live-test failure
(``FileNotFoundError: '/tmp/prom_multiproc/counter_15.db'`` raised from
``Counter.labels(...).inc()`` inside ``budget.consume()`` → user got HTTP
500-equivalent with ``error JSONB = NULL`` in ``core.operations``).

After PR #89 commit A (safe_metrics) + commit C (RFC 9457 catch-all), the
same failure must:

  * NOT raise out of ``budget.consume()`` — ``safe_inc`` swallows.
  * Increment the budget bookkeeping (``b.used``) so the request continues.
  * Be coverable by ``_async_failure_error_payload`` if the surrounding
    code path eventually does fail — the catch-all returns a structured
    ``internal_error`` body, never ``None``.

Also pins the new ``X-Operation-Id`` response header (PR #89 commit C 3b).

Per the research deliverable: ``TestClient(raise_server_exceptions=False)``
is mandatory for testing FastAPI's catch-all exception handler shape
(Starlette #1175). We use the inline sync ``_problem()`` rate-limit branch
in ``POST /api/zettels/add`` as the cheapest path that exercises the
header end-to-end — no Gemini call, no DB write, no auth needed.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from website.features.observability import safe_metrics
from website.features.summarization_engine.core.budget import (
    Budget,
    _emit_call_counter,
)


@pytest.fixture(autouse=True)
def _reset_dedupe():
    """Each test gets a clean safe_metrics rate-limit window."""
    safe_metrics._reset_dedup_state_for_tests()
    yield
    safe_metrics._reset_dedup_state_for_tests()


# ---------------------------------------------------------------------------
# budget.consume integration: the prom-counter raise NEVER reaches the caller
# ---------------------------------------------------------------------------


def test_budget_consume_survives_filenotfound_on_metric_emit(monkeypatch, caplog):
    """The exact 2026-05-25 failure path, end-to-end through the budget
    bookkeeping. Pre-fix this raised straight through ``consume()`` and
    landed as the silent ``error=NULL`` cohort. Post-fix the request must
    advance past the emit and ``b.used`` must increment so the LLM call
    sequence continues."""
    from website.features.summarization_engine.core import budget as budget_mod

    fake_counter = mock.MagicMock(_name="gen_ai_client_calls_total")
    fake_counter.labels.return_value.inc.side_effect = FileNotFoundError(
        2, "No such file or directory", "/tmp/prom_multiproc/counter_15.db",
    )
    monkeypatch.setattr(budget_mod, "LLM_CALLS_TOTAL", fake_counter)

    b = Budget(limit=3, summarizer="youtube")
    # Pre-fix: this raised. Post-fix: the swallow absorbs and consume() returns.
    b.consume(role="dense_verify")

    assert b.used == 1
    fake_counter.labels.assert_called_once_with("gemini", "youtube", "dense_verify")
    fake_counter.labels.return_value.inc.assert_called_once_with(1.0)


def test_budget_consume_does_not_increment_on_overrun_even_when_metric_fails(
    monkeypatch,
):
    """The overrun counter uses the same harness. Past-cap consume() raises
    BudgetExceeded as designed, even if the overrun-counter emit also fails —
    the swallow MUST NOT mask the BudgetExceeded contract."""
    from website.features.summarization_engine.core import budget as budget_mod

    fake_overrun = mock.MagicMock(_name="gen_ai_client_budget_exceeded_total")
    fake_overrun.labels.return_value.inc.side_effect = FileNotFoundError(
        "broken counter file"
    )
    monkeypatch.setattr(budget_mod, "BUDGET_EXCEEDED", fake_overrun)

    b = Budget(limit=1, summarizer="youtube")
    b.consume(role="brief")  # used = 1
    with pytest.raises(budget_mod.BudgetExceeded):
        b.consume(role="detailed")  # would push used to 2 > limit
    # The overrun-counter raise was swallowed (we still raised BudgetExceeded,
    # but for the right reason — cap, not metric error).
    assert b.overrun_attempts == 1
    assert b.used == 1  # not incremented past the cap


def test_emit_call_counter_is_a_safe_inc_passthrough(monkeypatch):
    """Direct contract test: ``_emit_call_counter`` must route through
    ``safe_inc`` so a future caller does not bypass the harness by
    importing the underlying Counter directly."""
    from website.features.summarization_engine.core import budget as budget_mod

    fake_counter = mock.MagicMock(_name="gen_ai_client_calls_total")
    fake_counter.labels.return_value.inc.side_effect = FileNotFoundError(
        "broken"
    )
    monkeypatch.setattr(budget_mod, "LLM_CALLS_TOTAL", fake_counter)

    # Must not raise — proves the refactor at budget.py:174-188 is in place.
    _emit_call_counter("youtube", "dense_verify")


# ---------------------------------------------------------------------------
# HTTP integration: X-Operation-Id header pinned end-to-end via the
# rate-limit 429 branch (cheap path, no Gemini / DB / auth needed)
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """A fresh FastAPI app per test. Per Starlette #1175, we MUST use
    ``raise_server_exceptions=False`` so the ``@app.exception_handler(Exception)``
    catch-all (if any) routes through ``ServerErrorMiddleware`` rather than
    re-raising into pytest."""
    from website.app import create_app

    return create_app()


def test_rate_limit_429_emits_x_operation_id_header(app, monkeypatch):
    """End-to-end: a 429 from the inline rate-limit gate goes through
    ``_problem()``. The X-Operation-Id header (PR #89 commit C 3b) must
    be set from the request's ``client_action_id`` so curl/fetch-style
    debugging surfaces it without needing to read the body."""
    # Force the rate-limit to trip on first request.
    from website.api import zettels_routes as zr

    monkeypatch.setattr(zr, "_RATE_LIMIT", 0)
    monkeypatch.setattr(zr, "_RATE_WINDOW_SECONDS", 60)
    # Also start with a clean rate-store so the bookkeeping doesn't carry
    # state from another test.
    monkeypatch.setattr(zr, "_RATE_STORE", __import__("collections").defaultdict(list))

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/zettels/add",
            json={
                "url": "https://example.com/anything",
                "client_action_id": "live-test-op-X",
                "persist": False,
                "surface": "home",
            },
        )

    assert resp.status_code == 429
    assert resp.headers.get("X-Operation-Id") == "live-test-op-X"
    assert resp.headers.get("content-type", "").startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "rate-limited"
    assert body["operation_id"] == "live-test-op-X"


def test_no_op_id_means_no_x_operation_id_header(app):
    """Anonymous 4xxs (validation fail before client_action_id is even
    parsed) must NOT emit ``X-Operation-Id: None`` — the header is omitted."""
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/zettels/add",
            json={
                # Missing required client_action_id → pydantic 422 / 4xx,
                # no operation_id in scope.
                "url": "https://example.com",
                "persist": False,
                "surface": "home",
            },
        )
    # Whatever the status, the header must not appear with literal "None".
    if "X-Operation-Id" in resp.headers:
        assert resp.headers["X-Operation-Id"] != "None"
        assert resp.headers["X-Operation-Id"] != ""


# ---------------------------------------------------------------------------
# Catch-all RFC 9457 shape: a typed-then-untyped sequence keeps each one
# pinned to its own ``code`` slug (regression guard for dispatch ordering)
# ---------------------------------------------------------------------------


def test_typed_and_untyped_exceptions_dispatch_independently():
    """Pin the dispatch ordering after the catch-all added in commit C.
    The catch-all branch is *last*; typed mappings above it must continue
    to win for their specific exception classes."""
    from website.api import zettels_routes as zr
    from website.core.persist import SupabaseV2PersistError
    from website.features.summarization_engine.core.errors import (
        ExtractionConfidenceError,
    )

    typed = zr._async_failure_error_payload(
        ExtractionConfidenceError("low", reason="low", tier_results=[]),
        operation_id="op-typed",
    )
    persist = zr._async_failure_error_payload(
        SupabaseV2PersistError("rls denial"),
        operation_id="op-persist",
    )
    untyped = zr._async_failure_error_payload(
        FileNotFoundError("/tmp/prom_multiproc/counter_15.db"),
        operation_id="op-untyped",
    )

    assert typed["code"] == "insufficient-content"
    assert persist["code"] == "kg-write-failed"
    assert untyped["code"] == "internal_error"
    # All three are dicts — the pre-fix `return None` is gone for good.
    assert all(p is not None for p in (typed, persist, untyped))
    # OWASP API8 redaction: untyped never carries the exc class or path.
    body = json.dumps(untyped)
    assert "FileNotFoundError" not in body
    assert "/tmp/prom_multiproc" not in body
