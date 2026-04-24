"""Newsletter liveness probe.

Content-based heuristic only — no network I/O. Callers pre-fetch html
and pass it in (or pass None to fall back to URL-pattern checks).
"""
from __future__ import annotations

from urllib.parse import urlparse

_DEAD_HTML_MARKERS: tuple[str, ...] = (
    # Generic / newsletter
    "404",
    "page not found",
    "410",
    "<title>gone</title>",
    # YouTube — "Video unavailable" appears in HTML for removed/private videos
    "video unavailable",
    "this video isn't available anymore",
    # GitHub — both repo-deleted and 404 sub-page strings
    "404 - page not found",
    "this is not the web page you are looking for",
    # Reddit — deleted posts/users render these literal markers in HTML
    "[deleted]",
    "[removed]",
    "this community has been banned",
    "page not found - reddit",
)

_DEAD_PATH_SUFFIXES: tuple[str, ...] = (
    "/unsubscribe",
    "/archive/deleted",
    "/p/deleted-post",
)


def is_live_newsletter(url: str, html: str | None = None) -> tuple[bool, str]:
    if html is not None:
        body = html.strip()
        if not body:
            return (False, "dead")
        lowered = body.lower()
        for marker in _DEAD_HTML_MARKERS:
            if marker in lowered:
                return (False, "dead")

    if html is None:
        # No html provided and no body to inspect — only URL-pattern check below.
        pass

    parsed = urlparse(url or "")
    path = (parsed.path or "").rstrip("/").lower()
    full = (parsed.path or "").lower()
    for suffix in _DEAD_PATH_SUFFIXES:
        if path.endswith(suffix) or full.endswith(suffix):
            return (False, "dead")

    if html is None and not url:
        return (False, "dead")

    return (True, "ok")


def liveness_probe(urls: list[str]) -> dict[str, tuple[bool, str]]:
    return {url: is_live_newsletter(url) for url in urls}
