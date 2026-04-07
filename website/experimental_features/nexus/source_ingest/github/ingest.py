from __future__ import annotations

from typing import Any

import httpx

from website.experimental_features.nexus.source_ingest.common.models import (
    NexusProvider,
    ProviderArtifact,
    StoredProviderAccount,
)

API_BASE_URL = "https://api.github.com"
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
        page = 1

        while len(artifacts) < limit:
            remaining = limit - len(artifacts)
            response = await http_client.get(
                f"{API_BASE_URL}/user/repos",
                params={
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": min(remaining, 100),
                    "page": page,
                    "affiliation": "owner,collaborator,organization_member",
                    "visibility": "all",
                },
                headers=_headers(account.access_token),
            )
            _raise_for_status(response, "/user/repos")
            payload = response.json()
            if not payload:
                break

            artifacts.extend(_repo_to_artifact(repo) for repo in payload)
            if len(payload) < min(remaining, 100):
                break
            page += 1

        return artifacts[:limit]
    finally:
        if own_client:
            await http_client.aclose()


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_to_artifact(repo: dict[str, Any]) -> ProviderArtifact:
    owner = repo.get("owner") or {}
    return ProviderArtifact(
        provider=NexusProvider.GITHUB,
        external_id=str(repo.get("id") or repo.get("node_id") or repo.get("full_name") or ""),
        url=str(repo.get("html_url") or ""),
        title=str(repo.get("full_name") or repo.get("name") or ""),
        description=str(repo.get("description") or ""),
        source_type="repository",
        metadata={
            "name": repo.get("name"),
            "owner_login": owner.get("login"),
            "owner_id": owner.get("id"),
            "default_branch": repo.get("default_branch"),
            "private": repo.get("private"),
            "archived": repo.get("archived"),
            "fork": repo.get("fork"),
            "language": repo.get("language"),
            "topics": repo.get("topics") or [],
            "stargazers_count": repo.get("stargazers_count"),
            "watchers_count": repo.get("watchers_count"),
            "forks_count": repo.get("forks_count"),
            "open_issues_count": repo.get("open_issues_count"),
            "pushed_at": repo.get("pushed_at"),
            "updated_at": repo.get("updated_at"),
        },
    )


def _raise_for_status(response: httpx.Response, action: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = (response.text or "no response body").strip()[:500]
        raise RuntimeError(
            f"GitHub ingest request {action} failed with status {response.status_code}: {detail}"
        ) from exc


__all__ = ["API_BASE_URL", "ingest_artifacts"]
