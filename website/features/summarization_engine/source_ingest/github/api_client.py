"""Thin GitHub REST API wrapper for Phase 0.5 signal enrichment."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class RepoSignals:
    pages_url: str | None = None
    has_workflows: bool = False
    workflow_count: int = 0
    releases: list[dict] = field(default_factory=list)
    languages: list[tuple[str, float]] = field(default_factory=list)
    root_dir_flags: dict[str, bool] = field(default_factory=dict)


class _HttpError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


class GitHubApiClient:
    def __init__(self, *, token: str, base_url: str, timeout_sec: int) -> None:
        self._token = token
        self._base = base_url.rstrip("/")
        self._timeout = timeout_sec
        self._headers = {
            "Authorization": f"Bearer {token}" if token else "",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get(self, path: str) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base}{path}",
                headers={k: v for k, v in self._headers.items() if v},
            )
            if response.status_code == 404:
                raise _HttpError(404)
            response.raise_for_status()
            return response.json()

    async def fetch_pages_url(self, slug: str) -> str | None:
        try:
            data = await self._get(f"/repos/{slug}/pages")
        except Exception:
            return None
        return (data or {}).get("html_url")

    async def fetch_workflows(self, slug: str) -> tuple[bool, int]:
        try:
            data = await self._get(f"/repos/{slug}/actions/workflows")
        except Exception:
            return False, 0
        count = int((data or {}).get("total_count", 0))
        return count > 0, count

    async def fetch_releases(self, slug: str, max_count: int) -> list[dict]:
        try:
            data = await self._get(f"/repos/{slug}/releases?per_page={max_count}")
        except Exception:
            return []
        releases = []
        for release in (data or [])[:max_count]:
            releases.append(
                {
                    "tag_name": release.get("tag_name"),
                    "name": release.get("name"),
                    "published_at": release.get("published_at"),
                    "prerelease": release.get("prerelease", False),
                }
            )
        return releases

    async def fetch_languages(self, slug: str) -> list[tuple[str, float]]:
        try:
            data = await self._get(f"/repos/{slug}/languages")
        except Exception:
            return []
        total = sum(data.values()) or 1
        pairs = [(language, value / total * 100.0) for language, value in data.items()]
        return sorted(pairs, key=lambda pair: pair[1], reverse=True)

    async def fetch_root_dir_signals(self, slug: str) -> dict[str, bool]:
        try:
            entries = await self._get(f"/repos/{slug}/contents")
        except Exception:
            return {}
        names = {entry["name"].lower() for entry in entries if entry.get("type") == "dir"}
        return {
            "has_tests": "tests" in names or "test" in names,
            "has_benchmarks": (
                "benchmarks" in names or "benchmark" in names or "bench" in names
            ),
            "has_examples": "examples" in names or "example" in names,
            "has_demo": "demo" in names or "demos" in names,
            "has_docs_dir": "docs" in names or "doc" in names,
        }

    async def fetch_all_signals(self, slug: str, cfg: dict) -> RepoSignals:
        signals = RepoSignals()
        if cfg.get("fetch_pages", True):
            signals.pages_url = await self.fetch_pages_url(slug)
        if cfg.get("fetch_workflows", True):
            signals.has_workflows, signals.workflow_count = await self.fetch_workflows(
                slug
            )
        if cfg.get("fetch_releases", True):
            signals.releases = await self.fetch_releases(
                slug,
                int(cfg.get("max_releases", 5)),
            )
        if cfg.get("fetch_languages", True):
            signals.languages = await self.fetch_languages(slug)
        if cfg.get("fetch_root_dir_listing", True):
            signals.root_dir_flags = await self.fetch_root_dir_signals(slug)
        return signals
