"""web_monitor — operational alerting surface.

Fans alerts from infra (DigitalOcean), CI (GitHub Actions), the app itself,
external uptime probes, SSL/DNS, and third-party quota ceilings into
dedicated Slack channels so signal stays separated by on-call concern.
"""

from website.features.web_monitor.DO_Alerts import router  # noqa: F401

__all__ = ["router"]
