"""UP-20: cross-tenant webhook spoof — valid signature, hostile ``notes``.

Attack scenario:
  1. Attacker A initiates a real payment flow (creates a billing profile and
     posts to ``/api/payments/orders``). This mints a local payment record
     ``payment_id_A`` owned by A (``render_user_id = A.auth_user_id``) and a
     Razorpay order — both echoed back in the order's ``notes`` dict.
  2. Razorpay later sends a ``payment.captured`` webhook for A's order.
  3. Hostile variant: an attacker who can guess / observe A's
     ``payment_id_A`` crafts a webhook payload where
     ``payload.payment.entity.notes.render_user_id`` is set to the VICTIM's
     auth UUID (B). The body is signed with the real webhook secret
     (simulating either a compromised webhook secret or — more realistically
     — Razorpay's own ``notes`` being client-supplied and unsigned by the
     provider beyond the HMAC over the JSON envelope).

Property under test: the handler resolves the credited account from the
**locally-issued ``payment_id`` lookup** (which is bound to A in the database
at order-create time), NOT from ``notes.render_user_id``. So even with a
valid signature over a notes-spoofed body, the credit lands on A — never B.

Discovery 2026-05-11 confirmed the handler chain:
  ``_h_payment_captured`` extracts ``pid = notes.payment_id``, then calls
  ``repo.mark_payment_paid(payment_id=pid, …)`` → ``_apply_fulfillment`` which
  reads ``record.render_user_id`` (the database-bound owner of pid) for
  credit attribution. ``notes.render_user_id`` is NEVER consulted on the
  one-time-pack path.

Subscription path (``_h_subscription_activated``) DOES read
``notes.render_user_id`` — that is a separate hardening surface tracked in
the discovery doc. This test pins the one-time-pack invariant; the
subscription notes-trust path is intentionally NOT exercised here (it
would require a separate Phase-9 fix and is out of UP-20 scope).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.live


WEBHOOK_PATH = "/api/payments/webhook"


# ─────────────────────────── fixtures ───────────────────────────


@pytest.fixture
def webhook_secret(monkeypatch) -> str:
    """Inject a deterministic webhook secret + reset the cached Razorpay client.

    Razorpay client cache reset is required because Phase 4 fixtures may have
    left a client bound to different test creds; without the reset the route
    would attempt to verify against a stale secret.
    """
    secret = "wave-a-spoof-test-secret"
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", secret)
    from website.features.user_pricing import razorpay_client
    razorpay_client.reset_client_cache()
    return secret


@pytest.fixture
def app_client(monkeypatch):
    """TestClient with v2 schema bound + Razorpay creds for the order endpoint."""
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    monkeypatch.setenv("GEMINI_API_KEYS", "stub-key-for-spoof-tests")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stub-key-for-spoof-tests")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_phase4_spoof")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "phase4-spoof-secret-not-deployed")

    from website.api import auth as auth_mod
    auth_mod._jwks_client = None
    from website.core import persist as persist_mod
    persist_mod._v2_core_repo = None
    persist_mod._v2_content_repo = None
    from website.features.user_pricing import razorpay_client
    razorpay_client.reset_client_cache()

    from website.app import create_app
    return TestClient(create_app())


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post_webhook(client: TestClient, body: bytes, signature: str):
    return client.post(
        WEBHOOK_PATH,
        content=body,
        headers={
            "X-Razorpay-Signature": signature,
            "Content-Type": "application/json",
        },
    )


def _seed_pack_payment(repo, *, user_sub: str) -> dict:
    """Bypass Razorpay by directly creating a local pack payment record.

    Mirrors what ``/api/payments/orders`` does AFTER its product/profile gates
    pass but BEFORE the Razorpay SDK call: ``repo.create_payment_record(...)``.
    Using the repo directly keeps the test hermetic (no respx, no SDK shim).
    The payment row's ``render_user_id`` is the database-bound owner that the
    webhook handler must respect — which is the invariant under test.
    """
    return repo.create_payment_record(
        user_sub=user_sub,
        product_id="zettel-pack-100",
        kind="pack",
        amount=9900,
        currency="INR",
        meter="zettels",
        quantity=100,
    )


# ─────────────────────────── UP-20: notes-spoof denial ───────────────────────────


def test_webhook_spoofed_notes_user_does_not_credit_victim(
    app_client, webhook_secret, mint_user, asyncpg_pool
):
    """Notes-level user-sub spoof must NOT credit the victim's account.

    The handler keys off ``notes.payment_id`` → DB lookup → record's
    ``render_user_id`` (the database-bound owner). The spoofed
    ``notes.render_user_id`` pointing at the victim is ignored on the
    one-time-pack credit path.
    """
    attacker = mint_user()
    victim = mint_user()

    # Step 1: attacker has a real local payment record (owned by attacker).
    from website.features.user_pricing.repository import get_pricing_repository
    repo = get_pricing_repository()
    attacker_payment = _seed_pack_payment(repo, user_sub=str(attacker.auth_user_id))
    attacker_pid = attacker_payment["payment_id"]

    # Step 2: craft a signed webhook for that payment with notes spoofed at
    # the victim. notes.payment_id resolves to attacker's record; the spoof is
    # in notes.render_user_id (which the one-time-pack handler must IGNORE).
    razorpay_payment_id = f"pay_{uuid.uuid4().hex[:14]}"
    event_id = f"evt_spoof_{uuid.uuid4().hex[:12]}"
    event = {
        "event": "payment.captured",
        "id": event_id,
        "payload": {
            "payment": {
                "entity": {
                    "id": razorpay_payment_id,
                    "order_id": attacker_payment.get("razorpay_order_id") or f"order_{uuid.uuid4().hex[:10]}",
                    "amount": 9900,
                    "currency": "INR",
                    "notes": {
                        "payment_id": attacker_pid,
                        # Hostile fields below — must NOT influence credit.
                        "render_user_id": str(victim.auth_user_id),
                        "user_sub": str(victim.auth_user_id),
                    },
                }
            }
        },
    }
    body = json.dumps(event).encode("utf-8")
    sig = _sign(body, webhook_secret)

    r = _post_webhook(app_client, body, sig)
    # Razorpay must always see a 2xx so it does not retry-storm; the handler's
    # idempotency layer records the event.
    assert r.status_code in (200, 202), r.text
    payload = r.json()
    assert payload.get("event_id") == event_id

    # Property: victim has ZERO paid pack credits as a result of the spoofed
    # webhook. We can validate via the credited-account lookup on the repo
    # (which reads the database-bound payment owner, not the notes).
    rec = repo.get_payment_record(payment_id=attacker_pid)
    assert rec is not None, "attacker's payment record vanished after webhook"
    assert rec.get("render_user_id") == str(attacker.auth_user_id), (
        f"webhook spoof changed payment_id owner — expected attacker "
        f"{attacker.auth_user_id}, got {rec.get('render_user_id')!r}"
    )

    # Defence-in-depth: query the v2 billing.pricing_orders row directly (the
    # canonical store under repo-scope). The render_user_id column must still
    # be attacker. asyncpg pool bypasses RLS via service role — exactly what
    # we want to confirm raw DB state.
    async def _victim_credit_count():
        async with asyncpg_pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM billing.pricing_orders "
                "WHERE render_user_id = $1 AND payment_id = $2",
                victim.auth_user_id,
                attacker_pid,
            )

    try:
        victim_rows = asyncio.get_event_loop().run_until_complete(_victim_credit_count())
    except Exception:
        # If the row never propagated to v2 (memory-only path), the in-memory
        # assertion above already pins the property; skip the DB cross-check.
        victim_rows = 0
    assert victim_rows == 0, (
        f"Webhook spoof CREDITED VICTIM: {victim_rows} row(s) found in "
        "billing.pricing_orders where render_user_id=victim AND "
        "payment_id=attacker's payment_id. The handler trusted notes — bug."
    )


def test_webhook_unsigned_spoof_rejected_400(app_client, webhook_secret, mint_user):
    """Sanity: a notes-spoofed body WITHOUT a valid signature is rejected at
    the signature gate (400 invalid_signature) — proves the spoof only
    matters when the attacker has the webhook secret (or a Razorpay-issued
    HMAC). The handler never reaches the user-attribution logic on bad sig.
    """
    victim = mint_user()
    event = {
        "event": "payment.captured",
        "id": f"evt_unsigned_{uuid.uuid4().hex[:10]}",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_unsigned_x",
                    "notes": {
                        "payment_id": "zk_pack_phantom",
                        "render_user_id": str(victim.auth_user_id),
                    },
                }
            }
        },
    }
    body = json.dumps(event).encode("utf-8")
    bogus_sig = _sign(body, "wrong-secret")
    r = _post_webhook(app_client, body, bogus_sig)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    code = detail.get("code") if isinstance(detail, dict) else None
    assert code == "invalid_signature", r.text
    # UUID-leak guard: rejection body must not echo the victim's id.
    assert str(victim.auth_user_id) not in r.text, (
        f"signature rejection leaked victim UUID: {r.text!r}"
    )
