from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.summarization_engine.source_ingest.newsletter.ingest import (
    NewsletterIngestor,
)


@pytest.mark.asyncio
async def test_ingest_adds_structural_signals(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    html = """
    <html>
      <head>
        <meta property="og:site_name" content="Example Substack">
        <meta name="preheader" content="Preheader copy">
      </head>
      <body>
        <article>
          <h1 class="post-title">Newsletter title</h1>
          <h3 class="subtitle">Subtitle text</h3>
          <div class="body markup">
            <p>Short body.</p>
            <p>I recommend trying the async version.</p>
          </div>
          <div class="post-footer">
            <a href="https://example.substack.com/subscribe">Subscribe now</a>
          </div>
        </article>
      </body>
    </html>
    """

    async def fake_fetch_and_extract(url: str, **kwargs):  # noqa: ARG001
        return (
            "Short body. I recommend trying the async version.",
            {"title": "Fallback title"},
            "https://example.substack.com/p/example",
            html,
        )

    monkeypatch.setattr(
        "website.features.summarization_engine.source_ingest.newsletter.ingest._fetch_and_extract",
        fake_fetch_and_extract,
    )
    monkeypatch.setattr(
        "website.features.summarization_engine.source_ingest.newsletter.ingest.classify_stance",
        AsyncMock(return_value="skeptical"),
    )
    fake_client = MagicMock()
    monkeypatch.setattr(
        "website.features.summarization_engine.api.routes._gemini_client",
        lambda: fake_client,
    )

    result = await NewsletterIngestor().ingest(
        "https://example.substack.com/p/example",
        config={
            "preflight_probe_enabled": False,
            "site_specific_selectors_enabled": True,
            "preheader_fallback_chars": 150,
            "cta_keyword_regex": "subscribe",
            "cta_max_count": 5,
            "conclusions_tail_fraction": 0.5,
            "conclusions_prefixes": ["i recommend"],
            "conclusions_max_count": 6,
            "stance_classifier_enabled": True,
            "stance_cache_ttl_days": 30,
            "min_text_length": 10,
        },
    )

    assert result.metadata["site"] == "substack"
    assert result.metadata["publication_identity"] == "Example Substack"
    assert result.metadata["preheader"] == "Preheader copy"
    assert result.metadata["cta_count"] == 1
    assert result.metadata["conclusions_count"] == 1
    assert result.metadata["detected_stance"] == "skeptical"
    assert result.sections["Title"] == "Newsletter title"
    assert result.sections["Subtitle"] == "Subtitle text"
    assert "Subscribe now" in result.sections["CTAs"]
    assert "trying the async version" in result.sections["Conclusions"]
    assert "Title" in result.raw_text
