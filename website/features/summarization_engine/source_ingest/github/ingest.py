"""GitHub repository ingestor."""
from __future__ import annotations

import base64
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import (
    compact_text,
    join_sections,
    raise_extraction,
    utc_now,
)


class GitHubIngestor(BaseIngestor):
    source_type = SourceType.GITHUB

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        owner, repo = _parse_repo(url)
        headers = {"Accept": "application/vnd.github+json"}
        token = os.environ.get(config.get("github_token_env", "GITHUB_TOKEN"))
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            repo_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
            if repo_resp.status_code == 404:
                raise_extraction("GitHub repository not found", self.source_type, "404")
            repo_resp.raise_for_status()
            repo_data = repo_resp.json()

            readme = await _optional_readme(client, owner, repo)
            languages = await _optional_json(client, f"https://api.github.com/repos/{owner}/{repo}/languages", {})
            issues = []
            if config.get("fetch_issues", True):
                issues = await _optional_json(
                    client,
                    f"https://api.github.com/repos/{owner}/{repo}/issues",
                    [],
                    params={"state": "open", "per_page": int(config.get("max_issues", 20))},
                )
            commits = []
            if config.get("fetch_commits", True):
                commits = await _optional_json(
                    client,
                    f"https://api.github.com/repos/{owner}/{repo}/commits",
                    [],
                    params={"per_page": int(config.get("max_commits", 10))},
                )

        sections = {
            "Repository": (
                f"{repo_data.get('full_name', f'{owner}/{repo}')}\n"
                f"{repo_data.get('description') or ''}\n"
                f"Language: {repo_data.get('language') or 'unknown'}\n"
                f"Topics: {', '.join(repo_data.get('topics') or [])}"
            ),
            "README": readme,
            "Languages": ", ".join(f"{k}: {v}" for k, v in languages.items()) if isinstance(languages, dict) else "",
            "Issues": "\n".join(_issue_line(issue) for issue in issues[: int(config.get("max_issues", 20))]),
            "Commits": "\n".join(_commit_line(commit) for commit in commits[: int(config.get("max_commits", 10))]),
        }
        raw_text = join_sections(sections)
        return IngestResult(
            source_type=self.source_type,
            url=f"https://github.com/{owner}/{repo}",
            original_url=url,
            raw_text=raw_text,
            sections=sections,
            metadata={
                "owner": owner,
                "repo": repo,
                "full_name": repo_data.get("full_name"),
                "stars": repo_data.get("stargazers_count", 0),
                "forks": repo_data.get("forks_count", 0),
                "language": repo_data.get("language"),
                "topics": repo_data.get("topics") or [],
                "license": (repo_data.get("license") or {}).get("spdx_id"),
                "updated_at": repo_data.get("updated_at"),
            },
            extraction_confidence="high" if readme else "medium",
            confidence_reason="repo metadata and README fetched" if readme else "repo metadata fetched without README",
            fetched_at=utc_now(),
        )


def _parse_repo(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or not re.match(r"^[A-Za-z0-9_.-]+$", parts[0]):
        raise_extraction("Invalid GitHub repository URL", SourceType.GITHUB, "bad_url")
    return parts[0], parts[1].removesuffix(".git")


async def _optional_json(client: httpx.AsyncClient, url: str, default: Any, **kwargs: Any) -> Any:
    try:
        response = await client.get(url, **kwargs)
        if response.status_code >= 400:
            return default
        return response.json()
    except Exception:
        return default


async def _optional_readme(client: httpx.AsyncClient, owner: str, repo: str) -> str:
    data = await _optional_json(client, f"https://api.github.com/repos/{owner}/{repo}/readme", {})
    encoded = data.get("content") if isinstance(data, dict) else None
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _issue_line(issue: dict[str, Any]) -> str:
    return compact_text(f"#{issue.get('number')}: {issue.get('title')} {issue.get('body') or ''}", max_chars=400)


def _commit_line(commit: dict[str, Any]) -> str:
    message = (commit.get("commit") or {}).get("message") or ""
    return compact_text(f"{commit.get('sha', '')}: {message}", max_chars=240)
