from __future__ import annotations

import os
from typing import Any

import httpx

from website.experimental_features.nexus.source_ingest.common.models import (
    NexusProvider,
    ProviderArtifact,
    StoredProviderAccount,
)
from website.experimental_features.nexus.source_ingest.reddit.oauth import (
    DEFAULT_USER_AGENT,
    USER_AGENT_ENV,
)

API_BASE_URL = "https://oauth.reddit.com"
REQUEST_TIMEOUT = 20.0


async def ingest_artifacts(
    account: StoredProviderAccount,
    limit: int = 25,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ProviderArtifact]:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    own_client = client is None
    http_client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    try:
        username = await _fetch_username(http_client, account.access_token)
        artifacts: list[ProviderArtifact] = []
        after: str | None = None

        while len(artifacts) < limit:
            remaining = limit - len(artifacts)
            response = await http_client.get(
                f"{API_BASE_URL}/user/{username}/saved",
                params={
                    "limit": min(remaining, 100),
                    "after": after or "",
                    "raw_json": 1,
                },
                headers=_headers(account.access_token),
            )
            _raise_for_status(response, f"/user/{username}/saved")
            payload = response.json().get("data") or {}
            children = payload.get("children") or []
            if not children:
                break

            for child in children:
                artifact = _saved_item_to_artifact(child)
                if artifact is not None:
                    artifacts.append(artifact)
                if len(artifacts) >= limit:
                    break

            after = payload.get("after")
            if not after:
                break

        return artifacts[:limit]
    finally:
        if own_client:
            await http_client.aclose()


async def _fetch_username(client: httpx.AsyncClient, access_token: str) -> str:
    response = await client.get(
        f"{API_BASE_URL}/api/v1/me",
        headers=_headers(access_token),
    )
    _raise_for_status(response, "/api/v1/me")
    payload = response.json()
    username = str(payload.get("name") or "").strip()
    if not username:
        raise RuntimeError("Reddit ingest could not determine the authenticated username.")
    return username


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": (os.environ.get(USER_AGENT_ENV) or DEFAULT_USER_AGENT).strip(),
    }


def _saved_item_to_artifact(child: dict[str, Any]) -> ProviderArtifact | None:
    kind = child.get("kind")
    data = child.get("data") or {}
    if kind == "t3":
        permalink = str(data.get("permalink") or "")
        url = str(
            data.get("url_overridden_by_dest")
            or data.get("url")
            or f"https://www.reddit.com{permalink}"
        )
        return ProviderArtifact(
            provider=NexusProvider.REDDIT,
            external_id=str(data.get("name") or f"post:{data.get('id') or ''}"),
            url=url,
            title=str(data.get("title") or ""),
            description=str(data.get("selftext") or ""),
            source_type="saved_post",
            metadata={
                "subreddit": data.get("subreddit"),
                "author": data.get("author"),
                "permalink": permalink,
                "score": data.get("score"),
                "created_utc": data.get("created_utc"),
                "num_comments": data.get("num_comments"),
                "over_18": data.get("over_18"),
                "is_self": data.get("is_self"),
            },
        )

    if kind == "t1":
        permalink = str(data.get("permalink") or "")
        return ProviderArtifact(
            provider=NexusProvider.REDDIT,
            external_id=str(data.get("name") or f"comment:{data.get('id') or ''}"),
            url=f"https://www.reddit.com{permalink}",
            title=str(data.get("link_title") or data.get("subreddit_name_prefixed") or "Saved comment"),
            description=str(data.get("body") or ""),
            source_type="saved_comment",
            metadata={
                "subreddit": data.get("subreddit"),
                "author": data.get("author"),
                "permalink": permalink,
                "score": data.get("score"),
                "created_utc": data.get("created_utc"),
                "link_id": data.get("link_id"),
                "parent_id": data.get("parent_id"),
            },
        )

    return None


def _raise_for_status(response: httpx.Response, action: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = (response.text or "no response body").strip()[:500]
        raise RuntimeError(
            f"Reddit ingest request {action} failed with status {response.status_code}: {detail}"
        ) from exc


__all__ = ["API_BASE_URL", "ingest_artifacts"]
