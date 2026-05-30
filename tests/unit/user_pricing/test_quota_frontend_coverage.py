from __future__ import annotations

from pathlib import Path


def test_metered_pages_load_purchase_launcher() -> None:
    for path in [
        "website/features/user_home/index.html",
        "website/features/user_zettels/index.html",
        "website/features/user_kastens/index.html",
        "website/features/user_rag/index.html",
        "website/features/knowledge_graph/index.html",
    ]:
        html = Path(path).read_text(encoding="utf-8")
        assert "/user-pricing/js/purchase_launcher.js" in html, path


def test_metered_frontend_callers_handle_quota_exhausted() -> None:
    """Every metered page must surface 402 quota_exhausted through ZKQuotaGate.show.

    Phase-9 update (PR #18): the 6 inline 402 handlers were migrated from
    ``window.ZKPricing.openPurchase`` to ``window.ZKQuotaGate.show`` (the new
    reusable popup that chains to ZKPricing internally). The contract for
    every site is identical: detect ``code === 'quota_exhausted'``, call
    ``ZKQuotaGate.show({detail, source, resumeAction, onResume})``.
    """
    expected = {
        "website/features/user_home/js/home.js": ["home:add-zettel", "home:create-kasten"],
        "website/features/user_zettels/js/user_zettels.js": ["my-zettels:add-zettel"],
        "website/features/user_kastens/js/user_kastens.js": ["my-kastens:create-kasten"],
        "website/features/knowledge_graph/js/kasten_modal.js": ["knowledge-graph:create-kasten"],
        "website/features/user_rag/js/user_rag.js": ["rag:ask-question"],
    }

    for path, markers in expected.items():
        js = Path(path).read_text(encoding="utf-8")
        # A metered caller detects quota exhaustion either via the inline
        # `code === 'quota_exhausted'` check OR via the centralized
        # ZKQuotaGate.extractQuotaDetail recognizer (PR #128 moved the literal
        # into quota_gate.js for the home / my-zettels add surfaces).
        assert ("quota_exhausted" in js) or ("extractQuotaDetail" in js), path
        assert "ZKQuotaGate" in js, path
        assert "resumeAction" in js, path
        for marker in markers:
            assert marker in js, path


def test_metered_pages_load_quota_gate_assets() -> None:
    """Every metered page that loads purchase_launcher must also load the
    ZKQuotaGate JS + CSS — otherwise the inline 402 handlers silently fail
    (window.ZKQuotaGate is undefined and the fallback path is /pricing).
    """
    for path in [
        "website/features/user_home/index.html",
        "website/features/user_zettels/index.html",
        "website/features/user_kastens/index.html",
        "website/features/user_rag/index.html",
        "website/features/knowledge_graph/index.html",
    ]:
        html = Path(path).read_text(encoding="utf-8")
        assert "/functional-gates/js/quota_gate.js" in html, path
        assert "/functional-gates/css/quota_gate.css" in html, path

