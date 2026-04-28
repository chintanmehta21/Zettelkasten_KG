"""Grid-search per-class margin threshold that maximizes calibration-set F1.

Spec 3.15 layer 6. Reads ``models/bge_calibration_pairs.parquet``, scores each
pair with the int8 ONNX, then picks the threshold that maximises F1 between
positive and negative score distributions per query_class. Writes the tuned
table back to ``website/features/rag_pipeline/retrieval/_int8_thresholds.json``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS_PATH = (
    ROOT / "website" / "features" / "rag_pipeline" / "retrieval" / "_int8_thresholds.json"
)


def grid_search_threshold(scores_pos: np.ndarray, scores_neg: np.ndarray) -> float:
    """Find the threshold maximising F1 across pos/neg score distributions."""
    candidates = np.linspace(0.05, 0.95, 91)
    best_thr, best_f1 = 0.50, 0.0
    for thr in candidates:
        tp = float((scores_pos >= thr).sum())
        fn = float((scores_pos < thr).sum())
        fp = float((scores_neg >= thr).sum())
        precision = tp / max(tp + fp, 1.0)
        recall = tp / max(tp + fn, 1.0)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        if f1 > best_f1:
            best_f1, best_thr = f1, float(thr)
    return best_thr


def main(argv: list[str] | None = None) -> int:
    import onnxruntime as ort
    import pandas as pd

    from website.features.rag_pipeline.rerank.cascade import _score_one

    p = argparse.ArgumentParser()
    p.add_argument("--int8-onnx", default=str(ROOT / "models" / "bge-reranker-base-int8.onnx"))
    p.add_argument("--calib", default=str(ROOT / "models" / "bge_calibration_pairs.parquet"))
    args = p.parse_args(argv)

    sess = ort.InferenceSession(args.int8_onnx, providers=["CPUExecutionProvider"])
    pairs = pd.read_parquet(args.calib)
    pairs["int8_score"] = [
        _score_one(sess, row["query"], row["chunk_text"]) for _, row in pairs.iterrows()
    ]

    thresholds: dict[str, float | str] = {}
    numeric: list[float] = []
    for cls in pairs["query_class"].unique():
        sub = pairs[pairs["query_class"] == cls]
        pos = sub[sub["label"] == 1]["int8_score"].to_numpy()
        neg = sub[sub["label"] == 0]["int8_score"].to_numpy()
        thr = grid_search_threshold(pos, neg)
        thresholds[str(cls)] = thr
        numeric.append(thr)
    thresholds["default"] = float(np.mean(numeric)) if numeric else 0.50
    thresholds["_note"] = "Auto-tuned by ops/scripts/tune_int8_thresholds.py"

    THRESHOLDS_PATH.write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    print(json.dumps(thresholds, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
