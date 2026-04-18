"""Website-native application settings.

This mirrors the configuration layering used by the Telegram bot without
pulling in telegram_bot-specific validation or dependencies.
"""

from __future__ import annotations

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
