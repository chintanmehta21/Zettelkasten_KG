"""Regression tests for the shared Add Zettel frontend caller."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2].parent
ADD_ZETTEL_ASSET_VERSION = "20260518a"


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
        assert f"/js/add_zettel_api.js?v={ADD_ZETTEL_ASSET_VERSION}" in text, path


def test_add_zettel_pages_reference_fresh_surface_scripts():
    pages_to_scripts = {
        ROOT / "website" / "static" / "index.html": f"/js/app.js?v={ADD_ZETTEL_ASSET_VERSION}",
        ROOT / "website" / "mobile" / "index.html": f"/m/js/summarizer.js?v={ADD_ZETTEL_ASSET_VERSION}",
        ROOT
        / "website"
        / "features"
        / "user_home"
        / "index.html": f"/home/js/home.js?v={ADD_ZETTEL_ASSET_VERSION}",
        ROOT
        / "website"
        / "features"
        / "user_zettels"
        / "index.html": f"/home/zettels/js/user_zettels.js?v={ADD_ZETTEL_ASSET_VERSION}",
    }
    stale_add_zettel_versions = ("20260404", "20260425", "20260512", "20260517")

    for page, expected_script in pages_to_scripts.items():
        text = page.read_text(encoding="utf-8")
        assert expected_script in text, page
        add_zettel_script_refs = [
            match
            for match in re.findall(r'<script\s+src="([^"]+)"', text)
            if any(
                path in match
                for path in (
                    "/js/add_zettel_api.js",
                    "/js/app.js",
                    "/m/js/summarizer.js",
                    "/home/js/home.js",
                    "/home/zettels/js/user_zettels.js",
                )
            )
        ]
        for stale_version in stale_add_zettel_versions:
            assert not any(stale_version in ref for ref in add_zettel_script_refs), page

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
        ROOT / "website" / "mobile" / "js" / "summarizer.js",
    ]
    for path in renderers:
        text = path.read_text(encoding="utf-8")
        assert "function normalizeSummaryMarkdown" in text, path
        # Hardened split: inline ATX heading onto its own block.
        assert r"(\S)[ \t]+(#{2,6})[ \t]+(?=\S)" in text, path
        # Strip a trailing ``#`` run the model appended to a heading line.
        assert r"^(#{2,6} .+?)[ \t]+#+[ \t]*$" in text, path


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


def test_retired_legacy_summarize_pipeline_has_no_tracked_references():
    forbidden_terms = [
        "/api/" + "summarize",
        "website/core/" + "pipeline.py",
        "website.core." + "pipeline",
    ]
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    text_suffixes = {
        ".html",
        ".js",
        ".json",
        ".md",
        ".py",
        ".sql",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
    offenders: list[str] = []
    for relative in tracked:
        path = ROOT / relative
        if path.suffix.lower() not in text_suffixes:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(term in text for term in forbidden_terms):
            offenders.append(relative)

    assert offenders == []
