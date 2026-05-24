"""Single source-of-truth registry for content source types.

D1 + D2 + D3 fix (Phase 4 / Task 4.1): three independent normalize/prefix/
color implementations collapsed to one Python module. Frontend picks up the
same data via ``GET /api/meta/source-types`` so adding a new source type is
a one-file change.

Per CLAUDE.md: amber/teal only on /knowledge-graph; everywhere else stays
teal. The hex values below are the per-source NODE colours (not edges) and
are intentionally distinct (one per source) — the knowledge-graph amber rule
applies to EDGE colours, not nodes.
"""
from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass


class SourceType(StrEnum):
    YOUTUBE = "youtube"
    REDDIT = "reddit"
    GITHUB = "github"
    SUBSTACK = "substack"
    NEWSLETTER = "newsletter"
    MEDIUM = "medium"
    TWITTER = "twitter"
    WEB = "web"


@dataclass(frozen=True, slots=True)
class SourceMeta:
    prefix: str
    label: str
    color_hex: str
    color_int: int
    modality: str  # video | article | post | book


SOURCE_REGISTRY: dict[SourceType, SourceMeta] = {
    SourceType.YOUTUBE:    SourceMeta("yt", "YouTube",    "#E05565", 0xE05565, "video"),
    SourceType.REDDIT:     SourceMeta("rd", "Reddit",     "#E09040", 0xE09040, "post"),
    SourceType.GITHUB:     SourceMeta("gh", "GitHub",     "#56C8D8", 0x56C8D8, "article"),
    SourceType.SUBSTACK:   SourceMeta("ss", "Substack",   "#60A5FA", 0x60A5FA, "article"),
    SourceType.NEWSLETTER: SourceMeta("ss", "Newsletter", "#60A5FA", 0x60A5FA, "article"),
    SourceType.MEDIUM:     SourceMeta("md", "Medium",     "#4ADE80", 0x4ADE80, "article"),
    SourceType.TWITTER:    SourceMeta("tw", "Twitter",    "#1DA1F2", 0x1DA1F2, "post"),
    SourceType.WEB:        SourceMeta("web", "Web",       "#94A3B8", 0x94A3B8, "article"),
}

# Legacy alias: 'generic' → web (D3 cleanup).
_ALIASES: dict[str, SourceType] = {"generic": SourceType.WEB}


def normalize(source_type: str | None) -> SourceType:
    """Normalize raw input to a SourceType enum. Unknown → WEB."""
    normalized = (source_type or "").strip().lower()
    if not normalized:
        return SourceType.WEB
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    try:
        return SourceType(normalized)
    except ValueError:
        return SourceType.WEB


def prefix(source_type: str | None) -> str:
    """Return the node-id prefix for a source type (e.g. 'yt', 'rd')."""
    return SOURCE_REGISTRY[normalize(source_type)].prefix


def to_wire_dict() -> dict[str, dict[str, str | int]]:
    """Serialize for the /api/meta/source-types endpoint.

    Returned shape (per key):
      ``{prefix, label, color_hex, color_int, modality}``
    """
    return {
        st.value: {
            "prefix": meta.prefix,
            "label": meta.label,
            "color_hex": meta.color_hex,
            "color_int": meta.color_int,
            "modality": meta.modality,
        }
        for st, meta in SOURCE_REGISTRY.items()
    }
