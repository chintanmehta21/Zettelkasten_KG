"""Single-URL iteration CLI for the summarization scoring program.

Two-phase auto-resume:
  Phase A: summary + standard evaluator + manual_review_prompt emission.
  Phase B: manual_review consumption + diff + next_actions + commit.

The CLI is state-aware: invoking it against an iter directory picks the
next phase automatically.  Override with --force-phase-a / --force-phase-b.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.eval_diversity import (
    EvalConfigInsufficientDiversity,
    check_github_heldout_diversity,
    check_reddit_training_diversity,
)
from ops.scripts.lib.links_parser import parse_links_file

REPO_ROOT = Path(__file__).resolve().parents[2]
LINKS_TXT = REPO_ROOT / "docs" / "testing" / "links.txt"
ARTIFACT_ROOT = REPO_ROOT / "docs" / "summary_eval"
CACHE_ROOT = ARTIFACT_ROOT / "_cache"
CONFIG_ROOT = ARTIFACT_ROOT / "_config"
DEAD_URLS_ROOT = ARTIFACT_ROOT / "_dead_urls"
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
#  10+: cadence policy — even iter = full held-out sweep (≥5 URLs);
#       odd iter = 3-URL training tune
LOOP_URL_COUNTS = {1: 1, 2: 1, 3: 1, 4: 2, 5: 3, 8: 3}
HELD_OUT_MIN_URLS = 5
EVAL_SOURCES_WITH_CHEAP_FAILFAST = {"youtube", "reddit", "github", "newsletter"}


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
    parser.add_argument("--auto-eval", choices=SUPPORTED_SOURCES, default=None,
                        help="Run rubric-only auto-eval over the most recent iteration's summaries for SOURCE")
    parser.add_argument("--auto-eval-threshold", type=int, default=85,
                        help="Composite score threshold for --auto-eval pass count (default 85)")
    parser.add_argument("--auto-eval-summaries-glob", default="**/auto_eval_input.json",
                        help="Glob (relative to the iter dir) to locate scored summary payloads")
    parser.add_argument("--calibrate", action="store_true",
                        help="Run held-out calibration gate and exit 0 (pass) or 2 (block)")
    parser.add_argument("--calibration-scores", type=str,
                        help="Path to JSON {url: composite_score} produced by external driver")
    parser.add_argument("--baseline", type=float,
                        help="Prior composite score to regress the held-out mean against")
    parser.add_argument("--floor", type=float, default=85.0,
                        help="Per-shape composite floor (default 85.0)")
    parser.add_argument("--regression-tolerance", type=float, default=3.0,
                        help="Max allowed mean regression below baseline (default 3.0)")
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
        held_out = all_urls[training_cut:]
        # Plan 7's Reddit loop was specified and reviewed against a single held-out URL.
        # Later appends in links.txt are exploratory extras, not part of the scored plan.
        if source == "reddit":
            held_out = held_out[:1]
        # For non-Reddit sources: ensure ≥HELD_OUT_MIN_URLS by promoting to the
        # full sweep when the held-out slice alone is too small.
        elif len(held_out) < HELD_OUT_MIN_URLS and len(all_urls) >= HELD_OUT_MIN_URLS:
            held_out = all_urls[:HELD_OUT_MIN_URLS]
        return held_out, True
    if iter_num >= 10:
        # Cadence: even iter = held-out sweep; odd iter = 3-URL training tune.
        if iter_num % 2 == 0:
            held_out = all_urls
            if source == "reddit":
                training_cut = 3
                held_out = all_urls[training_cut:][:1]
            return held_out, True
        return all_urls[:3], False
    # default: first URL
    return all_urls[:1], False


def _default_liveness_probe(urls: list[str]) -> dict[str, tuple[bool, str]]:
    """Default cross-source liveness probe.

    Wraps ``liveness_probe`` from ``summarization/newsletter/liveness.py``
    (which is now generic — see that module's ``_DEAD_HTML_MARKERS``).
    """
    from website.features.summarization_engine.summarization.newsletter.liveness import (
        liveness_probe,
    )
    return liveness_probe(urls)


def _filter_live_urls(
    urls: list[str], probe: Callable[[list[str]], dict[str, tuple[bool, str]]] | None = None
) -> tuple[list[str], list[str]]:
    """Pre-flight liveness check; partition input into (live, dead).

    Skipped entirely (returns ``(urls, [])``) when ``EVAL_SKIP_LIVENESS=1`` is
    set so CI can opt out without touching the network. The default probe is
    the URL-pattern variant from the newsletter module — it does no network
    I/O on its own; the eval loop does not currently pre-fetch HTML, so the
    check is purely URL-shape based here. Callers that want HTML-marker
    matching can pass a custom ``probe`` callable.
    """
    if not isinstance(urls, list):
        raise TypeError(f"_filter_live_urls: urls must be list, got {type(urls).__name__}")
    if os.environ.get("EVAL_SKIP_LIVENESS") == "1":
        return list(urls), []
    if probe is None:
        probe = _default_liveness_probe
    verdicts = probe(urls)
    live: list[str] = []
    dead: list[str] = []
    for url in urls:
        verdict = verdicts.get(url)
        if verdict is None:
            # Probe didn't return a verdict for this URL — fail loud rather
            # than silently treating it as live.
            raise RuntimeError(
                f"_filter_live_urls: probe returned no verdict for url={url!r}"
            )
        is_live, _reason = verdict
        if is_live:
            live.append(url)
        else:
            dead.append(url)
    return live, dead


def _log_dead_urls(source: str, iter_num: int, dead: list[str]) -> Path | None:
    """Persist dead URLs to ``docs/summary_eval/_dead_urls/<utc-ts>.json``.

    Returns the written path, or ``None`` when ``dead`` is empty.
    """
    if not dead:
        return None
    DEAD_URLS_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = DEAD_URLS_ROOT / f"{source}_iter{iter_num:02d}_{ts}.json"
    payload = {
        "source": source,
        "iter": iter_num,
        "captured_at_utc": ts,
        "dead_urls": dead,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def _enforce_diversity_gates(source: str, urls: list[str], held_out: bool) -> None:
    """Run per-source config-level diversity gates before spending Gemini calls.

    Raises ``EvalConfigInsufficientDiversity`` (``AssertionError`` subclass) on
    failure, which ``main`` turns into a clean exit-code-2 message. Respects
    ``EVAL_SKIP_*_DIVERSITY=1`` bypass envs for operator waivers.
    """
    if source == "reddit" and not held_out:
        check_reddit_training_diversity(urls)
    elif source == "github" and held_out:
        archetype_map = _load_github_archetype_map()
        check_github_heldout_diversity(urls, archetype_map)


def _load_github_archetype_map() -> dict[str, str]:
    """Load ``docs/summary_eval/_config/github_heldout_archetypes.yaml``.

    Returns ``{}`` if the file is missing; the diversity check reports that
    as "0 archetypes" and blocks, which is the correct default.
    """
    path = CONFIG_ROOT / "github_heldout_archetypes.yaml"
    if not path.exists():
        return {}
    import yaml  # local import to avoid cost when the gate doesn't fire
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in raw.items() if v}


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


def _apply_eval_key_pool_overrides(source: str | None) -> None:
    if source not in EVAL_SOURCES_WITH_CHEAP_FAILFAST:
        return
    os.environ.setdefault("GEMINI_KEY_ROLE_FILTER", "billing")
    os.environ.setdefault("GEMINI_MAX_RETRIES", "1")
    os.environ.setdefault("GEMINI_RATE_LIMIT_COOLDOWN_SECS", "75")
    os.environ.setdefault("GEMINI_FAIL_FAST_ON_ALL_COOLDOWNS", "1")


def _latest_iter_dir(source: str) -> Path | None:
    source_dir = ARTIFACT_ROOT / source
    if not source_dir.exists():
        return None
    iters = sorted(source_dir.glob("iter-*"))
    return iters[-1] if iters else None


def _run_auto_eval(args: argparse.Namespace) -> int:
    """Score the most recent iteration's summaries against the source rubric.

    Output: ``docs/summary_eval/auto_eval/<source>_<timestamp>.json``.
    Exit 0 on success, 2 if no summaries are discoverable.
    """
    from datetime import datetime, timezone

    from website.features.summarization_engine.evaluator.auto_eval_harness import (
        AutoEvalConfig,
        emit_scorecard_json,
        run_auto_eval,
    )

    source = args.auto_eval
    rubric_path = _rubric_path(source)
    if not rubric_path.exists():
        print(json.dumps({"status": "error", "reason": f"rubric not found: {rubric_path}"}))
        return 2

    iter_dir = _latest_iter_dir(source)
    if iter_dir is None:
        print(json.dumps({"status": "error", "reason": f"no iter dirs under {ARTIFACT_ROOT / source}"}))
        return 2

    summary_paths = sorted(iter_dir.glob(args.auto_eval_summaries_glob))
    if not summary_paths:
        print(json.dumps({
            "status": "error",
            "reason": f"no summaries matched {args.auto_eval_summaries_glob} under {iter_dir}",
        }))
        return 2

    config = AutoEvalConfig(
        source_type=source,
        rubric_path=rubric_path,
        summaries=summary_paths,
        composite_max=100,
        pass_threshold=int(args.auto_eval_threshold),
    )
    result = run_auto_eval(config)
    result["iter_dir"] = str(iter_dir)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ARTIFACT_ROOT / "auto_eval"
    out_path = out_dir / f"{source}_{ts}.json"
    emit_scorecard_json(result, out_path)

    print(json.dumps({"status": "ok", "scorecard": str(out_path), **{
        k: result[k] for k in ("summaries_scored", "mean_composite", "p50", "p10", "passed_threshold", "threshold")
    }}, indent=2))
    return 0


def _run_calibration(args: argparse.Namespace) -> int:
    from website.features.summarization_engine.summarization.common.calibration import (
        CalibrationHarness, CalibrationShape, CalibrationVerdict,
    )

    shapes = [
        CalibrationShape(name="lecture",   url=os.environ.get("CAL_LECTURE_URL", "")),
        CalibrationShape(name="interview", url=os.environ.get("CAL_INTERVIEW_URL", "")),
        CalibrationShape(name="tutorial",  url=os.environ.get("CAL_TUTORIAL_URL", "")),
        CalibrationShape(name="review",    url=os.environ.get("CAL_REVIEW_URL", "")),
        CalibrationShape(name="short",     url=os.environ.get("CAL_SHORT_URL", "")),
    ]
    if not all(s.url for s in shapes):
        print(json.dumps({"status": "skipped", "reason": "CAL_*_URL env vars not all set"}))
        return 0

    if args.baseline is None:
        print(json.dumps({"status": "error", "reason": "--baseline is required with --calibrate"}))
        return 2
    if not args.calibration_scores:
        print(json.dumps({"status": "error", "reason": "--calibration-scores path is required with --calibrate"}))
        return 2

    scores_path = Path(args.calibration_scores)
    if not scores_path.exists():
        print(json.dumps({"status": "error", "reason": f"scores file not found: {scores_path}"}))
        return 2
    scores = json.loads(scores_path.read_text(encoding="utf-8"))

    missing = [s.url for s in shapes if s.url not in scores]
    if missing:
        print(json.dumps({"status": "error", "reason": f"scores missing for URLs: {missing}"}))
        return 2

    class _JsonRunner:
        def __init__(self, table: dict[str, float]):
            self._table = table

        async def score(self, url: str) -> float:
            return float(self._table[url])

    harness = CalibrationHarness(
        shapes=shapes, floor=args.floor, regression_tolerance=args.regression_tolerance,
    )
    result = asyncio.run(harness.run(_JsonRunner(scores), baseline=args.baseline))

    payload = {
        "status": result.verdict.value,
        "reason": result.reason,
        "mean": result.mean,
        "per_shape": result.per_shape,
        "baseline": args.baseline,
        "floor": args.floor,
        "regression_tolerance": args.regression_tolerance,
    }
    print(json.dumps(payload, indent=2))
    return 0 if result.verdict is CalibrationVerdict.PASS else 2


def main() -> int:
    args = _parse_args()
    _apply_eval_key_pool_overrides(args.source)

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

    if args.auto_eval:
        return _run_auto_eval(args)

    if args.calibrate:
        return _run_calibration(args)

    if not args.source:
        raise SystemExit("--source is required")

    if args.phase == "0":
        print(json.dumps({"status": "phase_0", "note": "Phase 0 scaffolding is a manual task (rubric, decision docs); re-run with --phase iter after Plan 1 completion."}))
        return 0
    if args.phase == "0.5":
        print(json.dumps({"status": "phase_0_5", "note": "Phase 0.5 ingest tuning is manual per-source; re-run with --phase iter after Plan 2-5 completion."}))
        return 0

    from ops.scripts.lib.gemini_factory import make_client as make_gemini_client
    from ops.scripts.lib.phases import (
        run_determinism_check,
        run_phase_a,
        run_phase_b,
        run_replay,
    )
    from ops.scripts.lib.state_detector import IterationState, detect_iteration_state

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
            # Pre-flight liveness — drop dead URLs before spending Gemini calls.
            live_urls, dead_urls = _filter_live_urls(urls)
            if dead_urls:
                dead_log = _log_dead_urls(args.source, iter_num, dead_urls)
                print(json.dumps({
                    "status": "liveness_filtered",
                    "source": args.source,
                    "iter": iter_num,
                    "dead_count": len(dead_urls),
                    "dead_urls": dead_urls,
                    "log_path": str(dead_log) if dead_log else None,
                }, indent=2))
            urls = live_urls
            if not urls:
                print(json.dumps({
                    "status": "no_live_urls",
                    "source": args.source,
                    "iter": iter_num,
                    "note": "All planned URLs failed liveness pre-flight.",
                }, indent=2))
                return 2
            try:
                _enforce_diversity_gates(args.source, urls, held_out)
            except EvalConfigInsufficientDiversity as exc:
                print(json.dumps({
                    "status": "config_insufficient_diversity",
                    "source": args.source,
                    "iter": iter_num,
                    "detail": str(exc),
                    "bypass_env": (
                        "EVAL_SKIP_REDDIT_DIVERSITY" if args.source == "reddit"
                        else "EVAL_SKIP_GH_DIVERSITY"
                    ),
                }, indent=2))
                return 2
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
