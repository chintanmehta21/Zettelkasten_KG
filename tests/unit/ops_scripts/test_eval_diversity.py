"""Unit tests for ops.scripts.lib.eval_diversity EvalItem-based assertions."""
from __future__ import annotations

import pytest

from ops.scripts.lib.eval_diversity import (
    EvalItem,
    assert_github_diversity,
    assert_reddit_diversity,
)


# ── Reddit ──────────────────────────────────────────────────────────────────


def _reddit_item(url: str, *, subreddit: str | None = None, post_type: str | None = None) -> EvalItem:
    metadata: dict = {}
    if subreddit:
        metadata["subreddit"] = subreddit
    if post_type:
        metadata["post_type"] = post_type
    return EvalItem(url=url, source="reddit", metadata=metadata)


def test_assert_reddit_diversity_pass_with_metadata():
    items = [
        _reddit_item("https://reddit.com/r/python/comments/a1/t", subreddit="python", post_type="comments"),
        _reddit_item("https://reddit.com/r/golang/comments/b2/t", subreddit="golang", post_type="comments"),
        _reddit_item("https://reddit.com/r/rust/gallery/c3",       subreddit="rust",   post_type="gallery"),
    ]
    # Must not raise: 3 subreddits, 2 thread-types
    assert_reddit_diversity(items)


def test_assert_reddit_diversity_fail_too_few_subreddits():
    items = [
        _reddit_item("https://reddit.com/r/python/comments/a1/t", subreddit="python", post_type="comments"),
        _reddit_item("https://reddit.com/r/python/comments/b2/t", subreddit="python", post_type="gallery"),
    ]
    with pytest.raises(ValueError, match="lacks diversity"):
        assert_reddit_diversity(items)


def test_assert_reddit_diversity_fail_too_few_thread_types():
    items = [
        _reddit_item("https://reddit.com/r/python/comments/a1/t", subreddit="python", post_type="comments"),
        _reddit_item("https://reddit.com/r/golang/comments/b2/t", subreddit="golang", post_type="comments"),
        _reddit_item("https://reddit.com/r/rust/comments/c3/t",   subreddit="rust",   post_type="comments"),
    ]
    with pytest.raises(ValueError, match="thread-type"):
        assert_reddit_diversity(items)


def test_assert_reddit_diversity_falls_back_to_url_parsing():
    items = [
        EvalItem(url="https://reddit.com/r/python/comments/a1/title"),
        EvalItem(url="https://reddit.com/r/golang/comments/b2/title"),
        EvalItem(url="https://reddit.com/r/rust/gallery/c3"),
    ]
    assert_reddit_diversity(items)


def test_assert_reddit_diversity_empty_input_raises():
    with pytest.raises(ValueError, match="received 0 items"):
        assert_reddit_diversity([])


# ── GitHub ──────────────────────────────────────────────────────────────────


def _gh_item(url: str, *, archetype: str | None = None) -> EvalItem:
    metadata: dict = {}
    if archetype:
        metadata["archetype"] = archetype
    return EvalItem(url=url, source="github", metadata=metadata)


def test_assert_github_diversity_pass():
    items = [
        _gh_item("https://github.com/alice/lib",      archetype="library"),
        _gh_item("https://github.com/bob/cli",        archetype="cli"),
        _gh_item("https://github.com/carol/fw",       archetype="framework"),
        _gh_item("https://github.com/dave/app",       archetype="library"),
        _gh_item("https://github.com/eve/docs",       archetype="cli"),
    ]
    # 5 repos, 3 archetypes
    assert_github_diversity(items)


def test_assert_github_diversity_fail_too_few_repos():
    items = [
        _gh_item("https://github.com/alice/lib",  archetype="library"),
        _gh_item("https://github.com/alice/lib",  archetype="library"),  # dup repo
        _gh_item("https://github.com/bob/cli",    archetype="cli"),
        _gh_item("https://github.com/carol/fw",   archetype="framework"),
    ]
    with pytest.raises(ValueError, match="repo"):
        assert_github_diversity(items)


def test_assert_github_diversity_fail_too_few_archetypes():
    items = [
        _gh_item("https://github.com/alice/lib",  archetype="library"),
        _gh_item("https://github.com/bob/cli",    archetype="library"),
        _gh_item("https://github.com/carol/fw",   archetype="library"),
        _gh_item("https://github.com/dave/app",   archetype="library"),
        _gh_item("https://github.com/eve/docs",   archetype="library"),
    ]
    with pytest.raises(ValueError, match="archetype"):
        assert_github_diversity(items)


def test_assert_github_diversity_empty_input_raises():
    with pytest.raises(ValueError, match="received 0 items"):
        assert_github_diversity([])
