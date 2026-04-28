"""Iter-03 §6: /app/models becomes read-only inside the image (baked).
Compose must NO LONGER mount /opt/zettelkasten/data/models over /app/models.
A new /app/runtime mount holds runtime writes (degradation_events.jsonl).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

OPS = Path(__file__).resolve().parents[3] / "ops"


@pytest.mark.parametrize("color", ["blue", "green"])
def test_compose_does_not_mount_models(color: str):
    text = (OPS / f"docker-compose.{color}.yml").read_text(encoding="utf-8")
    assert "/app/models" not in text, (
        f"docker-compose.{color}.yml must NOT mount /app/models — models are "
        "baked into the image now. See spec §6."
    )


@pytest.mark.parametrize("color", ["blue", "green"])
def test_compose_mounts_runtime_dir(color: str):
    text = (OPS / f"docker-compose.{color}.yml").read_text(encoding="utf-8")
    assert "/opt/zettelkasten/data/runtime:/app/runtime:rw" in text, (
        f"docker-compose.{color}.yml must add the new /app/runtime mount for "
        "runtime writes (degradation_events.jsonl). See spec §6."
    )


@pytest.mark.parametrize("color", ["blue", "green"])
def test_compose_yaml_still_valid(color: str):
    payload = yaml.safe_load((OPS / f"docker-compose.{color}.yml").read_text(encoding="utf-8"))
    assert "services" in payload
