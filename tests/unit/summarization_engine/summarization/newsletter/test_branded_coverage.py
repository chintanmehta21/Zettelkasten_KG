"""Branded-source coverage: every entry in branded_newsletter_sources.yaml
flows through normalize_tags with the brand slug intact in the reserved slot,
and survives `is_live_newsletter` URL-pattern checks.

Mirrors `tests/unit/summarization_engine/test_router_branded_sources.py` —
adding a publication to the YAML auto-requires coverage here. Tests build
real `NewsletterStructuredPayload` instances (no pydantic mocks) so any
schema regression breaks them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from website.features.summarization_engine.summarization.common.structured import (
    _normalize_tags,
)
from website.features.summarization_engine.summarization.newsletter.liveness import (
    is_live_newsletter,
)
from website.features.summarization_engine.summarization.newsletter.summarizer import (
    _brand_reserved,
)
from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterDetailedPayload,
    NewsletterSection,
    NewsletterStructuredPayload,
)


_REPO_ROOT = Path(__file__).resolve().parents[5]
_YAML_PATH = (
    _REPO_ROOT
    / "docs"
    / "summary_eval"
    / "_config"
    / "branded_newsletter_sources.yaml"
)

# Engine config defaults (see `core/config.py::StructuredExtractConfig`).
_TAGS_MIN = 7
_TAGS_MAX = 10


@pytest.fixture(scope="module")
def branded_sources() -> list[str]:
    """Load the canonical branded-source registry once per module."""
    with _YAML_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    sources = data.get("branded_sources") or []
    assert isinstance(sources, list) and sources, (
        f"branded_sources missing/empty in {_YAML_PATH}"
    )
    return [str(s).lower() for s in sources]


def _load_branded_sources() -> list[str]:
    """Module-level loader for parametrize ids (fixtures aren't usable there)."""
    with _YAML_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return [str(s).lower() for s in (data.get("branded_sources") or [])]


_BRANDED_SOURCES = _load_branded_sources()


def _expected_slug(publication: str) -> str:
    """Mirror `_brand_reserved`'s slugification rule exactly."""
    return re.sub(r"[^a-z0-9+-]+", "-", publication.lower()).strip("-")


def _build_payload(publication: str) -> NewsletterStructuredPayload:
    """Construct a minimal valid payload whose mini_title satisfies the
    branded-name validator. Topical tags intentionally exceed the reserved
    slug count to exercise truncation behavior.
    """
    # Validator (`schema.py::_enforce_branded_label`) requires the matching
    # branded substring (the lowercased YAML entry that appears in
    # publication_identity) to also appear in mini_title. We embed it verbatim.
    mini_title = f"{publication}: Issue thesis sample"
    topical_tags = [
        "ai",
        "strategy",
        "platforms",
        "saas",
        "growth",
        "analysis",
        "tech",
        "subscription",
        "policy",
        "markets",
        "macro",
        "research",
    ]  # 12 topical tags so the cap (10) forces truncation.
    return NewsletterStructuredPayload(
        mini_title=mini_title,
        brief_summary="Brief sample summary covering the issue.",
        tags=topical_tags[:_TAGS_MAX],  # schema cap is 10
        detailed_summary=NewsletterDetailedPayload(
            publication_identity=publication,
            issue_thesis="The issue thesis sample.",
            sections=[
                NewsletterSection(heading="Intro", bullets=["bullet one"]),
            ],
            conclusions_or_recommendations=["Take note"],
            stance="neutral",
            cta=None,
        ),
    ), topical_tags


class TestBrandedTagCoverage:
    """Every branded source produces a normalized tag list with the brand
    slug reserved at position 0/1 and surviving topical-tag truncation."""

    @pytest.mark.parametrize("publication", _BRANDED_SOURCES)
    def test_brand_slug_present_in_normalized_tags(self, publication: str):
        payload, topical = _build_payload(publication)
        slug = _expected_slug(publication)
        assert slug, f"slug derivation produced empty string for {publication!r}"

        normalized = _normalize_tags(
            payload.tags,
            _TAGS_MIN,
            _TAGS_MAX,
            reserved=_brand_reserved(payload),
        )

        assert slug in normalized, (
            f"Brand slug {slug!r} missing from normalized tags for "
            f"publication={publication!r}: {normalized}"
        )

    @pytest.mark.parametrize("publication", _BRANDED_SOURCES)
    def test_brand_slug_survives_truncation(self, publication: str):
        """When topical tags push the list past tags_max, the brand slug must
        not be the one that gets truncated — proves it lives in the reserved
        slot, not at the tail."""
        payload, topical = _build_payload(publication)
        slug = _expected_slug(publication)

        # Re-feed with MORE topical tags than the cap allows — bypass the
        # schema cap by going straight to _normalize_tags with a long list.
        many_topical = topical + [
            "extra-one",
            "extra-two",
            "extra-three",
            "extra-four",
            "extra-five",
        ]
        normalized = _normalize_tags(
            many_topical,
            _TAGS_MIN,
            _TAGS_MAX,
            reserved=_brand_reserved(payload),
        )

        assert len(normalized) == _TAGS_MAX, (
            f"Expected truncation to {_TAGS_MAX}; got {len(normalized)}: "
            f"{normalized}"
        )
        assert slug in normalized, (
            f"Brand slug {slug!r} was truncated for publication="
            f"{publication!r} despite reserved-slot guarantee: {normalized}"
        )

    @pytest.mark.parametrize("publication", _BRANDED_SOURCES)
    def test_brand_slug_at_reserved_first_position(self, publication: str):
        """Reserved-first ordering: brand slug must be at index 0 or 1."""
        payload, _ = _build_payload(publication)
        slug = _expected_slug(publication)

        normalized = _normalize_tags(
            payload.tags,
            _TAGS_MIN,
            _TAGS_MAX,
            reserved=_brand_reserved(payload),
        )

        assert slug in normalized[:2], (
            f"Brand slug {slug!r} not in first 2 reserved positions for "
            f"publication={publication!r}: {normalized}"
        )


# ---------------------------------------------------------------------------
# Liveness × branded coverage
# ---------------------------------------------------------------------------

# Typical archive URL per branded slug. The YAML registry holds slugs only
# (no URL field); this map is the test-local source of truth and is
# deliberately aligned with `_SAMPLE_URLS` in `test_router_branded_sources.py`
# so the two suites move together. Where YAML is missing URL metadata, we
# default to `https://<slug>.substack.com/p/test-post`.
_TYPICAL_ARCHIVE_URLS: dict[str, str] = {
    "stratechery": "https://stratechery.com/2024/the-ai-unbundling/",
    "platformer": "https://www.platformer.news/substack-nazi-push-notification/",
    "lennysnewsletter": "https://lennysnewsletter.substack.com/p/how-the-best-pms-prioritize",
    "notboring": "https://notboring.substack.com/p/the-great-online-game",
    "thedispatch": "https://thedispatch.substack.com/p/the-dispatch-friday",
    "beehiiv": "https://product.beehiiv.com/p/introducing-email-boosts",
    "organic synthesis": "https://organicsynthesis.beehiiv.com/p/organic-synthesis-beehiiv",
    "pragmatic engineer": "https://newsletter.pragmaticengineer.com/p/the-product-minded-engineer",
    "benedict evans": "https://benedictevans.substack.com/p/ai-and-the-automation-of-work",
    "one useful thing": "https://oneusefulthing.substack.com/p/on-speaking-to-ai",
    "astral codex ten": "https://astralcodexten.substack.com/p/your-book-review-the-educated-mind",
}


def _typical_url_for(publication: str) -> str:
    """Lookup canonical URL or synthesize a substack default."""
    if publication in _TYPICAL_ARCHIVE_URLS:
        return _TYPICAL_ARCHIVE_URLS[publication]
    slug = re.sub(r"[^a-z0-9]+", "", publication.lower())
    return f"https://{slug}.substack.com/p/test-post"


class TestBrandedLiveness:
    """Every branded source's typical archive URL is treated as live; the
    canonical /unsubscribe and /archive/deleted variants are dead."""

    @pytest.mark.parametrize("publication", _BRANDED_SOURCES)
    def test_typical_archive_url_is_live(self, publication: str):
        url = _typical_url_for(publication)
        alive, reason = is_live_newsletter(url, html=None)
        assert alive is True, (
            f"Typical archive URL for {publication!r} ({url}) was flagged "
            f"dead (reason={reason!r}) — liveness probe is over-matching."
        )
        assert reason == "ok"

    @pytest.mark.parametrize("publication", _BRANDED_SOURCES)
    def test_unsubscribe_path_is_dead(self, publication: str):
        # Build an /unsubscribe URL on the same host as the typical archive
        # URL (path-based dead heuristic only inspects the path component).
        base = _typical_url_for(publication)
        # Drop the path, attach /unsubscribe.
        # urlparse handles this; constructing manually is simpler:
        host_part = base.split("//", 1)[1].split("/", 1)[0]
        url = f"https://{host_part}/unsubscribe"
        alive, reason = is_live_newsletter(url, html=None)
        assert alive is False, (
            f"/unsubscribe variant for {publication!r} ({url}) leaked through "
            f"as alive (reason={reason!r})."
        )
        assert reason == "dead"

    @pytest.mark.parametrize("publication", _BRANDED_SOURCES)
    def test_archive_deleted_path_is_dead(self, publication: str):
        base = _typical_url_for(publication)
        host_part = base.split("//", 1)[1].split("/", 1)[0]
        url = f"https://{host_part}/archive/deleted"
        alive, reason = is_live_newsletter(url, html=None)
        assert alive is False, (
            f"/archive/deleted variant for {publication!r} ({url}) leaked "
            f"through as alive (reason={reason!r})."
        )
        assert reason == "dead"
