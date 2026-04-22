from website.features.summarization_engine.source_ingest.newsletter.site_extractors import (
    StructuredNewsletter,
    extract_structured,
)


_SUBSTACK_HTML = """
<html><head><meta property="og:site_name" content="Example Substack"></head><body>
<article>
<h1 class="post-title">The Real Question About AI Moats</h1>
<h3 class="subtitle">Why scale doesn't translate to durability</h3>
<div class="body markup">
<p>Opening paragraph here.</p>
<p>Second paragraph.</p>
</div>
<div class="post-footer">
<a href="https://example.substack.com/subscribe">Subscribe now</a>
</div>
</article>
</body></html>
"""


def test_substack_extracts_title_subtitle_body():
    result = extract_structured(
        _SUBSTACK_HTML,
        url="https://example.substack.com/p/ai-moats",
    )
    assert isinstance(result, StructuredNewsletter)
    assert result.site == "substack"
    assert result.title == "The Real Question About AI Moats"
    assert "scale doesn't translate" in result.subtitle
    assert "Opening paragraph" in result.body_text
    assert any("subscribe" in cta.lower() for cta in result.cta_links)


def test_non_substack_returns_empty_structured():
    result = extract_structured(
        "<html><body><p>hi</p></body></html>",
        url="https://random.example.com/",
    )
    assert result.site == "unknown"
    assert result.title == ""
