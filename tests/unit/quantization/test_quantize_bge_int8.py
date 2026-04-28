"""Tests for the int8 quantization script.

The actual quantization run requires the fp32 BGE ONNX (~440 MB) and produces
the int8 artifact. Those steps are exercised manually on the droplet -- here
we verify the script imports cleanly, raises the right errors, and that the
artifact-validation tests are skipped when the heavy file is absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_quantize_module_importable():
    from ops.scripts.quantize_bge_int8 import quantize_to_int8

    assert callable(quantize_to_int8)


def test_quantize_raises_when_fp32_missing(tmp_path):
    from ops.scripts.quantize_bge_int8 import quantize_to_int8

    fake_calib = tmp_path / "calib.parquet"
    fake_calib.write_bytes(b"not really a parquet")
    with pytest.raises(FileNotFoundError, match="fp32 model missing"):
        quantize_to_int8(
            fp32_model_path=tmp_path / "missing.onnx",
            calibration_pairs_path=fake_calib,
            out_path=tmp_path / "out.onnx",
        )


def test_quantize_raises_when_calibration_missing(tmp_path):
    from ops.scripts.quantize_bge_int8 import quantize_to_int8

    fake_fp32 = tmp_path / "fp32.onnx"
    fake_fp32.write_bytes(b"placeholder")
    with pytest.raises(FileNotFoundError, match="calibration set missing"):
        quantize_to_int8(
            fp32_model_path=fake_fp32,
            calibration_pairs_path=tmp_path / "missing.parquet",
            out_path=tmp_path / "out.onnx",
        )


@pytest.mark.skipif(
    not Path("models/bge-reranker-base.onnx").exists(),
    reason="fp32 base ONNX not present - run ops/scripts/export_bge_onnx.py first",
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


@pytest.mark.skipif(
    not Path("models/bge-reranker-base.onnx").exists(),
    reason="fp32 base ONNX not present",
)
def test_int8_model_smaller_than_fp32(tmp_path):
    from ops.scripts.quantize_bge_int8 import quantize_to_int8

    out = tmp_path / "bge_int8.onnx"
    quantize_to_int8(
        fp32_model_path=Path("models/bge-reranker-base.onnx"),
        calibration_pairs_path=Path("models/bge_calibration_pairs.parquet"),
        out_path=out,
    )
    fp32_size = Path("models/bge-reranker-base.onnx").stat().st_size
    int8_size = out.stat().st_size
    assert int8_size < fp32_size * 0.40, f"int8 not smaller enough: {int8_size}/{fp32_size}"


@pytest.mark.skipif(
    not Path("models/bge-reranker-base-int8.onnx").exists(),
    reason="int8 ONNX not present - run ops/scripts/quantize_bge_int8.py first",
)
def test_int8_model_classifier_head_in_fp32():
    """Layer 2: classifier head must remain fp32 for accuracy."""
    try:
        import onnx
    except ImportError:
        pytest.skip("onnx package not installed (CI test env doesn't include it)")

    out = Path("models/bge-reranker-base-int8.onnx")
    model = onnx.load(str(out))
    classifier_ops = [n for n in model.graph.node if "classifier" in n.name.lower()]
    for op in classifier_ops:
        assert op.op_type != "QLinearMatMul", f"classifier op {op.name} was quantized"
