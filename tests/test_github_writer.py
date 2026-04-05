"""Tests for telegram_bot.pipeline.github_writer — GitHub API note pusher.

Uses pytest-httpx to mock GitHub API calls without hitting the network.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from telegram_bot.models.capture import ExtractedContent, SourceType
from telegram_bot.pipeline.github_writer import GitHubWriter
from telegram_bot.pipeline.summarizer import SummarizationResult


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_content(
    title: str = "Test Note",
    url: str = "https://example.com/article",
    source_type: SourceType = SourceType.WEB,
) -> ExtractedContent:
    return ExtractedContent(
        url=url,
        source_type=source_type,
        title=title,
        body="Article body content.",
        metadata={},
    )


def make_result(**kwargs) -> SummarizationResult:
    defaults = dict(
        summary="A structured summary of the article.",
        tags={"domain": ["AI"], "type": ["Research"], "difficulty": ["Intermediate"], "keywords": ["test"]},
        one_line_summary="Key takeaway from the article.",
        tokens_used=500,
        latency_ms=300,
        is_raw_fallback=False,
    )
    defaults.update(kwargs)
    return SummarizationResult(**defaults)


# ── Tests ────────────────────────────────────────────────────────────────────


class TestGitHubWriterInit:
    def test_stores_config(self):
        writer = GitHubWriter(token="ghp_abc", repo="user/repo", branch="main")
        assert writer._repo == "user/repo"
        assert writer._branch == "main"

    def test_parses_owner_and_repo(self):
        writer = GitHubWriter(token="ghp_abc", repo="myuser/myrepo", branch="main")
        assert writer._owner == "myuser"
        assert writer._repo_name == "myrepo"


class TestGitHubWriterWriteNote:
    @pytest.mark.asyncio
    async def test_creates_file_via_github_api(self, httpx_mock):
        """write_note PUTs the note content to GitHub Contents API."""
        # Mock ALL PUT requests (filename has dynamic date+hash)
        httpx_mock.add_response(
            method="PUT",
            json={
                "content": {
                    "html_url": "https://github.com/user/repo/blob/main/note.md",
                },
            },
            status_code=201,
        )

        writer = GitHubWriter(token="ghp_abc", repo="user/repo", branch="main")
        content = make_content()
        result = make_result()

        file_url = await writer.write_note(content, result, ["source/web", "domain/AI"])

        assert "github.com" in file_url

        # Verify the PUT request was made
        request = httpx_mock.get_request()
        assert request is not None
        assert request.method == "PUT"
        assert "Authorization" in request.headers
        assert request.headers["Authorization"] == "Bearer ghp_abc"

        # Verify body has base64-encoded content and commit message
        body = json.loads(request.content)
        assert "content" in body
        assert "message" in body
        # Content should be valid base64
        decoded = base64.b64decode(body["content"]).decode("utf-8")
        assert "---" in decoded  # frontmatter
        assert "Test Note" in decoded

    @pytest.mark.asyncio
    async def test_filename_matches_writer_convention(self, httpx_mock):
        """The filename pushed to GitHub follows the same convention as ObsidianWriter."""
        httpx_mock.add_response(method="PUT", json={"content": {"html_url": "https://example.com"}}, status_code=201)

        writer = GitHubWriter(token="ghp_abc", repo="user/repo", branch="main")
        content = make_content(source_type=SourceType.YOUTUBE, title="Python Tutorial")
        result = make_result()

        await writer.write_note(content, result, ["source/youtube"])

        request = httpx_mock.get_request()
        # URL path should contain youtube_YYYY-MM-DD_python-tutorial
        assert "youtube_" in request.url.path
        assert "python-tutorial" in request.url.path

    @pytest.mark.asyncio
    async def test_api_error_raises_runtime_error(self, httpx_mock):
        """A non-2xx response from GitHub should raise RuntimeError."""
        httpx_mock.add_response(method="PUT", json={"message": "Bad credentials"}, status_code=401)

        writer = GitHubWriter(token="bad_token", repo="user/repo", branch="main")
        content = make_content()
        result = make_result()

        with pytest.raises(RuntimeError, match="GitHub API error"):
            await writer.write_note(content, result, ["source/web"])

    @pytest.mark.asyncio
    async def test_note_content_has_frontmatter_and_body(self, httpx_mock):
        """The note pushed to GitHub must have YAML frontmatter and markdown body."""
        httpx_mock.add_response(method="PUT", json={"content": {"html_url": "https://example.com"}}, status_code=201)

        writer = GitHubWriter(token="ghp_abc", repo="user/repo", branch="main")
        content = make_content(title="Frontmatter Test")
        result = make_result(one_line_summary="A key takeaway.")

        await writer.write_note(content, result, ["source/web", "domain/AI"])

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        decoded = base64.b64decode(body["content"]).decode("utf-8")

        # Must start with YAML frontmatter
        assert decoded.startswith("---")
        assert "source_type: web" in decoded
        # Must have body with title and summary
        assert "# Frontmatter Test" in decoded
        assert "> A key takeaway." in decoded
        assert "## Summary" in decoded
