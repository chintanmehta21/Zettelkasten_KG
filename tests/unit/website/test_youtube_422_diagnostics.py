"""UX-4: /api/summarize 422 diagnostic payload for YouTube failures.

Covers:
  (a) YouTube extraction-confidence failure -> structured 422 detail with
      message + tier_results + url.
  (b) Non-YouTube extraction-confidence failure -> generic string detail
      preserved (backwards-compatible).
  (c) Successful summarize still returns 200 (regression guard).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from website.app import create_app
from website.features.summarization_engine.core.errors import (
    ExtractionConfidenceError,
)


@pytest.fixture
def client() -> TestClient:
    from website.api import routes

    routes._rate_store.clear()
    return TestClient(create_app())


_YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _yt_tier_results() -> list[dict]:
    return [
        {"tier": "ytdlp_player_rotation", "status": "failed",
         "reason": "all player clients failed", "latency_ms": 1200},
        {"tier": "transcript_api_direct", "status": "failed",
         "reason": "no captions", "latency_ms": 300},
        {"tier": "piped_pool", "status": "failed",
         "reason": "all instances unhealthy", "latency_ms": 50},
        {"tier": "invidious_pool", "status": "failed",
         "reason": "all instances unhealthy", "latency_ms": 50},
        {"tier": "gemini_audio", "status": "failed",
         "reason": "yt-dlp blocked", "latency_ms": 800},
        {"tier": "metadata_only", "status": "failed",
         "reason": "oembed 429", "latency_ms": 200},
    ]


class TestYouTube422Diagnostics:
    def test_youtube_extraction_failure_returns_structured_detail(
        self, client: TestClient
    ) -> None:
        exc = ExtractionConfidenceError(
            "Insufficient content extracted (12 chars). Reason: All tiers failed",
            source_type="youtube",
            reason="All tiers failed",
            tier_results=_yt_tier_results(),
            url=_YT_URL,
        )
        with patch(
            "website.api.routes.summarize_url",
            new_callable=AsyncMock,
            side_effect=exc,
        ):
            resp = client.post("/api/summarize", json={"url": _YT_URL})

        assert resp.status_code == 422
        body = resp.json()
        detail = body["detail"]
        assert isinstance(detail, dict), f"expected dict detail, got: {detail!r}"
        # New copy
        assert "YouTube transcript unavailable" in detail["message"]
        assert "datacenter IP" in detail["message"]
        # Structured tier results
        assert isinstance(detail["tier_results"], list)
        tier_names = [t["tier"] for t in detail["tier_results"]]
        assert "ytdlp_player_rotation" in tier_names
        assert "metadata_only" in tier_names
        # URL echoed back
        assert detail["url"] == _YT_URL

    def test_non_youtube_failure_keeps_generic_string_detail(
        self, client: TestClient
    ) -> None:
        exc = ExtractionConfidenceError(
            "Insufficient content extracted (10 chars). Reason: paywalled",
            source_type="newsletter",
            reason="paywalled",
        )
        with patch(
            "website.api.routes.summarize_url",
            new_callable=AsyncMock,
            side_effect=exc,
        ):
            resp = client.post(
                "/api/summarize", json={"url": "https://example.com/post"}
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        # Backward-compatible string
        assert isinstance(detail, str)
        assert "Could not extract enough content" in detail

    def test_successful_youtube_summarize_returns_200(
        self, client: TestClient
    ) -> None:
        mock_result = {
            "title": "YT Title",
            "summary": "Body",
            "brief_summary": "Brief",
            "tags": ["source/youtube"],
            "source_type": "youtube",
            "source_url": _YT_URL,
            "one_line_summary": "One",
            "is_raw_fallback": False,
            "tokens_used": 50,
            "latency_ms": 250,
            "metadata": {},
        }
        with patch(
            "website.api.routes.summarize_url",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post("/api/summarize", json={"url": _YT_URL})

        assert resp.status_code == 200
        assert resp.json()["title"] == "YT Title"
