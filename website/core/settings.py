"""Website-native application settings.

This mirrors the configuration layering used by the Telegram bot without
pulling in telegram_bot-specific validation or dependencies.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Tuple, Type

from pydantic import field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

logger = logging.getLogger(__name__)

# Module-level latch so the Reddit OAuth warning fires exactly once per process.
_reddit_warning_emitted = False

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_CONFIG_YAML = _PROJECT_ROOT / "ops" / "config.yaml"
_DEFAULT_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Website configuration loaded from env, .env, and YAML."""

    model_config = SettingsConfigDict(
        env_file=str(_DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    telegram_bot_token: str = ""
    allowed_chat_id: int = 0

    @field_validator("allowed_chat_id", mode="before")
    @classmethod
    def _coerce_empty_chat_id(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip() == "":
            return 0
        return value

    gemini_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "ZettelkastenBot/1.0"

    github_token: str = ""
    github_repo: str = ""
    github_branch: str = "main"

    @property
    def github_enabled(self) -> bool:
        return bool(self.github_token.strip() and self.github_repo.strip())

    @property
    def reddit_oauth_configured(self) -> bool:
        """True iff both Reddit OAuth credentials are non-empty.

        When False, the Reddit ingestor degrades to the public JSON endpoint
        plus HTML scraping, which often returns thin content behind Reddit's
        anti-bot wall.
        """
        return bool(self.reddit_client_id.strip() and self.reddit_client_secret.strip())

    reddit_comment_depth: int = 10

    kg_directory: str = "./kg_output"
    data_dir: str = "./data"

    webhook_mode: bool = False
    webhook_url: str = ""
    webhook_port: int = 8443
    webhook_secret: str = ""

    model_name: str = "gemini-2.5-flash"
    rag_chunks_enabled: bool = False

    log_level: str = "INFO"

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
        yaml_settings = YamlConfigSettingsSource(
            settings_cls,
            yaml_file=_DEFAULT_CONFIG_YAML,
        )
        return (init_settings, env_settings, dotenv_settings, yaml_settings)


def validate_reddit_credentials(settings: Settings) -> None:
    """Emit a one-shot startup warning when Reddit OAuth creds are missing
    in a production-like environment.

    "Production-like" is inferred from ``settings.webhook_mode`` because that
    is the existing prod/dev split in this codebase (polling=dev, webhook=prod).
    The warning fires at most once per process via a module-level latch; it
    never raises or exits, because Reddit capture is optional — the ingestor
    still works via the public JSON endpoint, just with thinner content.
    """
    global _reddit_warning_emitted
    if _reddit_warning_emitted:
        return
    if not settings.webhook_mode:
        return
    if settings.reddit_oauth_configured:
        return
    logger.warning(
        "Reddit OAuth credentials missing (REDDIT_CLIENT_ID and/or "
        "REDDIT_CLIENT_SECRET are unset). Reddit ingestion will use public "
        "JSON fallback; set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for "
        "full-quality extraction."
    )
    _reddit_warning_emitted = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    validate_reddit_credentials(settings)
    return settings
