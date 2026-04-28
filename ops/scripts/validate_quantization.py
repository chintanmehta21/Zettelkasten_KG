"""Pre-merge gate: int8 quantization quality must match fp32 within thresholds.

Refuses commit (exit 1) if any of:
  * Per-class gold@1 delta > 1pp from fp32
  * Margin distribution KL divergence > 0.05
  * Top-1 vs top-2 separation < 0.8x fp32 baseline
  * p95 rerank latency reduction < 30%

Per spec 3.15 layer 8. fp16 is NOT permitted as escape -- emits which
Layer 1-7 knob to adjust.
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

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("validate_quantization")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

GOLD_AT_1_DELTA_MAX = 0.01    # 1pp
KL_DIVERGENCE_MAX = 0.05
MARGIN_RATIO_MIN = 0.80
LATENCY_REDUCTION_MIN = 0.30  # 30%


def kl_divergence(p: np.ndarray, q: np.ndarray, bins: int = 50) -> float:
    """Histogram-binned KL(p || q). Robust to identical-input edge case."""
    p_hist, edges = np.histogram(p, bins=bins, density=True)
    q_hist, _ = np.histogram(q, bins=edges, density=True)
    p_hist = p_hist + 1e-9
    q_hist = q_hist + 1e-9
    return float(np.sum(p_hist * np.log(p_hist / q_hist)))


def evaluate(
    pairs,
    fp32_session,
    int8_session,
) -> tuple[list[str], dict]:
    """Score every calibration pair and return (failures, summary)."""
    from website.features.rag_pipeline.rerank.cascade import _score_one

    fp32_scores: list[float] = []
    int8_scores: list[float] = []
    fp32_lats: list[float] = []
    int8_lats: list[float] = []

    for _, row in pairs.iterrows():
        t0 = time.perf_counter()
        fp32_scores.append(_score_one(fp32_session, row["query"], row["chunk_text"]))
        fp32_lats.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        int8_scores.append(_score_one(int8_session, row["query"], row["chunk_text"]))
        int8_lats.append((time.perf_counter() - t0) * 1000)

    pairs = pairs.copy()
    pairs["fp32"] = fp32_scores
    pairs["int8"] = int8_scores

    failures: list[str] = []

    # Per-class gold@1 delta
    for cls in pairs["query_class"].unique():
        sub = pairs[pairs["query_class"] == cls].copy()
        for backend in ("fp32", "int8"):
            top = sub.sort_values(backend, ascending=False).iloc[0]
            sub[f"top_is_pos_{backend}"] = top["label"] == 1
        f32_g1 = sub["top_is_pos_fp32"].mean()
        i8_g1 = sub["top_is_pos_int8"].mean()
        delta = float(f32_g1 - i8_g1)
        if delta > GOLD_AT_1_DELTA_MAX:
            failures.append(
                f"class={cls} gold@1 delta={delta:.4f} > {GOLD_AT_1_DELTA_MAX} - "
                f"adjust Layer 1 (more calibration pairs) or Layer 6 (re-tune threshold)"
            )

    # KL divergence
    kl = kl_divergence(np.array(fp32_scores), np.array(int8_scores))
    if kl > KL_DIVERGENCE_MAX:
        failures.append(
            f"score-distribution KL={kl:.4f} > {KL_DIVERGENCE_MAX} - "
            f"adjust Layer 4 (refit score calibration) or Layer 2 (exclude more nodes from quantize)"
        )

    # Top-1 vs top-2 margin
    fp32_margins, int8_margins = [], []
    for _q, grp in pairs.groupby("query"):
        s32 = grp.sort_values("fp32", ascending=False)
        if len(s32) >= 2:
            fp32_margins.append(float(s32.iloc[0]["fp32"] - s32.iloc[1]["fp32"]))
        s8 = grp.sort_values("int8", ascending=False)
        if len(s8) >= 2:
            int8_margins.append(float(s8.iloc[0]["int8"] - s8.iloc[1]["int8"]))
    margin_ratio = None
    if fp32_margins and int8_margins:
        margin_ratio = statistics.median(int8_margins) / max(
            statistics.median(fp32_margins), 1e-9
        )
        if margin_ratio < MARGIN_RATIO_MIN:
            failures.append(
                f"margin ratio={margin_ratio:.3f} < {MARGIN_RATIO_MIN} - "
                f"adjust Layer 4 (recalibrate score scale) or Layer 7 (enable TTA)"
            )

    fp32_p95 = float(np.percentile(fp32_lats, 95))
    int8_p95 = float(np.percentile(int8_lats, 95))
    reduction = (fp32_p95 - int8_p95) / max(fp32_p95, 1e-9)
    if reduction < LATENCY_REDUCTION_MIN:
        failures.append(
            f"latency reduction={reduction:.2%} < {LATENCY_REDUCTION_MIN:.0%} - "
            f"verify CPU has AVX-VNNI; check ORT thread settings"
        )

    summary = {
        "fp32_p95_ms": fp32_p95,
        "int8_p95_ms": int8_p95,
        "latency_reduction_pct": reduction * 100,
        "kl_divergence": kl,
        "margin_ratio": margin_ratio,
    }
    return failures, summary


def main(argv: list[str] | None = None) -> int:
    import onnxruntime as ort
    import pandas as pd

    p = argparse.ArgumentParser()
    p.add_argument("--fp32-onnx", default=str(ROOT / "models" / "bge-reranker-base.onnx"))
    p.add_argument("--int8-onnx", default=str(ROOT / "models" / "bge-reranker-base-int8.onnx"))
    p.add_argument("--calib", default=str(ROOT / "models" / "bge_calibration_pairs.parquet"))
    args = p.parse_args(argv)

    pairs = pd.read_parquet(args.calib)
    fp32 = ort.InferenceSession(args.fp32_onnx, providers=["CPUExecutionProvider"])
    int8 = ort.InferenceSession(args.int8_onnx, providers=["CPUExecutionProvider"])

    failures, summary = evaluate(pairs, fp32, int8)

    if failures:
        logger.error("QUANTIZATION VALIDATION FAILED:")
        for f in failures:
            logger.error("  - %s", f)
        logger.error(
            "fp16 fallback is NOT permitted per spec 3.15. Adjust the indicated layer and re-run."
        )
        return 1

    logger.info("[ok] all quantization checks passed")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
