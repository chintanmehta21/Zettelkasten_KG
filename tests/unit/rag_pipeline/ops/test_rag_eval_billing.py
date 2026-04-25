from pathlib import Path

from ops.scripts.lib.rag_eval_billing import (
    BillingTier,
    escalate_on_429,
    write_halt,
    is_halted,
)


def test_escalate_from_free_to_billing():
    state = BillingTier.FREE
    new = escalate_on_429(state, free_keys_exhausted=True)
    assert new == BillingTier.BILLING


def test_escalate_billing_exhaustion_halts(tmp_path):
    state = BillingTier.BILLING
    new = escalate_on_429(state, free_keys_exhausted=True, billing_exhausted=True)
    assert new == BillingTier.HALTED


def test_write_halt_creates_sentinel(tmp_path):
    write_halt(tmp_path / ".halt", reason="quota exhausted")
    assert (tmp_path / ".halt").exists()
    assert is_halted(tmp_path / ".halt")
