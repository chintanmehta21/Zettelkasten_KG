"""iter-08 G7: cite-hygiene canary diff logic."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "canary_cite_hygiene",
    Path(__file__).resolve().parents[3] / "ops" / "scripts" / "canary_cite_hygiene.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps({"results": rows}), encoding="utf-8")


def test_diff_target_qids_returns_0_on_no_regression(tmp_path):
    off = tmp_path / "off.json"
    on = tmp_path / "on.json"
    _write(off, [
        {"qid": "q1", "gold_at_1": 0.8, "verdict": "pass"},
        {"qid": "q4", "gold_at_1": 0.6, "verdict": "pass"},
        {"qid": "q11", "gold_at_1": 0.5, "verdict": "pass"},
    ])
    _write(on, [
        {"qid": "q1", "gold_at_1": 0.85, "verdict": "pass"},
        {"qid": "q4", "gold_at_1": 0.65, "verdict": "pass"},
        {"qid": "q11", "gold_at_1": 0.55, "verdict": "pass"},
    ])
    assert _mod.diff_target_qids(off, on) == 0


def test_diff_target_qids_returns_1_on_regression(tmp_path):
    off = tmp_path / "off.json"
    on = tmp_path / "on.json"
    _write(off, [
        {"qid": "q1", "gold_at_1": 0.8, "verdict": "pass"},
        {"qid": "q4", "gold_at_1": 0.6, "verdict": "pass"},
        {"qid": "q11", "gold_at_1": 0.5, "verdict": "pass"},
    ])
    _write(on, [
        {"qid": "q1", "gold_at_1": 0.0, "verdict": "fail"},
        {"qid": "q4", "gold_at_1": 0.65, "verdict": "pass"},
        {"qid": "q11", "gold_at_1": 0.55, "verdict": "pass"},
    ])
    assert _mod.diff_target_qids(off, on) == 1


def test_diff_target_qids_handles_missing_qid(tmp_path):
    """Missing qid in either side yields 0.0 / '?' verdict; no flip flag."""
    off = tmp_path / "off.json"
    on = tmp_path / "on.json"
    _write(off, [{"qid": "q1", "gold_at_1": 0.8, "verdict": "pass"}])
    _write(on, [{"qid": "q1", "gold_at_1": 0.8, "verdict": "pass"}])
    # q4 and q11 absent on both sides — no regression flag.
    assert _mod.diff_target_qids(off, on) == 0
