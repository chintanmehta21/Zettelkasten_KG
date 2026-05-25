"""Pin the JWKS pre-warm in FastAPI lifespan.

The pre-warm hydrates PyJWKClient's cache so the first JWT validation after
deploy doesn't race against a cold JWKS endpoint fetch. Soft-fail: if JWKS is
unreachable at startup, the app must still come up.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from asgi_lifespan import LifespanManager


@pytest.mark.asyncio
async def test_jwks_prewarm_calls_get_signing_keys_at_startup():
    from website.app import create_app

    mock_client = MagicMock()
    mock_client.get_signing_keys = MagicMock(return_value=[])

    with patch("website.api.auth._get_jwks_client", return_value=mock_client):
        app = create_app()
        async with LifespanManager(app):
            # Lifespan startup has fired
            pass

    assert mock_client.get_signing_keys.call_count >= 1, (
        "expected JWKS pre-warm to call get_signing_keys at least once"
    )


@pytest.mark.asyncio
async def test_jwks_prewarm_soft_fails_on_endpoint_error():
    """If JWKS endpoint raises, startup must still complete."""
    from website.app import create_app

    mock_client = MagicMock()
    mock_client.get_signing_keys = MagicMock(side_effect=ConnectionError("test outage"))

    with patch("website.api.auth._get_jwks_client", return_value=mock_client):
        app = create_app()
        # Should NOT raise — lifespan must catch and continue
        async with LifespanManager(app):
            pass

    assert mock_client.get_signing_keys.called


@pytest.mark.asyncio
async def test_jwks_prewarm_skipped_when_client_is_none():
    """If JWKS isn't configured (SUPABASE_URL unset), pre-warm is a no-op."""
    from website.app import create_app

    with patch("website.api.auth._get_jwks_client", return_value=None):
        app = create_app()
        async with LifespanManager(app):
            pass
    # No assertion needed — the test passes if no exception escapes startup
