from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _python_sources():
    return [path for path in ROOT.rglob("*.py") if "pytests" not in path.parts]


def test_no_pageindex_chat_or_legacy_cloud_api_usage():
    forbidden = ("chat_completions", "submit_document", "enable_citations", "/retrieval/", "/chat/completions")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in _python_sources())
    for token in forbidden:
        assert token not in combined
    assert "https://api.pageindex.ai/markdown/" in combined


def test_pageindex_adapter_is_only_direct_pageindex_importer():
    offenders = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        if "from pageindex import" in text and path.name != "pageindex_adapter.py":
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_pageindex_adapter_has_local_markdown_fallback():
    text = (ROOT / "pageindex_adapter.py").read_text(encoding="utf-8")
    assert "_LocalMarkdownPageIndexClient" in text


def test_no_secret_file_reads_outside_secrets_module():
    offenders = []
    for path in _python_sources():
        if path.name == "secrets.py":
            continue
        if "login_details.txt" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_eval_artifacts_path_is_pageindex_knowledge_management():
    config_text = (ROOT / "config.py").read_text(encoding="utf-8")
    assert '"PageIndex"' in config_text
    assert '"knowledge-management"' in config_text
    assert '"iter-01"' in config_text
