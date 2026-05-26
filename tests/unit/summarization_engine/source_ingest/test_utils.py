"""Tests for source_ingest/utils.py.

PR #115 split the trafilatura import vs. extract catch so a corrupt /
missing install is distinguishable from "page not extractable", and
narrows the runtime-error catch to ValueError/AttributeError/TypeError.
Anything else (RuntimeError / etc.) propagates instead of silently
degrading to BeautifulSoup.
"""
from __future__ import annotations

import logging
import sys

import pytest

from website.features.summarization_engine.source_ingest.utils import extract_html_text


_SAMPLE_HTML = (
    "<html><head><title>doc title</title>"
    '<meta name="description" content="meta desc">'
    "</head><body><article><p>main article body</p></article></body></html>"
)


def test_extract_html_text_handles_missing_trafilatura(monkeypatch, caplog):
    """trafilatura ImportError → fall back to BeautifulSoup text + log WARN.
    Before PR #115 a missing/corrupt install was indistinguishable from a
    page that trafilatura simply couldn't parse — both returned the
    BeautifulSoup fallback silently.
    """
    monkeypatch.setitem(sys.modules, "trafilatura", None)

    with caplog.at_level(logging.WARNING):
        text, metadata = extract_html_text(_SAMPLE_HTML)

    assert "main article body" in text
    assert metadata.get("title") == "doc title"
    assert any(
        "ImportError" in record.getMessage()
        or "trafilatura" in record.getMessage().lower()
        for record in caplog.records
    )


@pytest.mark.parametrize("exc_cls", [ValueError, AttributeError, TypeError])
def test_extract_html_text_handles_trafilatura_extract_errors(
    monkeypatch, caplog, exc_cls
):
    """Known runtime-error classes from trafilatura.extract → fall back + log.
    These are the actual classes trafilatura can raise on malformed HTML;
    anything else means a real bug and must propagate.
    """
    import trafilatura

    def _bad_extract(html, **kwargs):
        raise exc_cls("trafilatura blew up")

    monkeypatch.setattr(trafilatura, "extract", _bad_extract)

    with caplog.at_level(logging.WARNING):
        text, _meta = extract_html_text(_SAMPLE_HTML)

    assert "main article body" in text
    assert any(exc_cls.__name__ in record.getMessage() for record in caplog.records)


def test_extract_html_text_propagates_unexpected_trafilatura_error(monkeypatch):
    """RuntimeError / KeyError / etc. = programmer or framework bug. They
    MUST surface so the operator sees the failure instead of receiving a
    BeautifulSoup-quality fallback that masks the issue.
    """
    import trafilatura

    def _bad_extract(html, **kwargs):
        raise RuntimeError("unexpected blow-up")

    monkeypatch.setattr(trafilatura, "extract", _bad_extract)

    with pytest.raises(RuntimeError, match="unexpected blow-up"):
        extract_html_text(_SAMPLE_HTML)


def test_extract_html_text_happy_path():
    """Regression guard: trafilatura+BS4 path returns title metadata and
    extracted body. Catches a future refactor that breaks the happy path.
    """
    text, metadata = extract_html_text(_SAMPLE_HTML)
    assert "main article body" in text
    assert metadata.get("title") == "doc title"
    assert metadata.get("description") == "meta desc"
