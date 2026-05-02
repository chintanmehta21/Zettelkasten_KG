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
    expected = {
        "website/features/user_home/js/home.js": ["home:add-zettel", "home:create-kasten"],
        "website/features/user_zettels/js/user_zettels.js": ["my-zettels:add-zettel"],
        "website/features/user_kastens/js/user_kastens.js": ["my-kastens:create-kasten"],
        "website/features/knowledge_graph/js/kasten_modal.js": ["knowledge-graph:create-kasten"],
        "website/features/user_rag/js/user_rag.js": ["rag:ask-question"],
    }

    for path, markers in expected.items():
        js = Path(path).read_text(encoding="utf-8")
        assert "quota_exhausted" in js, path
        assert "openPurchase" in js, path
        assert "resumeAction" in js, path
        for marker in markers:
            assert marker in js, path

