"""Tests for identity + country resolution."""
from __future__ import annotations

from website.features.feedback.core.identity import (
    Identity,
    resolve_identity,
)


def test_authenticated_with_profile_country() -> None:
    claims = {"sub": "u-123", "email": "naruto@konoha.jp",
              "user_metadata": {"name": "Naruto Uzumaki"}}
    headers = {"cf-ipcountry": "JP"}
    id_ = resolve_identity(
        claims=claims,
        anon_name=None,
        headers=headers,
        profile_country_code="IN",
    )
    assert id_.full_name == "Naruto Uzumaki"
    assert id_.email == "naruto@konoha.jp"
    # Profile country wins over IP-derived
    assert id_.country_label == "India — IN"
    assert id_.is_anonymous is False


def test_authenticated_falls_back_to_ip_country() -> None:
    claims = {"sub": "u-123", "email": "naruto@konoha.jp",
              "user_metadata": {"name": "Naruto Uzumaki"}}
    headers = {"cf-ipcountry": "IN"}
    id_ = resolve_identity(
        claims=claims,
        anon_name=None,
        headers=headers,
        profile_country_code=None,
    )
    assert "approx" in id_.country_label.lower()
    assert "IN" in id_.country_label


def test_anonymous_with_provided_name() -> None:
    id_ = resolve_identity(
        claims=None,
        anon_name="Sasuke",
        headers={"cf-ipcountry": "JP"},
        profile_country_code=None,
    )
    assert id_.full_name == "Sasuke"
    assert id_.email is None
    assert id_.is_anonymous is True
    assert "approx" in id_.country_label.lower()


def test_anonymous_without_name_uses_default() -> None:
    id_ = resolve_identity(
        claims=None, anon_name=None, headers={}, profile_country_code=None,
    )
    assert id_.full_name == "Anonymous"
    assert id_.country_label == "Unknown"


def test_authenticated_strips_whitespace_in_name() -> None:
    claims = {"sub": "u-1", "user_metadata": {"name": "  Naruto Uzumaki  "}}
    id_ = resolve_identity(
        claims=claims, anon_name=None, headers={}, profile_country_code="IN",
    )
    assert id_.full_name == "Naruto Uzumaki"
