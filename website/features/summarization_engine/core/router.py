"""URL to SourceType detection for the summarization engine.

Also exposes thin delegating wrappers for the YouTube format classifier and
GitHub archetype classifier so the orchestrator / per-source summarizers have
a single import surface for routing decisions (URL -> source, content ->
format/archetype). The wrappers MUST be safe no-ops on empty/None input so
callers do not need to duplicate guard logic at every site.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
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

logger = logging.getLogger(__name__)

_DOMAIN_RULES: list[tuple[tuple[str, ...], SourceType]] = [
    (("github.com",), SourceType.GITHUB),
    (("news.ycombinator.com",), SourceType.HACKERNEWS),
    (("arxiv.org", "ar5iv.labs.arxiv.org"), SourceType.ARXIV),
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


@dataclass(frozen=True)
class RouteDecision:
    """Structured route contract for source-aware ingestion.

    ``detect_source_type`` stays as the compatibility API. New callers can use
    this richer object to distinguish a supported repo URL from a GitHub issue,
    or a YouTube video URL from a channel/playlist shape that the summarizer
    should not pretend is video content.
    """

    source_type: SourceType
    subtype: str
    supported: bool = True
    reason: str | None = None


def _strip_known_mobile_prefix(host: str) -> str:
    for prefix in ("www.", "m.", "mobile.", "old."):
        if host.startswith(prefix):
            return host[len(prefix) :]
    return host


def _looks_like_newsletter_post(path: str) -> bool:
    normalized = (path or "").rstrip("/")
    return normalized == "/p" or normalized.startswith("/p/")


def _reddit_route(host: str, path: str) -> RouteDecision:
    """Route a Reddit URL by path shape.

    Only single-submission permalinks are supported for ingestion. Listings,
    wikis, user pages, multireddits, and bare comment permalinks return
    ``supported=False`` so the orchestrator refuses them at the gate instead of
    fetching a listing and persisting an empty/garbage zettel (the old generic
    route accepted every Reddit path and silently polluted the corpus).
    """

    def _unsupported(subtype: str) -> RouteDecision:
        return RouteDecision(
            SourceType.REDDIT, subtype, False, "unsupported_reddit_url_shape"
        )

    # redd.it short links always resolve to one submission (e.g. redd.it/abc123).
    if host == "redd.it" or host.endswith(".redd.it"):
        slug = path.strip("/")
        if slug and "/" not in slug:
            return RouteDecision(SourceType.REDDIT, "post_shortlink")
        return _unsupported("unknown")

    parts = [p for p in path.split("/") if p]

    # /user/<name>[/m/<multi>]  or  /u/<name>...
    if parts and parts[0] in {"user", "u"}:
        if len(parts) >= 4 and parts[2] == "m":
            return _unsupported("multireddit")
        return _unsupported("user_profile")

    # /comments/<id> — subreddit-less submission permalink.
    if parts and parts[0] == "comments":
        if len(parts) >= 2:
            return RouteDecision(SourceType.REDDIT, "post")
        return _unsupported("unknown")

    # /r/<sub>/...
    if len(parts) >= 2 and parts[0] == "r":
        if len(parts) >= 3 and parts[2] == "wiki":
            return _unsupported("wiki")
        if len(parts) >= 4 and parts[2] == "comments":
            # /r/<sub>/comments/<id>/<slug>/<commentid> => 6+ segments = a single
            # comment, whose JSON shape is not a thread; refuse it.
            if len(parts) >= 6:
                return _unsupported("comment_permalink")
            return RouteDecision(SourceType.REDDIT, "post")
        # /r/<sub>[/<sort>] and any other non-thread subreddit page.
        return _unsupported("subreddit_listing")

    return _unsupported("unknown")


def detect_source_type(url: str) -> SourceType:
    """Detect a source type, returning WEB for unknown or malformed URLs."""
    return detect_route_decision(url).source_type


def detect_route_decision(url: str) -> RouteDecision:
    """Detect source family plus object subtype/support contract."""
    if not url:
        return RouteDecision(SourceType.WEB, "unknown", False, "empty_url")
    try:
        parsed = urlparse(url)
    except ValueError:
        return RouteDecision(SourceType.WEB, "unknown", False, "malformed_url")

    host = (parsed.hostname or "").lower()
    if not host:
        return RouteDecision(SourceType.WEB, "unknown", False, "missing_host")
    host = _strip_known_mobile_prefix(host)
    path = parsed.path or ""

    if host == "youtu.be" or host.endswith(".youtu.be"):
        subtype = "video" if path.strip("/") else "unknown"
        return RouteDecision(
            SourceType.YOUTUBE,
            subtype,
            bool(path.strip("/")),
            None if path.strip("/") else "missing_youtube_video_id",
        )
    if host == "youtube.com" or host.endswith(".youtube.com"):
        normalized = path.rstrip("/") or "/"
        if parsed.query and query_param_from_parsed(parsed.query, "v"):
            return RouteDecision(SourceType.YOUTUBE, "video")
        if normalized.startswith("/shorts/") or normalized.startswith("/embed/"):
            return RouteDecision(SourceType.YOUTUBE, "video")
        if normalized.startswith("/playlist"):
            return RouteDecision(
                SourceType.YOUTUBE,
                "playlist",
                False,
                "unsupported_youtube_playlist",
            )
        if normalized.startswith("/@") or normalized.startswith("/channel/") or normalized.startswith("/c/"):
            return RouteDecision(
                SourceType.YOUTUBE,
                "channel",
                False,
                "unsupported_youtube_channel",
            )
        return RouteDecision(
            SourceType.YOUTUBE,
            "unknown",
            False,
            "unsupported_youtube_url_shape",
        )

    if host == "github.com" or host.endswith(".github.com"):
        parts = [p for p in path.split("/") if p]
        subtype = "repo"
        if len(parts) >= 4 and parts[2] in {"issues", "issue"}:
            subtype = "issue"
        elif len(parts) >= 4 and parts[2] in {"pull", "pulls"}:
            subtype = "pull_request"
        elif len(parts) >= 4 and parts[2] == "commit":
            subtype = "commit"
        elif len(parts) >= 3 and parts[2] == "releases":
            subtype = "release"
        elif len(parts) >= 4 and parts[2] == "blob":
            subtype = "blob"
        elif len(parts) >= 4 and parts[2] == "tree":
            subtype = "tree"
        supported = len(parts) >= 2
        return RouteDecision(
            SourceType.GITHUB,
            subtype if supported else "unknown",
            supported,
            None if supported else "missing_github_owner_repo",
        )

    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        normalized = path.rstrip("/") or "/"
        if normalized.startswith("/login") or normalized.startswith("/checkpoint"):
            return RouteDecision(
                SourceType.LINKEDIN,
                "authwall",
                False,
                "unsupported_linkedin_authwall",
            )
        if normalized.startswith("/posts/"):
            return RouteDecision(SourceType.LINKEDIN, "post")
        if normalized.startswith("/pulse/"):
            return RouteDecision(SourceType.LINKEDIN, "article")
        if normalized.startswith("/company/"):
            return RouteDecision(SourceType.LINKEDIN, "company")
        if normalized.startswith("/in/"):
            return RouteDecision(SourceType.LINKEDIN, "profile")
        return RouteDecision(SourceType.LINKEDIN, "public_page")

    if host == "ar5iv.labs.arxiv.org" or host.endswith(".ar5iv.labs.arxiv.org"):
        return RouteDecision(SourceType.ARXIV, "html")
    if host == "arxiv.org" or host.endswith(".arxiv.org"):
        if path.startswith("/pdf/"):
            return RouteDecision(SourceType.ARXIV, "pdf")
        if path.startswith("/html/"):
            return RouteDecision(SourceType.ARXIV, "html")
        return RouteDecision(SourceType.ARXIV, "abstract")

    if host in {"twitter.com", "x.com"} or host.endswith(".twitter.com") or host.endswith(".x.com"):
        return RouteDecision(
            SourceType.TWITTER,
            "status" if "/status/" in path else "public_page",
            "/status/" in path,
            None if "/status/" in path else "unsupported_twitter_url_shape",
        )

    if (
        host == "reddit.com"
        or host.endswith(".reddit.com")
        or host == "redd.it"
        or host.endswith(".redd.it")
    ):
        return _reddit_route(host, path)

    for domains, source_type in _DOMAIN_RULES:
        for domain in domains:
            if host == domain or host.endswith("." + domain):
                subtype = "episode" if source_type == SourceType.PODCAST else source_type.value
                return RouteDecision(source_type, subtype)

    for domain in _NEWSLETTER_DOMAINS:
        if host == domain or host.endswith("." + domain):
            subtype = "post" if _looks_like_newsletter_post(parsed.path) else "publication_page"
            return RouteDecision(SourceType.NEWSLETTER, subtype)

    if _looks_like_newsletter_post(parsed.path):
        for suffix in _NEWSLETTER_CUSTOM_SUFFIXES:
            if host.endswith(suffix):
                return RouteDecision(SourceType.NEWSLETTER, "post")

    return RouteDecision(SourceType.WEB, "page")


# Newsletter-probe signal matchers. Precision-first: we only upgrade WEB ->
# NEWSLETTER on signals that distinguish a blog/newsletter from a news site.
# Bare RSS autodiscovery and the WordPress generator are intentionally NOT
# triggers — news sites (CNN/BBC/NYT) expose RSS and run WordPress too, and a
# schema.org NewsArticle is not a newsletter.
_PROBE_HEAD_BYTES = 16384
_PROBE_TIMEOUT_SEC = 4.0
_GENERATOR_META_RE = re.compile(r"<meta\b[^>]*\bname=[\"']?generator[\"']?[^>]*>", re.IGNORECASE)
_NEWSLETTER_PLATFORM_RE = re.compile(
    r"\b(substack|ghost|beehiiv|buttondown|jekyll|hugo)\b", re.IGNORECASE
)
_BLOGPOSTING_JSONLD_RE = re.compile(
    r'"@type"\s*:\s*(?:"BlogPosting"|\[[^\]]*"BlogPosting")', re.IGNORECASE
)


def _newsletter_signal(html: str) -> str | None:
    """Return a reason string if the HTML head carries a high-precision
    newsletter/blog signal, else None. Only the first ``_PROBE_HEAD_BYTES`` are
    inspected so a huge body cannot blow up RAM or CPU."""
    if not html:
        return None
    head = html[:_PROBE_HEAD_BYTES]
    if _BLOGPOSTING_JSONLD_RE.search(head):
        return "probe_blogposting"
    for meta_tag in _GENERATOR_META_RE.findall(head):
        if _NEWSLETTER_PLATFORM_RE.search(meta_tag):
            return "probe_generator"
    return None


async def _default_probe_fetcher(url: str) -> str:
    """Bounded, SSRF-guarded HEAD-region fetch for the newsletter probe.

    Reuses the ingest layer's ``fetch_text`` (which routes through
    ``safe_request`` — the same private-IP/redirect guard the ingestors use).
    Lazy-imported to avoid a load-time circular import (utils imports models).
    """
    from website.features.summarization_engine.source_ingest.utils import fetch_text

    text, _final_url = await fetch_text(
        url,
        headers={
            "Range": f"bytes=0-{_PROBE_HEAD_BYTES}",
            "User-Agent": "ZettelkastenBot/1.0 (+newsletter-probe)",
        },
        timeout=_PROBE_TIMEOUT_SEC,
    )
    return text or ""


async def refine_web_route(
    url: str,
    decision: RouteDecision,
    *,
    fetcher: Callable[[str], Awaitable[str]] | None = None,
) -> RouteDecision:
    """Probe a generic-WEB URL for newsletter signals and upgrade if found.

    No-op for any non-WEB decision (the sync router already classified it). On
    a WEB decision, fetch the head region and look for a BlogPosting JSON-LD or
    a newsletter-platform ``generator`` meta. Any fetch/parse failure leaves the
    decision as WEB — the probe can never break ingestion, only enrich it.
    """
    if decision.source_type != SourceType.WEB:
        return decision
    fetch = fetcher or _default_probe_fetcher
    try:
        html = await fetch(url)
    except Exception:
        logger.warning("router.web_probe_fetch_failed url=%s", url, exc_info=True)
        return decision
    signal = _newsletter_signal(html or "")
    if signal:
        logger.info("router.web_probe_upgrade url=%s signal=%s", url, signal)
        return RouteDecision(SourceType.NEWSLETTER, "post", True, signal)
    return decision


def query_param_from_parsed(query: str, key: str) -> str | None:
    """Small local query parser to keep router independent from ingest utils."""
    from urllib.parse import parse_qs

    values = parse_qs(query or "").get(key)
    if not values:
        return None
    return values[0] or None


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
