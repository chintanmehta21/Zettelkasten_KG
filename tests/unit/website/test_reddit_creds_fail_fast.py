"""Fail-fast Reddit credentials gate (P8 carryover).

When WEBHOOK_SECRET is set AND Reddit OAuth credentials are missing, startup
must raise RuntimeError. An explicit opt-out (REDDIT_OPTIONAL=1) reverts to
the legacy warning-only behavior for webhook deployments that do not
capture Reddit.
"""
from __future__ import annotations

import pytest

import website.core.settings as settings_module
from website.core.settings import Settings, validate_reddit_credentials


@pytest.fixture(autouse=True)
def _reset_warning_latch(monkeypatch):
    """Each test starts with the warning latch cleared and REDDIT_OPTIONAL unset."""
    settings_module._reddit_warning_emitted = False
    monkeypatch.delenv("REDDIT_OPTIONAL", raising=False)
    yield
    settings_module._reddit_warning_emitted = False


def _s(**overrides) -> Settings:
    base = dict(
        reddit_client_id="",
        reddit_client_secret="",
        webhook_mode=False,
        webhook_secret="",
    )
    base.update(overrides)
    return Settings(**base)


def test_missing_reddit_creds_with_webhook_secret_raises():
    with pytest.raises(RuntimeError, match="Reddit OAuth"):
        validate_reddit_credentials(_s(webhook_secret="abc123"))


def test_opt_out_env_var_suppresses_raise(monkeypatch):
    monkeypatch.setenv("REDDIT_OPTIONAL", "1")
    # Should not raise even though creds are missing + webhook_secret set.
    validate_reddit_credentials(_s(webhook_secret="abc123"))


def test_with_reddit_creds_no_raise_no_warning():
    # Full creds bypass the gate entirely.
    validate_reddit_credentials(
        _s(
            webhook_secret="abc123",
            reddit_client_id="id",
            reddit_client_secret="secret",
        )
    )


def test_polling_mode_no_raise_no_warning_without_creds():
    # No webhook_secret, no webhook_mode → silent (dev mode).
    validate_reddit_credentials(_s())


def test_webhook_mode_without_secret_still_warns_not_raises(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    validate_reddit_credentials(_s(webhook_mode=True))
    assert any("Reddit OAuth" in r.getMessage() for r in caplog.records)
