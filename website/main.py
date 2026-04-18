"""Website-only runtime entrypoint.

Boots the FastAPI app directly under uvicorn. No Telegram webhook, no PTB
application lifecycle — this is the only production entrypoint now that the
Telegram bot has been retired.
"""

from __future__ import annotations

import logging

import uvicorn

from website.app import create_app
from website.core.settings import get_settings

logger = logging.getLogger("website.main")


def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = create_app()
    port = settings.webhook_port or 10000

    logger.info("Starting Zettelkasten website on 0.0.0.0:%d", port)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
