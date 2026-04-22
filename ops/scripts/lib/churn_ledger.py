"""Track per-iteration file edits vs. targeted criterion movement (spec §8.4).

The ledger is a JSON file at `docs/summary_eval/<source>/edit_ledger.json`.
Shape:
    {
      "entries": [
        {"iter": 2, "files": ["path/a.py"], "targeted_criterion": "brief.thesis_capture",
         "criterion_delta": 1.5, "composite_delta": 2.0},
         ...
      ]
    }

A file is "churning" if edited in >=3 consecutive tuning iters with combined
criterion_delta < 1.0.  The caller can then either skip the file or write a
`new_angle.md` under the iter directory.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


_LEDGER_LOCK = threading.RLock()


@dataclass
class LedgerEntry:
    iter: int
    files: list[str] = field(default_factory=list)
    targeted_criterion: str | None = None
    criterion_delta: float = 0.0
    composite_delta: float = 0.0


def _path(source_dir: Path) -> Path:
    return source_dir / "edit_ledger.json"


def load(source_dir: Path) -> list[LedgerEntry]:
    path = _path(source_dir)
    if not path.exists():
        return []
    for attempt in range(3):
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                return []
            data = json.loads(text)
            return [LedgerEntry(**item) for item in data.get("entries", [])]
        except json.JSONDecodeError:
            if attempt == 2:
                raise
            time.sleep(0.01 * (attempt + 1))
    return []


def save(source_dir: Path, entries: list[LedgerEntry]) -> None:
    path = _path(source_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"entries": [entry.__dict__ for entry in entries]}
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def record(
    source_dir: Path,
    *,
    iter_num: int,
    files: list[str],
    targeted_criterion: str | None,
    criterion_delta: float,
    composite_delta: float,
) -> None:
    with _LEDGER_LOCK:
        entries = load(source_dir)
        entries = [entry for entry in entries if entry.iter != iter_num]
        entries.append(
            LedgerEntry(
                iter=iter_num,
                files=sorted(set(files)),
                targeted_criterion=targeted_criterion,
                criterion_delta=criterion_delta,
                composite_delta=composite_delta,
            )
        )
        entries.sort(key=lambda entry: entry.iter)
        save(source_dir, entries)


def churning_files(source_dir: Path, *, current_iter: int, lookback: int = 3) -> list[str]:
    """Return files edited in >=lookback consecutive tuning iters with <1.0 combined delta."""
    entries = load(source_dir)
    window = [
        entry
        for entry in entries
        if current_iter - lookback <= entry.iter < current_iter
    ]
    if len(window) < lookback:
        return []
    expected = set(range(current_iter - lookback, current_iter))
    if {entry.iter for entry in window} != expected:
        return []

    file_totals: dict[str, float] = {}
    file_counts: dict[str, int] = {}
    for entry in window:
        for file in entry.files:
            file_totals[file] = file_totals.get(file, 0.0) + entry.criterion_delta
            file_counts[file] = file_counts.get(file, 0) + 1

    return sorted(
        file
        for file, count in file_counts.items()
        if count >= lookback and abs(file_totals.get(file, 0.0)) < 1.0
    )
