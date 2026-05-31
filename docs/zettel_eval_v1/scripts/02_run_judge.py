"""02_run_judge.py — run an LLM-as-judge pass over the frozen manifest.

WIRED implementation (2026-05-28). Reuses website/features/summarization_engine/
evaluator/* end-to-end:
  - extract_atomic_facts -> reuses Gemini extractor + on-disk cache
  - ConsolidatedEvaluator -> works with both Gemini and Claude clients
    (the Claude adapter lives in docs/zettel_eval_v1/scripts/lib/anthropic_factory.py
    and exposes the same .generate(...) surface as TieredGeminiClient)
  - filter_judge_false_positives -> existing post-judge FP filter
  - compute_numeric_grounding_signal -> deterministic numeric check

Reads:
  docs/zettel_eval_v1/_config/manifest.json          (zettel list, frozen)
  docs/zettel_eval_v1/_config/judges.yaml            (judge config per iter)
  docs/zettel_eval_v1/_data/<wz_uuid>/{meta,summary,source_text}.*

Writes (per iter <iter>):
  runs/<iter>/<source_type>/per_zettel/<wz_uuid>.json   (one per zettel)
  runs/<iter>/_overall/per_zettel/<wz_uuid>.json        (same content, dual-linked)
  runs/<iter>/config.json                                (judge ids + shas snapshot)
  runs/<iter>/telemetry.json                             (per-call costs + latency)

Pre-flight gate (METHODOLOGY §18.7):
  - _data/ must be populated (>= 1 sub-dir).
  - judge_calibration_set.json must have items_pending == 0 (smoke bank curated).
  - Calibration overall_pass must be True for the judges in use, UNLESS
    --override-calibration is set. Currently checked permissively because
    10_judge_calibration.py is still being wired; will tighten when it lands.

Usage:
    python docs/zettel_eval_v1/scripts/02_run_judge.py --iter iter-001-baseline
    python docs/zettel_eval_v1/scripts/02_run_judge.py --iter iter-002-claude
    python docs/zettel_eval_v1/scripts/02_run_judge.py --iter iter-004-jury
    python docs/zettel_eval_v1/scripts/02_run_judge.py --iter iter-001-baseline --max-zettels 3   # smoke
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

EVAL_ROOT = REPO_ROOT / "docs" / "zettel_eval_v1"
DATA_ROOT = EVAL_ROOT / "_data"
RUNS_ROOT = EVAL_ROOT / "runs"
CACHE_ROOT = EVAL_ROOT / "_cache"
MANIFEST = EVAL_ROOT / "_config" / "manifest.json"
JUDGES_YAML = EVAL_ROOT / "_config" / "judges.yaml"
CALIB_SET = EVAL_ROOT / "_config" / "judge_calibration_set.json"
RUBRIC_PATH = REPO_ROOT / "docs" / "summary_eval" / "_config" / "rubric_universal.yaml"


def _parse_api_env_lines(text: str) -> list[str]:
    """Extract Gemini key lines from an api_env-format string.

    api_env uses bare-key-per-line format with an optional ``role=billing|free``
    token (space-separated on the same line) — see
    ``website/features/api_key_switching/key_pool.py::parse_api_env_line``.

    Critically: do NOT split on ``=`` here. The legacy parser used to do
    ``_, ln = ln.split("=", 1)`` to support hypothetical ``KEY=VALUE`` lines,
    but that BREAKS lines with a ``role=billing`` token (the first ``=``
    falls inside the token, so the key gets discarded and only the literal
    string ``"billing"`` survives). Caught 2026-05-29 before iter-003 launch.

    The returned strings preserve any role token so that downstream
    ``gemini_factory._parse_csv_key_spec`` can recover (key, role) tuples.
    Blank lines and ``#`` comments are skipped. Surrounding quotes are
    stripped but only when they bracket the whole line.
    """
    out: list[str] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if len(ln) >= 2 and ((ln[0] == ln[-1]) and ln[0] in ('"', "'")):
            ln = ln[1:-1].strip()
        if ln:
            out.append(ln)
    return out


def _load_env() -> None:
    from dotenv import load_dotenv
    for p in (REPO_ROOT/".env", REPO_ROOT/".env.v2", REPO_ROOT.parent.parent.parent / ".env",
              REPO_ROOT.parent.parent.parent / ".env.v2"):
        if p.exists():
            load_dotenv(p, override=False)
    api_env_candidates = [
        REPO_ROOT / "api_env",
        Path("C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/api_env"),
        Path("/etc/secrets/api_env"),
    ]
    if not os.environ.get("GEMINI_API_KEYS"):
        for p in api_env_candidates:
            if not p.exists():
                continue
            keys = _parse_api_env_lines(p.read_text(encoding="utf-8", errors="ignore"))
            if keys:
                os.environ["GEMINI_API_KEYS"] = ",".join(keys)
                break


def _sha256(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return hashlib.sha256(s).hexdigest()


def _load_yaml(p: Path) -> dict:
    import yaml
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _pre_flight(iter_id: str, override_calibration: bool) -> None:
    if not MANIFEST.exists():
        raise SystemExit("Manifest missing; run 01_freeze_manifest.py first.")
    if not any(DATA_ROOT.iterdir() if DATA_ROOT.exists() else []):
        raise SystemExit("_data/ is empty; run 01_freeze_manifest.py first.")
    calib = json.loads(CALIB_SET.read_text(encoding="utf-8"))
    pending = sum((calib.get("items_pending") or {}).values())
    if pending > 0 and not override_calibration:
        raise SystemExit(
            f"judge_calibration_set has {pending} pending items; "
            f"hand-curate or pass --override-calibration."
        )


def _get_iter_row(iter_id: str) -> dict:
    jy = _load_yaml(JUDGES_YAML)
    for row in jy["run_matrix"]:
        if row.get("iter_id") == iter_id:
            return row
    raise SystemExit(f"iter_id {iter_id!r} not in judges.yaml::run_matrix")


def _make_judge(judge_kind: str):
    """judge_kind in {'primary','secondary'}. Returns (client, role_tag, model_id_requested)."""
    if judge_kind == "primary":
        from ops.scripts.lib.gemini_factory import make_client as make_gemini
        return make_gemini(), "rubric_evaluator", "gemini-2.5-flash-002"
    elif judge_kind == "secondary":
        from docs.zettel_eval_v1.scripts.lib.anthropic_factory import make_client as make_claude
        return make_claude(), "rubric_evaluator_diverse", "claude-haiku-4-5-20251001"
    else:
        raise ValueError(f"unknown judge_kind {judge_kind!r}")


def _judges_to_run(row: dict, override_judge: str | None) -> list[str]:
    if override_judge in {"primary", "secondary"}:
        return [override_judge]
    if override_judge == "both":
        return ["primary", "secondary"]
    # Honour the iter's judges list from judges.yaml
    raw = row.get("judges") or ["primary"]
    return list(raw)


def _judge_cache_key(*,
                    canonical_id: str,
                    source_sha: str,
                    summary_sha: str,
                    atomic_facts_sha: str,
                    rubric_sha: str,
                    prompt_version: str,
                    judge_provider: str,
                    judge_model_requested: str) -> str:
    raw = "|".join([
        judge_provider, judge_model_requested, prompt_version,
        canonical_id, source_sha, summary_sha, atomic_facts_sha, rubric_sha,
    ])
    return _sha256(raw)


async def _evaluate_one_zettel(*, manifest_entry: dict, judge_kind: str, judge_client, judge_model_id: str,
                               atomic_facts: list[dict], rubric_yaml: dict, source_text: str,
                               summary_json: dict, cache_dir: Path, force_refresh: bool,
                               compute_atomic_facts_call) -> dict:
    from website.features.summarization_engine.evaluator.consolidated import (
        ConsolidatedEvaluator, compute_numeric_grounding_signal,
    )
    from website.features.summarization_engine.evaluator.prompts import PROMPT_VERSION
    from ops.scripts.lib.phases import filter_judge_false_positives

    wz_id = manifest_entry["workspace_zettel_id"]
    canonical_id = manifest_entry["canonical_zettel_id"]
    source_sha = _sha256(source_text)
    summary_sha = _sha256(json.dumps(summary_json, sort_keys=True, ensure_ascii=False))
    atomic_sha = _sha256(json.dumps(atomic_facts, sort_keys=True, ensure_ascii=False))
    rubric_sha = _sha256(json.dumps(rubric_yaml, sort_keys=True))

    judge_provider = "google" if judge_kind == "primary" else "anthropic"
    cache_key = _judge_cache_key(
        canonical_id=canonical_id, source_sha=source_sha, summary_sha=summary_sha,
        atomic_facts_sha=atomic_sha, rubric_sha=rubric_sha,
        prompt_version=PROMPT_VERSION,
        judge_provider=judge_provider,
        judge_model_requested=judge_model_id,
    )
    cache_file = cache_dir / f"{cache_key}.json"
    if cache_file.exists() and not force_refresh:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        cached["_cache_hit"] = True
        return cached

    evaluator = ConsolidatedEvaluator(judge_client)
    t0 = time.perf_counter()
    eval_result = await evaluator.evaluate(
        rubric_yaml=rubric_yaml,
        atomic_facts=atomic_facts,
        source_text=source_text,
        summary_json=summary_json,
    )
    filter_judge_false_positives(eval_result, source_text)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    payload = eval_result.model_dump(mode="json")
    # numeric_grounding_score already in evaluator_metadata via ConsolidatedEvaluator
    payload["_meta"] = {
        "wz_zettel_id": wz_id,
        "canonical_zettel_id": canonical_id,
        "source_type": manifest_entry.get("source_type"),
        "judge_kind": judge_kind,
        "judge_provider": judge_provider,
        "judge_model_requested": judge_model_id,
        "judge_model_used": payload.get("evaluator_metadata", {}).get("model_used", judge_model_id),
        "prompt_version": PROMPT_VERSION,
        "rubric_sha256": rubric_sha,
        "source_sha256": source_sha,
        "summary_sha256": summary_sha,
        "atomic_facts_sha256": atomic_sha,
        "latency_ms": latency_ms,
        "cache_key": cache_key,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    payload["_cache_hit"] = False
    return payload


async def _ensure_atomic_facts(*, manifest_entry: dict, source_text: str,
                                 extractor_client, rubric_path: Path,
                                 cache_root: Path = CACHE_ROOT) -> list[dict]:
    from website.features.summarization_engine.evaluator.atomic_facts import extract_atomic_facts
    return await extract_atomic_facts(
        client=extractor_client,
        source_text=source_text,
        cache_root=cache_root,
        url=manifest_entry.get("normalized_url", ""),
        ingestor_version=manifest_entry.get("source_type", "web"),
    )


def _filter_zettels(zettels: list[dict], *, wz_filter: str | None,
                     max_zettels: int | None) -> list[dict]:
    """Apply --wz-filter (prefix match on workspace_zettel_id) then --max-zettels.

    Raises SystemExit if --wz-filter is set but matches zero entries — that's
    almost always a typo on a manual hot-fix re-run, fail loud so the operator
    doesn't waste a session waiting for a no-op.
    """
    out = list(zettels)
    if wz_filter:
        out = [z for z in out if z["workspace_zettel_id"].startswith(wz_filter)]
        if not out:
            raise SystemExit(f"--wz-filter {wz_filter!r} matched zero zettels in manifest")
    if max_zettels:
        out = out[: max_zettels]
    return out


def _write_per_zettel(*, run_dir: Path, source_type: str, wz_id: str, payload: dict,
                      multi_judge: bool = False) -> None:
    # Multi-judge iters (e.g. iter-004 jury, judges=[primary, secondary]) MUST
    # write one file PER judge — otherwise the second judge's <wz>.json
    # overwrites the first (last-writer-wins) and the jury is silently reduced
    # to a single judge (the iter-004 data-loss bug found 2026-05-31). The
    # judge_kind suffix keeps both. Single-judge iters (001/002/003/005) keep
    # the bare <wz>.json layout — backward-compatible with existing files and
    # every downstream glob (04/06/07/09).
    suffix = ""
    if multi_judge:
        jk = (payload.get("_meta") or {}).get("judge_kind", "judge")
        suffix = f"__{jk}"
    for parent in (run_dir / source_type / "per_zettel", run_dir / "_overall" / "per_zettel"):
        parent.mkdir(parents=True, exist_ok=True)
        (parent / f"{wz_id}{suffix}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


async def main_async(args) -> int:
    _load_env()
    _pre_flight(args.iter_id, args.override_calibration)
    row = _get_iter_row(args.iter_id)
    if row.get("status", "active") != "active":
        if not args.override_status:
            raise SystemExit(
                f"iter_id {args.iter_id!r} has status={row.get('status')}; "
                f"pass --override-status to force-run a deferred iter."
            )

    judge_kinds = _judges_to_run(row, args.judge)
    print(f"[02_run_judge] iter={args.iter_id} judges={judge_kinds} status={row.get('status')}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    zettels = _filter_zettels(
        manifest["zettels"], wz_filter=args.wz_filter, max_zettels=args.max_zettels
    )
    print(f"[02_run_judge] evaluating {len(zettels)} zettels"
          + (f" (filtered by wz prefix {args.wz_filter!r})" if args.wz_filter else ""))

    rubric_yaml = _load_yaml(RUBRIC_PATH)

    # Build clients
    judge_clients: dict[str, tuple] = {}
    for kind in judge_kinds:
        judge_clients[kind] = _make_judge(kind)

    # The atomic-facts extractor defaults to Gemini Flash. iter-005
    # (extractor=experimental_swap) swaps it to gemini-2.5-flash-lite to break the
    # same-family extract-and-judge circularity (judges.yaml). Swapped facts are
    # cached under a SEPARATE root so they never overwrite the flash facts shared
    # by iter-001..004 (overwriting would corrupt those iters). The swapped facts'
    # content differs → new atomic_facts_sha → judge cache miss → genuine re-judge.
    from ops.scripts.lib.gemini_factory import make_client as make_gemini
    swap_extractor = (row.get("extractor") == "experimental_swap") or getattr(args, "swap_extractor", False)
    extractor_client = make_gemini(swap_extractor=swap_extractor)
    extractor_cache_root = (CACHE_ROOT / "atomic_facts_swap_flash_lite") if swap_extractor else CACHE_ROOT
    if swap_extractor:
        print(f"[02_run_judge] EXTRACTOR SWAP: gemini-2.5-flash-lite | "
              f"facts cache_root={extractor_cache_root}")

    run_dir = RUNS_ROOT / args.iter_id

    judge_calls_log: list[dict] = []
    for i, entry in enumerate(zettels, 1):
        wz_id = entry["workspace_zettel_id"]
        src_type = entry.get("source_type", "web")
        data_dir = DATA_ROOT / wz_id
        if not data_dir.exists():
            print(f"  [{i}/{len(zettels)}] SKIP {wz_id}: _data bundle missing")
            continue
        source_text = (data_dir / "source_text.md").read_text(encoding="utf-8")
        summary_json = json.loads((data_dir / "summary.json").read_text(encoding="utf-8"))

        if not source_text.strip() or not summary_json:
            print(f"  [{i}/{len(zettels)}] SKIP {wz_id}: empty source or summary")
            continue

        atomic_facts = await _ensure_atomic_facts(
            manifest_entry=entry, source_text=source_text,
            extractor_client=extractor_client, rubric_path=RUBRIC_PATH,
            cache_root=extractor_cache_root,
        )

        for kind in judge_kinds:
            judge_client, _role_tag, judge_model_id = judge_clients[kind]
            cache_dir = CACHE_ROOT / f"judge_{('gemini' if kind=='primary' else 'claude')}"
            try:
                payload = await _evaluate_one_zettel(
                    manifest_entry=entry, judge_kind=kind, judge_client=judge_client,
                    judge_model_id=judge_model_id, atomic_facts=atomic_facts,
                    rubric_yaml=rubric_yaml, source_text=source_text,
                    summary_json=summary_json, cache_dir=cache_dir,
                    force_refresh=args.force_refresh,
                    compute_atomic_facts_call=None,
                )
            except Exception as exc:
                print(f"  [{i}/{len(zettels)}] FAIL judge={kind} wz={wz_id[:8]}: "
                      f"{type(exc).__name__}: {str(exc)[:120]}")
                continue

            # Stamp judge_kind, write to runs dir. multi_judge → per-judge
            # filenames so a jury (e.g. iter-004) keeps every judge's payload.
            _write_per_zettel(
                run_dir=run_dir,
                source_type=src_type,
                wz_id=wz_id,
                payload=payload,
                multi_judge=len(judge_kinds) > 1,
            )

            ev_meta = payload.get("evaluator_metadata", {}) or {}
            judge_calls_log.append({
                "wz_zettel_id": wz_id,
                "judge_kind": kind,
                "judge_model_requested": payload["_meta"]["judge_model_requested"],
                "judge_model_used": payload["_meta"]["judge_model_used"],
                "input_tokens": ev_meta.get("total_tokens_in", 0),
                "output_tokens": ev_meta.get("total_tokens_out", 0),
                "latency_ms": payload["_meta"]["latency_ms"],
                "cache_hit": payload.get("_cache_hit", False),
                "source_type": src_type,
            })
            status = "CACHE" if payload.get("_cache_hit") else "FRESH"
            print(f"  [{i}/{len(zettels)}] {status:5s} judge={kind:9s} wz={wz_id[:8]} "
                  f"composite={(payload.get('rubric',{}).get('caps_applied',{})!='unset')} "
                  f"src={src_type}")

    # Emit config.json + telemetry.json
    # When --wz-filter is set, this is a partial re-run (hot-fix patch). Do NOT
    # overwrite the original full-run config.json / telemetry.json — instead emit
    # an auditable patches/<timestamp>.json that records what was re-evaluated
    # and why (operator-supplied context lives in commit messages, not here).
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.wz_filter:
        patches_dir = run_dir / "patches"
        patches_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        patch_payload = {
            "iter_id": args.iter_id,
            "patched_at": datetime.now(timezone.utc).isoformat(),
            "git_sha": _git_sha(),
            "wz_filter": args.wz_filter,
            "judges_active": judge_kinds,
            "n_zettels_evaluated": len(zettels),
            "telemetry": _aggregate_telemetry(judge_calls_log),
        }
        patch_path = patches_dir / f"patch_{ts}_{args.wz_filter}.json"
        patch_path.write_text(
            json.dumps(patch_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"\n[02_run_judge] wrote patch record {patch_path}")
        print(f"[02_run_judge] original config.json / telemetry.json preserved")
        return 0

    config_snapshot = {
        "iter_id": args.iter_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "manifest_sha256": _sha256(MANIFEST.read_bytes()),
        "rubric_sha256": _sha256(RUBRIC_PATH.read_bytes()),
        "judges_yaml_sha256": _sha256(JUDGES_YAML.read_bytes()),
        "judges_active": judge_kinds,
        "n_zettels_evaluated": len(zettels),
        "max_zettels_arg": args.max_zettels,
        "override_calibration": args.override_calibration,
    }
    (run_dir / "config.json").write_text(
        json.dumps(config_snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    telemetry = _aggregate_telemetry(judge_calls_log)
    (run_dir / "telemetry.json").write_text(
        json.dumps(telemetry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\n[02_run_judge] wrote {run_dir/'config.json'}")
    print(f"[02_run_judge] wrote {run_dir/'telemetry.json'}")
    return 0


def _git_sha() -> str:
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _aggregate_telemetry(calls: list[dict]) -> dict:
    from collections import Counter
    by_kind = Counter(c["judge_kind"] for c in calls)
    by_source = Counter(c["source_type"] for c in calls)
    total_in = sum(c.get("input_tokens", 0) for c in calls)
    total_out = sum(c.get("output_tokens", 0) for c in calls)
    cache_hits = sum(1 for c in calls if c.get("cache_hit"))
    # Cost estimate per cited 2026-05 pricing (see METHODOLOGY §19.3.1)
    gemini_in = sum(c.get("input_tokens", 0) for c in calls if c["judge_kind"] == "primary" and not c.get("cache_hit"))
    gemini_out = sum(c.get("output_tokens", 0) for c in calls if c["judge_kind"] == "primary" and not c.get("cache_hit"))
    claude_in = sum(c.get("input_tokens", 0) for c in calls if c["judge_kind"] == "secondary" and not c.get("cache_hit"))
    claude_out = sum(c.get("output_tokens", 0) for c in calls if c["judge_kind"] == "secondary" and not c.get("cache_hit"))
    cost = {
        "gemini_usd": round(gemini_in * 0.30 / 1e6 + gemini_out * 2.50 / 1e6, 4),
        "claude_usd": round(claude_in * 1.00 / 1e6 + claude_out * 5.00 / 1e6, 4),
    }
    cost["total_usd"] = round(cost["gemini_usd"] + cost["claude_usd"], 4)
    return {
        "n_calls": len(calls),
        "cache_hits": cache_hits,
        "by_judge_kind": dict(by_kind),
        "by_source_type": dict(by_source),
        "tokens_in_total": total_in,
        "tokens_out_total": total_out,
        "cost_estimate": cost,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iter", required=True, dest="iter_id",
                    help="iter id matching a row in judges.yaml::run_matrix")
    ap.add_argument("--judge", choices=["primary", "secondary", "both"], default=None)
    ap.add_argument("--swap-extractor", action="store_true",
                    help="force the gemini-2.5-flash-lite atomic-facts extractor + a "
                         "separate facts cache (override; auto-enabled for iters with "
                         "extractor=experimental_swap in judges.yaml, e.g. iter-005)")
    ap.add_argument("--max-zettels", type=int, default=None)
    ap.add_argument("--wz-filter", type=str, default=None,
                    help="re-run only the zettel whose workspace_zettel_id starts with this prefix "
                         "(used for targeted re-evals after a hot-fix; cost-control vs --force-refresh)")
    ap.add_argument("--force-refresh", action="store_true")
    ap.add_argument("--override-calibration", action="store_true")
    ap.add_argument("--override-status", action="store_true",
                    help="run an iter even if its status != active")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
