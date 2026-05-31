"""Tests for 02_run_judge.py::_write_per_zettel multi-judge filename behavior.

Added 2026-05-31 after the iter-004 jury data-loss bug: when judges=[primary,
secondary] both wrote to <wz>.json, the second judge overwrote the first
(last-writer-wins) and the jury collapsed to a single judge in the per_zettel
output that 04 reads. The fix: multi-judge iters suffix the filename with the
judge_kind so both survive; single-judge iters keep the bare <wz>.json layout.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "02_run_judge.py"


def _load_module():
    sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("zettel_eval_v1_02_write_pz", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _payload(kind: str) -> dict:
    return {"finesure": {"faithfulness": 0.9}, "_meta": {"judge_kind": kind}}


def test_single_judge_keeps_bare_filename(tmp_path):
    """multi_judge=False → bare <wz>.json (backward-compatible layout)."""
    m = _load_module()
    m._write_per_zettel(run_dir=tmp_path, source_type="web", wz_id="abc123",
                        payload=_payload("primary"), multi_judge=False)
    assert (tmp_path / "_overall" / "per_zettel" / "abc123.json").exists()
    assert (tmp_path / "web" / "per_zettel" / "abc123.json").exists()
    # no judge-suffixed file
    assert not list((tmp_path / "_overall" / "per_zettel").glob("abc123__*.json"))


def test_multi_judge_suffixes_by_kind(tmp_path):
    """multi_judge=True → <wz>__<judge_kind>.json."""
    m = _load_module()
    m._write_per_zettel(run_dir=tmp_path, source_type="web", wz_id="abc123",
                        payload=_payload("primary"), multi_judge=True)
    assert (tmp_path / "_overall" / "per_zettel" / "abc123__primary.json").exists()
    assert not (tmp_path / "_overall" / "per_zettel" / "abc123.json").exists()


def test_jury_both_judges_survive(tmp_path):
    """THE BUG FIX: writing primary then secondary for the SAME wz must leave
    BOTH files (no last-writer-wins overwrite)."""
    m = _load_module()
    for kind in ("primary", "secondary"):
        m._write_per_zettel(run_dir=tmp_path, source_type="web", wz_id="abc123",
                            payload=_payload(kind), multi_judge=True)
    pz = tmp_path / "_overall" / "per_zettel"
    assert (pz / "abc123__primary.json").exists()
    assert (pz / "abc123__secondary.json").exists()
    assert len(list(pz.glob("abc123*.json"))) == 2, "both judges must survive"


if __name__ == "__main__":
    import tempfile
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                fn(Path(d))
            print(f"PASS {name}")
    print("ALL PASS")
