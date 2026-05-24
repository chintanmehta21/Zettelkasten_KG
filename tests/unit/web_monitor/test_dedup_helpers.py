"""Unit tests for maybe_fire_signup_alert / maybe_fire_payment_alert.

These are the dispatcher helpers /api/me and the Razorpay webhook handler
use to fire #user-activity alerts. They wrap notify_new_signup /
notify_payment with idempotency + recency gates so the underlying notifier
fires exactly once per logical event (signup / captured payment) even when
the caller is invoked multiple times.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from website.features.web_monitor import User_Activity as ua_mod
from website.features.web_monitor.User_Activity import (
    maybe_fire_payment_alert,
    maybe_fire_signup_alert,
)


@pytest.fixture(autouse=True)
def _reset_dedup_state():
    ua_mod._signup_alerted.clear()
    ua_mod._payment_alerted.clear()
    yield
    ua_mod._signup_alerted.clear()
    ua_mod._payment_alerted.clear()


def _recent_iso(seconds_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


# ---------------------------------------------------------------------------
# maybe_fire_signup_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_alert_fires_for_fresh_profile(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ua_mod, "notify_new_signup", _capture)

    fired = maybe_fire_signup_alert(
        user_id="f2105544-b73d-4946-8329-096d82f070d3",
        display_name="Naruto Uzumaki",
        email="naruto@example.com",
        created_at=_recent_iso(seconds_ago=5),
        country_code="IN",
    )
    # Yield so the scheduled create_task runs.
    await asyncio.sleep(0)

    assert fired is True
    assert len(captured) == 1
    assert captured[0]["display_name"] == "Naruto Uzumaki"
    assert captured[0]["country_code"] == "IN"


@pytest.mark.asyncio
async def test_signup_alert_skips_stale_profile(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ua_mod, "notify_new_signup", _capture)

    fired = maybe_fire_signup_alert(
        user_id="f2105544-b73d-4946-8329-096d82f070d3",
        display_name="Naruto",
        email="naruto@example.com",
        created_at=_recent_iso(seconds_ago=600),  # 10 min ago, beyond window
    )
    await asyncio.sleep(0)

    assert fired is False
    assert captured == []


@pytest.mark.asyncio
async def test_signup_alert_dedups_concurrent_calls(monkeypatch):
    """Second /api/me hit for the same user must not fire a second alert."""
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ua_mod, "notify_new_signup", _capture)

    recent = _recent_iso()
    r1 = maybe_fire_signup_alert(
        user_id="same-uuid",
        display_name="X",
        email="x@example.com",
        created_at=recent,
    )
    r2 = maybe_fire_signup_alert(
        user_id="same-uuid",
        display_name="X",
        email="x@example.com",
        created_at=recent,
    )
    await asyncio.sleep(0)

    assert r1 is True
    assert r2 is False
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_signup_alert_skips_missing_inputs(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ua_mod, "notify_new_signup", _capture)

    assert maybe_fire_signup_alert(user_id="", display_name="X", email=None, created_at=_recent_iso()) is False
    assert maybe_fire_signup_alert(user_id="u", display_name="X", email=None, created_at=None) is False
    assert maybe_fire_signup_alert(user_id="u", display_name="X", email=None, created_at="not-iso") is False
    await asyncio.sleep(0)
    assert captured == []


# ---------------------------------------------------------------------------
# maybe_fire_payment_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payment_alert_fires_first_time_with_name_and_country(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ua_mod, "notify_payment", _capture)

    fired = maybe_fire_payment_alert(
        provider_payment_id="pay_RAZORPAYxx",
        user_id="user-uuid",
        email="paying@example.com",
        display_name="Dave Doolittle",
        amount=499.0,
        currency="INR",
        plan="basic_monthly",
        country_code="IN",
    )
    await asyncio.sleep(0)

    assert fired is True
    assert len(captured) == 1
    assert captured[0]["provider_payment_id"] == "pay_RAZORPAYxx"
    assert captured[0]["display_name"] == "Dave Doolittle"
    # notify_payment takes ``country`` (alpha-2 code or None); format_country
    # turns it into "India (IN)" at render time.
    assert captured[0]["country"] == "IN"
    assert captured[0]["amount"] == 499.0


@pytest.mark.asyncio
async def test_payment_alert_dedups_duplicate_webhook(monkeypatch):
    """Razorpay sends payment.captured AND order.paid for the same payment.
    Both route through _h_payment_captured which calls maybe_fire_payment_alert
    twice — the helper must dedupe so Slack sees one alert."""
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ua_mod, "notify_payment", _capture)

    r1 = maybe_fire_payment_alert(
        provider_payment_id="pay_DUPE",
        user_id="u",
        email="e@x.com",
        display_name="E",
        amount=199.0,
    )
    r2 = maybe_fire_payment_alert(
        provider_payment_id="pay_DUPE",
        user_id="u",
        email="e@x.com",
        display_name="E",
        amount=199.0,
    )
    await asyncio.sleep(0)

    assert r1 is True
    assert r2 is False
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_payment_alert_skips_empty_provider_id(monkeypatch):
    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(ua_mod, "notify_payment", _capture)

    assert (
        maybe_fire_payment_alert(
            provider_payment_id="",
            user_id="u",
            email="e@x.com",
            display_name="E",
            amount=199.0,
        )
        is False
    )
    await asyncio.sleep(0)
    assert captured == []


# ---------------------------------------------------------------------------
# notify_new_signup country rendering (formatted_country in body)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_new_signup_renders_country_in_body(slack_webhook_mock):
    rec = slack_webhook_mock()
    from website.features.web_monitor.User_Activity import notify_new_signup

    await notify_new_signup(
        user_id="abcdef01-uuid-uuid-uuid-aaaaaaaaaaaa",
        email="alice@example.com",
        display_name="Alice Anderson",
        country_code="IN",
    )
    body = json.dumps(rec.calls["SLACK_WEBHOOK_USER_ACTIVITY"][0], ensure_ascii=False)
    assert "India (IN)" in body, body
    assert "Alice Anderson" in body


@pytest.mark.asyncio
async def test_notify_new_signup_handles_missing_country(slack_webhook_mock):
    rec = slack_webhook_mock()
    from website.features.web_monitor.User_Activity import notify_new_signup

    await notify_new_signup(
        user_id="abcdef01-uuid-uuid-uuid-aaaaaaaaaaaa",
        email="bob@example.com",
        display_name="Bob",
        country_code=None,
    )
    body = json.dumps(rec.calls["SLACK_WEBHOOK_USER_ACTIVITY"][0], ensure_ascii=False)
    # No raw "IN" leaks; em-dash placeholder for missing country.
    assert "—" in body
