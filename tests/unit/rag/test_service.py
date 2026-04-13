from __future__ import annotations

from pathlib import Path

from website.features.rag_pipeline import service


def test_load_example_queries_returns_clean_strings(tmp_path, monkeypatch):
    example_file = tmp_path / "example_queries.json"
    example_file.write_text('["  First query  ", "", 42, "Second query"]', encoding="utf-8")
    monkeypatch.setattr(service, "_EXAMPLE_QUERIES", Path(example_file))
    service.load_example_queries.cache_clear()

    try:
        assert service.load_example_queries() == ["First query", "Second query"]
    finally:
        service.load_example_queries.cache_clear()


def test_load_example_queries_returns_empty_for_invalid_json(tmp_path, monkeypatch):
    example_file = tmp_path / "example_queries.json"
    example_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(service, "_EXAMPLE_QUERIES", Path(example_file))
    service.load_example_queries.cache_clear()

    try:
        assert service.load_example_queries() == []
    finally:
        service.load_example_queries.cache_clear()
