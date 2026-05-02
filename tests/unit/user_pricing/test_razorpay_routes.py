"""Tests for the Razorpay integration in website/features/user_pricing.

The Razorpay SDK is mocked end-to-end — no real network calls are made.
Tests cover order creation (pack + subscription), signature verification
(success / mismatch / missing fields), the webhook handler (signature gate
+ idempotency + fulfillment), and authentication failures.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any
from unittest.mock import patch

import pytest

from website.features.user_pricing import razorpay_client, repository, routes


TEST_KEY_ID = "rzp_test_dummy_key_id"
TEST_KEY_SECRET = "test_secret_for_unit_tests_only"
TEST_WEBHOOK_SECRET = "test_webhook_secret"


def _hmac_sha256(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _razorpay_env(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", TEST_KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", TEST_KEY_SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    razorpay_client.reset_client_cache()
    repository.reset_memory_state_for_tests()
    yield
    razorpay_client.reset_client_cache()
    repository.reset_memory_state_for_tests()


@pytest.fixture
def stub_user() -> dict:
    return {
        "sub": "user-test-1",
        "email": "buyer@example.com",
        "user_metadata": {"full_name": "Test Buyer"},
    }


@pytest.fixture
def saved_profile(stub_user) -> dict:
    repo = repository.get_pricing_repository()
    return repo.upsert_billing_profile(
        user_sub=stub_user["sub"],
        email=stub_user["email"],
        phone="9999999999",
        name="Test Buyer",
    )


class _FakeOrderResource:
    def __init__(self, order_id: str = "order_LIVE_TEST_1") -> None:
        self.order_id = order_id
        self.last_data: dict[str, Any] | None = None

    def create(self, *, data: dict[str, Any]) -> dict[str, Any]:
        self.last_data = data
        return {
            "id": self.order_id,
            "amount": data["amount"],
            "currency": data["currency"],
            "receipt": data.get("receipt"),
            "notes": data.get("notes"),
            "status": "created",
        }


class _FakeRazorpayClient:
    def __init__(self, order_id: str = "order_LIVE_TEST_1") -> None:
        self.order = _FakeOrderResource(order_id)


@pytest.fixture
def fake_client(monkeypatch):
    client = _FakeRazorpayClient()

    def _factory():
        return client

    monkeypatch.setattr(routes, "get_razorpay_client", _factory)
    return client


# ──────────────────────────────── orders ────────────────────────────────


@pytest.mark.asyncio
async def test_create_pack_order_returns_checkout_payload(stub_user, saved_profile, fake_client):
    payload = await routes.create_order(
        routes.PaymentCreateRequest(product_id="zettel_10", expected_amount=9900),
        stub_user,
    )

    assert payload["kind"] == "pack"
    assert payload["key_id"] == TEST_KEY_ID
    assert payload["order_id"] == "order_LIVE_TEST_1"
    assert payload["amount"] == 9900
    assert payload["currency"] == "INR"
    assert payload["payment_id"].startswith("zk_pack_")
    assert payload["prefill"]["contact"] == "9999999999"
    assert payload["prefill"]["email"] == "buyer@example.com"

    assert fake_client.order.last_data["amount"] == 9900
    assert fake_client.order.last_data["notes"]["render_user_id"] == stub_user["sub"]
    assert fake_client.order.last_data["notes"]["product_id"] == "zettel_10"

    record = repository.get_pricing_repository().get_payment_record(payment_id=payload["payment_id"])
    assert record["razorpay_order_id"] == "order_LIVE_TEST_1"
    assert record["status"] == "created"


@pytest.mark.asyncio
async def test_create_subscription_order_uses_period_amount(stub_user, saved_profile, fake_client):
    payload = await routes.create_subscription(
        routes.PaymentCreateRequest(product_id="basic_monthly", expected_amount=14900),
        stub_user,
    )

    assert payload["kind"] == "subscription"
    assert payload["amount"] == 14900
    assert payload["order_id"] == "order_LIVE_TEST_1"
    notes = fake_client.order.last_data["notes"]
    assert notes["kind"] == "subscription"
    assert notes["period_id"] == "basic_monthly"
    assert notes["months"] == "1"


@pytest.mark.asyncio
async def test_create_order_requires_billing_profile(stub_user, fake_client):
    with pytest.raises(routes.HTTPException) as exc:
        await routes.create_order(
            routes.PaymentCreateRequest(product_id="zettel_10"),
            stub_user,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "billing_profile_required"


@pytest.mark.asyncio
async def test_create_order_rejects_amount_below_minimum(stub_user, saved_profile, fake_client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "find_product",
        lambda product_id: {
            "kind": "pack",
            "id": "tiny_pack",
            "amount": 50,
            "meter": "zettel",
            "quantity": 1,
            "name": "Tiny",
        },
    )
    with pytest.raises(routes.HTTPException) as exc:
        await routes.create_order(
            routes.PaymentCreateRequest(product_id="tiny_pack", expected_amount=50),
            stub_user,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "amount_too_low"


@pytest.mark.asyncio
async def test_create_order_returns_503_when_razorpay_not_configured(stub_user, saved_profile, monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    razorpay_client.reset_client_cache()

    with pytest.raises(routes.HTTPException) as exc:
        await routes.create_order(
            routes.PaymentCreateRequest(product_id="zettel_10"),
            stub_user,
        )
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "payments_not_configured"


@pytest.mark.asyncio
async def test_create_order_marks_failed_on_provider_error(stub_user, saved_profile, monkeypatch):
    class BadClient:
        class _OrderRes:
            def create(self, *, data):
                raise RuntimeError("razorpay 5xx")
        order = _OrderRes()

    monkeypatch.setattr(routes, "get_razorpay_client", lambda: BadClient())

    with pytest.raises(routes.HTTPException) as exc:
        await routes.create_order(
            routes.PaymentCreateRequest(product_id="zettel_10"),
            stub_user,
        )
    assert exc.value.status_code == 502
    assert exc.value.detail["code"] == "payments_provider_error"


# ──────────────────────────── verify endpoint ────────────────────────────


@pytest.mark.asyncio
async def test_verify_order_success_marks_paid_and_credits_pack(stub_user, saved_profile, fake_client):
    created = await routes.create_order(
        routes.PaymentCreateRequest(product_id="zettel_10", expected_amount=9900),
        stub_user,
    )
    payment_id = created["payment_id"]
    rzp_payment_id = "pay_DUMMY_12345"
    signature = _hmac_sha256(f"{created['order_id']}|{rzp_payment_id}", TEST_KEY_SECRET)

    result = await routes.verify_order(
        routes.PaymentVerifyRequest(
            payment_id=payment_id,
            razorpay_payment_id=rzp_payment_id,
            razorpay_order_id=created["order_id"],
            razorpay_signature=signature,
        ),
        stub_user,
    )

    assert result["status"] == "paid"
    record = repository.get_pricing_repository().get_payment_record(payment_id=payment_id)
    assert record["status"] == "paid"
    assert record["razorpay_payment_id"] == rzp_payment_id
    balances = repository.get_pricing_repository().get_balances(user_sub=stub_user["sub"])
    assert balances["zettel"] == 10


@pytest.mark.asyncio
async def test_verify_order_signature_mismatch_returns_400(stub_user, saved_profile, fake_client):
    created = await routes.create_order(
        routes.PaymentCreateRequest(product_id="zettel_10", expected_amount=9900),
        stub_user,
    )
    with pytest.raises(routes.HTTPException) as exc:
        await routes.verify_order(
            routes.PaymentVerifyRequest(
                payment_id=created["payment_id"],
                razorpay_payment_id="pay_X",
                razorpay_order_id=created["order_id"],
                razorpay_signature="0" * 64,
            ),
            stub_user,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "signature_mismatch"
    record = repository.get_pricing_repository().get_payment_record(payment_id=created["payment_id"])
    assert record["status"] == "failed"


@pytest.mark.asyncio
async def test_verify_order_rejects_other_users_payment(stub_user, saved_profile, fake_client):
    created = await routes.create_order(
        routes.PaymentCreateRequest(product_id="zettel_10", expected_amount=9900),
        stub_user,
    )
    intruder = {"sub": "user-other", "email": "intruder@example.com", "user_metadata": {}}
    with pytest.raises(routes.HTTPException) as exc:
        await routes.verify_order(
            routes.PaymentVerifyRequest(
                payment_id=created["payment_id"],
                razorpay_payment_id="pay_Y",
                razorpay_order_id=created["order_id"],
                razorpay_signature="abc",
            ),
            intruder,
        )
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "payment_not_found"


@pytest.mark.asyncio
async def test_verify_order_unknown_payment_returns_404(stub_user):
    with pytest.raises(routes.HTTPException) as exc:
        await routes.verify_order(
            routes.PaymentVerifyRequest(
                payment_id="zk_pack_does_not_exist",
                razorpay_payment_id="pay_Z",
                razorpay_order_id="order_Z",
                razorpay_signature="abc",
            ),
            stub_user,
        )
    assert exc.value.status_code == 404


# ──────────────────────────────── webhook ────────────────────────────────


class _FakeRequest:
    def __init__(self, body: bytes, signature: str) -> None:
        self._body = body
        self.headers = {"X-Razorpay-Signature": signature}

    async def body(self) -> bytes:
        return self._body


def _signed_request(event: dict) -> _FakeRequest:
    body = json.dumps(event).encode("utf-8")
    sig = hmac.new(TEST_WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return _FakeRequest(body, sig)


@pytest.mark.asyncio
async def test_webhook_payment_captured_credits_pack(stub_user, saved_profile, fake_client):
    created = await routes.create_order(
        routes.PaymentCreateRequest(product_id="zettel_10", expected_amount=9900),
        stub_user,
    )

    event = {
        "id": "evt_test_001",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_RZP_001",
                    "notes": {
                        "payment_id": created["payment_id"],
                        "render_user_id": stub_user["sub"],
                        "product_id": "zettel_10",
                    },
                }
            }
        },
    }

    response = await routes.razorpay_webhook(_signed_request(event))

    assert response["status"] == "ok"
    record = repository.get_pricing_repository().get_payment_record(payment_id=created["payment_id"])
    assert record["status"] == "paid"
    assert record["razorpay_payment_id"] == "pay_RZP_001"
    balances = repository.get_pricing_repository().get_balances(user_sub=stub_user["sub"])
    assert balances["zettel"] == 10


@pytest.mark.asyncio
async def test_webhook_idempotent_on_duplicate_event(stub_user, saved_profile, fake_client):
    created = await routes.create_order(
        routes.PaymentCreateRequest(product_id="zettel_10", expected_amount=9900),
        stub_user,
    )
    event = {
        "id": "evt_dup_001",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_RZP_DUP",
                    "notes": {"payment_id": created["payment_id"], "render_user_id": stub_user["sub"]},
                }
            }
        },
    }
    first = await routes.razorpay_webhook(_signed_request(event))
    second = await routes.razorpay_webhook(_signed_request(event))

    assert first["status"] == "ok"
    assert second["status"] == "duplicate"
    balances = repository.get_pricing_repository().get_balances(user_sub=stub_user["sub"])
    assert balances["zettel"] == 10  # not double-credited


@pytest.mark.asyncio
async def test_webhook_payment_failed_marks_record(stub_user, saved_profile, fake_client):
    created = await routes.create_order(
        routes.PaymentCreateRequest(product_id="zettel_10", expected_amount=9900),
        stub_user,
    )
    event = {
        "id": "evt_failed_001",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_FAIL",
                    "error_description": "INSUFFICIENT_FUNDS",
                    "notes": {"payment_id": created["payment_id"]},
                }
            }
        },
    }
    await routes.razorpay_webhook(_signed_request(event))
    record = repository.get_pricing_repository().get_payment_record(payment_id=created["payment_id"])
    assert record["status"] == "failed"
    assert record["failure_reason"] == "INSUFFICIENT_FUNDS"


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_400(stub_user):
    body = json.dumps({"id": "evt_x", "event": "payment.captured"}).encode("utf-8")
    req = _FakeRequest(body, signature="0" * 64)
    with pytest.raises(routes.HTTPException) as exc:
        await routes.razorpay_webhook(req)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "invalid_signature"


@pytest.mark.asyncio
async def test_webhook_missing_event_fields_returns_400():
    event = {"id": "evt_only_id"}  # missing 'event'
    with pytest.raises(routes.HTTPException) as exc:
        await routes.razorpay_webhook(_signed_request(event))
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "missing_event_fields"


@pytest.mark.asyncio
async def test_webhook_subscription_activated_creates_subscription(fake_client, stub_user, saved_profile):
    created = await routes.create_subscription(
        routes.PaymentCreateRequest(product_id="basic_monthly", expected_amount=14900),
        stub_user,
    )
    event = {
        "id": "evt_sub_001",
        "event": "subscription.activated",
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_RZP_001",
                    "notes": {
                        "payment_id": created["payment_id"],
                        "render_user_id": stub_user["sub"],
                        "plan_id": "basic",
                        "period_id": "basic_monthly",
                        "months": "1",
                    },
                }
            },
            "payment": {"entity": {"id": "pay_RZP_SUB_001"}},
        },
    }
    await routes.razorpay_webhook(_signed_request(event))
    sub = repository.get_pricing_repository().get_subscription(user_sub=stub_user["sub"])
    assert sub is not None
    assert sub["plan_id"] == "basic"
    assert sub["period_id"] == "basic_monthly"
    assert sub["status"] == "active"


# ───────────────────────── razorpay_client helpers ─────────────────────────


def test_verify_payment_signature_match():
    sig = _hmac_sha256("order_X|pay_X", TEST_KEY_SECRET)
    assert razorpay_client.verify_payment_signature(
        order_id="order_X", payment_id="pay_X", signature=sig
    )


def test_verify_payment_signature_mismatch():
    assert not razorpay_client.verify_payment_signature(
        order_id="order_X", payment_id="pay_X", signature="not-a-real-sig"
    )


def test_verify_webhook_signature_match():
    body = b'{"id":"evt","event":"payment.captured"}'
    sig = hmac.new(TEST_WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert razorpay_client.verify_webhook_signature(body=body, signature=sig)


def test_verify_webhook_signature_rejects_empty_secret(monkeypatch):
    monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
    body = b'{"x":1}'
    assert not razorpay_client.verify_webhook_signature(body=body, signature="anything")
