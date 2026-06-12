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


def _row(wz_id, url, body_md):
    return {
        "id": wz_id, "workspace_id": "ws-1",
        "ai_summary": json.dumps({"brief_summary": "B", "detailed_summary": "D"}),
        "created_at": "2026-01-01T00:00:00Z",
        "canonical": {
            "id": "cz-1", "normalized_url": url, "title": "T",
            "source_type": "youtube", "content_hash": "\\xab", "body_md": body_md,
            "source_metadata": {},
        },
    }


def test_bundle_cache_hit_writes_true_source(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "DATA_ROOT", tmp_path / "_data")
    cache_dir = tmp_path / "ingests"
    cache_dir.mkdir()
    (cache_dir / "hit.json").write_text(json.dumps({
        "url": "https://www.youtube.com/watch?v=ZZ", "source_type": "youtube",
        "raw_text": "REAL TRANSCRIPT NOT THE SUMMARY", "ingestor_version": "2.0.0",
        "fetched_at": "2026-04-24T00:00:00Z",
    }), encoding="utf-8")
    monkeypatch.setattr(m, "INGEST_CACHE_DIR", cache_dir)

    m.write_zettel_bundle(_row("wz-hit", "https://youtube.com/watch?v=ZZ", "SUMMARY-DERIVED BODY"),
                          dry_run=False)
    out = tmp_path / "_data" / "wz-hit"
    ev = json.loads((out / "source_evidence.json").read_text(encoding="utf-8"))
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert ev["evidence_source"] == "production_ingest_cache"
    assert ev["raw_text"] == "REAL TRANSCRIPT NOT THE SUMMARY"
    assert ev["ingestor_version"] == "2.0.0"
    assert meta["evidence_source"] == "production_ingest_cache"
    assert meta["content_digest"] == hashlib.sha256(
        "REAL TRANSCRIPT NOT THE SUMMARY".encode("utf-8")).hexdigest()
    # source_text.md is preserved untouched for back-compat
    assert (out / "source_text.md").read_text(encoding="utf-8") == "SUMMARY-DERIVED BODY"


def test_bundle_cache_miss_falls_back_and_flags(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "DATA_ROOT", tmp_path / "_data")
    cache_dir = tmp_path / "ingests"
    cache_dir.mkdir()  # empty -> guaranteed miss
    monkeypatch.setattr(m, "INGEST_CACHE_DIR", cache_dir)

    m.write_zettel_bundle(_row("wz-miss", "https://youtube.com/watch?v=NOPE", "BODY MD FALLBACK"),
                          dry_run=False)
    out = tmp_path / "_data" / "wz-miss"
    ev = json.loads((out / "source_evidence.json").read_text(encoding="utf-8"))
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert ev["evidence_source"] == "body_md_fallback"   # EXCLUDABLE, not silently scored
    assert ev["raw_text"] == "BODY MD FALLBACK"
    assert meta["evidence_source"] == "body_md_fallback"
    assert meta["content_digest"] == hashlib.sha256(
        "BODY MD FALLBACK".encode("utf-8")).hexdigest()


def test_bundle_caps_oversized_raw_text(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "DATA_ROOT", tmp_path / "_data")
    monkeypatch.setattr(m, "MAX_EVIDENCE_BYTES", 100)
    cache_dir = tmp_path / "ingests"
    cache_dir.mkdir()
    big = "x" * 5000
    (cache_dir / "big.json").write_text(json.dumps({
        "url": "https://youtube.com/watch?v=BIG", "source_type": "youtube",
        "raw_text": big, "ingestor_version": "2.0.0", "fetched_at": "2026-04-24T00:00:00Z",
    }), encoding="utf-8")
    monkeypatch.setattr(m, "INGEST_CACHE_DIR", cache_dir)

    m.write_zettel_bundle(_row("wz-big", "https://youtube.com/watch?v=BIG", "body"),
                          dry_run=False)
    ev = json.loads((tmp_path / "_data" / "wz-big" / "source_evidence.json").read_text(encoding="utf-8"))
    assert len(ev["raw_text"].encode("utf-8")) <= 100
    assert ev["raw_text_truncated"] is True
    assert ev["raw_text_full_len"] == 5000


def test_bundle_dry_run_writes_nothing(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "DATA_ROOT", tmp_path / "_data")
    monkeypatch.setattr(m, "INGEST_CACHE_DIR", tmp_path / "ingests")
    wz_id, status = m.write_zettel_bundle(_row("wz-dry", "https://x/y", "body"), dry_run=True)
    assert status == "dry-run"
    assert not (tmp_path / "_data" / "wz-dry").exists()
