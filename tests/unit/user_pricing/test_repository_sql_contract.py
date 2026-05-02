from __future__ import annotations

from pathlib import Path


def test_user_pricing_migration_defines_required_tables_and_rpcs() -> None:
    sql = Path("supabase/website/kg_public/migrations/2026-05-01_user_pricing.sql").read_text(encoding="utf-8")

    for name in [
        "pricing_billing_profiles",
        "pricing_orders",
        "pricing_subscriptions",
        "pricing_webhook_events",
        "pricing_credit_ledger",
        "pricing_usage_counters",
        "pricing_check_entitlement",
        "pricing_consume_entitlement",
    ]:
        assert name in sql

    assert "unique" in sql.lower()
    assert "for update" in sql.lower()

