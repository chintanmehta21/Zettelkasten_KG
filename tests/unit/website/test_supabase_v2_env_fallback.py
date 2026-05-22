"""β env-fallback: SUPABASE_V2_* should fall back to canonical SUPABASE_* names.

v1 is dead (2026-05). The SUPABASE_V2_* namespace was only needed for v1→v2
co-existence. In production the canonical SUPABASE_* keys point at v2 already.
"""
from __future__ import annotations

import os
import unittest.mock

import pytest

_ALL_SB_KEYS = [
    "SUPABASE_V2_URL", "SUPABASE_V2_ANON_KEY", "SUPABASE_V2_SERVICE_ROLE_KEY",
    "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY",
]
_BLANK = {k: "" for k in _ALL_SB_KEYS}


def test_is_v2_configured_falls_back_to_canonical_supabase_url():
    """β: SUPABASE_V2_* missing should fall back to SUPABASE_* canonical names."""
    env = {
        **_BLANK,
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "sb_publishable_test",
        "SUPABASE_SERVICE_ROLE_KEY": "eyJtest",
    }
    from website.core.supabase_v2.client import is_v2_configured
    with unittest.mock.patch.dict(os.environ, env, clear=False):
        assert is_v2_configured() is True


def test_is_v2_configured_prefers_v2_when_set():
    """If SUPABASE_V2_URL etc. ARE set, they take priority (back-compat)."""
    env = {
        "SUPABASE_V2_URL": "https://v2.supabase.co",
        "SUPABASE_V2_ANON_KEY": "sb_publishable_v2",
        "SUPABASE_V2_SERVICE_ROLE_KEY": "eyJv2",
        "SUPABASE_URL": "https://canonical.supabase.co",
        "SUPABASE_ANON_KEY": "sb_publishable_canon",
        "SUPABASE_SERVICE_ROLE_KEY": "eyJcanon",
    }
    from website.core.supabase_v2.client import is_v2_configured
    with unittest.mock.patch.dict(os.environ, env, clear=False):
        assert is_v2_configured() is True


def test_is_v2_configured_returns_false_when_neither_set():
    """Neither V2_* nor canonical SUPABASE_* set → False."""
    from website.core.supabase_v2.client import is_v2_configured
    with unittest.mock.patch.dict(os.environ, _BLANK, clear=False):
        assert is_v2_configured() is False


def test_use_supabase_v2_requires_db_schema_version():
    """use_supabase_v2 gates on DB_SCHEMA_VERSION=v2 AND is_v2_configured."""
    env_base = {
        **_BLANK,
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "sb_publishable_test",
        "SUPABASE_SERVICE_ROLE_KEY": "eyJtest",
    }
    from website.core.db_version import use_supabase_v2
    with unittest.mock.patch.dict(os.environ, {**env_base, "DB_SCHEMA_VERSION": "v1"}, clear=False):
        assert use_supabase_v2() is False
    with unittest.mock.patch.dict(os.environ, {**env_base, "DB_SCHEMA_VERSION": "v2"}, clear=False):
        assert use_supabase_v2() is True


@pytest.fixture
def _reset_jwks_cache():
    """Reset auth.py's module-level JWKS client cache around the test.

    ``_get_jwks_client`` memoizes into ``auth_mod._jwks_client``. Reset it both
    before and after so neither this test nor a later one sees a stale client.
    Note: do NOT ``importlib.reload`` the auth module — that rebinds
    ``get_current_user`` to a fresh object and silently breaks FastAPI
    ``dependency_overrides`` (keyed by object identity) in unrelated suites.
    """
    import website.api.auth as auth_mod
    auth_mod._jwks_client = None
    yield auth_mod
    auth_mod._jwks_client = None


def test_auth_jwks_uses_canonical_when_v2_env_missing(monkeypatch, _reset_jwks_cache):
    """auth.py JWKS resolver falls back to SUPABASE_URL when V2_URL not set."""
    monkeypatch.delenv("SUPABASE_V2_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "eyJtest")

    auth_mod = _reset_jwks_cache
    client = auth_mod._get_jwks_client()
    assert client is not None
    assert "example.supabase.co" in client.uri


def test_auth_config_falls_back_to_canonical(monkeypatch):
    """routes.py /auth/config falls back to SUPABASE_* when V2_* not set."""
    monkeypatch.delenv("SUPABASE_V2_URL", raising=False)
    monkeypatch.delenv("SUPABASE_V2_ANON_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "eyJtest")
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")

    import website.api.routes as routes_mod

    import asyncio
    result = asyncio.run(routes_mod.auth_config())
    assert result["supabase_url"] == "https://example.supabase.co"
    assert result["supabase_anon_key"] == "sb_publishable_test"
