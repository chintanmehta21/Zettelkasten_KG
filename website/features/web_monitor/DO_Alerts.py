"""DO_Alerts — alert fan-out for DigitalOcean droplet monitoring.

One file, one Slack channel: `#do-alerts`. Self-contained (its own Slack
posting helper, its own router) so it can be reasoned about without looking
at siblings.

Channel wiring:
    The 3 DO alert policies (CPU > 80 %, Memory > 85 %, Disk > 80 %) post
    **direct** to Slack via DO's native `notifications.slack` integration —
    that path does not go through our app, so alerts still fire if
    zettelkasten.in itself is the thing that's down. The webhook endpoint
    below exists as a backup / manual path in case we ever want to route
    DO → our app → Slack (e.g. for enrichment, cross-channel routing, or
    if DO's Slack integration breaks).

Mount (already done in website/app.py):
    from website.features.web_monitor.DO_Alerts import router as do_alerts_router
    app.include_router(do_alerts_router)

Env vars:
    SLACK_WEBHOOK_DO_ALERT       # Slack incoming webhook URL for #do-alerts
    DO_ALERT_WEBHOOK_SECRET      # shared secret DO must include as
                                 # `alert_uuid` in payload; blank disables
                                 # auth (fine for low-profile URLs)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError

from website.features.web_monitor._slack_client import post_with_retry

logger = logging.getLogger("website.web_monitor.do_alerts")

router = APIRouter(prefix="/webhooks/monitor", tags=["web_monitor.do_alerts"])

SLACK_ENV_VAR = "SLACK_WEBHOOK_DO_ALERT"

# Dedup state for maybe_fire_do_alert. Same sentinel + bounded-LRU pattern
# as App_Errors / User_Activity. Used by the app-layer memory sampler below
# so PSI / cgroup / asyncio-task breaches don't flood the channel during a
# sustained incident.
_DO_ALERT_DEDUP_MAX = 1000
_DO_ALERT_DEDUP_SECONDS = 15 * 60       # default 1 alert / dedup_key / 15 min
_do_alert_alerted: "OrderedDict[str, float]" = OrderedDict()


# ---------------------------------------------------------------------------
# Slack posting
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SlackMessage:
    title: str
    body: str
    severity: str = "warning"          # info | warning | critical
    fields: dict[str, str] | None = None
    source: str = "digitalocean"

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


async def post_to_do_alerts(msg: SlackMessage) -> bool:
    """POST a Slack message to #do-alerts. Returns True on 2xx.

    WM-05: delegates to _slack_client.post_with_retry for backoff handling.
    """
    url = os.getenv(SLACK_ENV_VAR)
    if not url:
        logger.warning(
            "do_alerts: %s unset; alert logged only: %s", SLACK_ENV_VAR, msg.title
        )
        logger.info("ALERT[do_alerts] %s — %s", msg.title, msg.body)
        return False
    response = await post_with_retry(url, msg.to_payload())
    if response is None:
        logger.error("do_alerts: Slack post gave up after retries: %s", msg.title)
        return False
    if not (200 <= response.status_code < 300):
        # B-4: drop response.text — Slack body may echo PII / log-injection.
        logger.error(
            "do_alerts: Slack post failed status=%s reason=%s body_len=%s",
            response.status_code,
            response.reason_phrase,
            len(response.text),
        )
        return False
    return True


# ---------------------------------------------------------------------------
# DigitalOcean monitoring webhook schema
# ---------------------------------------------------------------------------
# Representative DO payload (fields are all optional; schema is unversioned):
# {
#   "alert_id": "...",
#   "alert_uuid": "<secret we verify against>",
#   "alert_description": "CPU Utilization > 80%",
#   "trigger_metric": "cpu",
#   "trigger_status": "alert" | "resolved",
#   "droplet_id": 565709868,
#   "droplet_name": "Zettelkasten-Intel2GB",
#   "value": 91.2,
#   "region": "blr1",
#   "timestamp": "2026-04-21T14:05:00Z"
# }


class DOAlertPayload(BaseModel):
    alert_uuid: str | None = Field(default=None)
    alert_description: str | None = Field(default=None)
    trigger_metric: str | None = Field(default=None)
    trigger_status: str | None = Field(default=None)
    droplet_name: str | None = Field(default=None)
    droplet_id: int | None = Field(default=None)
    region: str | None = Field(default=None)
    value: float | None = Field(default=None)
    timestamp: str | None = Field(default=None)

    model_config = {"extra": "allow"}


def _severity(metric: str | None, status_: str | None, value: float | None) -> str:
    if status_ == "resolved":
        return "info"
    if value is None or metric is None:
        return "warning"
    if metric in {"cpu", "memory", "mem", "disk"} and value >= 95:
        return "critical"
    return "warning"


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


@router.post("/digitalocean", status_code=status.HTTP_202_ACCEPTED)
async def digitalocean_alert(request: Request) -> dict[str, str]:
    """DO monitoring webhook → Slack #do-alerts (backup path)."""
    raw = await request.body()
    try:
        data = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid json: {exc}") from exc

    # WM-08: cap validation failures at 400 so fuzz / malformed JSON never
    # escalates into a 5xx (non-object roots like list/string/number arrive
    # as dicts after json.loads but fail model validation).
    try:
        payload = DOAlertPayload.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc.errors()[:3]}") from exc

    expected = os.getenv("DO_ALERT_WEBHOOK_SECRET")
    # WM-03 surgical: constant-time compare blocks timing side-channels that
    # leak shared-secret prefix length to an attacker iterating UUIDs.
    if expected and not hmac.compare_digest(
        (payload.alert_uuid or "").encode("utf-8"),
        expected.encode("utf-8"),
    ):
        logger.warning("do_alerts: webhook rejected — alert_uuid mismatch")
        raise HTTPException(status_code=401, detail="bad alert_uuid")

    metric = (payload.trigger_metric or "unknown").lower()
    status_ = (payload.trigger_status or "alert").lower()
    emoji = {
        "cpu": ":fire:",
        "memory": ":battery:",
        "mem": ":battery:",
        "disk": ":floppy_disk:",
    }.get(metric, ":rotating_light:")
    if status_ == "resolved":
        emoji = ":white_check_mark:"

    msg = SlackMessage(
        title=f"{emoji} DO alert — {payload.alert_description or metric} [{status_}]",
        body=(
            f"*Droplet:* `{payload.droplet_name or payload.droplet_id or 'unknown'}` "
            f"({payload.region or 'n/a'})\n"
            f"*Metric:* `{metric}`  *Value:* "
            f"`{payload.value if payload.value is not None else 'n/a'}`"
        ),
        severity=_severity(metric, status_, payload.value),
        fields={
            "timestamp": payload.timestamp or "—",
            "droplet_id": str(payload.droplet_id or "—"),
        },
        source="digitalocean",
    )
    delivered = await post_to_do_alerts(msg)
    return {"status": "delivered" if delivered else "logged"}


# ---------------------------------------------------------------------------
# App-layer memory + asyncio sampler — fires to the SAME #do-alerts channel
# as the DO native infrastructure policies. PSI / cgroup mem / task-count
# are per-worker signals that complement DO's host-level CPU/Mem/Disk
# thresholds (fires earlier and per-worker, before the host avg trips).
# ---------------------------------------------------------------------------


async def notify_do_alert(
    *,
    title: str,
    body: str,
    severity: str = "warning",
    fields: dict[str, str] | None = None,
) -> None:
    """Post an app-layer infra signal to #do-alerts. Never raises.

    Distinct call surface from ``post_to_do_alerts``: the latter takes a
    pre-built ``SlackMessage`` (used by the inbound DO webhook below); this
    helper builds the message from primitive fields the sampler emits.
    """
    msg = SlackMessage(
        title=title, body=body, severity=severity, fields=fields, source="digitalocean"
    )
    try:
        await post_to_do_alerts(msg)
    except Exception:  # noqa: BLE001 — alerting must never break the sampler
        logger.exception("do_alerts: notify_do_alert dispatch failed")


def maybe_fire_do_alert(
    *,
    dedup_key: str,
    title: str,
    body: str,
    severity: str = "warning",
    fields: dict[str, str] | None = None,
    dedup_seconds: int = _DO_ALERT_DEDUP_SECONDS,
) -> bool:
    """Schedule a #do-alerts alert iff ``dedup_key`` hasn't fired recently.

    Same sentinel-based atomic check-and-set as ``maybe_fire_app_error``.
    Never raises. Returns True if scheduled, False otherwise.
    """
    if not dedup_key:
        logger.warning("do_alerts: maybe_fire_do_alert called without dedup_key")
        return False

    sentinel = object()
    prev = _do_alert_alerted.setdefault(dedup_key, sentinel)
    if prev is not sentinel:
        # Same inline-reset pattern as App_Errors.maybe_fire_app_error —
        # re-arm without recursing when the dedup window has passed.
        if isinstance(prev, float) and (time.time() - prev) > dedup_seconds:
            _do_alert_alerted[dedup_key] = time.time()
            _do_alert_alerted.move_to_end(dedup_key)
        else:
            return False
    else:
        _do_alert_alerted[dedup_key] = time.time()
    if len(_do_alert_alerted) > _DO_ALERT_DEDUP_MAX:
        _do_alert_alerted.popitem(last=False)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "do_alerts: maybe_fire_do_alert called outside event loop (dedup_key=%s)",
            dedup_key,
        )
        _do_alert_alerted.pop(dedup_key, None)
        return False
    loop.create_task(
        notify_do_alert(title=title, body=body, severity=severity, fields=fields)
    )
    return True


# Linux cgroup v2 paths (containerised app). On the production droplet the
# container runs under cgroup v2; on macOS / Windows dev the reads return
# None and the sampler silently degrades — no false alarms in local dev.
_PSI_MEM = Path("/proc/pressure/memory")
_CGROUP_MEM_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_MEM_MAX = Path("/sys/fs/cgroup/memory.max")

# Thresholds (per OOM/memory subagent recommendation 2026-05-24). Each metric
# has WARN/CRITICAL bands and a SAFE re-arm band; the sampler fires once when
# the sustained-breach count reaches the per-metric sample threshold, and
# stays armed (no re-fire) until the value drops below the safe band.
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
    psi_armed_severity: str | None = None     # None | "warning" | "critical"
    mem_breach: int = 0
    mem_armed_severity: str | None = None
    tasks_breach: int = 0
    tasks_armed_severity: str | None = None


class MemorySampler:
    """Background sampler. One instance per gunicorn worker.

    Reads /proc + asyncio state every ``interval`` seconds, applies
    sustained-N-samples + hysteresis logic, dispatches alerts to
    ``#do-alerts`` via the ``maybe_fire_do_alert`` channel.

    Constructed lazily by ``start()``; ``request_stop()`` flips a shutdown
    event that the loop polls between samples (cooperative cancellation).
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
            logger.warning("do_alerts: MemorySampler.start with no running loop")
            return None
        self._task = loop.create_task(
            self._run_forever(), name="do_alerts_memory_sampler"
        )
        return self._task

    def request_stop(self) -> None:
        self._stop.set()

    async def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception:  # noqa: BLE001 — sampler must never die
                logger.exception("do_alerts: sampler iteration raised")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
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
                maybe_fire_do_alert(
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
            self.state.psi_breach = 0
            self.state.psi_armed_severity = None

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
                maybe_fire_do_alert(
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
                maybe_fire_do_alert(
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


def start_memory_sampler(
    *, interval_seconds: float = _SAMPLE_INTERVAL_SECONDS
) -> "MemorySampler | None":
    """Boot a single MemorySampler instance. Idempotent within a worker."""
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
    return _sampler


@router.get("/digitalocean/healthz")
async def do_alerts_healthz() -> dict[str, Any]:
    """Liveness + whether the Slack webhook URL is wired."""
    sampler = get_sampler()
    return {
        "ok": True,
        "channel": "do_alerts",
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
    "post_to_do_alerts",
    "notify_do_alert",
    "maybe_fire_do_alert",
    "MemorySampler",
    "start_memory_sampler",
    "stop_memory_sampler",
    "get_sampler",
]
