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
        # gunicorn 25.1+ control socket defaults to $HOME/.gunicorn/, which is
        # read-only in the production image -> a noisy startup ERROR on every
        # worker boot. Blue/green deploys never use `gunicornc` runtime
        # control, so disable the socket outright.
        "--no-control-socket",
        "--bind", f"0.0.0.0:{os.environ.get('PORT', '10000')}",
        # iter-10 doc reconciliation: production droplet sets GUNICORN_TIMEOUT=240
        # in /opt/zettelkasten/compose/.env (>=180s per CLAUDE.md guardrail). The
        # "90" default below is for un-configured dev; prod always overrides.
        "--timeout", os.environ.get("GUNICORN_TIMEOUT", "90"),
        # 2026-05-24 — SSE recycle hardening (Naruto E2E surfaced "Lost
        # connection mid-answer"). Default 30s graceful_timeout killed
        # ask_kasten streams that ran longer than the recycle window. Per
        # Gunicorn maintainer (discussion #3042) + Modexa prod guide:
        # graceful_timeout MUST exceed the request --timeout so in-flight
        # SSE drains before SIGKILL. 200 > 180 (the prod TIMEOUT floor).
        "--graceful-timeout", os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "200"),
        "--keep-alive", os.environ.get("GUNICORN_KEEPALIVE", "5"),
        # 2026-05-24 — bumped from 100/25 (iter-05) to 1000/200 after live
        # SSE drops on /api/rag/sessions/.../messages (log:
        # "Maximum request limit of 108 exceeded. Terminating process"
        # fired DURING an in-flight stream). Modexa / Gunicorn issue #2672
        # recommend recycle every 15-60 min at steady QPS, not every few
        # requests. 10x bump gives ~10x lower probability of mid-SSE kill.
        # 20% jitter de-correlates the two workers' recycle clocks. The
        # iter-05 mem-fix work (clear_frames + aggressive_release) made
        # the original 100-request belt-and-braces unnecessary; bound is
        # now enforced by graceful_timeout overlap window + 2GB cgroup.
        "--max-requests", os.environ.get("GUNICORN_MAX_REQUESTS", "1000"),
        "--max-requests-jitter", os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "200"),
        # iter-04: cap OS accept-queue. Default gunicorn backlog is 2048
        # which lets the kernel accept 2048 SYNs into a 240 s death-trail
        # under burst load. With 2 workers x (2 sem + 8 queue) = 20 in-
        # flight + 4x headroom = 64. Beyond that we'd rather fail-fast at
        # the listen() boundary so Caddy can hand back 503.
        "--backlog", os.environ.get("GUNICORN_BACKLOG", "64"),
        "--config", os.environ.get("GUNICORN_CONFIG", "website/gunicorn_conf.py"),
        "website.main:app",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
