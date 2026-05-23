"""LD-8 / O3: embeddings must distinguish ok / rate_limit / rpc_error / empty.

The typed `generate_embedding_typed` wrapper returns an `EmbeddingResult`
dataclass with a `retryable` flag so the kg-populate state machine (LD-8)
can pick the right pipeline_runs terminal state.
"""
from __future__ import annotations

from unittest.mock import patch

from website.features.kg_features.embeddings import (
    EmbeddingFailureReason,
    EmbeddingResult,
    generate_embedding_typed,
)


def test_result_ok_carries_vector():
    r = EmbeddingResult(ok=True, vectors=[[0.1] * 768], reason=None, retryable=False)
    assert r.ok and len(r.vectors[0]) == 768


def test_result_rate_limit_is_retryable():
    r = EmbeddingResult(
        ok=False,
        vectors=[],
        reason=EmbeddingFailureReason.RATE_LIMIT,
        retryable=True,
    )
    assert not r.ok and r.retryable


def test_generate_embedding_typed_empty_input_returns_empty_not_failure():
    r = generate_embedding_typed("")
    assert r.ok is False
    assert r.reason == EmbeddingFailureReason.EMPTY_INPUT
    assert r.retryable is False  # empty input is terminal, never retried


def test_generate_embedding_typed_whitespace_only_treated_as_empty():
    r = generate_embedding_typed("   \t\n  ")
    assert r.ok is False
    assert r.reason == EmbeddingFailureReason.EMPTY_INPUT
    assert r.retryable is False


def test_generate_embedding_typed_pool_exhausted_returns_retryable_rate_limit():
    with patch("website.features.kg_features.embeddings.get_key_pool") as gp:
        gp.return_value.embed_content_safe.return_value = None
        r = generate_embedding_typed("hello")
    assert r.ok is False
    assert r.reason == EmbeddingFailureReason.RATE_LIMIT
    assert r.retryable is True


def test_generate_embedding_typed_429_classified_as_rate_limit():
    with patch("website.features.kg_features.embeddings.get_key_pool") as gp:
        gp.return_value.embed_content_safe.side_effect = RuntimeError("429 rate limit exceeded")
        r = generate_embedding_typed("hello")
    assert r.reason == EmbeddingFailureReason.RATE_LIMIT
    assert r.retryable is True


def test_generate_embedding_typed_unknown_exception_is_network_retryable():
    with patch("website.features.kg_features.embeddings.get_key_pool") as gp:
        gp.return_value.embed_content_safe.side_effect = RuntimeError("connection reset")
        r = generate_embedding_typed("hello")
    assert r.reason == EmbeddingFailureReason.NETWORK
    assert r.retryable is True
