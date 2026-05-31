"""Functional gates for Zettel, Kasten, and Question quota enforcement.

Public surface:
- :class:`FunctionalGates` (use :func:`get_functional_gates`).
- :class:`GateDecision` / :class:`QuotaSnapshot` (typed results).
- :class:`GateError` (raise to signal a 402 quota_exhausted).
- :class:`UrlDedupGate` (use :func:`get_url_dedup_gate`) + :class:`DedupDecision`.
- :mod:`config` (operator-editable plan caps + wallet meter map).
- :func:`if_none_match` (RFC 7232 weak ETag comparison for 304 short-circuits).
"""
from __future__ import annotations

from website.features.functional_gates.dedup_gate import (
    DedupDecision,
    UrlDedupGate,
    _reset_url_dedup_gate_for_tests,
    get_url_dedup_gate,
)
from website.features.functional_gates.gates import (
    FunctionalGates,
    GateDecision,
    GateError,
    QuotaSnapshot,
    get_functional_gates,
    reset_for_tests as _reset_gates,
)
from website.features.functional_gates.etag import if_none_match


def reset_for_tests() -> None:
    """Drop ALL functional_gates singletons (quota gate + url-dedup gate).
    Tests only — keeps a single reset entry point for the whole package."""
    _reset_gates()
    _reset_url_dedup_gate_for_tests()


__all__ = [
    "FunctionalGates",
    "GateDecision",
    "GateError",
    "QuotaSnapshot",
    "DedupDecision",
    "UrlDedupGate",
    "get_functional_gates",
    "get_url_dedup_gate",
    "if_none_match",
    "reset_for_tests",
]
