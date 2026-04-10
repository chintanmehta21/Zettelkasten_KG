"""Tests for typed error classes."""

from website.features.summarization_engine.core.errors import (
    EngineError,
    ExtractionError,
    RateLimitedError,
    RoutingError,
)


def test_base_engine_error_is_exception():
    err = EngineError("test")
    assert isinstance(err, Exception)
    assert str(err) == "test"


def test_routing_error_has_url():
    err = RoutingError("unknown", url="https://example.com")
    assert err.url == "https://example.com"


def test_extraction_error_carries_source_type():
    err = ExtractionError("fail", source_type="github", reason="404")
    assert err.source_type == "github"
    assert err.reason == "404"


def test_rate_limited_error_has_retry_after():
    err = RateLimitedError("rate limited", retry_after_sec=60)
    assert err.retry_after_sec == 60
