"""Unit tests for ops/scripts/provision_naruto_packs.py.

No live DB / no network. Verifies the script:
  * uses ONLY the real product ids zettel_20 + kasten_5;
  * reaches billing.pricing_add_pack_credits ONLY via the webhook handler
    (static AST guard: the script never calls add_pack_credits /
    pricing_add_pack_credits / pricing_balances writes directly);
  * --dry-run performs ZERO writes and ZERO POSTs;
  * is idempotent (deterministic event id => handler dedup, no double credit);
  * its locally-signed body verifies under the REAL verify_webhook_signature.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import ops.scripts.provision_naruto_packs as prov

SCRIPT_PATH = Path(prov.__file__)


# ─────────────────────── static / authority guards ───────────────────────


def test_only_real_product_ids():
    assert prov.TARGET_PRODUCT_IDS == ("zettel_20", "kasten_5")
    from website.features.user_pricing.catalog import find_product

    for pid in prov.TARGET_PRODUCT_IDS:
        product = find_product(pid)
        assert product is not None and product["kind"] == "pack"
        assert product["meter"] in {"zettel", "kasten"}
        assert int(product["quantity"]) > 0


def test_resolve_product_rejects_unknown_id():
    with pytest.raises(SystemExit):
        prov._resolve_product("zettel_999")


def test_no_forbidden_direct_pricing_write_in_source():
    """AST/static guard: the script must NOT directly call add_pack_credits,
    pricing_add_pack_credits, or write pricing_balances/usage_counters/
    subscriptions. The ONLY sanctioned path is the webhook handler chain.
    """
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Collect docstring node ids so explanatory prose (which legitimately
    # names the forbidden tables to document the prohibition) is excluded
    # from the executable-string scan.
    docstring_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(
                    first.value, ast.Constant
                ):
                    docstring_ids.add(id(first.value))

    called_attrs: set[str] = set()
    exec_strings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attrs.add(node.func.attr)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ):
            exec_strings.add(node.value)

    assert "add_pack_credits" not in called_attrs
    assert "pricing_add_pack_credits" not in called_attrs
    assert "deduct_pack_credits" not in called_attrs

    forbidden_tables = (
        "pricing_balances",
        "pricing_usage_counters",
        "pricing_subscriptions",
    )
    for s in exec_strings:
        for tbl in forbidden_tables:
            assert tbl not in s, f"forbidden table reference {tbl!r} in {s!r}"
        assert "pricing_add_pack_credits" not in s
    # The only billing RPC string allowed is the read-only quota snapshot.
    assert any(
        "pricing_get_quota_snapshot" in s for s in exec_strings
    ), "expected the read-only verification RPC reference"


# ─────────────────────────── behavioural ───────────────────────────


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "unit-test-webhook-secret")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_unit")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "unit-secret")
    from website.features.user_pricing import razorpay_client

    razorpay_client.reset_client_cache()
    yield
    razorpay_client.reset_client_cache()


def test_signed_body_verifies_under_real_verifier(env, monkeypatch):
    """The body the script signs must validate under the production
    verify_webhook_signature (same HMAC scheme)."""
    monkeypatch.setattr(prov, "_load_env_file", lambda _p: 0)

    captured: dict = {}

    class _FakeRepo:
        def create_payment_record(self, **kw):
            return {"payment_id": f"zk_pack_{kw['product_id']}", **kw}

        def attach_provider_order(self, *, payment_id, razorpay_order_id):
            return {"payment_id": payment_id}

    from website.features.user_pricing import repository as repo_mod

    monkeypatch.setattr(
        repo_mod, "get_pricing_repository", lambda: _FakeRepo()
    )

    class _FakeClient:
        def __init__(self, app):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, path, *, content, headers):
            from website.features.user_pricing.razorpay_client import (
                verify_webhook_signature,
            )

            sig = headers["X-Razorpay-Signature"]
            captured["verified"] = verify_webhook_signature(
                body=content, signature=sig
            )
            captured["path"] = path

            class _R:
                status_code = 200

                @staticmethod
                def json():
                    return {"status": "ok"}

            return _R()

    monkeypatch.setattr(
        "fastapi.testclient.TestClient", _FakeClient
    )
    monkeypatch.setattr(
        prov, "_quota_snapshot", lambda *a, **k: {"remaining_wallet": 20}
    )

    rc = prov.provision(dry_run=False)
    assert rc == 0
    assert captured["verified"] is True
    assert captured["path"] == "/api/payments/webhook"


def test_dry_run_zero_writes_zero_post(env, monkeypatch, capsys):
    """--dry-run: orders/events built + printed, but NO repo writes and NO
    HTTP POST."""
    monkeypatch.setattr(prov, "_load_env_file", lambda _p: 0)

    writes: list[str] = []
    posts: list[str] = []

    class _SpyRepo:
        def create_payment_record(self, **kw):
            return {"payment_id": f"zk_pack_{kw['product_id']}", **kw}

        def attach_provider_order(self, *, payment_id, razorpay_order_id):
            return {"payment_id": payment_id}

        def add_pack_credits(self, **kw):  # must never be called
            writes.append("add_pack_credits")

    from website.features.user_pricing import repository as repo_mod

    monkeypatch.setattr(
        repo_mod, "get_pricing_repository", lambda: _SpyRepo()
    )

    def _boom_client(*a, **k):
        posts.append("post")
        raise AssertionError("dry-run must not construct a TestClient/POST")

    monkeypatch.setattr("fastapi.testclient.TestClient", _boom_client)

    rc = prov.provision(dry_run=True)
    assert rc == 0
    assert writes == []
    assert posts == []
    out = capsys.readouterr().out
    assert "DRY RUN COMPLETE" in out
    assert out.count("WOULD POST") == 2


def test_idempotent_event_id_is_deterministic():
    """Re-running with the same payment_id yields the same event id, so the
    handler's event_already_processed dedup prevents a double grant."""
    product = {"id": "zettel_20", "meter": "zettel", "quantity": 20, "amount": 16900}
    payment = {
        "payment_id": "zk_pack_fixed",
        "razorpay_order_id": "order_fixed",
    }
    e1 = prov._build_event(payment, product)
    e2 = prov._build_event(payment, product)
    assert e1["id"] == e2["id"] == "evt_prov_zk_pack_fixed"
    assert e1["event"] == "payment.captured"
    notes = e1["payload"]["payment"]["entity"]["notes"]
    assert notes["payment_id"] == "zk_pack_fixed"
    assert notes["meter"] == "zettel"
    assert notes["quantity"] == "20"


def test_script_module_imports_clean():
    importlib.reload(prov)
    assert hasattr(prov, "main")
    assert hasattr(prov, "provision")
