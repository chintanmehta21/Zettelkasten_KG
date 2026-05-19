"""Pydantic schema for Newsletter-specific structured summary payload."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SummaryMetadata,
)


_BRANDED_YAML_DEFAULT = (
    Path(__file__).resolve().parents[5] / "docs" / "summary_eval" / "_config" / "branded_newsletter_sources.yaml"
)


def load_branded_newsletter_sources() -> list[str]:
    """Return lowercase list of branded publication identifiers."""
    path_override = os.environ.get("BRANDED_SOURCES_YAML")
    path = Path(path_override) if path_override else _BRANDED_YAML_DEFAULT
    if not path.exists():
        return ["stratechery", "platformer", "lennysnewsletter", "notboring", "thedispatch"]
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return [source.lower() for source in data.get("branded_sources", [])]


class NewsletterSection(BaseModel):
    heading: str
    bullets: list[str] = Field(..., min_length=1)


class NewsletterDetailedPayload(BaseModel):
    publication_identity: str
    issue_thesis: str
    sections: list[NewsletterSection] = Field(..., min_length=1)
    conclusions_or_recommendations: list[str] = Field(default_factory=list)
    stance: Literal["optimistic", "skeptical", "cautionary", "neutral", "mixed"]
    cta: str | None = None
    caveats: list[str] = Field(
        default_factory=list,
        description=(
            "Author-stated disclaimers, hedges, conflicts-of-interest, scope "
            "limits — verbatim or near-verbatim from source."
        ),
    )


class NewsletterStructuredPayload(BaseModel):
    mini_title: str
    brief_summary: str
    tags: list[str] = Field(..., min_length=7, max_length=10)
    detailed_summary: NewsletterDetailedPayload

    @model_validator(mode="after")
    def _enforce_branded_label(self) -> "NewsletterStructuredPayload":
        publication = (self.detailed_summary.publication_identity or "").lower()
        branded = load_branded_newsletter_sources()
        is_branded = any(source in publication for source in branded)
        if is_branded:
            title_lower = self.mini_title.lower()
            matched = any(source in title_lower for source in branded if source in publication)
            if not matched:
                raise ValueError(
                    f"Branded source '{publication}' requires publication name in label; got '{self.mini_title}'"
                )
        return self


class NewsletterSummaryResult(BaseModel):
    mini_title: str
    brief_summary: str
    tags: list[str] = Field(..., min_length=7, max_length=10)
    # MUST be the rendered section list (NOT the rich NewsletterDetailedPayload).
    # Every downstream consumer — render_detailed_summary
    # (summarization.summary_dto / nexus bulk_import) and writers/markdown.py —
    # iterates ``result.detailed_summary`` expecting DetailedSummarySection
    # objects with ``.heading``/``.bullets``/``.sub_sections``. Passing the
    # NewsletterDetailedPayload model here made ``for section in
    # detailed_summary`` iterate the Pydantic model and yield ``(field, value)``
    # tuples, producing the live "'tuple' object has no attribute 'heading'"
    # crash on every Substack/newsletter zettel. Reddit/GitHub/YouTube all
    # already return this shape; this aligns Newsletter with that contract. The
    # full NewsletterDetailedPayload is still preserved verbatim on
    # SummaryMetadata.structured_payload for any source-specific consumer.
    detailed_summary: list[DetailedSummarySection]
    metadata: SummaryMetadata
