"""rag_eval_v2 — thin wrapper over ops/scripts/post_iter_audit.py::run_audit.

Offline, read-only. Re-uses the v1 file-parsing audit (no live env, no DB).
``run_eval_v2.py`` already calls run_audit at the end of a run; this wrapper
is for re-running the audit standalone against an existing iter dir.

Usage:
    python docs/rag_eval_v2/scripts/post_iter_v2.py --kasten economics --iter 1
    python docs/rag_eval_v2/scripts/post_iter_v2.py --iter-dir docs/rag_eval_v2/economics/iter-1
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RAG_EVAL_V2 = ROOT / "docs" / "rag_eval_v2"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="rag_eval_v2 post-iter audit wrapper")
    p.add_argument("--kasten", choices=["psychedelic-drugs", "economics"])
    p.add_argument("--iter", type=int, dest="iter_n")
    p.add_argument("--iter-dir", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.iter_dir:
        iter_dir = Path(args.iter_dir)
    elif args.kasten and args.iter_n is not None:
        iter_dir = RAG_EVAL_V2 / args.kasten / f"iter-{args.iter_n}"
    else:
        raise SystemExit("Provide --iter-dir OR (--kasten AND --iter)")
    if not iter_dir.exists():
        raise SystemExit(f"iter dir not found: {iter_dir}")

    from ops.scripts.post_iter_audit import run_audit

    findings = run_audit(iter_dir)
    out = iter_dir / "post_iter_audit.md"
    findings.write_report(out)
    print(f"Wrote {out}")
    print(
        f"composite={findings.composite}  "
        f"accuracy_user_visible={findings.accuracy_user_visible}  "
        f"failed_gold_at_1={len(findings.failed_gold_at_1)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
