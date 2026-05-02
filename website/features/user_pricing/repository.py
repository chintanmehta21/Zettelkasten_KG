"""Persistence facade for pricing state.

The concrete production schema is provided by the Supabase migration. This
facade stays intentionally small so route code can be tested without a live
database and without leaking provider details into API handlers.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from website.core.supabase_kg.client import is_supabase_configured
from website.features.user_pricing.models import Meter

logger = logging.getLogger(__name__)

_MEMORY_PROFILES: dict[str, dict] = {}
_MEMORY_PAYMENTS: dict[str, dict] = {}


class PricingRepository:
    """Supabase-backed pricing repository.

    Until the migration is applied in a target environment, entitlement checks
    allow requests rather than breaking existing development/public flows.
    Production enforcement is activated by the SQL RPCs and service-role env.
    """

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

    def get_billing_profile(self, *, user_sub: str) -> dict | None:
        if not is_supabase_configured():
            return _MEMORY_PROFILES.get(user_sub)

        try:
            from website.core.persist import get_supabase_scope

            scoped = get_supabase_scope(user_id_override=user_sub)
            if not scoped:
                return None
            repo, _kg_user_id = scoped
            response = repo._client.table("pricing_billing_profiles").select("*").eq("render_user_id", user_sub).limit(1).execute()
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
            "updated_at": datetime.now(UTC).isoformat(),
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
            response = repo._client.table("pricing_billing_profiles").upsert(row, on_conflict="render_user_id").execute()
            return response.data[0] if response.data else row
        except Exception as exc:
            logger.warning("Billing profile upsert failed for user=%s: %s", user_sub, exc)
            _MEMORY_PROFILES[user_sub] = row
            return row

    def create_payment_record(self, *, user_sub: str, product_id: str, kind: str, amount: int, currency: str) -> dict:
        payment_id = f"zk_{kind}_{uuid4().hex}"
        row = {
            "payment_id": payment_id,
            "render_user_id": user_sub,
            "product_id": product_id,
            "kind": kind,
            "amount": amount,
            "currency": currency,
            "status": "created",
            "created_at": datetime.now(UTC).isoformat(),
        }
        _MEMORY_PAYMENTS[payment_id] = row
        return row

    def update_payment_provider_response(self, *, payment_id: str, provider_payload: dict) -> dict:
        row = _MEMORY_PAYMENTS.setdefault(payment_id, {"payment_id": payment_id})
        row["provider_payload"] = provider_payload
        row["status"] = provider_payload.get("order_status") or provider_payload.get("subscription_status") or row.get("status", "created")
        row["updated_at"] = datetime.now(UTC).isoformat()
        return row

    def get_payment_record(self, *, payment_id: str) -> dict | None:
        return _MEMORY_PAYMENTS.get(payment_id)


def get_pricing_repository() -> PricingRepository:
    return PricingRepository()
