"""Tests for DuplicateStore — JSON-backed duplicate URL detection.

Covers:
 - Happy path: mark and detect duplicates
 - Missing file: graceful empty store
 - Corrupt file: graceful empty store (no crash)
 - Data directory auto-creation
 - Normalization: URLs that normalize to the same value are treated as duplicates
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from telegram_bot.pipeline.duplicate import DuplicateStore


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> DuplicateStore:
    """DuplicateStore backed by a fresh temporary directory."""
    return DuplicateStore(tmp_path)


# ── Happy-path tests ──────────────────────────────────────────────────────────


def test_mark_seen_and_is_duplicate(store: DuplicateStore) -> None:
    """A URL marked as seen should be detected as a duplicate on next check."""
    url = "https://example.com/article"
    assert not store.is_duplicate(url)
    store.mark_seen(url)
    assert store.is_duplicate(url)


def test_not_duplicate_for_new_url(store: DuplicateStore) -> None:
    """A URL that was never marked seen must not appear as a duplicate."""
    assert not store.is_duplicate("https://example.com/new-article")


def test_mark_seen_persists_across_instances(tmp_path: Path) -> None:
    """Data written by one store instance should be visible to a new instance
    opened from the same directory."""
    url = "https://example.com/persistent"
    s1 = DuplicateStore(tmp_path)
    s1.mark_seen(url)

    s2 = DuplicateStore(tmp_path)
    assert s2.is_duplicate(url)


# ── Missing / corrupt file tests ──────────────────────────────────────────────


def test_load_missing_file(tmp_path: Path) -> None:
    """DuplicateStore initialised when no JSON file exists should start empty."""
    store = DuplicateStore(tmp_path, filename="nonexistent.json")
    assert not store.is_duplicate("https://example.com/any")
    # No exception raised — the store is empty
    assert store._seen == set()


def test_load_corrupt_file(tmp_path: Path) -> None:
    """Corrupt JSON in the store file should result in an empty store, not a
    crash."""
    bad_file = tmp_path / "seen_urls.json"
    bad_file.write_text("this is not valid json {{{{", encoding="utf-8")

    store = DuplicateStore(tmp_path)
    assert store._seen == set()
    assert not store.is_duplicate("https://example.com/any")


def test_load_non_list_json(tmp_path: Path) -> None:
    """JSON that is valid but not a list (e.g. a dict) should be treated as
    corrupt → empty store."""
    bad_file = tmp_path / "seen_urls.json"
    bad_file.write_text(json.dumps({"url": "https://example.com"}), encoding="utf-8")

    store = DuplicateStore(tmp_path)
    assert store._seen == set()


# ── Directory auto-creation test ──────────────────────────────────────────────


def test_data_dir_created_automatically(tmp_path: Path) -> None:
    """DuplicateStore must create the data directory if it does not exist."""
    nested = tmp_path / "deep" / "nested" / "dir"
    assert not nested.exists()

    store = DuplicateStore(nested)
    assert nested.exists()

    # Should also be able to mark and detect without error
    store.mark_seen("https://example.com/auto-dir")
    assert store.is_duplicate("https://example.com/auto-dir")


# ── Normalization tests ───────────────────────────────────────────────────────


def test_normalization_before_check(tmp_path: Path) -> None:
    """URLs that normalize to the same value should be detected as duplicates
    even when they differ only by tracking parameters or fragment."""
    store = DuplicateStore(tmp_path)

    canonical = "https://example.com/article"
    with_tracking = "https://example.com/article?utm_source=newsletter&utm_medium=email"
    with_fragment = "https://example.com/article#section-2"

    store.mark_seen(canonical)

    # Variant with tracking params should match the canonical form
    assert store.is_duplicate(with_tracking)
    # Variant with fragment should also match (fragment is stripped during normalization)
    assert store.is_duplicate(with_fragment)


def test_different_urls_not_duplicates(tmp_path: Path) -> None:
    """Two genuinely different URLs must not collide after normalization."""
    store = DuplicateStore(tmp_path)
    store.mark_seen("https://example.com/article-one")
    assert not store.is_duplicate("https://example.com/article-two")


# ── Force-flag boundary condition (via orchestrator) ──────────────────────────


def test_mark_seen_idempotent(store: DuplicateStore) -> None:
    """Marking the same URL multiple times should not raise and should keep it
    in the set exactly once."""
    url = "https://example.com/idempotent"
    store.mark_seen(url)
    store.mark_seen(url)  # second call must not crash

    normalized = "https://example.com/idempotent"
    assert store._seen == {normalized}
