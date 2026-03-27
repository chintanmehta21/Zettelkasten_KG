"""GitHub repository content extractor.

Extracts README content, repo description, language stats, and metadata
from public GitHub repositories using the GitHub API (no auth needed for
public repos, 60 req/hr rate limit).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from zettelkasten_bot.models.capture import ExtractedContent, SourceType
from zettelkasten_bot.sources.base import SourceExtractor

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


def _parse_github_path(url: str) -> tuple[str, str] | None:
    """Extract owner/repo from a GitHub URL. Returns (owner, repo) or None."""
    import urllib.parse  # noqa: PLC0415

    parsed = urllib.parse.urlparse(url)
    if "github.com" not in (parsed.hostname or ""):
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


class GitHubExtractor(SourceExtractor):
    """Extract README and metadata from public GitHub repositories."""

    source_type = SourceType.GITHUB

    async def extract(self, url: str) -> ExtractedContent:
        """Extract GitHub repository README and metadata."""
        parsed = _parse_github_path(url)
        if not parsed:
            raise ValueError(f"Cannot parse GitHub owner/repo from URL: {url}")

        owner, repo = parsed
        metadata: dict[str, Any] = {"owner": owner, "repo": repo}
        parts: list[str] = []

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ZettelkastenBot/1.0",
        }

        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            # ── Repo metadata ─────────────────────────────────────────────
            try:
                resp = await client.get(f"{_GITHUB_API}/repos/{owner}/{repo}")
                resp.raise_for_status()
                repo_data = resp.json()

                metadata["description"] = repo_data.get("description", "")
                metadata["stars"] = repo_data.get("stargazers_count", 0)
                metadata["forks"] = repo_data.get("forks_count", 0)
                metadata["language"] = repo_data.get("language", "")
                metadata["topics"] = repo_data.get("topics", [])
                metadata["created_at"] = repo_data.get("created_at", "")
                metadata["updated_at"] = repo_data.get("updated_at", "")
                metadata["license"] = (repo_data.get("license") or {}).get("spdx_id", "")
                metadata["open_issues"] = repo_data.get("open_issues_count", 0)
                metadata["homepage"] = repo_data.get("homepage", "")

                title = f"{owner}/{repo}"
                if repo_data.get("description"):
                    parts.append(f"## Description\n\n{repo_data['description']}")

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise ValueError(f"GitHub repository not found: {owner}/{repo}") from exc
                raise

            # ── Languages ─────────────────────────────────────────────────
            try:
                resp = await client.get(f"{_GITHUB_API}/repos/{owner}/{repo}/languages")
                if resp.status_code == 200:
                    langs = resp.json()
                    if langs:
                        total = sum(langs.values())
                        lang_lines = [
                            f"- {lang}: {bytes_count / total * 100:.1f}%"
                            for lang, bytes_count in sorted(
                                langs.items(), key=lambda x: x[1], reverse=True
                            )[:10]
                        ]
                        parts.append("## Languages\n\n" + "\n".join(lang_lines))
                        metadata["languages"] = langs
            except Exception as exc:
                logger.debug("Failed to fetch languages for %s/%s: %s", owner, repo, exc)

            # ── README ────────────────────────────────────────────────────
            try:
                resp = await client.get(
                    f"{_GITHUB_API}/repos/{owner}/{repo}/readme",
                    headers={**headers, "Accept": "application/vnd.github.raw+json"},
                )
                if resp.status_code == 200:
                    readme_text = resp.text
                    # Truncate very long READMEs to ~8000 chars
                    if len(readme_text) > 8000:
                        readme_text = readme_text[:8000] + "\n\n... (truncated)"
                    parts.append(f"## README\n\n{readme_text}")
            except Exception as exc:
                logger.debug("Failed to fetch README for %s/%s: %s", owner, repo, exc)

        body = "\n\n".join(parts) if parts else "(No content extracted)"

        return ExtractedContent(
            url=url,
            source_type=SourceType.GITHUB,
            title=title,
            body=body,
            metadata=metadata,
        )
