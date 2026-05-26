import json
import logging

import httpx
import pytest

from website.features.summarization_engine.source_ingest.github.api_client import (
    GitHubApiClient,
    _HttpError,
)


@pytest.mark.asyncio
async def test_github_api_client_get_enables_redirect_following(monkeypatch):
    captured = {}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            captured["follow_redirects"] = kwargs.get("follow_redirects")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            captured["url"] = url
            return DummyResponse()

    monkeypatch.setattr(
        "website.features.summarization_engine.source_ingest.github.api_client.httpx.AsyncClient",
        DummyClient,
    )

    client = GitHubApiClient(
        token="",
        base_url="https://api.github.com",
        timeout_sec=15,
    )
    payload = await client._get("/repos/tiangolo/typer")

    assert payload == {"ok": True}
    assert captured["follow_redirects"] is True
    assert captured["url"].endswith("/repos/tiangolo/typer")


# Fetcher inventory: (method name, args after slug, expected default on swallow).
_FETCHERS: list[tuple[str, tuple, object]] = [
    ("fetch_pages_url", (), None),
    ("fetch_workflows", (), (False, 0)),
    ("fetch_releases", (5,), []),
    ("fetch_languages", (), []),
    ("fetch_root_dir_signals", (), {}),
]


def _patch_get_to_raise(monkeypatch, exc):
    async def _bad_get(self, path):
        raise exc

    monkeypatch.setattr(
        "website.features.summarization_engine.source_ingest.github.api_client."
        "GitHubApiClient._get",
        _bad_get,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fn_name,extra_args,default",
    _FETCHERS,
    ids=[name for name, _, _ in _FETCHERS],
)
@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("conn refused"),
        httpx.ReadError("read fail"),
        _HttpError(404),
        json.JSONDecodeError("bad", "doc", 0),
    ],
    ids=["ConnectError", "ReadError", "_HttpError404", "JSONDecodeError"],
)
async def test_github_fetchers_swallow_expected_exceptions(
    monkeypatch, caplog, fn_name, extra_args, default, exc
):
    """Each fetcher's expected-error set: network / HTTP / JSON.
    Return type-appropriate default AND log at WARN with exception class name.
    The log is the diagnostic surface that was missing before PR #115 — silent
    swallow made GitHub-shape regressions invisible until the summarizer
    reported "low-confidence extraction" on every URL.
    """
    _patch_get_to_raise(monkeypatch, exc)
    client = GitHubApiClient(
        token="", base_url="https://api.github.com", timeout_sec=5
    )
    method = getattr(client, fn_name)

    with caplog.at_level(logging.WARNING):
        result = await method("owner/repo", *extra_args)

    assert result == default
    assert any(
        type(exc).__name__ in (record.getMessage() or "")
        for record in caplog.records
    ), (
        f"expected log message containing {type(exc).__name__}; "
        f"got {[r.getMessage() for r in caplog.records]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fn_name,extra_args,_default",
    _FETCHERS,
    ids=[name for name, _, _ in _FETCHERS],
)
async def test_github_fetchers_propagate_unexpected_exceptions(
    monkeypatch, fn_name, extra_args, _default
):
    """RuntimeError / TypeError / similar = programmer bugs or framework
    failures. They MUST propagate so the summarizer surfaces the issue
    instead of returning "low-confidence" empty defaults forever.
    Pins the narrowing introduced by PR #115.
    """
    _patch_get_to_raise(monkeypatch, RuntimeError("unexpected programmer error"))
    client = GitHubApiClient(
        token="", base_url="https://api.github.com", timeout_sec=5
    )
    method = getattr(client, fn_name)

    with pytest.raises(RuntimeError, match="unexpected programmer error"):
        await method("owner/repo", *extra_args)
