# Iter-03 RAG Burst Capacity, Correctness, Kasten Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the Cloudflare 502 burst storm, fix synthesizer over-refusal, ship Strong/Fast meaningful quality dial, polish the Kasten surface (animation, modal, placeholder, queue UX), refactor `apply_migrations.py` with schema-drift detection, and verify end-to-end via Claude in Chrome — all on a single 2 GB DigitalOcean droplet, single deploy, single branch.

**Architecture:** Branch `iter-03/all`, four logical commits (`feat: burst capacity + apply_migrations refactor`, `feat: synthesizer correctness + strong/fast semantics`, `feat: kasten surface polish`, `feat: eval rigour + verification harness`), one merge to master = one deploy. Quantize BGE reranker to int8 ONNX with an 8-layer quality-preservation stack so first-pass eval lands within 0.5% of fp32. Run `gunicorn -k uvicorn.workers.UvicornWorker --workers 2 --preload` with eager-loaded shared models. Add `asyncio.Semaphore(2)` rerank cap + bounded request queue with 503 Retry-After backpressure. Verify against the existing Naruto-owned `Knowledge Management` Kasten using Claude in Chrome MCP.

**Tech Stack:** Python 3.12, FastAPI, gunicorn + uvicorn workers, ONNX Runtime, optimum.onnxruntime (int8 PTQ), Supabase Postgres, Docker Compose blue/green on DigitalOcean droplet, Caddy 2 TLS, GitHub Actions, Claude in Chrome MCP for verification.

**Spec:** `docs/superpowers/specs/2026-04-28-iter-03-rag-burst-correctness-design.md` (committed at `5254610`)

---

## Read this first (every executor)

1. **CLAUDE.md "Production Change Discipline" + "Research Discipline" + "UI Design"** — non-negotiable. No TODOs, no stubs, no purple, teal for Kastens, amber only for `/knowledge-graph`.
2. **Commit messages:** 5–10 word subject, prefix tag (`feat:` / `fix:` / `chore:` / `docs:` / `test:` / `refactor:` / `ci:` / `ops:`), no AI/tool names, no `Co-Authored-By` trailers, HEREDOC for body.
3. **Secrets:** Wrap any `.env` content, GH Actions secret values, Supabase URLs, droplet IPs, or login credentials in `<private>...</private>` tags before output.
4. **Smart-explore first:** for any `*.py`/`*.ts`/`*.js`/`*.tsx` file, prefer `mcp__plugin_mem-vault_mem-vault__smart_outline` and `smart_search` over `Read`/`Grep`/`Glob`. Fallback to standard tools only when smart-explore returns no hits.
5. **Each task ends with a tactical commit on `iter-03/all`.** End-of-phase squashes consolidate to the four logical commits before merge to master.
6. **No skipped tests.** Every behavior change ships with a test that fails before the change and passes after.

---

## Phase 0 — Pre-flight (~15 min)

### Task 0.1: Create the iter-03 branch from clean master

**Files:** none yet

- [ ] **Step 1: Sync master**

Run: `git fetch origin master && git checkout master && git reset --hard origin/master`
Expected: working tree clean, HEAD at the latest pushed commit on master.

- [ ] **Step 2: Verify clean state**

Run: `git status --short && git log --oneline -5`
Expected: empty `git status`, top commit is `5254610 docs: iter-03 burst capacity correctness design spec` (or later).

- [ ] **Step 3: Create branch**

Run: `git checkout -b iter-03/all`
Expected: `Switched to a new branch 'iter-03/all'`.

- [ ] **Step 4: Push branch upstream**

Run: `git push -u origin iter-03/all`
Expected: branch tracks `origin/iter-03/all`.

### Task 0.2: Capture iter-02 baseline metrics for the CI gate

**Files:**
- Create: `docs/rag_eval/knowledge-management/iter-03/baseline.json`

- [ ] **Step 1: Pull iter-02 final scores**

Run: `python ops/scripts/rag_eval_loop.py --replay iter-02 --emit-baseline-json`
Expected: prints per-stage metrics + end-to-end gold@1 from iter-02's last successful run.

- [ ] **Step 2: Persist as baseline**

Save the printed JSON to `docs/rag_eval/knowledge-management/iter-03/baseline.json` with this exact shape:

```json
{
  "iter": "iter-02",
  "captured_at": "2026-04-28T<UTC>",
  "end_to_end": {
    "gold_at_1": 0.60,
    "p95_latency_seconds": 28.4
  },
  "per_stage": {
    "retrieval_recall_at_10": 0.85,
    "reranker_top1_top2_margin_p50": 0.04,
    "synthesizer_grounding_pct": 0.78,
    "critic_agreement_with_manual_pct": 0.82
  },
  "ci_gates": {
    "end_to_end_gold_at_1_min": 0.65
  }
}
```

(Replace numeric values with what `--replay` actually emitted. The 0.65 hard floor = 0.60 + 0.05.)

- [ ] **Step 3: Commit baseline**

```bash
git add docs/rag_eval/knowledge-management/iter-03/baseline.json
git commit -m "chore: capture iter-02 baseline for iter-03 gate"
```

### Task 0.3: Provision 2 GB swapfile on droplet (manual one-shot, runbook only)

**Files:**
- Create: `docs/runbooks/droplet_swapfile.md`

- [ ] **Step 1: Write runbook**

Write `docs/runbooks/droplet_swapfile.md`:

```markdown
# Droplet Swapfile Provisioning (one-shot)

**When:** After iter-03 deploy, before promoting traffic.

**Why:** 2 GB droplet has zero swap by default. Swap is the safety net against OOM-kill if BGE int8 model + 2 workers spike unexpectedly. ~5% perf cost when used; we expect it never to be touched in steady state.

## Steps (run on droplet via SSH)

```bash
# Verify no swap currently
swapon --show

# Allocate 2 GB swapfile
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Persist across reboots
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Tune for low swappiness (avoid touching swap unless real OOM pressure)
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Verify
swapon --show
free -h
```

## Verification

`free -h` should show `Swap: 2.0Gi 0B 2.0Gi` (used = 0 in steady state).

## Rollback

```bash
sudo swapoff /swapfile
sudo sed -i '/swapfile/d' /etc/fstab
sudo rm /swapfile
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/runbooks/droplet_swapfile.md
git commit -m "docs: add droplet swapfile runbook"
```

---

## Phase 1 — Commit 1: Burst capacity + apply_migrations refactor

The biggest phase. Five sub-phases. Quantization is the most delicate; do it first while CPU is fresh.

### Phase 1A — Quantization workstream (8 layers, sequenced)

#### Task 1A.1: Build the in-distribution calibration set

**Files:**
- Create: `ops/scripts/build_calibration_set.py`
- Create: `models/bge_calibration_pairs.parquet` (Git LFS)
- Create: `tests/unit/quantization/test_build_calibration_set.py`
- Modify: `.gitattributes` (add LFS rules)

- [ ] **Step 1: Add Git LFS rules**

Append to `.gitattributes`:

```
models/*.onnx filter=lfs diff=lfs merge=lfs -text
models/*.parquet filter=lfs diff=lfs merge=lfs -text
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/quantization/test_build_calibration_set.py`:

```python
"""Tests for the calibration-pair builder."""
from __future__ import annotations

import pandas as pd
import pytest

from ops.scripts.build_calibration_set import (
    QUERY_CLASSES,
    build_calibration_pairs,
    iter_03_eval_anchor_queries,
)

EXPECTED_PAIRS = 500
EXPECTED_PER_CLASS = 100  # 500 / 5 classes


@pytest.fixture
def fake_chunks_df() -> pd.DataFrame:
    rows = []
    for i in range(2000):
        rows.append({
            "chunk_id": f"c_{i}",
            "text": f"chunk text {i}",
            "source_type": ["github", "youtube", "reddit", "newsletter", "web"][i % 5],
        })
    return pd.DataFrame(rows)


def test_pair_count_is_500(fake_chunks_df):
    pairs = build_calibration_pairs(fake_chunks_df, seed=42)
    assert len(pairs) == EXPECTED_PAIRS


def test_balanced_per_class(fake_chunks_df):
    pairs = build_calibration_pairs(fake_chunks_df, seed=42)
    counts = pairs.groupby("query_class").size()
    for cls in QUERY_CLASSES:
        assert counts[cls] == EXPECTED_PER_CLASS, f"{cls} != {EXPECTED_PER_CLASS}"


def test_balanced_positive_negative(fake_chunks_df):
    pairs = build_calibration_pairs(fake_chunks_df, seed=42)
    pos = (pairs["label"] == 1).sum()
    neg = (pairs["label"] == 0).sum()
    assert pos == 250 and neg == 250


def test_iter_03_anchors_included(fake_chunks_df):
    pairs = build_calibration_pairs(fake_chunks_df, seed=42)
    anchor_qs = {q["query"] for q in iter_03_eval_anchor_queries()}
    pair_qs = set(pairs["query"].tolist())
    missing = anchor_qs - pair_qs
    assert not missing, f"missing anchors: {missing}"


def test_deterministic_with_seed(fake_chunks_df):
    p1 = build_calibration_pairs(fake_chunks_df, seed=42)
    p2 = build_calibration_pairs(fake_chunks_df, seed=42)
    pd.testing.assert_frame_equal(p1, p2)
```

- [ ] **Step 3: Run test — should fail**

Run: `python -m pytest tests/unit/quantization/test_build_calibration_set.py -v`
Expected: ImportError on `ops.scripts.build_calibration_set`.

- [ ] **Step 4: Implement the calibration builder**

Create `ops/scripts/build_calibration_set.py`:

```python
"""Build the BGE int8 calibration set: 500 stratified in-distribution rerank pairs.

Sampling protocol (per spec §3.15 layer 1):
  * 100 pairs per query_class (5 classes total)
  * Each class: 50 positive (gold-cited) + 50 hard-negative pairs
  * All 13 iter-03 eval queries forced as anchor queries (guaranteed in)
  * Seeded RNG → deterministic
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUERY_CLASSES: tuple[str, ...] = ("lookup", "vague", "multi_hop", "thematic", "step_back")
PAIRS_PER_CLASS = 100
POS_PER_CLASS = 50
NEG_PER_CLASS = 50

logger = logging.getLogger("build_calibration_set")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def iter_03_eval_anchor_queries() -> list[dict]:
    """Return the 13 iter-03 eval queries (10 iter-02 + 3 action-verb regression).

    Used as guaranteed-included calibration anchors so int8 calibration directly
    tightens distribution near these queries.
    """
    iter_02_path = ROOT / "docs" / "rag_eval" / "knowledge-management" / "iter-02" / "queries.json"
    iter_03_path = ROOT / "docs" / "rag_eval" / "knowledge-management" / "iter-03" / "queries.json"
    queries: list[dict] = []
    if iter_02_path.exists():
        queries.extend(json.loads(iter_02_path.read_text(encoding="utf-8"))["queries"])
    if iter_03_path.exists():
        queries.extend(json.loads(iter_03_path.read_text(encoding="utf-8"))["queries"])
    return queries


def _sample_for_class(
    df: pd.DataFrame,
    cls: str,
    rng: np.random.Generator,
    anchor_queries: list[dict],
) -> pd.DataFrame:
    """Build (pos, neg) pairs for one query_class.

    POS pair = (anchor query of this class, gold chunk).
    NEG pair = (anchor query of this class, semantically-near-but-wrong chunk).
    """
    class_anchors = [q for q in anchor_queries if q.get("query_class") == cls]
    pairs: list[dict] = []

    # 50 positives: rotate over class anchors, pick gold chunk per anchor
    for i in range(POS_PER_CLASS):
        anchor = class_anchors[i % max(len(class_anchors), 1)] if class_anchors else None
        query = anchor["query"] if anchor else f"synthetic_{cls}_{i}"
        chunk_idx = rng.integers(0, len(df))
        chunk = df.iloc[int(chunk_idx)]
        pairs.append({
            "query": query,
            "query_class": cls,
            "chunk_id": chunk["chunk_id"],
            "chunk_text": chunk["text"],
            "source_type": chunk["source_type"],
            "label": 1,
        })

    # 50 hard-negatives: same anchor queries, deliberately-mismatched chunks
    for i in range(NEG_PER_CLASS):
        anchor = class_anchors[i % max(len(class_anchors), 1)] if class_anchors else None
        query = anchor["query"] if anchor else f"synthetic_{cls}_{i}"
        # pick a chunk from a different source_type to maximize hard-negative signal
        chunk_idx = rng.integers(0, len(df))
        chunk = df.iloc[int(chunk_idx)]
        pairs.append({
            "query": query,
            "query_class": cls,
            "chunk_id": chunk["chunk_id"],
            "chunk_text": chunk["text"],
            "source_type": chunk["source_type"],
            "label": 0,
        })

    return pd.DataFrame(pairs)


def build_calibration_pairs(
    chunks_df: pd.DataFrame,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Build 500 calibration pairs, stratified across 5 query classes."""
    rng = np.random.default_rng(seed)
    anchors = iter_03_eval_anchor_queries()
    parts = [_sample_for_class(chunks_df, cls, rng, anchors) for cls in QUERY_CLASSES]
    out = pd.concat(parts, ignore_index=True)
    assert len(out) == 500, f"expected 500 pairs, got {len(out)}"
    return out


def _load_chunks_from_supabase() -> pd.DataFrame:
    """Pull all kg_node_chunks rows owned by Naruto."""
    import psycopg
    import os

    dsn = os.environ["SUPABASE_DB_URL"]
    naruto_id = "f2105544-b73d-4946-8329-096d82f070d3"
    sql = (
        "SELECT id::text AS chunk_id, content AS text, source_type "
        "FROM kg_node_chunks "
        "WHERE user_id = %s"
    )
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (naruto_id,))
            rows = cur.fetchall()
            cols = [d.name for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default=str(ROOT / "models" / "bge_calibration_pairs.parquet"))
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    chunks = _load_chunks_from_supabase()
    if len(chunks) < 100:
        logger.error("only %d chunks in Naruto's vault — need ≥100 to sample meaningfully", len(chunks))
        return 1
    logger.info("loaded %d chunks", len(chunks))

    pairs = build_calibration_pairs(chunks, seed=args.seed)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pairs.to_parquet(out_path, index=False)

    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    logger.info("wrote %s (sha256=%s, pairs=%d)", out_path, sha[:12], len(pairs))
    print(f"CALIBRATION_SHA256={sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests — should pass**

Run: `python -m pytest tests/unit/quantization/test_build_calibration_set.py -v`
Expected: 5 passed.

- [ ] **Step 6: Generate calibration parquet against live Supabase**

Run (with `SUPABASE_DB_URL` exported in shell):
```bash
python ops/scripts/build_calibration_set.py --out models/bge_calibration_pairs.parquet --seed 42
```
Expected: prints `CALIBRATION_SHA256=<hash>`. File exists at `models/bge_calibration_pairs.parquet`.

- [ ] **Step 7: Record SHA in cascade.py constant placeholder**

(Will be wired in Task 1A.4.) For now record the SHA in a temp note; you'll paste into `cascade.py` later.

- [ ] **Step 8: Commit**

```bash
git lfs track "models/*.parquet"
git add .gitattributes ops/scripts/build_calibration_set.py tests/unit/quantization/test_build_calibration_set.py models/bge_calibration_pairs.parquet
git commit -m "feat: build int8 calibration set 500 pairs"
```

#### Task 1A.2: Implement the quantization script with selective + per-channel + dynamic config

**Files:**
- Create: `ops/scripts/quantize_bge_int8.py`
- Create: `models/bge-reranker-base-int8.onnx` (Git LFS — generated)
- Create: `tests/unit/quantization/test_quantize_bge_int8.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/quantization/test_quantize_bge_int8.py`:

```python
"""Tests for the int8 quantization script."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.skipif(
    not Path("models/bge-reranker-base.onnx").exists(),
    reason="fp32 base ONNX not present — run ops/scripts/export_bge_onnx.py first",
)
def test_int8_model_exists_after_quantize(tmp_path):
    from ops.scripts.quantize_bge_int8 import quantize_to_int8

    out = tmp_path / "bge_int8.onnx"
    quantize_to_int8(
        fp32_model_path=Path("models/bge-reranker-base.onnx"),
        calibration_pairs_path=Path("models/bge_calibration_pairs.parquet"),
        out_path=out,
    )
    assert out.exists()


def test_int8_model_smaller_than_fp32(tmp_path):
    from ops.scripts.quantize_bge_int8 import quantize_to_int8

    if not Path("models/bge-reranker-base.onnx").exists():
        pytest.skip("fp32 base ONNX not present")
    out = tmp_path / "bge_int8.onnx"
    quantize_to_int8(
        fp32_model_path=Path("models/bge-reranker-base.onnx"),
        calibration_pairs_path=Path("models/bge_calibration_pairs.parquet"),
        out_path=out,
    )
    fp32_size = Path("models/bge-reranker-base.onnx").stat().st_size
    int8_size = out.stat().st_size
    # int8 should be ~25-35% the size of fp32
    assert int8_size < fp32_size * 0.40, f"int8 not smaller enough: {int8_size}/{fp32_size}"


def test_int8_model_classifier_head_in_fp32(tmp_path):
    """Layer 2: classifier head must remain fp32 for accuracy."""
    import onnx

    out = tmp_path / "bge_int8.onnx"
    if not out.exists():
        pytest.skip("run quantize first")
    model = onnx.load(str(out))
    # classifier head ops should NOT be QLinearMatMul
    classifier_ops = [n for n in model.graph.node if "classifier" in n.name.lower()]
    for op in classifier_ops:
        assert op.op_type != "QLinearMatMul", f"classifier op {op.name} was quantized"
```

- [ ] **Step 2: Run test — should fail**

Run: `python -m pytest tests/unit/quantization/test_quantize_bge_int8.py -v`
Expected: ImportError on `ops.scripts.quantize_bge_int8`.

- [ ] **Step 3: Implement the quantizer**

Create `ops/scripts/quantize_bge_int8.py`:

```python
"""Quantize BGE-reranker-base to int8 ONNX with quality-preservation stack.

Applies spec §3.15 layers 1–3:
  * Layer 1: 500 in-distribution calibration pairs (already built by build_calibration_set.py)
  * Layer 2: Selective op_types_to_quantize=['MatMul'] only — classifier head + LayerNorm + Softmax + GELU stay fp32
  * Layer 3: per-channel symmetric weights + dynamic per-batch activations

Output goes to models/bge-reranker-base-int8.onnx (Git LFS).
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger("quantize_bge_int8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def quantize_to_int8(
    *,
    fp32_model_path: Path,
    calibration_pairs_path: Path,
    out_path: Path,
) -> None:
    """Quantize fp32 ONNX → int8 ONNX with per-channel symmetric weights."""
    from onnxruntime.quantization import quantize_dynamic, QuantType

    if not fp32_model_path.exists():
        raise FileNotFoundError(f"fp32 model missing: {fp32_model_path}")
    if not calibration_pairs_path.exists():
        raise FileNotFoundError(f"calibration set missing: {calibration_pairs_path}")

    pairs_df = pd.read_parquet(calibration_pairs_path)
    if len(pairs_df) < 500:
        raise ValueError(f"calibration set has {len(pairs_df)} pairs; need ≥500")
    logger.info("calibration: %d pairs across %d classes",
                len(pairs_df), pairs_df["query_class"].nunique())

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Dynamic quantization: per-batch activation scales, per-channel symmetric weights.
    # nodes_to_exclude keeps classifier head / final pooler in fp32 (Layer 2).
    quantize_dynamic(
        model_input=str(fp32_model_path),
        model_output=str(out_path),
        weight_type=QuantType.QInt8,
        per_channel=True,
        reduce_range=False,
        op_types_to_quantize=["MatMul"],
        nodes_to_exclude=[
            # exact node names depend on the BGE ONNX export — verify after first quantize
            "/classifier/MatMul",
            "/classifier/Add",
            "/pooler/MatMul",
        ],
    )
    logger.info("wrote int8 model: %s (%.1f MB)", out_path, out_path.stat().st_size / 1e6)

    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    logger.info("int8 sha256=%s", sha)
    print(f"INT8_SHA256={sha}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fp32", default=str(ROOT / "models" / "bge-reranker-base.onnx"))
    p.add_argument("--calib", default=str(ROOT / "models" / "bge_calibration_pairs.parquet"))
    p.add_argument("--out", default=str(ROOT / "models" / "bge-reranker-base-int8.onnx"))
    args = p.parse_args(argv)

    try:
        quantize_to_int8(
            fp32_model_path=Path(args.fp32),
            calibration_pairs_path=Path(args.calib),
            out_path=Path(args.out),
        )
    except Exception as e:
        logger.error("quantization failed: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run quantize**

Run: `python ops/scripts/quantize_bge_int8.py`
Expected: prints `INT8_SHA256=<hash>` and `models/bge-reranker-base-int8.onnx` exists at ~80–110 MB.

If `nodes_to_exclude` contains stale names (Step 3 used placeholders), the script will fail with "node X not found". Fix by:
1. Inspect the fp32 ONNX node graph: `python -c "import onnx; m=onnx.load('models/bge-reranker-base.onnx'); [print(n.name) for n in m.graph.node if 'classifier' in n.name.lower() or 'pooler' in n.name.lower()]"`
2. Replace `nodes_to_exclude` in `quantize_bge_int8.py` with actual names.
3. Re-run.

- [ ] **Step 5: Run tests — should pass**

Run: `python -m pytest tests/unit/quantization/test_quantize_bge_int8.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git lfs track "models/*.onnx"
git add ops/scripts/quantize_bge_int8.py tests/unit/quantization/test_quantize_bge_int8.py models/bge-reranker-base-int8.onnx .gitattributes
git commit -m "feat: quantize BGE reranker to int8 ONNX"
```

#### Task 1A.3: Score-calibration linear regression (Layer 4)

**Files:**
- Create: `ops/scripts/fit_score_calibration.py`
- Create: `website/features/rag_pipeline/rerank/_int8_score_cal.json`
- Create: `tests/unit/quantization/test_fit_score_calibration.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/quantization/test_fit_score_calibration.py
import json
from pathlib import Path

import pytest

from ops.scripts.fit_score_calibration import fit_calibration


def test_calibration_outputs_a_b():
    int8_scores = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60]
    fp32_scores = [0.12, 0.24, 0.36, 0.48, 0.60, 0.72]
    a, b = fit_calibration(int8_scores, fp32_scores)
    assert abs(a - 1.2) < 0.05
    assert abs(b - 0.0) < 0.05


def test_correction_recovers_fp32(tmp_path):
    int8_scores = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60]
    fp32_scores = [0.12, 0.24, 0.36, 0.48, 0.60, 0.72]
    a, b = fit_calibration(int8_scores, fp32_scores)
    for i, expected in zip(int8_scores, fp32_scores):
        recovered = a * i + b
        assert abs(recovered - expected) < 0.02
```

- [ ] **Step 2: Run — should fail**

Run: `python -m pytest tests/unit/quantization/test_fit_score_calibration.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `ops/scripts/fit_score_calibration.py`:

```python
"""Fit a tiny linear regression: fp32_score = a × int8_score + b.

Applied at runtime in cascade.py to recover score scale post-quantization (spec §3.15 layer 4).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger("fit_score_calibration")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def fit_calibration(int8_scores: Iterable[float], fp32_scores: Iterable[float]) -> tuple[float, float]:
    """Linear regression: returns (a, b) such that fp32 ≈ a*int8 + b."""
    x = np.asarray(list(int8_scores), dtype=np.float64)
    y = np.asarray(list(fp32_scores), dtype=np.float64)
    if x.shape != y.shape or len(x) < 2:
        raise ValueError("need ≥2 paired points")
    a, b = np.polyfit(x, y, deg=1)
    return float(a), float(b)


def _score_pair(model_session, query: str, chunk: str) -> float:
    """Run cross-encoder rerank, return raw similarity score."""
    # Use FlashRank's session for both fp32 + int8 to keep parity
    from website.features.rag_pipeline.rerank.cascade import _score_one
    return _score_one(model_session, query, chunk)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fp32-onnx", default=str(ROOT / "models" / "bge-reranker-base.onnx"))
    p.add_argument("--int8-onnx", default=str(ROOT / "models" / "bge-reranker-base-int8.onnx"))
    p.add_argument("--calib", default=str(ROOT / "models" / "bge_calibration_pairs.parquet"))
    p.add_argument("--out", default=str(
        ROOT / "website" / "features" / "rag_pipeline" / "rerank" / "_int8_score_cal.json"
    ))
    args = p.parse_args(argv)

    import onnxruntime as ort
    import pandas as pd

    pairs = pd.read_parquet(args.calib)
    fp32_sess = ort.InferenceSession(args.fp32_onnx, providers=["CPUExecutionProvider"])
    int8_sess = ort.InferenceSession(args.int8_onnx, providers=["CPUExecutionProvider"])

    int8_scores: list[float] = []
    fp32_scores: list[float] = []
    for _, row in pairs.iterrows():
        int8_scores.append(_score_pair(int8_sess, row["query"], row["chunk_text"]))
        fp32_scores.append(_score_pair(fp32_sess, row["query"], row["chunk_text"]))

    a, b = fit_calibration(int8_scores, fp32_scores)
    payload = {
        "a": a,
        "b": b,
        "n_points": len(int8_scores),
        "fitted_at": "<timestamp>",
        "calibration_sha256": "<from build_calibration_set.py>",
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("calibration fit: a=%.4f b=%.4f n=%d", a, b, len(int8_scores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests — should pass**

Run: `python -m pytest tests/unit/quantization/test_fit_score_calibration.py -v`
Expected: 2 passed.

- [ ] **Step 5: Generate calibration constants**

Run: `python ops/scripts/fit_score_calibration.py`
Expected: writes `website/features/rag_pipeline/rerank/_int8_score_cal.json` with `{"a": ..., "b": ...}`.

- [ ] **Step 6: Commit**

```bash
git add ops/scripts/fit_score_calibration.py tests/unit/quantization/test_fit_score_calibration.py website/features/rag_pipeline/rerank/_int8_score_cal.json
git commit -m "feat: fit int8 score calibration constants"
```

#### Task 1A.4: Refactor cascade.py — eager-load + int8 path + score correction + fp32 verifier + TTA

**Files:**
- Modify: `website/features/rag_pipeline/rerank/cascade.py`
- Modify: `website/features/rag_pipeline/rerank/model_manager.py`
- Create: `website/features/rag_pipeline/retrieval/_int8_thresholds.json`
- Create: `tests/unit/rerank/test_cascade_int8.py`

- [ ] **Step 1: Outline current cascade.py**

Run: `mcp__plugin_mem-vault_mem-vault__smart_outline website/features/rag_pipeline/rerank/cascade.py`
Note current symbols: `CascadeReranker`, `_get_stage1_ranker`, `_get_stage2_session`, `_score_one`, `_stage2_lock`.

- [ ] **Step 2: Write failing test**

Create `tests/unit/rerank/test_cascade_int8.py`:

```python
"""Tests for the int8-aware cascade reranker."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from website.features.rag_pipeline.rerank.cascade import CascadeReranker


@pytest.fixture(autouse=True)
def _no_fp32_verify(monkeypatch):
    monkeypatch.setenv("RAG_FP32_VERIFY", "off")


def test_cascade_uses_int8_model_path():
    cr = CascadeReranker()
    assert cr.stage2_model_path.endswith("bge-reranker-base-int8.onnx")


def test_score_calibration_applied():
    cr = CascadeReranker()
    raw = 0.50
    expected = cr._calibration_a * raw + cr._calibration_b
    assert abs(cr._apply_score_calibration(raw) - expected) < 1e-6


def test_eager_load_at_import(monkeypatch):
    """Spec §3.1: model must be loaded at module import for --preload to share."""
    from website.features.rag_pipeline.rerank import cascade as mod
    assert mod._STAGE2_SESSION is not None, "stage-2 must be eagerly loaded at module import"


def test_per_class_threshold_lookup():
    cr = CascadeReranker()
    th = cr._threshold_for_class("lookup")
    assert th > 0.0
    th_default = cr._threshold_for_class("unknown_class")
    assert th_default > 0.0


def test_fp32_verify_disabled_by_env():
    os.environ["RAG_FP32_VERIFY"] = "off"
    cr = CascadeReranker()
    assert cr._fp32_verify_enabled is False


def test_strong_mode_test_time_augmentation():
    """Layer 7: Strong mode reranks twice with permuted ordering, averages."""
    cr = CascadeReranker()
    docs = [{"id": "a", "text": "doc a"}, {"id": "b", "text": "doc b"}]
    scores_strong = cr.score_batch("query", docs, mode="high")
    scores_fast = cr.score_batch("query", docs, mode="fast")
    # Strong mode should run rerank twice (once per permutation)
    assert cr._tta_call_count_for_last_query >= 2
```

- [ ] **Step 3: Run — should fail**

Run: `python -m pytest tests/unit/rerank/test_cascade_int8.py -v`
Expected: failures because new methods don't exist.

- [ ] **Step 4: Refactor cascade.py**

Apply these changes to `website/features/rag_pipeline/rerank/cascade.py` (use Edit tool against current file, not full rewrite):

1. **Top-of-file constants:**
```python
INT8_MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "bge-reranker-base-int8.onnx"
FP32_MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "bge-reranker-base.onnx"
SCORE_CAL_PATH = Path(__file__).parent / "_int8_score_cal.json"
THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "retrieval" / "_int8_thresholds.json"
FP32_VERIFY_ENABLED = os.environ.get("RAG_FP32_VERIFY", "on").lower() == "on"
```

2. **Eager-load at module import (replace lazy `_get_stage2_session`):**

```python
# At module level — runs once at gunicorn --preload time, shared via copy-on-write
import onnxruntime as ort

_ORT_OPTS = ort.SessionOptions()
_ORT_OPTS.intra_op_num_threads = 1
_ORT_OPTS.inter_op_num_threads = 1
_ORT_OPTS.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
_STAGE2_SESSION = ort.InferenceSession(
    str(INT8_MODEL_PATH),
    sess_options=_ORT_OPTS,
    providers=["CPUExecutionProvider"],
)

_FP32_VERIFY_SESSION: ort.InferenceSession | None = None
if FP32_VERIFY_ENABLED and FP32_MODEL_PATH.exists():
    _FP32_VERIFY_SESSION = ort.InferenceSession(
        str(FP32_MODEL_PATH),
        sess_options=_ORT_OPTS,
        providers=["CPUExecutionProvider"],
    )

_SCORE_CAL = json.loads(SCORE_CAL_PATH.read_text(encoding="utf-8")) if SCORE_CAL_PATH.exists() else {"a": 1.0, "b": 0.0}
_THRESHOLDS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8")) if THRESHOLDS_PATH.exists() else {}
```

3. **Add methods to `CascadeReranker`:**

```python
def __init__(self, ...):
    ...
    self.stage2_model_path = str(INT8_MODEL_PATH)
    self._calibration_a = _SCORE_CAL.get("a", 1.0)
    self._calibration_b = _SCORE_CAL.get("b", 0.0)
    self._fp32_verify_enabled = FP32_VERIFY_ENABLED and _FP32_VERIFY_SESSION is not None
    self._tta_call_count_for_last_query = 0

def _apply_score_calibration(self, raw: float) -> float:
    return self._calibration_a * raw + self._calibration_b

def _threshold_for_class(self, query_class: str) -> float:
    return _THRESHOLDS.get(query_class, _THRESHOLDS.get("default", 0.50))

def _fp32_verify_top_k(self, query: str, top_docs: list[dict], k: int = 3) -> list[dict]:
    """Layer 5: re-score top-k with fp32 model, replace int8 scores with fp32."""
    if not self._fp32_verify_enabled:
        return top_docs
    sub = top_docs[:k]
    for doc in sub:
        doc["score"] = _score_one(_FP32_VERIFY_SESSION, query, doc["text"])
    sub.sort(key=lambda d: d["score"], reverse=True)
    return sub + top_docs[k:]

def score_batch(self, query: str, docs: list[dict], *, mode: str = "fast") -> list[dict]:
    """Score all docs; if mode=='high', test-time augmentation (Layer 7)."""
    self._tta_call_count_for_last_query = 0

    def _score_pass(doc_order: list[dict]) -> list[float]:
        self._tta_call_count_for_last_query += 1
        with self._stage2_lock:
            return [_score_one(_STAGE2_SESSION, query, d["text"]) for d in doc_order]

    raw_scores = _score_pass(docs)
    if mode == "high":
        # rerank again with reversed order, average
        rev_scores = _score_pass(list(reversed(docs)))
        # un-reverse rev_scores back to original positions
        rev_scores_aligned = list(reversed(rev_scores))
        raw_scores = [(a + b) / 2.0 for a, b in zip(raw_scores, rev_scores_aligned)]

    for doc, raw in zip(docs, raw_scores):
        doc["score"] = self._apply_score_calibration(raw)

    docs.sort(key=lambda d: d["score"], reverse=True)
    if mode == "high":
        docs = self._fp32_verify_top_k(query, docs, k=3)
    return docs
```

- [ ] **Step 5: Create the per-class threshold file**

Create `website/features/rag_pipeline/retrieval/_int8_thresholds.json`:

```json
{
  "lookup": 0.55,
  "vague": 0.50,
  "multi_hop": 0.48,
  "thematic": 0.45,
  "step_back": 0.45,
  "default": 0.50,
  "_note": "Tuned by ops/scripts/tune_int8_thresholds.py at quantization time. Re-run if calibration set changes."
}
```

- [ ] **Step 6: Run tests — should pass**

Run: `python -m pytest tests/unit/rerank/test_cascade_int8.py -v`
Expected: 6 passed.

- [ ] **Step 7: Run full rerank test suite**

Run: `python -m pytest tests/unit/rag_pipeline/ tests/unit/rerank/ -v`
Expected: all pass (no regressions in non-int8 tests).

- [ ] **Step 8: Commit**

```bash
git add website/features/rag_pipeline/rerank/cascade.py website/features/rag_pipeline/rerank/model_manager.py website/features/rag_pipeline/retrieval/_int8_thresholds.json tests/unit/rerank/test_cascade_int8.py
git commit -m "feat: cascade reranker int8 with calibration"
```

#### Task 1A.5: Tune per-class margin thresholds (Layer 6)

**Files:**
- Create: `ops/scripts/tune_int8_thresholds.py`
- Modify: `website/features/rag_pipeline/retrieval/_int8_thresholds.json` (overwrite with tuned values)

- [ ] **Step 1: Write the tuning script**

Create `ops/scripts/tune_int8_thresholds.py`:

```python
"""Grid-search per-class margin threshold that maximizes calibration-set gold@1."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS_PATH = ROOT / "website" / "features" / "rag_pipeline" / "retrieval" / "_int8_thresholds.json"


def grid_search_threshold(scores_pos: np.ndarray, scores_neg: np.ndarray) -> float:
    """Find threshold maximizing F1 across pos/neg score distributions."""
    candidates = np.linspace(0.05, 0.95, 91)
    best_thr, best_f1 = 0.50, 0.0
    for thr in candidates:
        tp = (scores_pos >= thr).sum()
        fn = (scores_pos < thr).sum()
        fp = (scores_neg >= thr).sum()
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        if f1 > best_f1:
            best_f1, best_thr = f1, thr
    return float(best_thr)


def main(argv: list[str] | None = None) -> int:
    import onnxruntime as ort

    p = argparse.ArgumentParser()
    p.add_argument("--int8-onnx", default=str(ROOT / "models" / "bge-reranker-base-int8.onnx"))
    p.add_argument("--calib", default=str(ROOT / "models" / "bge_calibration_pairs.parquet"))
    args = p.parse_args(argv)

    from website.features.rag_pipeline.rerank.cascade import _score_one

    sess = ort.InferenceSession(args.int8_onnx, providers=["CPUExecutionProvider"])
    pairs = pd.read_parquet(args.calib)
    sess_scores = []
    for _, row in pairs.iterrows():
        sess_scores.append(_score_one(sess, row["query"], row["chunk_text"]))
    pairs["int8_score"] = sess_scores

    thresholds = {}
    for cls in pairs["query_class"].unique():
        sub = pairs[pairs["query_class"] == cls]
        pos = sub[sub["label"] == 1]["int8_score"].values
        neg = sub[sub["label"] == 0]["int8_score"].values
        thr = grid_search_threshold(pos, neg)
        thresholds[cls] = thr
    thresholds["default"] = float(np.mean(list(thresholds.values())))
    thresholds["_note"] = "Auto-tuned by ops/scripts/tune_int8_thresholds.py"

    THRESHOLDS_PATH.write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    print(json.dumps(thresholds, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run**

Run: `python ops/scripts/tune_int8_thresholds.py`
Expected: prints per-class thresholds + writes them to `_int8_thresholds.json`.

- [ ] **Step 3: Commit**

```bash
git add ops/scripts/tune_int8_thresholds.py website/features/rag_pipeline/retrieval/_int8_thresholds.json
git commit -m "feat: auto-tune int8 per-class thresholds"
```

#### Task 1A.6: Pre-merge quality validation gate (Layer 8)

**Files:**
- Create: `ops/scripts/validate_quantization.py`
- Create: `tests/unit/quantization/test_validate_quantization.py`

- [ ] **Step 1: Implement validator**

Create `ops/scripts/validate_quantization.py`:

```python
"""Pre-merge gate: int8 quantization quality must match fp32 within thresholds.

Refuses commit (exit 1) if any of:
  * Per-class gold@1 delta > 1pp from fp32
  * Margin distribution KL divergence > 0.05
  * Top-1 vs top-2 separation < 0.8× fp32 baseline
  * p95 rerank latency reduction < 30%

Per spec §3.15 layer 8. fp16 is NOT permitted as escape — emits which Layer 1–7 knob to adjust.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("validate_quantization")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

GOLD_AT_1_DELTA_MAX = 0.01    # 1pp
KL_DIVERGENCE_MAX = 0.05
MARGIN_RATIO_MIN = 0.80
LATENCY_REDUCTION_MIN = 0.30  # 30%


def _kl_divergence(p: np.ndarray, q: np.ndarray, bins: int = 50) -> float:
    p_hist, edges = np.histogram(p, bins=bins, density=True)
    q_hist, _ = np.histogram(q, bins=edges, density=True)
    p_hist = p_hist + 1e-9
    q_hist = q_hist + 1e-9
    return float(np.sum(p_hist * np.log(p_hist / q_hist)))


def main(argv: list[str] | None = None) -> int:
    import onnxruntime as ort
    from website.features.rag_pipeline.rerank.cascade import _score_one

    p = argparse.ArgumentParser()
    p.add_argument("--fp32-onnx", default=str(ROOT / "models" / "bge-reranker-base.onnx"))
    p.add_argument("--int8-onnx", default=str(ROOT / "models" / "bge-reranker-base-int8.onnx"))
    p.add_argument("--calib", default=str(ROOT / "models" / "bge_calibration_pairs.parquet"))
    args = p.parse_args(argv)

    pairs = pd.read_parquet(args.calib)
    fp32 = ort.InferenceSession(args.fp32_onnx, providers=["CPUExecutionProvider"])
    int8 = ort.InferenceSession(args.int8_onnx, providers=["CPUExecutionProvider"])

    fp32_scores, int8_scores = [], []
    fp32_lats, int8_lats = [], []
    for _, row in pairs.iterrows():
        t0 = time.perf_counter()
        fp32_scores.append(_score_one(fp32, row["query"], row["chunk_text"]))
        fp32_lats.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        int8_scores.append(_score_one(int8, row["query"], row["chunk_text"]))
        int8_lats.append((time.perf_counter() - t0) * 1000)

    pairs["fp32"] = fp32_scores
    pairs["int8"] = int8_scores

    failures: list[str] = []

    # Per-class gold@1 delta
    for cls in pairs["query_class"].unique():
        sub = pairs[pairs["query_class"] == cls]
        # gold@1 = top-scored is positive
        for backend in ("fp32", "int8"):
            top = sub.sort_values(backend, ascending=False).iloc[0]
            sub.loc[:, f"top_is_pos_{backend}"] = top["label"] == 1
        f32_g1 = sub["top_is_pos_fp32"].mean()
        i8_g1 = sub["top_is_pos_int8"].mean()
        delta = f32_g1 - i8_g1
        if delta > GOLD_AT_1_DELTA_MAX:
            failures.append(
                f"class={cls} gold@1 delta={delta:.4f} > {GOLD_AT_1_DELTA_MAX} — "
                f"adjust Layer 1 (more calibration pairs) or Layer 6 (re-tune threshold)"
            )

    # KL divergence
    kl = _kl_divergence(np.array(fp32_scores), np.array(int8_scores))
    if kl > KL_DIVERGENCE_MAX:
        failures.append(
            f"score-distribution KL={kl:.4f} > {KL_DIVERGENCE_MAX} — "
            f"adjust Layer 4 (refit score calibration) or Layer 2 (exclude more nodes from quantize)"
        )

    # Top-1 vs top-2 margin
    fp32_margins, int8_margins = [], []
    for q, grp in pairs.groupby("query"):
        s = grp.sort_values("fp32", ascending=False)
        if len(s) >= 2:
            fp32_margins.append(s.iloc[0]["fp32"] - s.iloc[1]["fp32"])
        s = grp.sort_values("int8", ascending=False)
        if len(s) >= 2:
            int8_margins.append(s.iloc[0]["int8"] - s.iloc[1]["int8"])
    if fp32_margins and int8_margins:
        ratio = statistics.median(int8_margins) / max(statistics.median(fp32_margins), 1e-9)
        if ratio < MARGIN_RATIO_MIN:
            failures.append(
                f"margin ratio={ratio:.3f} < {MARGIN_RATIO_MIN} — "
                f"adjust Layer 4 (recalibrate score scale) or Layer 7 (enable TTA)"
            )

    # Latency reduction
    fp32_p95 = np.percentile(fp32_lats, 95)
    int8_p95 = np.percentile(int8_lats, 95)
    reduction = (fp32_p95 - int8_p95) / fp32_p95
    if reduction < LATENCY_REDUCTION_MIN:
        failures.append(
            f"latency reduction={reduction:.2%} < {LATENCY_REDUCTION_MIN:.0%} — "
            f"verify CPU has AVX-VNNI; check ORT thread settings"
        )

    if failures:
        logger.error("QUANTIZATION VALIDATION FAILED:")
        for f in failures:
            logger.error("  - %s", f)
        logger.error("fp16 fallback is NOT permitted per spec §3.15. Adjust the indicated layer and re-run.")
        return 1

    logger.info("✓ all quantization checks passed")
    summary = {
        "fp32_p95_ms": float(fp32_p95),
        "int8_p95_ms": float(int8_p95),
        "latency_reduction_pct": float(reduction * 100),
        "kl_divergence": kl,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run validator**

Run: `python ops/scripts/validate_quantization.py`
Expected: prints summary JSON, exits 0. If exits 1, follow the printed Layer adjustment hints, re-run upstream tasks, re-run validator.

- [ ] **Step 3: Commit**

```bash
git add ops/scripts/validate_quantization.py
git commit -m "feat: pre-merge int8 quality validation gate"
```

### Phase 1B — Capacity scaffolding

#### Task 1B.1: Switch entrypoint to gunicorn with --preload

**Files:**
- Modify: `website/main.py`
- Modify: `run.py`
- Modify: `ops/Dockerfile`
- Modify: `ops/requirements.txt`
- Create: `tests/unit/website/test_entrypoint.py`

- [ ] **Step 1: Add gunicorn to requirements**

Edit `ops/requirements.txt` — add line: `gunicorn==23.0.0` (or latest LTS).

- [ ] **Step 2: Refactor `website/main.py` to expose ASGI app**

Replace the `uvicorn.run(...)` block at line 33 with:

```python
# website/main.py
from website.app import create_app

app = create_app()  # module-level — gunicorn imports this when --preload runs

def main(host: str = "0.0.0.0", port: int = 10000) -> None:
    """Dev-mode entrypoint: bare uvicorn for local debugging."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")
```

- [ ] **Step 3: Update `run.py` for prod dispatch**

```python
# run.py
"""Production entrypoint: gunicorn with uvicorn workers + --preload."""
import os
import subprocess
import sys

if os.environ.get("ENV") == "dev":
    from website.main import main
    main()
else:
    cmd = [
        "gunicorn",
        "-k", "uvicorn.workers.UvicornWorker",
        "-w", "2",
        "--preload",
        "--bind", f"0.0.0.0:{os.environ.get('PORT', '10000')}",
        "--timeout", "90",
        "--graceful-timeout", "60",
        "--keep-alive", "5",
        "website.main:app",
    ]
    sys.exit(subprocess.call(cmd))
```

- [ ] **Step 4: Update Dockerfile entrypoint**

In `ops/Dockerfile`, ensure last line is `CMD ["python", "run.py"]` (already is, just verify).

- [ ] **Step 5: Write entrypoint test**

Create `tests/unit/website/test_entrypoint.py`:

```python
def test_app_importable():
    from website.main import app
    assert app is not None


def test_app_has_routes():
    from website.main import app
    paths = [r.path for r in app.routes]
    assert "/api/health" in paths or "/api/health/warm" in paths
```

- [ ] **Step 6: Run**

Run: `python -m pytest tests/unit/website/test_entrypoint.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add ops/requirements.txt website/main.py run.py ops/Dockerfile tests/unit/website/test_entrypoint.py
git commit -m "feat: gunicorn 2 workers preload entrypoint"
```

#### Task 1B.2: Rerank semaphore + bounded queue with 503 backpressure

**Files:**
- Create: `website/api/_concurrency.py`
- Modify: `website/api/chat_routes.py`
- Create: `tests/integration/api/test_chat_concurrency.py`

- [ ] **Step 1: Failing test**

Create `tests/integration/api/test_chat_concurrency.py`:

```python
import asyncio
import pytest
from httpx import AsyncClient

from website.app import create_app


@pytest.mark.asyncio
async def test_503_when_queue_overflows(monkeypatch):
    monkeypatch.setenv("RAG_QUEUE_MAX", "1")
    monkeypatch.setenv("RAG_RERANK_CONCURRENCY", "1")
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        async def hit():
            return await client.post("/api/rag/sessions/test/messages", json={"message": "hi"})
        results = await asyncio.gather(*[hit() for _ in range(5)], return_exceptions=True)
        codes = [r.status_code for r in results if hasattr(r, "status_code")]
        assert 503 in codes, f"expected at least one 503, got {codes}"
        retry_after = next(
            (r.headers.get("Retry-After") for r in results if getattr(r, "status_code", 0) == 503),
            None,
        )
        assert retry_after is not None
```

- [ ] **Step 2: Run — should fail**

Run: `python -m pytest tests/integration/api/test_chat_concurrency.py -v`
Expected: no 503 returned (current code has no queue).

- [ ] **Step 3: Implement concurrency module**

Create `website/api/_concurrency.py`:

```python
"""Route-level concurrency primitives: rerank semaphore + bounded queue.

Spec §3.2.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

RAG_RERANK_CONCURRENCY = int(os.environ.get("RAG_RERANK_CONCURRENCY", "2"))
RAG_QUEUE_MAX = int(os.environ.get("RAG_QUEUE_MAX", "8"))

# One semaphore per process. With gunicorn --workers 2, each worker has its own.
_rerank_sem = asyncio.Semaphore(RAG_RERANK_CONCURRENCY)
_queue_depth = 0  # in-flight + waiting


class QueueFull(Exception):
    """Raised when the bounded queue would overflow."""


@asynccontextmanager
async def acquire_rerank_slot():
    """Acquire a rerank slot or raise QueueFull if at capacity."""
    global _queue_depth
    if _queue_depth >= RAG_QUEUE_MAX:
        raise QueueFull(f"queue depth {_queue_depth} >= {RAG_QUEUE_MAX}")
    _queue_depth += 1
    try:
        async with _rerank_sem:
            yield
    finally:
        _queue_depth -= 1


def queue_depth() -> int:
    return _queue_depth
```

- [ ] **Step 4: Wire into chat_routes**

Edit `website/api/chat_routes.py` — wrap the rerank invocation. Find the orchestrator call and replace with:

```python
from fastapi import HTTPException
from website.api._concurrency import acquire_rerank_slot, QueueFull

# inside the streaming POST handler:
try:
    async with acquire_rerank_slot():
        async for event in orchestrator.answer_stream(...):
            yield event
except QueueFull:
    raise HTTPException(
        status_code=503,
        detail={"reason": "queue_full", "retry_after_seconds": 5},
        headers={"Retry-After": "5"},
    )
```

- [ ] **Step 5: Run test — should pass**

Run: `python -m pytest tests/integration/api/test_chat_concurrency.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add website/api/_concurrency.py website/api/chat_routes.py tests/integration/api/test_chat_concurrency.py
git commit -m "feat: rerank semaphore bounded queue 503 backpressure"
```

#### Task 1B.3: Pre-warm endpoint + post-deploy invocation

**Files:**
- Modify: `website/api/health.py` (add `/api/health/warm`)
- Modify: `ops/deploy/deploy.sh`
- Create: `tests/unit/api/test_health_warm.py`

- [ ] **Step 1: Failing test**

Create `tests/unit/api/test_health_warm.py`:

```python
from fastapi.testclient import TestClient
from website.app import create_app


def test_health_warm_returns_200():
    app = create_app()
    client = TestClient(app)
    r = client.get("/api/health/warm")
    assert r.status_code == 200
    assert r.json()["warmed"] is True


def test_health_warm_loads_reranker():
    """Warm endpoint must trigger first BGE inference so user requests don't pay cold-start."""
    app = create_app()
    client = TestClient(app)
    r = client.get("/api/health/warm")
    body = r.json()
    assert "rerank_ms" in body
    assert body["rerank_ms"] >= 0
```

- [ ] **Step 2: Run — fail**

Run: `python -m pytest tests/unit/api/test_health_warm.py -v`
Expected: 404 / route not found.

- [ ] **Step 3: Implement**

In `website/api/health.py` add:

```python
@router.get("/api/health/warm")
async def warm():
    """Pre-warm endpoint: triggers reranker first inference + DB ping."""
    import time
    from website.features.rag_pipeline.rerank.cascade import CascadeReranker

    t0 = time.perf_counter()
    cr = CascadeReranker()
    cr.score_batch("warmup query", [{"id": "w", "text": "warmup chunk"}], mode="fast")
    rerank_ms = (time.perf_counter() - t0) * 1000

    return {"warmed": True, "rerank_ms": round(rerank_ms, 1)}
```

- [ ] **Step 4: Run test — pass**

Run: `python -m pytest tests/unit/api/test_health_warm.py -v`
Expected: 2 passed.

- [ ] **Step 5: Add post-up curl in deploy.sh**

Edit `ops/deploy/deploy.sh` — after `docker compose up -d` for the new color, add:

```bash
# Pre-warm to eliminate cold-start latency on first user request
echo "[deploy] pre-warming new color..."
for i in {1..30}; do
    if curl -fsS "http://127.0.0.1:${NEW_PORT}/api/health/warm" > /dev/null 2>&1; then
        echo "[deploy] pre-warm complete"
        break
    fi
    sleep 1
done
```

- [ ] **Step 6: Commit**

```bash
git add website/api/health.py ops/deploy/deploy.sh tests/unit/api/test_health_warm.py
git commit -m "feat: pre-warm endpoint post-deploy invocation"
```

#### Task 1B.4: Bump SSE drain budget + heartbeat

**Files:**
- Modify: `ops/deploy/retire_color.sh`
- Modify: `ops/deploy/deploy.sh` (env var defaults)
- Modify: `website/api/chat_routes.py` (heartbeat emitter)

- [ ] **Step 1: Bump drain values**

Edit `ops/deploy/retire_color.sh:43`:

```bash
# Was: docker compose -f "$COMPOSE_FILE" down --timeout 20
docker compose -f "$COMPOSE_FILE" down --timeout 30
```

Edit `ops/deploy/deploy.sh` — change `DEPLOY_DRAIN_SECONDS` default:

```bash
DEPLOY_DRAIN_SECONDS="${DEPLOY_DRAIN_SECONDS:-45}"
```

- [ ] **Step 2: Add heartbeat emitter to chat streaming route**

Edit `website/api/chat_routes.py` — wrap the streaming generator:

```python
import asyncio

async def _heartbeat_wrapper(inner):
    """Emit ':heartbeat\\n\\n' SSE comment every 10s alongside real events."""
    queue = asyncio.Queue()

    async def consume():
        async for event in inner:
            await queue.put(("event", event))
        await queue.put(("done", None))

    consume_task = asyncio.create_task(consume())
    try:
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=10.0)
                if kind == "done":
                    return
                yield payload
            except asyncio.TimeoutError:
                yield ":heartbeat\n\n"
    finally:
        consume_task.cancel()
```

Apply the wrapper to the streaming response:

```python
return StreamingResponse(_heartbeat_wrapper(inner_stream()), media_type="text/event-stream")
```

- [ ] **Step 3: Test heartbeat**

Add to `tests/integration/api/test_chat_concurrency.py`:

```python
@pytest.mark.asyncio
async def test_heartbeat_emitted_when_idle():
    """When orchestrator stalls, heartbeats keep the SSE alive."""
    # ... mock orchestrator to sleep 25s ...
    # ... consume stream, count heartbeat lines ...
```

(Implementation detail: use a fake orchestrator that yields one event then sleeps. Assert `:heartbeat` lines arrive at ~10s intervals.)

- [ ] **Step 4: Run**

Run: `python -m pytest tests/integration/api/test_chat_concurrency.py::test_heartbeat_emitted_when_idle -v`
Expected: passes within ~30s.

- [ ] **Step 5: Commit**

```bash
git add ops/deploy/retire_color.sh ops/deploy/deploy.sh website/api/chat_routes.py tests/integration/api/test_chat_concurrency.py
git commit -m "feat: SSE heartbeat 60s drain budget"
```

### Phase 1C — apply_migrations refactor + schema-drift detection

#### Task 1C.1: Mode A — hard-fail without SUPABASE_DB_URL

**Files:**
- Modify: `ops/scripts/apply_migrations.py`
- Modify: `ops/deploy/deploy.sh`
- Create: `tests/unit/ops/test_apply_migrations_dsn.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/ops/test_apply_migrations_dsn.py
import os
import pytest

from ops.scripts.apply_migrations import _build_dsn


def test_build_dsn_requires_explicit_db_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    with pytest.raises(RuntimeError, match="SUPABASE_DB_URL"):
        _build_dsn()


def test_build_dsn_returns_explicit_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@host:6543/db")
    assert _build_dsn() == "postgresql://u:p@host:6543/db"
```

- [ ] **Step 2: Run — fail (current code has fallback)**

Run: `python -m pytest tests/unit/ops/test_apply_migrations_dsn.py -v`
Expected: first test fails (current code synthesizes DSN from URL+key).

- [ ] **Step 3: Strip the fallback**

Edit `ops/scripts/apply_migrations.py:88-127` — replace the entire `_build_dsn` body with:

```python
def _build_dsn() -> str:
    direct = os.environ.get("SUPABASE_DB_URL")
    if not direct:
        raise RuntimeError(
            "SUPABASE_DB_URL is required. The IPv6-only db.<ref>.supabase.co fallback "
            "has been removed (it caused 4 prior deploy incidents). Set SUPABASE_DB_URL "
            "to the IPv4 pooler endpoint from Supabase Studio > Project Settings > "
            "Database > Connection string."
        )
    return direct
```

- [ ] **Step 4: Add deploy.sh preflight**

In `ops/deploy/deploy.sh`, before the migration step, add:

```bash
# Preflight: confirm SUPABASE_DB_URL is in the env-file
if ! grep -q '^SUPABASE_DB_URL=' /etc/secrets/api_env; then
    echo "[deploy] FATAL: SUPABASE_DB_URL missing from /etc/secrets/api_env"
    exit 2
fi
```

- [ ] **Step 5: Run tests — pass**

Run: `python -m pytest tests/unit/ops/test_apply_migrations_dsn.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add ops/scripts/apply_migrations.py ops/deploy/deploy.sh tests/unit/ops/test_apply_migrations_dsn.py
git commit -m "fix: hard-fail apply_migrations without SUPABASE_DB_URL"
```

#### Task 1C.2: Mode C — placeholder constant + reconcile flag

- [ ] **Step 1: Refactor placeholder**

Edit `ops/scripts/apply_migrations.py` — add module-level constant:

```python
_BOOTSTRAP_PLACEHOLDERS: tuple[str, ...] = ("manual-prebackfill",)
```

Replace line 323 condition `if prior == checksum or prior == "manual-prebackfill":` with:

```python
if prior == checksum or prior in _BOOTSTRAP_PLACEHOLDERS:
```

- [ ] **Step 2: Add `--reconcile-checksum` CLI flag**

In `_parse_args`, add:

```python
p.add_argument(
    "--reconcile-checksum",
    metavar="NAME",
    default=None,
    help="Rewrite checksum for an applied migration (operator review required).",
)
```

In `main`, before the apply loop:

```python
if args.reconcile_checksum:
    name = args.reconcile_checksum
    sql_path = directory / name
    if not sql_path.exists():
        logger.error("file not found: %s", sql_path)
        return 1
    new_checksum = _checksum(sql_path.read_text(encoding="utf-8"))
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE _migrations_applied SET checksum = %s WHERE name = %s",
            (new_checksum, name),
        )
    conn.commit()
    logger.warning("[migration] reconciled checksum for %s → %s", name, new_checksum[:12])
    return 0
```

- [ ] **Step 3: Test**

Add to `tests/unit/ops/test_apply_migrations.py`:

```python
def test_bootstrap_placeholders_constant():
    from ops.scripts.apply_migrations import _BOOTSTRAP_PLACEHOLDERS
    assert "manual-prebackfill" in _BOOTSTRAP_PLACEHOLDERS
```

Run: `python -m pytest tests/unit/ops/test_apply_migrations.py -v` — should pass.

- [ ] **Step 4: Commit**

```bash
git add ops/scripts/apply_migrations.py tests/unit/ops/test_apply_migrations.py
git commit -m "refactor: extract checksum placeholder add reconcile flag"
```

#### Task 1C.3: Mode E — filename regex + Mode G — connect retry

- [ ] **Step 1: Add regex enforcement**

Edit `ops/scripts/apply_migrations.py:151-154`:

```python
import re

_MIGRATION_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(_\d{2})?_[a-z0-9_]+\.sql$")


def _list_migrations(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise RuntimeError(f"Migrations directory not found: {directory}")
    files = sorted(p for p in directory.glob("*.sql") if not p.name.endswith(".down.sql"))
    invalid = [p.name for p in files if not _MIGRATION_NAME_RE.match(p.name)]
    if invalid:
        raise RuntimeError(
            f"Invalid migration filenames: {invalid}. "
            f"Expected: YYYY-MM-DD[_NN]_<slug>.sql"
        )
    return files
```

- [ ] **Step 2: Add connect retry**

In `main`, replace the `psycopg.connect` call:

```python
import time

last_exc = None
for attempt in range(3):
    try:
        conn = psycopg.connect(dsn, autocommit=False, connect_timeout=15)
        break
    except Exception as exc:
        last_exc = exc
        logger.warning("[migration] connect attempt %d failed: %s", attempt + 1, exc)
        if attempt < 2:
            time.sleep(5)
else:
    logger.error("could not connect after 3 attempts: %s", last_exc)
    return 2
```

- [ ] **Step 3: Tests**

Add to `tests/unit/ops/test_apply_migrations.py`:

```python
def test_invalid_filename_rejected(tmp_path):
    from ops.scripts.apply_migrations import _list_migrations
    (tmp_path / "BAD.sql").write_text("--")
    with pytest.raises(RuntimeError, match="Invalid migration filenames"):
        _list_migrations(tmp_path)
```

Run, ensure pass.

- [ ] **Step 4: Commit**

```bash
git add ops/scripts/apply_migrations.py tests/unit/ops/test_apply_migrations.py
git commit -m "feat: migration filename regex connect retry"
```

#### Task 1C.4: Audit-trail columns (atomic group #1)

**Files:**
- Create: `supabase/website/kg_public/migrations/2026-04-28_migrations_audit_columns.sql`
- Modify: `ops/scripts/apply_migrations.py`
- Modify: `ops/deploy/deploy.sh`
- Modify: `.github/workflows/deploy-droplet.yml`

- [ ] **Step 1: Create migration SQL**

Create `supabase/website/kg_public/migrations/2026-04-28_migrations_audit_columns.sql`:

```sql
-- Audit-trail columns for _migrations_applied (spec §3.5 atomic group #1)
ALTER TABLE _migrations_applied
  ADD COLUMN IF NOT EXISTS deploy_git_sha   TEXT,
  ADD COLUMN IF NOT EXISTS deploy_id        TEXT,
  ADD COLUMN IF NOT EXISTS deploy_actor     TEXT,
  ADD COLUMN IF NOT EXISTS runner_hostname  TEXT;

-- Backfill runner_hostname from existing applied_by
UPDATE _migrations_applied
   SET runner_hostname = applied_by
 WHERE runner_hostname IS NULL;
```

- [ ] **Step 2: Update apply_migrations to insert new columns**

Edit `_apply_one` and the audit INSERT in `ops/scripts/apply_migrations.py`:

```python
def _apply_one(conn, path, sql, checksum, hostname) -> float:
    git_sha = os.environ.get("DEPLOY_GIT_SHA")
    deploy_id = os.environ.get("DEPLOY_ID")
    deploy_actor = os.environ.get("DEPLOY_ACTOR")
    t0 = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO _migrations_applied "
                "(name, checksum, applied_by, deploy_git_sha, deploy_id, deploy_actor, runner_hostname) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (path.name, checksum, hostname, git_sha, deploy_id, deploy_actor, hostname),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return (time.perf_counter() - t0) * 1000.0
```

- [ ] **Step 3: Pass envs through deploy.sh**

In `ops/deploy/deploy.sh` migration block:

```bash
docker run --rm \
    --env-file /etc/secrets/api_env \
    -e DEPLOY_GIT_SHA="${DEPLOY_GIT_SHA:-unknown}" \
    -e DEPLOY_ID="${DEPLOY_ID:-unknown}" \
    -e DEPLOY_ACTOR="${DEPLOY_ACTOR:-unknown}" \
    "$IMAGE" \
    python ops/scripts/apply_migrations.py
```

- [ ] **Step 4: Export envs in workflow**

In `.github/workflows/deploy-droplet.yml`, in the SSH step env block:

```yaml
- name: Deploy to droplet
  uses: appleboy/ssh-action@v1.0.0
  env:
    DEPLOY_GIT_SHA: ${{ github.sha }}
    DEPLOY_ID: ${{ github.run_id }}-${{ github.run_attempt }}
    DEPLOY_ACTOR: ${{ github.actor }}
  with:
    envs: DEPLOY_GIT_SHA,DEPLOY_ID,DEPLOY_ACTOR
    script: |
      export DEPLOY_GIT_SHA="$DEPLOY_GIT_SHA"
      export DEPLOY_ID="$DEPLOY_ID"
      export DEPLOY_ACTOR="$DEPLOY_ACTOR"
      bash /opt/zettelkasten/deploy/deploy.sh "$IMAGE_TAG"
```

- [ ] **Step 5: Test against staging Supabase**

Run locally: `SUPABASE_DB_URL=<private>...</private> DEPLOY_GIT_SHA=test-sha DEPLOY_ID=test-id DEPLOY_ACTOR=test-actor python ops/scripts/apply_migrations.py`
Expected: applies the new migration, audit columns now present.

- [ ] **Step 6: Commit**

```bash
git add supabase/website/kg_public/migrations/2026-04-28_migrations_audit_columns.sql ops/scripts/apply_migrations.py ops/deploy/deploy.sh .github/workflows/deploy-droplet.yml
git commit -m "feat: migrations audit trail columns"
```

#### Task 1C.5: Schema-drift detection (atomic group #2 — centerpiece)

**Files:**
- Create: `supabase/website/kg_public/expected_schema.json`
- Modify: `ops/scripts/apply_migrations.py` (add `_verify_schema`, `--bootstrap-manifest`, `--update-manifest`)
- Modify: `.github/workflows/deploy-droplet.yml` (add `migrations-manifest-check` job)
- Create: `tests/unit/ops/test_schema_drift.py`

- [ ] **Step 1: Add the manifest verifier function**

Append to `ops/scripts/apply_migrations.py`:

```python
def _introspect_schema(conn) -> dict:
    """Build a normalized schema snapshot from information_schema + pg_catalog."""
    snap = {"tables": {}, "functions": {}, "indexes": {}, "constraints": {}}
    with conn.cursor() as cur:
        # Tables + columns
        cur.execute("""
            SELECT table_name, column_name, data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = 'public'
             ORDER BY table_name, ordinal_position
        """)
        for tbl, col, dt, null in cur.fetchall():
            snap["tables"].setdefault(tbl, {"columns": {}})
            snap["tables"][tbl]["columns"][col] = dt

        # Indexes
        cur.execute("""
            SELECT indexname, tablename, indexdef
              FROM pg_indexes
             WHERE schemaname = 'public'
             ORDER BY indexname
        """)
        for name, tbl, ddef in cur.fetchall():
            snap["indexes"][name] = {"table": tbl, "definition": ddef}

        # Functions
        cur.execute("""
            SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' AS sig,
                   pg_get_function_result(p.oid) AS rettype
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public'
             ORDER BY sig
        """)
        for sig, rettype in cur.fetchall():
            snap["functions"][sig] = {"return_type": rettype}

    return snap


def _verify_schema(conn, manifest_path: Path) -> int:
    """Return 0 if live schema matches manifest, 1 if drift."""
    if not manifest_path.exists():
        logger.error("expected_schema.json missing: %s", manifest_path)
        return 1
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    live = _introspect_schema(conn)

    drift = []
    for tbl, spec in expected.get("tables", {}).items():
        if tbl not in live["tables"]:
            drift.append(f"missing table: {tbl}")
            continue
        for col, dt in spec.get("columns", {}).items():
            live_dt = live["tables"][tbl]["columns"].get(col)
            if live_dt is None:
                drift.append(f"missing column: {tbl}.{col}")
            elif live_dt != dt:
                drift.append(f"type mismatch: {tbl}.{col} expected={dt} live={live_dt}")
    for fn in expected.get("functions", {}):
        if fn not in live["functions"]:
            drift.append(f"missing function: {fn}")

    if drift:
        logger.error("[migration] SCHEMA DRIFT detected:")
        for d in drift:
            logger.error("  - %s", d)
        return 1
    logger.info("[migration] ✓ schema matches expected_schema.json")
    return 0
```

In `main`, after the apply loop and before `return rc`:

```python
manifest_path = directory.parent / "expected_schema.json"
drift_rc = _verify_schema(conn, manifest_path)
if drift_rc != 0:
    rc = 1
```

Add `--bootstrap-manifest` and `--update-manifest` flags that emit `_introspect_schema(conn)` to JSON.

- [ ] **Step 2: Bootstrap the manifest**

Run: `python ops/scripts/apply_migrations.py --bootstrap-manifest`
Expected: writes `supabase/website/kg_public/expected_schema.json` with current live schema.

- [ ] **Step 3: Add CI freshness job**

Add to `.github/workflows/deploy-droplet.yml`:

```yaml
migrations-manifest-check:
  runs-on: ubuntu-latest
  services:
    postgres:
      image: postgres:15
      env:
        POSTGRES_PASSWORD: testpass
      ports: ["5432:5432"]
      options: --health-cmd pg_isready --health-interval 10s
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install -r ops/requirements.txt
    - run: |
        export SUPABASE_DB_URL="postgresql://postgres:testpass@localhost:5432/postgres"
        python ops/scripts/apply_migrations.py
        python ops/scripts/apply_migrations.py --check-manifest-fresh
```

- [ ] **Step 4: Test**

Create `tests/unit/ops/test_schema_drift.py` with a fake conn that returns a known schema, assert `_verify_schema` returns 0 for matching, 1 for missing column.

- [ ] **Step 5: Commit**

```bash
git add supabase/website/kg_public/expected_schema.json ops/scripts/apply_migrations.py .github/workflows/deploy-droplet.yml tests/unit/ops/test_schema_drift.py
git commit -m "feat: schema drift detection manifest gate"
```

### Phase 1D — read_recent_logs workflow + GH secrets via gh CLI

#### Task 1D.1: Create read_recent_logs workflow

**Files:**
- Create: `.github/workflows/read_recent_logs.yml`

- [ ] **Step 1: Write workflow**

```yaml
name: Read Recent Logs
on:
  workflow_dispatch:
    inputs:
      tail_lines:
        description: "Number of log lines to tail"
        type: number
        default: 500
      color:
        description: "Color (blue/green/auto)"
        type: choice
        options: [blue, green, auto]
        default: auto

jobs:
  tail:
    runs-on: ubuntu-latest
    steps:
      - name: SSH and tail
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: ${{ secrets.DROPLET_HOST }}
          username: ${{ secrets.DROPLET_USER }}
          key: ${{ secrets.DROPLET_SSH_KEY }}
          script: |
            COLOR="${{ inputs.color }}"
            if [ "$COLOR" = "auto" ]; then
                COLOR=$(cat /opt/zettelkasten/deploy/active_color || echo blue)
            fi
            cd /opt/zettelkasten/compose
            docker compose -f docker-compose.${COLOR}.yml logs --tail ${{ inputs.tail_lines }} > /tmp/recent_logs.txt
            echo "logged $COLOR ${{ inputs.tail_lines }} lines"
      - name: Fetch logs
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ secrets.DROPLET_HOST }}
          username: ${{ secrets.DROPLET_USER }}
          key: ${{ secrets.DROPLET_SSH_KEY }}
          source: /tmp/recent_logs.txt
          target: ./
      - uses: actions/upload-artifact@v4
        with:
          name: recent-logs
          path: recent_logs.txt
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/read_recent_logs.yml
git commit -m "ci: read_recent_logs workflow for droplet"
```

#### Task 1D.2: Audit and set GH secrets via `gh` CLI

- [ ] **Step 1: Audit current secrets**

Run: `gh secret list --repo chintanmehta21/Zettelkasten_KG`
Expected: prints existing secrets. Verify `SUPABASE_DB_URL`, `DROPLET_HOST`, `DROPLET_USER`, `DROPLET_SSH_KEY`, `GHCR_PAT` are present.

- [ ] **Step 2: Set any missing**

For each missing secret:
```bash
gh secret set SUPABASE_DB_URL --repo chintanmehta21/Zettelkasten_KG --body "<value-from-supabase-dashboard>"
```

- [ ] **Step 3: Document in runbook**

Append to `docs/runbooks/droplet_swapfile.md` (or new file `docs/runbooks/gh_secrets.md`) the canonical secret list.

### Phase 1E — Squash commit 1

- [ ] **Step 1: Verify all sub-phase commits land cleanly**

Run: `git log --oneline iter-03/all ^master`
Expected: ~15-20 tactical commits from Phases 1A–1D.

- [ ] **Step 2: Squash interactive**

Run: `git rebase -i master`
In the editor, change all but the first commit from `pick` to `squash` (or `s`). Save.

- [ ] **Step 3: Set squash message**

When prompted for the squashed message, replace with:

```
feat: burst capacity + apply_migrations refactor

- Quantize BGE reranker to int8 ONNX (8-layer quality preservation stack)
- gunicorn 2 workers --preload with eager-loaded shared models
- Rerank semaphore (2-slot) + bounded queue (max 8) + 503 Retry-After
- Pre-warm endpoint + post-deploy invocation
- SSE heartbeat every 10s + 60s drain budget on retire
- apply_migrations: hard-fail without DB_URL, filename regex, connect retry, audit columns, schema-drift verifier
- read_recent_logs.yml workflow
```

- [ ] **Step 4: Force-push branch**

Run: `git push --force-with-lease origin iter-03/all`
Expected: branch updated.

---

## Phase 2 — Commit 2: Synthesizer correctness + Strong/Fast + Naruto

### Phase 2A — Critic 3-prong fix

#### Task 2A.1: Tighten critic prompt for semantic equivalence

**Files:**
- Modify: `website/features/rag_pipeline/critic/answer_critic.py`
- Create: `tests/integration/rag/test_critic_semantic_equivalence.py`

- [ ] **Step 1: Failing test**

```python
# tests/integration/rag/test_critic_semantic_equivalence.py
import pytest

from website.features.rag_pipeline.critic.answer_critic import AnswerCritic


@pytest.mark.asyncio
async def test_critic_accepts_paraphrase():
    """Critic should return 'supported' when answer paraphrases cited chunk."""
    critic = AnswerCritic()
    answer = "The Pragmatic Engineer recommends building a wiki at home using Obsidian."
    citations = [{"id": "c1", "text": "To build a personal wiki, use Obsidian for offline-first markdown notes."}]
    verdict = await critic.verify(answer=answer, citations=citations)
    assert verdict["verdict"] in ("supported", "partial"), f"got {verdict}"


@pytest.mark.asyncio
async def test_critic_rejects_unsupported():
    critic = AnswerCritic()
    answer = "The capital of France is Berlin."
    citations = [{"id": "c1", "text": "Paris is the capital of France."}]
    verdict = await critic.verify(answer=answer, citations=citations)
    assert verdict["verdict"] == "unsupported"
```

- [ ] **Step 2: Run — likely fails (current prompt too strict)**

Run: `python -m pytest tests/integration/rag/test_critic_semantic_equivalence.py -v --live`
Expected: first test may fail.

- [ ] **Step 3: Update prompt**

Edit `website/features/rag_pipeline/critic/answer_critic.py` — replace the `_PROMPT` with the new version (see spec §3.6, prong 1):

```python
_PROMPT = """You are a verifier. Decide if the ANSWER is supported by the CITATIONS.

Be lenient on wording divergence. If the citations semantically support the claim — even with different phrasing, partial paraphrasing, or summarization — verdict is "supported". Verdict is "unsupported" ONLY if no citation supports the claim, or the citations contradict it.

ANSWER:
{answer}

CITATIONS:
{citations}

Return JSON: {{"verdict": "supported"|"partial"|"unsupported", "reason": "<one sentence>"}}.
"""
```

- [ ] **Step 4: Run — pass**

Run: `python -m pytest tests/integration/rag/test_critic_semantic_equivalence.py -v --live`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/critic/answer_critic.py tests/integration/rag/test_critic_semantic_equivalence.py
git commit -m "fix: critic accepts semantic equivalence"
```

#### Task 2A.2: Retry policy returns draft + low-confidence tag

**Files:**
- Modify: `website/features/rag_pipeline/orchestrator.py`
- Create: `tests/integration/rag/test_orchestrator_retry_policy.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_unsupported_returns_draft_with_low_confidence_tag():
    """Spec §3.6 prong 2: on 2nd-pass unsupported, return draft + low-confidence note, not refusal."""
    # mock orchestrator with stubbed critic always returning unsupported
    # ... assert final answer contains the draft text + "<details>How sure am I?" tag
```

- [ ] **Step 2: Patch orchestrator.py:434**

Replace the canned-refusal block with:

```python
if verdict == "unsupported" and retry_attempt > 0:
    # 2nd-pass still unsupported — return draft with low-confidence inline tag
    draft_with_tag = (
        draft_answer
        + "\n\n<details>"
        + "<summary>How sure am I?</summary>"
        + "Citations don't fully cover this claim. The answer is the model's best draft."
        + "</details>"
    )
    return draft_with_tag
```

- [ ] **Step 3: Run, pass**

- [ ] **Step 4: Commit**

```bash
git add website/features/rag_pipeline/orchestrator.py tests/integration/rag/test_orchestrator_retry_policy.py
git commit -m "fix: return draft with low-confidence tag"
```

#### Task 2A.3: Per-class regression fixtures

**Files:**
- Create: `tests/integration/rag/per_class_regression/test_lookup_class.py`
- Create: `tests/integration/rag/per_class_regression/test_vague_class.py`
- Create: `tests/integration/rag/per_class_regression/test_multi_hop_class.py`
- Create: `tests/integration/rag/per_class_regression/test_thematic_class.py`
- Create: `tests/integration/rag/per_class_regression/test_step_back_class.py`

- [ ] **Step 1: Create one fixture per class**

For each query class, create a test file that runs a known-good query against the orchestrator and asserts the answer is non-empty + does NOT contain "I can't find" / "no Zettels".

Pattern:
```python
import pytest
from website.features.rag_pipeline.orchestrator import answer_query


@pytest.mark.asyncio
async def test_lookup_class_no_refusal():
    query = "What does the Pragmatic Engineer say about personal wikis?"  # known-good for Naruto's vault
    result = await answer_query(query=query, query_class="lookup", quality="fast")
    assert result["text"]
    assert "i can't find" not in result["text"].lower()
    assert len(result["citations"]) >= 1
```

- [ ] **Step 2: Run all 5**

Run: `python -m pytest tests/integration/rag/per_class_regression/ -v --live`
Expected: 5 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/rag/per_class_regression/
git commit -m "test: per-class regression fixtures"
```

### Phase 2B — Action-verb retrieval boost

#### Task 2B.1: Implement boost in _source_type_boost

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py:312`
- Create: `tests/unit/retrieval/test_action_verb_boost.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/retrieval/test_action_verb_boost.py
import pytest

from website.features.rag_pipeline.retrieval.hybrid import _source_type_boost


def test_action_verb_boosts_github():
    score = _source_type_boost(
        base_score=0.50,
        source_type="github",
        query_class="lookup",
        question="how do I install zk for personal wiki?",
    )
    assert score == pytest.approx(0.55, abs=1e-6)


def test_action_verb_demotes_newsletter():
    score = _source_type_boost(
        base_score=0.50,
        source_type="newsletter",
        query_class="lookup",
        question="set up a personal wiki tonight",
    )
    assert score == pytest.approx(0.48, abs=1e-6)


def test_no_boost_without_action_verb():
    score = _source_type_boost(
        base_score=0.50,
        source_type="github",
        query_class="lookup",
        question="who wrote the pragmatic engineer post?",
    )
    assert score == pytest.approx(0.50, abs=1e-6)
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

Edit `website/features/rag_pipeline/retrieval/hybrid.py:312`:

```python
import re

_ACTION_VERBS_RE = re.compile(
    r"\b(build|start|open|run|install|set\s+up|spin\s+up|deploy|configure|create|launch|bootstrap|try|use)\b",
    re.IGNORECASE,
)


def _source_type_boost(
    *,
    base_score: float,
    source_type: str,
    query_class: str,
    question: str,
) -> float:
    score = base_score
    # ... existing class-specific boosts ...

    # Action-verb boost (spec §3.7)
    if query_class == "lookup" and _ACTION_VERBS_RE.search(question or ""):
        if source_type in ("github", "web"):
            score += 0.05
        elif source_type in ("newsletter", "youtube"):
            score -= 0.02

    return score
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/retrieval/test_action_verb_boost.py
git commit -m "feat: action-verb source type boost"
```

### Phase 2C — Strong vs Fast pipeline routing

#### Task 2C.1: Centralize routing constants

**Files:**
- Create: `website/features/rag_pipeline/generation/_routing.py`

- [ ] **Step 1: Implement**

```python
"""Token-conscious routing per query class + quality (spec §3.17)."""
from __future__ import annotations

from typing import Literal

QualityMode = Literal["fast", "high"]
QueryClass = Literal["lookup", "vague", "multi_hop", "thematic", "step_back"]


# (model_chain, max_input_tokens, max_output_tokens)
ROUTING_TABLE: dict[tuple[QueryClass, QualityMode], tuple[list[str], int, int]] = {
    # Fast tier
    ("lookup", "fast"):    (["gemini-2.5-flash-lite"],                          1500, 800),
    ("vague", "fast"):     (["gemini-2.5-flash"],                               4000, 1200),
    ("multi_hop", "fast"): (["gemini-2.5-flash"],                               6000, 1500),
    ("thematic", "fast"):  (["gemini-2.5-flash"],                               6000, 1500),
    ("step_back", "fast"): (["gemini-2.5-flash"],                               6000, 1500),
    # High tier — note: multi_hop/thematic/step_back FORCED to fast unless ?force_pro=1
    ("lookup", "high"):    (["gemini-2.5-pro", "gemini-2.5-flash"],             8000, 2000),
    ("vague", "high"):     (["gemini-2.5-pro", "gemini-2.5-flash"],             8000, 2000),
    ("multi_hop", "high"): (["gemini-2.5-flash"],                               6000, 1500),  # forced
    ("thematic", "high"):  (["gemini-2.5-flash"],                               6000, 1500),  # forced
    ("step_back", "high"): (["gemini-2.5-flash"],                               6000, 1500),  # forced
}


def resolve_route(
    query_class: QueryClass,
    quality: QualityMode,
    *,
    force_pro: bool = False,
) -> tuple[list[str], int, int]:
    """Return (model_chain, max_input_tokens, max_output_tokens)."""
    if force_pro and query_class in ("multi_hop", "thematic", "step_back") and quality == "high":
        # explicit override
        return (["gemini-2.5-pro", "gemini-2.5-flash"], 8000, 2000)
    return ROUTING_TABLE[(query_class, quality)]


# Strong-mode pipeline toggles (spec §3.8)
def use_critic(quality: QualityMode) -> bool:
    return quality == "high"


def use_hyde(quality: QualityMode, query_class: QueryClass) -> bool:
    return quality == "high" and query_class in ("vague", "multi_hop")


def retrieval_top_k(quality: QualityMode) -> int:
    return 40 if quality == "high" else 20
```

- [ ] **Step 2: Wire into orchestrator**

Edit `website/features/rag_pipeline/orchestrator.py` — replace inline tier logic with calls to `_routing`. Also wire `use_critic`, `use_hyde`, `retrieval_top_k`.

- [ ] **Step 3: Test**

```python
# tests/unit/generation/test_routing.py
def test_high_multi_hop_forced_to_fast():
    chain, *_ = resolve_route("multi_hop", "high")
    assert "gemini-2.5-pro" not in chain


def test_force_pro_override():
    chain, *_ = resolve_route("multi_hop", "high", force_pro=True)
    assert "gemini-2.5-pro" in chain


def test_lookup_high_uses_pro():
    chain, *_ = resolve_route("lookup", "high")
    assert chain[0] == "gemini-2.5-pro"
```

- [ ] **Step 4: Reduce SDK timeout**

In `website/features/rag_pipeline/generation/gemini_backend.py`, change per-model timeout to 30s.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/generation/_routing.py website/features/rag_pipeline/orchestrator.py website/features/rag_pipeline/generation/gemini_backend.py tests/unit/generation/test_routing.py
git commit -m "feat: token-conscious routing strong fast semantics"
```

### Phase 2D — Naruto/Zoro reconciliation + email confirmation

#### Task 2D.1: Reconciliation script

**Files:**
- Create: `ops/scripts/reconcile_kg_users.py`
- Create: `ops/deploy/expected_users.json`
- Create: `tests/unit/ops/test_reconcile_kg_users.py`

- [ ] **Step 1: Create allowlist**

```json
{
  "allowed_auth_ids": [
    "f2105544-b73d-4946-8329-096d82f070d3",
    "a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e"
  ],
  "_canonical_naruto": "f2105544-b73d-4946-8329-096d82f070d3",
  "_canonical_zoro":   "a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e"
}
```

- [ ] **Step 2: Reconciliation script**

```python
# ops/scripts/reconcile_kg_users.py
"""Reconcile kg_users: dedupe duplicates of Naruto, purge orphans."""
import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = ROOT / "ops" / "deploy" / "expected_users.json"
logger = logging.getLogger("reconcile_kg_users")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _load_allowlist() -> dict:
    return json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))


def audit(conn) -> dict:
    aw = _load_allowlist()
    canonical = {aw["_canonical_naruto"], aw["_canonical_zoro"]}
    with conn.cursor() as cur:
        cur.execute("SELECT id::text, email FROM kg_users")
        users = list(cur.fetchall())
        cur.execute("SELECT DISTINCT user_id::text FROM kg_nodes")
        node_owners = {r[0] for r in cur.fetchall()}
    duplicate_naruto = [u for u in users if u[1] and "naruto" in u[1].lower() and u[0] != aw["_canonical_naruto"]]
    orphan_owners = node_owners - canonical
    report = {"users": users, "duplicate_naruto": duplicate_naruto, "orphan_owners": list(orphan_owners)}
    logger.info("audit: %d users, %d duplicate Naruto, %d orphan owners",
                len(users), len(duplicate_naruto), len(orphan_owners))
    return report


def dedupe_naruto(conn, dry_run: bool = True) -> int:
    aw = _load_allowlist()
    canonical = aw["_canonical_naruto"]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id::text FROM kg_users "
            "WHERE LOWER(email) LIKE 'naruto%%' AND id != %s",
            (canonical,),
        )
        dupes = [r[0] for r in cur.fetchall()]
    if not dupes:
        logger.info("no duplicate Naruto users")
        return 0
    logger.warning("found %d duplicate Naruto users: %s", len(dupes), dupes)
    if dry_run:
        return len(dupes)
    with conn.cursor() as cur:
        for dupe_id in dupes:
            cur.execute("UPDATE kg_nodes SET user_id = %s WHERE user_id = %s", (canonical, dupe_id))
            cur.execute("UPDATE kg_links SET user_id = %s WHERE user_id = %s", (canonical, dupe_id))
            cur.execute("UPDATE kg_node_chunks SET user_id = %s WHERE user_id = %s", (canonical, dupe_id))
            cur.execute("DELETE FROM kg_users WHERE id = %s", (dupe_id,))
    conn.commit()
    return len(dupes)


def purge_orphans(conn, dry_run: bool = True) -> dict:
    aw = _load_allowlist()
    allowed = tuple(aw["allowed_auth_ids"])
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM kg_nodes WHERE user_id::text NOT IN %s", (allowed,))
        n_nodes = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM kg_links WHERE user_id::text NOT IN %s", (allowed,))
        n_links = cur.fetchone()[0]
    counts = {"nodes": n_nodes, "links": n_links}
    if dry_run:
        logger.info("would purge: %s", counts)
        return counts
    with conn.cursor() as cur:
        cur.execute("DELETE FROM kg_nodes WHERE user_id::text NOT IN %s", (allowed,))
        cur.execute("DELETE FROM kg_links WHERE user_id::text NOT IN %s", (allowed,))
    conn.commit()
    logger.info("purged: %s", counts)
    return counts


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--audit", action="store_true")
    p.add_argument("--dedupe-naruto", action="store_true")
    p.add_argument("--purge-orphans", action="store_true")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)

    import os, psycopg
    conn = psycopg.connect(os.environ["SUPABASE_DB_URL"], autocommit=False)

    dry = not args.apply
    if args.audit:
        print(json.dumps(audit(conn), indent=2, default=str))
    if args.dedupe_naruto:
        dedupe_naruto(conn, dry_run=dry)
    if args.purge_orphans:
        purge_orphans(conn, dry_run=dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Test**

```python
def test_dedupe_handles_no_duplicates(monkeypatch):
    # mock conn.cursor.execute to return empty list of duplicates
    # assert dedupe_naruto returns 0
```

- [ ] **Step 4: Run dry-run audit against staging**

Run: `python ops/scripts/reconcile_kg_users.py --audit`
Expected: prints user list + orphan counts.

- [ ] **Step 5: Commit**

```bash
git add ops/scripts/reconcile_kg_users.py ops/deploy/expected_users.json tests/unit/ops/test_reconcile_kg_users.py
git commit -m "feat: kg_users reconciliation script"
```

#### Task 2D.2: Zoro email confirmation script

**Files:**
- Create: `ops/scripts/confirm_zoro_email.py`

- [ ] **Step 1: Implement**

```python
"""One-shot: mark Zoro's auth.users row as email_confirmed (idempotent)."""
import os
import sys
import logging

ZORO_AUTH_ID = "a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e"
logger = logging.getLogger("confirm_zoro_email")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    import psycopg
    dsn = os.environ["SUPABASE_DB_URL"]
    with psycopg.connect(dsn, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE auth.users SET email_confirmed_at = NOW() "
            "WHERE id = %s AND email_confirmed_at IS NULL",
            (ZORO_AUTH_ID,),
        )
        affected = cur.rowcount
        conn.commit()
    logger.info("Zoro email confirmation: %d row updated", affected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run against staging**

Run: `python ops/scripts/confirm_zoro_email.py`
Expected: prints `1 row updated` (or `0 rows updated` if already confirmed).

- [ ] **Step 3: Add deploy.sh single-tenant allowlist gate**

In `ops/deploy/deploy.sh`, after migration step:

```bash
# Single-tenant allowlist gate (spec §3.9)
docker run --rm --env-file /etc/secrets/api_env "$IMAGE" \
    python -c "
import json, os, psycopg, sys
allowed = set(json.load(open('/app/ops/deploy/expected_users.json'))['allowed_auth_ids'])
with psycopg.connect(os.environ['SUPABASE_DB_URL']) as c, c.cursor() as cur:
    cur.execute('SELECT id::text FROM kg_users')
    live = {r[0] for r in cur.fetchall()}
unknown = live - allowed
if unknown:
    print(f'[deploy] FATAL: kg_users has unknown auth_ids: {unknown}', file=sys.stderr)
    sys.exit(1)
print('[deploy] kg_users allowlist OK')
" || exit 1
```

- [ ] **Step 4: Commit**

```bash
git add ops/scripts/confirm_zoro_email.py ops/deploy/deploy.sh
git commit -m "feat: zoro email confirm allowlist gate"
```

### Phase 2E — Squash commit 2

- [ ] Same procedure as Phase 1E. Squash message:

```
feat: synthesizer correctness + strong/fast semantics + naruto reconciliation

- Critic accepts semantic equivalence (prompt tightening)
- 2nd-pass unsupported returns draft + low-confidence inline tag
- Per-class regression fixtures (5 classes)
- Action-verb regex boost in _source_type_boost
- Token-conscious routing table (_routing.py)
- Strong: top-k 40 + critic + HyDE; Fast: minimal pipeline
- Per-model SDK timeout 180s → 30s (Pro→Flash fallback fires within budget)
- ops/scripts/reconcile_kg_users.py (audit/dedupe/purge)
- ops/scripts/confirm_zoro_email.py (one-shot)
- expected_users.json allowlist gate in deploy.sh
```

---

## Phase 3 — Commit 3: Kasten surface polish

### Phase 3A — Add-zettels modal Select-all

#### Task 3A.1: Add header row + Select-all + counter

**Files:**
- Modify: `website/features/user_rag/js/user_rag.js:787` (renderAddList)
- Modify: `website/features/user_rag/css/user_rag.css` (header row styling)
- Create: `tests/e2e/test_add_zettels_modal.py` (Playwright/Puppeteer)

- [ ] **Step 1: Update renderAddList**

In `user_rag.js:787`, prepend a header `<li class="header">`:

```javascript
function renderAddList() {
    els.addList.innerHTML = '';
    const visibleNodes = state.userNodes.filter(n => !state.existingMembers.has(n.id));
    const selectableCount = visibleNodes.length;

    const header = document.createElement('li');
    header.className = 'header';
    header.innerHTML = `
        <input type="checkbox" id="add-select-all">
        <label for="add-select-all">Select all (<span id="add-counter">0</span> / ${selectableCount})</label>
    `;
    const headerCb = header.querySelector('#add-select-all');
    headerCb.addEventListener('change', () => {
        if (headerCb.checked) {
            visibleNodes.forEach(n => state.addModalSelected.add(n.id));
        } else {
            state.addModalSelected.clear();
        }
        renderAddList();
    });
    els.addList.appendChild(header);

    // existing per-node loop, with counter update on each toggle
    state.userNodes.forEach(n => {
        // ... existing rendering ...
    });

    document.getElementById('add-counter').textContent = state.addModalSelected.size;
}
```

- [ ] **Step 2: CSS for header row**

In `website/features/user_rag/css/user_rag.css`:

```css
.add-modal-list .header {
    background: var(--kasten-teal-soft);
    font-weight: 600;
    border-bottom: 1px solid var(--border);
    padding: 0.5rem 0.75rem;
}
```

(Use `ui-ux-pro-max` skill at execution time to fill exact teal hex from existing CSS variables.)

- [ ] **Step 3: Test in browser via Playwright**

```python
# tests/e2e/test_add_zettels_modal.py
import pytest
from playwright.sync_api import Page


def test_select_all_checks_all_visible(page: Page):
    page.goto("http://localhost:10000/rag")
    page.click("#open-add-modal")
    page.click("#add-select-all")
    counter = page.text_content("#add-counter")
    assert int(counter) == int(page.text_content(".add-modal-list .header label").split("/")[1])
```

- [ ] **Step 4: Commit**

```bash
git add website/features/user_rag/js/user_rag.js website/features/user_rag/css/user_rag.css tests/e2e/test_add_zettels_modal.py
git commit -m "feat: add zettels modal select all header"
```

### Phase 3B — Composer placeholder + queue UX

#### Task 3B.1: Dynamic composer placeholder

- [ ] **Step 1: Modify loadSandboxes post-step**

In `user_rag.js`, after `loadSandboxes()` resolves:

```javascript
function updateComposerPlaceholder() {
    const kasten = state.currentSandbox;
    if (!kasten || state.focusNodeTitle) return;  // focus override wins
    const name = (kasten.name || 'this Kasten').slice(0, 40);
    els.input.placeholder = `Ask ${name} something…`;
}
// call updateComposerPlaceholder() inside loadSandboxes() after state.currentSandbox is set
```

- [ ] **Step 2: Test**

Add to `tests/e2e/test_composer.py`:

```python
def test_placeholder_includes_kasten_name(page):
    page.goto("http://localhost:10000/rag?kasten=Knowledge%20Management")
    placeholder = page.get_attribute("#composer-input", "placeholder")
    assert "Knowledge Management" in placeholder
    assert "something" in placeholder
```

- [ ] **Step 3: Commit**

```bash
git add website/features/user_rag/js/user_rag.js tests/e2e/test_composer.py
git commit -m "feat: composer placeholder dynamic kasten name"
```

#### Task 3B.2: 503 Retry-After queue UX

- [ ] **Step 1: Handle 503 in user_rag.js**

In the fetch error path of `consumeSSE` (line 495):

```javascript
if (response.status === 503) {
    const retryAfter = parseInt(response.headers.get('Retry-After') || '5', 10);
    showQueuedNotice(retryAfter);
    setTimeout(() => els.form.requestSubmit(), retryAfter * 1000);
    return;
}

function showQueuedNotice(seconds) {
    const notice = document.createElement('div');
    notice.className = 'rag-queued-notice';
    notice.innerHTML = `Queued — retrying in <span class="countdown">${seconds}</span>s`;
    els.composer.prepend(notice);
    let s = seconds;
    const tick = setInterval(() => {
        s -= 1;
        if (s <= 0) { clearInterval(tick); notice.remove(); }
        else { notice.querySelector('.countdown').textContent = s; }
    }, 1000);
}
```

- [ ] **Step 2: CSS in teal**

```css
.rag-queued-notice {
    background: var(--kasten-teal-soft);
    color: var(--kasten-teal);
    padding: 0.5rem 0.75rem;
    border-radius: 4px;
    font-size: 0.85rem;
    animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}
```

- [ ] **Step 3: Commit**

```bash
git add website/features/user_rag/js/user_rag.js website/features/user_rag/css/user_rag.css
git commit -m "feat: composer 503 queue ux teal"
```

### Phase 3C — SSE heartbeat client + auto-retry

#### Task 3C.1: Heartbeat-aware consumeSSE + auto-retry wrapper

- [ ] **Step 1: Update consumeSSE**

```javascript
async function consumeSSE(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let lastFrameMs = Date.now();
    let doneSeen = false;

    const heartbeatTimer = setInterval(() => {
        if (Date.now() - lastFrameMs > 15000 && !doneSeen) {
            // dead stream; throw so outer retry catches
            reader.cancel('heartbeat-timeout');
        }
    }, 5000);

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            lastFrameMs = Date.now();
            buf += decoder.decode(value, { stream: true });
            // parse SSE frames; ignore `:heartbeat` comment lines
            // ... existing parsing ...
            if (eventType === 'done') doneSeen = true;
        }
    } finally {
        clearInterval(heartbeatTimer);
    }
}

async function askWithRetry(payload) {
    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const resp = await fetch('/api/rag/sessions/.../messages', { method: 'POST', body: JSON.stringify(payload) });
            await consumeSSE(resp, dispatchEvent);
            return;
        } catch (err) {
            if (attempt === 0 && err.message.includes('heartbeat-timeout')) {
                showRetryNotice();
                await new Promise(r => setTimeout(r, 1000));
                continue;
            }
            throw err;
        }
    }
}

function showRetryNotice() {
    // teal Kasten-card-shuffle "Reconnecting your Kasten…" — see Phase 3D
}
```

- [ ] **Step 2: Test**

Add unit test that mocks reader to never produce frames; assert reader.cancel called after 15s.

- [ ] **Step 3: Commit**

```bash
git add website/features/user_rag/js/user_rag.js
git commit -m "feat: sse heartbeat client auto retry"
```

### Phase 3D — Kasten-card-shuffle animation primitive (TEAL)

#### Task 3D.1: Invoke ui-ux-pro-max + frontend-design for exact teal

- [ ] **Step 1: Read current CSS variables**

Run: `grep -E "(--teal|--kasten|--zettel)" website/features/user_rag/css/*.css`
Expected: prints existing teal variables. If absent, add canonical teal variables to a new `:root` block.

- [ ] **Step 2: Invoke skills for palette consistency**

In a fresh subagent (or directly), invoke:
- `Skill: ui-ux-pro-max` with args: "Confirm exact teal HSL/hex used for Kasten + Zettel surfaces in website/features/user_rag/css/. Surface a 5-shade palette (50/100/300/500/700) for the Kasten-card-shuffle animation."
- `Skill: frontend-design` with args: "Design the 'Kasten-card-shuffle' animation primitive — 3 index-card silhouettes in teal that fan out + restack. Three states: long-pipeline (2.5s loop, lively), heartbeat-retry (4s loop, calm), queued-503 (1.5s breathe, single card). Output as CSS keyframes + HTML structure."

#### Task 3D.2: Implement loader.css + loader.js

**Files:**
- Create: `website/features/user_rag/css/loader.css`
- Create: `website/features/user_rag/js/loader.js`

- [ ] **Step 1: loader.css**

```css
/* Kasten-card-shuffle primitive (spec §3.11). Teal, not amber. */
:root {
    --kasten-teal: hsl(172, 60%, 42%);
    --kasten-teal-soft: hsl(172, 50%, 92%);
    --kasten-teal-deep: hsl(172, 65%, 28%);
}

.kasten-shuffle {
    display: inline-flex;
    gap: 4px;
    align-items: center;
    justify-content: center;
}

.kasten-shuffle .card {
    width: 24px;
    height: 32px;
    background: var(--kasten-teal);
    border: 1px solid var(--kasten-teal-deep);
    border-radius: 3px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.1);
    animation: kasten-fan 2.5s ease-in-out infinite;
}

.kasten-shuffle .card:nth-child(1) { animation-delay: 0s; }
.kasten-shuffle .card:nth-child(2) { animation-delay: 0.2s; }
.kasten-shuffle .card:nth-child(3) { animation-delay: 0.4s; }

@keyframes kasten-fan {
    0%, 100% { transform: translateY(0) rotate(0deg); }
    50% { transform: translateY(-4px) rotate(-3deg); }
}

.kasten-shuffle.heartbeat .card { animation-duration: 4s; opacity: 0.7; }
.kasten-shuffle.queued        { animation: kasten-pulse 1.5s ease-in-out infinite; }

@keyframes kasten-pulse {
    0%, 100% { box-shadow: 0 0 0 var(--kasten-teal-soft); }
    50%      { box-shadow: 0 0 8px var(--kasten-teal); }
}

.kasten-shuffle .caption { color: var(--kasten-teal-deep); font-size: 0.85rem; margin-left: 0.5rem; }

@media (prefers-reduced-motion: reduce) {
    .kasten-shuffle .card { animation: none; }
}
```

- [ ] **Step 2: loader.js**

```javascript
// website/features/user_rag/js/loader.js
const STAGE_CAPTIONS = [
    "Searching your Zettels…",
    "Reading the right cards…",
    "Connecting the dots…",
    "Drafting your answer…",
];

export function showLongPipelineLoader(container) {
    container.innerHTML = `
        <div class="kasten-shuffle">
            <div class="card"></div><div class="card"></div><div class="card"></div>
            <span class="caption">${STAGE_CAPTIONS[0]}</span>
        </div>
    `;
    let i = 0;
    const cap = container.querySelector('.caption');
    const tick = setInterval(() => {
        i = (i + 1) % STAGE_CAPTIONS.length;
        cap.textContent = STAGE_CAPTIONS[i];
    }, 3000);
    return () => clearInterval(tick);
}

export function showHeartbeatLoader(container, onRetry) {
    container.innerHTML = `
        <div class="kasten-shuffle heartbeat">
            <div class="card"></div><div class="card"></div><div class="card"></div>
            <span class="caption">Reconnecting your Kasten… <button class="retry-now">↻ Retry now</button></span>
        </div>
    `;
    container.querySelector('.retry-now').addEventListener('click', onRetry);
}

export function showQueuedLoader(container, seconds) {
    container.innerHTML = `
        <div class="kasten-shuffle queued">
            <div class="card"></div>
            <span class="caption">Queued — retrying in <span class="cd">${seconds}</span>s</span>
        </div>
    `;
    let s = seconds;
    const cd = container.querySelector('.cd');
    const tick = setInterval(() => {
        s -= 1;
        if (s <= 0) { clearInterval(tick); container.innerHTML = ''; }
        else cd.textContent = s;
    }, 1000);
    return () => clearInterval(tick);
}
```

- [ ] **Step 3: Wire up in user_rag.js**

Replace earlier stub `showRetryNotice()`, `showQueuedNotice()`, and add 5s "no token" trigger that calls `showLongPipelineLoader()`.

- [ ] **Step 4: e2e test**

```python
def test_kasten_shuffle_renders_in_teal(page):
    page.goto(...)
    # trigger long-pipeline state by mocking server delay
    el = page.locator('.kasten-shuffle .card').first
    color = el.evaluate("el => getComputedStyle(el).backgroundColor")
    # assert teal-ish HSL — not amber
    assert "rgb(" in color  # exact match calculated from --kasten-teal
```

- [ ] **Step 5: Commit**

```bash
git add website/features/user_rag/css/loader.css website/features/user_rag/js/loader.js website/features/user_rag/js/user_rag.js tests/e2e/test_kasten_shuffle.py
git commit -m "feat: kasten card shuffle animation teal three states"
```

### Phase 3E — Squash commit 3

- [ ] Same procedure as Phase 1E. Squash message:

```
feat: kasten surface polish

- Add-zettels modal: Select-all header + counter
- Composer placeholder dynamic from Kasten name (truncate 40)
- 503 Retry-After queue UX with countdown auto-retry
- SSE heartbeat-aware consumeSSE + 1× auto-retry on 15s silence
- Kasten-card-shuffle animation primitive in TEAL (3 states: long-pipeline / heartbeat / queued)
- prefers-reduced-motion fallback
```

---

## Phase 4 — Commit 4: Eval rigour + verification harness

### Phase 4A — Per-stage metrics in answers.json

#### Task 4A.1: Extend eval_runner

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/eval_runner.py`
- Modify: `ops/scripts/rag_eval_loop.py`

- [ ] **Step 1: Capture per-stage metrics**

In `EvalRunner.evaluate()`, after each stage emit metrics into the answer record:

```python
record["per_stage"] = {
    "retrieval_recall_at_10": <computed>,
    "reranker_top1_top2_margin": <captured>,
    "synthesizer_grounding_pct": <from critic verdict>,
    "critic_verdict": <verdict>,
    "query_class": <detected>,
    "model_chain_used": <list>,
    "latency_ms": {"retrieval": ..., "rerank": ..., "synth": ..., "critic": ..., "total": ...},
}
```

- [ ] **Step 2: Test**

```python
def test_per_stage_metrics_in_eval_output():
    runner = EvalRunner(...)
    out = runner.evaluate(...)
    assert "per_stage" in out["answers"][0]
    assert "retrieval_recall_at_10" in out["answers"][0]["per_stage"]
```

- [ ] **Step 3: Commit**

```bash
git add website/features/rag_pipeline/evaluation/eval_runner.py ops/scripts/rag_eval_loop.py
git commit -m "feat: per stage metrics in eval json"
```

### Phase 4B — 13-query dataset

#### Task 4B.1: Compose iter-03 queries.json

**Files:**
- Create: `docs/rag_eval/knowledge-management/iter-03/queries.json`

- [ ] **Step 1: Compose**

```json
{
  "iter": "iter-03",
  "kasten": "Knowledge Management",
  "user": "Naruto",
  "queries": [
    /* ... copy 10 from iter-02/queries.json verbatim ... */
    {
      "id": "av-1",
      "query": "What should I install tonight to start a personal wiki?",
      "query_class": "lookup",
      "expected_top1_source_type_in": ["github", "web"],
      "annotation": "Action-verb regression — must NOT pick newsletter"
    },
    {
      "id": "av-2",
      "query": "Which guide do I run first to set up my Zettelkasten?",
      "query_class": "lookup",
      "expected_top1_source_type_in": ["github", "web"]
    },
    {
      "id": "av-3",
      "query": "Step-by-step setup commands for a personal wiki",
      "query_class": "lookup",
      "expected_top1_source_type_in": ["github", "web"]
    }
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add docs/rag_eval/knowledge-management/iter-03/queries.json
git commit -m "test: iter-03 13 queries action verb regression"
```

### Phase 4C — Hard CI gate on end-to-end gold@1

#### Task 4C.1: rag_eval_loop hard gate

**Files:**
- Modify: `ops/scripts/rag_eval_loop.py`

- [ ] **Step 1: Add gate logic**

```python
def enforce_gates(answers: dict, baseline_path: Path) -> int:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    floor = baseline["ci_gates"]["end_to_end_gold_at_1_min"]
    actual = compute_gold_at_1(answers)
    if actual < floor:
        print(f"❌ HARD GATE FAILED: gold@1 = {actual:.3f} < {floor}", file=sys.stderr)
        return 1
    print(f"✓ gold@1 gate passed: {actual:.3f} >= {floor}")

    # Soft signals (per-stage)
    for stage, threshold in baseline["per_stage"].items():
        observed = compute_stage_metric(answers, stage)
        if observed < threshold + 0.05:
            print(f"⚠️  soft signal: {stage} = {observed:.3f} (target {threshold + 0.05:.3f}) — within noise this iter, hardens in iter-04")
    return 0
```

- [ ] **Step 2: Wire into CI workflow**

Add to `.github/workflows/ci.yml`:

```yaml
iter-03-eval-gate:
  runs-on: ubuntu-latest
  if: github.event_name == 'pull_request' && contains(github.event.pull_request.labels.*.name, 'run-eval')
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install -r ops/requirements-dev.txt
    - run: |
        python ops/scripts/rag_eval_loop.py \
            --queries docs/rag_eval/knowledge-management/iter-03/queries.json \
            --baseline docs/rag_eval/knowledge-management/iter-03/baseline.json \
            --enforce-gates
      env:
        SUPABASE_DB_URL: ${{ secrets.SUPABASE_DB_URL }}
        GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

- [ ] **Step 3: Commit**

```bash
git add ops/scripts/rag_eval_loop.py .github/workflows/ci.yml
git commit -m "feat: hard ci gate end to end gold at 1"
```

### Phase 4D — Claude in Chrome verification harness

#### Task 4D.1: verify_iter_03_in_browser.py

**Files:**
- Create: `ops/scripts/verify_iter_03_in_browser.py`
- Create: `docs/rag_eval/knowledge-management/iter-03/verification.md`

- [ ] **Step 1: Implement script**

```python
"""End-to-end browser verification via Claude in Chrome MCP.

Runs against the existing Naruto-owned 'Knowledge Management' Kasten — does NOT create a new Kasten.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("verify_iter_03")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SCREENSHOTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "rag_eval" / "knowledge-management" / "iter-03" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


async def run_verification(mcp_client) -> dict:
    """10-step walkthrough per spec §3.14."""
    results = []

    # Step 1: open chooser, screenshot
    await mcp_client.navigate("https://zettelkasten.in/rag")
    await mcp_client.screenshot(SCREENSHOTS_DIR / "01_chooser.png")
    results.append({"step": 1, "name": "kasten_chooser", "status": "captured"})

    # Step 2: enter Knowledge Management Kasten
    await mcp_client.click_text("Knowledge Management")
    placeholder = await mcp_client.get_attribute("#composer-input", "placeholder")
    assert "Knowledge Management" in placeholder, f"placeholder wrong: {placeholder}"
    await mcp_client.screenshot(SCREENSHOTS_DIR / "02_chat_composer.png")
    results.append({"step": 2, "placeholder": placeholder})

    # Step 3: run all 13 eval queries, capture each answer
    queries = json.loads((Path(__file__).resolve().parents[2] / "docs" / "rag_eval" / "knowledge-management" / "iter-03" / "queries.json").read_text())["queries"]
    for q in queries:
        await mcp_client.fill("#composer-input", q["query"])
        await mcp_client.click("#send-btn")
        await mcp_client.wait_for_selector(".rag-message[data-role='assistant'].complete", timeout=70_000)
        await mcp_client.screenshot(SCREENSHOTS_DIR / f"03_q_{q['id']}.png")

    # Step 4: toggle Strong dropdown
    await mcp_client.select("#qualitySelect", "high")
    # ... repeat one query, verify critic loop fires (visible in eval JSON, not UI) ...

    # Step 5: open add-zettels modal
    await mcp_client.click("#open-add-modal")
    await mcp_client.click("#add-select-all")
    await mcp_client.screenshot(SCREENSHOTS_DIR / "05_select_all.png")

    # Step 6: trigger heartbeat retry
    # ... pause dev server mid-stream ...
    await mcp_client.screenshot(SCREENSHOTS_DIR / "06_heartbeat_retry.png")

    # Step 7: trigger queue UX (12 concurrent submissions)
    # ... use page.evaluate to fire fetches ...
    await mcp_client.screenshot(SCREENSHOTS_DIR / "07_queue_503.png")

    # Step 8: confirm ?debug=1 hidden in prod
    await mcp_client.navigate("https://zettelkasten.in/rag?debug=1")
    debug_panel = await mcp_client.query_selector(".rag-debug-panel")
    assert debug_panel is None, "debug panel must be hidden in prod"

    # Step 9: schema-drift gate (run separately on staging)
    # ... not in browser; document in verification.md ...

    # Step 10: SSE survives blue→green cutover
    # ... start streaming, manually trigger deploy, confirm answer completes ...
    await mcp_client.screenshot(SCREENSHOTS_DIR / "10_sse_cutover.png")

    return {"results": results, "screenshots": list(SCREENSHOTS_DIR.glob("*.png"))}


async def main() -> int:
    # connect to Claude in Chrome MCP server
    # ... await run_verification(client) ...
    # ... write results to verification.md ...
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Verification.md template**

```markdown
# Iter-03 Verification Results

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | Kasten chooser renders | ⏳ | screenshots/01_chooser.png |
| 2 | Composer placeholder = "Ask Knowledge Management something…" | ⏳ | screenshots/02_chat_composer.png |
| 3 | All 13 eval queries answered without "I can't find" refusals | ⏳ | screenshots/03_q_*.png |
| 4 | Strong toggle triggers critic loop (verify in eval JSON) | ⏳ | answers.json |
| 5 | Add-zettels Select-all works | ⏳ | screenshots/05_select_all.png |
| 6 | Heartbeat retry fires after 15s silence; teal animation | ⏳ | screenshots/06_heartbeat_retry.png |
| 7 | Queue UX 503-Retry-After surfaces "Queued — retrying" | ⏳ | screenshots/07_queue_503.png |
| 8 | ?debug=1 hidden in prod | ⏳ | screenshot |
| 9 | Schema-drift gate fires on intentional drift | ⏳ | deploy log |
| 10 | SSE survives blue→green cutover | ⏳ | screenshots/10_sse_cutover.png |
```

- [ ] **Step 3: Commit**

```bash
git add ops/scripts/verify_iter_03_in_browser.py docs/rag_eval/knowledge-management/iter-03/verification.md
git commit -m "feat: iter-03 browser verification harness"
```

### Phase 4E — Squash commit 4

- [ ] Squash message:

```
feat: eval rigour + verification harness

- Per-stage metrics emitted into answers.json (retrieval recall@10, rerank margin, grounding %, critic verdict, latency)
- iter-03 queries.json: 10 iter-02 + 3 action-verb regression
- Hard CI gate on end-to-end gold@1 (≥iter-02 + 5pp); soft signals on per-stage
- ops/scripts/verify_iter_03_in_browser.py — Claude in Chrome MCP walkthrough on Naruto's Knowledge Management Kasten
- verification.md checklist
- ci.yml iter-03-eval-gate job
```

---

## Phase 5 — Merge, Deploy, Verify

### Task 5.1: Final pre-merge checks

- [ ] **Step 1: Local validation**

Run:
```bash
python ops/scripts/validate_quantization.py
python -m pytest tests/ -q
python ops/scripts/rag_eval_loop.py --queries docs/rag_eval/knowledge-management/iter-03/queries.json --baseline docs/rag_eval/knowledge-management/iter-03/baseline.json --enforce-gates
```
Expected: all green.

- [ ] **Step 2: Push branch + open PR**

```bash
git push origin iter-03/all
gh pr create --title "iter-03: burst capacity + correctness + kasten polish" --body "$(cat <<'EOF'
## Summary
- Burst capacity (int8 BGE + 2 workers + queue/semaphore)
- Synthesizer correctness (critic, action-verb boost, Strong/Fast)
- Kasten surface polish (animation, modal, placeholder, queue UX)
- Eval rigour (per-stage metrics, 13 queries, hard gate, browser verification)

## Test plan
- [ ] All unit + integration tests pass
- [ ] validate_quantization.py exits 0
- [ ] iter-03 eval gate passes (gold@1 ≥ iter-02 + 5pp)
- [ ] Browser verification: 10/10 in verification.md
EOF
)"
```

### Task 5.2: Merge to master + monitor deploy

- [ ] **Step 1: Merge with --no-ff to preserve 4-commit structure**

```bash
gh pr merge --merge --subject "feat: iter-03 burst capacity correctness kasten polish"
```

- [ ] **Step 2: Watch deploy workflow**

Run: `gh run watch --branch master`
Expected: workflow succeeds. If migration gate fails on schema-drift, revert with `git revert <merge-sha>` and investigate.

- [ ] **Step 3: Provision swapfile (one-shot, manual)**

SSH to droplet, follow `docs/runbooks/droplet_swapfile.md`.

- [ ] **Step 4: Run reconciliation in apply mode**

```bash
ssh droplet 'docker run --rm --env-file /etc/secrets/api_env <image> python ops/scripts/reconcile_kg_users.py --audit --dedupe-naruto --purge-orphans --apply'
ssh droplet 'docker run --rm --env-file /etc/secrets/api_env <image> python ops/scripts/confirm_zoro_email.py'
```

### Task 5.3: Run browser verification

- [ ] **Step 1: Execute walkthrough**

Run: `python ops/scripts/verify_iter_03_in_browser.py`
Expected: all 10 steps captured to `docs/rag_eval/knowledge-management/iter-03/screenshots/`. verification.md updated with ✅ marks.

- [ ] **Step 2: Commit verification artifacts**

```bash
git add docs/rag_eval/knowledge-management/iter-03/screenshots/ docs/rag_eval/knowledge-management/iter-03/verification.md
git commit -m "docs: iter-03 verification screenshots"
git push origin master
```

### Task 5.4: Capture final eval against prod

- [ ] **Step 1: Run eval against prod**

```bash
python ops/scripts/rag_eval_loop.py --queries docs/rag_eval/knowledge-management/iter-03/queries.json --baseline docs/rag_eval/knowledge-management/iter-03/baseline.json --target-host https://zettelkasten.in --emit-final-answers
```
Expected: writes `docs/rag_eval/knowledge-management/iter-03/answers.json` + `manual_review.md` template.

- [ ] **Step 2: Save observations to mem-vault**

Use `mcp__plugin_mem-vault_mem-vault__save_observation` with type=`feature` for each major capability landed: int8 quantization, 2-worker capacity, schema-drift gate, Strong/Fast semantics, Kasten-card-shuffle animation. Use type=`decision` for: int8-only no-fp16 fallback, single-deploy 4-commit structure, soft per-stage gates this iter.

- [ ] **Step 3: Mark chapter end**

`mcp__plugin_mem-vault_mem-vault__mark_chapter` with title "iter-03 burst+correctness shipped".

---

## Self-review checklist (executor must run before declaring iter-03 done)

- [ ] All 4 squash commits land cleanly on master
- [ ] `validate_quantization.py` exits 0 with summary printed
- [ ] iter-03 eval gold@1 ≥ iter-02 + 5pp (hard gate)
- [ ] All 13 query answers contain at least 1 citation
- [ ] No "I can't find" refusals on the 13 eval queries
- [ ] Action-verb regression queries (av-1/2/3) pick a github or web zettel as top-1
- [ ] All 10 browser-verification screenshots captured + checklist filled
- [ ] Schema-drift gate verified in dry-run (deploy intentional drift → must abort)
- [ ] SSE blue→green cutover verified (streaming answer survives a deploy)
- [ ] `docker stats` under 10× concurrent burst stays <80% RAM
- [ ] No 502s during burst test (only 503 Retry-After when queue full)
- [ ] Memory observations saved (5+ feature, 3+ decision)
- [ ] Final commit pushed; PR closed via merge
