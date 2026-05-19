"""Arxiv-only: drop a Limitations/Citations section whose SOLE bullet is an
LLM 'nothing here' placeholder. Registered as a section rule (source=arxiv).
Conservative: only these two headings, only exactly-one-bullet, only the
anchored placeholder regex. Pure + idempotent.

Sections are ``DetailedSummarySection`` Pydantic objects (NOT dicts) on the
real generic detailed-summary path, so ``_placeholder_only`` reads the
``.heading`` / ``.bullets`` attributes. Semantics are identical to the
dict-shaped reference in the plan."""
from __future__ import annotations

import re

from website.features.summarization_engine.post_summary_transformation import registry as _reg

_TARGETS = {"limitations", "citations"}
# FULLMATCH: the bullet must be ONLY the placeholder sentence plus an optional
# benign tail. A second clause / "however"/"but"/";"/extra sentence keeps the
# section (real trailing content must not be discarded as an empty placeholder).
_PLACEHOLDER = re.compile(
    r"no (specific )?(limitations|citations) were (mentioned|provided)"
    r"( (in|for) (the )?(provided |given )?"
    r"(summary|text|paper|abstract|article|content))?\.?\s*",
    re.IGNORECASE,
)


def _placeholder_only(section) -> bool:
    heading = getattr(section, "heading", None)
    if heading is None:
        return False
    if str(heading or "").strip().lower() not in _TARGETS:
        return False
    bullets = getattr(section, "bullets", None)
    if not isinstance(bullets, list) or len(bullets) != 1:
        return False
    return _PLACEHOLDER.fullmatch(str(bullets[0] or "").strip()) is not None


@_reg.register_section(source_type="arxiv")
def drop_empty_optional_sections(sections: list) -> list:
    if not isinstance(sections, list):
        return sections
    return [s for s in sections if not _placeholder_only(s)]
