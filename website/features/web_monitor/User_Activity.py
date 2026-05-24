"""User_Activity — alert fan-out for conversion-funnel events.

One file, one Slack channel: `#user-activity`. Self-contained (own Slack
helper, own in-memory throttle, own router) matching the per-channel
convention already established by DO_Alerts.py and App_Errors.py.

Events surfaced:
    1. ``notify_new_signup(...)``      — first successful row insert into
       ``core.profiles`` (v2). Called from the v2 profile-bootstrap path
       the moment a brand-new user lands (OAuth or email signup, uniform
       path).
    2. ``notify_pricing_visit(...)``   — authenticated user opens /pricing.
       Fired from the client-side beacon ``POST /api/monitor/pricing-visit``
       which requires a valid Supabase JWT, so curl/bot/internal-network
       hits on the public GET /pricing page never trigger an alert.
       Throttled to one alert per profile UUID per hour.
    3. ``notify_payment(...)``         — payment success. Future. Fire
       from the provider webhook handler once Stripe/Razorpay is wired in.
       The ``/webhooks/monitor/payment`` stub endpoint below is the
       placeholder; flesh it out with signature verification when the
       provider is chosen.

Wiring (one-time):

    # website/core/supabase_v2/repositories/core_repository.py — after a new
    # core.profiles row has been inserted via ensure_profile().
    from website.features.web_monitor.User_Activity import notify_new_signup
    import asyncio
    asyncio.create_task(notify_new_signup(
        user_id=str(profile_id),
        email=email,
        display_name=display_name,
        render_user_id=render_user_id,
    ))

    # Client-side: website/footer/pricing/js/pricing.js posts to
    # /api/monitor/pricing-visit with the user's JWT once the page boots.
    # See ``pricing_visit_beacon`` below for the server-side handler.

Env vars:
    SLACK_WEBHOOK_USER_ACTIVITY   # Slack incoming webhook URL
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from website.api.auth import get_current_user
from website.features.web_monitor._country import format_country
from website.features.web_monitor._slack_client import post_with_retry

logger = logging.getLogger("website.web_monitor.user_activity")

router = APIRouter(prefix="/webhooks/monitor", tags=["web_monitor.user_activity"])

# Authenticated beacon endpoints — distinct prefix from the webhook router
# so JWT-gated client beacons don't share a URL space with inbound webhooks
# from payment providers (different threat model, different rate limits).
api_router = APIRouter(prefix="/api/monitor", tags=["web_monitor.user_activity"])

SLACK_ENV_VAR = "SLACK_WEBHOOK_USER_ACTIVITY"

# Per-profile throttle for pricing-visit alerts. Keyed by Supabase ``sub``
# (profile UUID) so a single user reloading /pricing in a loop doesn't burst
# the channel — and so curl / health-check traffic, which never has a JWT,
# can't touch the throttle map at all (they're rejected at auth gate before
# the throttle is consulted). OrderedDict + move_to_end for O(1) LRU; bounded
# by _PRICING_THROTTLE_MAX with FIFO eviction.
_PRICING_THROTTLE_SECONDS = 60 * 60       # 1 alert / profile UUID / hour
_PRICING_THROTTLE_MAX = 2000
_pricing_seen_at: "OrderedDict[str, float]" = OrderedDict()

# Signup-alert dedup. Per-replica in-memory set of profile UUIDs we've
# already fired ``notify_new_signup`` for. Profiles are created by a Postgres
# trigger (``core.handle_new_auth_user``) the Python layer never observes
# directly — so signup detection happens at the next /api/me call, gated on
# ``created_at`` recency to avoid alerting on every login. Worst-case
# duplicate: blue/green cutover fires once each (2 alerts) which is
# acceptable noise. Bounded by _SIGNUP_DEDUP_MAX with FIFO eviction.
_SIGNUP_DEDUP_MAX = 5000
_SIGNUP_RECENCY_SECONDS = 120
_signup_alerted: "OrderedDict[str, float]" = OrderedDict()

# Payment-alert dedup. Razorpay delivers payment.captured AND order.paid for
# the same payment (both routed through `_h_payment_captured`), so without
# dedup we'd post the same alert twice. Keyed by the provider's payment id
# (Razorpay ``pay_XXX``) which is unique per real payment but shared across
# duplicate webhook deliveries — exactly what we want to dedupe on.
_PAYMENT_DEDUP_MAX = 5000
_payment_alerted: "OrderedDict[str, float]" = OrderedDict()


# ---------------------------------------------------------------------------
# Slack posting
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SlackMessage:
    title: str
    body: str
    severity: str = "info"          # info | warning | critical
    fields: dict[str, str] | None = None
    source: str = "user_activity"

    def to_payload(self) -> dict[str, Any]:
        color = {
            "info": "#2E86AB",
            "warning": "#D4A024",
            "critical": "#C83E4D",
        }.get(self.severity, "#2E86AB")
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
                        "text": f"source: `{self.source}` · event: `{self.severity}`",
                    }
                ],
            }
        )
        return {"attachments": [{"color": color, "blocks": blocks}]}


async def post_to_user_activity(msg: SlackMessage) -> bool:
    """POST to #user-activity. Returns True on 2xx. Never raises.

    WM-05: delegates to _slack_client.post_with_retry for backoff handling.
    """
    url = os.getenv(SLACK_ENV_VAR)
    if not url:
        logger.warning(
            "user_activity: %s unset; event logged only: %s", SLACK_ENV_VAR, msg.title
        )
        logger.info("ALERT[user_activity] %s — %s", msg.title, msg.body)
        return False
    response = await post_with_retry(url, msg.to_payload())
    if response is None:
        logger.error("user_activity: Slack post gave up after retries: %s", msg.title)
        return False
    if not (200 <= response.status_code < 300):
        # B-4: drop response.text — Slack body may echo PII / log-injection.
        logger.error(
            "user_activity: Slack post failed status=%s reason=%s body_len=%s",
            response.status_code,
            response.reason_phrase,
            len(response.text),
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    """Return the real client IP, validated.

    M-3: prefer ``cf-connecting-ip`` (single trusted value Cloudflare sets)
    over ``X-Forwarded-For`` (attacker-controllable comma-list — a crafted
    header could grow ``_pricing_seen_at`` toward _PRICING_THROTTLE_MAX in
    a single burst). Anything that doesn't parse as a real IP collapses to
    the ``"unknown"`` single-bucket — DoS-safe.
    """
    raw = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )
    if not raw:
        return "unknown"
    # XFF may be a comma-list; take the first hop.
    candidate = raw.split(",")[0].strip()
    if not candidate:
        return "unknown"
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return "unknown"
    return candidate


def _mask_email(email: str | None) -> str:
    """Redact email to ``a***@domain.tld`` so Slack doesn't leak PII."""
    if not email or "@" not in email:
        return email or "—"
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def _resolve_full_name(
    *,
    display_name: str | None,
    email: str | None,
) -> str:
    """WM-15: resolve user's display name for Slack payloads.

    Source-of-truth is ``core.profiles.display_name`` (NOT ``full_name`` —
    the column was renamed during the DB v2 cutover; see
    ``supabase/website/_v2/01_core_schema.sql:7``). The trigger
    ``core.handle_new_auth_user`` populates this from the OAuth provider's
    ``raw_user_meta_data ->> 'name'`` (Google / GitHub return the full
    profile name there).

    Fallback chain:
      1. ``display_name`` if set and non-empty.
      2. Email local-part (e.g. ``"alice@x.com" → "alice"``).
      3. Em-dash placeholder for log-only mode when neither is available.

    Pure helper — does not hit the DB. Callers pass display_name explicitly
    so the function stays sync and side-effect-free for unit testing.
    """
    if display_name:
        cleaned = display_name.strip()
        if cleaned:
            return cleaned
    if email and "@" in email:
        local = email.split("@", 1)[0].strip()
        if local:
            return local
    return "—"


# ---------------------------------------------------------------------------
# Event 1 — new signup
# ---------------------------------------------------------------------------


async def notify_new_signup(
    *,
    user_id: str,
    email: str | None = None,
    display_name: str | None = None,
    render_user_id: str | None = None,
    signup_source: str | None = None,
    country_code: str | None = None,
) -> None:
    """A new row just landed in ``core.profiles`` — celebrate in Slack.

    Called from the /api/me handler the FIRST time we observe a recently-
    created profile (see ``maybe_fire_signup_alert``). The trigger
    ``core.handle_new_auth_user`` does the actual INSERT in Postgres on
    every OAuth/email signup, so the Python layer never sees the moment
    of insertion directly.

    Args:
        user_id: our internal Supabase UUID (primary key of core.profiles).
        email: supplied by Supabase auth metadata; will be masked in Slack.
        display_name: OAuth provider display name if any.
        render_user_id: Supabase auth.users id (the ``sub`` from the JWT).
            Optional — same as user_id under the v2 schema, kept for callers
            that still hold the legacy distinction.
        signup_source: free-form hint ("oauth:google", "email", …) if the
            caller has it. Optional.
        country_code: ISO-3166 alpha-2 country code (typically from
            ``cf-ipcountry`` on the first /api/me hit). Rendered as
            ``"Name (CC)"`` via :func:`format_country`.
    """
    # WM-15: resolved name appears in BOTH the body text AND the fields block
    # so on-call ops sees who signed up without scanning the field strip.
    resolved_name = _resolve_full_name(display_name=display_name, email=email)
    formatted_country = format_country(country_code)
    fields = {
        "name": resolved_name,
        "user_id": user_id[:8] + "…",
        "email": _mask_email(email),
        "country": formatted_country,
    }
    if render_user_id and render_user_id != user_id:
        fields["auth_id"] = render_user_id[:8] + "…"
    if signup_source:
        fields["source"] = signup_source

    msg = SlackMessage(
        title=":tada: New signup",
        body=f"A new user just joined — *{resolved_name}* ({_mask_email(email)}) from *{formatted_country}*",
        severity="info",
        fields=fields,
        source="signup",
    )
    try:
        await post_to_user_activity(msg)
    except Exception:  # noqa: BLE001 — alerting must never break signup
        logger.exception("user_activity: notify_new_signup dispatch failed")


def maybe_fire_signup_alert(
    *,
    user_id: str,
    display_name: str | None,
    email: str | None,
    created_at: str | None,
    country_code: str | None = None,
) -> bool:
    """Schedule a signup alert iff this profile is brand-new + un-alerted.

    Called from ``/api/me`` on every authenticated request. The two gates:
      * ``created_at`` is within ``_SIGNUP_RECENCY_SECONDS`` of now — keeps
        established users from triggering on every login.
      * ``user_id`` not already in ``_signup_alerted`` — bounded LRU dedup
        so refresh-spam during the first page load fires exactly once.

    Returns True if an alert task was scheduled, False otherwise. Never
    raises — alerting must not break /api/me.
    """
    if not user_id or not created_at:
        return False
    # Parse the Supabase ISO-8601 timestamp. Tolerate both "...+00:00" and
    # "...Z" suffixes; bail silently on any other shape (we'd rather skip
    # the alert than block a /api/me response on a parse error).
    try:
        ts_text = created_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_text)
    except (ValueError, AttributeError):
        return False
    now_ts = time.time()
    try:
        age_seconds = now_ts - dt.timestamp()
    except (OSError, OverflowError, ValueError):
        return False
    if age_seconds < 0 or age_seconds > _SIGNUP_RECENCY_SECONDS:
        return False

    # Atomic check-and-set via setdefault with a unique sentinel — a plain
    # timestamp marker is not unique on Windows (time.time() resolution is
    # ~15 ms) so two rapid concurrent calls can produce identical floats.
    # Using ``object()`` guarantees identity equality only on the inserter.
    sentinel = object()
    prev = _signup_alerted.setdefault(user_id, sentinel)
    if prev is not sentinel:
        return False
    # We won the insert; replace the sentinel with the actual timestamp
    # so LRU eviction has a useful key, and bound the dict.
    _signup_alerted[user_id] = now_ts
    if len(_signup_alerted) > _SIGNUP_DEDUP_MAX:
        _signup_alerted.popitem(last=False)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Sync caller — should never happen for /api/me (async route),
        # but a misuse from a script context shouldn't crash either.
        logger.warning("user_activity: maybe_fire_signup_alert called with no event loop")
        # Roll back the dedup entry so a later async caller can still fire.
        _signup_alerted.pop(user_id, None)
        return False
    loop.create_task(
        notify_new_signup(
            user_id=user_id,
            email=email,
            display_name=display_name,
            country_code=country_code,
        )
    )
    return True


# ---------------------------------------------------------------------------
# Event 2 — pricing page visit (authenticated only)
# ---------------------------------------------------------------------------


async def notify_pricing_visit(
    *,
    user_id: str,
    display_name: str | None = None,
    email: str | None = None,
    country_code: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    referer: str | None = None,
) -> None:
    """An authenticated user opened /pricing — alert #user-activity.

    Caller responsibility (the ``pricing_visit_beacon`` endpoint below
    plus any future server-side trigger): pass a real profile UUID for
    ``user_id``. There is no anonymous path — synthetic / curl / health-
    check traffic gets filtered at the JWT gate, never reaches here.

    Throttle: one alert per ``user_id`` per ``_PRICING_THROTTLE_SECONDS``.
    Each blue/green replica owns its own in-memory map; during a cutover
    the worst case is ~2 alerts per user per hour, still well below the
    Slack-noise threshold.
    """
    if not user_id:
        # Defensive guard: refuse to alert without a profile UUID. The
        # whole point of the auth gate is to prevent anonymous noise.
        logger.warning("user_activity: notify_pricing_visit called without user_id; dropping")
        return

    now = time.time()
    last = _pricing_seen_at.get(user_id)
    if last is not None and (now - last) < _PRICING_THROTTLE_SECONDS:
        # Touch on access so this user_id stays at the LRU tail.
        _pricing_seen_at.move_to_end(user_id)
        return  # throttled

    if len(_pricing_seen_at) >= _PRICING_THROTTLE_MAX:
        _pricing_seen_at.popitem(last=False)
    _pricing_seen_at[user_id] = now
    _pricing_seen_at.move_to_end(user_id)

    resolved_name = _resolve_full_name(display_name=display_name, email=email)
    formatted_country = format_country(country_code)
    ua = (user_agent or "—")[:120]
    ref = (referer or "—")[:200]

    msg = SlackMessage(
        title=":eyes: Pricing page visit",
        body=f"*{resolved_name}* is checking out the pricing page from *{formatted_country}*",
        severity="info",
        fields={
            "name": resolved_name,
            "user_id": user_id[:8] + "…",
            "country": formatted_country,
            "ip": ip or "—",
            "referer": ref,
            "user_agent": ua,
        },
        source="pricing",
    )
    try:
        await post_to_user_activity(msg)
    except Exception:  # noqa: BLE001
        logger.exception("user_activity: notify_pricing_visit dispatch failed")


# ---------------------------------------------------------------------------
# Beacon endpoint — client-side fires this once authenticated /pricing loads
# ---------------------------------------------------------------------------


@api_router.post("/pricing-visit", status_code=status.HTTP_202_ACCEPTED)
async def pricing_visit_beacon(
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, str]:
    """Authenticated beacon — client-side fetch from /pricing JS posts here.

    The gate is the ``Depends(get_current_user)`` dependency — without a
    valid Supabase JWT the handler 401s before any work happens, which is
    exactly the property that filters curl / health-check / docker-internal
    probes out of the #user-activity channel.

    No DB hit: ``display_name`` and ``email`` come from JWT claims (set by
    Supabase auth from the OAuth provider's profile, or by the email-signup
    handler). That keeps the beacon path latency-free and lets us avoid
    coupling the alert pipeline to the v2 Supabase client. If the JWT
    metadata is sparse we fall back to the email local-part via
    ``_resolve_full_name``.
    """
    metadata = user.get("user_metadata") or {}
    # Supabase mints both keys depending on provider — try the richer one
    # first (Google: full_name; GitHub: name; email-signup: display_name).
    display_name = (
        metadata.get("full_name")
        or metadata.get("name")
        or metadata.get("display_name")
        or None
    )
    email = user.get("email") or metadata.get("email") or None
    user_id = user.get("sub") or ""

    asyncio.create_task(
        notify_pricing_visit(
            user_id=user_id,
            display_name=display_name,
            email=email,
            country_code=request.headers.get("cf-ipcountry"),
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            referer=request.headers.get("referer"),
        )
    )
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Event 3 — payment (future)
# ---------------------------------------------------------------------------


async def notify_payment(
    *,
    user_id: str | None,
    email: str | None,
    amount: float,
    currency: str = "INR",
    plan: str | None = None,
    provider: str = "unknown",
    provider_payment_id: str | None = None,
    display_name: str | None = None,
    country: str | None = None,
) -> None:
    """Payment succeeded. Wire this into the eventual provider webhook
    handler (Stripe ``payment_intent.succeeded``, Razorpay ``payment.captured``
    — whichever is chosen).

    WM-15/WM-16: includes resolved display_name + formatted country in the
    payload so payment alerts surface "who & where" at a glance. Both are
    optional — callers that don't yet plumb them through still get a valid
    Slack message, just without the enrichment.

    Left as a callable now so the hook site in /webhooks/monitor/payment
    below can be filled in later without touching this file's public API.
    """
    resolved_name = _resolve_full_name(display_name=display_name, email=email)
    formatted_country = format_country(country)
    msg = SlackMessage(
        title=f":moneybag: Payment — {amount:.2f} {currency}",
        body=f"*{resolved_name}* ({_mask_email(email)}) just paid "
        f"{amount:.2f} {currency}"
        + (f" for *{plan}*" if plan else ""),
        severity="info",
        fields={
            "user_id": (user_id or "—")[:8] + ("…" if user_id else ""),
            "name": resolved_name,
            "country": formatted_country,
            "provider": provider,
            "provider_payment_id": provider_payment_id or "—",
            "plan": plan or "—",
        },
        source="payment",
    )
    try:
        await post_to_user_activity(msg)
    except Exception:  # noqa: BLE001
        logger.exception("user_activity: notify_payment dispatch failed")


def maybe_fire_payment_alert(
    *,
    provider_payment_id: str,
    user_id: str | None,
    email: str | None,
    display_name: str | None,
    amount: float,
    currency: str = "INR",
    plan: str | None = None,
    provider: str = "razorpay",
    country_code: str | None = None,
) -> bool:
    """Schedule a payment alert iff this ``provider_payment_id`` is new.

    Idempotent on the provider's payment id so Razorpay's at-least-once
    webhook delivery (payment.captured + order.paid for the same payment)
    only produces one Slack alert per real payment. Never raises.
    """
    if not provider_payment_id:
        return False
    # Identity-based check-and-set (see maybe_fire_signup_alert: a float
    # marker isn't unique enough on Windows where time.time() resolution
    # is coarse). A unique ``object()`` guarantees only the inserter wins.
    sentinel = object()
    prev = _payment_alerted.setdefault(provider_payment_id, sentinel)
    if prev is not sentinel:
        return False
    _payment_alerted[provider_payment_id] = time.time()
    if len(_payment_alerted) > _PAYMENT_DEDUP_MAX:
        _payment_alerted.popitem(last=False)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("user_activity: maybe_fire_payment_alert called with no event loop")
        _payment_alerted.pop(provider_payment_id, None)
        return False
    loop.create_task(
        notify_payment(
            user_id=user_id,
            email=email,
            amount=amount,
            currency=currency,
            plan=plan,
            provider=provider,
            provider_payment_id=provider_payment_id,
            display_name=display_name,
            country=country_code,
        )
    )
    return True


# ---------------------------------------------------------------------------
# Future payment webhook (stub — provider-agnostic placeholder)
# ---------------------------------------------------------------------------


@router.post("/payment", status_code=status.HTTP_202_ACCEPTED)
async def payment_webhook(request: Request) -> dict[str, str]:
    """Future: receive Stripe/Razorpay webhook → notify_payment().

    Left as a stub returning 501 until the payment provider is wired in.
    When flipping this on:
      1. Verify the provider's signature header (Stripe-Signature /
         X-Razorpay-Signature) using the provider's webhook secret from
         env (``STRIPE_WEBHOOK_SECRET`` / ``RAZORPAY_WEBHOOK_SECRET``).
      2. Accept only the success event type(s) you actually care about.
      3. Extract ``user_id``, ``email``, ``amount``, ``currency``,
         ``plan``, ``provider_payment_id`` from the payload.
      4. Call ``await notify_payment(...)``.

    Keep the 401/400 paths strict — payment webhooks are an attractive
    target for spoofing "fake success" messages to Slack.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="payment webhook not yet wired — provider TBD",
    )


# ---------------------------------------------------------------------------
# Healthz
# ---------------------------------------------------------------------------


@router.get("/user-activity/healthz")
async def user_activity_healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "channel": "user_activity",
        "webhook_configured": bool(os.getenv(SLACK_ENV_VAR)),
        "pricing_throttle_seen": len(_pricing_seen_at),
    }


__all__ = [
    "router",
    "api_router",
    "SlackMessage",
    "post_to_user_activity",
    "notify_new_signup",
    "notify_pricing_visit",
    "notify_payment",
    "maybe_fire_signup_alert",
    "maybe_fire_payment_alert",
]
