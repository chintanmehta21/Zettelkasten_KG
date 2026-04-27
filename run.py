"""Production entrypoint.

In production, dispatches to ``gunicorn`` with two ``UvicornWorker``s and the
``--preload`` flag so the heavy BGE int8 ONNX session in
``website.features.rag_pipeline.rerank.cascade`` is loaded once in the master
process and inherited by workers via copy-on-write -- a ~110 MB RAM saving on
a 2 GB droplet.

Set ``ENV=dev`` to fall back to bare uvicorn for local debugging.

Usage: ``python run.py``
"""

from __future__ import annotations

import os
import subprocess
import sys


def _is_dev() -> bool:
    return os.environ.get("ENV", "").strip().lower() == "dev"


def main() -> int:
    if _is_dev():
        from website.main import main as uvicorn_main

        uvicorn_main()
        return 0

    cmd = [
        "gunicorn",
        "-k", "uvicorn.workers.UvicornWorker",
        "-w", os.environ.get("GUNICORN_WORKERS", "2"),
        "--preload",
        "--bind", f"0.0.0.0:{os.environ.get('PORT', os.environ.get('WEBHOOK_PORT', '10000'))}",
        "--timeout", os.environ.get("GUNICORN_TIMEOUT", "90"),
        "--graceful-timeout", os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "60"),
        "--keep-alive", os.environ.get("GUNICORN_KEEPALIVE", "5"),
        "website.main:app",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
