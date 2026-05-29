"""08_canary_drift.py — daily canary set + drift hash detection.

WIRED implementation (2026-05-28 TDD). Eval-time only on operator laptop.
Never runs against the production droplet.

Flow:
  1. Load _config/canary_set.json (7 deterministic prompts).
  2. For each item, call each configured judge at temperature 0.0.
  3. Hash the response text (sha256 over UTF-8 bytes).
  4. With --save-baseline: store the hash map under
     canary_set.json::baselines[<judge_bucket>].
     Without --save-baseline: compare every hash to the saved baseline;
     any mismatch is reported as drift and the script exits non-zero.

Bucket naming:
  primary  -> baselines["primary_judge_gemini"]
  secondary -> baselines["secondary_judge_claude"]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
CANARY_PATH = REPO_ROOT / "docs" / "zettel_eval_v1" / "_config" / "canary_set.json"
ANALYSIS = REPO_ROOT / "docs" / "zettel_eval_v1" / "analysis"

BUCKET = {
    "primary": "primary_judge_gemini",
    "secondary": "secondary_judge_claude",
}


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class FakeJudge:
    """Deterministic stub-judge for tests + --fake-judge."""
    def __init__(self, response_text: str = "OK"):
        self.response_text = response_text
        self.model_name = "fake-judge-1"

    async def call(self, system: str, user: str) -> tuple[str, str]:
        # response, model_used
        return self.response_text, self.model_name


async def _call_real_judge(judge_kind: str, system: str, user: str) -> tuple[str, str]:
    if judge_kind == "primary":
        from ops.scripts.lib.gemini_factory import make_client
        cli = make_client()
        # The TieredGeminiClient.generate combines system + user via system_instruction
        result = await cli.generate(
            user, tier="flash", role="canary",
            system_instruction=system or None,
            temperature=0.0, max_output_tokens=1024,
        )
        return (result.text or "").strip(), getattr(result, "model_used", "?")
    elif judge_kind == "secondary":
        from docs.zettel_eval_v1.scripts.lib.anthropic_factory import make_client
        cli = make_client()
        result = await cli.generate(
            user, tier=None, role="canary",
            system_instruction=system or None,
            temperature=0.0, max_output_tokens=1024,
        )
        return (result.text or "").strip(), getattr(result, "model_used", "?")
    raise ValueError(f"unknown judge_kind {judge_kind}")


async def main_async(args) -> int:
    doc = json.loads(CANARY_PATH.read_text(encoding="utf-8"))
    items = doc["items"]

    judges = ["primary", "secondary"] if args.judge == "both" else [args.judge]

    drift_found = False
    fake = FakeJudge(response_text=args.fake_response) if args.fake_judge else None

    full_report: dict = {"checked_at": datetime.now(timezone.utc).isoformat(),
                         "items_per_judge": {}}

    for jk in judges:
        bucket = BUCKET[jk]
        prior_hashes: dict[str, str] = doc.get("baselines", {}).get(bucket, {}) or {}
        new_hashes: dict[str, str] = {}
        per_item_report = []

        for item in items:
            sys_instr = item.get("system_instruction") or ""
            usr = item.get("user_prompt") or ""
            try:
                if fake:
                    text, model = await fake.call(sys_instr, usr)
                else:
                    text, model = await _call_real_judge(jk, sys_instr, usr)
            except Exception as exc:
                per_item_report.append({
                    "id": item["id"], "judge": jk,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                drift_found = True
                continue
            h = _sha(text)
            new_hashes[item["id"]] = h
            prev = prior_hashes.get(item["id"])
            status = "BASELINE" if args.save_baseline else (
                "MATCH" if (prev == h) else ("NEW" if prev is None else "DRIFT")
            )
            if status == "DRIFT":
                drift_found = True
            per_item_report.append({
                "id": item["id"], "judge": jk,
                "model_used": model, "response_hash": h,
                "previous_hash": prev, "status": status,
            })

        full_report["items_per_judge"][jk] = per_item_report

        if args.save_baseline:
            doc.setdefault("baselines", {})[bucket] = new_hashes

    if args.save_baseline:
        CANARY_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[08] baseline saved for judges={judges} ({sum(len(v) for v in doc['baselines'].values())} hashes)")
        return 0

    # Optional report emit
    if args.emit_report:
        ANALYSIS.mkdir(parents=True, exist_ok=True)
        path = ANALYSIS / args.emit_report
        path.write_text(json.dumps(full_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[08] report written: {path}")

    # Print summary
    for jk, items_report in full_report["items_per_judge"].items():
        n_drift = sum(1 for r in items_report if r.get("status") == "DRIFT")
        n_match = sum(1 for r in items_report if r.get("status") == "MATCH")
        n_new = sum(1 for r in items_report if r.get("status") == "NEW")
        n_err = sum(1 for r in items_report if r.get("error"))
        print(f"[08] judge={jk}  match={n_match}  drift={n_drift}  new={n_new}  err={n_err}")

    if drift_found:
        print("[08] DRIFT DETECTED — vendor model or upstream behavior changed since last baseline.")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--judge", choices=["primary", "secondary", "both"], default="both")
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--emit-report", type=str, default=None,
                    help="filename under analysis/ to write the per-item report JSON")
    ap.add_argument("--canary-run-id", type=str, default=None,
                    help="reserved; not used currently")
    ap.add_argument("--fake-judge", action="store_true",
                    help="use FakeJudge — for tests + dry-runs")
    ap.add_argument("--fake-response", type=str, default="OK",
                    help="FakeJudge response text (drives the hash)")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
