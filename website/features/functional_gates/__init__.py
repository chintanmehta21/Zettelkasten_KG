"""Functional gates for Zettel, Kasten, and Question quota enforcement.

Public surface:
- :class:`FunctionalGates` (use :func:`get_functional_gates`).
- :class:`GateDecision` / :class:`QuotaSnapshot` (typed results).
- :class:`GateError` (raise to signal a 402 quota_exhausted).
- :mod:`config` (operator-editable plan caps + wallet meter map).
"""
from __future__ import annotations

from website.features.functional_gates.gates import (
    FunctionalGates,
    GateDecision,
    GateError,
    QuotaSnapshot,
    get_functional_gates,
    reset_for_tests,
)

__all__ = [
    "FunctionalGates",
    "GateDecision",
    "GateError",
    "QuotaSnapshot",
    "get_functional_gates",
    "reset_for_tests",
]
