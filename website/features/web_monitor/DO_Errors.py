"""DO_Errors — app-layer memory-pressure & asyncio-leak alerts.

Distinct Slack channel `#do-errors` (env: ``SLACK_WEBHOOK_DO_ERRORS``) —
complements the existing #do-alerts (which is fed by DigitalOcean's native
monitoring policies posting DIRECT to Slack at the host level) and the
#app-errors channel (which carries application 5xx-class incidents).

These signals are emitted by an in-app background sampler that reads:

* ``/proc/pressure/memory`` PSI — the kernel's own "I'm about to evict"
  signal. ``full avg10`` >10% means stall already happening; >0% means
  any task is stalled on memory reclamation.
* ``/sys/fs/cgroup/memory.current`` ÷ ``/sys/fs/cgroup/memory.max`` —
  per-worker cgroup share of the container's memory budget. Detects the
  case where worker A leaks while worker B is idle (host RSS averaged
  below DO's 85% threshold; one worker is 30 s from SIGKILL).
* ``len(asyncio.all_tasks())`` per worker — canary for the BG-task leak
  surfaces (orphaned graph-cache SWR refresh, slack ``_inflight``, etc.).
  Sustained growth above the steady-state baseline is the textbook
  PyLeak / aiomonitor signature.

All thresholds carry hysteresis so the channel doesn't flap during normal
load swings: an alert fires when the sustained breach is confirmed across
N samples and re-arms only after the value drops below the safe band.

Why a separate channel: #do-alerts is reserved for DO's native, out-of-band
host monitoring (fires even when the app process is down). #do-errors is
in-app telemetry — useful complement but a different operational class.
Splitting keeps the dashboards clean.

Compliance with CLAUDE.md "Critical Infra Decision Guardrails":
- This module never touches GUNICORN_WORKERS, --preload, BGE int8 cascade,
  the rerank semaphore, the SSE heartbeat wrapper, or Caddy timeouts. It
  is observation-only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from website.features.web_monitor._slack_client import post_with_retry

logger = logging.getLogger("website.web_monitor.do_errors")

router = APIRouter(prefix="/webhooks/monitor", tags=["web_monitor.do_errors"])

SLACK_ENV_VAR = "SLACK_WEBHOOK_DO_ERRORS"

# Dedup state for maybe_fire_do_error. Same sentinel + bounded-LRU pattern
# as App_Errors / User_Activity.
_DO_ERROR_DEDUP_MAX = 1000
_DO_ERROR_DEDUP_SECONDS = 15 * 60       # default 1 alert / dedup_key / 15 min
_do_error_alerted: "OrderedDict[str, float]" = OrderedDict()


# ---------------------------------------------------------------------------
# Slack message + posting
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SlackMessage:
    title: str
    body: str
    severity: str = "warning"            # info | warning | critical
    fields: dict[str, str] | None = None
    source: str = "do_errors"

    def to_payload(self) -> dict[str, Any]:
        color = {
            "info": "#2E86AB",
            "warning": "#D4A024",
            "critical": "#C83E4D",
        }.get(self.severity, "#D4A024")
        fields = [
            {"type": "mrkdwn", "text": f"*{k}*\n{v}"}
            for k, v in (self.fields or {}).items()
        ]
        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": self.title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": self.body}},
        ]
        if fields:
            blocks.append({"type": "section", "fields": fields[:10]})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"source: `{self.source}` · severity: `{self.severity}`",
                    }
                ],
            }
        )
        return {"attachments": [{"color": color, "blocks": blocks}]}


async def post_to_do_errors(msg: SlackMessage) -> bool:
    """POST a Slack message to #do-errors. Returns True on 2xx. Never raises."""
    url = os.getenv(SLACK_ENV_VAR)
    if not url:
        logger.warning(
            "do_errors: %s unset; alert logged only: %s", SLACK_ENV_VAR, msg.title
        )
        logger.info("ALERT[do_errors] %s — %s", msg.title, msg.body)
        return False
    response = await post_with_retry(url, msg.to_payload())
    if response is None:
        logger.error("do_errors: Slack post gave up after retries: %s", msg.title)
        return False
    if not (200 <= response.status_code < 300):
        logger.error(
            "do_errors: Slack post failed status=%s reason=%s body_len=%s",
            response.status_code,
            response.reason_phrase,
            len(response.text),
        )
        return False
    return True


async def notify_do_error(
    *,
    title: str,
    body: str,
    severity: str = "warning",
    fields: dict[str, str] | None = None,
) -> None:
    """Post an app-layer infra signal to #do-errors. Never raises."""
    msg = SlackMessage(
        title=title, body=body, severity=severity, fields=fields, source="do_errors"
    )
    try:
        await post_to_do_errors(msg)
    except Exception:  # noqa: BLE001 — alerting must never break the sampler
        logger.exception("do_errors: notify_do_error dispatch failed")


def maybe_fire_do_error(
    *,
    dedup_key: str,
    title: str,
    body: str,
    severity: str = "warning",
    fields: dict[str, str] | None = None,
    dedup_seconds: int = _DO_ERROR_DEDUP_SECONDS,
) -> bool:
    """Schedule a #do-errors alert iff ``dedup_key`` hasn't fired recently.

    Same sentinel-based atomic check-and-set as ``maybe_fire_app_error``.
    Never raises. Returns True if scheduled, False otherwise.
    """
    if not dedup_key:
        logger.warning("do_errors: maybe_fire_do_error called without dedup_key")
        return False

    sentinel = object()
    prev = _do_error_alerted.setdefault(dedup_key, sentinel)
    if prev is not sentinel:
        if isinstance(prev, float) and (time.time() - prev) > dedup_seconds:
            _do_error_alerted.pop(dedup_key, None)
            return maybe_fire_do_error(
                dedup_key=dedup_key,
                title=title,
                body=body,
                severity=severity,
                fields=fields,
                dedup_seconds=dedup_seconds,
            )
        return False
    _do_error_alerted[dedup_key] = time.time()
    if len(_do_error_alerted) > _DO_ERROR_DEDUP_MAX:
        _do_error_alerted.popitem(last=False)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "do_errors: maybe_fire_do_error called outside event loop (dedup_key=%s)",
            dedup_key,
        )
        _do_error_alerted.pop(dedup_key, None)
        return False
    loop.create_task(
        notify_do_error(title=title, body=body, severity=severity, fields=fields)
    )
    return True


# ---------------------------------------------------------------------------
# Memory + asyncio-task sampler
# ---------------------------------------------------------------------------

# Linux cgroup v2 paths (containerised app). On the production droplet the
# container runs under cgroup v2; on macOS / Windows dev the reads return
# None and the sampler silently degrades — no false alarms in local dev.
_PSI_MEM = Path("/proc/pressure/memory")
_CGROUP_MEM_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_MEM_MAX = Path("/sys/fs/cgroup/memory.max")

# Thresholds (per OOM/memory subagent recommendation 2026-05-24).
#
# Each metric has WARN/CRITICAL bands and a SAFE re-arm band. The sampler
# fires once when the sustained-breach count reaches ``_BREACH_SAMPLES_*``
# and stays armed (no re-fire) until the value drops below the safe band
# for one sample — that's the hysteresis preventing channel flapping.
_PSI_FULL_AVG10_WARN = 5.0           # %
_PSI_FULL_AVG10_CRITICAL = 10.0
_PSI_FULL_AVG10_SAFE = 1.0
_PSI_BREACH_SAMPLES = 2              # 2 × 15 s = 30 s sustained

_CGROUP_MEM_WARN = 0.80              # ratio
_CGROUP_MEM_CRITICAL = 0.90
_CGROUP_MEM_SAFE = 0.70
_CGROUP_BREACH_SAMPLES = 2           # 30 s sustained

_TASKS_WARN = 150
_TASKS_CRITICAL = 300
_TASKS_SAFE = 80
_TASKS_BREACH_SAMPLES = 4            # 4 × 15 s = 60 s sustained

_SAMPLE_INTERVAL_SECONDS = 15.0


def _read_psi_full_avg10() -> float | None:
    """Return ``full avg10`` percentage from /proc/pressure/memory, or None."""
    try:
        text = _PSI_MEM.read_text()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    # File format:
    #   some avg10=0.00 avg60=0.00 avg300=0.00 total=...
    #   full avg10=0.00 avg60=0.00 avg300=0.00 total=...
    for line in text.splitlines():
        if line.startswith("full "):
            for tok in line.split():
                if tok.startswith("avg10="):
                    try:
                        return float(tok.split("=", 1)[1])
                    except (TypeError, ValueError):
                        return None
    return None


def _read_cgroup_mem_ratio() -> tuple[float | None, int | None, int | None]:
    """Return (ratio, current_bytes, max_bytes) for cgroup v2, or (None, ...)."""
    try:
        current_text = _CGROUP_MEM_CURRENT.read_text().strip()
        max_text = _CGROUP_MEM_MAX.read_text().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None, None, None
    try:
        current = int(current_text)
    except (TypeError, ValueError):
        return None, None, None
    if max_text == "max":
        # No effective limit; ratio is meaningless.
        return None, current, None
    try:
        max_bytes = int(max_text)
    except (TypeError, ValueError):
        return None, current, None
    if max_bytes <= 0:
        return None, current, max_bytes
    return current / max_bytes, current, max_bytes


def _read_asyncio_task_count() -> int:
    try:
        return len(asyncio.all_tasks())
    except RuntimeError:
        return 0


@dataclass
class _SamplerState:
    """Hysteresis state per metric — single instance per sampler."""
    psi_breach: int = 0
    psi_armed_severity: str | None = None    # None | "warning" | "critical"
    mem_breach: int = 0
    mem_armed_severity: str | None = None
    tasks_breach: int = 0
    tasks_armed_severity: str | None = None


class MemorySampler:
    """Background sampler. One instance per gunicorn worker.

    Reads /proc + asyncio state every ``interval`` seconds, applies
    sustained-N-samples + hysteresis logic, dispatches alerts to
    ``#do-errors`` via the ``maybe_fire_do_error`` channel.

    Constructed lazily by ``start()``; ``stop()`` flips a shutdown event
    that the loop polls between samples (cooperative cancellation).
    """

    def __init__(self, *, interval_seconds: float = _SAMPLE_INTERVAL_SECONDS):
        self._interval = interval_seconds
        self._stop = asyncio.Event()
        self.state = _SamplerState()
        self._task: asyncio.Task | None = None

    def start(self) -> "asyncio.Task | None":
        if self._task is not None and not self._task.done():
            return self._task
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("do_errors: MemorySampler.start with no running loop")
            return None
        self._task = loop.create_task(self._run_forever(), name="do_errors_memory_sampler")
        return self._task

    def request_stop(self) -> None:
        self._stop.set()

    async def _run_forever(self) -> None:
        # First sample immediately so a chronically over-budget worker
        # gets a fast signal after boot; subsequent samples are paced.
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception:  # noqa: BLE001 — sampler must never die
                logger.exception("do_errors: sampler iteration raised")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                # If we got here without TimeoutError, stop was requested.
                return
            except asyncio.TimeoutError:
                continue

    def sample_once(self) -> dict[str, Any]:
        """One sample iteration; returns a snapshot for tests + healthz."""
        psi = _read_psi_full_avg10()
        mem_ratio, mem_current, mem_max = _read_cgroup_mem_ratio()
        tasks = _read_asyncio_task_count()

        self._evaluate_psi(psi)
        self._evaluate_mem(mem_ratio, mem_current, mem_max)
        self._evaluate_tasks(tasks)

        return {
            "psi_full_avg10": psi,
            "mem_ratio": mem_ratio,
            "mem_current_bytes": mem_current,
            "mem_max_bytes": mem_max,
            "asyncio_tasks": tasks,
            "state": {
                "psi_breach": self.state.psi_breach,
                "psi_armed_severity": self.state.psi_armed_severity,
                "mem_breach": self.state.mem_breach,
                "mem_armed_severity": self.state.mem_armed_severity,
                "tasks_breach": self.state.tasks_breach,
                "tasks_armed_severity": self.state.tasks_armed_severity,
            },
        }

    def _evaluate_psi(self, psi: float | None) -> None:
        if psi is None:
            return
        if psi >= _PSI_FULL_AVG10_CRITICAL:
            self.state.psi_breach += 1
            if (
                self.state.psi_breach >= _PSI_BREACH_SAMPLES
                and self.state.psi_armed_severity != "critical"
            ):
                self.state.psi_armed_severity = "critical"
                maybe_fire_do_error(
                    dedup_key="memory_psi_critical",
                    title=":fire: PSI memory pressure (full avg10 ≥ 10%)",
                    body=(
                        f"Kernel is stalling on memory reclamation — "
                        f"`full avg10 = {psi:.2f}%`. Imminent OOM risk."
                    ),
                    severity="critical",
                    fields={
                        "psi_full_avg10_pct": f"{psi:.2f}",
                        "threshold_pct": str(_PSI_FULL_AVG10_CRITICAL),
                        "sustained_samples": str(self.state.psi_breach),
                    },
                )
        elif psi <= _PSI_FULL_AVG10_SAFE:
            # Safe band: reset breach counter and re-arm if previously fired.
            self.state.psi_breach = 0
            self.state.psi_armed_severity = None
        else:
            # In-between band — don't fire but don't re-arm either.
            pass

    def _evaluate_mem(
        self, ratio: float | None, current_bytes: int | None, max_bytes: int | None
    ) -> None:
        if ratio is None:
            return
        if ratio >= _CGROUP_MEM_CRITICAL:
            self.state.mem_breach += 1
            if (
                self.state.mem_breach >= _CGROUP_BREACH_SAMPLES
                and self.state.mem_armed_severity != "critical"
            ):
                self.state.mem_armed_severity = "critical"
                maybe_fire_do_error(
                    dedup_key="memory_cgroup_critical",
                    title=":battery: Cgroup memory >90% (per-worker share)",
                    body=(
                        f"This worker is using `{ratio * 100:.1f}%` of its cgroup "
                        f"share — single-worker blow-up before host avg trips "
                        f"the DO 85% alert. Likely OOM-kill within 30 s."
                    ),
                    severity="critical",
                    fields={
                        "ratio_pct": f"{ratio * 100:.1f}",
                        "current_bytes": str(current_bytes or "?"),
                        "max_bytes": str(max_bytes or "?"),
                        "sustained_samples": str(self.state.mem_breach),
                        "pid": str(os.getpid()),
                    },
                )
        elif ratio <= _CGROUP_MEM_SAFE:
            self.state.mem_breach = 0
            self.state.mem_armed_severity = None

    def _evaluate_tasks(self, tasks: int) -> None:
        if tasks > _TASKS_CRITICAL:
            self.state.tasks_breach += 1
            if (
                self.state.tasks_breach >= _TASKS_BREACH_SAMPLES
                and self.state.tasks_armed_severity != "warning"
            ):
                self.state.tasks_armed_severity = "warning"
                maybe_fire_do_error(
                    dedup_key="asyncio_task_leak",
                    title=":sparkle: Asyncio task count > 300 (possible leak)",
                    body=(
                        f"`len(asyncio.all_tasks())` = {tasks} sustained "
                        f"≥ 60 s. Likely BG-task leak surface (orphaned "
                        f"graph-cache SWR refresh, slack _inflight, "
                        f"_USER_ACTIVITY_TASKS)."
                    ),
                    severity="warning",
                    fields={
                        "task_count": str(tasks),
                        "threshold": str(_TASKS_CRITICAL),
                        "sustained_samples": str(self.state.tasks_breach),
                        "pid": str(os.getpid()),
                    },
                )
        elif tasks <= _TASKS_SAFE:
            self.state.tasks_breach = 0
            self.state.tasks_armed_severity = None


# Module-level sampler — initialised by main._lifespan; ``None`` outside.
_sampler: MemorySampler | None = None


def start_memory_sampler(*, interval_seconds: float = _SAMPLE_INTERVAL_SECONDS) -> "MemorySampler | None":
    """Boot a single MemorySampler instance. Idempotent within a worker.

    Returns the sampler so the caller (main._lifespan) can ``request_stop``
    + await its task during shutdown.
    """
    global _sampler
    if _sampler is None:
        _sampler = MemorySampler(interval_seconds=interval_seconds)
    _sampler.start()
    return _sampler


def stop_memory_sampler() -> "MemorySampler | None":
    """Request the sampler to stop; returns the instance for the caller to await."""
    if _sampler is not None:
        _sampler.request_stop()
    return _sampler


def get_sampler() -> "MemorySampler | None":
    """Diagnostic accessor — used by ``do_errors_healthz`` + tests."""
    return _sampler


# ---------------------------------------------------------------------------
# Healthz
# ---------------------------------------------------------------------------


@router.get("/do-errors/healthz")
async def do_errors_healthz() -> dict[str, Any]:
    sampler = get_sampler()
    return {
        "ok": True,
        "channel": "do_errors",
        "webhook_configured": bool(os.getenv(SLACK_ENV_VAR)),
        "sampler_running": (
            sampler is not None
            and sampler._task is not None
            and not sampler._task.done()
        ),
    }


__all__ = [
    "router",
    "SlackMessage",
    "post_to_do_errors",
    "notify_do_error",
    "maybe_fire_do_error",
    "MemorySampler",
    "start_memory_sampler",
    "stop_memory_sampler",
    "get_sampler",
]
