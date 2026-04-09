"""Webhook-path regression tests for telegram_bot.main."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI


def _make_settings(**overrides):
    settings = {
        "telegram_bot_token": "test-token",
        "allowed_chat_id": 12345,
        "webhook_mode": True,
        "webhook_url": "https://example.com/custom/path",
        "webhook_port": 10000,
        "webhook_secret": "secret123",
    }
    settings.update(overrides)
    return SimpleNamespace(**settings)


def test_derive_webhook_url_uses_telegram_namespace():
    """Webhook URL derivation should ignore any path and use /telegram/webhook."""
    from telegram_bot.main import _derive_webhook_url

    assert _derive_webhook_url("https://example.com/anything") == "https://example.com/telegram/webhook"
    assert _derive_webhook_url("https://example.com") == "https://example.com/telegram/webhook"


def test_run_webhook_mounts_telegram_webhook_route():
    """_run_webhook should insert the webhook route at /telegram/webhook."""
    from telegram_bot.main import _run_webhook

    web_app = FastAPI()
    mock_uvicorn = MagicMock()
    mock_ptb_app = MagicMock()
    mock_ptb_app.bot = MagicMock()
    mock_ptb_app.update_queue = AsyncMock()

    with (
        patch("telegram_bot.main._build_ptb_app", return_value=mock_ptb_app),
        patch.dict(
            "sys.modules",
            {
                "uvicorn": mock_uvicorn,
                "website.app": MagicMock(create_app=MagicMock(return_value=web_app)),
            },
        ),
    ):
        _run_webhook(_make_settings())

    served_app = mock_uvicorn.run.call_args.args[0]
    route_paths = {route.path for route in served_app.routes}
    assert "/telegram/webhook" in route_paths
