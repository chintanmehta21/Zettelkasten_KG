"""URL to SourceType detection for the summarization engine."""
from __future__ import annotations

from urllib.parse import urlparse

from website.features.summarization_engine.core.models import SourceType

_DOMAIN_RULES: list[tuple[tuple[str, ...], SourceType]] = [
    (("github.com",), SourceType.GITHUB),
    (("news.ycombinator.com",), SourceType.HACKERNEWS),
    (("arxiv.org", "ar5iv.labs.arxiv.org"), SourceType.ARXIV),
    (("reddit.com", "redd.it"), SourceType.REDDIT),
    (("youtube.com", "youtu.be"), SourceType.YOUTUBE),
    (("linkedin.com",), SourceType.LINKEDIN),
    (("twitter.com", "x.com"), SourceType.TWITTER),
    (
        (
            "podcasts.apple.com",
            "open.spotify.com",
            "overcast.fm",
            "pca.st",
            "share.snipd.com",
            "snipd.com",
        ),
        SourceType.PODCAST,
    ),
]

_NEWSLETTER_DOMAINS: tuple[str, ...] = (
    "substack.com",
    "medium.com",
    "beehiiv.com",
    "buttondown.email",
    "mailchimp.com",
    "hackernoon.com",
    "dev.to",
    "stratechery.com",
)


def _strip_known_mobile_prefix(host: str) -> str:
    for prefix in ("www.", "m.", "mobile.", "old."):
        if host.startswith(prefix):
            return host[len(prefix) :]
    return host


def detect_source_type(url: str) -> SourceType:
    """Detect a source type, returning WEB for unknown or malformed URLs."""
    if not url:
        return SourceType.WEB
    try:
        parsed = urlparse(url)
    except ValueError:
        return SourceType.WEB

    host = (parsed.hostname or "").lower()
    if not host:
        return SourceType.WEB
    host = _strip_known_mobile_prefix(host)

    for domains, source_type in _DOMAIN_RULES:
        for domain in domains:
            if host == domain or host.endswith("." + domain):
                return source_type

    for domain in _NEWSLETTER_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return SourceType.NEWSLETTER

    return SourceType.WEB

