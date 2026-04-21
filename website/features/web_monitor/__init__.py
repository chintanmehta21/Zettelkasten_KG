"""web_monitor — one file per Slack channel.

Each file is self-contained (its own Slack posting helper, its own router).
Add a new channel = add a new sibling file; no shared base to coordinate.
"""

from fastapi import APIRouter

from website.features.web_monitor.App_Errors import notify_app_error
from website.features.web_monitor.App_Errors import router as _app_errors_router
from website.features.web_monitor.DO_Alerts import router as _do_alerts_router
from website.features.web_monitor.User_Activity import (
    notify_new_signup,
    notify_payment,
    notify_pricing_visit,
)
from website.features.web_monitor.User_Activity import router as _user_activity_router

# Aggregated router so app.py only has one include_router call.
router = APIRouter()
router.include_router(_do_alerts_router)
router.include_router(_app_errors_router)
router.include_router(_user_activity_router)

__all__ = [
    "router",
    "notify_app_error",
    "notify_new_signup",
    "notify_pricing_visit",
    "notify_payment",
]
