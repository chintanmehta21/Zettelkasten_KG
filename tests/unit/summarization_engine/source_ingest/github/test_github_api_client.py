import pytest

from website.features.summarization_engine.source_ingest.github.api_client import (
    GitHubApiClient,
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
