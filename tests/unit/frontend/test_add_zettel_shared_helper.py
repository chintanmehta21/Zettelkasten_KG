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
        ROOT / "website" / "mobile" / "js" / "summarizer.js",
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


def test_logged_in_surfaces_expose_document_upload_paperclip():
    surfaces = [
        (
            ROOT / "website" / "features" / "user_home" / "index.html",
            ROOT / "website" / "features" / "user_home" / "js" / "home.js",
            ROOT / "website" / "features" / "user_home" / "css" / "home.css",
            "home-document",
        ),
        (
            ROOT / "website" / "features" / "user_zettels" / "index.html",
            ROOT / "website" / "features" / "user_zettels" / "js" / "user_zettels.js",
            ROOT / "website" / "features" / "user_zettels" / "css" / "user_zettels.css",
            "zettels-document",
        ),
    ]

    for html_path, js_path, css_path, action_id in surfaces:
        html = html_path.read_text(encoding="utf-8")
        js = js_path.read_text(encoding="utf-8")
        css = css_path.read_text(encoding="utf-8")

        assert 'id="add-document-input"' in html, html_path
        assert 'id="add-document-btn"' in html, html_path
        assert "accept=\".pdf,.txt,.md,.markdown,.docx" in html, html_path
        assert 'id="add-url-input" class="home-add-input"' in html, html_path
        assert 'id="add-url-input" class="home-add-input" placeholder="https://…" aria-label="URL to capture" required' not in html
        assert "uploadDocument({" in js, js_path
        assert action_id in js, js_path
        assert ".home-add-document-btn" in css, css_path


def test_mobile_page_exposes_document_upload_paperclip():
    html = (ROOT / "website" / "mobile" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "website" / "mobile" / "js" / "summarizer.js").read_text(encoding="utf-8")
    css = (ROOT / "website" / "mobile" / "css" / "mobile.css").read_text(encoding="utf-8")

    assert 'id="document-input"' in html
    assert 'id="document-upload-btn"' in html
    assert "accept=\".pdf,.txt,.md,.markdown,.docx" in html
    assert 'id="url-input"' in html
    assert 'id="url-input" placeholder="Paste a URL..." required' not in html
    assert "uploadDocument({" in js
    assert "mobile-document" in js
    assert ".m-document-btn" in css


def test_all_add_zettel_frontend_entrypoints_have_document_upload():
    entrypoints = {
        "desktop_landing": (
            ROOT / "website" / "static" / "index.html",
            ROOT / "website" / "static" / "js" / "app.js",
            "document-upload-btn",
            "landing-document",
        ),
        "mobile_landing": (
            ROOT / "website" / "mobile" / "index.html",
            ROOT / "website" / "mobile" / "js" / "summarizer.js",
            "document-upload-btn",
            "mobile-document",
        ),
        "home": (
            ROOT / "website" / "features" / "user_home" / "index.html",
            ROOT / "website" / "features" / "user_home" / "js" / "home.js",
            "add-document-btn",
            "home-document",
        ),
        "my_zettels": (
            ROOT / "website" / "features" / "user_zettels" / "index.html",
            ROOT / "website" / "features" / "user_zettels" / "js" / "user_zettels.js",
            "add-document-btn",
            "zettels-document",
        ),
    }

    for name, (html_path, js_path, button_id, action_id) in entrypoints.items():
        html = html_path.read_text(encoding="utf-8")
        js = js_path.read_text(encoding="utf-8")
        assert f'id="{button_id}"' in html, name
        assert 'type="file"' in html, name
        assert "uploadDocument({" in js, name
        assert action_id in js, name
        assert "ZKAddZettel.add" in js, name


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

    assert "/home/css/home.css?v=20260518a" in (
        ROOT / "website" / "features" / "user_home" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/home/js/home.js?v=20260518a" in (
        ROOT / "website" / "features" / "user_home" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/home/zettels/css/user_zettels.css?v=20260518a" in (
        ROOT / "website" / "features" / "user_zettels" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/home/zettels/js/user_zettels.js?v=20260518a" in (
        ROOT / "website" / "features" / "user_zettels" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/m/css/mobile.css?v=20260518a" in (
        ROOT / "website" / "mobile" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/m/js/summarizer.js?v=20260518a" in (
        ROOT / "website" / "mobile" / "index.html"
    ).read_text(encoding="utf-8")


def test_summary_renderers_split_inline_markdown_headings():
    renderers = [
        ROOT / "website" / "static" / "js" / "app.js",
        ROOT / "website" / "mobile" / "js" / "summarizer.js",
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
        ROOT / "website" / "mobile" / "js" / "summarizer.js",
        ROOT / "website" / "features" / "user_home" / "js" / "home.js",
        ROOT / "website" / "features" / "user_zettels" / "js" / "user_zettels.js",
    ]
    offenders = [
        str(path.relative_to(ROOT))
        for path in surfaces
        if ("/api/" + "summarize") in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
