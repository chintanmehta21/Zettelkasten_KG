"""Iter-03 §9: refresh wrapper.

End-to-end calibration + int8 refresh. Used by the manual one-liner
fallback AND by .github/workflows/check_calibration_drift.yml after the
drift detector flags a refresh as needed.

Steps:
1. ops/scripts/build_calibration_set.py -> writes models/bge_calibration_pairs.parquet
2. ops/scripts/quantize_bge_int8.py     -> writes models/bge-reranker-base-int8.onnx
3. Pull fresh corpus stats from Supabase
4. Update models/calibration_baseline.json with fresh sha256s + corpus_stats
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("refresh_calibration_and_int8")


def _run_subprocess(cmd: list[str], **kwargs) -> int:
    logger.info("running: %s", " ".join(cmd))
    return subprocess.run(cmd, check=True, **kwargs).returncode


def _sha256(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def _pull_current_corpus_stats() -> dict:
    from ops.scripts.check_corpus_drift import _load_supabase_stats
    return _load_supabase_stats()


def refresh(
    *,
    calibration_path: Path,
    int8_path: Path,
    baseline_path: Path,
) -> int:
    _run_subprocess([sys.executable, str(ROOT / "ops" / "scripts" / "build_calibration_set.py"),
                     "--out", str(calibration_path)])
    _run_subprocess([sys.executable, str(ROOT / "ops" / "scripts" / "quantize_bge_int8.py"),
                     "--calib", str(calibration_path), "--out", str(int8_path)])
    stats = _pull_current_corpus_stats()
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    payload["calibrated_at"] = date.today().isoformat()
    payload["calibration_parquet_sha256"] = _sha256(calibration_path)
    payload["int8_onnx_sha256"] = _sha256(int8_path)
    payload["corpus_stats"] = stats
    baseline_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("baseline updated: %s", baseline_path)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--calibration", default=str(ROOT / "models" / "bge_calibration_pairs.parquet"))
    p.add_argument("--int8", default=str(ROOT / "models" / "bge-reranker-base-int8.onnx"))
    p.add_argument("--baseline", default=str(ROOT / "models" / "calibration_baseline.json"))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return refresh(
        calibration_path=Path(args.calibration),
        int8_path=Path(args.int8),
        baseline_path=Path(args.baseline),
    )


if __name__ == "__main__":
    sys.exit(main())
