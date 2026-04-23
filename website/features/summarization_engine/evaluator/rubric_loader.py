"""Load and validate rubric_<source>.yaml files."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class RubricSchemaError(ValueError):
    """Raised when a rubric YAML is missing required fields."""


_REQUIRED_KEYS = {"version", "source_type", "composite_max_points", "components"}


def load_rubric(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    missing = _REQUIRED_KEYS - set(data.keys())
    if missing:
        raise RubricSchemaError(
            f"rubric {path} missing required keys: {sorted(missing)}"
        )

    total = sum(component.get("max_points", 0) for component in data.get("components", []))
    if total != data.get("composite_max_points", 100):
        raise RubricSchemaError(
            f"rubric {path} component sum {total} != composite_max_points "
            f"{data['composite_max_points']}"
        )

    return data
