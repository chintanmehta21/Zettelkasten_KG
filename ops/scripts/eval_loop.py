"""Single-URL iteration CLI for the summarization scoring program.

Two-phase auto-resume:
  Phase A: summary + standard evaluator + manual_review_prompt emission.
  Phase B: manual_review consumption + diff + next_actions + commit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.cost_ledger import CostLedger
from ops.scripts.lib.links_parser import parse_links_file
from ops.scripts.lib.server_manager import start_server, stop_server
from ops.scripts.lib.state_detector import IterationState, detect_iteration_state

REPO_ROOT = Path(__file__).resolve().parents[2]
LINKS_TXT = REPO_ROOT / "docs" / "testing" / "links.txt"
ARTIFACT_ROOT = REPO_ROOT / "docs" / "summary_eval"
CACHE_ROOT = ARTIFACT_ROOT / "_cache"
LOGIN_DETAILS = REPO_ROOT / "docs" / "login_details.txt"
SUPPORTED_SOURCES = [
    "youtube",
    "reddit",
    "github",
    "newsletter",
    "hackernews",
    "linkedin",
    "arxiv",
    "podcast",
    "twitter",
    "web",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=SUPPORTED_SOURCES)
    parser.add_argument("--iter", type=int)
    parser.add_argument("--phase", choices=["0", "0.5", "iter", "extension"], default="iter")
    parser.add_argument("--env", choices=["dev", "prod-parity"], default="dev")
    parser.add_argument("--url")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--server", default="http://127.0.0.1:10000")
    parser.add_argument("--manage-server", action=argparse.BooleanOptionalAction, default=True)
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
    return parser.parse_args()


def _zoro_credentials() -> dict[str, str]:
    """Parse zoro creds from docs/login_details.txt without hardcoding."""
    if not LOGIN_DETAILS.exists():
        return {}
    text = LOGIN_DETAILS.read_text(encoding="utf-8")
    email_match = re.search(r"email\s*:\s*(.+)", text, flags=re.IGNORECASE)
    password_match = re.search(r"password\s*:\s*(.+)", text, flags=re.IGNORECASE)
    creds: dict[str, str] = {}
    if email_match:
        creds["email"] = email_match.group(1).strip()
    if password_match:
        creds["password"] = password_match.group(1).strip()
    return creds


def _legacy_flat_links(path: Path) -> dict[str, list[str]]:
    """Best-effort parser for the pre-sectioned links.txt format."""
    result = {source: [] for source in SUPPORTED_SOURCES}
    if not path.exists():
        return result

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^\d+\.\s*", "", line)
        if "youtube.com" in line or "youtu.be" in line:
            result["youtube"].append(line)
        elif "reddit.com" in line:
            result["reddit"].append(line)
        elif "x.com/" in line or "twitter.com/" in line:
            result["twitter"].append(line)
    return result


def _links_by_source() -> dict[str, list[str]]:
    parsed = parse_links_file(LINKS_TXT)
    if parsed:
        return parsed
    return _legacy_flat_links(LINKS_TXT)


def _resolve_urls(args: argparse.Namespace) -> list[str]:
    if args.url:
        return [args.url]
    if not args.source:
        return []
    return _links_by_source().get(args.source, [])


def _iteration_dir(source: str, iteration: int | None) -> Path:
    suffix = f"iter-{iteration:02d}" if iteration is not None else "iter-latest"
    return ARTIFACT_ROOT / source / suffix


def main() -> int:
    args = _parse_args()
    ledger = CostLedger()
    _ = ledger

    if args.stop_server:
        print(json.dumps({"status": "noop", "message": "Use process handle from manager to stop server."}))
        return 0

    if args.list_urls:
        print(json.dumps(_resolve_urls(args), indent=2))
        return 0

    if not args.source:
        raise SystemExit("--source is required unless using --stop-server")

    iter_dir = _iteration_dir(args.source, args.iter)
    iter_dir.mkdir(parents=True, exist_ok=True)
    state = detect_iteration_state(iter_dir)
    if args.force_phase_a:
        state = IterationState.PHASE_A_REQUIRED
    if args.force_phase_b:
        state = IterationState.PHASE_B_REQUIRED

    env_overrides: dict[str, str] = {}
    if args.env == "prod-parity":
        env_overrides["SUMMARIZE_ENV"] = "prod-parity"
        env_overrides["SUMMARIZE_CONFIG_OVERRIDES"] = str(REPO_ROOT / "ops" / "config.prod-overrides.yaml")
        creds = _zoro_credentials()
        if creds:
            env_overrides["EVAL_ZORO_EMAIL"] = creds.get("email", "")
            env_overrides["EVAL_ZORO_PASSWORD"] = creds.get("password", "")

    proc = None
    try:
        if args.manage_server and not args.dry_run:
            port = int(args.server.rsplit(":", 1)[-1])
            proc = start_server(port=port, env_overrides=env_overrides)
        payload = {
            "status": "ready",
            "source": args.source,
            "phase_state": state.value,
            "iter_dir": str(iter_dir),
            "urls": _resolve_urls(args),
            "cache_root": str(CACHE_ROOT),
            "env": args.env,
            "dry_run": args.dry_run,
        }
        print(json.dumps(payload, indent=2))
        return 0
    finally:
        if proc is not None:
            stop_server(proc)


if __name__ == "__main__":
    raise SystemExit(main())
