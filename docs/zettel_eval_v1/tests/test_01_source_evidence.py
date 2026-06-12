"""Tests for 01_freeze_manifest.py true-source evidence (Sol 1 / D2).

Pins the cache-first source_evidence.json behavior:
  - URL normalization matches the proven _d2_cache_check.norm() (PR _llm_silver).
  - A cache hit yields raw_text + evidence_source=production_ingest_cache.
  - A cache miss falls back to body_md + evidence_source=body_md_fallback
    (so circular items stay EXCLUDABLE, never silently scored — D2).
  - raw_text is capped to bound git size (one 513KB transcript exists in prod).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "01_freeze_manifest.py"


def _mod():
    sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("zettel_eval_v1_01_freeze", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_norm_url_matches_d2_check():
    m = _mod()
    # scheme + www + trailing slash + case all collapse (see _d2_cache_check.norm)
    assert m._norm_url("https://www.YouTube.com/watch?v=abc/") == "youtube.com/watch?v=abc"
    assert m._norm_url("http://Example.com/Foo/") == "example.com/foo"
    assert m._norm_url("") == ""
    assert m._norm_url(None) == ""


def test_cache_index_keys_on_normalized_url(tmp_path):
    m = _mod()
    cache_dir = tmp_path / "ingests"
    cache_dir.mkdir()
    (cache_dir / "a.json").write_text(json.dumps({
        "url": "https://www.youtube.com/watch?v=HIT", "source_type": "youtube",
        "raw_text": "TRANSCRIPT BODY", "ingestor_version": "2.0.0",
    }), encoding="utf-8")
    # a fixture file with no usable raw_text must be ignored
    (cache_dir / "b.json").write_text(json.dumps({
        "url": "https://x/empty", "source_type": "web", "raw_text": "",
    }), encoding="utf-8")
    idx = m._load_ingest_cache_index(cache_dir)
    assert idx[m._norm_url("https://youtube.com/watch?v=HIT")]["raw_text"] == "TRANSCRIPT BODY"
    assert m._norm_url("https://x/empty") not in idx  # empty raw_text dropped


def test_cache_index_missing_dir_returns_empty(tmp_path):
    m = _mod()
    assert m._load_ingest_cache_index(tmp_path / "does_not_exist") == {}
