# Wave 0 — Eval Evidence Reference + Judge Contract Guard Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the offline eval (`docs/zettel_eval_v1/`) score faithfulness against the *true* immutable raw source (the production ingest cache) instead of the summary-derived `body_md`, and add a deterministic schema-contract guard at the judge boundary — both without any paid re-judge/re-extract API call.

**Architecture:** Two offline, data-only changes. (1) `01_freeze_manifest.py::write_zettel_bundle` gains a cache-first true-source lookup (join manifest `normalized_url`+`source_type` against `docs/summary_eval/_cache/ingests/*.json`), writing a new `source_evidence.json` (raw_text capped ~600KB) + `evidence_source`/`content_digest` into `meta.json`; the two faithfulness consumers (`02_run_judge.py:353`, `03_run_nli.py:542`) repoint their *data source* from `source_text.md` to `source_evidence.json` with a back-compat fallback. (2) A pure helper `assert_summary_contract` runs at the judge load seam (`02_run_judge.py:354`) to fail-closed on malformed-fresh bundles and warn (not raise) on legacy bundles.

**Tech Stack:** Python 3.12, pytest (`asyncio_mode=auto`), stdlib only (`json`, `hashlib`, `re`, `pathlib`). No new dependencies, no model calls, no network.

---

## Context & decisions baked in (read once)

- **D1 — NO re-judge this iteration.** The operator declined the ~$8 spend. These fixes apply to *future* freezes. **No task in this plan calls a paid judge/extractor/NLI-model API.** The existing 81 frozen bundles stay as the reference; we do not re-freeze + re-judge them.
- **D2 — raw-source provenance = cache-where-present + fallback.** Verified live: 38 of 81 manifest URLs are present in `docs/summary_eval/_cache/ingests/` (run of `docs/zettel_eval_v1/analysis/_llm_silver/_d2_cache_check.py`, 2026-06-12: `manifest URLs found in cache: 38/81`). The other 43 fall back to `body_md` and are flagged `evidence_source="body_md_fallback"` so circular items are **excludable**, never silently scored. The operator re-ingests the misses out-of-band (a future freeze will then upgrade those to `evidence_source="reingest"` — value reserved, not written by this plan).
- **Supersedes / completes the master plan.** This plan supersedes `docs/superpowers/plans/2026-06-09-summarization-quality-fixes.md` Step A7 (re-judge — SKIPPED per D1) and completes its Step A5 sketch (the deterministic contract guard) and its Phase B sketch (Sol 1, true-source evidence). It is self-contained; the master plan is referenced only for lineage.

### Verified seams (confirmed against the real files 2026-06-12 — quote-of-record)

| Seam | File:line | Current code (verbatim) |
|---|---|---|
| Freeze writer signature | `01_freeze_manifest.py:103` | `def write_zettel_bundle(row: dict, *, dry_run: bool) -> tuple[str, str]:` |
| `DATA_ROOT` global | `01_freeze_manifest.py:42` | `DATA_ROOT = EVAL_ROOT / "_data"` |
| `body_md` extraction | `01_freeze_manifest.py:108` | `body_md = canon.get("body_md") or ""` |
| `meta` dict end | `01_freeze_manifest.py:124` | `"source_metadata": canon.get("source_metadata") or {},` |
| `source_text.md` write | `01_freeze_manifest.py:134` | `(out / "source_text.md").write_text(body_md, encoding="utf-8")` |
| `summary.json` block | `01_freeze_manifest.py:135-142` | `try:`…`json.loads(ai_summary)`…`(out / "summary.json").write_text(...)` |
| Freeze end-of-run prints | `01_freeze_manifest.py:199-202` | `print(f"wrote {written} per-zettel bundles to {DATA_ROOT}")` … |
| Judge source read | `02_run_judge.py:353` | `source_text = (data_dir / "source_text.md").read_text(encoding="utf-8")` |
| Judge summary load | `02_run_judge.py:354` | `summary_json = json.loads((data_dir / "summary.json").read_text(encoding="utf-8"))` |
| Judge empty guard | `02_run_judge.py:356` | `if not source_text.strip() or not summary_json:` |
| NLI `DATA` global | `03_run_nli.py:45` | `DATA = EVAL / "_data"` |
| NLI source path | `03_run_nli.py:542` | `source_path = data_dir / "source_text.md"` |
| NLI source read | `03_run_nli.py:548` | `source_text = source_path.read_text(encoding="utf-8", errors="replace")` |

### Cache file shape (confirmed against real production ingests 2026-06-12)

`docs/summary_eval/_cache/ingests/*.json` (184 files). Each is a flat JSON object (an `IngestResult` dump):
```
{ "confidence_reason": str, "extraction_confidence": str, "fetched_at": str (ISO),
  "ingestor_version": str (e.g. "2.0.0"), "metadata": {…}, "original_url": str,
  "raw_text": str, "sections": {…}, "source_type": str, "url": str }
```
- Join key: `url` (and `original_url`) vs manifest `normalized_url`, normalized by the same `norm()` the D2 check uses. Largest real `raw_text` = **513823 bytes** (the `ytdlp` transcript, `url=...watch?v=5t1vTLU7s40`), comfortably under the ~600KB cap. Some files are tiny test fixtures (`watch?v=test123`, `/foo/bar`) — those simply won't match real manifest URLs, so no special handling needed.

### Import-safety of `02_run_judge.py` (verified — drives the A5 test design)

AST scan (2026-06-12) of `02_run_judge.py` module body: the only top-level statements are the module docstring, `import`s, path-constant assigns (`REPO_ROOT`, `EVAL_ROOT`, `DATA_ROOT`, `RUNS_ROOT`, `CACHE_ROOT`, `MANIFEST`, `JUDGES_YAML`, `CALIB_SET`, `RUBRIC_PATH`), function/coroutine defs, and the `if __name__ == "__main__":` guard at line 520. **There are no import-time network calls, no `get_settings()`, no `SystemExit`.** The existing test `docs/zettel_eval_v1/tests/test_02_run_judge_env.py` already imports the script via `importlib.util.spec_from_file_location(...)` + `exec_module(...)` and passes. **Decision (flagged):** `assert_summary_contract` is added as a module-level pure function in `02_run_judge.py` and the A5 test loads it the same `exec_module` way — safe, and keeps the contract logic colocated with its only caller. No separate module is needed.

### Reconciliation with master-plan Phase A `_summary_source` values (flagged)

Master plan Step A3 (`01_freeze_manifest.py`, future) will set `summary.json["_summary_source"]` to `"structured_payload"` (fresh, has `tags`+`mini_title`) or `"ai_summary_envelope"` (fresh thin row). The **existing 81** bundles were written by the *old* block (lines 135-142) and have **no `_summary_source` key at all**. The A5 contract here therefore distinguishes three states:
1. `_summary_source == "structured_payload"` but `{tags, mini_title}` not both present → **raise** (malformed-fresh, fail-closed).
2. `_summary_source` **missing** (legacy-81, or any pre-A3 bundle) → **return a warning string** (do NOT raise — a hard fail would break the judge on the current corpus, which D1 forbids re-freezing).
3. anything else — including a well-formed `"structured_payload"` (both fields present) **and** `"ai_summary_envelope"` (documented fresh fallback) → **return `None`**.

This is consistent with A3 and intentionally additive: A5 is the *boundary enforcement* of the contract A3 produces.

---

## Task 1 — Pure helper `_norm_url` + `_load_ingest_cache_index` (cache join, no I/O coupling)

Build the URL-normalization + cache-index lookup as small pure/file-only helpers in the freeze script so they are unit-testable without Supabase. Reuses the exact `norm()` regex proven in `docs/zettel_eval_v1/analysis/_llm_silver/_d2_cache_check.py:18-19`.

**Files:**
- Modify: `docs/zettel_eval_v1/scripts/01_freeze_manifest.py` (add helpers after the `_project_ref_from_url` function, currently ending line 73; insert at line 74)
- Test: `docs/zettel_eval_v1/tests/test_01_source_evidence.py` (Create)

- [ ] **Step 1.1 — Write the failing test for `_norm_url` + cache index**

Create `docs/zettel_eval_v1/tests/test_01_source_evidence.py`:
```python
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
```

- [ ] **Step 1.2 — Run it, verify FAIL**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_01_source_evidence.py -v`
Expected: FAIL — `AttributeError: module 'zettel_eval_v1_01_freeze' has no attribute '_norm_url'` (and `_load_ingest_cache_index`).

- [ ] **Step 1.3 — Implement the helpers**

In `docs/zettel_eval_v1/scripts/01_freeze_manifest.py`, add `import re` to the import block (after `import os`, line 33) and insert these helpers immediately after `_project_ref_from_url` (after line 73):
```python
# --- Sol 1 / D2: true-source evidence from the production ingest cache ---
# The cache lives at docs/summary_eval/_cache/ingests/*.json (FsContentCache of
# IngestResult). Join is by normalized URL, NOT by the cache filename hash.
INGEST_CACHE_DIR = REPO_ROOT / "docs" / "summary_eval" / "_cache" / "ingests"
# Cap to bound git size; largest real prod raw_text is ~513KB (one ytdlp transcript).
MAX_EVIDENCE_BYTES = 600_000


def _norm_url(u: str | None) -> str:
    """Normalize a URL for cache joins. Mirrors _d2_cache_check.norm() exactly:
    drop scheme + leading www., strip trailing slash, lowercase."""
    return re.sub(r"^https?://(www\.)?", "", (u or "").rstrip("/").lower())


def _load_ingest_cache_index(cache_dir: Path) -> dict[str, dict]:
    """Build {normalized_url: ingest_dict} from the prod ingest cache. Files with
    no usable raw_text are skipped so they can never masquerade as true source.
    On a duplicate normalized URL the most-recently fetched record wins."""
    index: dict[str, dict] = {}
    if not cache_dir.exists():
        return index
    for f in sorted(cache_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or not (d.get("raw_text") or "").strip():
            continue
        for url_key in ("url", "original_url", "normalized_url", "source_url"):
            raw = d.get(url_key)
            if isinstance(raw, str) and raw.startswith("http"):
                nu = _norm_url(raw)
                prev = index.get(nu)
                if prev is None or (d.get("fetched_at") or "") >= (prev.get("fetched_at") or ""):
                    index[nu] = d
    return index
```

- [ ] **Step 1.4 — Run test, verify PASS**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_01_source_evidence.py -v`
Expected: PASS (3 passed).

- [ ] **Step 1.5 — Commit**

```bash
git add docs/zettel_eval_v1/scripts/01_freeze_manifest.py docs/zettel_eval_v1/tests/test_01_source_evidence.py
git commit -m "feat: add ingest-cache URL join helpers for eval evidence"
```

---

## Task 2 — `write_zettel_bundle` writes `source_evidence.json` + `evidence_source`/`content_digest` in `meta.json`

Cache-first true source; `body_md` fallback flagged + excludable. `source_text.md` is **kept untouched** for back-compat.

**Files:**
- Modify: `docs/zettel_eval_v1/scripts/01_freeze_manifest.py:103-143` (`write_zettel_bundle`)
- Test: `docs/zettel_eval_v1/tests/test_01_source_evidence.py` (add cases)

- [ ] **Step 2.1 — Write the failing test for the bundle writer**

Append to `docs/zettel_eval_v1/tests/test_01_source_evidence.py`:
```python
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
```

- [ ] **Step 2.2 — Run it, verify FAIL**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_01_source_evidence.py -v`
Expected: FAIL — `KeyError: 'evidence_source'` in `source_evidence.json` / `meta.json` (the writer does not yet emit them; `source_evidence.json` does not exist).

- [ ] **Step 2.3 — Implement the writer changes**

Build the cache index **once per run**, not per zettel (184 files × 81 zettels = wasteful). Add a module-level cached accessor after the helpers from Task 1 (insert right after `_load_ingest_cache_index`):
```python
_INGEST_INDEX_CACHE: dict[str, dict] | None = None


def _ingest_index() -> dict[str, dict]:
    """Lazy, run-scoped cache of the ingest index (built once, reused per zettel)."""
    global _INGEST_INDEX_CACHE
    if _INGEST_INDEX_CACHE is None:
        _INGEST_INDEX_CACHE = _load_ingest_cache_index(INGEST_CACHE_DIR)
    return _INGEST_INDEX_CACHE
```
Then, inside `write_zettel_bundle`, in the `meta` dict (currently lines 112-125) resolve the evidence **before** building `meta` so the fields can be embedded. Replace the block from `body_md = canon.get("body_md") or ""` (line 108) through the end of the `meta = { ... }` dict (line 125) with:
```python
    body_md = canon.get("body_md") or ""
    ai_summary = row.get("ai_summary") or ""
    content_hash = canon.get("content_hash") or ""
    chash_hex = content_hash.replace("\\x", "") if isinstance(content_hash, str) else ""

    # Sol 1 / D2: choose the TRUE raw source. Cache hit -> production_ingest_cache;
    # miss -> body_md_fallback (flagged so circular items are EXCLUDABLE, not scored).
    norm_url = _norm_url(canon.get("normalized_url"))
    hit = _ingest_index().get(norm_url)
    if hit is not None:
        evidence_source = "production_ingest_cache"
        raw_text_full = hit.get("raw_text") or ""
        ingestor_version = hit.get("ingestor_version") or ""
        fetched_at = hit.get("fetched_at") or ""
    else:
        evidence_source = "body_md_fallback"
        raw_text_full = body_md
        ingestor_version = ""
        fetched_at = ""

    raw_bytes = raw_text_full.encode("utf-8")
    truncated = len(raw_bytes) > MAX_EVIDENCE_BYTES
    raw_text = raw_bytes[:MAX_EVIDENCE_BYTES].decode("utf-8", errors="ignore") if truncated else raw_text_full
    content_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    meta = {
        "workspace_zettel_id": wz_id,
        "workspace_id": str(row["workspace_id"]),
        "canonical_zettel_id": str(canon.get("id") or ""),
        "normalized_url": canon.get("normalized_url"),
        "title": canon.get("title"),
        "source_type": canon.get("source_type"),
        "publication_date": str(canon.get("publication_date") or ""),
        "captured_at": str(row.get("created_at") or ""),
        "ai_summary_len": len(ai_summary),
        "body_md_len": len(body_md),
        "content_hash_hex": chash_hex,
        "source_metadata": canon.get("source_metadata") or {},
        # Sol 1 provenance: lets a consumer exclude circular (body_md_fallback) items.
        "evidence_source": evidence_source,
        "content_digest": content_digest,
    }
```
Then, after the existing `source_text.md` write (line 134, leave it exactly as-is), add the new `source_evidence.json` write immediately before the `try:`/`summary.json` block (insert between line 134 and line 135):
```python
    source_evidence = {
        "evidence_source": evidence_source,
        "raw_text": raw_text,
        "content_digest": content_digest,
        "ingestor_version": ingestor_version,
        "fetched_at": fetched_at,
        "raw_text_truncated": truncated,
        "raw_text_full_len": len(raw_text_full),
    }
    (out / "source_evidence.json").write_text(
        json.dumps(source_evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
```

- [ ] **Step 2.4 — Run test, verify PASS**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_01_source_evidence.py -v`
Expected: PASS (8 passed — 3 from Task 1 + 5 here).

- [ ] **Step 2.5 — Commit**

```bash
git add docs/zettel_eval_v1/scripts/01_freeze_manifest.py docs/zettel_eval_v1/tests/test_01_source_evidence.py
git commit -m "feat: write source_evidence.json from ingest cache"
```

---

## Task 3 — Harness-health metric: "% of corpus with true source" printed at freeze end

`main()` already prints a summary at lines 199-202. Add a count of `evidence_source == production_ingest_cache` vs `body_md_fallback`, returned from `write_zettel_bundle` and tallied in `main()`.

**Files:**
- Modify: `docs/zettel_eval_v1/scripts/01_freeze_manifest.py:103-143` (return value) and `:194-202` (`main()` tally + print)
- Test: `docs/zettel_eval_v1/tests/test_01_source_evidence.py` (add case asserting the returned evidence label)

- [ ] **Step 3.1 — Write the failing test for the returned evidence label**

Append to `docs/zettel_eval_v1/tests/test_01_source_evidence.py`:
```python
def test_bundle_returns_evidence_source_label(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "DATA_ROOT", tmp_path / "_data")
    cache_dir = tmp_path / "ingests"
    cache_dir.mkdir()
    (cache_dir / "h.json").write_text(json.dumps({
        "url": "https://youtube.com/watch?v=L", "source_type": "youtube",
        "raw_text": "R", "ingestor_version": "2.0.0", "fetched_at": "2026-04-24T00:00:00Z",
    }), encoding="utf-8")
    monkeypatch.setattr(m, "INGEST_CACHE_DIR", cache_dir)

    wz_id, status = m.write_zettel_bundle(
        _row("wz-lab", "https://youtube.com/watch?v=L", "body"), dry_run=False)
    assert status == "production_ingest_cache"  # status doubles as the evidence label
    wz_id2, status2 = m.write_zettel_bundle(
        _row("wz-lab2", "https://youtube.com/watch?v=MISS", "body"), dry_run=False)
    assert status2 == "body_md_fallback"
```

NOTE — this changes the `write_zettel_bundle` return contract: the second tuple element becomes the **evidence label** on success (was the literal string `"written"`). `main()` (the only caller) is updated in Step 3.3 to treat any non-`"dry-run"` status as written. The master plan's Phase A test (`test_01_freeze_contract.py`) calls `write_zettel_bundle(...)` for its side effects and ignores the return tuple, so this is non-breaking for it.

- [ ] **Step 3.2 — Run it, verify FAIL**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_01_source_evidence.py::test_bundle_returns_evidence_source_label -v`
Expected: FAIL — `assert 'written' == 'production_ingest_cache'` (writer still returns the literal `"written"`).

- [ ] **Step 3.3 — Implement the return-label + main() tally/print**

In `write_zettel_bundle`, change the final return (line 143) from:
```python
    return wz_id, "written"
```
to:
```python
    # 2nd element = evidence label (was "written") so main() can tally true-source %.
    return wz_id, evidence_source
```
In `main()`, replace the write loop + summary (lines 194-202) — current code:
```python
    written = 0
    for r in rows:
        _, status = write_zettel_bundle(r, dry_run=args.dry_run)
        if status == "written":
            written += 1
    print(f"wrote {written} per-zettel bundles to {DATA_ROOT}")
```
with:
```python
    written = 0
    n_true_source = 0
    n_fallback = 0
    for r in rows:
        _, status = write_zettel_bundle(r, dry_run=args.dry_run)
        if status == "dry-run":
            continue
        written += 1
        if status == "production_ingest_cache":
            n_true_source += 1
        elif status == "body_md_fallback":
            n_fallback += 1
    print(f"wrote {written} per-zettel bundles to {DATA_ROOT}")
    if written:
        pct = 100.0 * n_true_source / written
        # Harness-health (Sol 1): faithfulness is trustworthy only on true-source items;
        # body_md_fallback items are circular and should be EXCLUDED from faithfulness stats.
        print(f"true-source coverage: {n_true_source}/{written} ({pct:.0f}%) "
              f"via production_ingest_cache; {n_fallback} body_md_fallback (EXCLUDABLE)")
```

- [ ] **Step 3.4 — Run test, verify PASS**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_01_source_evidence.py -v`
Expected: PASS (9 passed).

- [ ] **Step 3.5 — Commit**

```bash
git add docs/zettel_eval_v1/scripts/01_freeze_manifest.py docs/zettel_eval_v1/tests/test_01_source_evidence.py
git commit -m "feat: print true-source coverage at freeze end"
```

---

## Task 4 — Repoint the judge faithfulness consumer to `source_evidence.json` (data-source only)

`02_run_judge.py:353` currently reads `source_text.md` (= summary-derived `body_md`). Repoint to the true source with a back-compat fallback for bundles frozen before this plan. **No judge-logic change** — only the bytes fed as `source_text`.

**Files:**
- Modify: `docs/zettel_eval_v1/scripts/02_run_judge.py:353` (+ a tiny helper near the top, inserted after the path constants, line 60)
- Test: `docs/zettel_eval_v1/tests/test_02_evidence_source.py` (Create)

- [ ] **Step 4.1 — Write the failing test for the source-selection helper**

The judge's per-zettel loop is `async` and constructs Gemini/Claude clients before reaching the read (would require network) — so we extract the *pure* data-selection into a helper `read_faithfulness_source(data_dir) -> str` and test that in isolation. Create `docs/zettel_eval_v1/tests/test_02_evidence_source.py`:
```python
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
```

- [ ] **Step 4.2 — Run it, verify FAIL**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_02_evidence_source.py -v`
Expected: FAIL — `AttributeError: module 'zettel_eval_v1_02_judge_ev' has no attribute 'read_faithfulness_source'`.

- [ ] **Step 4.3 — Implement the helper + repoint the read**

In `02_run_judge.py`, insert the helper after the path constants (after `RUBRIC_PATH = ...`, line 59):
```python
def read_faithfulness_source(data_dir: Path) -> str:
    """TRUE source for faithfulness: source_evidence.json.raw_text (Sol 1).
    Falls back to source_text.md for bundles frozen before Sol 1 / when evidence
    raw_text is empty. Data-source only — judge logic unchanged."""
    ev_path = data_dir / "source_evidence.json"
    if ev_path.exists():
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            raw = (ev or {}).get("raw_text") or ""
            if raw.strip():
                return raw
        except Exception:
            pass
    legacy = data_dir / "source_text.md"
    return legacy.read_text(encoding="utf-8") if legacy.exists() else ""
```
Then change the read at line 353 from:
```python
        source_text = (data_dir / "source_text.md").read_text(encoding="utf-8")
```
to:
```python
        source_text = read_faithfulness_source(data_dir)  # Sol 1: true source, fallback to source_text.md
```

- [ ] **Step 4.4 — Run test, verify PASS**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_02_evidence_source.py -v`
Expected: PASS (3 passed).

- [ ] **Step 4.5 — Commit**

```bash
git add docs/zettel_eval_v1/scripts/02_run_judge.py docs/zettel_eval_v1/tests/test_02_evidence_source.py
git commit -m "feat: judge reads true source_evidence with fallback"
```

---

## Task 5 — Repoint the NLI faithfulness consumer to `source_evidence.json` (data-source only)

`03_run_nli.py:542` sets `source_path = data_dir / "source_text.md"`, read at line 548 as the NLI premise. Repoint to the true source via the same fallback. **NLI already chunks + max-pools long premises** (`_chunk_premise`, lines 222-310) so no NLI-logic change is needed even for the 513KB transcript.

**Files:**
- Modify: `docs/zettel_eval_v1/scripts/03_run_nli.py:542-548` (`_augment_one`) + a helper after the path constants (line 46)
- Test: `docs/zettel_eval_v1/tests/test_03_evidence_source.py` (Create)

- [ ] **Step 5.1 — Write the failing test for the NLI source helper**

`03_run_nli.py` may import torch/transformers lazily, but its module body defines path constants + functions; the existing `tests/test_03_run_nli.py` imports it via `exec_module`. We add a pure helper `read_nli_source(data_dir) -> str` mirroring the judge's, and test it in isolation. Create `docs/zettel_eval_v1/tests/test_03_evidence_source.py`:
```python
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
```

- [ ] **Step 5.2 — Run it, verify FAIL**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_03_evidence_source.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'read_nli_source'`.

- [ ] **Step 5.3 — Implement the helper + repoint the premise read**

In `03_run_nli.py`, insert the helper after the path constants (after `CACHE = EVAL / "_cache"`, line 46):
```python
def read_nli_source(data_dir: Path) -> str:
    """TRUE NLI premise: source_evidence.json.raw_text (Sol 1). Falls back to
    source_text.md for pre-Sol-1 bundles / empty evidence. Premise bytes only —
    NLI chunking (_chunk_premise) handles long sources unchanged."""
    ev_path = data_dir / "source_evidence.json"
    if ev_path.exists():
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8", errors="replace"))
            raw = (ev or {}).get("raw_text") or ""
            if raw.strip():
                return raw
        except Exception:
            pass
    legacy = data_dir / "source_text.md"
    return legacy.read_text(encoding="utf-8", errors="replace") if legacy.exists() else ""
```
Then in `_augment_one`, replace the source read block (lines 542-548). Current code:
```python
    source_path = data_dir / "source_text.md"
    summary_path = data_dir / "summary.json"
    meta_path = data_dir / "meta.json"
    if not source_path.exists():
        payload["nli"] = {"error": f"source_text.md missing for {wz_id}"}
        return payload
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
```
with:
```python
    summary_path = data_dir / "summary.json"
    meta_path = data_dir / "meta.json"
    source_text = read_nli_source(data_dir)  # Sol 1: true premise, fallback to source_text.md
    if not source_text:
        payload["nli"] = {"error": f"no source for {wz_id} (evidence + source_text.md both empty)"}
        return payload
```

- [ ] **Step 5.4 — Run test, verify PASS**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_03_evidence_source.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5.5 — Commit**

```bash
git add docs/zettel_eval_v1/scripts/03_run_nli.py docs/zettel_eval_v1/tests/test_03_evidence_source.py
git commit -m "feat: NLI premise reads true source_evidence with fallback"
```

---

## Task 6 — Sol 2 / A5: deterministic schema-contract guard at the judge boundary

A pure helper `assert_summary_contract(wz_id, summary_json) -> str | None` enforces the master-plan Phase A contract at the judge load seam (`02_run_judge.py:354`). Fail-closed on malformed-fresh; WARN (not raise) on legacy bundles (D1 forbids re-freezing the 81); `None` otherwise.

**Files:**
- Modify: `docs/zettel_eval_v1/scripts/02_run_judge.py` (add helper after `read_faithfulness_source` from Task 4; call it after line 354)
- Test: `docs/zettel_eval_v1/tests/test_02_summary_contract.py` (Create)

**Import-safety decision (flagged):** `assert_summary_contract` is a module-level pure function in `02_run_judge.py`. Verified 2026-06-12 that importing the module has no side effects (AST: only path constants + defs + `if __name__` guard at line 520; the existing `test_02_run_judge_env.py` already `exec_module`s it and passes). So the test loads it via `exec_module` directly — no separate module, contract logic stays colocated with its sole caller.

- [ ] **Step 6.1 — Write the failing test for the contract guard**

Create `docs/zettel_eval_v1/tests/test_02_summary_contract.py`:
```python
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
```

- [ ] **Step 6.2 — Run it, verify FAIL**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_02_summary_contract.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'assert_summary_contract'`.

- [ ] **Step 6.3 — Implement the helper + wire it at the seam**

In `02_run_judge.py`, add the helper immediately after `read_faithfulness_source` (from Task 4):
```python
def assert_summary_contract(wz_id: str, summary_json: dict) -> str | None:
    """Deterministic schema-contract guard (Sol 2 / A5) — NOT the LLM judge.
    Fail-closed on malformed-fresh; WARN (not raise) on legacy bundles.

    Returns None if clean, or a warning string for legacy bundles. Raises
    ValueError for malformed-fresh (structured_payload missing rubric fields)."""
    src = (summary_json or {}).get("_summary_source")
    if src == "structured_payload":
        # fresh bundle that claims to carry the rubric fields MUST carry both
        if not ({"tags", "mini_title"} <= set(summary_json)):
            raise ValueError(
                f"{wz_id}: malformed-fresh summary.json — _summary_source="
                f"'structured_payload' but tags/mini_title not both present")
        return None
    if src is None:
        # legacy bundle (pre master-plan A3); D1 declined the re-freeze so WARN only
        return (f"{wz_id}: legacy summary.json (no _summary_source) — contract "
                f"not enforced; faithfulness reference unaffected")
    return None  # ai_summary_envelope (documented fresh fallback) or any other tagged state
```
Then wire it at the seam. Current code at lines 354-358:
```python
        summary_json = json.loads((data_dir / "summary.json").read_text(encoding="utf-8"))

        if not source_text.strip() or not summary_json:
            print(f"  [{i}/{len(zettels)}] SKIP {wz_id}: empty source or summary")
            continue
```
Insert the contract check between the load (line 354) and the empty guard (line 356):
```python
        summary_json = json.loads((data_dir / "summary.json").read_text(encoding="utf-8"))

        contract_warn = assert_summary_contract(wz_id, summary_json)
        if contract_warn:
            print(f"  [{i}/{len(zettels)}] WARN {contract_warn}")

        if not source_text.strip() or not summary_json:
            print(f"  [{i}/{len(zettels)}] SKIP {wz_id}: empty source or summary")
            continue
```

- [ ] **Step 6.4 — Run test, verify PASS**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/test_02_summary_contract.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6.5 — Commit**

```bash
git add docs/zettel_eval_v1/scripts/02_run_judge.py docs/zettel_eval_v1/tests/test_02_summary_contract.py
git commit -m "feat: deterministic summary-contract guard at judge boundary"
```

---

## Task 7 — Full-suite regression + dry-run smoke (no paid calls)

Confirm nothing else in the eval test suite broke, and that the freeze dry-run path still works end-to-end without touching Supabase or model APIs.

**Files:** none (verification only).

- [ ] **Step 7.1 — Run the full eval test suite**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python -m pytest docs/zettel_eval_v1/tests/ -v`
Expected: all PASS, including the four new files (`test_01_source_evidence.py`, `test_02_evidence_source.py`, `test_02_summary_contract.py`, `test_03_evidence_source.py`) and the pre-existing `test_02_run_judge_env.py` / `test_03_run_nli.py` etc. (No `test_01_freeze_contract.py` exists yet — that file is created by the master plan's Phase A and is out of scope here.)

- [ ] **Step 7.2 — Smoke the freeze helpers against the real cache (read-only, offline)**

Confirm the true-source coverage is the expected 38/81 against the real corpus. This calls **no** API — it only reads JSON files. Re-run the proven coverage checker, which exercises the same `norm()` join the new `_norm_url` helper mirrors:

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180 && python docs/zettel_eval_v1/analysis/_llm_silver/_d2_cache_check.py`
Expected: `manifest URLs found in cache: 38/81` (per-source: github 11/12, newsletter 1/2, reddit 9/15, web 14/19, youtube 3/33). This is the harness-health number Task 3 prints during a real freeze — `38/81 (47%) via production_ingest_cache; 43 body_md_fallback (EXCLUDABLE)`.

- [ ] **Step 7.3 — Commit (only if any doc/whitespace touch-up was needed; otherwise skip)**

```bash
git add -A
git commit -m "test: verify eval evidence + contract suite green"
```

---

## Self-review

**Spec coverage (PART 1 — Sol 1, true-source evidence):**
- ✅ `evidence_source` ∈ {`production_ingest_cache`, `reingest`, `body_md_fallback`} + `content_digest` (sha256 of chosen raw source) in `meta.json` — Task 2 (writer emits both; `reingest` value is *reserved* for the operator's out-of-band re-ingest, not written by this offline plan — flagged in Context).
- ✅ New `source_evidence.json` per zettel: cache hit → `raw_text` (capped ~600KB, `MAX_EVIDENCE_BYTES=600_000`) + `evidence_source=production_ingest_cache`; miss → `body_md` + `evidence_source=body_md_fallback` (flagged + excludable) — Task 2. `source_text.md` is **not** overwritten (back-compat) — asserted in `test_bundle_cache_hit_writes_true_source`.
- ✅ Repoint faithfulness consumers, data-source only: `02_run_judge.py:353` (Task 4) and `03_run_nli.py:542` (Task 5). NLI logic unchanged — premise chunking (`_chunk_premise`, 222-310) confirmed to handle long sources; only the premise bytes change.
- ✅ Harness-health metric "% of corpus with true source" printed at freeze end — Task 3.
- ✅ URL-normalization join reuses the proven `_d2_cache_check.norm()` regex verbatim (Task 1 `_norm_url`); cache shape confirmed against real production ingests (keys `raw_text`, `url`/`original_url`, `source_type`, `ingestor_version`, `fetched_at`).
- ✅ No paid API: every task reads cached JSON / runs pure helpers; **no judge, extractor, or NLI-model call anywhere** (D1 honored). No re-freeze + re-judge of the existing 81 (D1).
- ✅ Citations to embed in code/commit context where the rationale lands (faithfulness-vs-true-source): FineSurE (ACL'24), FaithBench (NAACL'25), RAGAS (arXiv:2309.15217), golden-dataset immutability (Statsig/Arize'25). These justify *why* faithfulness must score against the immutable raw source, not the summary-derived `body_md`.

**Spec coverage (PART 2 — Sol 2 / A5, contract guard):**
- ✅ Pure helper `assert_summary_contract(wz_id, summary_json) -> str | None` — Task 6. structured_payload-without-{tags,mini_title} → **raise** (fail-closed); `_summary_source` missing (legacy 81) → **warn string** (no raise, D1-safe); else → **None** (covers clean structured_payload and `ai_summary_envelope`).
- ✅ Called at the seam right after `summary.json` load (`02_run_judge.py:354`), before the empty guard at line 356; warning printed if returned — Task 6 Step 6.3.
- ✅ Focused unit test in `docs/zettel_eval_v1/tests/` matching the existing `exec_module` style: malformed-fresh raises, legacy warns (not raise), clean returns None, plus partial-malformed + envelope-fallback edge cases — Task 6 Step 6.1.
- ✅ Import-side-effect question resolved + **flagged**: AST-verified `02_run_judge.py` is import-safe; helper stays module-level and colocated; test uses `exec_module` (same as the passing `test_02_run_judge_env.py`).
- ✅ Supersedes master-plan A7 (re-judge skipped) and completes A5 sketch — stated in Context; reconciliation of `_summary_source` values ({structured_payload, ai_summary_envelope, missing}) vs master-plan A3 is **flagged**.

**Placeholder scan:** No "TBD", no "add X", no "similar to Task N", no "write tests for the above" without code. Every test step shows full real test code; every implement step shows the exact verbatim before/after. All `cd … && python -m pytest …` commands use the absolute repo path.

**Type / seam consistency:**
- `write_zettel_bundle` return type stays `tuple[str, str]`; 2nd element semantics change from the literal `"written"` to the evidence label (`production_ingest_cache` | `body_md_fallback` | `dry-run`). Sole caller `main()` updated (Task 3); master-plan Phase A test ignores the return tuple → non-breaking (flagged in Task 3.1).
- `read_faithfulness_source(Path) -> str` and `read_nli_source(Path) -> str` are parallel pure helpers with identical fallback semantics; both return `""` when nothing is available (judge guards on `not source_text.strip()` at line 356; NLI guards on `if not source_text` in Task 5.3).
- `assert_summary_contract(str, dict) -> str | None` — `None`=clean, `str`=legacy warn, `ValueError`=malformed-fresh. Caller treats truthy return as a printable warning only.
- New module-level constants in `01_freeze_manifest.py`: `INGEST_CACHE_DIR`, `MAX_EVIDENCE_BYTES`, `_INGEST_INDEX_CACHE`; all monkeypatch-overridable in tests (done in Tasks 1-3). `import re` + `import hashlib` (hashlib already imported at line 31; only `re` is new).

**Residual risk:** Low — offline-only, no production blast radius. The one behavioral change in a shared seam (`write_zettel_bundle` return label) is covered by Task 3.1 and the only caller is updated. The `_INGEST_INDEX_CACHE` module global persists across `write_zettel_bundle` calls within a process; tests reset it implicitly by reloading the module via `exec_module` and monkeypatching `INGEST_CACHE_DIR` before the first `_ingest_index()` call — each `_mod()` returns a fresh module object, so no cross-test bleed.
