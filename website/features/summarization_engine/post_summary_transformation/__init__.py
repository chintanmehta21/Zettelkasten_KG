"""Post-summary transformations that make engine output render cleanly."""

from .markdown_structure import normalize_markdown_headings, transform_detailed_summary_sections
from .rules import title as _title  # noqa: F401  (registers title rules)
from .rules import sections as _sections  # noqa: F401  (registers arxiv section rule)

__all__ = ["normalize_markdown_headings", "transform_detailed_summary_sections"]
