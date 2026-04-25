"""Gold-data loader for rag_eval seed and held-out queries."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from website.features.rag_pipeline.evaluation._schemas import (
    HeldoutQueryFile,
    SeedQueryFile,
)
from website.features.rag_pipeline.evaluation.types import GoldQuery


class GoldLoaderError(Exception):
    """Raised when gold-data loading or sealing fails."""


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise GoldLoaderError(f"File not found: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise GoldLoaderError(f"YAML parse error in {path}: {exc}") from exc


def load_seed_queries(path: Path) -> list[GoldQuery]:
    raw = _load_yaml(path)
    try:
        parsed = SeedQueryFile.model_validate(raw)
    except ValidationError as exc:
        raise GoldLoaderError(f"Invalid seed.yaml at {path}: {exc}") from exc
    return parsed.queries


def load_heldout_queries(path: Path, *, allow_sealed: bool) -> list[GoldQuery]:
    sentinel = path.parent / ".heldout_sealed"
    if sentinel.exists() and not allow_sealed:
        raise GoldLoaderError(
            f"heldout.yaml at {path} is sealed; pass --unseal-heldout for the final iter only"
        )
    raw = _load_yaml(path)
    try:
        parsed = HeldoutQueryFile.model_validate(raw)
    except ValidationError as exc:
        raise GoldLoaderError(f"Invalid heldout.yaml at {path}: {exc}") from exc
    return parsed.queries


def seal_heldout(path: Path) -> None:
    sentinel = path.parent / ".heldout_sealed"
    sentinel.write_text("sealed", encoding="utf-8")
