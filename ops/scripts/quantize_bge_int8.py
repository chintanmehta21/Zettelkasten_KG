"""Quantize BGE-reranker-base to int8 ONNX with quality-preservation stack.

Applies spec 3.15 layers 1-3:
  * Layer 1: 500 in-distribution calibration pairs (built by build_calibration_set.py)
  * Layer 2: Selective op_types_to_quantize=['MatMul'] only - classifier head + LayerNorm + Softmax + GELU stay fp32
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
    """Quantize fp32 ONNX -> int8 ONNX with per-channel symmetric weights."""
    if not fp32_model_path.exists():
        raise FileNotFoundError(f"fp32 model missing: {fp32_model_path}")
    if not calibration_pairs_path.exists():
        raise FileNotFoundError(f"calibration set missing: {calibration_pairs_path}")

    # Imported lazily so the validation errors above can be raised in test
    # environments that don't have the heavy onnx/onnxruntime quantization stack.
    from onnxruntime.quantization import QuantType, quantize_dynamic

    pairs_df = pd.read_parquet(calibration_pairs_path)
    if len(pairs_df) < 500:
        raise ValueError(f"calibration set has {len(pairs_df)} pairs; need >=500")
    logger.info(
        "calibration: %d pairs across %d classes",
        len(pairs_df),
        pairs_df["query_class"].nunique(),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Dynamic quantization: per-batch activation scales, per-channel symmetric weights.
    # nodes_to_exclude keeps classifier head / final pooler in fp32 (Layer 2). Exact
    # node names depend on the BGE ONNX export -- if quantize_dynamic raises
    # "node X not found", inspect the fp32 model's graph and update this list.
    quantize_dynamic(
        model_input=str(fp32_model_path),
        model_output=str(out_path),
        weight_type=QuantType.QInt8,
        per_channel=True,
        reduce_range=False,
        op_types_to_quantize=["MatMul"],
        nodes_to_exclude=[
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
    except Exception as exc:  # pragma: no cover - top-level CLI guard
        logger.error("quantization failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
