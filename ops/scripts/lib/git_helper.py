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


def worktree_changed_paths(repo_root: Path) -> list[str]:
    """Return changed tracked/untracked paths from the current worktree."""
    output = _run(["status", "--short"], repo_root).splitlines()
    paths: list[str] = []
    for line in output:
        if not line:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            paths.append(path)
    return paths


def head_changed_paths(repo_root: Path) -> list[str]:
    """Return paths changed by HEAD, used for pre-Phase-A tuning commits."""
    output = _run(
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        repo_root,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def changed_paths_since(repo_root: Path, base_ref: str) -> list[str]:
    """Return file paths changed between base_ref (exclusive) and HEAD."""
    output = _run(["diff", "--name-only", f"{base_ref}..HEAD"], repo_root)
    return [line.strip() for line in output.splitlines() if line.strip()]


def last_commit_matching_subject(repo_root: Path, subject_text: str) -> str | None:
    """Return latest commit SHA whose subject contains subject_text."""
    output = _run(
        ["log", "--fixed-strings", "--grep", subject_text, "--format=%H", "-n", "1"],
        repo_root,
    ).strip()
    return output or None
