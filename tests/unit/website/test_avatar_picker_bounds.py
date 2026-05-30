"""Regression + smoke tests for the 120-slot avatar picker surface.

Covers:
  * ``website.app._CURATED_AVATAR_RE`` accepts 00-119 and rejects overflow / junk
  * ``website.api.routes.AvatarUpdateRequest`` enforces 0 <= avatar_id <= 119
  * Desktop renderAvatarGrid emits fetchpriority="high" on first 8 + lazy+low rest
  * Mobile renderPicker eager-loads first 4 with fetchpriority="high"
  * Picker CSS applies content-visibility on grid cells

Both client-side checks are static-string assertions on the JS source — the
picker render path is browser-only, so this is the cheapest defense against
regression of the perf knobs (web.dev fetch-priority + content-visibility).
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
WEBSITE = REPO_ROOT / "website"


# ──────────────────────────────────────────────────────────────────────────
# Regex regression — _CURATED_AVATAR_RE
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "/artifacts/avatars/avatar_00.svg",
        "/artifacts/avatars/avatar_09.svg",
        "/artifacts/avatars/avatar_59.svg",
        "/artifacts/avatars/avatar_60.svg",  # first new bundle
        "/artifacts/avatars/avatar_99.svg",
        "/artifacts/avatars/avatar_100.svg",  # 3-digit boundary
        "/artifacts/avatars/avatar_119.svg",  # last present asset
    ],
)
def test_curated_avatar_regex_accepts_valid_ids(url: str) -> None:
    from website.app import _CURATED_AVATAR_RE

    assert _CURATED_AVATAR_RE.match(url) is not None, f"should accept: {url}"


@pytest.mark.parametrize(
    "url",
    [
        "/artifacts/avatars/avatar_0.svg",        # 1-digit
        "/artifacts/avatars/avatar_120.svg",      # one past the pool (no file)
        "/artifacts/avatars/avatar_199.svg",      # in 3-digit space, no file
        "/artifacts/avatars/avatar_200.svg",      # 2xx, no file
        "/artifacts/avatars/avatar_999.svg",      # max 3-digit, no file
        "/artifacts/avatars/avatar_1000.svg",     # 4-digit
        "/artifacts/avatars/avatar_abc.svg",      # non-numeric
        "/artifacts/avatars/avatar_-1.svg",       # signed
        "/artifacts/avatars/../passwd",           # traversal
        "/artifacts/avatars/avatar_00.png",       # wrong ext
        "/artifacts/avatars/avatar_00.svg.bak",   # trailing junk
        "https://evil.example/avatar_00.svg",     # absolute external
        "",
    ],
)
def test_curated_avatar_regex_rejects_invalid(url: str) -> None:
    from website.app import _CURATED_AVATAR_RE

    assert _CURATED_AVATAR_RE.match(url) is None, f"should reject: {url}"


# ──────────────────────────────────────────────────────────────────────────
# Pydantic regression — AvatarUpdateRequest bound
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("avatar_id", [0, 1, 59, 60, 99, 100, 119])
def test_avatar_update_request_accepts_in_range(avatar_id: int) -> None:
    from website.api.routes import AvatarUpdateRequest

    req = AvatarUpdateRequest(avatar_id=avatar_id)
    assert req.avatar_id == avatar_id


@pytest.mark.parametrize("avatar_id", [-1, 120, 200, 9999])
def test_avatar_update_request_rejects_out_of_range(avatar_id: int) -> None:
    from pydantic import ValidationError

    from website.api.routes import AvatarUpdateRequest

    with pytest.raises(ValidationError):
        AvatarUpdateRequest(avatar_id=avatar_id)


# ──────────────────────────────────────────────────────────────────────────
# Smoke — desktop picker render emits priority hints
# ──────────────────────────────────────────────────────────────────────────


def _read(rel: str) -> str:
    return (WEBSITE / rel).read_text(encoding="utf-8")


def test_desktop_picker_emits_priority_hints() -> None:
    src = _read("features/user_profile/js/user_profile.js")
    assert "AVATAR_COUNT = 120" in src, "desktop picker must size to 120 avatars"
    assert "AVATAR_EAGER_COUNT = 8" in src, "first-row eager count must be 8"
    assert 'fetchpriority="high"' in src, "first-row cells need fetchpriority=high"
    assert 'fetchpriority="low"' in src, "below-fold cells need fetchpriority=low"
    assert 'loading="lazy"' in src, "below-fold cells need native lazy loading"


def test_mobile_picker_emits_priority_hints() -> None:
    src = _read("mobile/js/profile.js")
    assert "MOBILE_EAGER_COUNT = 4" in src, "mobile first-row eager count must be 4"
    assert 'fetchpriority="high"' in src, "first-row cells need fetchpriority=high"
    assert 'fetchpriority="low"' in src, "below-fold cells need fetchpriority=low"


def test_shared_avatar_renderer_sized_to_120() -> None:
    # avatar.js is the shared mobile+desktop renderer; window.ZK.avatarUrls()
    # feeds the mobile picker. It has its own pool size + curated regex that
    # must stay in sync with website/app.py::_CURATED_AVATAR_RE.
    src = _read("mobile/js/avatar.js")
    assert "length: 120" in src, "shared avatar pool must be 120"
    assert r"0\d|[1-9]\d|1[01]\d" in src, "shared curated regex must bound to 0-119"


def test_mobile_profile_curated_regex_bounds_to_119() -> None:
    # profile.js has an inline isCuratedAvatarUrl gate guarding selectAvatar.
    src = _read("mobile/js/profile.js")
    assert r"0\d|[1-9]\d|1[01]\d" in src, "mobile selectAvatar gate must bound to 0-119"


# ──────────────────────────────────────────────────────────────────────────
# Smoke — content-visibility CSS present on grid cells
# ──────────────────────────────────────────────────────────────────────────


def test_desktop_picker_css_has_content_visibility() -> None:
    css = _read("features/user_profile/css/user_profile.css")
    assert "content-visibility: auto" in css, "desktop grid cell needs content-visibility"
    assert "contain-intrinsic-size" in css, "desktop grid cell needs intrinsic-size reservation"


def test_mobile_picker_css_has_content_visibility() -> None:
    css = _read("mobile/css/components/avatar-picker.css")
    assert "content-visibility: auto" in css, "mobile grid cell needs content-visibility"
    assert "contain-intrinsic-size" in css, "mobile grid cell needs intrinsic-size reservation"


# ──────────────────────────────────────────────────────────────────────────
# Smoke — asset count on disk matches advertised picker capacity
# ──────────────────────────────────────────────────────────────────────────


def test_avatar_asset_count_matches_picker() -> None:
    avatars_dir = WEBSITE / "artifacts" / "avatars"
    svgs = sorted(avatars_dir.glob("avatar_*.svg"))
    assert len(svgs) == 120, f"expected 120 avatar SVGs on disk, got {len(svgs)}"
    expected = {f"avatar_{i:02d}.svg" for i in range(120)}
    actual = {p.name for p in svgs}
    assert actual == expected, f"missing or extra avatar files: {actual ^ expected}"
