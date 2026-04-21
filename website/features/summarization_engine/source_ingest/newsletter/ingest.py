"""Newsletter ingestor with paywall-bypass chain.

Handles Substack, Medium, Beehiiv, Buttondown, HackerNoon, dev.to, Stratechery
and similar publications. The extractor:

1. Fetches the article directly, optionally pretending to be Googlebot.
2. If content is below ``min_text_length``, walks a configured fallback chain
   (Wayback Machine → archive.today → 12ft.io → Freedium for Medium) and
   returns the longest body it can recover.
3. Falls back to the thin direct response if every provider fails.

Config is read from ``summarization_engine/config.yaml`` under
``sources.newsletter``:

    newsletter:
      extractors: ["trafilatura", "readability", "newspaper4k"]
      paywall_fallbacks: ["googlebot", "wayback", "archive_ph", "twelveft", "freedium"]
      googlebot_ua: true
      min_text_length: 500
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import (
    DEFAULT_TIMEOUT,
    compact_text,
    extract_html_text,
    utc_now,
)

logger = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_GOOGLEBOT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)
_FACEBOOK_UA = "facebookexternalhit/1.1"

# Ordered bypass chain. Each entry is (name, url-builder-callable).
# Providers return full HTML; we pipe them through extract_html_text like
# the direct fetch so we can compare body length and pick the best.
_PROVIDER_ORDER = (
    "googlebot",
    "wayback",
    "archive_ph",
    "twelveft",
    "freedium",
)


class NewsletterIngestor(BaseIngestor):
    source_type = SourceType.NEWSLETTER

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        min_len = int(config.get("min_text_length", 500))
        use_googlebot = bool(config.get("googlebot_ua", True))
        fallback_names: list[str] = list(
            config.get("paywall_fallbacks") or _PROVIDER_ORDER
        )

        best_text = ""
        best_meta: dict[str, Any] = {}
        best_final_url = url
        best_provider = "direct"

        # Step 1 — direct fetch with either Googlebot or a regular browser UA.
        direct_ua = _GOOGLEBOT_UA if use_googlebot else _DEFAULT_UA
        direct_text, direct_meta, direct_final = await _fetch_and_extract(
            url, headers={"User-Agent": direct_ua}
        )
        if direct_text:
            best_text, best_meta, best_final_url = direct_text, direct_meta, direct_final
            logger.info(
                "[newsletter] direct fetch len=%d ua=%s url=%s",
                len(direct_text),
                "googlebot" if use_googlebot else "browser",
                url,
            )

        # Step 2 — walk paywall bypass providers if below threshold.
        if len(best_text) < min_len:
            for name in fallback_names:
                if name == "googlebot" and use_googlebot:
                    # already tried via direct fetch
                    continue
                try:
                    provider_text, provider_meta, provider_final = await _try_provider(
                        name, url
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[newsletter] provider %s failed for %s: %s", name, url, exc
                    )
                    continue

                if provider_text and len(provider_text) > len(best_text):
                    logger.info(
                        "[newsletter] provider=%s recovered len=%d (prev %d) url=%s",
                        name,
                        len(provider_text),
                        len(best_text),
                        url,
                    )
                    best_text = provider_text
                    # Keep the original URL's meta.title if we have it; overlay new keys.
                    merged_meta = {**provider_meta, **{k: v for k, v in best_meta.items() if v}}
                    best_meta = merged_meta
                    best_final_url = best_final_url or provider_final
                    best_provider = name
                    if len(best_text) >= min_len:
                        break

        confidence = "high" if len(best_text) >= min_len else "low" if not best_text else "medium"
        reason = (
            f"HTML article text extracted via {best_provider}"
            if best_text
            else "all paywall-bypass providers failed"
        )

        return IngestResult(
            source_type=self.source_type,
            url=best_final_url or url,
            original_url=url,
            raw_text=best_text,
            sections={"Article": best_text},
            metadata={
                **best_meta,
                "paywall_provider": best_provider,
            },
            extraction_confidence=confidence,
            confidence_reason=reason,
            fetched_at=utc_now(),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_and_extract(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str, dict[str, Any], str]:
    """Fetch ``url`` and run the shared HTML extractor.

    Returns ``("", {}, url)`` on any network / status-code failure so callers can
    simply compare content lengths across providers.
    """
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                return "", {}, str(response.url)
            html = response.text
            final_url = str(response.url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[newsletter] fetch failed for %s: %s", url, exc)
        return "", {}, url

    text, metadata = extract_html_text(html)
    return text, metadata, final_url


async def _try_provider(name: str, url: str) -> tuple[str, dict[str, Any], str]:
    """Dispatch to a named bypass provider."""
    if name == "googlebot":
        return await _fetch_and_extract(url, headers={"User-Agent": _GOOGLEBOT_UA})
    if name == "facebook":
        return await _fetch_and_extract(url, headers={"User-Agent": _FACEBOOK_UA})
    if name == "wayback":
        return await _wayback(url)
    if name == "archive_ph":
        return await _archive_ph(url)
    if name == "twelveft":
        return await _twelveft(url)
    if name == "freedium":
        return await _freedium(url)
    logger.debug("[newsletter] unknown provider %s — skipping", name)
    return "", {}, url


async def _wayback(url: str) -> tuple[str, dict[str, Any], str]:
    """Ask the Wayback Machine for the most recent snapshot and extract it."""
    api = f"https://archive.org/wayback/available?url={quote(url, safe='')}"
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT, follow_redirects=True
    ) as client:
        info_resp = await client.get(api)
        if info_resp.status_code >= 400:
            return "", {}, url
        info = info_resp.json() or {}
        snapshot = (
            ((info.get("archived_snapshots") or {}).get("closest") or {}).get("url")
        )
        if not snapshot:
            return "", {}, url
        return await _fetch_and_extract(snapshot)


async def _archive_ph(url: str) -> tuple[str, dict[str, Any], str]:
    """archive.today mirror. Uses the /newest/ endpoint which 302s to the
    latest snapshot. Returns empty-tuple if none exists yet."""
    target = f"https://archive.ph/newest/{url}"
    return await _fetch_and_extract(target, headers={"User-Agent": _DEFAULT_UA})


async def _twelveft(url: str) -> tuple[str, dict[str, Any], str]:
    """12ft.io strips simple paywalls for many mainstream publishers."""
    target = f"https://12ft.io/{url}"
    return await _fetch_and_extract(target, headers={"User-Agent": _DEFAULT_UA})


async def _freedium(url: str) -> tuple[str, dict[str, Any], str]:
    """Freedium is a Medium-specific paywall bypass; skip for non-Medium URLs."""
    host = (urlparse(url).hostname or "").lower()
    if "medium.com" not in host and not host.endswith(".medium.com"):
        return "", {}, url
    target = f"https://freedium.cfd/{url}"
    text, meta, final = await _fetch_and_extract(
        target, headers={"User-Agent": _DEFAULT_UA}
    )
    # Freedium pre-pends its own banner; compact_text already trims, no-op here.
    return text, meta, final


__all__ = ["NewsletterIngestor"]
