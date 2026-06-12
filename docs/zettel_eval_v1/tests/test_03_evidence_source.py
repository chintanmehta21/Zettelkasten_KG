"""03_run_nli.py uses the TRUE source (source_evidence.json) as the NLI premise,
falling back to source_text.md for pre-Sol-1 bundles. NLI already chunks + max-pools
long premises (_chunk_premise), so no NLI-logic change — only the premise bytes."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "03_run_nli.py"


def _mod():
    sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("zettel_eval_v1_03_nli_ev", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_nli_prefers_source_evidence(tmp_path):
    m = _mod()
    d = tmp_path / "wz"
    d.mkdir()
    (d / "source_text.md").write_text("SUMMARY-DERIVED BODY", encoding="utf-8")
    (d / "source_evidence.json").write_text(json.dumps({
        "evidence_source": "production_ingest_cache", "raw_text": "TRUE RAW PREMISE",
    }), encoding="utf-8")
    assert m.read_nli_source(d) == "TRUE RAW PREMISE"


def test_nli_falls_back_to_source_text(tmp_path):
    m = _mod()
    d = tmp_path / "wz"
    d.mkdir()
    (d / "source_text.md").write_text("LEGACY PREMISE", encoding="utf-8")
    assert m.read_nli_source(d) == "LEGACY PREMISE"


def test_nli_missing_both_returns_empty(tmp_path):
    m = _mod()
    d = tmp_path / "wz"
    d.mkdir()
    assert m.read_nli_source(d) == ""
