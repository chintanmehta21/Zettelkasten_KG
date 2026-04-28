# Iter-03 Prod Memory-Bounded Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hold peak RSS per blue/green container ≤ 1.3 GB on the existing 2 GB / 1 vCPU DigitalOcean droplet, without regressing user latency or `end_to_end_gold@1` by more than 3%.

**Architecture:** Nine independently-revertable changes (compose ceiling, host swap verification, ONNX arena off, fp32 verifier env-disabled, FlashRank module-preload, LRU-bounded query cache, gunicorn worker recycling, ops instrumentation, soft RSS-guard middleware) plus a manual one-shot droplet runbook step. Each change is one commit on `iter-03/prod-memory-bounded` branched from `master`, then squashed/merged after validation.

**Tech Stack:** Python 3.12, FastAPI, gunicorn 25 + uvicorn workers, onnxruntime, flashrank, cachetools, Docker Compose blue/green, Caddy 2, DigitalOcean droplet.

**Spec:** `docs/superpowers/specs/2026-04-28-iter-03-prod-memory-bounded-design.md` (committed at `8ddea22`)

---

## Read this first (every executor)

1. **CLAUDE.md "Critical Infra Decision Guardrails" + "When to ask vs when to keep moving"** — non-negotiable. Never silently undo `GUNICORN_WORKERS=2`, `--preload`, int8 cascade, Phase 1B semaphore + queue, SSE heartbeat, Caddy 240s timeouts, schema-drift gate, allowlist gate, teal/amber palette. Re-enabling `RAG_FP32_VERIFY=on` is **last-resort only**, never the first revert.
2. **Commit messages:** 5–10 words, prefix tag (`feat:` / `fix:` / `refactor:` / `test:` / `ops:` / `docs:` / `chore:` / `ci:`), no AI/tool names, no `Co-Authored-By` trailers. HEREDOC body if longer rationale needed (rare).
3. **Smart-explore first:** for any `*.py` / `*.ts` / `*.js` / `*.tsx` file, prefer `mcp__plugin_mem-vault_mem-vault__smart_outline` and `smart_search` over `Read` / `Grep` / `Glob`. Fallback to standard tools only when smart-explore returns nothing.
4. **Each task ends with a tactical commit on `iter-03/prod-memory-bounded`.** End-of-phase squashes consolidate to nine logical commits before merge to `master` (see Phase 12).
5. **No skipped tests.** Every behavior change ships with a test that fails before the change and passes after.
6. **Wrap any secret value in `<private>...</private>` tags before output.** This includes: any `.env` content, GH Actions secrets, Supabase URLs, droplet IPs, SSH keys.

---

## Phase 0 — Pre-flight (~10 min)

### Task 0.1: Create the iter-03/prod-memory-bounded branch

**Files:** none yet.

- [ ] **Step 1: Sync master**

Run: `git fetch origin master && git checkout master && git reset --hard origin/master`
Expected: working tree clean, HEAD at the latest pushed commit on master.

- [ ] **Step 2: Verify clean state**

Run: `git status --short && git log --oneline -5`
Expected: empty `git status`. Top commit is the most recent merged change (sha will vary; should include `7158a8d` "fix: drop sudo in log workflow allow docker tail" and predecessors).

- [ ] **Step 3: Create branch**

Run: `git checkout -b iter-03/prod-memory-bounded`
Expected: `Switched to a new branch 'iter-03/prod-memory-bounded'`.

- [ ] **Step 4: Push branch upstream**

Run: `git push -u origin iter-03/prod-memory-bounded`
Expected: branch tracks `origin/iter-03/prod-memory-bounded`.

### Task 0.2: Capture pre-change baseline metrics

**Files:**
- Create: `docs/rag_eval/common/knowledge-management/iter-03/baseline_pre_mem_bounded.json`

- [ ] **Step 1: Run the Playwright harness against current prod**

Operator runs (locally, not in CI):
```powershell
$env:ZK_BEARER_TOKEN = Get-Clipboard
python ops/scripts/eval_iter_03_playwright.py --max-queries 13 --skip-burst
```
Expected: produces `docs/rag_eval/common/knowledge-management/iter-03/verification_results.json` with the current production state (the 502s are a feature here — they ARE the baseline `infra_failures` count).

- [ ] **Step 2: Persist as baseline**

Copy:
```bash
cp docs/rag_eval/common/knowledge-management/iter-03/verification_results.json \
   docs/rag_eval/common/knowledge-management/iter-03/baseline_pre_mem_bounded.json
```

The post-deploy eval (Phase 11) will diff against this file.

- [ ] **Step 3: Commit baseline**

```bash
git add docs/rag_eval/common/knowledge-management/iter-03/baseline_pre_mem_bounded.json
git commit -m "chore: capture pre-mem-bounded baseline"
```

---

## Phase 1 — Container ceiling (compose) (~10 min)

### Task 1.1: Bump mem_limit + memswap_limit in compose files

**Files:**
- Modify: `ops/docker-compose.blue.yml` (lines 21-22)
- Modify: `ops/docker-compose.green.yml` (lines 21-22 — same shape)

- [ ] **Step 1: Read current state of `ops/docker-compose.blue.yml`**

Run: `grep -n 'mem_limit\|memswap_limit' ops/docker-compose.blue.yml ops/docker-compose.green.yml`
Expected output:
```
ops/docker-compose.blue.yml:21:    mem_limit: 1024m
ops/docker-compose.blue.yml:22:    memswap_limit: 1024m
ops/docker-compose.green.yml:21:    mem_limit: 1024m
ops/docker-compose.green.yml:22:    memswap_limit: 1024m
```

- [ ] **Step 2: Edit `ops/docker-compose.blue.yml`**

Replace exactly:
```yaml
    mem_limit: 1024m
    memswap_limit: 1024m
```
with:
```yaml
    # iter-03 mem-bounded: cgroup ceiling 1300m + 1000m swap budget. Spec §2.1.
    mem_limit: 1300m
    memswap_limit: 2300m
```

- [ ] **Step 3: Edit `ops/docker-compose.green.yml`**

Identical change as Step 2. Same lines, same replacement.

- [ ] **Step 4: Lint both compose files**

Run: `python -c "import yaml; yaml.safe_load(open('ops/docker-compose.blue.yml')); yaml.safe_load(open('ops/docker-compose.green.yml')); print('yaml OK')"`
Expected: `yaml OK`.

- [ ] **Step 5: Commit**

```bash
git add ops/docker-compose.blue.yml ops/docker-compose.green.yml
git commit -m "ops: bump container mem_limit 1300m 1g swap"
```

---

## Phase 2 — ONNX arena off (cascade.py) (~25 min)

### Task 2.1: Disable arena + mem_pattern in `_build_ort_session`

**Files:**
- Modify: `website/features/rag_pipeline/rerank/cascade.py` (lines 53-60 — inside `_build_ort_session`)
- Test: `tests/unit/quantization/test_arena_off.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/quantization/test_arena_off.py`:

```python
"""Iter-03 mem-bounded §2.3: ONNX arena + mem_pattern must default to off
in _build_ort_session so per-call working set does not leak into a
session-lifetime arena slab. See microsoft/onnxruntime#11627.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from website.features.rag_pipeline.rerank import cascade


class _CaptureOpts:
    """Stand-in for ort.SessionOptions that just records every assignment."""

    def __init__(self) -> None:
        self.intra_op_num_threads = None
        self.inter_op_num_threads = None
        self.graph_optimization_level = None
        self.enable_cpu_mem_arena = None
        self.enable_mem_pattern = None


def test_build_ort_session_disables_arena(tmp_path: Path):
    fake_path = tmp_path / "fake.onnx"
    fake_path.write_bytes(b"")  # exists, contents irrelevant — InferenceSession is mocked

    captured = _CaptureOpts()

    def _fake_session_options():
        return captured

    def _fake_inference_session(*_args, **_kwargs):
        return object()

    with patch.object(cascade.ort, "SessionOptions", _fake_session_options), \
         patch.object(cascade.ort, "InferenceSession", _fake_inference_session):
        result = cascade._build_ort_session(fake_path)

    assert result is not None
    assert captured.enable_cpu_mem_arena is False, \
        "arena MUST be off — see spec §2.3 / onnxruntime issue #11627"
    assert captured.enable_mem_pattern is False, \
        "mem_pattern MUST be off — no perf benefit on dynamic-shape inputs"
    assert captured.intra_op_num_threads == 1
    assert captured.inter_op_num_threads == 1


def test_build_ort_session_returns_none_when_path_missing(tmp_path: Path):
    missing = tmp_path / "nope.onnx"
    assert cascade._build_ort_session(missing) is None
```

- [ ] **Step 2: Run test — must fail**

Run: `python -m pytest tests/unit/quantization/test_arena_off.py -v`
Expected: `FAILED ... assert captured.enable_cpu_mem_arena is False` (currently the helper does not set the flag).

- [ ] **Step 3: Edit `_build_ort_session` in `website/features/rag_pipeline/rerank/cascade.py`**

Replace exactly (lines 53-60 inside the existing helper):

```python
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    try:
        return ort.InferenceSession(
            str(path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
```

with:

```python
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # iter-03 mem-bounded §2.3: cap arena at per-call working set instead of
    # holding the high-water mark for the session lifetime. Both flags off
    # because mem_pattern only helps when arena is on AND shapes are static.
    # Latency cost: +10-30 ms per BGE call (Gemini-bound p50 ~20s ⇒ invisible).
    opts.enable_cpu_mem_arena = False
    opts.enable_mem_pattern = False
    try:
        return ort.InferenceSession(
            str(path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
```

- [ ] **Step 4: Run test — must pass**

Run: `python -m pytest tests/unit/quantization/test_arena_off.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Run the existing rerank test suite to confirm no regression**

Run: `python -m pytest tests/unit/quantization tests/unit/rerank -v`
Expected: all pass (existing 1A.x tests still green).

- [ ] **Step 6: Commit**

```bash
git add website/features/rag_pipeline/rerank/cascade.py tests/unit/quantization/test_arena_off.py
git commit -m "perf: disable onnx cpu mem arena and pattern"
```

---

## Phase 3 — RAG_FP32_VERIFY=off in deploy STATIC_BODY (~10 min)

### Task 3.1: Add the env line to the workflow

**Files:**
- Modify: `.github/workflows/deploy-droplet.yml` (around line 218 — the STATIC_BODY block)
- Test: `tests/unit/website/test_static_body_has_fp32_off.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/website/test_static_body_has_fp32_off.py`:

```python
"""Iter-03 mem-bounded §2.4: RAG_FP32_VERIFY=off must be in the deploy
workflow's STATIC_BODY so apply_migrations + the running container both see
the env disabled. Re-enabling fp32 is a documented LAST-RESORT operation —
the steady-state default is OFF.
"""
from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-droplet.yml"


def test_static_body_contains_rag_fp32_verify_off():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"RAG_FP32_VERIFY=off"' in text, (
        "STATIC_BODY in deploy-droplet.yml must include RAG_FP32_VERIFY=off "
        "between REDDIT_OPTIONAL=1 and DEPLOY_GIT_SHA. See spec §2.4."
    )


def test_static_body_position_is_after_reddit_optional_before_deploy_git_sha():
    text = WORKFLOW.read_text(encoding="utf-8")
    fp32_idx = text.index('"RAG_FP32_VERIFY=off"')
    reddit_idx = text.index('"REDDIT_OPTIONAL=1"')
    deploy_sha_idx = text.index('"DEPLOY_GIT_SHA=${DEPLOY_GIT_SHA}"')
    assert reddit_idx < fp32_idx < deploy_sha_idx, (
        "RAG_FP32_VERIFY=off must sit between REDDIT_OPTIONAL=1 and "
        "DEPLOY_GIT_SHA=... so the STATIC_BODY block stays grouped."
    )
```

- [ ] **Step 2: Run test — must fail**

Run: `python -m pytest tests/unit/website/test_static_body_has_fp32_off.py -v`
Expected: FAILED.

- [ ] **Step 3: Edit `.github/workflows/deploy-droplet.yml`**

Current STATIC_BODY block (lines 213-224):

```yaml
          STATIC_BODY=$(printf '%s\n' \
            "WEBHOOK_MODE=true" \
            "WEBHOOK_PORT=10000" \
            "WEBHOOK_URL=https://${TARGET_HOST}" \
            "NEXUS_ENABLED=true" \
            "REDDIT_OPTIONAL=1" \
            "DEPLOY_GIT_SHA=${DEPLOY_GIT_SHA}" \
            "DEPLOY_ID=${DEPLOY_ID}" \
            "DEPLOY_ACTOR=${DEPLOY_ACTOR}" \
            "GUNICORN_WORKERS=2" \
            "GUNICORN_TIMEOUT=240" \
            "GUNICORN_GRACEFUL_TIMEOUT=90")
```

Replace exactly with (single new line `"RAG_FP32_VERIFY=off" \` inserted between `"REDDIT_OPTIONAL=1" \` and `"DEPLOY_GIT_SHA=…" \`):

```yaml
          STATIC_BODY=$(printf '%s\n' \
            "WEBHOOK_MODE=true" \
            "WEBHOOK_PORT=10000" \
            "WEBHOOK_URL=https://${TARGET_HOST}" \
            "NEXUS_ENABLED=true" \
            "REDDIT_OPTIONAL=1" \
            "RAG_FP32_VERIFY=off" \
            "DEPLOY_GIT_SHA=${DEPLOY_GIT_SHA}" \
            "DEPLOY_ID=${DEPLOY_ID}" \
            "DEPLOY_ACTOR=${DEPLOY_ACTOR}" \
            "GUNICORN_WORKERS=2" \
            "GUNICORN_TIMEOUT=240" \
            "GUNICORN_GRACEFUL_TIMEOUT=90")
```

**Note on in-code default**: `website/features/rag_pipeline/rerank/cascade.py:41` has `FP32_VERIFY_ENABLED = os.environ.get("RAG_FP32_VERIFY", "on").lower() == "on"`. The deploy workflow env is the authoritative gate; do NOT flip the in-code default. The workflow always emits `RAG_FP32_VERIFY=off` after this change so prod sees off; the `"on"` literal in code is harmless (only matters in dev where the env var is unset).

- [ ] **Step 4: Lint workflow yaml**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-droplet.yml')); print('yaml OK')"`
Expected: `yaml OK`.

- [ ] **Step 5: Run the test — must pass**

Run: `python -m pytest tests/unit/website/test_static_body_has_fp32_off.py -v`
Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/deploy-droplet.yml tests/unit/website/test_static_body_has_fp32_off.py
git commit -m "ops: default RAG_FP32_VERIFY off in deploy"
```

---

## Phase 4 — FlashRank module-level preload (cascade.py) (~30 min)

### Task 4.1: Hoist `Ranker` to module-level singleton + rewrite `_get_stage1_ranker`

**Files:**
- Modify: `website/features/rag_pipeline/rerank/cascade.py` (multiple regions)
- Test: `tests/unit/rerank/test_flashrank_preload.py` (new)

- [ ] **Step 1: Read existing context**

Run: `grep -n '_STAGE1_RANKER\|_get_stage1_ranker\|_FLASHRANK\|class CascadeReranker\|self\._stage1\b' website/features/rag_pipeline/rerank/cascade.py`
Expected: shows the lazy-load path at `_get_stage1_ranker` and `self._stage1: Ranker | None` (no module-level singleton today).

- [ ] **Step 2: Write the failing test**

Create `tests/unit/rerank/test_flashrank_preload.py`:

```python
"""Iter-03 mem-bounded §2.5: FlashRank Ranker is built at module import so
gunicorn --preload + fork lets workers inherit the ~80 MB model via COW
instead of paying it private per-worker.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from website.features.rag_pipeline.rerank import cascade


def test_module_level_singleton_attribute_exists():
    assert hasattr(cascade, "_STAGE1_RANKER"), (
        "cascade.py must expose _STAGE1_RANKER at module scope (built at "
        "import) — see spec §2.5."
    )


def test_get_stage1_ranker_returns_module_singleton_when_present():
    fake_ranker = object()
    reranker = cascade.CascadeReranker(model_dir=None)
    with patch.object(cascade, "_STAGE1_RANKER", fake_ranker):
        result = reranker._get_stage1_ranker()
    assert result is fake_ranker, (
        "When the module-level singleton is loaded, _get_stage1_ranker MUST "
        "return it — not lazy-build a per-instance copy."
    )


def test_get_stage1_ranker_falls_back_when_singleton_missing(monkeypatch):
    """When _STAGE1_RANKER is None (test / smoke env without model files), the
    legacy per-instance lazy build path must still work so existing tests pass.
    """
    monkeypatch.setattr(cascade, "_STAGE1_RANKER", None)
    reranker = cascade.CascadeReranker(model_dir=None)
    fake_per_instance = object()

    def _fake_ranker_ctor(*args, **kwargs):
        return fake_per_instance

    with patch.object(cascade, "Ranker", _fake_ranker_ctor):
        result = reranker._get_stage1_ranker()

    assert result is fake_per_instance


def test_build_flashrank_ranker_returns_none_on_failure(tmp_path):
    # Force the helper to raise inside; the helper must swallow + return None
    # so import-time failures do NOT crash the whole app.
    def _explode(*_args, **_kwargs):
        raise RuntimeError("simulated cache-dir failure")

    with patch.object(cascade, "ModelManager", _explode):
        result = cascade._build_flashrank_ranker(tmp_path)
    assert result is None
```

- [ ] **Step 3: Run test — must fail**

Run: `python -m pytest tests/unit/rerank/test_flashrank_preload.py -v`
Expected: FAILED on the first test (no `_STAGE1_RANKER` attribute).

- [ ] **Step 4: Add the module-level helper + singleton in `cascade.py`**

Verify imports are already in place — `from website.features.rag_pipeline.rerank.model_manager import FLASHRANK_MODEL_NAME, ModelManager` already exists at line 28; `Ranker` already imported at line 24; `Path` from line 21. Use those — do **not** redefine `FLASHRANK_MODEL_NAME` locally.

Verify `_logger` exists: run `grep -nE 'import logging|^_logger' website/features/rag_pipeline/rerank/cascade.py`. If `_logger` is not defined at module level, add `_logger = logging.getLogger(__name__)` right after the existing imports.

Locate the block immediately after the `_FP32_VERIFY_SESSION` assignment (around line 67-69 — search for `_FP32_VERIFY_SESSION:`). Insert this block immediately after it, before the `_load_json` helper:

```python
# iter-03 mem-bounded §2.5: hoist FlashRank to module-level so gunicorn
# --preload shares it via COW. The lazy per-instance path stays as a fallback
# for tests where the model file is absent.
_DEFAULT_FLASHRANK_DIR = _REPO_ROOT / "models"


def _build_flashrank_ranker(model_dir: Path) -> Ranker | None:
    """Build the FlashRank stage-1 ranker eagerly so it COW-shares post-fork.

    Filesystem side effects (model download into ``model_dir``) MUST happen
    pre-fork — we trigger them via ``ModelManager.ensure_flashrank_model()``
    here at import time so the cache directory is populated and forked
    workers do not race for the file.

    Returns ``None`` on any failure so import-time problems degrade to the
    legacy lazy path rather than crashing the whole app.
    """
    try:
        ModelManager(str(model_dir)).ensure_flashrank_model()
        return Ranker(model_name=FLASHRANK_MODEL_NAME, cache_dir=str(model_dir))
    except Exception as exc:  # pragma: no cover - bootstrap fault is logged
        _logger.warning("failed to preload FlashRank ranker: %s", exc)
        return None


_STAGE1_RANKER: Ranker | None = _build_flashrank_ranker(_DEFAULT_FLASHRANK_DIR)
```

- [ ] **Step 5: Rewrite `CascadeReranker._get_stage1_ranker` to consult the singleton first**

Locate the existing method (search for `def _get_stage1_ranker`). Replace its body with:

```python
    def _get_stage1_ranker(self) -> Ranker:
        # Production path: the module-level singleton was preloaded in master
        # under gunicorn --preload, so workers inherit it via COW. Return it
        # directly without locking — the singleton is read-only after import.
        if _STAGE1_RANKER is not None:
            return _STAGE1_RANKER
        # Test / smoke fallback: legacy per-instance lazy build retained so
        # tests that patch model_dir keep working. Preserve the existing
        # ensure_flashrank_model() download trigger so the file is on disk.
        with self._stage1_lock:
            if self._stage1 is None:
                self._model_manager.ensure_flashrank_model()
                self._stage1 = Ranker(
                    model_name=FLASHRANK_MODEL_NAME,
                    cache_dir=str(self._model_manager.model_dir),
                )
            return self._stage1
```

- [ ] **Step 6: Run test — must pass**

Run: `python -m pytest tests/unit/rerank/test_flashrank_preload.py -v`
Expected: `4 passed`.

- [ ] **Step 7: Run wider test suite**

Run: `python -m pytest tests/unit/rerank tests/unit/quantization tests/unit/rag -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add website/features/rag_pipeline/rerank/cascade.py tests/unit/rerank/test_flashrank_preload.py
git commit -m "perf: preload flashrank ranker module level cow"
```

---

## Phase 5 — LRU-bounded embedder query cache (~20 min)

### Task 5.1: Replace unbounded dict with `cachetools.LRUCache`

**Files:**
- Modify: `website/features/rag_pipeline/ingest/embedder.py` (lines 1-25 — top of file + `__init__`)
- Test: `tests/unit/rag/test_query_cache_lru.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/rag/test_query_cache_lru.py`:

```python
"""Iter-03 mem-bounded §2.6: ChunkEmbedder._query_cache must be a bounded
LRU. Default cap 256 entries × ~6 KB = ~1.5 MB. Env override
RAG_QUERY_CACHE_MAX honored at construction time.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from cachetools import LRUCache

from website.features.rag_pipeline.ingest.embedder import ChunkEmbedder


def _new_embedder(**kwargs) -> ChunkEmbedder:
    pool = AsyncMock()
    return ChunkEmbedder(pool=pool, **kwargs)


def test_query_cache_is_lru_with_default_256(monkeypatch):
    monkeypatch.delenv("RAG_QUERY_CACHE_MAX", raising=False)
    e = _new_embedder()
    assert isinstance(e._query_cache, LRUCache)
    assert e._query_cache.maxsize == 256


def test_query_cache_honors_env_override(monkeypatch):
    monkeypatch.setenv("RAG_QUERY_CACHE_MAX", "32")
    e = _new_embedder()
    assert e._query_cache.maxsize == 32


def test_query_cache_evicts_oldest_when_full(monkeypatch):
    monkeypatch.setenv("RAG_QUERY_CACHE_MAX", "3")
    e = _new_embedder()
    # Pretend three queries already cached
    e._query_cache["a"] = [0.1]
    e._query_cache["b"] = [0.2]
    e._query_cache["c"] = [0.3]
    # Inserting a 4th must evict the LRU entry (a)
    e._query_cache["d"] = [0.4]
    assert "a" not in e._query_cache
    assert "d" in e._query_cache
    assert len(e._query_cache) == 3
```

- [ ] **Step 2: Run test — must fail**

Run: `python -m pytest tests/unit/rag/test_query_cache_lru.py -v`
Expected: FAILED on `isinstance(e._query_cache, LRUCache)` — current type is `dict`.

- [ ] **Step 3: Edit `website/features/rag_pipeline/ingest/embedder.py`**

At the top of the file, after the existing imports, add:

```python
import os
from cachetools import LRUCache
```

Replace the line in `__init__` (line 25 today):

```python
        self._query_cache: dict[str, list[float]] = {}
```

with:

```python
        # iter-03 mem-bounded §2.6: bounded LRU caps slow linear leak. Default
        # 256 entries × ~6 KB ≈ 1.5 MB. Override via RAG_QUERY_CACHE_MAX.
        self._query_cache: LRUCache[str, list[float]] = LRUCache(
            maxsize=int(os.environ.get("RAG_QUERY_CACHE_MAX", "256")),
        )
```

- [ ] **Step 4: Run test — must pass**

Run: `python -m pytest tests/unit/rag/test_query_cache_lru.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Run the embedder + ingest tests to confirm no regression**

Run: `python -m pytest tests/unit/rag -v -k "embed or ingest"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add website/features/rag_pipeline/ingest/embedder.py tests/unit/rag/test_query_cache_lru.py
git commit -m "perf: bound embedder query cache lru 256"
```

---

## Phase 6 — Gunicorn worker recycling (~15 min)

### Task 6.1: Add `--max-requests` + `--max-requests-jitter` flags to `run.py`

**Files:**
- Modify: `run.py` (lines 32-43)
- Test: `tests/unit/website/test_run_py_emits_max_requests.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/website/test_run_py_emits_max_requests.py`:

```python
"""Iter-03 mem-bounded §2.7: gunicorn must run with --max-requests 100 and
--max-requests-jitter 20 by default so workers recycle every ~100 requests.
With FlashRank now COW-shared (§2.5), recycle is ~10-50ms — invisible.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

import run as run_module


def test_run_py_emits_max_requests_in_argv(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("GUNICORN_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("GUNICORN_MAX_REQUESTS_JITTER", raising=False)
    captured: list[list[str]] = []

    def _fake_call(cmd):
        captured.append(cmd)
        return 0

    with patch.object(run_module.subprocess, "call", _fake_call):
        rc = run_module.main()
    assert rc == 0
    assert len(captured) == 1
    cmd = captured[0]
    assert "--max-requests" in cmd
    idx = cmd.index("--max-requests")
    assert cmd[idx + 1] == "100"
    assert "--max-requests-jitter" in cmd
    jdx = cmd.index("--max-requests-jitter")
    assert cmd[jdx + 1] == "20"


def test_run_py_honors_env_override(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("GUNICORN_MAX_REQUESTS", "250")
    monkeypatch.setenv("GUNICORN_MAX_REQUESTS_JITTER", "50")
    captured: list[list[str]] = []
    with patch.object(run_module.subprocess, "call", lambda c: captured.append(c) or 0):
        run_module.main()
    cmd = captured[0]
    assert cmd[cmd.index("--max-requests") + 1] == "250"
    assert cmd[cmd.index("--max-requests-jitter") + 1] == "50"
```

- [ ] **Step 2: Run test — must fail**

Run: `python -m pytest tests/unit/website/test_run_py_emits_max_requests.py -v`
Expected: FAILED — flags absent.

- [ ] **Step 3: Edit `run.py`**

Current `run.py:32-42`:

```python
    cmd = [
        "gunicorn",
        "-k", "uvicorn.workers.UvicornWorker",
        "-w", os.environ.get("GUNICORN_WORKERS", "2"),
        "--preload",
        "--bind", f"0.0.0.0:{os.environ.get('PORT', os.environ.get('WEBHOOK_PORT', '10000'))}",
        "--timeout", os.environ.get("GUNICORN_TIMEOUT", "90"),
        "--graceful-timeout", os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "60"),
        "--keep-alive", os.environ.get("GUNICORN_KEEPALIVE", "5"),
        "website.main:app",
    ]
```

Replace exactly that block with (only adds two lines for `--max-requests` flags — leaves all existing in-code defaults `90` / `60` unchanged because the deploy workflow env already sets `GUNICORN_TIMEOUT=240` / `GUNICORN_GRACEFUL_TIMEOUT=90`, which wins at runtime):

```python
    cmd = [
        "gunicorn",
        "-k", "uvicorn.workers.UvicornWorker",
        "-w", os.environ.get("GUNICORN_WORKERS", "2"),
        "--preload",
        "--bind", f"0.0.0.0:{os.environ.get('PORT', os.environ.get('WEBHOOK_PORT', '10000'))}",
        "--timeout", os.environ.get("GUNICORN_TIMEOUT", "90"),
        "--graceful-timeout", os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "60"),
        "--keep-alive", os.environ.get("GUNICORN_KEEPALIVE", "5"),
        # iter-03 mem-bounded §2.7: recycle workers every ~100 requests to
        # bound drift from leaky deps (psycopg pool, google-genai HTTP buffers).
        # With FlashRank in master COW (§2.5), restart cost is ~10-50ms only.
        "--max-requests", os.environ.get("GUNICORN_MAX_REQUESTS", "100"),
        "--max-requests-jitter", os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "20"),
        "website.main:app",
    ]
```

- [ ] **Step 4: Run test — must pass**

Run: `python -m pytest tests/unit/website/test_run_py_emits_max_requests.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add run.py tests/unit/website/test_run_py_emits_max_requests.py
git commit -m "ops: gunicorn max requests 100 jitter 20"
```

---

## Phase 7 — RSS+CPU+load instrumentation (~60 min)

### Task 7.1: New helper module `website/api/_proc_stats.py`

**Files:**
- Create: `website/api/_proc_stats.py`
- Test: `tests/unit/api/test_proc_stats_helper.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_proc_stats_helper.py`:

```python
"""Iter-03 mem-bounded §2.8: _proc_stats helper reads /proc/self/status,
/proc/loadavg, and /sys/fs/cgroup/memory.{max,current,swap.current,swap.max}
and returns a flat JSON-able dict.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from website.api import _proc_stats


def _write(p: Path, body: str) -> None:
    p.write_text(body, encoding="utf-8")


def test_read_proc_stats_shape(tmp_path: Path):
    # Build a fake /proc + /sys layout
    proc = tmp_path / "proc"
    sys_cg = tmp_path / "cgroup"
    proc.mkdir()
    sys_cg.mkdir()
    _write(proc / "status", "VmRSS:\t  524288 kB\nVmSize:\t1048576 kB\nVmSwap:\t   2048 kB\nThreads:\t   16\n")
    _write(proc / "loadavg", "0.18 0.22 0.30 1/123 4567")
    _write(sys_cg / "memory.max", "1363148800\n")
    _write(sys_cg / "memory.current", "523648000\n")
    _write(sys_cg / "memory.swap.max", "1048576000\n")
    _write(sys_cg / "memory.swap.current", "18432000\n")

    with patch.object(_proc_stats, "_PROC_STATUS", proc / "status"), \
         patch.object(_proc_stats, "_PROC_LOADAVG", proc / "loadavg"), \
         patch.object(_proc_stats, "_CGROUP_MEM_MAX", sys_cg / "memory.max"), \
         patch.object(_proc_stats, "_CGROUP_MEM_CURRENT", sys_cg / "memory.current"), \
         patch.object(_proc_stats, "_CGROUP_SWAP_MAX", sys_cg / "memory.swap.max"), \
         patch.object(_proc_stats, "_CGROUP_SWAP_CURRENT", sys_cg / "memory.swap.current"):
        out = _proc_stats.read_proc_stats()

    assert out["vm_rss_kb"] == 524288
    assert out["vm_size_kb"] == 1048576
    assert out["vm_swap_kb"] == 2048
    assert out["num_threads"] == 16
    assert out["load_1m"] == pytest.approx(0.18)
    assert out["load_5m"] == pytest.approx(0.22)
    assert out["load_15m"] == pytest.approx(0.30)
    assert out["cgroup_mem_max"] == 1363148800
    assert out["cgroup_mem_current"] == 523648000
    assert out["cgroup_swap_max"] == 1048576000
    assert out["cgroup_swap_current"] == 18432000


def test_read_proc_stats_missing_files_yields_none(tmp_path: Path):
    nope = tmp_path / "nope"  # doesn't exist
    with patch.object(_proc_stats, "_PROC_STATUS", nope), \
         patch.object(_proc_stats, "_PROC_LOADAVG", nope), \
         patch.object(_proc_stats, "_CGROUP_MEM_MAX", nope), \
         patch.object(_proc_stats, "_CGROUP_MEM_CURRENT", nope), \
         patch.object(_proc_stats, "_CGROUP_SWAP_MAX", nope), \
         patch.object(_proc_stats, "_CGROUP_SWAP_CURRENT", nope):
        out = _proc_stats.read_proc_stats()
    assert out["vm_rss_kb"] is None
    assert out["cgroup_mem_max"] is None


def test_log_line_format():
    sample = {
        "vm_rss_kb": 524288, "vm_swap_kb": 18240, "vm_size_kb": 1048576,
        "num_threads": 16,
        "load_1m": 0.18, "load_5m": 0.22, "load_15m": 0.30,
        "cgroup_mem_current": 523648000, "cgroup_mem_max": 1363148800,
        "cgroup_swap_current": 18432000, "cgroup_swap_max": 1048576000,
    }
    line = _proc_stats.format_log_line(sample)
    # Single line, key=value pairs, fields the spec calls out are present
    for key in ("vm_rss_kb", "vm_swap_kb", "load_1m", "cgroup_mem_current",
                "cgroup_mem_max", "cgroup_swap_current", "cgroup_swap_max"):
        assert f"{key}=" in line
    assert "\n" not in line
```

- [ ] **Step 2: Run test — must fail**

Run: `python -m pytest tests/unit/api/test_proc_stats_helper.py -v`
Expected: ImportError on `website.api._proc_stats`.

- [ ] **Step 3: Implement `website/api/_proc_stats.py`**

```python
"""Reader for /proc + cgroup memory stats. iter-03 mem-bounded §2.8.

Single-shot helper; no caching. Expected per-call cost ~50-80 µs (six file
reads in /proc and /sys/fs/cgroup, all small). Both the on-demand admin
endpoint and the periodic logger task call ``read_proc_stats``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("website.api._proc_stats")

# Override-able module-level paths so tests can point at a fake /proc layout.
_PROC_STATUS = Path("/proc/self/status")
_PROC_LOADAVG = Path("/proc/loadavg")
_CGROUP_MEM_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_MEM_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_SWAP_MAX = Path("/sys/fs/cgroup/memory.swap.max")
_CGROUP_SWAP_CURRENT = Path("/sys/fs/cgroup/memory.swap.current")

# cgroup v1 fallback paths (used in older kernels / dev environments).
_CGROUP_V1_MEM_MAX = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_CGROUP_V1_MEM_CURRENT = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")


def _read_int(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return None
    if raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_proc_status(path: Path) -> dict[str, int | None]:
    out: dict[str, int | None] = {
        "vm_rss_kb": None, "vm_size_kb": None, "vm_swap_kb": None,
        "num_threads": None,
    }
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return out
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            out["vm_rss_kb"] = int(line.split()[1])
        elif line.startswith("VmSize:"):
            out["vm_size_kb"] = int(line.split()[1])
        elif line.startswith("VmSwap:"):
            out["vm_swap_kb"] = int(line.split()[1])
        elif line.startswith("Threads:"):
            out["num_threads"] = int(line.split()[1])
    return out


def _parse_loadavg(path: Path) -> dict[str, float | None]:
    try:
        parts = path.read_text(encoding="utf-8").split()
    except (OSError, FileNotFoundError):
        return {"load_1m": None, "load_5m": None, "load_15m": None}
    if len(parts) < 3:
        return {"load_1m": None, "load_5m": None, "load_15m": None}
    return {
        "load_1m": float(parts[0]),
        "load_5m": float(parts[1]),
        "load_15m": float(parts[2]),
    }


def _read_cgroup_mem() -> dict[str, int | None]:
    # Prefer cgroup v2; fall through to v1.
    out: dict[str, int | None] = {
        "cgroup_mem_max": _read_int(_CGROUP_MEM_MAX),
        "cgroup_mem_current": _read_int(_CGROUP_MEM_CURRENT),
        "cgroup_swap_max": _read_int(_CGROUP_SWAP_MAX),
        "cgroup_swap_current": _read_int(_CGROUP_SWAP_CURRENT),
    }
    if out["cgroup_mem_max"] is None:
        out["cgroup_mem_max"] = _read_int(_CGROUP_V1_MEM_MAX)
    if out["cgroup_mem_current"] is None:
        out["cgroup_mem_current"] = _read_int(_CGROUP_V1_MEM_CURRENT)
    return out


def read_proc_stats() -> dict[str, Any]:
    """Return a flat dict of all the stats. Missing values are ``None``."""
    out: dict[str, Any] = {}
    out.update(_parse_proc_status(_PROC_STATUS))
    out.update(_parse_loadavg(_PROC_LOADAVG))
    out.update(_read_cgroup_mem())
    return out


def format_log_line(stats: dict[str, Any]) -> str:
    """Render one-line ``[proc_stats] key=val key=val ...`` for the periodic
    logger. Stable field order so log greppers can rely on it."""
    fields = [
        "vm_rss_kb", "vm_swap_kb", "vm_size_kb", "num_threads",
        "load_1m", "load_5m", "load_15m",
        "cgroup_mem_current", "cgroup_mem_max",
        "cgroup_swap_current", "cgroup_swap_max",
    ]
    parts = [f"{k}={stats.get(k)}" for k in fields]
    return "[proc_stats] " + " ".join(parts)
```

- [ ] **Step 4: Run test — must pass**

Run: `python -m pytest tests/unit/api/test_proc_stats_helper.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add website/api/_proc_stats.py tests/unit/api/test_proc_stats_helper.py
git commit -m "feat: proc stats reader cgroup v2 fallback"
```

### Task 7.2: Admin router with `/api/admin/_proc_stats`

**Files:**
- Create: `website/api/admin_routes.py`
- Modify: `website/app.py` (add `app.include_router(admin_router)` near line 119)
- Test: `tests/unit/api/test_proc_stats.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_proc_stats.py`:

```python
"""Iter-03 mem-bounded §2.8: GET /api/admin/_proc_stats returns proc stats.

Auth-gated against the single-tenant allowlist at ops/deploy/expected_users.json.
Non-allowlisted users get 404 (NOT 403, to avoid leaking the existence of admin
endpoints).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from website.api import admin_routes
from website.app import create_app

NARUTO = "f2105544-b73d-4946-8329-096d82f070d3"
ZORO = "a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e"
RANDO = "11111111-1111-1111-1111-111111111111"


def _client_with_user(user_sub: str | None) -> TestClient:
    app = create_app()
    if user_sub is None:
        return TestClient(app)
    async def _stub_user():
        return {"sub": user_sub, "email": f"{user_sub}@test"}
    from website.api import auth as auth_mod
    app.dependency_overrides[auth_mod.get_current_user] = _stub_user
    return TestClient(app)


def test_admin_proc_stats_returns_json_for_allowlisted_user(monkeypatch):
    fake_stats = {"vm_rss_kb": 100, "vm_swap_kb": 0, "cgroup_mem_max": 1363148800}
    monkeypatch.setattr(admin_routes, "read_proc_stats", lambda: fake_stats)
    client = _client_with_user(NARUTO)
    r = client.get("/api/admin/_proc_stats")
    assert r.status_code == 200
    body = r.json()
    assert body["vm_rss_kb"] == 100


def test_admin_proc_stats_returns_404_for_random_user():
    client = _client_with_user(RANDO)
    r = client.get("/api/admin/_proc_stats")
    assert r.status_code == 404


def test_admin_proc_stats_returns_401_unauthenticated():
    client = _client_with_user(None)
    r = client.get("/api/admin/_proc_stats")
    assert r.status_code == 401
```

- [ ] **Step 2: Run test — must fail**

Run: `python -m pytest tests/unit/api/test_proc_stats.py -v`
Expected: 404 on the route (router not yet mounted).

- [ ] **Step 3: Implement `website/api/admin_routes.py`**

```python
"""Ops-only diagnostic endpoints. iter-03 mem-bounded §2.8.

Mounted at /api/admin/*. Auth gated against the single-tenant allowlist at
ops/deploy/expected_users.json (the file the Phase 2D `kg_users` allowlist
gate also reads). Non-allowlisted users get 404 to avoid leaking the
existence of admin endpoints.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from website.api._proc_stats import read_proc_stats
from website.api.auth import get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin"], include_in_schema=False)

_ALLOWLIST_PATH = (
    Path(__file__).resolve().parents[2] / "ops" / "deploy" / "expected_users.json"
)


def _load_admin_allowlist() -> set[str]:
    try:
        return set(
            json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))["allowed_auth_ids"]
        )
    except Exception:  # noqa: BLE001 — file may be absent in tests/dev
        return set()


def _require_admin(user: dict) -> None:
    allowed = _load_admin_allowlist()
    if not allowed or user.get("sub") not in allowed:
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/_proc_stats")
async def proc_stats(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    _require_admin(user)
    return read_proc_stats()
```

- [ ] **Step 4: Mount the router in `website/app.py`**

In `website/app.py`, add the import line on line 24 (immediately after `from website.features.web_monitor import router as web_monitor_router`). The plan adds two imports total in this region (the second one is added later in Phase 8.2). Define the order now so both phases agree:

```python
# (existing line 23) from website.api.sandbox_routes import router as sandbox_router
# (existing line 24 today) from website.features.web_monitor import router as web_monitor_router

# Phase 7.2 adds this:
from website.api.admin_routes import router as admin_router

# Phase 8.2 will append this AFTER the line above:
# from website.api import _memory_guard
```

Add the include line in `create_app()` immediately after `app.include_router(web_monitor_router)` (currently line 119) so the order in `create_app` becomes: `api_router → engine_v2_router → chat_router → sandbox_router → web_monitor_router → admin_router → (nexus_router conditional)`:

```python
    app.include_router(web_monitor_router)
    app.include_router(admin_router)
```

- [ ] **Step 5: Run test — must pass**

Run: `python -m pytest tests/unit/api/test_proc_stats.py -v`
Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add website/api/admin_routes.py website/app.py tests/unit/api/test_proc_stats.py
git commit -m "feat: admin proc stats endpoint allowlist gated"
```

### Task 7.3: Lifespan-registered periodic logger task

**Files:**
- Modify: `website/main.py` (replace the bare `app = create_app()` with a lifespan-wrapped factory)
- Test: `tests/unit/api/test_lifespan_proc_stats_task.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_lifespan_proc_stats_task.py`:

```python
"""Iter-03 mem-bounded §2.8: a periodic asyncio task logs proc stats every
PROC_STATS_LOG_INTERVAL_SECONDS (default 60). Lifecycle: started in lifespan
startup, cancelled cleanly within 1s on shutdown.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from website import main as main_mod


@pytest.mark.asyncio
async def test_proc_stats_logger_loop_emits_log_line(monkeypatch, caplog):
    monkeypatch.setattr(main_mod, "_proc_stats_interval_seconds", lambda: 0.05)
    monkeypatch.setattr(
        main_mod._proc_stats_module, "read_proc_stats",
        lambda: {"vm_rss_kb": 42, "vm_swap_kb": 0,
                 "vm_size_kb": 100, "num_threads": 4,
                 "load_1m": 0.0, "load_5m": 0.0, "load_15m": 0.0,
                 "cgroup_mem_current": 0, "cgroup_mem_max": 0,
                 "cgroup_swap_current": 0, "cgroup_swap_max": 0},
    )
    caplog.set_level(logging.INFO, logger="website.main")
    task = asyncio.create_task(main_mod._proc_stats_logger_loop())
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    msgs = [r.message for r in caplog.records if "[proc_stats]" in r.message]
    assert msgs, "logger loop must have emitted at least one [proc_stats] line"
    assert "vm_rss_kb=42" in msgs[0]


@pytest.mark.asyncio
async def test_lifespan_starts_and_cancels_task():
    started: list[bool] = []
    stopped: list[bool] = []

    async def _fake_loop():
        started.append(True)
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            stopped.append(True)
            raise

    import contextlib
    @contextlib.asynccontextmanager
    async def _wrap_lifespan(app):
        async with main_mod._lifespan(app, loop_factory=_fake_loop):
            yield

    from fastapi import FastAPI
    fake_app = FastAPI()
    async with _wrap_lifespan(fake_app):
        await asyncio.sleep(0.05)
    assert started == [True]
    assert stopped == [True]
```

- [ ] **Step 2: Run test — must fail**

Run: `python -m pytest tests/unit/api/test_lifespan_proc_stats_task.py -v`
Expected: FAIL — `_proc_stats_logger_loop`, `_proc_stats_interval_seconds`, `_lifespan` not defined.

- [ ] **Step 3: Replace `website/main.py`**

```python
"""Website-only runtime entrypoint.

Boots the FastAPI app. The module-level ``app`` is what gunicorn loads when
``--preload`` runs, so heavy ONNX sessions in :mod:`website.features.rag_pipeline.rerank.cascade`
are imported once in the master and inherited by workers via copy-on-write.

iter-03 mem-bounded §2.8: a lifespan-managed periodic task logs proc stats
every ``PROC_STATS_LOG_INTERVAL_SECONDS`` (default 60) so ops can decide
later whether to re-enable RAG_FP32_VERIFY.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Awaitable, Callable

import uvicorn
from fastapi import FastAPI

from website.api import _proc_stats as _proc_stats_module
from website.app import create_app
from website.core.settings import get_settings

logger = logging.getLogger("website.main")


def _proc_stats_interval_seconds() -> float:
    try:
        return float(os.environ.get("PROC_STATS_LOG_INTERVAL_SECONDS", "60"))
    except ValueError:
        return 60.0


async def _proc_stats_logger_loop() -> None:
    """Emit one line per interval. Loop exits cleanly on cancellation."""
    interval = _proc_stats_interval_seconds()
    while True:
        try:
            stats = _proc_stats_module.read_proc_stats()
            logger.info(_proc_stats_module.format_log_line(stats))
        except Exception:  # noqa: BLE001 — never let the logger kill the worker
            logger.exception("proc_stats logger iteration failed")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return


@contextlib.asynccontextmanager
async def _lifespan(
    _app: FastAPI,
    *,
    loop_factory: Callable[[], Awaitable[None]] = _proc_stats_logger_loop,
):
    task = asyncio.create_task(loop_factory())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# Module-level ASGI app. gunicorn imports ``website.main:app`` with --preload.
app = create_app(lifespan=_lifespan)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    port = settings.webhook_port or 10000
    logger.info("Starting Zettelkasten website on 0.0.0.0:%d (uvicorn dev mode)", port)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test — must pass**

Run: `python -m pytest tests/unit/api/test_lifespan_proc_stats_task.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Run wider test suite to catch any startup regression**

Run: `python -m pytest tests/unit/api tests/unit/website -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add website/main.py tests/unit/api/test_lifespan_proc_stats_task.py
git commit -m "feat: periodic proc stats logger lifespan"
```

---

## Phase 8 — Soft RSS-guard middleware (~45 min)

### Task 8.1: New module `website/api/_memory_guard.py`

**Files:**
- Create: `website/api/_memory_guard.py`
- Test: `tests/unit/api/test_memory_guard.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_memory_guard.py`:

```python
"""Iter-03 mem-bounded §2.9: soft RSS-guard middleware returns 503 with
Retry-After when VmRSS exceeds the threshold (default 90% of cgroup mem_max).

Threshold detection: cgroup v2 → v1 → /proc/meminfo fallback.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.api import _memory_guard


def _app_with_guard(threshold_percent: int | None = None) -> FastAPI:
    app = FastAPI()
    if threshold_percent is not None:
        with patch.dict(__import__("os").environ,
                        {"RAG_MEMORY_GUARD_THRESHOLD_PERCENT": str(threshold_percent)}):
            _memory_guard.install(app)
    else:
        _memory_guard.install(app)

    @app.get("/echo")
    async def _echo():
        return {"ok": True}

    @app.get("/api/health")
    async def _health():
        return {"status": "ok"}

    return app


def test_below_threshold_passes_through(monkeypatch):
    monkeypatch.setattr(_memory_guard, "_detect_mem_max", lambda: 1_000_000_000)
    monkeypatch.setattr(_memory_guard, "_read_vm_rss_bytes", lambda: 100_000_000)
    app = _app_with_guard(threshold_percent=90)
    client = TestClient(app)
    r = client.get("/echo")
    assert r.status_code == 200


def test_above_threshold_returns_503_with_retry_after(monkeypatch):
    monkeypatch.setattr(_memory_guard, "_detect_mem_max", lambda: 1_000_000_000)
    monkeypatch.setattr(_memory_guard, "_read_vm_rss_bytes", lambda: 950_000_000)
    app = _app_with_guard(threshold_percent=90)
    client = TestClient(app)
    r = client.get("/echo")
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "5"
    body = r.json()
    assert body["error"] == "server_under_memory_pressure"


def test_threshold_zero_disables_guard(monkeypatch):
    monkeypatch.setattr(_memory_guard, "_detect_mem_max", lambda: 1_000_000_000)
    monkeypatch.setattr(_memory_guard, "_read_vm_rss_bytes", lambda: 999_999_999)
    app = _app_with_guard(threshold_percent=0)
    client = TestClient(app)
    r = client.get("/echo")
    assert r.status_code == 200


def test_detect_mem_max_cgroup_v2(tmp_path: Path, monkeypatch):
    p = tmp_path / "memory.max"
    p.write_text("1363148800\n", encoding="utf-8")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V2_MEM_MAX", p)
    monkeypatch.setattr(_memory_guard, "_CGROUP_V1_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_PROC_MEMINFO", tmp_path / "missing")
    assert _memory_guard._detect_mem_max() == 1363148800


def test_detect_mem_max_falls_back_to_v1(tmp_path: Path, monkeypatch):
    p = tmp_path / "limit_in_bytes"
    p.write_text("1024000000\n", encoding="utf-8")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V2_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V1_MEM_MAX", p)
    monkeypatch.setattr(_memory_guard, "_PROC_MEMINFO", tmp_path / "missing")
    assert _memory_guard._detect_mem_max() == 1024000000


def test_detect_mem_max_falls_back_to_proc_meminfo(tmp_path: Path, monkeypatch):
    mi = tmp_path / "meminfo"
    mi.write_text("MemTotal:    1992928 kB\nMemFree:      324616 kB\n", encoding="utf-8")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V2_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V1_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_PROC_MEMINFO", mi)
    assert _memory_guard._detect_mem_max() == 1992928 * 1024


def test_detect_mem_max_handles_max_string(tmp_path: Path, monkeypatch):
    p = tmp_path / "memory.max"
    p.write_text("max\n", encoding="utf-8")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V2_MEM_MAX", p)
    monkeypatch.setattr(_memory_guard, "_CGROUP_V1_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_PROC_MEMINFO", tmp_path / "missing")
    # No bound found anywhere → returns 0 → guard self-disables.
    assert _memory_guard._detect_mem_max() == 0
```

- [ ] **Step 2: Run test — must fail**

Run: `python -m pytest tests/unit/api/test_memory_guard.py -v`
Expected: ImportError on `_memory_guard`.

- [ ] **Step 3: Implement `website/api/_memory_guard.py`**

```python
"""Soft RSS-guard middleware. iter-03 mem-bounded §2.9.

Reads /proc/self/status before dispatching every request. When VmRSS exceeds
``RAG_MEMORY_GUARD_THRESHOLD_PERCENT`` of the cgroup memory limit, returns
503 with Retry-After=5 instead of letting the kernel cgroup-OOM the worker
mid-request (which would surface as a 502 from Caddy).

Path exemptions: /api/health, /api/admin/*, /telegram/webhook, /favicon.*.
These probes/ops paths must always work, even under pressure.

Set RAG_MEMORY_GUARD_THRESHOLD_PERCENT=0 to disable entirely (tests/dev).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("website.api._memory_guard")

_CGROUP_V2_MEM_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V1_MEM_MAX = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_STATUS = Path("/proc/self/status")

_EXEMPT_PREFIXES = (
    "/api/health",
    "/api/admin/",
    "/telegram/webhook",
    "/favicon.ico",
    "/favicon.svg",
)

_DEFAULT_THRESHOLD_PERCENT = 90


def _detect_mem_max() -> int:
    """Return the cgroup memory limit in bytes, falling back to MemTotal."""
    for p in (_CGROUP_V2_MEM_MAX, _CGROUP_V1_MEM_MAX):
        try:
            raw = p.read_text(encoding="utf-8").strip()
        except (OSError, FileNotFoundError):
            continue
        if raw == "max":
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    try:
        for line in _PROC_MEMINFO.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, FileNotFoundError):
        pass
    return 0


def _read_vm_rss_bytes() -> int:
    try:
        for line in _PROC_STATUS.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, FileNotFoundError):
        pass
    return 0


def _threshold_percent() -> int:
    raw = os.environ.get("RAG_MEMORY_GUARD_THRESHOLD_PERCENT")
    if raw is None:
        return _DEFAULT_THRESHOLD_PERCENT
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_THRESHOLD_PERCENT


def install(app: FastAPI) -> None:
    """Register the middleware on ``app``."""

    @app.middleware("http")
    async def _memory_guard_middleware(request: Request, call_next):
        threshold = _threshold_percent()
        if threshold <= 0:
            return await call_next(request)
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)
        mem_max = _detect_mem_max()
        if mem_max <= 0:
            # Cannot determine bound — guard self-disables to avoid blocking prod.
            return await call_next(request)
        rss = _read_vm_rss_bytes()
        if rss <= 0:
            return await call_next(request)
        if rss * 100 >= mem_max * threshold:
            logger.warning(
                "memory pressure shedding: rss=%d mem_max=%d threshold_pct=%d path=%s",
                rss, mem_max, threshold, path,
            )
            return JSONResponse(
                {"error": "server_under_memory_pressure", "retry_after_seconds": 5},
                status_code=503,
                headers={"Retry-After": "5"},
            )
        return await call_next(request)
```

- [ ] **Step 4: Run test — must pass**

Run: `python -m pytest tests/unit/api/test_memory_guard.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add website/api/_memory_guard.py tests/unit/api/test_memory_guard.py
git commit -m "feat: soft rss guard middleware 503 retry"
```

### Task 8.2: Wire the middleware into the app + path-exemption test

**Files:**
- Modify: `website/app.py` (add `_memory_guard.install(app)` near line 119)
- Test: `tests/unit/api/test_memory_guard_exempts_health.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_memory_guard_exempts_health.py`:

```python
"""Iter-03 mem-bounded §2.9: middleware MUST NOT shed exempt paths even when
VmRSS is over the threshold. Exempt prefixes: /api/health, /api/admin/,
/telegram/webhook, /favicon.ico, /favicon.svg.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from website.api import _memory_guard
from website.app import create_app


@pytest.fixture
def under_pressure_app(monkeypatch):
    monkeypatch.setattr(_memory_guard, "_detect_mem_max", lambda: 1_000_000_000)
    monkeypatch.setattr(_memory_guard, "_read_vm_rss_bytes", lambda: 950_000_000)
    monkeypatch.setenv("RAG_MEMORY_GUARD_THRESHOLD_PERCENT", "90")
    return create_app()


def test_health_passes_through_under_pressure(under_pressure_app):
    client = TestClient(under_pressure_app)
    r = client.get("/api/health")
    assert r.status_code == 200


def test_favicon_ico_passes_through_under_pressure(under_pressure_app):
    client = TestClient(under_pressure_app)
    r = client.get("/favicon.ico")
    assert r.status_code in (200, 304)


def test_favicon_svg_passes_through_under_pressure(under_pressure_app):
    client = TestClient(under_pressure_app)
    r = client.get("/favicon.svg")
    assert r.status_code in (200, 304)


def test_admin_proc_stats_path_passes_through_under_pressure(under_pressure_app):
    client = TestClient(under_pressure_app)
    # Unauthenticated → 401 from auth dependency BEFORE the guard could 503.
    # The point: NOT 503. /api/admin/* prefix is exempt regardless of auth.
    r = client.get("/api/admin/_proc_stats")
    assert r.status_code != 503


def test_telegram_webhook_path_passes_through_under_pressure(under_pressure_app):
    client = TestClient(under_pressure_app)
    # The webhook may not even exist in the FastAPI app in dev (Telegram bot
    # registers it only in webhook mode), so we accept 404 / 405 — what we
    # MUST NOT see is 503.
    r = client.post("/telegram/webhook")
    assert r.status_code != 503
```

- [ ] **Step 2: Run test — must fail**

Run: `python -m pytest tests/unit/api/test_memory_guard_exempts_health.py -v`
Expected: middleware not yet installed in `create_app` — `/api/health` returns 503 OR test passes spuriously because no middleware. Either way, the install line is missing. Confirm by `grep '_memory_guard' website/app.py` returns nothing.

- [ ] **Step 3: Wire the middleware in `website/app.py`**

Add the import line immediately after the `admin_router` import added in Phase 7.2 (so the import region reads `sandbox_router → web_monitor_router → admin_router → _memory_guard`):

```python
from website.api.admin_routes import router as admin_router      # added in Phase 7.2
from website.api import _memory_guard                             # added in Phase 8.2
```

Inside `create_app()`, add `_memory_guard.install(app)` immediately AFTER the last `app.include_router(...)` call (after the conditional `app.include_router(nexus_router)` block — i.e., after the entire router-include block ends). The expected sequence becomes: all `include_router` calls, then `_memory_guard.install(app)`, then any subsequent app setup:

```python
    app.include_router(web_monitor_router)
    app.include_router(admin_router)
    if nexus_enabled:
        app.include_router(nexus_router)
    # iter-03 mem-bounded §2.9: install AFTER routers so middleware wraps every route.
    _memory_guard.install(app)
```

- [ ] **Step 4: Run test — must pass**

Run: `python -m pytest tests/unit/api/test_memory_guard_exempts_health.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Run the broader API test suite to confirm no route regression**

Run: `python -m pytest tests/unit/api -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add website/app.py tests/unit/api/test_memory_guard_exempts_health.py
git commit -m "feat: install rss guard exempt health admin"
```

---

## Phase 9 — Stress harness extension + cgroup detection coverage (~15 min)

### Task 9.1: Extend `tests/stress/test_burst_capacity.py` with cgroup detection sanity

**Files:**
- Modify: `tests/stress/test_burst_capacity.py` (append new test fn)

- [ ] **Step 1: Append the new test**

Append to `tests/stress/test_burst_capacity.py`:

```python
@pytest.mark.asyncio
async def test_memory_guard_detect_mem_max_returns_sane_int():
    """Sanity: _detect_mem_max returns a non-zero int when the harness is
    running on a real host (or test harness with a writable proc). On
    GitHub Actions / Linux this should be > 0; on macOS / Windows hosts
    where /proc + cgroup are absent, it falls back to /proc/meminfo OR 0.
    The point of this test is to ensure the fallback chain doesn't crash."""
    from website.api import _memory_guard
    value = _memory_guard._detect_mem_max()
    assert isinstance(value, int)
    assert value >= 0
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/stress/test_burst_capacity.py -v`
Expected: all (existing 4 + 1 new) pass.

- [ ] **Step 3: Commit**

```bash
git add tests/stress/test_burst_capacity.py
git commit -m "test: stress detect mem max sane int"
```

---

## Phase 10 — Runbook + droplet manual one-shot (~15 min)

### Task 10.1: Update `docs/runbooks/droplet_swapfile.md` to call out the verify-first flow

**Files:**
- Modify: `docs/runbooks/droplet_swapfile.md` (full rewrite)

- [ ] **Step 1: Read current state**

Run: `cat docs/runbooks/droplet_swapfile.md | head -60`
Expected: existing 2 GB swapfile runbook (created in Phase 0.3 of the original iter-03 plan).

- [ ] **Step 2: Rewrite the runbook**

Overwrite `docs/runbooks/droplet_swapfile.md` with:

```markdown
# Droplet Swapfile Provisioning + Verification

**When:** During the iter-03-mem-bounded rollout, after the Docker compose
ceiling change lands but before promoting traffic. Re-run any time the
droplet image is rebuilt or the swap config drifts.

**Why:** The 2 GB DigitalOcean droplet pairs with a 2 GB host swapfile so
the cgroup-confined containers (mem_limit 1300m, memswap_limit 2300m, see
`ops/docker-compose.{blue,green}.yml`) have a 1 GB swap budget per color.
Without this the kernel cgroup-OOM kills gunicorn workers under inference
pressure → Caddy reports 502s.

## Steps (run on droplet via SSH as the deploy user)

```bash
# ── 1. Verify current state first ─────────────────────────────────────
swapon --show
free -h
sysctl vm.swappiness

# Expected: /swapfile  file  2G ...   Swap: 2.0Gi ...   vm.swappiness = 10
# If already correct, SKIP the recreate block below.
```

```bash
# ── 2. Recreate to 2 GB if smaller (idempotent) ───────────────────────
sudo swapoff /swapfile
sudo rm /swapfile
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Persist across reboots (only if not already present)
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Tune for low swappiness — only swap under real OOM pressure
sysctl vm.swappiness  # if not already 10:
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

```bash
# ── 3. Verify cgroup v2 honors the new swap budget ────────────────────
docker exec zettelkasten-blue cat /sys/fs/cgroup/memory.max
# Expect: 1363148800 (~1.3 GB)

docker exec zettelkasten-blue cat /sys/fs/cgroup/memory.swap.max
# Expect: 1048576000 (~1.0 GB swap budget for the cgroup)
```

```bash
# ── 4. Confirm zero extra DigitalOcean cost ───────────────────────────
df -h /                   # confirm /swapfile fits on the 70 GB SSD
# Optional: from a workstation with doctl set up:
#   doctl compute droplet get <DROPLET_ID> --format Name,Size,Memory,VCPUs,PriceMonthly
# Expect: same plan and same price as before. Swap is local SSD storage,
# already billed inside the droplet plan.
```

## Verification

`free -h` shows `Swap: 2.0Gi …`. The blue and green containers report
`memory.swap.max = 1048576000`. No change in droplet plan or monthly bill.

## Rollback

```bash
sudo swapoff /swapfile
sudo sed -i '/swapfile/d' /etc/fstab
sudo rm /swapfile
```

The compose `mem_limit/memswap_limit` settings are still in repo; revert
those separately if needed.
```

- [ ] **Step 3: Commit**

```bash
git add docs/runbooks/droplet_swapfile.md
git commit -m "docs: swapfile runbook verify cgroup budget"
```

---

## Phase 11 — Validation + deploy + post-deploy verification (~60 min)

### Task 11.1: Full local test sweep

**Files:** none (test execution only)

- [ ] **Step 1: Full pytest sweep**

Run: `python -m pytest tests/unit tests/stress -q --tb=line`
Expected: ALL existing + new tests pass; 5 ONNX-bootstrap skips remain expected. New tests added across Phases 2–9 break down as: 2 (Phase 2) + 2 (Phase 3) + 4 (Phase 4) + 3 (Phase 5) + 2 (Phase 6) + 3 (Phase 7.1) + 3 (Phase 7.2) + 2 (Phase 7.3) + 7 (Phase 8.1) + 5 (Phase 8.2) + 1 (Phase 9.1) = **34 new tests**. Total expected: `1376 baseline + 34 new = 1410 pass + ~5 skip`.

- [ ] **Step 2: Lint sweep**

Run: `python -m py_compile website/api/_memory_guard.py website/api/_proc_stats.py website/api/admin_routes.py website/main.py website/app.py website/features/rag_pipeline/rerank/cascade.py website/features/rag_pipeline/ingest/embedder.py run.py && echo "py_compile OK"`
Expected: `py_compile OK`.

Run: `python -c "import yaml; [yaml.safe_load(open(p)) for p in ('.github/workflows/deploy-droplet.yml','ops/docker-compose.blue.yml','ops/docker-compose.green.yml')]; print('yaml OK')"`
Expected: `yaml OK`.

Run: `bash -n ops/deploy/deploy.sh && echo "bash OK"`
Expected: `bash OK`.

- [ ] **Step 3: Local Docker smoke (operator)**

```bash
docker build -f ops/Dockerfile -t zettelkasten-kg-website:smoke .

docker run --rm \
  -m 1300m --memory-swap 2300m \
  --env-file .env.local \
  -p 10000:10000 \
  zettelkasten-kg-website:smoke
```

In another shell:

```bash
curl -s http://localhost:10000/api/health
# Expect: {"status":"ok"}

# (If you have a local bearer token for testing)
curl -s -H "Authorization: Bearer $LOCAL_TOKEN" \
     http://localhost:10000/api/admin/_proc_stats | jq .
# Expect: JSON with vm_rss_kb populated and cgroup_mem_max == 1363148800

# Then fire one /api/rag/adhoc against the same instance:
curl -s -H "Authorization: Bearer $LOCAL_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"sandbox_id":"<KM_KASTEN_ID>","content":"Which programming language is the zk-org/zk command-line tool written in, and what file format does it use for notes?","quality":"fast","stream":false,"scope_filter":{}}' \
     http://localhost:10000/api/rag/adhoc | jq .
# Expect: HTTP 200, turn.citations[0].node_id == "gh-zk-org-zk"

# Verify VmRSS stayed under 90% during the call:
curl -s -H "Authorization: Bearer $LOCAL_TOKEN" \
     http://localhost:10000/api/admin/_proc_stats | jq '{vm_rss_kb, cgroup_mem_max}'
# Expect: vm_rss_kb * 1024 < cgroup_mem_max * 0.9
```

If the curl-based smoke is impractical (e.g., no `.env.local` with a staging Supabase pointer is available locally), explicitly skip to Phase 11.2 (deploy). The Playwright harness in Phase 11.3 against prod is the authoritative gate; the local smoke is purely a fast-fail check.

### Task 11.2: Deploy

**Files:** none

- [ ] **Step 1: Push the branch**

```bash
git push origin iter-03/prod-memory-bounded
```

- [ ] **Step 2: Fast-forward merge to master**

Always fast-forward (no merge commit) — the branch is squashed in Phase 12 anyway. Run exactly:

```bash
git checkout master
git pull --ff-only origin master
git merge --ff-only iter-03/prod-memory-bounded
git push origin master
```

If `git merge --ff-only` errors with "fatal: Not possible to fast-forward, aborting" — STOP and rebase the branch onto master first:

```bash
git checkout iter-03/prod-memory-bounded
git rebase origin/master
git push --force-with-lease origin iter-03/prod-memory-bounded
```

then return to the merge step.

- [ ] **Step 3: Wait for the GH Actions Deploy to DigitalOcean Droplet to complete (success)**

Run: `gh run list --branch master --limit 1` — wait for `completed/success` on the "Deploy to DigitalOcean Droplet" workflow. If it fails, pull droplet logs (`gh workflow run read_recent_logs.yml -f tail_lines=400 -f color=auto`) and triage; do NOT touch any protected knob.

- [ ] **Step 4: Run the manual swapfile op + assert cgroup budget on the droplet**

Operator follows `docs/runbooks/droplet_swapfile.md` Steps 1-4. Then asserts cgroup-side budget (executor can run these via SSH or via the `read_recent_logs.yml` workflow if extended; recommended: extend the workflow with one extra step that runs `docker exec zettelkasten-blue cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.swap.max` and prints the values, OR use the proc_stats endpoint):

```bash
# Via the deployed app's admin endpoint (preferred — no SSH needed):
curl -sH "Authorization: Bearer $ZK_BEARER_TOKEN" \
     https://zettelkasten.in/api/admin/_proc_stats | jq '{cgroup_mem_max, cgroup_swap_max}'
# Expect:
#   {
#     "cgroup_mem_max": 1363148800,
#     "cgroup_swap_max": 1048576000
#   }
```

If `cgroup_mem_max != 1363148800` OR `cgroup_swap_max != 1048576000`: STOP. The compose limits did not apply — likely the deploy script raced the swapfile or compose was edited without recreating the container. Triage before continuing.

### Task 11.3: Post-deploy verification (Playwright harness)

**Files:**
- Read: `docs/rag_eval/common/knowledge-management/iter-03/baseline_pre_mem_bounded.json` (from Phase 0.2)
- Update: `docs/rag_eval/common/knowledge-management/iter-03/scores.md` (final 3-way comparison)

- [ ] **Step 1: Operator runs the harness against prod**

```powershell
$env:ZK_BEARER_TOKEN = Get-Clipboard
python ops/scripts/eval_iter_03_playwright.py
```

- [ ] **Step 2: Inspect `verification_results.json`**

Read the JSON and assert each acceptance gate from spec §4 step 5:
- `infra_failures = 0` on the 13 sequential queries.
- `end_to_end_gold_at_1 ≥ baseline.json.ci_gates.end_to_end_gold_at_1_min` (= 0.65) AND ≥ `baseline_pre_mem_bounded.json.qa_summary.end_to_end_gold_at_1 - 0.03`.
- `synthesizer_over_refusals = 0`.
- `p95_latency_ms ≤ baseline_pre_mem_bounded.json.qa_summary.p95_latency_ms * 1.05`.
- per-stage signals (retrieval recall, reranker margin, synth grounding) within 3% absolute drop.

- [ ] **Step 3: If any acceptance gate fails — STOP, do NOT revert fp32 first**

Follow spec §3 quality-regression triage order:
1. Verify the regression is real (re-run eval).
2. Inspect critic_verdict distribution.
3. Inspect `retrieval_recall_at_10`.
4. Try non-fp32 fixes first (re-enable arena on int8 only; bump stage-1 candidate count; re-tune per-class margins; re-tune score calibration).
5. **Only if 1-4 fail to recover** → escalate to user before flipping `RAG_FP32_VERIFY=on`.

- [ ] **Step 4: Write the final scorecard**

Create `docs/rag_eval/common/knowledge-management/iter-03/scores.md` with 3-way comparison: iter-01 (blocked) vs iter-02 (deployed_sha 83da88e) vs iter-03 (post-mem-bounded). Mirror the table format used in `docs/rag_eval/common/knowledge-management/iter-02/scores.md`. Include:
- per-query verdict table (q1-q10, av-1..av-3, div-1, div-2)
- per-stage metrics 3-way comparison
- composite verdict
- residual gaps (if any)

- [ ] **Step 5: Commit results**

```bash
git add docs/rag_eval/common/knowledge-management/iter-03/verification_results.json \
        docs/rag_eval/common/knowledge-management/iter-03/timing_report.md \
        docs/rag_eval/common/knowledge-management/iter-03/screenshots/ \
        docs/rag_eval/common/knowledge-management/iter-03/scores.md
git commit -m "docs: iter-03 mem bounded eval scorecard"
git push origin master
```

---

## Phase 12 — Squash, merge, and 24h observation (~ongoing)

### Task 12.1: Squash branch into nine logical commits

**Files:** git history only

- [ ] **Step 1: From `iter-03/prod-memory-bounded`, interactive rebase**

Squash the per-task commits into the nine logical commits below. Run `git rebase -i master` and use the `s` (squash) action to merge adjacent commits onto the first one of each group; for each squashed group, replace the squash-message with the canonical commit message listed below:

1. `ops: bump container mem_limit 1300m 1g swap`
2. `perf: disable onnx cpu mem arena and pattern`
3. `ops: default RAG_FP32_VERIFY off in deploy`
4. `perf: preload flashrank ranker module level cow`
5. `perf: bound embedder query cache lru 256`
6. `ops: gunicorn max requests 100 jitter 20`
7. `feat: proc stats reader and admin endpoint` (squash 7.1 + 7.2 + 7.3)
8. `feat: soft rss guard middleware exempt health` (squash 8.1 + 8.2 + 9.1 stress)
9. `docs: swapfile runbook iter-03 mem bounded scorecard` (squash 10.1 + 11.3 results)

```bash
git rebase -i master
# in editor, squash adjacent commits per the list above; reword to the
# 5-10-word forms.
```

- [ ] **Step 2: Force-push the squashed branch**

```bash
git push --force-with-lease origin iter-03/prod-memory-bounded
```

- [ ] **Step 3: Already-fast-forwarded master needs no further action; squash applied for history hygiene only.**

### Task 12.2: 24h observation window

**Files:** none

- [ ] **Step 1: Daily log pull for 7 days**

Run: `gh workflow run read_recent_logs.yml -f tail_lines=2000 -f color=auto` once daily.

- [ ] **Step 2: Inspect `[proc_stats]` lines**

Look for `vm_rss_kb`, `cgroup_mem_current` trend and `cgroup_swap_current`. Record p95 RSS over the 24h window.

- [ ] **Step 3: Decision point on day 7**

If `vm_rss_p95 < 70% * cgroup_mem_max` AND `cpu_p95 < 60%` AND `infra_failures = 0`:
- Candidate to attempt re-enabling `RAG_FP32_VERIFY=on` as a SEPARATE isolated rollout.
- The re-enable rollout is **a new spec + plan**, not part of this one.

If conditions are not met: log the data, leave fp32 off, and surface the residual to a future iter.

---

## Out of scope (mirrors spec §5)

- Changing the droplet (hard constraint).
- Changing `GUNICORN_WORKERS` away from 2 (hard constraint).
- Switching to `gthread` workers (FastAPI is ASGI; not viable).
- Re-quantizing BGE to a smaller variant (would need a new int8 calibration run + new score-calibration regression — separate iter).
- Adding a second droplet behind a load balancer (out of cost budget).
- Re-enabling `RAG_FP32_VERIFY=on` (last-resort triage step only; out of scope for this rollout).
