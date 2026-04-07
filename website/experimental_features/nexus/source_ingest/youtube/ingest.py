from __future__ import annotations

from typing import Any

import httpx

from website.experimental_features.nexus.source_ingest.common.models import (
    NexusProvider,
    ProviderArtifact,
    StoredProviderAccount,
)

API_BASE_URL = "https://www.googleapis.com/youtube/v3"
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
        artifacts: list[ProviderArtifact] = []
        page_token: str | None = None

        while len(artifacts) < limit:
            remaining = limit - len(artifacts)
            playlists_page = await _get_json(
                http_client,
                "/playlists",
                account.access_token,
                params={
                    "part": "snippet,contentDetails,status",
                    "mine": "true",
                    "maxResults": str(min(remaining, 50)),
                    "pageToken": page_token or "",
                },
            )

            playlists = playlists_page.get("items") or []
            if not playlists:
                break

            for playlist in playlists:
                artifacts.append(_playlist_to_artifact(playlist))
                if len(artifacts) >= limit:
                    break

                remaining = limit - len(artifacts)
                playlist_items = await _fetch_playlist_items(
                    http_client,
                    access_token=account.access_token,
                    playlist_id=str(playlist.get("id") or ""),
                    limit=remaining,
                )
                artifacts.extend(playlist_items[:remaining])
                if len(artifacts) >= limit:
                    break

            page_token = playlists_page.get("nextPageToken")
            if not page_token:
                break

        return artifacts[:limit]
    finally:
        if own_client:
            await http_client.aclose()


async def _fetch_playlist_items(
    client: httpx.AsyncClient,
    *,
    access_token: str,
    playlist_id: str,
    limit: int,
) -> list[ProviderArtifact]:
    artifacts: list[ProviderArtifact] = []
    page_token: str | None = None

    while len(artifacts) < limit:
        remaining = limit - len(artifacts)
        page = await _get_json(
            client,
            "/playlistItems",
            access_token,
            params={
                "part": "snippet,contentDetails,status",
                "playlistId": playlist_id,
                "maxResults": str(min(remaining, 50)),
                "pageToken": page_token or "",
            },
        )
        items = page.get("items") or []
        if not items:
            break

        for item in items:
            video_id = (
                ((item.get("contentDetails") or {}).get("videoId"))
                or ((item.get("snippet") or {}).get("resourceId") or {}).get("videoId")
            )
            if not video_id:
                continue
            artifacts.append(_playlist_item_to_artifact(item, playlist_id, str(video_id)))
            if len(artifacts) >= limit:
                break

        page_token = page.get("nextPageToken")
        if not page_token:
            break

    return artifacts


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    access_token: str,
    *,
    params: dict[str, str],
) -> dict[str, Any]:
    clean_params = {key: value for key, value in params.items() if value}
    response = await client.get(
        f"{API_BASE_URL}{path}",
        params=clean_params,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    _raise_for_status(response, path)
    return response.json()


def _playlist_to_artifact(item: dict[str, Any]) -> ProviderArtifact:
    snippet = item.get("snippet") or {}
    content_details = item.get("contentDetails") or {}
    status = item.get("status") or {}
    playlist_id = str(item.get("id") or "")
    return ProviderArtifact(
        provider=NexusProvider.YOUTUBE,
        external_id=f"playlist:{playlist_id}",
        url=f"https://www.youtube.com/playlist?list={playlist_id}",
        title=str(snippet.get("title") or ""),
        description=str(snippet.get("description") or ""),
        source_type="playlist",
        metadata={
            "channel_id": snippet.get("channelId"),
            "channel_title": snippet.get("channelTitle"),
            "published_at": snippet.get("publishedAt"),
            "item_count": content_details.get("itemCount"),
            "privacy_status": status.get("privacyStatus"),
            "thumbnails": snippet.get("thumbnails") or {},
        },
    )


def _playlist_item_to_artifact(
    item: dict[str, Any],
    playlist_id: str,
    video_id: str,
) -> ProviderArtifact:
    snippet = item.get("snippet") or {}
    content_details = item.get("contentDetails") or {}
    return ProviderArtifact(
        provider=NexusProvider.YOUTUBE,
        external_id=f"video:{video_id}",
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=str(snippet.get("title") or ""),
        description=str(snippet.get("description") or ""),
        source_type="video",
        metadata={
            "playlist_id": playlist_id,
            "playlist_item_id": item.get("id"),
            "channel_id": snippet.get("channelId"),
            "channel_title": snippet.get("channelTitle"),
            "published_at": snippet.get("publishedAt"),
            "position": snippet.get("position"),
            "video_published_at": content_details.get("videoPublishedAt"),
            "thumbnails": snippet.get("thumbnails") or {},
        },
    )


def _raise_for_status(response: httpx.Response, action: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = (response.text or "no response body").strip()[:500]
        raise RuntimeError(
            f"YouTube ingest request {action} failed with status {response.status_code}: {detail}"
        ) from exc


__all__ = ["API_BASE_URL", "ingest_artifacts"]
