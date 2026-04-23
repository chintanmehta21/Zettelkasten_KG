from __future__ import annotations

import pytest

from website.features.api_key_switching.key_pool import GeminiKeyPool, parse_api_env_line


def test_parse_api_env_line_with_role():
    assert parse_api_env_line("AIzaKey1 role=free") == ("AIzaKey1", "free")
    assert parse_api_env_line("AIzaKey2  role=billing") == ("AIzaKey2", "billing")


def test_parse_api_env_line_untagged_defaults_to_free():
    assert parse_api_env_line("AIzaKey3") == ("AIzaKey3", "free")


def test_key_pool_prefers_free_before_billing():
    pool = GeminiKeyPool(
        [
            ("keyA", "free"),
            ("keyB", "billing"),
        ]
    )

    first = pool.next_attempt("gemini-2.5-pro")

    assert first.key == "keyA"
    assert first.role == "free"
    assert first.model == "gemini-2.5-pro"


def test_parse_api_env_line_rejects_unknown_role():
    with pytest.raises(ValueError, match="invalid role"):
        parse_api_env_line("AIzaKey4 role=vip")
