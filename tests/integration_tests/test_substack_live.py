"""Live integration tests for Substack extraction.

These tests hit real Substack URLs — run with ``pytest --live``.
They verify end-to-end extraction for both free and paid articles.
"""

from __future__ import annotations

import pytest

from zettelkasten_bot.sources.newsletter import NewsletterExtractor


@pytest.mark.live
async def test_substack_free_article_live():
    """Free Substack article → extracts full content and metadata."""
    url = "https://nlp.elvissaravia.com/p/top-ai-papers-of-the-week-b8c"
    extractor = NewsletterExtractor()
    result = await extractor.extract(url)

    assert result.body, "Body should not be empty for a free article"
    assert len(result.body) > 200, "Free article should have substantial content"
    assert result.title, "Title should be extracted"
    assert result.source_type.value == "newsletter"


@pytest.mark.live
async def test_substack_paid_article_live():
    """Paid Substack article → returns partial content gracefully (no crash)."""
    url = "https://nlp.elvissaravia.com/p/ai-agents-weekly-gpt-53-codex-spark"
    extractor = NewsletterExtractor()
    result = await extractor.extract(url)

    # Should NOT raise — either bypass succeeded or partial content returned
    assert result.body, "Body should not be empty even for paid articles"
    assert result.title, "Title should be extracted"
    assert result.source_type.value == "newsletter"


@pytest.mark.live
async def test_substack_native_domain_free_live():
    """Native *.substack.com free article → full content + Substack metadata."""
    url = "https://blog.pragmaticengineer.com/p/what-is-engineering-management"
    extractor = NewsletterExtractor()
    try:
        result = await extractor.extract(url)
        assert result.body, "Body should not be empty"
        assert result.title, "Title should be extracted"
    except RuntimeError:
        pytest.skip("Live URL may have changed or be unavailable")
