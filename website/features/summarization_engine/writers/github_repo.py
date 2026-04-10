"""Opt-in GitHub repository writer."""
from __future__ import annotations

import base64
import os
from typing import Any
from uuid import UUID

import httpx

from website.features.summarization_engine.core.errors import WriterError
from website.features.summarization_engine.core.models import SummaryResult
from website.features.summarization_engine.writers.base import BaseWriter
from website.features.summarization_engine.writers.markdown import render_markdown
from website.features.summarization_engine.writers.obsidian import _slug


class GithubRepoWriter(BaseWriter):
    async def write(self, result: SummaryResult, *, user_id: UUID) -> dict[str, Any]:
        token = os.environ.get("GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPO")
        branch = os.environ.get("GITHUB_BRANCH", "main")
        if not token or not repo:
            raise WriterError("GITHUB_TOKEN and GITHUB_REPO are required", writer="github_repo")

        path = f"notes/{_slug(result.mini_title)}.md"
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        sha = await _existing_file_sha(url, branch, headers)
        payload = {
            "message": f"Add note: {result.mini_title}",
            "content": base64.b64encode(render_markdown(result).encode()).decode(),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            response = await client.put(url, json=payload)
        if response.status_code >= 400:
            raise WriterError(f"GitHub write failed: {response.status_code}", writer="github_repo")
        return {"path": path, "status": "updated" if sha else "created"}


async def _existing_file_sha(url: str, branch: str, headers: dict[str, str]) -> str | None:
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        response = await client.get(url, params={"ref": branch})
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise WriterError(f"GitHub lookup failed: {response.status_code}", writer="github_repo")
    payload = response.json()
    return payload.get("sha")
