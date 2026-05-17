from __future__ import annotations

from pathlib import Path


def test_add_zettel_route_uses_module_runner():
    source = open("website/api/zettels_routes.py", encoding="utf-8").read()
    assert "website.api.module_runners.summarization" in source
    assert "run_add_zettel_pipeline(" in source


def test_summarization_runner_has_cli_entrypoint():
    source = open("website/api/module_runners/summarization.py", encoding="utf-8").read()
    assert "argparse.ArgumentParser" in source
    assert "if __name__ == \"__main__\"" in source
    assert "run_add_zettel_pipeline(" in source


def test_cli_env_loader_reads_api_env_and_defaults_to_v2(tmp_path, monkeypatch):
    from website.api.module_runners import summarization

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DB_SCHEMA_VERSION", raising=False)

    Path("api_env").write_text("key-one\nGEMINI_API_KEY=key-two\n", encoding="utf-8")

    summarization._load_local_env()

    assert summarization.os.environ["GEMINI_API_KEYS"] == "key-one,key-two"
    assert summarization.os.environ["DB_SCHEMA_VERSION"] == "v2"
