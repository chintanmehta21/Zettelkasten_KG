"""iter-08 G7 canary: A/B test the cite-hygiene flag.

Runs the iter-08 eval twice — once with RAG_CITE_HYGIENE_ENABLED=false then
again with =true — diffs the regression-risk targets (q1/q4/q11), and exits
0 if no pass→fail flips, 1 otherwise.

NOTE: This script flips RAG_CITE_HYGIENE_ENABLED in its OWN environment only.
The droplet's container env is what actually drives behaviour, so the
operator must flip the droplet flag (via gh workflow dispatch / droplet
env edit) between the two passes when prompted. The local env flip is
informational and serves as a guard for any locally-evaluated path that
honours the variable.

The eval harness (`eval_iter_03_playwright.py`) accepts --iter as a path
fragment under docs/rag_eval/common/knowledge-management/, so passing
"iter-08/_canary_off" and "iter-08/_canary_on" routes outputs to those
subdirs cleanly. queries.json must exist in each subdir before the run —
the bootstrap copies it from iter-08/queries.json automatically.

Usage:
    python ops/scripts/canary_cite_hygiene.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ITER_DIR = REPO_ROOT / "docs" / "rag_eval" / "common" / "knowledge-management" / "iter-08"
EVAL_SCRIPT = REPO_ROOT / "ops" / "scripts" / "eval_iter_03_playwright.py"
MINT_SCRIPT = REPO_ROOT / "ops" / "scripts" / "mint_eval_jwt.py"
TARGET_QIDS = ("q1", "q4", "q11")


def _ensure_token() -> str:
    tok = os.environ.get("ZK_BEARER_TOKEN")
    if tok:
        return tok
    proc = subprocess.run(
        [sys.executable, str(MINT_SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
    )
    token = proc.stdout.strip()
    if not token:
        raise RuntimeError("mint_eval_jwt.py produced no token")
    os.environ["ZK_BEARER_TOKEN"] = token
    return token


def _bootstrap_subdir(subdir: str) -> Path:
    """Ensure iter-08/<subdir>/queries.json exists by copying from iter-08."""
    out = ITER_DIR / subdir
    out.mkdir(parents=True, exist_ok=True)
    src_q = ITER_DIR / "queries.json"
    dst_q = out / "queries.json"
    if src_q.exists() and not dst_q.exists():
        shutil.copy2(src_q, dst_q)
    return out


def _run_eval(env_value: str, out_subdir: str) -> Path:
    """Run iter-08 eval with given RAG_CITE_HYGIENE_ENABLED, write to subdir.

    Returns path to verification_results.json.
    """
    env = {**os.environ, "RAG_CITE_HYGIENE_ENABLED": env_value}
    out = _bootstrap_subdir(out_subdir)
    print(
        f"\n=== Running eval with RAG_CITE_HYGIENE_ENABLED={env_value} "
        f"(output: iter-08/{out_subdir}) ==="
    )
    subprocess.run(
        [sys.executable, str(EVAL_SCRIPT), "--iter", f"iter-08/{out_subdir}"],
        env=env,
        check=True,
    )
    results = out / "verification_results.json"
    if not results.exists():
        raise FileNotFoundError(f"Expected {results} not produced")
    return results


def _load_results(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("results", data)
    return {row["qid"]: row for row in rows if isinstance(row, dict) and "qid" in row}


def diff_target_qids(off_path: Path, on_path: Path) -> int:
    """Print markdown diff for q1/q4/q11; return 1 if any flipped pass→fail, else 0."""
    off = _load_results(off_path)
    on = _load_results(on_path)
    print("\n## Cite-hygiene canary diff (q1/q4/q11)\n")
    print("| qid | off: gold@1, verdict | on: gold@1, verdict | delta |")
    print("|-----|----------------------|---------------------|-------|")
    regressed = False
    for qid in TARGET_QIDS:
        o = off.get(qid, {})
        n = on.get(qid, {})
        off_g1 = float(o.get("gold_at_1", 0.0) or 0.0)
        on_g1 = float(n.get("gold_at_1", 0.0) or 0.0)
        off_v = o.get("verdict", "?")
        on_v = n.get("verdict", "?")
        delta = on_g1 - off_g1
        flipped = (off_v == "pass" and on_v == "fail")
        if flipped:
            regressed = True
        marker = " ⚠ REGRESSION" if flipped else ""
        print(f"| {qid} | {off_g1:.2f}, {off_v} | {on_g1:.2f}, {on_v} | {delta:+.2f}{marker} |")
    return 1 if regressed else 0


def main() -> int:
    _ensure_token()
    off = _run_eval("false", "_canary_off")
    print(
        "\nNOW: flip RAG_CITE_HYGIENE_ENABLED=true on the droplet "
        "(gh workflow dispatch or droplet env edit), then press Enter."
    )
    try:
        input("Press Enter when droplet env flipped...")
    except EOFError:
        pass
    on = _run_eval("true", "_canary_on")
    return diff_target_qids(off, on)


if __name__ == "__main__":
    sys.exit(main())
