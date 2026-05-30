"""R7 (2026-05-30): avatar preset manifest + drift guard.

The avatar count was hardcoded in four places (on-disk files, the backend
validator, the desktop picker JS, the mobile avatar JS). GET /api/avatars now
exposes the on-disk set as the single source of truth; this test is the CI
guard that fails the build if any of the four drift apart.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from website.api.routes import _AVATAR_IDS, _scan_avatar_ids

REPO = Path(__file__).resolve().parents[3]
AVATARS_DIR = REPO / "website" / "artifacts" / "avatars"


def _disk_ids() -> list[int]:
    return sorted(
        int(m.group(1))
        for p in AVATARS_DIR.glob("avatar_*.svg")
        if (m := re.match(r"^avatar_(\d{2})\.svg$", p.name))
    )


def test_disk_set_is_contiguous_from_zero():
    ids = _disk_ids()
    assert ids, "no avatar SVGs found on disk"
    assert ids == list(range(len(ids))), f"avatar IDs not contiguous from 0: {ids}"


def test_backend_scan_matches_disk():
    assert _scan_avatar_ids() == _disk_ids()
    assert _AVATAR_IDS == _disk_ids()


def test_get_avatars_manifest_shape_and_headers():
    from website.app import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/api/avatars")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    disk = _disk_ids()
    assert body["count"] == len(disk)
    assert [a["id"] for a in body["avatars"]] == disk
    assert body["avatars"][0]["url"] == "/artifacts/avatars/avatar_00.svg"
    cc = resp.headers.get("cache-control", "")
    assert "max-age" in cc and "public" in cc
    assert resp.headers.get("etag")


def test_get_avatars_etag_304():
    from website.app import create_app

    with TestClient(create_app()) as client:
        first = client.get("/api/avatars")
        etag = first.headers["etag"]
        second = client.get("/api/avatars", headers={"If-None-Match": etag})
    assert second.status_code == 304


def test_js_constants_match_disk_count():
    """The two JS bundles still carry a hardcoded count for synchronous render;
    pin them against the on-disk set so a future add/remove can't silently break
    the picker grid."""
    n = len(_disk_ids())
    profile_js = (REPO / "website" / "features" / "user_profile" / "js" / "user_profile.js").read_text(encoding="utf-8")
    header_js = (REPO / "website" / "features" / "header" / "js" / "header.js").read_text(encoding="utf-8")
    mobile_js = (REPO / "website" / "mobile" / "js" / "avatar.js").read_text(encoding="utf-8")

    m_profile = re.search(r"AVATAR_COUNT\s*=\s*(\d+)", profile_js)
    m_header = re.search(r"AVATAR_COUNT\s*=\s*(\d+)", header_js)
    m_mobile = re.search(r"length:\s*(\d+)\s*\}", mobile_js)

    assert m_profile and int(m_profile.group(1)) == n, "user_profile.js AVATAR_COUNT drifted from disk"
    assert m_header and int(m_header.group(1)) == n, "header.js AVATAR_COUNT drifted from disk"
    assert m_mobile and int(m_mobile.group(1)) == n, "mobile avatar.js ALL_AVATARS length drifted from disk"
