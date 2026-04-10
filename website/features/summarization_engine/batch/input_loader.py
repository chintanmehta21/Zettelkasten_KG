"""CSV/JSON batch input loader."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BatchInputItem:
    url: str
    user_tags: list[str] = field(default_factory=list)
    user_note: str | None = None


def load_batch_input(
    path: Path | None = None,
    *,
    input_bytes: bytes | None = None,
    filename: str = "",
    max_size_mb: int | None = None,
) -> list[BatchInputItem]:
    if input_bytes is not None and max_size_mb is not None:
        _validate_size(len(input_bytes), max_size_mb)
    elif path is not None and max_size_mb is not None:
        _validate_size(Path(path).stat().st_size, max_size_mb)
    raw = input_bytes.decode("utf-8-sig") if input_bytes is not None else Path(path).read_text(encoding="utf-8-sig")  # type: ignore[arg-type]
    fmt = _detect_format(filename or (str(path) if path else ""), raw)
    if fmt == "json":
        payload = json.loads(raw)
        rows = payload if isinstance(payload, list) else payload.get("urls", [])
        return [_item_from_json_row(row) for row in rows]
    reader = csv.DictReader(raw.splitlines())
    return [
        BatchInputItem(
            url=row["url"],
            user_tags=[tag.strip() for tag in (row.get("tags") or "").split(",") if tag.strip()],
            user_note=row.get("note") or None,
        )
        for row in reader
        if row.get("url")
    ]


def _detect_format(name: str, raw: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".json") or raw.lstrip().startswith(("{", "[")):
        return "json"
    return "csv"


def _validate_size(size_bytes: int, max_size_mb: int) -> None:
    max_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise ValueError(f"Batch input too large: max {max_size_mb} MB")


def _item_from_json_row(row: Any) -> BatchInputItem:
    if isinstance(row, str):
        return BatchInputItem(url=row)
    return BatchInputItem(
        url=row["url"],
        user_tags=list(row.get("tags", [])),
        user_note=row.get("note"),
    )
