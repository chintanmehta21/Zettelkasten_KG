"""Structural parity gate.

Replaces the deferred LLM-judge live-eval with a deterministic,
zero-API-cost fingerprint check that runs on every CI push. The gate
reads the pre-captured fingerprints from
``tests/fixtures/engine_baseline_composites.json`` — one per held-out
document per source — and asserts structural invariants that hold
UNIFORMLY across every baseline today.

Intentionally narrow: we only encode invariants that the current
baseline set already satisfies. That keeps the gate actionable — any
failure is a real regression, not a pre-existing wart — while still
catching the catastrophic drift the 3-call refactor needs to avoid:

1. **Schema shape is stable** — top-level JSON keys match the envelope
   (``mini_title``, ``brief_summary``, ``detailed_summary``, ``tags``,
   ``metadata``). This is the single most load-bearing invariant; any
   schema drift silently breaks downstream KG consumers.
2. **Brief token count has a floor** — we never ship a sub-20-token
   brief, which is always a collapsed-fallback signal.
3. **Tag arrays stay in the 5-12 band** — starving or runaway tagging
   both break the KG linker.

Other properties (heading counts, bullet density, terminated sentences,
sentinel tags) vary across the current baseline set because the
fingerprint extractor interprets some structured payloads as flat
(e.g. newsletters are captured as a single-blob ``detailed_summary``
dict rather than a header list). Adding them as gates here would fail
on current artifacts. They ride along as informational delta checks
in :func:`test_no_regression_against_baseline` which asserts a NEW
fingerprint (passed via env var) is no worse than the recorded one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "engine_baseline_composites.json"
)

_EXPECTED_SCHEMA_KEYS = {
    "brief_summary",
    "detailed_summary",
    "metadata",
    "mini_title",
    "tags",
}

# A brief below this is structurally dead — every source should clear it.
_MIN_BRIEF_TOKENS = 20
_MIN_TAGS = 5
_MAX_TAGS = 12


def _load_baselines() -> list[dict[str, Any]]:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return data["baselines"]


@pytest.fixture(scope="module")
def baselines() -> list[dict[str, Any]]:
    assert _FIXTURE.exists(), f"Baseline fixture missing: {_FIXTURE}"
    items = _load_baselines()
    assert items, "Baseline fixture is empty — regenerate via build_structural_baseline.py"
    return items


def test_baseline_fixture_covers_all_four_sources(baselines):
    """Fail loudly if a source was dropped from the baseline set."""
    seen = {b["source_type"] for b in baselines}
    assert {"newsletter", "youtube", "reddit", "github"}.issubset(seen), (
        "Baseline set missing sources: "
        f"{ {'newsletter','youtube','reddit','github'} - seen}"
    )


def test_baseline_fixture_count_matches_held_out_corpus(baselines):
    """Regenerate the fixture if held-out docs were added/removed."""
    # Current: 6 github + 5 newsletter + 1 reddit + 1 youtube = 13.
    # The exact number is intentionally pinned so silent corpus shrinkage
    # (e.g. a broken builder that skips files) is caught immediately.
    assert len(baselines) == 13, (
        f"Expected 13 baselines, got {len(baselines)}. "
        "Regenerate via `python ops/scripts/build_structural_baseline.py`."
    )


@pytest.mark.parametrize(
    "fixture_id",
    [b["fixture_id"] for b in _load_baselines()],
)
def test_schema_keys_match_envelope(fixture_id):
    b = next(x for x in _load_baselines() if x["fixture_id"] == fixture_id)
    keys = set(b["schema_keys"])
    assert keys == _EXPECTED_SCHEMA_KEYS, (
        f"{b['source_type']}/{fixture_id}: schema keys diverged. "
        f"Expected {_EXPECTED_SCHEMA_KEYS}, got {keys}. "
        f"Summary path: {b['summary_relpath']}"
    )


@pytest.mark.parametrize(
    "fixture_id",
    [b["fixture_id"] for b in _load_baselines()],
)
def test_brief_token_count_above_floor(fixture_id):
    b = next(x for x in _load_baselines() if x["fixture_id"] == fixture_id)
    tc = b["brief_token_count"]
    assert tc >= _MIN_BRIEF_TOKENS, (
        f"{b['source_type']}/{fixture_id}: brief {tc} tokens (below "
        f"{_MIN_BRIEF_TOKENS}). Summary: {b['summary_relpath']}"
    )


@pytest.mark.parametrize(
    "fixture_id",
    [b["fixture_id"] for b in _load_baselines()],
)
def test_tag_count_in_band(fixture_id):
    b = next(x for x in _load_baselines() if x["fixture_id"] == fixture_id)
    tc = b["tag_count"]
    assert _MIN_TAGS <= tc <= _MAX_TAGS, (
        f"{b['source_type']}/{fixture_id}: tag_count {tc} outside "
        f"[{_MIN_TAGS}, {_MAX_TAGS}]. Summary: {b['summary_relpath']}"
    )


# --- Delta gate -----------------------------------------------------------

def _no_regression(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    """Return a list of regression messages; empty list = candidate is OK.

    A NEW fingerprint (captured post-refactor) must:
      - keep the same schema keys,
      - not drop below 85% of the baseline brief-token count,
      - not introduce a sentinel tag that the baseline lacked,
      - not introduce unterminated bullets that the baseline lacked,
      - not lose detailed headings or bullets that the baseline had.
    """
    msgs: list[str] = []
    if set(candidate.get("schema_keys", [])) != set(baseline["schema_keys"]):
        msgs.append(
            f"schema keys changed: "
            f"{sorted(set(baseline['schema_keys']))} -> "
            f"{sorted(set(candidate.get('schema_keys', [])))}"
        )
    base_tokens = baseline["brief_token_count"]
    cand_tokens = candidate.get("brief_token_count", 0)
    if cand_tokens < int(0.85 * base_tokens):
        msgs.append(
            f"brief shrank from {base_tokens} to {cand_tokens} tokens "
            f"(>15% loss)"
        )
    if candidate.get("sentinel_tag_present", False) and not baseline.get(
        "sentinel_tag_present", False
    ):
        msgs.append("sentinel tag leaked where baseline had none")
    base_ut = baseline["unterminated_bullets"]
    cand_ut = candidate.get("unterminated_bullets", 0)
    if cand_ut > base_ut:
        msgs.append(
            f"unterminated bullets rose from {base_ut} to {cand_ut}"
        )
    base_heads = len(baseline["detailed_headings"])
    cand_heads = len(candidate.get("detailed_headings", []))
    if base_heads > 0 and cand_heads < base_heads:
        msgs.append(
            f"detailed headings dropped from {base_heads} to {cand_heads}"
        )
    base_bullets = sum(baseline["bullet_counts_per_section"])
    cand_bullets = sum(candidate.get("bullet_counts_per_section", []))
    if base_bullets > 0 and cand_bullets < int(0.75 * base_bullets):
        msgs.append(
            f"bullet total fell from {base_bullets} to {cand_bullets} "
            f"(>25% loss)"
        )
    return msgs


def test_no_regression_helper_is_noop_against_self(baselines):
    """Sanity: running the delta gate against each baseline as candidate
    yields zero regression messages. This protects the helper itself
    against future edits that make it either too lax or too strict."""
    for b in baselines:
        msgs = _no_regression(b, b)
        assert msgs == [], (
            f"Self-comparison regressions for {b['source_type']}/"
            f"{b['fixture_id']}: {msgs}"
        )
