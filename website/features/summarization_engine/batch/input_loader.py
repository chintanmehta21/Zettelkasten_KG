"""CSV/JSON batch input loader."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BatchInputItem:
    url: str
    user_tags: list[str] = field(default_factory=list)
    user_note: str | None = None


def load_batch_input(path: Path | None = None, *, input_bytes: bytes | None = None, filename: str = "") -> list[BatchInputItem]:
    raw = input_bytes.decode("utf-8-sig") if input_bytes is not None else Path(path).read_text(encoding="utf-8-sig")  # type: ignore[arg-type]
    fmt = _detect_format(filename or (str(path) if path else ""), raw)
    if fmt == "json":
        payload = json.loads(raw)
        rows = payload if isinstance(payload, list) else payload.get("urls", [])
        return [BatchInputItem(url=row["url"], user_tags=row.get("tags", []), user_note=row.get("note")) for row in rows]
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
