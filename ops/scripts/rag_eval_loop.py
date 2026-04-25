"""rag_eval iteration CLI - two-phase auto-resume.

Mirrors ops/scripts/eval_loop.py shape; sources: youtube|reddit|github|newsletter.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.rag_eval_state import detect_state, IterState

ARTIFACT_ROOT = Path("docs/rag_eval")
HALT_FILE = ARTIFACT_ROOT / ".halt"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--source",
        choices=["youtube", "reddit", "github", "newsletter"],
        required=True,
    )
    p.add_argument("--iter", type=int, required=True, dest="iter_num")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-determinism", action="store_true")
    p.add_argument("--skip-breadth", action="store_true")
    p.add_argument(
        "--unseal-heldout",
        action="store_true",
        help="Allow loading heldout.yaml (final iter only).",
    )
    p.add_argument(
        "--auto",
        action="store_true",
        help="Run Phase A + dispatch reviewer + Phase B without pausing.",
    )
    return p.parse_args(argv)


async def _run_phase_a(args: argparse.Namespace) -> dict:
    """Stub - real implementation lands in Task 3.7."""
    return {"status": "phase_a_stub", "source": args.source, "iter": args.iter_num}


async def _run_phase_b(args: argparse.Namespace) -> dict:
    return {"status": "phase_b_stub", "source": args.source, "iter": args.iter_num}


def _cli_dispatch(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if HALT_FILE.exists():
        print(f"HALTED: {HALT_FILE.read_text(encoding='utf-8')}")
        return 1
    iter_dir = ARTIFACT_ROOT / args.source / f"iter-{args.iter_num:02d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    state = detect_state(iter_dir)

    if args.dry_run:
        print(
            json.dumps(
                {"status": "dry_run", "state": state.value, "iter_dir": str(iter_dir)},
                indent=2,
            )
        )
        return 0

    if state == IterState.PHASE_A_REQUIRED:
        result = asyncio.run(_run_phase_a(args))
    elif state == IterState.AWAITING_MANUAL_REVIEW:
        if not args.auto:
            print(f"AWAITING_MANUAL_REVIEW - write {iter_dir}/manual_review.md")
            return 0
        result = {"status": "auto_review_dispatch_stub"}
    elif state == IterState.PHASE_B_REQUIRED:
        result = asyncio.run(_run_phase_b(args))
    else:
        result = {"status": "already_committed"}

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli_dispatch())
