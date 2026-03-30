"""Source-type auto-detection registry.

Maps a URL to the appropriate :class:`SourceType` by inspecting its hostname.
The detection order matters: more specific patterns (Reddit, YouTube, GitHub)
are checked before the newsletter list, which falls back to Generic.
"""

from __future__ import annotations

import urllib.parse

from zettelkasten_bot.models.capture import SourceType


def detect_source_type(
    url: str,
    newsletter_domains: list[str] | None = None,
) -> SourceType:
    """Detect the :class:`SourceType` for *url* based on its hostname.

    Detection priority:
    1. **Reddit** — hostname contains ``reddit.com`` or ``redd.it``
    2. **YouTube** — hostname contains ``youtube.com`` or ``youtu.be``
    3. **GitHub** — hostname contains ``github.com``
    4. **Newsletter** — hostname ends with any domain in *newsletter_domains*
    5. **Generic** — everything else

    Args:
        url: A well-formed URL string.
        newsletter_domains: Optional list of newsletter domain suffixes to
            match against.  When *None*, the list is loaded from
            :func:`~zettelkasten_bot.config.settings.get_settings`.

    Returns:
        The inferred :class:`SourceType`.
    """
    if newsletter_domains is None:
        # Import lazily to avoid circular imports and to allow the module to be
        # imported without valid credentials (useful in tests).
        from zettelkasten_bot.config.settings import get_settings  # noqa: PLC0415

        try:
            newsletter_domains = get_settings().newsletter_domains
        except SystemExit:
            # Settings not configured (e.g. missing token in tests) — fall back
            # to an empty list so detection still works for the other types.
            newsletter_domains = []

    parsed = urllib.parse.urlparse(url)
    # Normalise: drop port, lowercase
    host: str = parsed.hostname or ""

    # ── Reddit ────────────────────────────────────────────────────────────────
    # Exclude media-only hosts (i.redd.it, v.redd.it, preview.redd.it) which
    # are direct image/video links without post context — route to Generic.
    _REDDIT_MEDIA_HOSTS = {"i.redd.it", "v.redd.it", "preview.redd.it"}
    if host not in _REDDIT_MEDIA_HOSTS:
        if "reddit.com" in host or "redd.it" in host or host == "reddit.app.link":
            return SourceType.REDDIT

    # ── YouTube ───────────────────────────────────────────────────────────────
    # Includes youtube-nocookie.com (privacy/embed variant)
    if "youtube.com" in host or "youtube-nocookie.com" in host or "youtu.be" in host:
        return SourceType.YOUTUBE

    # ── GitHub ────────────────────────────────────────────────────────────────
    # Exclude gist.github.com — different structure, route to Generic.
    if "github.com" in host and not host.startswith("gist."):
        return SourceType.GITHUB

    # ── Newsletter ────────────────────────────────────────────────────────────
    for domain in newsletter_domains:
        # Match exact domain or any subdomain (e.g. user.substack.com)
        if host == domain or host.endswith("." + domain):
            return SourceType.NEWSLETTER

    # ── Generic ───────────────────────────────────────────────────────────────
    return SourceType.GENERIC
