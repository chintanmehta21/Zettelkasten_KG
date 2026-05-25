"""Tests for the avatar URL validation regex."""

from __future__ import annotations


def test_valid_indices_pass():
    from website.features.user_profile.models import is_valid_avatar_url

    for n in (0, 1, 7, 22, 58, 59):
        url = f"/artifacts/avatars/avatar_{n:02d}.svg"
        assert is_valid_avatar_url(url), f"expected pass for {url}"


def test_out_of_range_fails():
    from website.features.user_profile.models import is_valid_avatar_url

    assert not is_valid_avatar_url("/artifacts/avatars/avatar_60.svg")
    assert not is_valid_avatar_url("/artifacts/avatars/avatar_99.svg")


def test_path_traversal_rejected():
    from website.features.user_profile.models import is_valid_avatar_url

    assert not is_valid_avatar_url("/artifacts/avatars/../../etc/passwd")
    assert not is_valid_avatar_url("/artifacts/avatars/avatar_00.svg/../bad")


def test_external_url_rejected():
    from website.features.user_profile.models import is_valid_avatar_url

    assert not is_valid_avatar_url("https://lh3.googleusercontent.com/x/y.jpg")
    assert not is_valid_avatar_url("//evil.example.com/avatar.svg")


def test_wrong_extension_rejected():
    from website.features.user_profile.models import is_valid_avatar_url

    assert not is_valid_avatar_url("/artifacts/avatars/avatar_07.png")
    assert not is_valid_avatar_url("/artifacts/avatars/avatar_07.svg.exe")


def test_empty_and_none_rejected():
    from website.features.user_profile.models import is_valid_avatar_url

    assert not is_valid_avatar_url("")
    assert not is_valid_avatar_url(None)
