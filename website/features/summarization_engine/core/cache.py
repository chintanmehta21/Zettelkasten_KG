"""Content-hashed on-disk cache shim for ingest / summary / atomic-facts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
    )


class FsContentCache:
    """Key-tuple to JSON-payload cache rooted at disk."""

    def __init__(self, root: Path, namespace: str) -> None:
        self._dir = Path(root) / namespace
        self._dir.mkdir(parents=True, exist_ok=True)

    def key_hash(self, key_tuple: tuple) -> str:
        canonical = _canonical_json(list(key_tuple))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, key_tuple: tuple) -> Path:
        return self._dir / f"{self.key_hash(key_tuple)}.json"

    @property
    def enabled(self) -> bool:
        return os.environ.get("CACHE_DISABLED") != "1"

    def get(self, key_tuple: tuple) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self._path(key_tuple)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def put(self, key_tuple: tuple, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self._path(key_tuple)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        return None
