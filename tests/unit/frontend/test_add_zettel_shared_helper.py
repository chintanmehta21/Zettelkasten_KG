"""Regression tests for the shared Add Zettel frontend caller."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2].parent


def test_all_add_zettel_surfaces_use_shared_helper():
    helper = ROOT / "website" / "static" / "js" / "add_zettel_api.js"
    assert helper.exists()
    helper_text = helper.read_text(encoding="utf-8")
    assert "window.ZKAddZettel" in helper_text
    assert "content-type" in helper_text.lower()
    assert "/api/zettels/add" in helper_text
    assert "/api/zettels/add/document" in helper_text
    assert "uploadDocument" in helper_text

    surfaces = [
        ROOT / "website" / "static" / "js" / "app.js",
        ROOT / "website" / "features" / "user_home" / "js" / "home.js",
        ROOT / "website" / "features" / "user_zettels" / "js" / "user_zettels.js",
    ]
    for path in surfaces:
        text = path.read_text(encoding="utf-8")
        assert "ZKAddZettel.add" in text, path
        assert "mode: 'sync'" in text, path
        assert "mode: 'auto'" not in text, path


def test_landing_page_exposes_document_upload_paperclip():
    html = (ROOT / "website" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "website" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "website" / "static" / "css" / "style.css").read_text(encoding="utf-8")

    assert 'id="document-input"' in html
    assert 'id="document-upload-btn"' in html
    assert "accept=\".pdf,.txt,.md,.markdown,.docx" in html
    assert "uploadDocument({" in js
    assert "landing-document" in js
    assert ".document-upload-btn" in css


def test_add_zettel_helper_defaults_to_sync_and_cache_busted():
    helper = (ROOT / "website" / "static" / "js" / "add_zettel_api.js").read_text(encoding="utf-8")
    assert "mode: opts.mode || 'sync'" in helper

    pages = [
        ROOT / "website" / "static" / "index.html",
        ROOT / "website" / "mobile" / "index.html",
        ROOT / "website" / "features" / "user_home" / "index.html",
        ROOT / "website" / "features" / "user_zettels" / "index.html",
    ]
    for path in pages:
        text = path.read_text(encoding="utf-8")
        assert "/js/add_zettel_api.js?v=20260517a" in text, path


def test_summary_renderers_split_inline_markdown_headings():
    renderers = [
        ROOT / "website" / "static" / "js" / "app.js",
        ROOT / "website" / "features" / "user_home" / "js" / "home.js",
        ROOT / "website" / "features" / "user_zettels" / "js" / "user_zettels.js",
    ]
    for path in renderers:
        text = path.read_text(encoding="utf-8")
        assert "function normalizeSummaryMarkdown" in text, path
        assert r"([^\n])\s+(#{2,6}\s+)" in text, path


def test_add_zettel_surfaces_do_not_call_legacy_summarize_directly():
    surfaces = [
        ROOT / "website" / "static" / "js" / "app.js",
        ROOT / "website" / "features" / "user_home" / "js" / "home.js",
        ROOT / "website" / "features" / "user_zettels" / "js" / "user_zettels.js",
    ]
    offenders = [
        str(path.relative_to(ROOT))
        for path in surfaces
        if ("/api/" + "summarize") in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
