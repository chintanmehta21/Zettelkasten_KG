"""URL to SourceType detection for the summarization engine.

Also exposes thin delegating wrappers for the YouTube format classifier and
GitHub archetype classifier so the orchestrator / per-source summarizers have
a single import surface for routing decisions (URL -> source, content ->
format/archetype). The wrappers MUST be safe no-ops on empty/None input so
callers do not need to duplicate guard logic at every site.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
    classify_archetype,
)
from website.features.summarization_engine.summarization.youtube.format_classifier import (
    FORMAT_LABELS,
    classify_format,
)

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
    "platformer.news",
    "pragmaticengineer.com",
)
_NEWSLETTER_CUSTOM_SUFFIXES: tuple[str, ...] = (".news",)


def _strip_known_mobile_prefix(host: str) -> str:
    for prefix in ("www.", "m.", "mobile.", "old."):
        if host.startswith(prefix):
            return host[len(prefix) :]
    return host


def _looks_like_newsletter_post(path: str) -> bool:
    normalized = (path or "").rstrip("/")
    return normalized == "/p" or normalized.startswith("/p/")


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

    if _looks_like_newsletter_post(parsed.path):
        for suffix in _NEWSLETTER_CUSTOM_SUFFIXES:
            if host.endswith(suffix):
                return SourceType.NEWSLETTER

    return SourceType.WEB


# Default fallbacks used when input is empty/None. Kept module-private so
# callers cannot drift from the contract.
_YOUTUBE_DEFAULT_FORMAT = "commentary"
_YOUTUBE_DEFAULT_CONFIDENCE = 0.0
_GITHUB_DEFAULT_ARCHETYPE = RepoArchetype.LIBRARY_THIN.value


def classify_youtube_format(transcript: str | None) -> tuple[str, float]:
    """Return ``(format_label, confidence)`` for a YouTube transcript.

    Thin wrapper around :func:`...youtube.format_classifier.classify_format`.
    The underlying classifier scores against title / description / chapter
    titles / speakers; when only a raw transcript is available we feed it as
    the description signal so lexical cues (`tutorial`, `interview`, etc.)
    still fire. On empty/None input returns the default label with confidence
    ``0.0`` so callers can branch on confidence safely.
    """
    if not transcript or not str(transcript).strip():
        return _YOUTUBE_DEFAULT_FORMAT, _YOUTUBE_DEFAULT_CONFIDENCE
    label, confidence = classify_format(
        title="",
        description=str(transcript),
        chapter_titles=[],
        speakers=[],
    )
    if label not in FORMAT_LABELS:
        return _YOUTUBE_DEFAULT_FORMAT, _YOUTUBE_DEFAULT_CONFIDENCE
    return label, float(confidence)


def classify_github_archetype(repo_metadata: dict[str, Any] | None) -> str:
    """Return the archetype string for a GitHub repo metadata dict.

    Thin wrapper around :func:`...github.archetype.classify_archetype`. The
    underlying classifier needs ``raw_text`` plus optional metadata; the
    metadata dict accepted here may carry ``raw_text`` / ``readme`` /
    ``description`` plus structural metadata (``topics``, ``language``,
    ``has_*`` flags). On empty/None input returns ``"library"`` (mapped to
    :data:`RepoArchetype.LIBRARY_THIN`) so the caller always has a usable
    label.
    """
    if not repo_metadata or not isinstance(repo_metadata, dict):
        return _GITHUB_DEFAULT_ARCHETYPE
    raw_text = (
        repo_metadata.get("raw_text")
        or repo_metadata.get("readme")
        or repo_metadata.get("description")
        or ""
    )
    if not isinstance(raw_text, str) or not raw_text.strip():
        return _GITHUB_DEFAULT_ARCHETYPE
    structural = {
        k: v for k, v in repo_metadata.items()
        if k not in {"raw_text", "readme", "description"}
    }
    verdict = classify_archetype(raw_text=raw_text, metadata=structural)
    return verdict.archetype.value
