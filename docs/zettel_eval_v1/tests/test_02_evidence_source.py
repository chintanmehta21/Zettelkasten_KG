"""02_run_judge.py reads the TRUE source (source_evidence.json) for faithfulness,
falling back to source_text.md for bundles frozen before Sol 1. Data-source only —
no judge-logic change. Importing 02_run_judge.py is side-effect-free (only path
constants + defs at module level; verified 2026-06-12), so exec_module is safe."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "02_run_judge.py"


def _mod():
    sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("zettel_eval_v1_02_judge_ev", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_prefers_source_evidence(tmp_path):
    m = _mod()
    d = tmp_path / "wz"
    d.mkdir()
    (d / "source_text.md").write_text("SUMMARY-DERIVED BODY", encoding="utf-8")
    (d / "source_evidence.json").write_text(json.dumps({
        "evidence_source": "production_ingest_cache", "raw_text": "TRUE RAW SOURCE",
    }), encoding="utf-8")
    assert m.read_faithfulness_source(d) == "TRUE RAW SOURCE"


def test_falls_back_to_source_text_when_evidence_absent(tmp_path):
    m = _mod()
    d = tmp_path / "wz"
    d.mkdir()
    (d / "source_text.md").write_text("LEGACY BODY MD", encoding="utf-8")
    assert m.read_faithfulness_source(d) == "LEGACY BODY MD"


def test_falls_back_when_evidence_raw_text_empty(tmp_path):
    m = _mod()
    d = tmp_path / "wz"
    d.mkdir()
    (d / "source_text.md").write_text("LEGACY BODY MD", encoding="utf-8")
    (d / "source_evidence.json").write_text(json.dumps({
        "evidence_source": "body_md_fallback", "raw_text": ""}), encoding="utf-8")
    assert m.read_faithfulness_source(d) == "LEGACY BODY MD"
