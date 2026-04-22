"""Conclusions and action-item detector for newsletters."""
from __future__ import annotations

import re


_HEADER_PATTERN = re.compile(
    r"(?im)^\s*#{0,3}\s*(takeaways?|what to do|action items?|key points?|conclusion)\s*:?\s*$"
)
_LIST_MARKER_PATTERN = re.compile(r"^\s*(?:[-*]|[0-9]+\.)\s+")
_INLINE_HEADER_PATTERN = re.compile(
    r"(?im)(?:^|[\r\n]|[.!?]\s+)\s*#{0,3}\s*"
    r"(takeaways?|what to do|action items?|key points?|conclusion)\s*:?\s*(?:\r?\n|$)"
)


def extract_conclusions(
    text: str,
    *,
    tail_fraction: float,
    prefixes: list[str],
    max_count: int,
) -> list[str]:
    if not text:
        return []

    tail_start = int(len(text) * max(0.0, 1.0 - tail_fraction))
    boundary = max(
        text.rfind("\n", 0, tail_start),
        text.rfind(". ", 0, tail_start),
        text.rfind("! ", 0, tail_start),
        text.rfind("? ", 0, tail_start),
    )
    if boundary >= 0:
        tail = text[boundary + 1 :]
    else:
        tail = text[tail_start:]
    out: list[str] = []

    for sentence in re.split(r"(?<=[.!?])\s+", tail):
        stripped = sentence.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(lowered.startswith(prefix) for prefix in prefixes):
            out.append(stripped)
            if len(out) >= max_count:
                return out

    header_match = _INLINE_HEADER_PATTERN.search(tail)
    lines = tail[header_match.end() :].splitlines() if header_match else tail.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if header_match or _HEADER_PATTERN.match(line):
            index += 1
            while index < len(lines) and _LIST_MARKER_PATTERN.match(lines[index]):
                cleaned = _LIST_MARKER_PATTERN.sub("", lines[index]).strip()
                if cleaned:
                    out.append(cleaned)
                    if len(out) >= max_count:
                        return out
                index += 1
            if header_match:
                break
            continue
        index += 1
    return out
