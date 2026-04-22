"""Artifact I/O helpers for the eval iteration loop.

Every iteration produces a consistent layout under
`docs/summary_eval/<source>/iter-NN/`:

    input.json              - metadata + gemini usage
    summary.json            - either one summary or a list of {url, summary}
    eval.json               - either one EvalResult or a list of {url, eval}
    source_text.md          - concatenated raw_text per URL (for replay)
    atomic_facts.json       - per-URL atomic fact lists
    manual_review_prompt.md - emitted by Phase A, consumed by the reviewer
    manual_review.md        - written by reviewer (Codex/Claude), consumed by Phase B
    diff.md                 - written by Phase B
    next_actions.md         - written by Phase B
    run.log                 - stdout of the run

For held-out loops (iter-06/09) a `held_out/<sha>/` subtree is used instead
of the top-level summary.json/eval.json.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def url_slug(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def append_log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def iter_artifact_paths(iter_dir: Path) -> dict[str, Path]:
    return {
        "input": iter_dir / "input.json",
        "summary": iter_dir / "summary.json",
        "eval": iter_dir / "eval.json",
        "source_text": iter_dir / "source_text.md",
        "atomic_facts": iter_dir / "atomic_facts.json",
        "prompt": iter_dir / "manual_review_prompt.md",
        "review": iter_dir / "manual_review.md",
        "diff": iter_dir / "diff.md",
        "next_actions": iter_dir / "next_actions.md",
        "log": iter_dir / "run.log",
        "held_out": iter_dir / "held_out",
        "aggregate": iter_dir / "aggregate.md",
        "new_angle": iter_dir / "new_angle.md",
        "regression": iter_dir / "regression_note.md",
        "disagreement": iter_dir / "disagreement_analysis.md",
    }
