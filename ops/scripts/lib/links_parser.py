"""Parse section-headered docs/testing/links.txt."""
from __future__ import annotations

from pathlib import Path

_KNOWN_HEADERS = {
    "youtube",
    "reddit",
    "github",
    "newsletter",
    "hackernews",
    "hacker news",
    "linkedin",
    "arxiv",
    "podcast",
    "twitter",
    "web",
}


def parse_links_file(path: Path) -> dict[str, list[str]]:
    """Return ``{source_key: [url, ...]}`` parsed from ``# Source`` headers."""
    result: dict[str, list[str]] = {}
    current: str | None = None

    with Path(path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("# "):
                candidate = line[2:].strip().lower()
                if candidate not in _KNOWN_HEADERS:
                    continue
                current = candidate.replace(" ", "")
                result.setdefault(current, [])
                continue
            if line.startswith("#"):
                continue
            if current is not None:
                result.setdefault(current, []).append(line)

    return result
