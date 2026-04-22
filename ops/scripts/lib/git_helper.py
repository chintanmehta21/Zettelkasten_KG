"""Tiny wrapper around `git` for iteration commits."""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def current_branch(repo_root: Path) -> str:
    return _run(["rev-parse", "--abbrev-ref", "HEAD"], repo_root).strip()


def head_sha(repo_root: Path) -> str:
    return _run(["rev-parse", "HEAD"], repo_root).strip()


def add_paths(repo_root: Path, paths: list[Path]) -> None:
    rels = [str(p.relative_to(repo_root)) for p in paths if p.exists()]
    if not rels:
        return
    _run(["add", "--", *rels], repo_root)


def commit(repo_root: Path, message: str) -> str:
    """Create a commit with the given subject, return SHA. No-op if nothing staged."""
    status = _run(["diff", "--cached", "--name-only"], repo_root).strip()
    if not status:
        return ""
    _run(["commit", "-m", message], repo_root)
    return head_sha(repo_root)
