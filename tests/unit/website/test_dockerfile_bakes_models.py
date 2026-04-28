"""Iter-03 §5: Dockerfile must bake models/ into the runtime image so
/app/models is read-only at runtime and the host-state-drift bug class
(which defeated iter-03-stale) is eliminated.
"""
from __future__ import annotations

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[3] / "ops" / "Dockerfile"


def test_runtime_stage_copies_models_dir():
    text = DOCKERFILE.read_text(encoding="utf-8")
    runtime_idx = text.index("FROM python:3.12-slim AS runtime")
    runtime_section = text[runtime_idx:]
    assert "COPY --chown=appuser:appuser models/ /app/models/" in runtime_section, (
        "Dockerfile runtime stage must include 'COPY --chown=appuser:appuser models/ /app/models/' "
        "so the int8 BGE + FlashRank artifacts ship inside the image. See spec §5."
    )


def test_models_copy_uses_appuser_chown():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY models/ /app/models/" not in text, (
        "models/ COPY must use --chown=appuser:appuser; bare COPY leaves files as root."
    )
