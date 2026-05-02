"""Persistence facade for pricing state.

The concrete production schema is provided by the Supabase migration
(``supabase/website/user_pricing/schema.sql``). This facade stays small so
route code can be tested without a live database and without leaking
provider details into API handlers.

In-memory dicts are used as a graceful fallback whenever Supabase is not
configured or a write fails — entitlement checks "fail open" rather than
blocking real users on infra hiccups.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from website.core.supabase_kg.client import is_supabase_configured
from website.features.user_pricing.models import Meter

logger = logging.getLogger(__name__)

_MEMORY_PROFILES: dict[str, dict] = {}
_MEMORY_PAYMENTS: dict[str, dict] = {}
_MEMORY_BALANCES: dict[str, dict[str, int]] = {}
_MEMORY_SUBSCRIPTIONS: dict[str, dict] = {}
_MEMORY_EVENTS: dict[str, dict] = {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class PricingRepository:
    """Supabase-backed pricing repository with in-memory fallback."""

    # ────────────────────────── entitlements ──────────────────────────

    def check_entitlement(self, *, user_sub: str, meter: Meter, action_id: str | None) -> bool:
        if not is_supabase_configured():
            return True

        try:
            from website.core.persist import get_supabase_scope

            scoped = get_supabase_scope(user_id_override=user_sub)
            if not scoped:
                return True
            repo, _kg_user_id = scoped
            response = repo._client.rpc(
                "pricing_check_entitlement",
                {"p_render_user_id": user_sub, "p_meter": str(meter), "p_action_id": action_id},
            ).execute()
            return bool(response.data)
        except Exception as exc:
            logger.warning("Pricing entitlement check failed open for user=%s meter=%s: %s", user_sub, meter, exc)
            return True

    def consume_entitlement(self, *, user_sub: str, meter: Meter, action_id: str | None) -> None:
        if not is_supabase_configured():
            return

        try:
            from website.core.persist import get_supabase_scope

            scoped = get_supabase_scope(user_id_override=user_sub)
            if not scoped:
                return
            repo, _kg_user_id = scoped
            repo._client.rpc(
                "pricing_consume_entitlement",
                {"p_render_user_id": user_sub, "p_meter": str(meter), "p_action_id": action_id},
            ).execute()
        except Exception as exc:
            logger.warning("Pricing entitlement consume failed for user=%s meter=%s: %s", user_sub, meter, exc)

    # ───────────────────────── billing profile ─────────────────────────

    def get_billing_profile(self, *, user_sub: str) -> dict | None:
        if not is_supabase_configured():
            return _MEMORY_PROFILES.get(user_sub)

        try:
            from website.core.persist import get_supabase_scope

            scoped = get_supabase_scope(user_id_override=user_sub)
            if not scoped:
                return None
            repo, _kg_user_id = scoped
            response = (
                repo._client.table("pricing_billing_profiles")
                .select("*")
                .eq("render_user_id", user_sub)
                .limit(1)
                .execute()
            )
            return response.data[0] if response.data else None
        except Exception as exc:
            logger.warning("Billing profile lookup failed for user=%s: %s", user_sub, exc)
            return _MEMORY_PROFILES.get(user_sub)

    def upsert_billing_profile(self, *, user_sub: str, email: str, phone: str, name: str = "") -> dict:
        row = {
            "render_user_id": user_sub,
            "email": email,
            "phone": phone,
            "name": name,
            "updated_at": _now_iso(),
        }
        if not is_supabase_configured():
            _MEMORY_PROFILES[user_sub] = row
            return row

        try:
            from website.core.persist import get_supabase_scope

            scoped = get_supabase_scope(user_id_override=user_sub)
            if not scoped:
                _MEMORY_PROFILES[user_sub] = row
                return row
            repo, _kg_user_id = scoped
            response = (
                repo._client.table("pricing_billing_profiles")
                .upsert(row, on_conflict="render_user_id")
                .execute()
            )
            return response.data[0] if response.data else row
        except Exception as exc:
            logger.warning("Billing profile upsert failed for user=%s: %s", user_sub, exc)
            _MEMORY_PROFILES[user_sub] = row
            return row

    # ─────────────────────────── payments ────────────────────────────

    def create_payment_record(
        self,
        *,
        user_sub: str,
        product_id: str,
        kind: str,
        amount: int,
        currency: str,
        plan_id: str | None = None,
        period_id: str | None = None,
        meter: str | None = None,
        quantity: int | None = None,
    ) -> dict:
        payment_id = f"zk_{kind}_{uuid4().hex}"
        row = {
            "payment_id": payment_id,
            "render_user_id": user_sub,
            "product_id": product_id,
            "kind": kind,
            "amount": int(amount),
            "currency": currency,
            "status": "created",
            "plan_id": plan_id,
            "period_id": period_id,
            "meter": meter,
            "quantity": int(quantity) if quantity is not None else None,
            "razorpay_order_id": None,
            "razorpay_subscription_id": None,
            "razorpay_payment_id": None,
            "created_at": _now_iso(),
        }
        _MEMORY_PAYMENTS[payment_id] = row
        if is_supabase_configured():
            self._supabase_insert("pricing_orders", row)
        return row

    def attach_provider_order(
        self,
        *,
        payment_id: str,
        razorpay_order_id: str | None = None,
        razorpay_subscription_id: str | None = None,
    ) -> dict:
        row = _MEMORY_PAYMENTS.setdefault(payment_id, {"payment_id": payment_id})
        if razorpay_order_id is not None:
            row["razorpay_order_id"] = razorpay_order_id
        if razorpay_subscription_id is not None:
            row["razorpay_subscription_id"] = razorpay_subscription_id
        row["updated_at"] = _now_iso()
        if is_supabase_configured():
            self._supabase_update(
                "pricing_orders",
                {
                    k: v
                    for k, v in {
                        "razorpay_order_id": razorpay_order_id,
                        "razorpay_subscription_id": razorpay_subscription_id,
                        "updated_at": row["updated_at"],
                    }.items()
                    if v is not None
                },
                where=("payment_id", payment_id),
            )
        return row

    def mark_payment_paid(
        self,
        *,
        payment_id: str,
        razorpay_payment_id: str,
        signature: str | None = None,
    ) -> dict:
        row = _MEMORY_PAYMENTS.setdefault(payment_id, {"payment_id": payment_id})
        row["razorpay_payment_id"] = razorpay_payment_id
        row["status"] = "paid"
        row["signature"] = signature
        row["paid_at"] = _now_iso()
        row["updated_at"] = row["paid_at"]
        if is_supabase_configured():
            self._supabase_update(
                "pricing_orders",
                {
                    "razorpay_payment_id": razorpay_payment_id,
                    "status": "paid",
                    "paid_at": row["paid_at"],
                    "updated_at": row["paid_at"],
                },
                where=("payment_id", payment_id),
            )
        return row

    def mark_payment_failed(self, *, payment_id: str, reason: str) -> dict:
        row = _MEMORY_PAYMENTS.setdefault(payment_id, {"payment_id": payment_id})
        row["status"] = "failed"
        row["failure_reason"] = reason
        row["updated_at"] = _now_iso()
        if is_supabase_configured():
            self._supabase_update(
                "pricing_orders",
                {"status": "failed", "failure_reason": reason, "updated_at": row["updated_at"]},
                where=("payment_id", payment_id),
            )
        return row

    def get_payment_record(self, *, payment_id: str) -> dict | None:
        if payment_id in _MEMORY_PAYMENTS:
            return _MEMORY_PAYMENTS[payment_id]
        if is_supabase_configured():
            try:
                from website.core.persist import get_supabase_scope

                scoped = get_supabase_scope()
                if not scoped:
                    return None
                repo, _ = scoped
                response = (
                    repo._client.table("pricing_orders")
                    .select("*")
                    .eq("payment_id", payment_id)
                    .limit(1)
                    .execute()
                )
                if response.data:
                    _MEMORY_PAYMENTS[payment_id] = response.data[0]
                    return response.data[0]
            except Exception as exc:
                logger.warning("Payment lookup failed for %s: %s", payment_id, exc)
        return None

    def find_payment_by_razorpay_order(self, *, razorpay_order_id: str) -> dict | None:
        for row in _MEMORY_PAYMENTS.values():
            if row.get("razorpay_order_id") == razorpay_order_id:
                return row
        if is_supabase_configured():
            try:
                from website.core.persist import get_supabase_scope

                scoped = get_supabase_scope()
                if not scoped:
                    return None
                repo, _ = scoped
                response = (
                    repo._client.table("pricing_orders")
                    .select("*")
                    .eq("razorpay_order_id", razorpay_order_id)
                    .limit(1)
                    .execute()
                )
                if response.data:
                    _MEMORY_PAYMENTS[response.data[0]["payment_id"]] = response.data[0]
                    return response.data[0]
            except Exception as exc:
                logger.warning("Payment lookup by order failed for %s: %s", razorpay_order_id, exc)
        return None

    # ─────────────────────────── balances ────────────────────────────

    def add_pack_credits(self, *, user_sub: str, meter: str, quantity: int) -> dict[str, int]:
        wallet = _MEMORY_BALANCES.setdefault(user_sub, {})
        wallet[meter] = int(wallet.get(meter, 0)) + int(quantity)
        if is_supabase_configured():
            try:
                from website.core.persist import get_supabase_scope

                scoped = get_supabase_scope(user_id_override=user_sub)
                if scoped:
                    repo, _ = scoped
                    repo._client.rpc(
                        "pricing_add_pack_credits",
                        {"p_render_user_id": user_sub, "p_meter": meter, "p_quantity": int(quantity)},
                    ).execute()
            except Exception as exc:
                logger.warning("add_pack_credits supabase failed for user=%s meter=%s: %s", user_sub, meter, exc)
        return dict(wallet)

    def get_balances(self, *, user_sub: str) -> dict[str, int]:
        return dict(_MEMORY_BALANCES.get(user_sub, {}))

    # ───────────────────────── subscriptions ─────────────────────────

    def activate_subscription(
        self,
        *,
        user_sub: str,
        plan_id: str,
        period_id: str,
        months: int,
        razorpay_subscription_id: str | None = None,
        razorpay_payment_id: str | None = None,
    ) -> dict:
        start = datetime.now(UTC)
        end = start + timedelta(days=int(months) * 30)
        row = {
            "render_user_id": user_sub,
            "plan_id": plan_id,
            "period_id": period_id,
            "status": "active",
            "current_period_start": start.isoformat(),
            "current_period_end": end.isoformat(),
            "razorpay_subscription_id": razorpay_subscription_id,
            "razorpay_payment_id": razorpay_payment_id,
            "updated_at": start.isoformat(),
        }
        _MEMORY_SUBSCRIPTIONS[user_sub] = row
        if is_supabase_configured():
            self._supabase_insert("pricing_subscriptions", row, upsert_on="render_user_id")
        return row

    def get_subscription(self, *, user_sub: str) -> dict | None:
        return _MEMORY_SUBSCRIPTIONS.get(user_sub)

    # ─────────────────── payment_events / idempotency ───────────────────

    def event_already_processed(self, *, event_id: str) -> bool:
        if event_id in _MEMORY_EVENTS:
            return True
        if is_supabase_configured():
            try:
                from website.core.persist import get_supabase_scope

                scoped = get_supabase_scope()
                if not scoped:
                    return False
                repo, _ = scoped
                response = (
                    repo._client.table("pricing_payment_events")
                    .select("event_id")
                    .eq("event_id", event_id)
                    .limit(1)
                    .execute()
                )
                if response.data:
                    _MEMORY_EVENTS[event_id] = {"event_id": event_id}
                    return True
            except Exception as exc:
                logger.warning("Event idempotency check failed for %s: %s", event_id, exc)
        return False

    def record_event(self, *, event_id: str, event_type: str, payment_id: str | None, payload: dict) -> dict:
        row = {
            "event_id": event_id,
            "event_type": event_type,
            "payment_id": payment_id,
            "payload": payload,
            "created_at": _now_iso(),
        }
        _MEMORY_EVENTS[event_id] = row
        if is_supabase_configured():
            self._supabase_insert("pricing_payment_events", row)
        return row

    # ─────────────────────── supabase helpers ───────────────────────

    def _supabase_insert(self, table: str, row: dict, *, upsert_on: str | None = None) -> None:
        try:
            from website.core.persist import get_supabase_scope

            scoped = get_supabase_scope()
            if not scoped:
                return
            repo, _ = scoped
            if upsert_on:
                repo._client.table(table).upsert(row, on_conflict=upsert_on).execute()
            else:
                repo._client.table(table).insert(row).execute()
        except Exception as exc:
            logger.warning("Supabase insert into %s failed: %s", table, exc)

    def _supabase_update(self, table: str, row: dict, *, where: tuple[str, str]) -> None:
        try:
            from website.core.persist import get_supabase_scope

            scoped = get_supabase_scope()
            if not scoped:
                return
            repo, _ = scoped
            col, value = where
            repo._client.table(table).update(row).eq(col, value).execute()
        except Exception as exc:
            logger.warning("Supabase update on %s failed: %s", table, exc)


def get_pricing_repository() -> PricingRepository:
    return PricingRepository()


def reset_memory_state_for_tests() -> None:
    """Test hook — clears in-memory state between tests."""
    _MEMORY_PROFILES.clear()
    _MEMORY_PAYMENTS.clear()
    _MEMORY_BALANCES.clear()
    _MEMORY_SUBSCRIPTIONS.clear()
    _MEMORY_EVENTS.clear()
