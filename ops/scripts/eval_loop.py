"""Single-URL iteration CLI for the summarization scoring program.

Two-phase auto-resume:
  Phase A: summary + standard evaluator + manual_review_prompt emission.
  Phase B: manual_review consumption + diff + next_actions + commit.

The CLI is state-aware: invoking it against an iter directory picks the
next phase automatically.  Override with --force-phase-a / --force-phase-b.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.cost_ledger import CostLedger  # noqa: F401 — reserved
from ops.scripts.lib.gemini_factory import make_client as make_gemini_client
from ops.scripts.lib.links_parser import parse_links_file
from ops.scripts.lib.phases import (
    run_determinism_check,
    run_phase_a,
    run_phase_b,
    run_replay,
)
from ops.scripts.lib.state_detector import IterationState, detect_iteration_state

REPO_ROOT = Path(__file__).resolve().parents[2]
LINKS_TXT = REPO_ROOT / "docs" / "testing" / "links.txt"
ARTIFACT_ROOT = REPO_ROOT / "docs" / "summary_eval"
CACHE_ROOT = ARTIFACT_ROOT / "_cache"
CONFIG_ROOT = ARTIFACT_ROOT / "_config"
HALT_FILE = ARTIFACT_ROOT / ".halt"
LOGIN_DETAILS = REPO_ROOT / "docs" / "login_details.txt"

SUPPORTED_SOURCES = [
    "youtube", "reddit", "github", "newsletter",
    "hackernews", "linkedin", "arxiv", "podcast", "twitter", "web",
]

# Per-loop URL allocation per spec §4.1.
#   1:  training URL only (measurement)
#   2:  training URL (tune)
#   3:  training URL (tune)
#   4:  URL #1 + URL #2 (probe)
#   5:  URL #1 + URL #2 + URL #3 (joint tune)
#   6:  all remaining held-out URLs
#   7:  held-out URLs (prod-parity)
#   8:  URL #1 + #2 + #3 + failed held-out (conditional tune)
#   9:  all held-out (conditional measurement)
LOOP_URL_COUNTS = {1: 1, 2: 1, 3: 1, 4: 2, 5: 3, 8: 3}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=SUPPORTED_SOURCES)
    parser.add_argument("--iter", type=int)
    parser.add_argument("--phase", choices=["0", "0.5", "iter", "extension"], default="iter")
    parser.add_argument("--env", choices=["dev", "prod-parity"], default="dev")
    parser.add_argument("--url", action="append")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--server", default="http://127.0.0.1:10000")
    parser.add_argument("--manage-server", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-phase-a", action="store_true")
    parser.add_argument("--force-phase-b", action="store_true")
    parser.add_argument("--emit-review-prompt-only", action="store_true")
    parser.add_argument("--rebuild-index", action="store_true")
    parser.add_argument("--list-urls", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--since")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--stop-server", action="store_true")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--skip-determinism", action="store_true")
    return parser.parse_args()


def _legacy_flat_links(path: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {source: [] for source in SUPPORTED_SOURCES}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^\d+\.\s*", "", line)
        if "youtube.com" in line or "youtu.be" in line:
            result["youtube"].append(line)
        elif "reddit.com" in line:
            result["reddit"].append(line)
        elif "github.com" in line:
            result["github"].append(line)
        elif "x.com/" in line or "twitter.com/" in line:
            result["twitter"].append(line)
    return result


def _links_by_source() -> dict[str, list[str]]:
    parsed = parse_links_file(LINKS_TXT)
    if parsed:
        return parsed
    return _legacy_flat_links(LINKS_TXT)


def _urls_for_iter(source: str, iter_num: int, override: list[str] | None) -> tuple[list[str], bool]:
    """Pick URLs for this iteration and whether it is held-out."""
    if override:
        return override, False
    all_urls = _links_by_source().get(source, [])
    if iter_num in LOOP_URL_COUNTS:
        count = LOOP_URL_COUNTS[iter_num]
        return all_urls[:count], False
    if iter_num in (6, 7, 9):
        # held-out: URLs beyond the training slice (3)
        training_cut = 3
        return all_urls[training_cut:], True
    # default: first URL
    return all_urls[:1], False


def _rubric_path(source: str) -> Path:
    return CONFIG_ROOT / f"rubric_{source}.yaml"


def _iter_dir(source: str, iteration: int | None) -> Path:
    if iteration is None:
        raise SystemExit("--iter is required")
    return ARTIFACT_ROOT / source / f"iter-{iteration:02d}"


def _prev_iter_dir(source: str, iteration: int) -> Path | None:
    if iteration <= 1:
        return None
    return ARTIFACT_ROOT / source / f"iter-{iteration - 1:02d}"


def _zoro_credentials() -> dict[str, str]:
    if not LOGIN_DETAILS.exists():
        return {}
    text = LOGIN_DETAILS.read_text(encoding="utf-8")
    email = re.search(r"email\s*:\s*(.+)", text, flags=re.IGNORECASE)
    password = re.search(r"password\s*:\s*(.+)", text, flags=re.IGNORECASE)
    creds: dict[str, str] = {}
    if email:
        creds["email"] = email.group(1).strip()
    if password:
        creds["password"] = password.group(1).strip()
    return creds


def _report(source: str, since: str | None = None) -> dict:
    """Composite progression report across all iter-NN/ dirs for a source."""
    source_dir = ARTIFACT_ROOT / source
    if not source_dir.exists():
        return {"source": source, "iterations": []}
    rows: list[dict] = []
    from ops.scripts.lib.phases import _composite_from_iter_dir
    for iter_path in sorted(source_dir.glob("iter-*")):
        composite = _composite_from_iter_dir(iter_path)
        rows.append({
            "iter": iter_path.name,
            "composite": round(composite, 2),
            "has_diff": (iter_path / "diff.md").exists(),
        })
    return {"source": source, "iterations": rows}


def main() -> int:
    args = _parse_args()

    if args.stop_server:
        print(json.dumps({"status": "noop"}))
        return 0

    if args.list_urls:
        print(json.dumps(_links_by_source().get(args.source, []), indent=2))
        return 0

    if args.report:
        print(json.dumps(_report(args.source or "youtube", since=args.since), indent=2))
        return 0

    if HALT_FILE.exists():
        print(json.dumps({"status": "halted", "reason": str(HALT_FILE)}))
        return 0

    if not args.source:
        raise SystemExit("--source is required")

    if args.phase == "0":
        print(json.dumps({"status": "phase_0", "note": "Phase 0 scaffolding is a manual task (rubric, decision docs); re-run with --phase iter after Plan 1 completion."}))
        return 0
    if args.phase == "0.5":
        print(json.dumps({"status": "phase_0_5", "note": "Phase 0.5 ingest tuning is manual per-source; re-run with --phase iter after Plan 2-5 completion."}))
        return 0

    iter_num = args.iter
    iter_dir = _iter_dir(args.source, iter_num)
    iter_dir.mkdir(parents=True, exist_ok=True)

    rubric_path = _rubric_path(args.source)
    if not rubric_path.exists():
        raise SystemExit(f"rubric not found: {rubric_path}")

    # Optional managed server (off by default — in-process is sufficient).
    server_proc = None
    if args.manage_server and not args.dry_run:
        from ops.scripts.lib.server_manager import start_server, stop_server
        port = int(args.server.rsplit(":", 1)[-1])
        env_overrides: dict[str, str] = {}
        if args.env == "prod-parity":
            env_overrides["SUMMARIZE_ENV"] = "prod-parity"
            creds = _zoro_credentials()
            if creds:
                env_overrides["EVAL_ZORO_EMAIL"] = creds.get("email", "")
                env_overrides["EVAL_ZORO_PASSWORD"] = creds.get("password", "")
        server_proc = start_server(port=port, env_overrides=env_overrides)

    try:
        if args.replay:
            payload = run_replay(
                source=args.source,
                iter_dir=iter_dir,
                rubric_path=rubric_path,
                gemini_client_factory=make_gemini_client,
            )
            print(json.dumps(payload, indent=2))
            return 0 if payload.get("status") == "stable" else 1

        state = detect_iteration_state(iter_dir)
        if args.force_phase_a:
            state = IterationState.PHASE_A_REQUIRED
        if args.force_phase_b:
            state = IterationState.PHASE_B_REQUIRED

        if args.dry_run:
            urls, held_out = _urls_for_iter(args.source, iter_num, args.url)
            if iter_num in (6, 7, 9):
                held_out = True
            print(json.dumps({
                "status": "dry_run",
                "source": args.source,
                "iter": iter_num,
                "state": state.value,
                "iter_dir": str(iter_dir),
                "rubric": str(rubric_path),
                "urls": urls,
                "held_out": held_out,
                "env": args.env,
            }, indent=2))
            return 0

        if state == IterationState.PHASE_A_REQUIRED:
            # Determinism check against prior iter (optional).
            prev_dir = _prev_iter_dir(args.source, iter_num)
            if prev_dir and prev_dir.exists() and not args.skip_determinism:
                check = run_determinism_check(
                    source=args.source,
                    prev_iter_dir=prev_dir,
                    rubric_path=rubric_path,
                    gemini_client_factory=make_gemini_client,
                )
                if check["status"] == "evaluator_drift":
                    print(json.dumps({
                        "status": "evaluator_drift",
                        "detail": check,
                        "note": "halting Phase A; investigate evaluator/prompts.py or bump PROMPT_VERSION",
                    }, indent=2))
                    return 2

            urls, held_out = _urls_for_iter(args.source, iter_num, args.url)
            if iter_num in (6, 7, 9):
                held_out = True
            payload = run_phase_a(
                source=args.source,
                iter_num=iter_num,
                urls=urls,
                iter_dir=iter_dir,
                rubric_path=rubric_path,
                cache_root=CACHE_ROOT,
                gemini_client_factory=make_gemini_client,
                held_out=held_out,
                env=args.env,
            )
            print(json.dumps(payload, indent=2))
            return 0

        if state == IterationState.AWAITING_MANUAL_REVIEW:
            print(json.dumps({
                "status": "awaiting_manual_review",
                "path": str(iter_dir / "manual_review_prompt.md"),
            }, indent=2))
            return 0

        if state == IterationState.PHASE_B_REQUIRED:
            prev_dir = _prev_iter_dir(args.source, iter_num)
            payload = run_phase_b(
                source=args.source,
                iter_num=iter_num,
                iter_dir=iter_dir,
                prev_dir=prev_dir,
                repo_root=REPO_ROOT,
                allow_commit=not args.no_commit,
            )
            print(json.dumps(payload, indent=2))
            return 0 if payload.get("status", "").startswith("continue") else 1

        if state == IterationState.ALREADY_COMMITTED:
            print(json.dumps({"status": "already_committed", "iter": str(iter_dir)}))
            return 0

        raise SystemExit(f"unknown state: {state}")

    finally:
        if server_proc is not None:
            from ops.scripts.lib.server_manager import stop_server
            stop_server(server_proc)


if __name__ == "__main__":
    raise SystemExit(main())
