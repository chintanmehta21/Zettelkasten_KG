"""Defensive ``prometheus_client`` emit helpers.

Why this module exists
======================
The OpenTelemetry spec mandates that telemetry MUST NOT throw unhandled
exceptions at runtime (`opentelemetry.io/docs/specs/otel/error-handling`).
``prometheus_client`` deliberately does not follow that rule — its
``MmapedDict`` happily raises ``OSError`` / ``FileNotFoundError`` through
``Counter.labels(...).inc()`` if the multiprocess directory is torn or
missing (issues #127, #275, #425, #599, #939 against
``prometheus/client_python``).

On 2026-05-25 the Naruto live URL repro hit exactly that path:
``FileNotFoundError: '/tmp/prom_multiproc/counter_15.db'`` raised inside
``LLM_CALLS_TOTAL.labels(...).inc()`` propagated all the way back through
the FastAPI request handler, the operations row landed with ``error=NULL``,
and the user saw a literal ``"Summary failed."`` toast with no diagnostic.

This module is a *thin* safety harness applied at the emit call site — the
pattern used by ``prometheus-fastapi-instrumentator`` and recommended in
Grafana Labs' meta-monitoring playbook:

  * ``safe_inc`` / ``safe_observe`` wrap ``.inc()`` / ``.observe()`` in a
    narrow ``try / except``. ``BaseException`` subclasses
    (``KeyboardInterrupt``, ``SystemExit``) intentionally propagate.
  * A best-effort meta-counter, ``app_metric_emit_failures_total``,
    increments on each swallow so a metric-emit outage stays visible.
    Its own construction failure is swallowed too — the harness must not
    *itself* become a failure point.
  * Logging is rate-limited to one record per 60 s per
    ``(metric_name, exc_class)`` signature. A torn multiproc dir would
    otherwise fault on every request and the warning would flood stdout.

The harness is the *safety net*, not the fix. The actual root cause of
the missing directory is addressed separately in the Dockerfile +
``website.main`` lifespan recreate (PR #89 commit B).
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

logger = logging.getLogger("website.features.observability.safe_metrics")

# Narrow on purpose. BaseException subclasses keep propagating. The three
# concrete classes we *do* swallow are the documented escape paths from
# ``prometheus_client`` under load + the broader OSError family that covers
# any future filesystem hiccup on the multiproc directory.
_SWALLOW: tuple[type[BaseException], ...] = (OSError, ValueError, RuntimeError)

_LOG_DEDUPE_SECONDS = 60.0
_last_logged: dict[tuple[str, str], float] = {}
_last_logged_lock = Lock()

# Meta-counter: lazy single-shot construction, defensive — if even
# Counter() construction blows up (prometheus_client missing, multiproc dir
# torn at import time, …) we silently degrade to log-only.
_METRIC_EMIT_FAILURES: Any = None
_meta_init_attempted = False


def _ensure_meta_counter() -> Any:
    global _METRIC_EMIT_FAILURES, _meta_init_attempted
    if _meta_init_attempted:
        return _METRIC_EMIT_FAILURES
    _meta_init_attempted = True
    try:
        from prometheus_client import Counter

        _METRIC_EMIT_FAILURES = Counter(
            "app_metric_emit_failures_total",
            "Times a Counter/Histogram emit was swallowed by safe_metrics.",
            ["metric", "exc_class"],
        )
    except Exception:  # noqa: BLE001 — meta-counter is strictly best-effort
        _METRIC_EMIT_FAILURES = None
    return _METRIC_EMIT_FAILURES


def _should_log(metric_name: str, exc_class: str) -> bool:
    now = time.monotonic()
    key = (metric_name, exc_class)
    with _last_logged_lock:
        last = _last_logged.get(key, 0.0)
        if now - last < _LOG_DEDUPE_SECONDS:
            return False
        _last_logged[key] = now
        return True


def _on_swallow(metric_name: str, exc: BaseException) -> None:
    exc_class = type(exc).__name__
    meta = _ensure_meta_counter()
    if meta is not None:
        try:
            meta.labels(metric_name, exc_class).inc()
        except Exception:  # noqa: BLE001 — meta-counter must NEVER fail loudly
            pass
    if _should_log(metric_name, exc_class):
        logger.warning(
            "safe_metrics: emit failed (metric=%s exc=%s); request continues",
            metric_name,
            exc_class,
            exc_info=True,
        )


def _counter_name(counter: Any, fallback: str | None) -> str:
    if fallback:
        return fallback
    name = getattr(counter, "_name", None)
    return name or "unknown"


def safe_inc(
    counter: Any,
    label_values: tuple[Any, ...],
    *,
    amount: float = 1.0,
    metric_name: str | None = None,
) -> None:
    """Increment a ``Counter`` (with labels) without ever raising.

    ``counter`` may be None (e.g. when ``prometheus_client`` is unavailable
    in a dev shell) — a no-op in that case. Any in-family exception from
    ``.labels(...).inc()`` is swallowed, the meta-counter bumped, and a
    rate-limited WARNING emitted with the original stack.
    """
    if counter is None:
        return
    try:
        counter.labels(*label_values).inc(amount)
    except _SWALLOW as exc:
        _on_swallow(_counter_name(counter, metric_name), exc)


def safe_observe(
    histogram: Any,
    label_values: tuple[Any, ...],
    value: float,
    *,
    metric_name: str | None = None,
) -> None:
    """Observe a ``Histogram`` / ``Summary`` (with labels) without ever raising.

    Same contract as :func:`safe_inc` for the ``.observe(value)`` operation.
    """
    if histogram is None:
        return
    try:
        histogram.labels(*label_values).observe(value)
    except _SWALLOW as exc:
        _on_swallow(_counter_name(histogram, metric_name), exc)


def _reset_dedup_state_for_tests() -> None:
    """Test-only helper: drop the rate-limit dedupe window so each test can
    independently assert that its own swallow logged. Never called from
    production code."""
    with _last_logged_lock:
        _last_logged.clear()
