#!/usr/bin/env python3
"""Export BAAI/bge-reranker-base to ONNX and record its source revision."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from huggingface_hub import model_info

MODEL_ID = "BAAI/bge-reranker-base"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export BGE reranker to ONNX")
    parser.add_argument("output_dir", type=Path, help="Directory where the ONNX export will be written")
    parser.add_argument("--no-quantize", action="store_true", help="Skip dynamic INT8 quantization")
    args = parser.parse_args()

    try:
        from optimum.onnxruntime import ORTModelForSequenceClassification, ORTQuantizer
        from optimum.onnxruntime.configuration import AutoQuantizationConfig
        from transformers import AutoTokenizer
    except ImportError:
        print("Install export dependencies first: pip install optimum[onnxruntime] transformers torch")
        sys.exit(1)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    model = ORTModelForSequenceClassification.from_pretrained(MODEL_ID, export=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)

    onnx_dir = output_dir / "onnx"
    onnx_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(onnx_dir)
    tokenizer.save_pretrained(output_dir)

    if not args.no_quantize:
        quantizer = ORTQuantizer.from_pretrained(onnx_dir)
        quantizer.quantize(
            save_dir=onnx_dir,
            quantization_config=AutoQuantizationConfig.avx2(is_static=False),
        )

    info = model_info(MODEL_ID)
    metadata = {"model_id": MODEL_ID, "source_sha": info.sha}
    (output_dir / "export_metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    size_mb = sum(path.stat().st_size for path in output_dir.rglob("*") if path.is_file()) / 1024 / 1024
    print(f"Export complete: {output_dir}")
    print(f"Source revision: {info.sha}")
    print(f"Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
