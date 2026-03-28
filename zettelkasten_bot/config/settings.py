"""Application settings loaded from environment variables and config/config.yaml.

Priority (highest to lowest):
  1. Explicit constructor arguments (init)
  2. Environment variables (e.g. TELEGRAM_BOT_TOKEN=...)
  3. config/config.yaml values
  4. Field defaults defined below

Secrets (bot token, API keys) must be provided via environment variables —
they should never be committed to config.yaml.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Tuple, Type

from pydantic import field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings import YamlConfigSettingsSource

# Resolve config/config.yaml relative to the project root (two levels above this file:
# zettelkasten_bot/config/settings.py → zettelkasten_bot/ → project root)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_CONFIG_YAML = _PROJECT_ROOT / "config" / "config.yaml"
_DEFAULT_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Central application settings.

    All fields without defaults are REQUIRED at startup.
    """

    model_config = SettingsConfigDict(
        env_file=str(_DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        # Allow env-var names to be case-insensitive (e.g. TELEGRAM_BOT_TOKEN or telegram_bot_token)
        case_sensitive=False,
        # Extra fields in yaml/env are silently ignored
        extra="ignore",
    )

    # ── Required ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    allowed_chat_id: int = 0

    @field_validator("allowed_chat_id", mode="before")
    @classmethod
    def _coerce_empty_chat_id(cls, v: Any) -> Any:
        """Treat empty-string ALLOWED_CHAT_ID (from .env template) as 0."""
        if isinstance(v, str) and v.strip() == "":
            return 0
        return v

    # ── Optional / secrets ───────────────────────────────────────────────────
    gemini_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "ZettelkastenBot/1.0"

    # ── GitHub note storage (optional — for cloud deployment) ────────────
    github_token: str = ""
    github_repo: str = ""       # e.g., "user/repo"
    github_branch: str = "main"

    @property
    def github_enabled(self) -> bool:
        """True when both GitHub token and repo are configured."""
        return bool(self.github_token.strip() and self.github_repo.strip())

    # ── Reddit settings ──────────────────────────────────────────────────────
    # D001: reddit_comment_depth controls how many top-level comments to fetch
    reddit_comment_depth: int = 10

    # ── Storage paths ─────────────────────────────────────────────────────────
    kg_directory: str = "./kg_output"
    data_dir: str = "./data"

    # ── Webhook configuration ─────────────────────────────────────────────────
    webhook_mode: bool = False
    webhook_url: str = ""
    webhook_port: int = 8443
    webhook_secret: str = ""

    # ── AI model ──────────────────────────────────────────────────────────────
    model_name: str = "gemini-2.5-flash"

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Source detection ──────────────────────────────────────────────────────
    newsletter_domains: list[str] = [
        "substack.com",
        "buttondown.email",
        "beehiiv.com",
        "mailchimp.com",
        "medium.com",
        "stackoverflow.com",
        "stackexchange.com",
        "news.ycombinator.com",
        "dev.to",
        "hackernoon.com",
    ]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """Set source priority: init → env → dotenv → yaml → defaults."""
        yaml_settings = YamlConfigSettingsSource(
            settings_cls,
            yaml_file=_DEFAULT_CONFIG_YAML,
        )
        return (init_settings, env_settings, dotenv_settings, yaml_settings)


def _validate_settings(settings: Settings) -> None:
    """Raise SystemExit if required fields are missing or are placeholder values."""
    placeholder_tokens = {"", "your-telegram-bot-token", "changeme", "<your-token>"}

    if settings.telegram_bot_token.strip().lower() in placeholder_tokens:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN is missing or is a placeholder value.\n"
            "Set it via environment variable:  export TELEGRAM_BOT_TOKEN=<your-token>\n"
            "Or add it to config/config.yaml under 'telegram_bot_token:'",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if settings.allowed_chat_id == 0:
        print(
            "ERROR: ALLOWED_CHAT_ID is not set.\n"
            "Set it via environment variable:  export ALLOWED_CHAT_ID=<your-chat-id>",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if settings.webhook_mode and not settings.webhook_url.strip():
        print(
            "ERROR: webhook_mode is enabled but WEBHOOK_URL is empty.\n"
            "Set it via environment variable:  export WEBHOOK_URL=https://your-domain.com/hook\n"
            "Or add it to config/config.yaml under 'webhook_url:'",
            file=sys.stderr,
        )
        raise SystemExit(1)

    gemini_placeholders = {"", "your-gemini-api-key", "changeme", "<your-key>"}
    if settings.gemini_api_key.strip().lower() in gemini_placeholders:
        print(
            "WARNING: GEMINI_API_KEY is missing or is a placeholder value.\n"
            "AI summarization will fail — notes will be saved as raw content.\n"
            "Set it via environment variable:  export GEMINI_API_KEY=<your-key>",
            file=sys.stderr,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton.

    Validates required fields on first call; raises SystemExit on bad config.
    """
    settings = Settings()
    _validate_settings(settings)
    return settings
