import pytest
from pydantic import ValidationError

from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterDetailedPayload,
    NewsletterSection,
    NewsletterStructuredPayload,
)


def _base_detailed(publication: str, stance: str = "neutral") -> NewsletterDetailedPayload:
    return NewsletterDetailedPayload(
        publication_identity=publication,
        issue_thesis="Thesis here.",
        sections=[NewsletterSection(heading="Intro", bullets=["b"])],
        conclusions_or_recommendations=["Do X"],
        stance=stance,
        cta=None,
    )


def test_branded_source_requires_publication_in_title(monkeypatch):
    monkeypatch.setenv("BRANDED_SOURCES_YAML", "")
    with pytest.raises(ValidationError):
        NewsletterStructuredPayload(
            mini_title="Aggregation Theory Insight",
            brief_summary="...",
            tags=["business", "strategy", "saas", "platforms", "analysis", "tech", "subscription"],
            detailed_summary=_base_detailed("Stratechery"),
        )


def test_non_branded_source_accepts_thesis_only():
    payload = NewsletterStructuredPayload(
        mini_title="Kubernetes Networking Pitfalls",
        brief_summary="...",
        tags=["kubernetes", "networking", "devops", "cloud", "cni", "operations", "analysis"],
        detailed_summary=_base_detailed("Random Devops Blog"),
    )
    assert payload.mini_title == "Kubernetes Networking Pitfalls"
