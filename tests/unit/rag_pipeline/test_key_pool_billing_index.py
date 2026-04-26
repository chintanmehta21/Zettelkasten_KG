"""Bug 5 regression: env-var-driven billing-key escalation in GeminiKeyPool.

Iter-06 spec §11: free keys must be exhausted (within an iter / process-life)
before the billing-tier key is promoted. The existing pool already deferred
keys whose role token explicitly equals "billing" (parsed from api_env).
This test asserts the env-var override RAG_BILLING_KEY_INDEX so an unmarked
api_env file can still tag a specific index as billing-tier without editing
the file in place.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from website.features.api_key_switching.key_pool import GeminiKeyPool


def test_billing_index_env_overrides_role_to_billing(monkeypatch):
    """Setting RAG_BILLING_KEY_INDEX=2 must demote that key to billing-tier
    so it is only chosen after free-tier keys."""
    monkeypatch.setenv("RAG_BILLING_KEY_INDEX", "2")

    pool = GeminiKeyPool(["k0", "k1", "k2"])
    # All three keys default to free, but the env override marks index 2 as billing.
    assert pool._role_for_key(0) == "free"
    assert pool._role_for_key(1) == "free"
    assert pool._role_for_key(2) == "billing"

    # The attempt chain must list both free keys before the billing key.
    chain = pool._build_attempt_chain(starting_model="gemini-2.5-flash")
    # Filter to the first model only for ordering check.
    first_model = chain[0][1]
    first_model_slots = [(ki, m) for ki, m in chain if m == first_model]
    key_order = [ki for ki, _ in first_model_slots]
    # Free keys (0,1) come before billing (2).
    assert key_order.index(2) > key_order.index(0)
    assert key_order.index(2) > key_order.index(1)


def test_billing_index_skipped_after_both_free_on_cooldown(monkeypatch):
    """When both free keys are on cooldown for the requested model, the next
    attempt resolves to the billing key — escalation under quota pressure."""
    monkeypatch.setenv("RAG_BILLING_KEY_INDEX", "2")

    pool = GeminiKeyPool(["k0", "k1", "k2"])
    pool._mark_cooldown(0, "gemini-2.5-flash")
    pool._mark_cooldown(1, "gemini-2.5-flash")

    attempt = pool.next_attempt("gemini-2.5-flash")
    # First non-cooldown slot for gemini-2.5-flash should now be key 2 (billing).
    assert attempt.key == "k2"
    assert attempt.role == "billing"


def test_no_env_var_preserves_existing_behavior(monkeypatch):
    """Without the env var, all keys default to free — backward compatible."""
    monkeypatch.delenv("RAG_BILLING_KEY_INDEX", raising=False)

    pool = GeminiKeyPool(["k0", "k1", "k2"])
    for i in range(3):
        assert pool._role_for_key(i) == "free"


def test_explicit_role_in_api_env_takes_precedence(monkeypatch):
    """If api_env already supplied role tokens, the env override must NOT
    silently overwrite them — the explicit caller intent wins."""
    monkeypatch.setenv("RAG_BILLING_KEY_INDEX", "0")

    # k0 explicitly free, k2 explicitly billing already.
    pool = GeminiKeyPool([("k0", "free"), ("k1", "free"), ("k2", "billing")])
    # Explicit free at index 0 must remain free; the env override is a tag-by-default
    # mechanism for unmarked keys, not an override of explicit roles.
    # After normalize_api_keys sorts free first: [(k0,free),(k1,free),(k2,billing)]
    assert pool._role_for_key(0) == "free"
    assert pool._role_for_key(2) == "billing"
