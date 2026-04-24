"""Tests for the URL-inventory liveness pre-flight in ops/scripts/eval_loop.py."""
from __future__ import annotations

import os

import pytest

from ops.scripts.eval_loop import _filter_live_urls
from website.features.summarization_engine.summarization.newsletter.liveness import (
    is_live_newsletter,
)


# ---------- _filter_live_urls direct tests ----------

def test_filter_all_live_returns_all_in_live_bucket(monkeypatch):
    monkeypatch.delenv("EVAL_SKIP_LIVENESS", raising=False)
    urls = [
        "https://example.substack.com/p/post-a",
        "https://example.substack.com/p/post-b",
        "https://example.substack.com/p/post-c",
    ]
    probe = lambda batch: {u: (True, "ok") for u in batch}
    live, dead = _filter_live_urls(urls, probe=probe)
    assert live == urls
    assert dead == []


def test_filter_mixed_live_and_dead(monkeypatch):
    monkeypatch.delenv("EVAL_SKIP_LIVENESS", raising=False)
    urls = [
        "https://example.com/alive-1",
        "https://example.com/dead",
        "https://example.com/alive-2",
    ]
    verdicts = {
        "https://example.com/alive-1": (True, "ok"),
        "https://example.com/dead": (False, "dead"),
        "https://example.com/alive-2": (True, "ok"),
    }
    probe = lambda batch: verdicts
    live, dead = _filter_live_urls(urls, probe=probe)
    assert live == [
        "https://example.com/alive-1",
        "https://example.com/alive-2",
    ]
    assert dead == ["https://example.com/dead"]


def test_filter_skip_liveness_env_bypasses_probe(monkeypatch):
    monkeypatch.setenv("EVAL_SKIP_LIVENESS", "1")
    called = {"n": 0}

    def probe(batch):
        called["n"] += 1
        return {u: (False, "dead") for u in batch}

    urls = ["https://example.com/x", "https://example.com/y"]
    live, dead = _filter_live_urls(urls, probe=probe)
    assert live == urls
    assert dead == []
    assert called["n"] == 0  # probe was NOT invoked


def test_filter_raises_on_non_list():
    with pytest.raises(TypeError, match="urls must be list"):
        _filter_live_urls("not a list")  # type: ignore[arg-type]


def test_filter_raises_when_probe_omits_verdict(monkeypatch):
    monkeypatch.delenv("EVAL_SKIP_LIVENESS", raising=False)
    urls = ["https://example.com/a", "https://example.com/b"]
    probe = lambda batch: {urls[0]: (True, "ok")}  # missing url[1]
    with pytest.raises(RuntimeError, match="probe returned no verdict"):
        _filter_live_urls(urls, probe=probe)


def test_filter_empty_urls(monkeypatch):
    monkeypatch.delenv("EVAL_SKIP_LIVENESS", raising=False)
    live, dead = _filter_live_urls([], probe=lambda b: {})
    assert live == []
    assert dead == []


# ---------- Source-specific dead-marker recognition ----------
# These exercise the extended marker list in newsletter/liveness.py via the
# default probe path. No real HTTP — we hand-craft mock HTML strings.

def test_youtube_video_unavailable_html_is_dead():
    html = (
        "<html><head><title>YouTube</title></head>"
        "<body><div>Video unavailable</div></body></html>"
    )
    alive, _ = is_live_newsletter("https://www.youtube.com/watch?v=abc123", html)
    assert alive is False


def test_youtube_normal_video_html_is_alive():
    html = (
        "<html><head><title>How transformers work — YouTube</title></head>"
        "<body><div>Real video page content</div></body></html>"
    )
    alive, _ = is_live_newsletter("https://www.youtube.com/watch?v=abc123", html)
    assert alive is True


def test_github_404_page_html_is_dead():
    html = (
        "<html><head><title>Page not found · GitHub</title></head>"
        "<body><h1>404 - page not found</h1></body></html>"
    )
    alive, _ = is_live_newsletter("https://github.com/foo/bar", html)
    assert alive is False


def test_github_repo_page_html_is_alive():
    html = (
        "<html><head><title>foo/bar — GitHub</title></head>"
        "<body><div>README contents</div></body></html>"
    )
    alive, _ = is_live_newsletter("https://github.com/foo/bar", html)
    assert alive is True


def test_reddit_deleted_post_html_is_dead():
    html = (
        "<html><body><div class='post'><p>[deleted]</p></div></body></html>"
    )
    alive, _ = is_live_newsletter(
        "https://www.reddit.com/r/python/comments/abc/title/", html
    )
    assert alive is False


def test_reddit_removed_post_html_is_dead():
    html = (
        "<html><body><div class='post'><p>[removed]</p></div></body></html>"
    )
    alive, _ = is_live_newsletter(
        "https://www.reddit.com/r/python/comments/abc/title/", html
    )
    assert alive is False


def test_reddit_normal_thread_html_is_alive():
    html = (
        "<html><body><div class='post'><p>This is a normal thread body</p>"
        "</div></body></html>"
    )
    alive, _ = is_live_newsletter(
        "https://www.reddit.com/r/python/comments/abc/title/", html
    )
    assert alive is True


def test_newsletter_404_html_is_dead():
    html = "<h1>404 Not Found</h1>"
    alive, _ = is_live_newsletter("https://example.substack.com/p/x", html)
    assert alive is False


# ---------- Ensure bypass env doesn't leak across tests ----------

def test_skip_liveness_env_isolated(monkeypatch):
    """Sanity: after monkeypatch removes the env var, normal probe runs."""
    monkeypatch.delenv("EVAL_SKIP_LIVENESS", raising=False)
    assert os.environ.get("EVAL_SKIP_LIVENESS") is None
    probe = lambda batch: {u: (False, "dead") for u in batch}
    live, dead = _filter_live_urls(["https://example.com/x"], probe=probe)
    assert live == []
    assert dead == ["https://example.com/x"]
