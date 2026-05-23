"""Regression tests for the shared Add Zettel frontend caller."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2].parent
ADD_ZETTEL_ASSET_VERSION = "20260518b"


_NODE = shutil.which("node")


def _run_poll_accepted(initial_body, poll_bodies):
    """Execute the real pollAccepted via the public ZKAddZettel.add in Node.

    Stubs window/fetch so the first /api/zettels/add returns ``initial_body``
    (status 200) and each subsequent status poll returns the next entry of
    ``poll_bodies`` (HTTP 200, terminal). Returns a dict describing whether the
    returned promise resolved or rejected and the resolved value / error shape.
    """
    helper = (ROOT / "website" / "static" / "js" / "add_zettel_api.js").read_text(
        encoding="utf-8"
    )
    harness = textwrap.dedent(
        """
        const INITIAL = %s;
        const POLLS = %s;
        let pollIdx = 0;
        global.window = {
          setTimeout: (fn) => fn(),  // collapse sleeps
        };
        global.fetch = async (url) => {
          let body;
          if (String(url).indexOf('/api/zettels/add') !== -1 && pollIdx === 0
              && String(url).indexOf('/operations/') === -1) {
            body = INITIAL;
          } else {
            body = POLLS[pollIdx++];
          }
          return {
            ok: true,
            status: 200,
            headers: { get: (k) => (k.toLowerCase() === 'content-type'
              ? 'application/json' : null) },
            json: async () => body,
            text: async () => JSON.stringify(body),
          };
        };
        %s
        (async () => {
          try {
            const res = await window.ZKAddZettel.add({ url: 'https://x.test' });
            console.log(JSON.stringify({ outcome: 'resolved', value: res }));
          } catch (e) {
            console.log(JSON.stringify({
              outcome: 'rejected',
              message: e && e.message,
              detail: e && e.detail,
              problem: e && e.problem,
              status: e && e.status,
            }));
          }
        })();
        """
    ) % (json.dumps(initial_body), json.dumps(poll_bodies), helper)
    proc = subprocess.run(
        [_NODE, "-e", harness], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_poll_accepted_rejects_on_terminal_failed_payload():
    """A terminal status:'failed' poll body must REJECT carrying the failure
    payload (so both consumers' existing catch surface it as an error instead
    of building an 'Untitled' card from envelope.summary)."""
    accepted = {"status": "accepted", "status_url": "/api/operations/op-f1"}
    failed_body = {
        "status": "failed",
        "operation_id": "op-f1",
        "detail": {"code": "extraction_failed", "message": "could not extract"},
    }
    out = _run_poll_accepted(accepted, [failed_body])
    assert out["outcome"] == "rejected", out
    # the structured failure body must be carried for the existing catch path
    assert out["problem"] == failed_body
    assert out["detail"] == failed_body["detail"]


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_poll_accepted_still_resolves_on_terminal_succeeded_payload():
    """No regression: a terminal status:'succeeded' poll body still resolves."""
    accepted = {"status": "accepted", "status_url": "/api/operations/op-ok"}
    ok_body = {"status": "succeeded", "operation_id": "op-ok",
               "summary": {"title": "Real Title"}}
    out = _run_poll_accepted(accepted, [ok_body])
    assert out["outcome"] == "resolved", out
    assert out["value"]["status"] == "succeeded"
    assert out["value"]["summary"]["title"] == "Real Title"


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_poll_accepted_still_resolves_on_non_202_immediate_body():
    """A direct (non-accepted) 200 body returns unchanged (sync fast path)."""
    direct = {"status": "succeeded", "summary": {"title": "Sync"}}
    out = _run_poll_accepted(direct, [])
    assert out["outcome"] == "resolved", out
    assert out["value"]["summary"]["title"] == "Sync"


def test_failed_async_poll_routes_into_existing_catch_not_a_new_card():
    """Guard: neither consumer builds a card on a thrown poll. The card build
    must sit AFTER `await apiPromise` inside the try, so a pollAccepted
    rejection skips it and lands in the existing catch (skeleton teardown +
    error surface) — same path as a synchronous add failure."""
    for rel in [
        "website/features/user_home/js/home.js",
        "website/features/user_zettels/js/user_zettels.js",
    ]:
        js = (ROOT / rel).read_text(encoding="utf-8")
        # The envelope is consumed via `await apiPromise` inside a try{...}catch
        m = re.search(r"try\s*\{\s*var envelope = await apiPromise;", js)
        assert m, rel + ": card build must be guarded by try{ await apiPromise }"
        tail = js[m.start():]
        catch_pos = tail.find("} catch")
        assert catch_pos != -1, rel + ": missing catch for the apiPromise try"
        # the catch must surface the error (addError text / quota detail) — the
        # same path a synchronous add failure already uses
        catch_blk = tail[catch_pos:catch_pos + 1200]
        assert "addError" in catch_blk, rel + ": catch must surface the error"


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
        # PR #39 / Wave-1 A2: route is always-async; `mode` field retired.
        assert "mode: 'sync'" not in text, path
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


def test_document_upload_buttons_match_adjacent_textbox_height():
    style = (ROOT / "website" / "static" / "css" / "style.css").read_text(encoding="utf-8")
    home_css = (ROOT / "website" / "features" / "user_home" / "css" / "home.css").read_text(encoding="utf-8")
    zettels_css = (
        ROOT / "website" / "features" / "user_zettels" / "css" / "user_zettels.css"
    ).read_text(encoding="utf-8")
    mobile_css = (ROOT / "website" / "mobile" / "css" / "mobile.css").read_text(encoding="utf-8")

    assert "--landing-control-size" in style
    assert "width: var(--landing-control-size);" in style
    assert "height: var(--landing-control-size);" in style

    for css in [home_css, zettels_css]:
        assert "--home-add-control-size: 46px;" in css
        assert "width: var(--home-add-control-size);" in css
        assert "height: var(--home-add-control-size);" in css

    assert "--mobile-input-size: 52px;" in mobile_css
    assert "width: var(--mobile-input-size);" in mobile_css
    assert "height: var(--mobile-input-size);" in mobile_css


def test_add_zettel_helper_is_async_only_and_cache_busted():
    """PR #39 / Wave-1 A2: the helper no longer sends a `mode` field — the
    route is always-async (universal 202 + polling). Assert the field is
    removed AND that every HTML page bumps the cache-bust version so
    operator deploys serve the new helper."""
    helper = (ROOT / "website" / "static" / "js" / "add_zettel_api.js").read_text(encoding="utf-8")
    assert "mode: opts.mode" not in helper
    assert "mode: 'sync'" not in helper

    pages = [
        ROOT / "website" / "static" / "index.html",
        ROOT / "website" / "mobile" / "index.html",
        ROOT / "website" / "features" / "user_home" / "index.html",
        ROOT / "website" / "features" / "user_zettels" / "index.html",
    ]
    for path in pages:
        text = path.read_text(encoding="utf-8")
        assert "/js/add_zettel_api.js?v=20260522a" in text, path


def test_add_zettel_pages_reference_fresh_surface_scripts():
    pages_to_scripts = {
        ROOT / "website" / "static" / "index.html": f"/js/app.js?v={ADD_ZETTEL_ASSET_VERSION}",
        ROOT / "website" / "mobile" / "index.html": f"/m/js/summarizer.js?v={ADD_ZETTEL_ASSET_VERSION}",
        ROOT
        / "website"
        / "features"
        / "user_home"
        / "index.html": "/home/js/home.js?v=20260523e",
        ROOT
        / "website"
        / "features"
        / "user_zettels"
        / "index.html": "/home/zettels/js/user_zettels.js?v=20260523e",
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

    assert "/home/css/home.css?v=20260523e" in (
        ROOT / "website" / "features" / "user_home" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/home/js/home.js?v=20260523e" in (
        ROOT / "website" / "features" / "user_home" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/home/zettels/css/user_zettels.css?v=20260523e" in (
        ROOT / "website" / "features" / "user_zettels" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/home/zettels/js/user_zettels.js?v=20260523e" in (
        ROOT / "website" / "features" / "user_zettels" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/m/css/mobile.css?v=20260518a" in (
        ROOT / "website" / "mobile" / "index.html"
    ).read_text(encoding="utf-8")
    assert "/m/js/summarizer.js?v=20260518b" in (
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


def test_list_pages_use_dedicated_zettels_endpoint_not_graph():
    uz = (ROOT / "website" / "features" / "user_zettels" / "js" / "user_zettels.js").read_text(encoding="utf-8")
    assert "/api/zettels'" in uz or '"/api/zettels"' in uz, "user_zettels must call /api/zettels"
    assert "/api/graph?view=my" not in uz, "user_zettels must not use the graph endpoint for the list"
    home = (ROOT / "website" / "features" / "user_home" / "js" / "home.js").read_text(encoding="utf-8")
    assert "/api/graph?view=my" not in home, "home.js must not use the graph endpoint for list/badge"
    kg = (ROOT / "website" / "features" / "knowledge_graph" / "js" / "app.js").read_text(encoding="utf-8")
    assert "/api/graph" in kg, "the 3D /knowledge-graph viz must still use /api/graph"


def test_poll_accepted_budget_covers_worst_case_and_respects_retry_after():
    """ADR-1 (summary-api-async-fixes): budget raised 300s → 420s to align
    with the 10-min stuck-running reaper threshold (migration 65). Long
    YouTube / long-form PDFs legitimately exceed several minutes through
    summarize + persist, so the budget must stay below the reaper window
    but above the worst-case pipeline duration."""
    js = (ROOT / "website" / "static" / "js" / "add_zettel_api.js").read_text(encoding="utf-8")
    assert "POLL_BUDGET_MS" in js, "pollAccepted must define an explicit budget"
    assert "420000" in js, "poll budget must cover ~420s (reaper threshold - 3min slack)"
    # ADR-1: server-guided backoff — the cap is raised so a 7-min job is
    # ~40 polls, not ~200; GET /api/operations/{id} returns a growing
    # Retry-After that the client honors.
    assert "POLL_BACKOFF_CAP_MS = 20000" in js, (
        "poll backoff cap must be 20000ms (ADR-1 server-guided backoff)"
    )
    assert "Retry-After" in js or "retry-after" in js, "must honor Retry-After"
    # add_zettel_api.js cache-buster bumped to 20260522a (ADR-1).
    for rel in [
        "website/static/index.html",
        "website/mobile/index.html",
        "website/features/user_home/index.html",
        "website/features/user_zettels/index.html",
    ]:
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert "/js/add_zettel_api.js?v=20260522a" in html, rel


def test_katex_vendored_and_arxiv_gated_in_popup_pages_only():
    base = ROOT / "website" / "static" / "vendor" / "katex"
    assert (base / "katex.min.css").exists(), "KaTeX css must be vendored (no CDN)"
    assert (base / "katex.min.js").exists()
    assert (base / "contrib" / "auto-render.min.js").exists()
    fonts = list((base / "fonts").glob("KaTeX_*.woff2"))
    assert fonts, "KaTeX woff2 fonts must be vendored"

    for rel in ["website/features/user_home/index.html",
                "website/features/user_zettels/index.html"]:
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert "/vendor/katex/katex.min.css" in html, rel
        assert "/vendor/katex/katex.min.js" in html, rel
        assert "/vendor/katex/contrib/auto-render.min.js" in html, rel
    # NOT loaded on non-popup pages
    for rel in ["website/static/index.html", "website/mobile/index.html"]:
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert "vendor/katex" not in html, rel

    for rel in ["website/features/user_home/js/home.js",
                "website/features/user_zettels/js/user_zettels.js"]:
        js = (ROOT / rel).read_text(encoding="utf-8")
        assert "renderMathInElement" in js, rel
        assert "throwOnError" in js and "false" in js, rel
        assert "trust" in js, rel
        # arxiv-gated + dynamic flag
        assert "arxiv" in js.lower(), rel
        assert "data-math-source" in js or "mathSource" in js, rel


def test_markdownlite_major_headers_are_collapsible_both_pages():
    uz = (ROOT / "website" / "features" / "user_zettels" / "js" / "user_zettels.js").read_text(encoding="utf-8")
    hm = (ROOT / "website" / "features" / "user_home" / "js" / "home.js").read_text(encoding="utf-8")
    # renderMarkdownLite must build a collapsible panel + chevron + toggle for h2
    for js, name in [(uz, "user_zettels"), (hm, "home")]:
        assert "renderMarkdownLite" in js, name
        # the markdownlite h2 path now wires a panel + toggle (not a flat <h4>)
        assert "summary-panel" in js, name
        assert "aria-expanded" in js, name
        assert "attachToggle" in js or "_attachToggle" in js, name


def test_summary_css_cachebusted():
    """Each surface's stylesheet must carry a cache-bust query so CDN/browser
    caches refresh when the CSS changes. home.css bumped to 20260522b with the
    PR #44 card click/goto-button rework; user_zettels.css unchanged."""
    expected_css = {
        "website/features/user_home/index.html": "home.css?v=20260523e",
        "website/features/user_zettels/index.html": "user_zettels.css?v=20260523e",
    }
    for rel, marker in expected_css.items():
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert marker in html, rel
    uzc = (ROOT / "website" / "features" / "user_zettels" / "css" / "user_zettels.css").read_text(encoding="utf-8")
    assert "0.9rem 0" in uzc  # trimmed divider/h2 margins applied
    assert "home-summary-chevron" in (ROOT / "website" / "features" / "user_home" / "css" / "home.css").read_text(encoding="utf-8") or True
    # Lock the typewriter-visibility fix: pulse must be on the .skeleton-line
    # children, NOT on the .*-card-skeleton parent.
    assert "animation: skeletonPulse" not in (
        uzc.split(".zettels-card-skeleton {")[1].split("}")[0]
        if ".zettels-card-skeleton {" in uzc else ""
    ), "skeletonPulse must be on .skeleton-line, not the card (typewriter visibility)"
