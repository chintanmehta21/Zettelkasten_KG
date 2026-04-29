from __future__ import annotations

import hashlib
import re

from .types import ZettelRecord


RENDERER_VERSION = "pageindex-zettel-md-v1"


def _clean_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("#", "").strip()) or "Untitled"


def _demote_embedded_headings(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            lines.append("#### " + _clean_heading(line))
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def render_zettel_markdown(zettel: ZettelRecord) -> tuple[str, str]:
    title = _clean_heading(zettel.title)
    tags = ", ".join(sorted(zettel.tags))
    metadata_lines = [
        f"- Node ID: {zettel.node_id}",
        f"- Source Type: {zettel.source_type}",
        f"- Source URL: {zettel.url or ''}",
        f"- Tags: {tags}",
    ]
    body = "\n\n".join(
        [
            f"# {title}",
            "## Metadata",
            "\n".join(metadata_lines),
            "## Summary",
            _demote_embedded_headings(zettel.summary),
            "## Captured Content",
            _demote_embedded_headings(zettel.content),
        ]
    ).strip() + "\n"
    content_hash = hashlib.sha256((RENDERER_VERSION + "\n" + body).encode("utf-8")).hexdigest()
    return body, content_hash
