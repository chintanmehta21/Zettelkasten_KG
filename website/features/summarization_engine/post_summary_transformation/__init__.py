"""Post-summary transformations that make engine output render cleanly."""

from .markdown_structure import normalize_markdown_headings, transform_detailed_summary_sections
from .rules import title as _title  # noqa: F401  (registers title rules)

__all__ = ["normalize_markdown_headings", "transform_detailed_summary_sections"]
