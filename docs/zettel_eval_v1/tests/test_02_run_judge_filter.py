"""Tests for 02_run_judge.py --wz-filter behavior.

Added 2026-05-28 in response to iter-001-baseline post-mortem: needed to scope
a hot-fix re-run to one zettel (wz=1c0af8ec) without re-evaluating the whole
manifest. --wz-filter <prefix> implements that; this test pins its behavior
so future refactors don't silently regress the cost-control path.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Dynamic import: 02_run_judge.py is not a Python-importable name. Load the
# module by file path and pull out `_filter_zettels` for direct testing.
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "02_run_judge.py"


def _load_module():
    sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("zettel_eval_v1_02_run_judge", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _z(wz: str) -> dict:
    return {"workspace_zettel_id": wz, "source_type": "youtube",
            "canonical_zettel_id": "c-" + wz}


def test_filter_zettels_no_filter_returns_all():
    mod = _load_module()
    zettels = [_z("1c0af8ec-aaa"), _z("628789b4-bbb"), _z("881865c9-ccc")]
    out = mod._filter_zettels(zettels, wz_filter=None, max_zettels=None)
    assert len(out) == 3


def test_filter_zettels_wz_prefix_match_single():
    """Regression: re-running just wz=1c0af8ec must yield exactly that one zettel."""
    mod = _load_module()
    zettels = [_z("1c0af8ec-aaa"), _z("628789b4-bbb"), _z("881865c9-ccc")]
    out = mod._filter_zettels(zettels, wz_filter="1c0af8ec", max_zettels=None)
    assert len(out) == 1
    assert out[0]["workspace_zettel_id"] == "1c0af8ec-aaa"


def test_filter_zettels_wz_prefix_short():
    """Partial prefixes like '1c' should still work, matching any zettel that starts with it."""
    mod = _load_module()
    zettels = [_z("1c0af8ec-aaa"), _z("1c777777-zzz"), _z("881865c9-ccc")]
    out = mod._filter_zettels(zettels, wz_filter="1c", max_zettels=None)
    assert {z["workspace_zettel_id"] for z in out} == {"1c0af8ec-aaa", "1c777777-zzz"}


def test_filter_zettels_no_match_raises():
    """Operator typo on a manual re-run must fail loud, not silently no-op."""
    mod = _load_module()
    zettels = [_z("1c0af8ec-aaa")]
    with pytest.raises(SystemExit) as excinfo:
        mod._filter_zettels(zettels, wz_filter="DEADBEEF", max_zettels=None)
    assert "matched zero zettels" in str(excinfo.value)


def test_filter_zettels_max_then_filter_order():
    """--wz-filter applies BEFORE --max-zettels (so filter narrows then cap applies)."""
    mod = _load_module()
    zettels = [_z(f"1c0af8ec-{i:03d}") for i in range(5)] + [_z("881865c9-zzz")]
    out = mod._filter_zettels(zettels, wz_filter="1c0af8ec", max_zettels=2)
    assert len(out) == 2
    assert all(z["workspace_zettel_id"].startswith("1c0af8ec") for z in out)


if __name__ == "__main__":
    test_filter_zettels_no_filter_returns_all()
    print("PASS test_filter_zettels_no_filter_returns_all")
    test_filter_zettels_wz_prefix_match_single()
    print("PASS test_filter_zettels_wz_prefix_match_single")
    test_filter_zettels_wz_prefix_short()
    print("PASS test_filter_zettels_wz_prefix_short")
    test_filter_zettels_no_match_raises()
    print("PASS test_filter_zettels_no_match_raises")
    test_filter_zettels_max_then_filter_order()
    print("PASS test_filter_zettels_max_then_filter_order")
    print("ALL 5 TESTS PASS")
