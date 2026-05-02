"""Public pricing catalog derived from the editable config."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import math
import re
from typing import Any

from website.features.user_pricing.config import PRICING_CONFIG

_CUSTOM_PRODUCT_RE = re.compile(r"^custom_(zettel|kasten|question)_(\d+)$")


def format_amount(amount_paise: int, currency: str = "INR") -> str:
    if currency == "INR":
        rupees = amount_paise // 100
        paise = amount_paise % 100
        if paise:
            return f"₹{rupees}.{paise:02d}"
        return f"₹{rupees}"
    major = amount_paise / 100
    return f"{currency} {major:.2f}"


def active_amount(item: dict[str, Any], *, launch_enabled: bool) -> int:
    if launch_enabled:
        return int(item.get("launch_amount", item["list_amount"]))
    return int(item["list_amount"])


def _with_money_fields(item: dict[str, Any], currency: str, launch_enabled: bool) -> dict[str, Any]:
    out = deepcopy(item)
    out["amount"] = active_amount(out, launch_enabled=launch_enabled)
    out["display_amount"] = format_amount(out["amount"], currency)
    out["display_list_amount"] = format_amount(int(out["list_amount"]), currency)
    out["display_launch_amount"] = format_amount(int(out["launch_amount"]), currency)
    return out


@lru_cache(maxsize=1)
def get_public_catalog() -> dict[str, Any]:
    config = deepcopy(PRICING_CONFIG)
    currency = config["currency"]
    launch_enabled = bool(config["launch_pricing_enabled"])

    plans: dict[str, Any] = {}
    for plan_id, plan in config["plans"].items():
        public_plan = deepcopy(plan)
        public_plan["periods"] = {
            period_id: _with_money_fields(period, currency, launch_enabled)
            for period_id, period in plan["periods"].items()
        }
        plans[plan_id] = public_plan

    packs = {
        group: [_with_money_fields(pack, currency, launch_enabled) for pack in group_packs]
        for group, group_packs in config["packs"].items()
    }

    return {
        "currency": currency,
        "launch_pricing_enabled": launch_enabled,
        "meters": deepcopy(config["meters"]),
        "plans": plans,
        "packs": packs,
        "custom_slider_values": deepcopy(config["custom_slider_values"]),
        "recommendations": deepcopy(config["recommendations"]),
    }


def find_product(product_id: str) -> dict[str, Any] | None:
    catalog = get_public_catalog()
    for plan in catalog["plans"].values():
        for period in plan["periods"].values():
            if period["id"] == product_id:
                return {"kind": "subscription", "plan_id": plan["id"], **period}
    for packs in catalog["packs"].values():
        for pack in packs:
            if pack["id"] == product_id:
                return {"kind": "pack", **pack}
    custom_match = _CUSTOM_PRODUCT_RE.match(product_id)
    if custom_match:
        return _generated_custom_pack(catalog, custom_match.group(1), int(custom_match.group(2)))
    return None


def _generated_custom_pack(catalog: dict[str, Any], group: str, quantity: int) -> dict[str, Any] | None:
    values = catalog["custom_slider_values"].get(group)
    packs = catalog["packs"].get(group)
    if not values or not packs:
        return None

    normalized = _normalize_custom_quantity(group, quantity)
    if normalized <= values[-1]:
        return next(({"kind": "pack", **pack} for pack in packs if pack["quantity"] == normalized), None)

    base_pack = next((pack for pack in packs if pack["quantity"] == values[-1]), None)
    if not base_pack:
        return None

    amount = _extend_amount(base_pack["amount"], base_pack["quantity"], normalized)
    list_amount = _extend_amount(base_pack["list_amount"], base_pack["quantity"], normalized)
    meter = "rag_question" if group == "question" else group
    label = "Questions" if group == "question" else ("Zettels" if group == "zettel" else "Kastens")
    return {
        "kind": "pack",
        "id": f"custom_{group}_{normalized}",
        "meter": meter,
        "name": f"{normalized} {label}",
        "quantity": normalized,
        "list_amount": list_amount,
        "launch_amount": amount,
        "amount": amount,
        "display_amount": format_amount(amount, catalog["currency"]),
        "display_list_amount": format_amount(list_amount, catalog["currency"]),
        "display_launch_amount": format_amount(amount, catalog["currency"]),
    }


def _normalize_custom_quantity(group: str, quantity: int) -> int:
    quantity = max(1, int(quantity))
    if group == "question":
        return max(50, math.ceil(quantity / 50) * 50)
    if quantity <= 1:
        return 1
    if quantity <= 5:
        return 5
    return math.ceil(quantity / 10) * 10


def _extend_amount(base_amount: int, base_quantity: int, quantity: int) -> int:
    return math.ceil((quantity * base_amount / base_quantity) / 100) * 100
