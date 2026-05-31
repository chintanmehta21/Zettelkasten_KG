"""Shared RFC 7232 If-None-Match gate (website.features.functional_gates.etag).

One weak-comparison predicate reused by GET /api/avatars and GET /api/profile/stats
so neither re-derives 304 matching inline. The recurring failure it guards: a
naive ``header == etag`` returns 200 forever once an intermediary (Cloudflare on
compression) rewrites the strong ETag to a weak ``W/"…"`` validator.
"""
from __future__ import annotations

import pytest

from website.features.functional_gates import if_none_match

ETAG = "08d27272241d5e0b6bb517b025acfad0"


@pytest.mark.parametrize(
    "header,expected",
    [
        (f'"{ETAG}"', True),                     # strong, quoted (what we emit)
        (ETAG, True),                            # raw / unquoted (profile-stats form)
        (f'W/"{ETAG}"', True),                   # weak — the Cloudflare-compression case
        (f'w/"{ETAG}"', True),                   # lowercase weak indicator (lenient)
        ("*", True),                             # wildcard
        (f'"deadbeef", W/"{ETAG}"', True),       # comma list, match is second
        (f'  W/"{ETAG}"  ', True),               # surrounding whitespace
        ('"deadbeef"', False),                   # different validator
        ('W/"deadbeef"', False),                 # weak, different validator
        (None, False),                           # no header
        ("", False),                             # empty header
        ("   ", False),                          # blank header
    ],
)
def test_if_none_match(header, expected):
    assert if_none_match(header, ETAG) is expected


def test_empty_server_etag_never_matches():
    # No representation/validator on the server side → never 304, even on '*'.
    assert if_none_match("*", "") is False
    assert if_none_match(f'"{ETAG}"', "") is False


def test_quoted_or_unquoted_server_etag_both_match():
    # The gate normalizes both sides, so callers may pass either form.
    assert if_none_match(f'"{ETAG}"', f'"{ETAG}"') is True
    assert if_none_match(f'"{ETAG}"', ETAG) is True
    assert if_none_match(f'W/"{ETAG}"', f'"{ETAG}"') is True
