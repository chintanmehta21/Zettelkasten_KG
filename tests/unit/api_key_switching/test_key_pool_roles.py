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


def test_parse_api_env_line_whitespace_tolerance():
    # Trailing whitespace, leading whitespace, multiple spaces between tokens —
    # the parser splits on any whitespace run, so all of these must yield the
    # same (key, role) tuple. The CSV path in gemini_factory.make_client()
    # relies on this when an operator pastes a value with stray spaces.
    assert parse_api_env_line("  AIzaKey5  role=billing  ") == (
        "AIzaKey5",
        "billing",
    )
    assert parse_api_env_line("AIzaKey6\trole=free") == ("AIzaKey6", "free")
    assert parse_api_env_line("AIzaKey7    role=billing") == (
        "AIzaKey7",
        "billing",
    )


def test_parse_api_env_line_explicit_role_free():
    # Backward-compat invariant: an explicit `role=free` token MUST be
    # treated identically to the implicit default. Some operators tag every
    # key for clarity rather than relying on the default.
    assert parse_api_env_line("AIzaKey8 role=free") == ("AIzaKey8", "free")
