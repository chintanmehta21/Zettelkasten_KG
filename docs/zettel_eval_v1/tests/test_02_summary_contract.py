"""Sol 2 / A5: deterministic summary-contract guard at the judge boundary.
NOT the LLM judge — a pure check run at summary.json load time.

  - _summary_source == "structured_payload" but tags/mini_title missing -> RAISE
    (malformed-fresh, fail-closed).
  - _summary_source MISSING (legacy 81 bundles, pre master-plan A3) -> WARN string,
    do NOT raise (D1 declined the re-freeze; a hard fail would break the judge on
    the current corpus).
  - clean structured_payload, OR ai_summary_envelope (documented fresh fallback)
    -> None.

Importing 02_run_judge.py is side-effect-free (verified 2026-06-12), so exec_module
is safe and the contract logic stays colocated with its only caller."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "02_run_judge.py"


def _mod():
    sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("zettel_eval_v1_02_contract", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_malformed_fresh_raises():
    m = _mod()
    # claims structured_payload but omits the rubric fields -> fail-closed
    with pytest.raises(ValueError) as ei:
        m.assert_summary_contract("wz-bad", {
            "brief_summary": "B", "detailed_summary": "D",
            "_summary_source": "structured_payload",  # but no tags / mini_title
        })
    assert "wz-bad" in str(ei.value)


def test_malformed_fresh_partial_raises():
    m = _mod()
    # has tags but not mini_title -> still malformed-fresh
    with pytest.raises(ValueError):
        m.assert_summary_contract("wz-partial", {
            "_summary_source": "structured_payload", "tags": ["a"],
        })


def test_legacy_missing_source_warns_not_raises():
    m = _mod()
    # the existing 81 bundles: OLD summary.json, no _summary_source key
    warn = m.assert_summary_contract("wz-legacy", {
        "brief_summary": "B", "detailed_summary": "D"})
    assert isinstance(warn, str)
    assert "wz-legacy" in warn
    assert "legacy" in warn.lower()


def test_clean_structured_payload_returns_none():
    m = _mod()
    assert m.assert_summary_contract("wz-ok", {
        "brief_summary": "B", "detailed_summary": "D",
        "_summary_source": "structured_payload",
        "tags": ["a", "b"], "mini_title": "psf/requests",
    }) is None


def test_envelope_fallback_returns_none():
    m = _mod()
    # documented fresh thin-row fallback (master-plan A3) is a clean contract state
    assert m.assert_summary_contract("wz-env", {
        "brief_summary": "B", "detailed_summary": "D",
        "_summary_source": "ai_summary_envelope",
    }) is None
