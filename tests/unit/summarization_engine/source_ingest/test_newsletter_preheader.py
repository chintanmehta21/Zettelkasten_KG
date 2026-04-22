from website.features.summarization_engine.source_ingest.newsletter.preheader import (
    extract_preheader,
)


def test_explicit_preheader_meta_tag():
    html = (
        '<html><head><meta name="preheader" content="This is the preheader text.">'
        "</head><body><p>body</p></body></html>"
    )
    assert extract_preheader(html, fallback_chars=150) == "This is the preheader text."


def test_fallback_first_n_chars_of_body():
    html = "<html><body><p>Opening paragraph sets context. " + ("x" * 200) + "</p></body></html>"
    result = extract_preheader(html, fallback_chars=100)
    assert len(result) <= 100
    assert "Opening paragraph" in result


def test_no_body_returns_empty():
    assert extract_preheader("<html></html>", fallback_chars=150) == ""
