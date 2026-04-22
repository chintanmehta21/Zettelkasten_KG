from website.features.summarization_engine.source_ingest.newsletter.cta import (
    extract_ctas,
)


def test_matches_keyword_regex():
    html = """
    <a href="/sub">Subscribe now</a>
    <a href="/x">random link</a>
    <a href="/learn">Learn more</a>
    """
    ctas = extract_ctas(html, keyword_regex="subscribe|learn more", max_count=5)
    assert len(ctas) == 2
    assert any("Subscribe" in c.text for c in ctas)
    assert any("Learn more" in c.text for c in ctas)


def test_respects_max_count():
    html = "".join(f'<a href="/x{i}">Subscribe {i}</a>' for i in range(10))
    ctas = extract_ctas(html, keyword_regex="subscribe", max_count=3)
    assert len(ctas) == 3


def test_strips_boilerplate():
    html = '<a href="/unsub">Unsubscribe</a><a href="/sub">Subscribe</a>'
    ctas = extract_ctas(html, keyword_regex="subscribe", max_count=5)
    assert len(ctas) == 1
    assert "Unsubscribe" not in ctas[0].text
