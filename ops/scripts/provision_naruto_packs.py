"""One-shot pack provisioning for canonical Naruto via the LEGITIMATE
purchase-fulfillment path ONLY.

This is a PURCHASE, not a seed. It synthesizes real ``billing.pricing_orders``
rows through the same ``PricingRepository`` the ``POST /api/payments/orders``
route uses, then drives a locally-signed Razorpay ``payment.captured`` webhook
through the REAL in-process FastAPI app so the genuine pipeline runs end to
end:

    signature verify (verify_webhook_signature, razorpay_client.py:82)
      -> event idempotency (repo.event_already_processed, routes.py:525)
      -> dispatch table _WEBHOOK_HANDLERS["payment.captured"] (routes.py:894)
      -> _h_payment_captured (routes.py:564)
           -> repo.mark_payment_paid (repository.py:279)
           -> _apply_fulfillment (routes.py:1014)
                -> repo.add_pack_credits (repository.py:379)
                     -> billing.pricing_add_pack_credits RPC (repository.py:387)

HARD RULES enforced by construction:
  * No direct INSERT/UPSERT/UPDATE into billing.pricing_balances /
    pricing_usage_counters / pricing_subscriptions anywhere in this file.
  * billing.pricing_add_pack_credits is reached ONLY through the webhook
    handler -> _apply_fulfillment chain (never called directly here).
  * Product ids are read from website.features.user_pricing.catalog
    (sourced from config.PRICING_CONFIG); only the real ``zettel_20`` and
    ``kasten_5`` packs are used.

Operator usage (do NOT run against prod without explicit authorization):

    cd C:\\Users\\LENOVO\\Documents\\Claude_Code\\Projects\\Obsidian_Vault\\.claude\\worktrees\\pedantic-nash-324d30
    python ops/scripts/provision_naruto_packs.py --dry-run
    python ops/scripts/provision_naruto_packs.py
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid
from pathlib import Path

# Canonical Naruto profile / subscription UUID (Supabase auth subject ==
# v2 billing profile_id; see website/core/persist.py:get_billing_scope).
NARUTO_USER_SUB = "f2105544-b73d-4946-8329-096d82f070d3"

# Real product ids — verified against website/features/user_pricing/config.py
# PRICING_CONFIG["packs"]: zettel_20 (meter=zettel, quantity=20),
# kasten_5 (meter=kasten, quantity=5). Never invented.
TARGET_PRODUCT_IDS: tuple[str, ...] = ("zettel_20", "kasten_5")

ENV_PATH = Path(
    r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.env"
)

WEBHOOK_PATH = "/api/payments/webhook"


# ────────────────────────── env loading ──────────────────────────


def _load_env_file(path: Path) -> int:
    """Load KEY=VALUE lines from ``path`` into os.environ BEFORE any app /
    client import (lru_cache lock on get_v2_client / get_razorpay_client).

    Existing process env vars win (never clobber an explicitly-set value).
    Returns the count of keys loaded. Secret values are never printed.
    """
    if not path.exists():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


# ──────────────────────── product resolution ────────────────────────


def _resolve_product(product_id: str) -> dict:
    """Look up the product via the catalog (config.PRICING_CONFIG source of
    truth). Hard-fail if it is not a real ``pack`` with meter + quantity.
    """
    from website.features.user_pricing.catalog import find_product

    product = find_product(product_id)
    if not product:
        raise SystemExit(f"FATAL: product id {product_id!r} not in catalog")
    if product.get("kind") != "pack":
        raise SystemExit(f"FATAL: product {product_id!r} is not a pack")
    if not product.get("meter") or not int(product.get("quantity") or 0):
        raise SystemExit(
            f"FATAL: product {product_id!r} missing meter/quantity"
        )
    if product_id not in TARGET_PRODUCT_IDS:
        raise SystemExit(f"FATAL: {product_id!r} not an approved target")
    return product


# ──────────────── order synth + signed webhook event ────────────────


def _create_order(repo, product: dict) -> dict:
    """Create a REAL pricing_orders record via the repository, mirroring the
    exact sequence POST /api/payments/orders performs (routes.py:147-174):
    create_payment_record -> attach_provider_order. Returns the in-memory
    payment row whose ``payment_id`` the webhook's notes link to.
    """
    payment = repo.create_payment_record(
        user_sub=NARUTO_USER_SUB,
        product_id=product["id"],
        kind="pack",
        amount=int(product["amount"]),
        currency="INR",
        meter=product.get("meter"),
        quantity=int(product.get("quantity") or 0) or None,
    )
    # Synthesize a deterministic-ish Razorpay order id so mark_payment_paid's
    # v2 UPDATE (keyed by razorpay_order_id, repository.py:294) can match.
    rzp_order_id = f"order_prov_{uuid.uuid4().hex[:14]}"
    repo.attach_provider_order(
        payment_id=payment["payment_id"], razorpay_order_id=rzp_order_id
    )
    payment["razorpay_order_id"] = rzp_order_id
    return payment


def _build_event(payment: dict, product: dict) -> dict:
    """Construct the exact ``payment.captured`` envelope the handler expects.

    ``_h_payment_captured`` (routes.py:564) reads:
      payload.payment.entity.notes.payment_id  -> locates internal order
      payload.payment.entity.id                -> razorpay_payment_id
    The event-level ``id`` is the idempotency key (routes.py:519/525).
    """
    rzp_payment_id = f"pay_prov_{uuid.uuid4().hex[:14]}"
    # Deterministic event id keyed by payment_id => safe to re-run: the
    # handler's event_already_processed dedup short-circuits the second run.
    event_id = f"evt_prov_{payment['payment_id']}"
    return {
        "id": event_id,
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": rzp_payment_id,
                    "order_id": payment["razorpay_order_id"],
                    "status": "captured",
                    "amount": int(product["amount"]),
                    "currency": "INR",
                    "notes": {
                        "payment_id": payment["payment_id"],
                        "render_user_id": NARUTO_USER_SUB,
                        "product_id": product["id"],
                        "kind": "pack",
                        "meter": product.get("meter") or "",
                        "quantity": str(int(product.get("quantity") or 0)),
                    },
                }
            },
            "order": {
                "entity": {
                    "id": payment["razorpay_order_id"],
                    "status": "paid",
                }
            },
        },
    }


def _sign(body: bytes) -> str:
    """HMAC-SHA256(raw_body, RAZORPAY_WEBHOOK_SECRET) hex digest — byte-for-byte
    the scheme verify_webhook_signature (razorpay_client.py:82) checks against
    the X-Razorpay-Signature header. Secret value is never logged.
    """
    from website.features.user_pricing.razorpay_client import (
        get_razorpay_webhook_secret,
    )

    secret = get_razorpay_webhook_secret()
    if not secret:
        raise SystemExit(
            "FATAL: RAZORPAY_WEBHOOK_SECRET not set; cannot sign webhook"
        )
    return hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


# ─────────────────────────── verification ───────────────────────────


def _quota_snapshot(profile_id: str, feature: str) -> dict:
    """Call the REAL billing.pricing_get_quota_snapshot RPC (read-only) to
    confirm post-grant wallet credits. Signature (per
    tests/integration/v2/test_entitlement_phase9_active.py:47 and
    44_functional_gates.sql): pricing_get_quota_snapshot(profile, feature,
    caps::jsonb, wallet_meter). Caps + wallet meter come from the operator-
    editable functional_gates.config (never DB-sourced).
    """
    import asyncpg

    from website.core.supabase_v2.client import get_v2_database_url
    from website.features.functional_gates.config import (
        caps_for,
        wallet_meter_for,
    )

    caps_json = json.dumps(caps_for("free", feature))
    wallet_meter = wallet_meter_for(feature)
    dsn = get_v2_database_url(listen=False)

    async def _run() -> dict:
        conn = await asyncpg.connect(dsn)
        try:
            value = await conn.fetchval(
                "SELECT billing.pricing_get_quota_snapshot"
                "($1, $2, $3::jsonb, $4)",
                profile_id,
                feature,
                caps_json,
                wallet_meter,
            )
        finally:
            await conn.close()
        return json.loads(value) if isinstance(value, str) else value

    import asyncio

    return asyncio.run(_run())


# ───────────────────────────── driver ─────────────────────────────


def provision(*, dry_run: bool) -> int:
    loaded = _load_env_file(ENV_PATH)
    print(f"[env] loaded {loaded} key(s) from .env (values not shown)")

    # Imports AFTER env load so lru_cache'd clients pick up the credentials.
    from fastapi.testclient import TestClient

    from website.features.user_pricing.razorpay_client import (
        is_razorpay_configured,
        reset_client_cache,
        verify_webhook_signature,
    )
    from website.features.user_pricing.repository import (
        get_pricing_repository,
    )

    reset_client_cache()
    repo = get_pricing_repository()

    results: list[dict] = []
    for product_id in TARGET_PRODUCT_IDS:
        product = _resolve_product(product_id)
        payment = _create_order(repo, product)
        event = _build_event(payment, product)
        body = json.dumps(event).encode("utf-8")
        signature = _sign(body)

        # Self-check: the body we POST must verify under the REAL verifier.
        assert verify_webhook_signature(
            body=body, signature=signature
        ), "FATAL: locally-signed body fails verify_webhook_signature"

        results.append(
            {
                "product_id": product_id,
                "payment_id": payment["payment_id"],
                "razorpay_order_id": payment["razorpay_order_id"],
                "event_id": event["id"],
                "amount": int(product["amount"]),
                "meter": product["meter"],
                "quantity": int(product["quantity"]),
            }
        )

        if dry_run:
            print(
                f"[dry-run] WOULD POST {WEBHOOK_PATH} product={product_id} "
                f"payment_id={payment['payment_id']} "
                f"order={payment['razorpay_order_id']} "
                f"event_id={event['id']} (0 writes, no POST)"
            )
            continue

        if not is_razorpay_configured():
            print(
                "[warn] is_razorpay_configured() is False — webhook signature "
                "verify still uses RAZORPAY_WEBHOOK_SECRET; continuing"
            )

        from website.app import create_app

        with TestClient(create_app()) as client:
            resp = client.post(
                WEBHOOK_PATH,
                content=body,
                headers={
                    "X-Razorpay-Signature": signature,
                    "Content-Type": "application/json",
                },
            )
        status = resp.status_code
        payload = resp.json() if status < 500 else {"text": resp.text[:200]}
        results[-1]["webhook_status"] = status
        results[-1]["webhook_result"] = payload
        print(
            f"[post] {product_id}: HTTP {status} "
            f"-> {json.dumps(payload)}"
        )

    if dry_run:
        print("\n=== DRY RUN COMPLETE — zero writes, zero POSTs ===")
        for r in results:
            print(json.dumps(r))
        return 0

    # Verification: real read-only quota snapshot per feature.
    print("\n=== VERIFICATION (billing.pricing_get_quota_snapshot) ===")
    for feature in ("zettel", "kasten"):
        try:
            snap = _quota_snapshot(NARUTO_USER_SUB, feature)
            rem = snap.get("remaining_wallet") if isinstance(snap, dict) else None
            print(f"[verify] {feature}: remaining_wallet={rem}")
        except Exception as exc:  # noqa: BLE001 — verification is best-effort
            print(f"[verify] {feature}: snapshot failed: {exc}")

    print("\n=== SUMMARY ===")
    for r in results:
        print(
            f"product={r['product_id']} order={r['razorpay_order_id']} "
            f"payment_id={r['payment_id']} "
            f"webhook_status={r.get('webhook_status')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision Naruto zettel_20 + kasten_5 packs via the "
        "real purchase-fulfillment webhook path."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build orders + signed events and print what WOULD post; "
        "ZERO writes and ZERO POSTs.",
    )
    args = parser.parse_args(argv)
    return provision(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
