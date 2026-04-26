"""rag_eval quality gate.

Loads the most recent (or specified) ``iter-NN/eval.json`` for a given source
and asserts every threshold passes. Exits 0 on PASS, 1 on FAIL. Designed to
run locally or in CI; CI wiring is intentionally deferred (a separate iter
will gate deploys on this script once thresholds have been observed for a
few production cycles).

Usage:
    python ops/scripts/rag_eval_quality_gate.py --source youtube
    python ops/scripts/rag_eval_quality_gate.py --source youtube --iter 7
    python ops/scripts/rag_eval_quality_gate.py --source youtube \\
        --docs-root ./docs

Thresholds (iter-07 baseline; tighten in future iters):
    composite           >= 88
    faithfulness_score  >= 80
    retrieval           >= 95   (component_scores.retrieval)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


COMPOSITE_MIN = 88.0
FAITHFULNESS_MIN = 80.0
RETRIEVAL_MIN = 95.0

_ITER_DIR_RE = re.compile(r"^iter-(\d+)$")


def _list_iter_dirs(source_dir: Path) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    if not source_dir.exists():
        return out
    for child in source_dir.iterdir():
        m = _ITER_DIR_RE.match(child.name)
        if m and child.is_dir() and (child / "eval.json").is_file():
            out.append((int(m.group(1)), child))
    out.sort(key=lambda x: x[0])
    return out


def _resolve_iter_dir(docs_root: Path, source: str, iter_num: int | None) -> Path:
    source_dir = docs_root / "rag_eval" / source
    iters = _list_iter_dirs(source_dir)
    if not iters:
        raise SystemExit(f"No eval.json found under {source_dir}")
    if iter_num is None:
        return iters[-1][1]
    for n, path in iters:
        if n == iter_num:
            return path
    raise SystemExit(f"iter-{iter_num:02d} not found under {source_dir}")


def _load_eval(iter_dir: Path) -> dict:
    return json.loads((iter_dir / "eval.json").read_text(encoding="utf-8"))


def _check_thresholds(report: dict) -> tuple[bool, list[str]]:
    failures: list[str] = []

    composite = float(report.get("composite") or 0.0)
    if composite < COMPOSITE_MIN:
        failures.append(
            f"composite {composite:.2f} < {COMPOSITE_MIN:.2f}"
        )

    faithfulness = float(report.get("faithfulness_score") or 0.0)
    if faithfulness < FAITHFULNESS_MIN:
        failures.append(
            f"faithfulness {faithfulness:.2f} < {FAITHFULNESS_MIN:.2f}"
        )

    retrieval = float(
        (report.get("component_scores") or {}).get("retrieval") or 0.0
    )
    if retrieval < RETRIEVAL_MIN:
        failures.append(
            f"retrieval {retrieval:.2f} < {RETRIEVAL_MIN:.2f}"
        )

    return (not failures, failures)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="rag_eval quality gate")
    parser.add_argument("--source", required=True, help="e.g. youtube, github")
    parser.add_argument(
        "--iter", dest="iter_num", type=int, default=None,
        help="Iter number (zero-padded if needed). Defaults to most recent.",
    )
    parser.add_argument(
        "--docs-root", default=str(Path(__file__).resolve().parents[2] / "docs"),
        help="Root containing rag_eval/<source>/iter-NN/. Defaults to ./docs.",
    )
    args = parser.parse_args(argv)

    docs_root = Path(args.docs_root)
    iter_dir = _resolve_iter_dir(docs_root, args.source, args.iter_num)
    report = _load_eval(iter_dir)

    passed, failures = _check_thresholds(report)
    if passed:
        print(
            f"PASS {args.source} {iter_dir.name}: "
            f"composite={report.get('composite'):.2f}, "
            f"faithfulness={report.get('faithfulness_score'):.2f}, "
            f"retrieval={(report.get('component_scores') or {}).get('retrieval'):.2f}"
        )
        return 0

    print(f"FAIL {args.source} {iter_dir.name}:")
    for line in failures:
        print(f"  - {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
