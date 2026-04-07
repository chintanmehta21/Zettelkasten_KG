from __future__ import annotations

import os
from typing import Any

import httpx

from website.experimental_features.nexus.source_ingest.common.models import (
    NexusProvider,
    ProviderArtifact,
    StoredProviderAccount,
)

API_BASE_URL = os.environ.get("NEXUS_TWITTER_API_BASE_URL", "https://api.twitter.com/2")
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
        me = await _get_me(http_client, account.access_token)
        user_id = str(me.get("id") or "")
        viewer_username = str(me.get("username") or "")
        if not user_id:
            raise RuntimeError("Twitter ingest could not determine the authenticated user id.")

        artifacts: list[ProviderArtifact] = []
        pagination_token: str | None = None

        while len(artifacts) < limit:
            remaining = limit - len(artifacts)
            response = await http_client.get(
                f"{API_BASE_URL}/users/{user_id}/bookmarks",
                params={
                    "max_results": min(remaining, 100),
                    "pagination_token": pagination_token or "",
                    "tweet.fields": "attachments,author_id,conversation_id,created_at,entities,lang,public_metrics",
                    "expansions": "attachments.media_keys,author_id",
                    "user.fields": "id,name,username,profile_image_url",
                    "media.fields": "duration_ms,height,preview_image_url,type,url,width",
                },
                headers=_headers(account.access_token),
            )
            _raise_for_status(response, f"/users/{user_id}/bookmarks")
            payload = response.json()
            tweets = payload.get("data") or []
            if not tweets:
                break

            includes = payload.get("includes") or {}
            users_by_id = {
                str(user.get("id")): user for user in (includes.get("users") or [])
            }
            media_by_key = {
                str(media.get("media_key")): media for media in (includes.get("media") or [])
            }

            for tweet in tweets:
                artifacts.append(
                    _tweet_to_artifact(
                        tweet,
                        users_by_id=users_by_id,
                        media_by_key=media_by_key,
                        viewer_username=viewer_username,
                    )
                )
                if len(artifacts) >= limit:
                    break

            pagination_token = ((payload.get("meta") or {}).get("next_token"))
            if not pagination_token:
                break

        return artifacts[:limit]
    finally:
        if own_client:
            await http_client.aclose()


async def _get_me(client: httpx.AsyncClient, access_token: str) -> dict[str, Any]:
    response = await client.get(
        f"{API_BASE_URL}/users/me",
        params={"user.fields": "id,name,username,profile_image_url"},
        headers=_headers(access_token),
    )
    _raise_for_status(response, "/users/me")
    payload = response.json().get("data") or {}
    return payload


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _tweet_to_artifact(
    tweet: dict[str, Any],
    *,
    users_by_id: dict[str, dict[str, Any]],
    media_by_key: dict[str, dict[str, Any]],
    viewer_username: str,
) -> ProviderArtifact:
    author = users_by_id.get(str(tweet.get("author_id") or "")) or {}
    author_username = str(author.get("username") or viewer_username or "i")
    media_keys = ((tweet.get("attachments") or {}).get("media_keys") or [])
    media = [media_by_key[key] for key in media_keys if key in media_by_key]
    text = str(tweet.get("text") or "")
    return ProviderArtifact(
        provider=NexusProvider.TWITTER,
        external_id=str(tweet.get("id") or ""),
        url=f"https://x.com/{author_username}/status/{tweet.get('id')}",
        title=_title_from_text(text),
        description=text,
        source_type="bookmark",
        metadata={
            "author_id": tweet.get("author_id"),
            "author_name": author.get("name"),
            "author_username": author.get("username"),
            "created_at": tweet.get("created_at"),
            "conversation_id": tweet.get("conversation_id"),
            "lang": tweet.get("lang"),
            "public_metrics": tweet.get("public_metrics") or {},
            "entities": tweet.get("entities") or {},
            "media": media,
        },
    )


def _title_from_text(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= 80:
        return normalized
    return normalized[:77].rstrip() + "..."


def _raise_for_status(response: httpx.Response, action: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = (response.text or "no response body").strip()[:500]
        raise RuntimeError(
            f"Twitter ingest request {action} failed with status {response.status_code}: {detail}"
        ) from exc


__all__ = ["API_BASE_URL", "ingest_artifacts"]
