"""Operator-driven pack provisioning for ANY user via the LEGITIMATE
purchase-fulfillment path ONLY.

Generalised sibling of ``provision_naruto_packs.py``. Same hard rules: this is
a PURCHASE, not a seed. It synthesizes a real ``billing.pricing_orders`` row
through the same ``PricingRepository`` the ``POST /api/payments/orders`` route
uses, then drives a locally-signed Razorpay ``payment.captured`` webhook
through the in-process FastAPI app so the genuine pipeline runs end to end:

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
  * Product ids are read from website.features.user_pricing.catalog (sourced
    from config.PRICING_CONFIG); only catalogued ``pack`` kind products
    resolve. Inventing plan names / SKUs is impossible — find_product()
    returns None for anything not in PRICING_CONFIG (or its custom_*_N form).
  * Non-dry runs require BOTH --confirm-prod AND the operator passing the
    target user-sub explicitly. No defaults, no env-derived users.

Operator usage (PowerShell or Git Bash):

    cd C:\\Users\\LENOVO\\Documents\\Claude_Code\\Projects\\Obsidian_Vault\\.claude\\worktrees\\busy-brattain-bd117b
    python ops/scripts/provision_pack.py --user-sub <uuid> --pack zettel_10 --dry-run
    python ops/scripts/provision_pack.py --user-sub <uuid> --pack zettel_10 --confirm-prod
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import uuid
from pathlib import Path

# Primary env (Supabase v2 DSN, Gemini, etc.) loads first; razorpay_test
# overlays the three RAZORPAY_* keys without clobbering anything already set.
ENV_PATHS: tuple[Path, ...] = (
    Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.env"),
    Path(
        r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.env.razorpay_test"
    ),
)

WEBHOOK_PATH = "/api/payments/webhook"

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


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

    Unlike ``provision_naruto_packs.py``, this script does NOT pin to a
    Naruto-specific allowlist — any catalogued pack (including the custom_*_N
    slider form) is acceptable. Inventing SKUs is still impossible: products
    not in PRICING_CONFIG return None and we hard-fail.
    """
    from website.features.user_pricing.catalog import find_product

    product = find_product(product_id)
    if not product:
        raise SystemExit(
            f"FATAL: product id {product_id!r} not in catalog (no inventing SKUs)"
        )
    if product.get("kind") != "pack":
        raise SystemExit(
            f"FATAL: product {product_id!r} is not a pack (subscriptions go through "
            "the real Razorpay checkout, not this script)"
        )
    if not product.get("meter") or not int(product.get("quantity") or 0):
        raise SystemExit(
            f"FATAL: product {product_id!r} missing meter/quantity"
        )
    return product


# ──────────────── order synth + signed webhook event ────────────────


def _create_order(repo, *, user_sub: str, product: dict) -> dict:
    """Create a REAL pricing_orders record via the repository, mirroring the
    exact sequence POST /api/payments/orders performs (routes.py:147-174):
    create_payment_record -> attach_provider_order. Returns the in-memory
    payment row whose ``payment_id`` the webhook's notes link to.
    """
    payment = repo.create_payment_record(
        user_sub=user_sub,
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


def _build_event(payment: dict, *, user_sub: str, product: dict) -> dict:
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
                        "render_user_id": user_sub,
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
    confirm post-grant wallet credits. Caps + wallet meter come from the
    operator-editable functional_gates.config (never DB-sourced).
    """
    import asyncio

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

    return asyncio.run(_run())


# ───────────────────────────── driver ─────────────────────────────


def provision(*, user_sub: str, pack: str, dry_run: bool) -> int:
    if not _UUID_RE.match(user_sub):
        raise SystemExit(
            f"FATAL: --user-sub must be a UUID; got {user_sub!r}"
        )

    total_loaded = 0
    for env_path in ENV_PATHS:
        n = _load_env_file(env_path)
        total_loaded += n
        print(f"[env] loaded {n} key(s) from {env_path.name} (values not shown)")
    print(f"[env] total {total_loaded} key(s) loaded across {len(ENV_PATHS)} files")
    print(f"[target] user_sub={user_sub} pack={pack} dry_run={dry_run}")

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

    product = _resolve_product(pack)
    print(
        f"[catalog] product={product['id']} meter={product['meter']} "
        f"quantity={product['quantity']} amount_paise={int(product['amount'])}"
    )

    payment = _create_order(repo, user_sub=user_sub, product=product)
    event = _build_event(payment, user_sub=user_sub, product=product)
    body = json.dumps(event).encode("utf-8")
    signature = _sign(body)

    # Self-check: the body we POST must verify under the REAL verifier.
    assert verify_webhook_signature(
        body=body, signature=signature
    ), "FATAL: locally-signed body fails verify_webhook_signature"

    result = {
        "user_sub": user_sub,
        "product_id": product["id"],
        "payment_id": payment["payment_id"],
        "razorpay_order_id": payment["razorpay_order_id"],
        "event_id": event["id"],
        "amount_paise": int(product["amount"]),
        "meter": product["meter"],
        "quantity": int(product["quantity"]),
    }

    if dry_run:
        print(
            f"[dry-run] WOULD POST {WEBHOOK_PATH} product={product['id']} "
            f"payment_id={payment['payment_id']} "
            f"order={payment['razorpay_order_id']} "
            f"event_id={event['id']} (the create_payment_record + "
            f"attach_provider_order calls above ARE writes — see warning)"
        )
        print("\n=== DRY RUN COMPLETE — webhook NOT posted ===")
        print(json.dumps(result, indent=2))
        print(
            "\n[warn] NOTE: dry-run still wrote a pricing_orders row via "
            "create_payment_record + attach_provider_order (mirrors the real "
            "POST /api/payments/orders sequence). The wallet credit has NOT "
            "been applied — that only happens when the webhook is posted."
        )
        return 0

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
    result["webhook_status"] = status
    result["webhook_result"] = payload
    print(f"[post] {product['id']}: HTTP {status} -> {json.dumps(payload)}")

    # Verification: real read-only quota snapshot for the granted meter.
    print("\n=== VERIFICATION (billing.pricing_get_quota_snapshot) ===")
    try:
        snap = _quota_snapshot(user_sub, product["meter"])
        rem = snap.get("remaining_wallet") if isinstance(snap, dict) else None
        print(f"[verify] {product['meter']}: remaining_wallet={rem}")
    except Exception as exc:  # noqa: BLE001 — verification is best-effort
        print(f"[verify] {product['meter']}: snapshot failed: {exc}")

    print("\n=== SUMMARY ===")
    print(json.dumps(result, indent=2))
    return 0 if status < 400 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Provision a single catalogued pack for a specific user via the "
            "real purchase-fulfillment webhook path. Generalised operator "
            "tool — any catalogued pack id is accepted. No SKU invention."
        )
    )
    parser.add_argument(
        "--user-sub",
        required=True,
        help="Target user sub (Supabase auth subject == billing profile_id). "
        "Must be a UUID.",
    )
    parser.add_argument(
        "--pack",
        required=True,
        help=(
            "Catalogued pack id (e.g. zettel_1, zettel_5, zettel_10, "
            "zettel_20, kasten_5, questions_50, ...). Must resolve via "
            "website.features.user_pricing.catalog.find_product()."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the order + signed event and print what WOULD post; "
        "the webhook itself is NOT posted (no wallet credit applied). "
        "Note: this still writes a pricing_orders row via the same path "
        "POST /api/payments/orders uses.",
    )
    parser.add_argument(
        "--confirm-prod",
        action="store_true",
        help="REQUIRED for non-dry runs. Acknowledges that this script will "
        "post a synthesized payment.captured webhook to the in-process app, "
        "creating a real billing.pricing_orders row + applying wallet "
        "credit on the v2 Supabase DB the local .env points at.",
    )
    args = parser.parse_args(argv)

    if not args.dry_run and not args.confirm_prod:
        raise SystemExit(
            "FATAL: non-dry run requires --confirm-prod. Re-run with "
            "--dry-run first, inspect the output, then re-run with "
            "--confirm-prod."
        )

    return provision(
        user_sub=args.user_sub, pack=args.pack, dry_run=args.dry_run
    )


if __name__ == "__main__":
    sys.exit(main())
