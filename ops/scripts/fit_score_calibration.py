"""Fit a tiny linear regression: fp32_score = a * int8_score + b.

Applied at runtime in cascade.py to recover score scale post-quantization
(spec 3.15 layer 4).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from collections.abc import Iterable
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger("fit_score_calibration")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def fit_calibration(int8_scores: Iterable[float], fp32_scores: Iterable[float]) -> tuple[float, float]:
    """Linear regression: returns (a, b) such that fp32 ~= a*int8 + b."""
    x = np.asarray(list(int8_scores), dtype=np.float64)
    y = np.asarray(list(fp32_scores), dtype=np.float64)
    if x.shape != y.shape or len(x) < 2:
        raise ValueError("need >=2 paired points")
    a, b = np.polyfit(x, y, deg=1)
    return float(a), float(b)


def _score_pair_via_session(session, query: str, chunk: str) -> float:
    """Run a single rerank pair through an ORT session.

    Loaded lazily so the unit tests that only exercise ``fit_calibration`` do
    not require onnxruntime / the BGE tokenizer to be installed.
    """
    from website.features.rag_pipeline.rerank.cascade import _score_one  # type: ignore[attr-defined]

    return _score_one(session, query, chunk)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fp32-onnx", default=str(ROOT / "models" / "bge-reranker-base.onnx"))
    p.add_argument("--int8-onnx", default=str(ROOT / "models" / "bge-reranker-base-int8.onnx"))
    p.add_argument("--calib", default=str(ROOT / "models" / "bge_calibration_pairs.parquet"))
    p.add_argument(
        "--out",
        default=str(
            ROOT / "website" / "features" / "rag_pipeline" / "rerank" / "_int8_score_cal.json"
        ),
    )
    args = p.parse_args(argv)

    import onnxruntime as ort
    import pandas as pd

    pairs = pd.read_parquet(args.calib)
    fp32_sess = ort.InferenceSession(args.fp32_onnx, providers=["CPUExecutionProvider"])
    int8_sess = ort.InferenceSession(args.int8_onnx, providers=["CPUExecutionProvider"])

    int8_scores: list[float] = []
    fp32_scores: list[float] = []
    for _, row in pairs.iterrows():
        int8_scores.append(_score_pair_via_session(int8_sess, row["query"], row["chunk_text"]))
        fp32_scores.append(_score_pair_via_session(fp32_sess, row["query"], row["chunk_text"]))

    a, b = fit_calibration(int8_scores, fp32_scores)
    payload = {
        "a": a,
        "b": b,
        "n_points": len(int8_scores),
        "fitted_at": _dt.datetime.utcnow().isoformat() + "Z",
        "calibration_sha256": "set_by_build_calibration_set.py",
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("calibration fit: a=%.4f b=%.4f n=%d", a, b, len(int8_scores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
