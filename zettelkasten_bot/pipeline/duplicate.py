"""JSON-backed duplicate URL detection store.

Persists seen URLs to ``{data_dir}/seen_urls.json`` so the bot never
captures the same URL twice in the same knowledge graph.  Atomic saves
(write-to-temp then rename) guard against partial writes.

Usage::

    store = DuplicateStore("/path/to/data")
    if store.is_duplicate(url):
        return  # already captured
    # … do work …
    store.mark_seen(url)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from zettelkasten_bot.utils.url_utils import normalize_url

logger = logging.getLogger(__name__)

_DEFAULT_FILENAME = "seen_urls.json"


class DuplicateStore:
    """Persistent set of already-captured (normalized) URLs.

    Args:
        data_dir: Directory that holds ``seen_urls.json``.  Created
            automatically if it does not exist.
        filename: Override the default ``seen_urls.json`` filename
            (useful in tests to avoid clobbering production data).
    """

    def __init__(self, data_dir: str | Path, filename: str = _DEFAULT_FILENAME) -> None:
        self._dir = Path(data_dir)
        self._path = self._dir / filename
        self._seen: set[str] = set()

        # Ensure the data directory exists before trying to read/write
        os.makedirs(self._dir, exist_ok=True)

        self.load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def load(self) -> None:
        """Read URLs from the JSON file into the in-memory set.

        If the file is missing or contains invalid JSON the store is
        initialised to an empty set and a warning is logged — the bot will
        continue without duplicates rather than crash.
        """
        if not self._path.exists():
            logger.debug("Seen-URLs file not found at %s — starting empty", self._path)
            self._seen = set()
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError(f"Expected a JSON list, got {type(data).__name__}")
            self._seen = set(data)
            logger.debug("Loaded %d seen URLs from %s", len(self._seen), self._path)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logger.warning(
                "Could not load seen_urls.json (%s) — starting with empty set: %s",
                self._path,
                exc,
            )
            self._seen = set()

    def save(self) -> None:
        """Atomically persist the in-memory set to the JSON file.

        Writes to a temporary file in the same directory then renames it to
        avoid partial-write corruption.
        """
        os.makedirs(self._dir, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(sorted(self._seen), fh, ensure_ascii=False, indent=2)
            except Exception:
                os.unlink(tmp_path)
                raise
            os.replace(tmp_path, self._path)
            logger.debug("Saved %d seen URLs to %s", len(self._seen), self._path)
        except OSError as exc:
            logger.error("Failed to save seen_urls.json to %s: %s", self._path, exc)
            raise

    # ── Lookup / mutation ────────────────────────────────────────────────────

    def is_duplicate(self, url: str) -> bool:
        """Return True if the normalized form of *url* was already captured.

        Args:
            url: Raw or already-normalized URL.

        Returns:
            ``True`` when the URL is in the seen set, ``False`` otherwise.
        """
        return normalize_url(url) in self._seen

    def mark_seen(self, url: str) -> None:
        """Add the normalized form of *url* to the set and persist.

        Args:
            url: URL to record as captured.
        """
        normalized = normalize_url(url)
        self._seen.add(normalized)
        logger.info("Marked as seen: %s", normalized)
        self.save()
