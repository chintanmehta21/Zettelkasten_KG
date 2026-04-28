"""Iter-03 end-to-end browser verification — runbook helper.

The actual browser steps run via Claude in Chrome MCP tools
(``mcp__Claude_in_Chrome__navigate`` / ``read_page`` / ``computer`` / ...)
from the controller session — see
``docs/rag_eval/common/knowledge-management/iter-03/verification.md``.

This script's only jobs:
  * Load the 13 iter-03 eval queries.
  * Materialize an empty results template the controller fills in as the
    Chrome session walks through each step.
  * Print the queries as a tab-separated list so they can be pasted into
    a browser dev console for batch submission.

Usage:
    python ops/scripts/verify_iter_03_in_browser.py --emit-template
    python ops/scripts/verify_iter_03_in_browser.py --print-queries
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "docs" / "rag_eval" / "common" / "knowledge-management" / "iter-03"
QUERIES_PATH = EVAL_DIR / "queries.json"
RESULTS_PATH = EVAL_DIR / "verification_results.json"
SCREENSHOTS_DIR = EVAL_DIR / "screenshots"

logger = logging.getLogger("verify_iter_03")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_queries() -> list[dict]:
    payload = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "queries" in payload:
        return payload["queries"]
    return payload


def emit_template(queries: list[dict]) -> dict:
    """Build an empty results structure the controller fills as steps complete."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    template = {
        "iter": "iter-03",
        "deployed_sha": None,
        "captured_at": None,
        "checks": [
            {"id": 1, "name": "kasten_chooser_renders", "status": "pending", "evidence": "screenshots/01_chooser.png"},
            {"id": 2, "name": "composer_placeholder_uses_kasten_name", "status": "pending", "evidence": "screenshots/02_chat_composer.png"},
            {"id": 3, "name": "all_13_queries_answered_without_overrefusal", "status": "pending", "evidence": "screenshots/03_q_*.png"},
            {"id": 4, "name": "strong_mode_triggers_critic_loop", "status": "pending", "evidence": "answers.json"},
            {"id": 5, "name": "add_zettels_select_all_works", "status": "pending", "evidence": "screenshots/05_select_all.png"},
            {"id": 6, "name": "heartbeat_retry_fires_after_idle", "status": "pending", "evidence": "screenshots/06_heartbeat_retry.png"},
            {"id": 7, "name": "queue_ux_surfaces_503_retry_after", "status": "pending", "evidence": "screenshots/07_queue_503.png"},
            {"id": 8, "name": "debug_param_hidden_in_prod", "status": "pending", "evidence": "screenshots/08_debug_hidden.png"},
            {"id": 9, "name": "schema_drift_gate_blocks_drift", "status": "pending", "evidence": "deploy.log excerpt"},
            {"id": 10, "name": "sse_survives_blue_green_cutover", "status": "pending", "evidence": "screenshots/10_sse_cutover.png"},
        ],
        "queries": [
            {
                "qid": q.get("qid") or q.get("id"),
                "query": q.get("query") or q.get("text"),
                "expected_primary_citation": q.get("expected_primary_citation"),
                "answer": None,
                "primary_citation": None,
                "elapsed_ms": None,
                "verdict": "pending",
            }
            for q in queries
        ],
    }
    RESULTS_PATH.write_text(json.dumps(template, indent=2), encoding="utf-8")
    logger.info("wrote results template: %s", RESULTS_PATH)
    return template


def print_queries(queries: list[dict]) -> None:
    for q in queries:
        qid = q.get("qid") or q.get("id")
        text = q.get("query") or q.get("text")
        print(f"{qid}\t{text}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--emit-template", action="store_true")
    p.add_argument("--print-queries", action="store_true")
    args = p.parse_args(argv)

    if not (args.emit_template or args.print_queries):
        p.error("specify --emit-template or --print-queries")

    queries = load_queries()
    logger.info("loaded %d iter-03 queries from %s", len(queries), QUERIES_PATH)

    if args.emit_template:
        emit_template(queries)
    if args.print_queries:
        print_queries(queries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
