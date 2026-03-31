"""GitHub API-based note writer for cloud deployment.

Pushes Obsidian markdown notes to a GitHub repository via the
Contents API (PUT /repos/{owner}/{repo}/contents/{path}).

Used when GITHUB_TOKEN and GITHUB_REPO are configured (cloud mode).
Falls back to the local ObsidianWriter when not configured.
"""

from __future__ import annotations

import base64
import logging

import httpx

from telegram_bot.models.capture import ExtractedContent
from telegram_bot.pipeline.summarizer import SummarizationResult
from telegram_bot.pipeline.writer import _build_body, _build_filename, _build_frontmatter

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


class GitHubWriter:
    """Pushes processed notes to a GitHub repository.

    Args:
        token: GitHub personal access token with ``repo`` scope.
        repo: Repository in ``owner/repo`` format.
        branch: Target branch (default ``main``).
    """

    def __init__(self, token: str, repo: str, branch: str = "main") -> None:
        self._token = token
        self._repo = repo
        self._branch = branch

        parts = repo.split("/", 1)
        self._owner = parts[0]
        self._repo_name = parts[1] if len(parts) > 1 else ""

    async def write_note(
        self,
        content: ExtractedContent,
        result: SummarizationResult,
        tags: list[str],
    ) -> str:
        """Push a note to GitHub. Returns the file's HTML URL on GitHub."""
        filename = _build_filename(content.source_type, content.title, content.url)
        frontmatter = _build_frontmatter(content, result, tags)
        body = _build_body(content, result)
        note_text = f"{frontmatter}\n\n{body}\n"

        encoded = base64.b64encode(note_text.encode("utf-8")).decode("ascii")
        url = f"{_GITHUB_API}/repos/{self._repo}/contents/{filename}"

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={
                    "message": f"note: {content.title[:60]}",
                    "content": encoded,
                    "branch": self._branch,
                },
                timeout=30.0,
            )

        if resp.status_code not in (200, 201):
            logger.error("GitHub API error %d: %s", resp.status_code, resp.text)
            raise RuntimeError(
                f"GitHub API error {resp.status_code}: {resp.json().get('message', resp.text)}"
            )

        file_url = resp.json().get("content", {}).get("html_url", "")
        logger.info("Note pushed to GitHub: %s", file_url)
        return file_url
