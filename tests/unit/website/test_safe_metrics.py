"""Tests for the safe_metrics defensive emit harness.

Contract: ``safe_inc`` and ``safe_observe`` MUST NEVER re-raise an OSError
family exception from the underlying ``Counter.labels(...).inc()`` /
``Histogram.labels(...).observe()`` call. The swallow:
  * bumps an ``app_metric_emit_failures_total`` meta-counter (best-effort),
  * logs a WARNING (rate-limited to 1 per 60 s per (metric, exc_class)),
  * lets the surrounding request continue.

Test-target rule: patch where the symbol is *used*, not where it's defined
(see browniebroke 2024). We pass a ``MagicMock`` counter directly into
``safe_inc`` rather than touching ``prometheus_client.Counter`` globally;
that keeps each test independent of any other test in the suite.

Live URL repro on 2026-05-25 hit ``FileNotFoundError`` from the multiproc
``mmap_dict``; we parametrise the OSError family to prove the swallow
covers every observed-in-prod variant, not just the one we caught.
"""

from __future__ import annotations

import logging
from unittest import mock

import pytest

from website.features.observability import safe_metrics
from website.features.observability.safe_metrics import (
    safe_inc,
    safe_observe,
)


@pytest.fixture(autouse=True)
def _reset_dedupe():
    """The rate-limit dedupe is module-level state; clear it between tests
    so each test can independently assert its swallow logged."""
    safe_metrics._reset_dedup_state_for_tests()
    yield
    safe_metrics._reset_dedup_state_for_tests()


# ---------------------------------------------------------------------------
# safe_inc: OSError family is swallowed, request continues
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(
            FileNotFoundError(2, "No such file or directory", "/tmp/prom_multiproc/counter_15.db"),
            id="missing-multiproc-dir",  # the 2026-05-25 Naruto failure
        ),
        pytest.param(PermissionError(13, "Permission denied"), id="perm-denied"),
        pytest.param(OSError("generic-oserror"), id="generic-oserror"),
        pytest.param(BrokenPipeError("broken pipe"), id="broken-pipe"),
        pytest.param(ValueError("bad label values"), id="bad-label-values"),
        pytest.param(RuntimeError("torn multiproc state"), id="torn-multiproc"),
    ],
)
def test_safe_inc_swallows_emit_exceptions(exc, caplog):
    counter = mock.MagicMock(_name="gen_ai_client_calls_total")
    counter.labels.return_value.inc.side_effect = exc

    with caplog.at_level(logging.WARNING, logger=safe_metrics.logger.name):
        # Must not re-raise — the request-handler's contract is broken otherwise.
        result = safe_inc(
            counter,
            ("gemini", "youtube", "dense_verify"),
            metric_name="gen_ai_client_calls_total",
        )

    assert result is None
    # The attempt happened (proves we're not silently skipping).
    counter.labels.assert_called_once_with("gemini", "youtube", "dense_verify")
    counter.labels.return_value.inc.assert_called_once_with(1.0)
    # Exactly one WARNING for the swallow, with the original exception attached.
    swallow_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "safe_metrics" in r.name
    ]
    assert len(swallow_records) == 1
    assert swallow_records[0].exc_info is not None
    assert swallow_records[0].exc_info[1] is exc


def test_safe_inc_lets_baseexception_propagate():
    """``KeyboardInterrupt`` / ``SystemExit`` must NOT be swallowed.

    The swallow tuple is intentionally narrow. A blanket ``except Exception``
    would eat genuinely-fatal signals — ruff BLE001 caught this in early review.
    """
    counter = mock.MagicMock(_name="gen_ai_client_calls_total")
    counter.labels.return_value.inc.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        safe_inc(counter, ("gemini", "youtube", "dense_verify"))


def test_safe_inc_noop_on_none_counter():
    """When ``prometheus_client`` is unavailable in a dev shell, the counter
    objects are ``None``; the harness must not raise an ``AttributeError``."""
    # Should not raise.
    safe_inc(None, ("gemini", "youtube", "dense_verify"))


def test_safe_inc_happy_path_calls_inc():
    """Happy path: counter is healthy, ``.inc(1.0)`` is called once, no log."""
    counter = mock.MagicMock(_name="gen_ai_client_calls_total")
    counter.labels.return_value.inc.return_value = None

    safe_inc(counter, ("gemini", "youtube", "dense_verify"))

    counter.labels.assert_called_once_with("gemini", "youtube", "dense_verify")
    counter.labels.return_value.inc.assert_called_once_with(1.0)


def test_safe_inc_respects_custom_amount():
    counter = mock.MagicMock(_name="gen_ai_client_calls_total")
    safe_inc(counter, ("a", "b"), amount=3.5)
    counter.labels.return_value.inc.assert_called_once_with(3.5)


# ---------------------------------------------------------------------------
# safe_observe: same swallow contract for histograms
# ---------------------------------------------------------------------------


def test_safe_observe_swallows_oserror(caplog):
    histogram = mock.MagicMock(_name="my_histogram")
    histogram.labels.return_value.observe.side_effect = FileNotFoundError(
        "no /tmp/prom_multiproc"
    )

    with caplog.at_level(logging.WARNING, logger=safe_metrics.logger.name):
        safe_observe(histogram, ("label",), 0.123)

    histogram.labels.return_value.observe.assert_called_once_with(0.123)
    assert any(
        r.levelno == logging.WARNING and "safe_metrics" in r.name
        for r in caplog.records
    )


def test_safe_observe_noop_on_none():
    safe_observe(None, ("label",), 1.0)  # must not raise


# ---------------------------------------------------------------------------
# Rate-limit dedupe: log once per 60 s per (metric, exc_class)
# ---------------------------------------------------------------------------


def test_repeated_swallows_log_only_once_within_window(caplog):
    """A torn multiproc dir floods every request with the same exception —
    the swallow logger must dedupe so the log bill doesn't blow up.
    """
    counter = mock.MagicMock(_name="gen_ai_client_calls_total")
    counter.labels.return_value.inc.side_effect = FileNotFoundError(
        2, "No such file or directory", "/tmp/prom_multiproc/counter_15.db"
    )

    with caplog.at_level(logging.WARNING, logger=safe_metrics.logger.name):
        for _ in range(5):
            safe_inc(counter, ("gemini", "youtube", "dense_verify"))

    swallow_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "safe_metrics" in r.name
    ]
    # 5 failures, only 1 log line — dedupe is honest.
    assert len(swallow_records) == 1
    # But the underlying inc was still called 5 times.
    assert counter.labels.return_value.inc.call_count == 5


def test_different_exc_classes_log_independently(caplog):
    """Two different exception classes for the same metric should each log
    once — the dedupe key is ``(metric, exc_class)``, not metric alone."""
    counter = mock.MagicMock(_name="gen_ai_client_calls_total")

    with caplog.at_level(logging.WARNING, logger=safe_metrics.logger.name):
        counter.labels.return_value.inc.side_effect = FileNotFoundError("a")
        safe_inc(counter, ("gemini", "youtube", "dense_verify"))
        counter.labels.return_value.inc.side_effect = PermissionError("b")
        safe_inc(counter, ("gemini", "youtube", "dense_verify"))

    swallow_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "safe_metrics" in r.name
    ]
    assert len(swallow_records) == 2


# ---------------------------------------------------------------------------
# Meta-counter best-effort: a torn meta-counter must not break the swallow
# ---------------------------------------------------------------------------


def test_meta_counter_failure_does_not_re_raise(monkeypatch, caplog):
    """If even the meta-counter's ``.inc()`` raises, the harness must still
    swallow + log without re-raising. The "safety net is itself the failure
    point" anti-pattern is exactly what BLE001 caution flags."""
    fake_meta = mock.MagicMock()
    fake_meta.labels.return_value.inc.side_effect = FileNotFoundError(
        "meta counter also broken"
    )
    monkeypatch.setattr(safe_metrics, "_METRIC_EMIT_FAILURES", fake_meta)
    monkeypatch.setattr(safe_metrics, "_meta_init_attempted", True)

    counter = mock.MagicMock(_name="gen_ai_client_calls_total")
    counter.labels.return_value.inc.side_effect = FileNotFoundError("primary broken")

    with caplog.at_level(logging.WARNING, logger=safe_metrics.logger.name):
        safe_inc(counter, ("gemini", "youtube", "dense_verify"))

    # The harness still logged the primary swallow, and the meta-counter
    # failure was itself swallowed silently.
    assert any(
        r.levelno == logging.WARNING and "safe_metrics" in r.name
        for r in caplog.records
    )
