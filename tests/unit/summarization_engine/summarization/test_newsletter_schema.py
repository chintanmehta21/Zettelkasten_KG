import pytest
from pydantic import ValidationError

from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterDetailedPayload,
    NewsletterSection,
    NewsletterStructuredPayload,
    load_branded_newsletter_sources,
)


def _base_detailed(
    publication: str, stance: str = "neutral"
) -> NewsletterDetailedPayload:
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
            tags=[
                "business",
                "strategy",
                "saas",
                "platforms",
                "analysis",
                "tech",
                "subscription",
            ],
            detailed_summary=_base_detailed("Stratechery"),
        )


def test_non_branded_source_accepts_thesis_only():
    payload = NewsletterStructuredPayload(
        mini_title="Kubernetes Networking Pitfalls",
        brief_summary="...",
        tags=[
            "kubernetes",
            "networking",
            "devops",
            "cloud",
            "cni",
            "operations",
            "analysis",
        ],
        detailed_summary=_base_detailed("Random Devops Blog"),
    )
    assert payload.mini_title == "Kubernetes Networking Pitfalls"


def test_load_branded_sources_falls_back_for_missing_file(monkeypatch, tmp_path):
    missing_file = tmp_path / "missing.yaml"
    monkeypatch.setenv("BRANDED_SOURCES_YAML", str(missing_file))

    branded_sources = load_branded_newsletter_sources()

    assert "stratechery" in branded_sources
    assert "platformer" in branded_sources


def test_load_branded_sources_reads_override_yaml(monkeypatch, tmp_path):
    override_yaml = tmp_path / "branded.yaml"
    override_yaml.write_text(
        "branded_sources:\n  - Deep Research Weekly\n", encoding="utf-8"
    )
    monkeypatch.setenv("BRANDED_SOURCES_YAML", str(override_yaml))

    assert load_branded_newsletter_sources() == ["deep research weekly"]


def test_branded_source_accepts_case_insensitive_publication_match(
    monkeypatch, tmp_path
):
    override_yaml = tmp_path / "branded.yaml"
    override_yaml.write_text("branded_sources:\n  - Stratechery\n", encoding="utf-8")
    monkeypatch.setenv("BRANDED_SOURCES_YAML", str(override_yaml))

    payload = NewsletterStructuredPayload(
        mini_title="STRATECHERY Aggregation Theory Insight",
        brief_summary="...",
        tags=[
            "business",
            "strategy",
            "saas",
            "platforms",
            "analysis",
            "tech",
            "subscription",
        ],
        detailed_summary=_base_detailed("Stratechery"),
    )

    assert payload.mini_title.startswith("STRATECHERY")
