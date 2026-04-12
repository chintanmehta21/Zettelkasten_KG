from telegram_bot.config.settings import Settings


def test_rag_chunks_enabled_default_false() -> None:
    settings = Settings(telegram_bot_token="token", allowed_chat_id=1)
    assert settings.rag_chunks_enabled is False
