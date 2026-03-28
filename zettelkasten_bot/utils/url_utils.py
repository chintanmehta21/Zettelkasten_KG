"""URL validation, normalization, redirect-resolution, and shortener detection.

All functions are pure/stateless except `resolve_redirects` which is async
and makes a real HTTP request (mocked in tests).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

# Tracking parameters to strip from query strings
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "ref",
        "source",
    }
)

# Known URL-shortener hostnames (without 'www.' prefix)
_SHORTENER_HOSTS: frozenset[str] = frozenset(
    {
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "ow.ly",
        "is.gd",
        "buff.ly",
        "adf.ly",
        "shorturl.at",
        "rb.gy",
        "v.gd",
        "tiny.cc",
        "lnkd.in",
        "amzn.to",
        "youtu.be",
        "redd.it",
    }
)


def _is_private_ip(hostname: str) -> bool:
    """Return True if *hostname* resolves to a private, loopback, or reserved IP.

    Used to prevent SSRF attacks when deployed on a VPS — blocks requests to
    internal services, cloud metadata endpoints (169.254.169.254), and loopback.
    """
    try:
        # Try parsing as a literal IP address first (no DNS lookup needed)
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        pass

    # Hostname — resolve via DNS and check the result
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _family, _type, _proto, _canonname, sockaddr in results:
            ip_str = sockaddr[0]
            addr = ipaddress.ip_address(ip_str)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return True
    except (socket.gaierror, OSError):
        # DNS resolution failed — let the caller handle it downstream
        pass
    return False


def validate_url(url: str) -> bool:
    """Return True if *url* has an http/https scheme and a non-empty hostname.

    Also rejects URLs that resolve to private/reserved IP addresses to
    prevent SSRF attacks when the bot is deployed on a server.

    Args:
        url: The URL string to validate.  Must not be None (TypeError raised).

    Returns:
        True when the URL is well-formed, uses http or https, and does not
        target a private IP.  False otherwise.

    Raises:
        TypeError: When *url* is None.
    """
    if url is None:
        raise TypeError("url must be a str, not None")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False

    hostname = parsed.hostname or ""
    if _is_private_ip(hostname):
        logger.warning("Blocked private/reserved IP in URL: %s", url)
        return False

    return True


def normalize_url(url: str) -> str:
    """Return a canonicalized form of *url*.

    Transformations applied:
    - Lowercase scheme and hostname.
    - Remove URL fragment (``#...``).
    - Strip tracking query parameters (UTM, fbclid, gclid, ref, source).
    - Sort the remaining query parameters for deterministic comparison.

    The path and port are left unchanged; only the components listed above
    are touched.

    Args:
        url: A well-formed http/https URL string.

    Returns:
        Normalized URL string.
    """
    parsed = urllib.parse.urlparse(url)

    # Lowercase scheme and netloc (host + optional port)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Filter out tracking parameters; sort the rest
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(k, v) for k, v in query_params if k.lower() not in _TRACKING_PARAMS]
    # Sort by key for deterministic output
    filtered.sort(key=lambda kv: kv[0])
    new_query = urllib.parse.urlencode(filtered)

    # Rebuild — strip fragment by passing empty string
    normalized = urllib.parse.urlunparse(
        (scheme, netloc, parsed.path, parsed.params, new_query, "")
    )
    return normalized


async def resolve_redirects(url: str) -> str:
    """Follow redirect chains and return the final URL.

    Uses a HEAD request first (cheap); falls back to GET if the server
    returns a 4xx/5xx on HEAD.  Timeout is capped at 10 seconds.

    On *any* exception (network error, timeout, malformed response) the
    original URL is returned unchanged and a warning is logged.

    Args:
        url: The initial URL to resolve.

    Returns:
        The final URL after all redirects, or *url* unchanged on error.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            try:
                response = await client.head(url)
                # Some servers disallow HEAD; retry with GET
                if response.status_code >= 400:
                    response = await client.get(url)
            except httpx.UnsupportedProtocol:
                # HEAD not supported by some servers, try GET
                response = await client.get(url)
            return str(response.url)
    except httpx.TimeoutException:
        logger.warning("Timeout resolving redirects for %s — returning original URL", url)
        return url
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error resolving redirects for %s: %s — returning original URL", url, exc)
        return url


def is_shortener(url: str) -> bool:
    """Return True if *url* is hosted on a known URL-shortener service.

    The check is based on the hostname only (scheme and path are ignored).

    Args:
        url: A URL string to inspect.

    Returns:
        True when the hostname matches a known shortener, False otherwise.
    """
    parsed = urllib.parse.urlparse(url)
    # Strip leading 'www.' for comparison
    host = parsed.netloc.lower().removeprefix("www.")
    return host in _SHORTENER_HOSTS
