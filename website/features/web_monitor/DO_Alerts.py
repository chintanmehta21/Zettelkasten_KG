"""DO_Alerts — alert fan-out to 3 Slack channels.

Channels:
    UPTIME       — BetterStack probe: zettelkasten.in reachability
                   (already wired by user; endpoint here is a no-op pass-through
                    in case you ever want to route BetterStack through us too)
    INFRA        — DigitalOcean droplet alerts: CPU > 80 %, Mem > 85 %, Disk > 80 %
    APP_ERRORS   — Uncaught exceptions / 5xx from the FastAPI app

Mount:
    from website.features.web_monitor import router as web_monitor_router
    app.include_router(web_monitor_router)

Env vars (missing URL → alert is logged to journalctl, not silently dropped):
    SLACK_WEBHOOK_UPTIME         # BetterStack channel (optional passthrough)
    SLACK_WEBHOOK_DO_ALERT       # DO alerts channel
    SLACK_WEBHOOK_APP_ERRORS     # App errors channel
    DO_ALERT_WEBHOOK_SECRET      # shared-secret matched against DO's alert_uuid
                                 # (only needed for /digitalocean endpoint)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger("website.web_monitor")

router = APIRouter(prefix="/webhooks/monitor", tags=["web_monitor"])

# ---------------------------------------------------------------------------
# Channel registry
# ---------------------------------------------------------------------------


class Channel(str, Enum):
    UPTIME = "uptime"
    DO_ALERT = "do_alert"
    APP_ERRORS = "app_errors"


_ENV_BY_CHANNEL: dict[Channel, str] = {
    Channel.UPTIME: "SLACK_WEBHOOK_UPTIME",
    Channel.DO_ALERT: "SLACK_WEBHOOK_DO_ALERT",
    Channel.APP_ERRORS: "SLACK_WEBHOOK_APP_ERRORS",
}


def _webhook_url(channel: Channel) -> str | None:
    return os.getenv(_ENV_BY_CHANNEL[channel])


# ---------------------------------------------------------------------------
# Slack posting
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SlackAlert:
    channel: Channel
    title: str
    body: str
    severity: str = "warning"          # info | warning | critical
    fields: dict[str, str] | None = None
    source: str = "web_monitor"

    def to_blocks(self) -> dict[str, Any]:
        color = {"info": "#2E86AB", "warning": "#D4A024", "critical": "#C83E4D"}.get(
            self.severity, "#D4A024"
        )
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
                    {"type": "mrkdwn", "text": f"source: `{self.source}` · severity: `{self.severity}`"}
                ],
            }
        )
        return {"attachments": [{"color": color, "blocks": blocks}]}


async def post_to_slack(alert: SlackAlert) -> bool:
    url = _webhook_url(alert.channel)
    if not url:
        logger.warning(
            "web_monitor: channel %s has no webhook URL; alert logged only: %s",
            alert.channel.value,
            alert.title,
        )
        logger.info("ALERT[%s] %s — %s", alert.channel.value, alert.title, alert.body)
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=alert.to_blocks())
        if not (200 <= r.status_code < 300):
            logger.error(
                "web_monitor: Slack post failed (%s) channel=%s body=%s",
                r.status_code,
                alert.channel.value,
                r.text[:200],
            )
            return False
        return True
    except httpx.HTTPError as exc:
        logger.exception("web_monitor: Slack post errored: %s", exc)
        return False


# ---------------------------------------------------------------------------
# DigitalOcean monitoring webhook → #infra
# ---------------------------------------------------------------------------


class DOAlertPayload(BaseModel):
    alert_uuid: str | None = Field(default=None)
    alert_description: str | None = Field(default=None)
    trigger_metric: str | None = Field(default=None)
    trigger_status: str | None = Field(default=None)   # "alert" | "resolved"
    droplet_name: str | None = Field(default=None)
    droplet_id: int | None = Field(default=None)
    region: str | None = Field(default=None)
    value: float | None = Field(default=None)
    timestamp: str | None = Field(default=None)

    model_config = {"extra": "allow"}


def _do_severity(metric: str | None, status_: str | None, value: float | None) -> str:
    if status_ == "resolved":
        return "info"
    if value is None or metric is None:
        return "warning"
    if metric in {"cpu", "memory", "mem", "disk"} and value >= 95:
        return "critical"
    return "warning"


@router.post("/digitalocean", status_code=status.HTTP_202_ACCEPTED)
async def digitalocean_alert(request: Request) -> dict[str, str]:
    """DO monitoring webhook → Slack #infra.

    Security: DO does not HMAC-sign alert webhooks. Instead we require the
    alert policy's ``uuid`` field to match ``DO_ALERT_WEBHOOK_SECRET``; any
    other caller is rejected.
    """
    raw = await request.body()
    try:
        data = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid json: {exc}") from exc

    payload = DOAlertPayload.model_validate(data)

    expected = os.getenv("DO_ALERT_WEBHOOK_SECRET")
    if expected and payload.alert_uuid != expected:
        logger.warning("web_monitor: DO webhook rejected — alert_uuid mismatch")
        raise HTTPException(status_code=401, detail="bad alert_uuid")

    metric = (payload.trigger_metric or "unknown").lower()
    status_ = (payload.trigger_status or "alert").lower()
    emoji = {"cpu": ":fire:", "memory": ":battery:", "mem": ":battery:", "disk": ":floppy_disk:"}.get(
        metric, ":rotating_light:"
    )
    if status_ == "resolved":
        emoji = ":white_check_mark:"

    title = f"{emoji} DO alert — {payload.alert_description or metric} [{status_}]"
    body = (
        f"*Droplet:* `{payload.droplet_name or payload.droplet_id or 'unknown'}` "
        f"({payload.region or 'n/a'})\n"
        f"*Metric:* `{metric}`  *Value:* `{payload.value if payload.value is not None else 'n/a'}`"
    )
    fields = {
        "timestamp": payload.timestamp or "—",
        "droplet_id": str(payload.droplet_id or "—"),
    }

    alert = SlackAlert(
        channel=Channel.DO_ALERT,
        title=title,
        body=body,
        severity=_do_severity(metric, status_, payload.value),
        fields=fields,
        source="digitalocean",
    )
    delivered = await post_to_slack(alert)
    return {"status": "delivered" if delivered else "logged"}


# ---------------------------------------------------------------------------
# App errors — internal notifier (wired into FastAPI exception handler)
# ---------------------------------------------------------------------------


async def notify_app_error(
    *,
    route: str,
    exc_type: str,
    message: str,
    request_id: str | None = None,
) -> None:
    """Post an uncaught exception / 5xx to #app-errors.

    Wire once in website/app.py::

        from website.features.web_monitor.DO_Alerts import notify_app_error
        from starlette.responses import JSONResponse

        @app.exception_handler(Exception)
        async def _on_exc(request, exc):
            await notify_app_error(
                route=request.url.path,
                exc_type=type(exc).__name__,
                message=str(exc)[:400],
            )
            return JSONResponse({"error": "internal"}, status_code=500)
    """
    await post_to_slack(
        SlackAlert(
            channel=Channel.APP_ERRORS,
            title=f":boom: {exc_type} on {route}",
            body=f"```{message[:900]}```",
            severity="critical",
            fields={"request_id": request_id or "—"},
            source="app",
        )
    )


# ---------------------------------------------------------------------------
# Uptime passthrough (optional — BetterStack already posts direct to Slack)
# ---------------------------------------------------------------------------


@router.post("/uptime", status_code=status.HTTP_202_ACCEPTED)
async def uptime_alert(payload: dict[str, Any]) -> dict[str, str]:
    """Optional passthrough if you later want BetterStack to route through us."""
    attrs = (payload.get("data") or {}).get("attributes") or payload
    name = attrs.get("name") or attrs.get("monitor_friendly_name") or "unknown monitor"
    url = attrs.get("url") or attrs.get("monitor_url") or ""
    state = (attrs.get("status") or attrs.get("alert_type") or "down").lower()
    alert = SlackAlert(
        channel=Channel.UPTIME,
        title=f":satellite: {name} — {state}",
        body=f"<{url}|{url}>" if url else "(no url)",
        severity="critical" if state in {"down", "alert"} else "info",
        source="uptime",
    )
    delivered = await post_to_slack(alert)
    return {"status": "delivered" if delivered else "logged"}


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True, "channels": {c.value: bool(_webhook_url(c)) for c in Channel}}


__all__ = [
    "router",
    "Channel",
    "SlackAlert",
    "post_to_slack",
    "notify_app_error",
]
