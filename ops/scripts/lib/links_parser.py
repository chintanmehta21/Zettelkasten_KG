"""Parse section-headered docs/testing/links.txt."""
from __future__ import annotations

import re
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

_NUMBERED_PREFIX = re.compile(r"^\d+\.\s*")


def _match_header(candidate: str) -> str | None:
    """Match a header line against known source names (allows trailing text)."""
    lowered = candidate.strip().lower()
    if lowered in _KNOWN_HEADERS:
        return lowered.replace(" ", "")
    # Allow "# Reddit — stale" or "# GitHub (archive)" style headers
    for known in _KNOWN_HEADERS:
        if lowered.startswith(known):
            rest = lowered[len(known):].lstrip()
            if not rest or rest[0] in "—-—:(":
                return known.replace(" ", "")
    return None


def parse_links_file(path: Path) -> dict[str, list[str]]:
    """Return ``{source_key: [url, ...]}`` parsed from ``# Source`` headers.

    Missing file → empty dict (defensive for CI / fresh clones).
    """
    result: dict[str, list[str]] = {}
    current: str | None = None

    p = Path(path)
    if not p.exists():
        return result

    with p.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("# "):
                matched = _match_header(line[2:])
                if matched is None:
                    continue
                current = matched
                result.setdefault(current, [])
                continue
            if line.startswith("#"):
                continue
            # strip "1. " / "12.  " numbering prefix for legacy-style lists
            line = _NUMBERED_PREFIX.sub("", line)
            if current is not None and line:
                result.setdefault(current, []).append(line)

    return result
