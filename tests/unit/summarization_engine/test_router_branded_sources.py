"""Regression coverage: every branded newsletter source routes to SourceType.NEWSLETTER.

Driven by ``docs/summary_eval/_config/branded_newsletter_sources.yaml`` so that adding
a publication there auto-requires a canonical sample URL here — mirroring the lesson
from ``docs/summary_eval/newsletter/final_scorecard.md`` that a pragmatic-engineer URL
was misrouted to the generic web summarizer before branded router coverage existed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.core.router import detect_source_type


_REPO_ROOT = Path(__file__).resolve().parents[3]
_YAML_PATH = _REPO_ROOT / "docs" / "summary_eval" / "_config" / "branded_newsletter_sources.yaml"

# Minimum branded source count documented in the Newsletter final scorecard (Plan 9).
_MIN_BRANDED_SOURCES = 11

# Canonical sample URL per branded publication slug. These URLs are chosen so the
# current production router (``website/features/summarization_engine/core/router.py``)
# can classify them via one of: custom-domain whitelist, substack.com suffix, beehiiv.com
# suffix, or ``.news`` + ``/p/`` heuristic.
#
# Keep this in sync with ``branded_newsletter_sources.yaml``. A missing entry fails
# ``test_every_branded_source_has_sample_url`` — that is the forcing function.
_SAMPLE_URLS: dict[str, str] = {
    "stratechery": "https://stratechery.com/2024/the-ai-unbundling/",
    "platformer": "https://www.platformer.news/substack-nazi-push-notification/",
    "lennysnewsletter": "https://lennysnewsletter.substack.com/p/how-the-best-pms-prioritize",
    # Not Boring publishes on both `notboring.co` (custom domain) and `notboring.substack.com`.
    # Router only recognises the substack-hosted form today; see surfaced-gap note in report.
    "notboring": "https://notboring.substack.com/p/the-great-online-game",
    "thedispatch": "https://thedispatch.substack.com/p/the-dispatch-friday",
    "beehiiv": "https://product.beehiiv.com/p/introducing-email-boosts",
    "organic synthesis": "https://organicsynthesis.beehiiv.com/p/organic-synthesis-beehiiv",
    "pragmatic engineer": "https://newsletter.pragmaticengineer.com/p/the-product-minded-engineer",
    "benedict evans": "https://benedictevans.substack.com/p/ai-and-the-automation-of-work",
    "one useful thing": "https://oneusefulthing.substack.com/p/on-speaking-to-ai",
    "astral codex ten": "https://astralcodexten.substack.com/p/your-book-review-the-educated-mind",
}


def _load_branded_sources() -> list[str]:
    with _YAML_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    sources = data.get("branded_sources", [])
    if not isinstance(sources, list):
        raise AssertionError(
            f"branded_sources must be a list, got {type(sources).__name__}"
        )
    return [str(s).lower() for s in sources]


_BRANDED_SOURCES = _load_branded_sources()


def test_yaml_exists_and_is_readable():
    assert _YAML_PATH.exists(), f"Missing branded-sources YAML at {_YAML_PATH}"
    assert _BRANDED_SOURCES, "branded_sources list is empty"


def test_branded_source_count_meets_scorecard_minimum():
    assert len(_BRANDED_SOURCES) >= _MIN_BRANDED_SOURCES, (
        f"branded_newsletter_sources.yaml has {len(_BRANDED_SOURCES)} entries; "
        f"final scorecard requires >= {_MIN_BRANDED_SOURCES}. If you intentionally "
        f"removed a source, update _MIN_BRANDED_SOURCES and the scorecard."
    )


def test_every_branded_source_has_sample_url():
    missing = [slug for slug in _BRANDED_SOURCES if slug not in _SAMPLE_URLS]
    assert not missing, (
        f"Branded sources added to YAML without a canonical sample URL in the test "
        f"fixture: {missing}. Add an entry to _SAMPLE_URLS so router regression is "
        f"enforced for the new publication."
    )


@pytest.mark.parametrize("slug", _BRANDED_SOURCES)
def test_branded_source_routes_to_newsletter(slug: str):
    url = _SAMPLE_URLS.get(slug)
    assert url is not None, f"No sample URL registered for branded slug '{slug}'"
    actual = detect_source_type(url)
    assert actual == SourceType.NEWSLETTER, (
        f"Router misrouted branded source '{slug}': URL={url!r} classified as "
        f"{actual!r}, expected SourceType.NEWSLETTER. This is the exact regression "
        f"that caused pragmatic-engineer to be summarized as generic web."
    )


def test_generic_web_url_is_not_classified_as_newsletter():
    # Negative control: a plain article URL on an unrelated domain must NOT be
    # mistakenly routed as a newsletter.
    url = "https://example.com/article/some-plain-post"
    actual = detect_source_type(url)
    assert actual != SourceType.NEWSLETTER, (
        f"Negative control failed: {url!r} was routed to NEWSLETTER (got {actual!r}). "
        f"Router is over-matching; the newsletter domain list or /p/ heuristic is too broad."
    )
    assert actual == SourceType.WEB
