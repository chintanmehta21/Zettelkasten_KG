"""X5 (T4.13): NFKC + lowercase + strip canonical form for user tags."""
from __future__ import annotations

import pytest

from website.core.text_polish import normalize_tag, normalize_tags


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Reddit", "reddit"),
        ("  Programming  ", "programming"),
        ("Café", "café"),
        # NFD form: "café" with combining acute. NFKC folds into NFC.
        ("café", "café"),
        # Full-width digits -> ASCII via NFKC.
        ("１２３", "123"),
        # Ligature: ﬁ -> fi
        ("ﬁnal", "final"),
        # Already canonical -> identity.
        ("hello world", "hello world"),
    ],
)
def test_normalize_tag_canonical_forms(raw: str, expected: str) -> None:
    assert normalize_tag(raw) == expected


def test_normalize_tag_idempotent() -> None:
    for raw in ["Café", "café", "  REDDIT  ", "１２"]:
        once = normalize_tag(raw)
        twice = normalize_tag(once)
        assert once == twice, f"not idempotent for {raw!r}: {once!r} != {twice!r}"


def test_normalize_tag_non_string_passes_through() -> None:
    assert normalize_tag(None) is None
    assert normalize_tag(42) == "42"


def test_normalize_tags_dedupes_preserving_first_seen_order() -> None:
    # "Café" + "café" both fold to "café" — second occurrence dropped.
    result = normalize_tags(["Reddit", "Café", "café", "Programming"])
    assert result == ["reddit", "café", "programming"]


def test_normalize_tags_skips_empty_and_non_strings() -> None:
    result = normalize_tags(["foo", "", "   ", None, 42, "bar"])
    assert result == ["foo", "bar"]


def test_normalize_tags_passthrough_for_non_list() -> None:
    assert normalize_tags("foo") == "foo"
    assert normalize_tags(None) is None
