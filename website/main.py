"""Website-only runtime entrypoint.

Boots the FastAPI app. The module-level ``app`` is what gunicorn loads when
``--preload`` runs, so heavy ONNX sessions in :mod:`website.features.rag_pipeline.rerank.cascade`
are imported once in the master and inherited by workers via copy-on-write.

``main()`` retains a uvicorn fallback for ``ENV=dev`` / interactive debugging.
"""

from __future__ import annotations

import logging

import uvicorn

from website.app import create_app
from website.core.settings import get_settings

logger = logging.getLogger("website.main")

# Module-level ASGI app. gunicorn imports ``website.main:app`` with --preload.
app = create_app()


def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    port = settings.webhook_port or 10000
    logger.info("Starting Zettelkasten website on 0.0.0.0:%d (uvicorn dev mode)", port)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
