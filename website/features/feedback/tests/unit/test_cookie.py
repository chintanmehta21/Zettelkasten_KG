"""Tests for the signed HMAC cookie issuer + validator."""
from __future__ import annotations

import pytest

from website.features.feedback.api.cookie import (
    issue_cookie_value,
    validate_cookie_value,
    COOKIE_NAME,
)


SECRET = b"unit-test-secret-32-bytes-long-aaaa"


def test_cookie_name_is_stable() -> None:
    assert COOKIE_NAME == "zk_feedback_token"


def test_issue_cookie_value_format() -> None:
    val = issue_cookie_value(SECRET)
    # Format: <base64url-uuid>.<hex-hmac>
    assert "." in val
    body, mac = val.split(".", 1)
    assert len(body) >= 16
    assert len(mac) == 64  # sha256 hex = 64 chars


def test_validate_cookie_value_accepts_self_issued() -> None:
    val = issue_cookie_value(SECRET)
    assert validate_cookie_value(val, SECRET) is True


def test_validate_cookie_value_rejects_tampered_body() -> None:
    val = issue_cookie_value(SECRET)
    body, mac = val.split(".", 1)
    tampered = "AAAAAAAAAAAA." + mac
    assert validate_cookie_value(tampered, SECRET) is False


def test_validate_cookie_value_rejects_tampered_mac() -> None:
    val = issue_cookie_value(SECRET)
    body, mac = val.split(".", 1)
    tampered = body + ".0" * 64
    assert validate_cookie_value(tampered, SECRET) is False


def test_validate_cookie_value_rejects_wrong_secret() -> None:
    val = issue_cookie_value(SECRET)
    assert validate_cookie_value(val, b"different-secret") is False


@pytest.mark.parametrize("bad", ["", "no-dot", ".", "abc.", ".xyz", "a.b.c"])
def test_validate_cookie_value_rejects_malformed(bad: str) -> None:
    assert validate_cookie_value(bad, SECRET) is False
