"""RFC 7232 conditional-request helpers — shared 304 gate.

One implementation of the ``If-None-Match`` weak comparison so every route's 304
short-circuit derives from the same gate instead of re-deriving it inline and
getting it subtly wrong. The recurring bug: Cloudflare rewrites our strong ETag
to a weak one (``W/"…"``) when it compresses the response, and a naive
``header == etag`` check then never matches, so the 304 path silently dies behind
the CDN and the endpoint returns 200 on every revalidation.

Used by ``GET /api/avatars`` and ``GET /api/profile/stats``.
"""
from __future__ import annotations


def _normalize_etag(tag: str) -> str:
    """Strip the optional weak ``W/`` prefix and surrounding quotes (RFC 7232 §2.3)."""
    tag = tag.strip()
    if tag[:2] in ("W/", "w/"):
        tag = tag[2:]
    return tag.strip().strip('"')


def if_none_match(header_value: str | None, etag: str) -> bool:
    """True iff ``If-None-Match`` matches ``etag`` under RFC 7232 §3.2 weak comparison.

    Handles the ``W/`` weak prefix, the comma-separated validator list, and the
    ``*`` wildcard. Both sides are normalized, so a quoted/unquoted or weak/strong
    mismatch between what the server emitted and what an intermediary echoes back
    still matches. Returns False for an empty header or an empty server etag.
    """
    if not header_value or not etag:
        return False
    target = _normalize_etag(etag)
    for token in header_value.split(","):
        token = token.strip()
        if token == "*":
            return True
        if _normalize_etag(token) == target:
            return True
    return False
