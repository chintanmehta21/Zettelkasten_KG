"""One-shot: register iter-23 github (pydantic) zettel under Naruto via the
canonical ``persist_summarized_result`` fanout (Supabase + file graph + entity extraction)."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

MAIN_ROOT = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault")
load_dotenv(MAIN_ROOT / "supabase" / ".env", override=False)

WORKTREE = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.worktrees\eval-summary-engine-v2-scoring")
sys.path.insert(0, str(WORKTREE))

from website.core.persist import persist_summarized_result  # noqa: E402
from website.features.summarization_engine.evaluator.models import EvalResult, composite_score  # noqa: E402

NARUTO_RENDER_UUID = "f2105544-b73d-4946-8329-096d82f070d3"
ITER_DIR = WORKTREE / "docs" / "summary_eval" / "github" / "iter-23"
ITER_NUM = 23
ITER_SOURCE = "github"


def main() -> int:
    summary = json.loads((ITER_DIR / "summary.json").read_text(encoding="utf-8"))
    eval_data = json.loads((ITER_DIR / "eval.json").read_text(encoding="utf-8"))

    meta = summary.get("metadata", {})
    sp = meta.get("structured_payload", {}) or {}
    mini_title = summary.get("mini_title") or sp.get("mini_title") or "pydantic/pydantic"
    brief = summary.get("brief_summary") or sp.get("brief_summary") or ""
    detailed_raw = summary.get("detailed_summary") or sp.get("detailed_summary") or []
    # Pass structured detailed_summary straight through; persist's
    # _normalize_summary_text handles list/dict -> markdown conversion
    # via _coerce_detailed_to_markdown. Stringifying here with f"- {item}"
    # produced a Python repr (single-quoted dict keys), which broke the
    # frontend renderer for gh-pydantic-pydantic on prod (iter-23 regression).
    detailed = detailed_raw
    tags = summary.get("tags") or sp.get("tags") or []

    url = meta.get("url") or "https://github.com/pydantic/pydantic"
    source_type = meta.get("source_type") or ITER_SOURCE

    # Composite via evaluator library (same code used by eval_loop).
    composite = composite_score(EvalResult(**eval_data))

    archetype_pre = sp.get("_github_archetype") or {}
    dense_verify = sp.get("_dense_verify") or {}

    result = {
        "source_url": url,
        "source_type": source_type,
        "title": mini_title,
        "brief_summary": brief,
        "detailed_summary": detailed,
        "tags": tags,
        "metadata": {
            "eval_iter": ITER_NUM,
            "eval_source": ITER_SOURCE,
            "composite": composite,
            "eval_branch": "codex/summarization-engine-execution",
            "archetype_pre": archetype_pre.get("archetype") if isinstance(archetype_pre, dict) else None,
            "archetype_pre_confidence": archetype_pre.get("confidence") if isinstance(archetype_pre, dict) else None,
            "dense_verify_archetype": dense_verify.get("archetype") if isinstance(dense_verify, dict) else None,
            "evaluator_model": eval_data.get("evaluator_metadata", {}).get("model_used"),
        },
    }

    outcome = asyncio.run(
        persist_summarized_result(
            result,
            user_sub=NARUTO_RENDER_UUID,
            captured_on=date.today(),
        )
    )

    if outcome.supabase_saved:
        status = "created"
    elif outcome.supabase_duplicate:
        status = "duplicate"
    else:
        status = "file_only"

    print(json.dumps({
        "status": status,
        "file_node_id": outcome.file_node_id,
        "supabase_node_id": outcome.supabase_node_id,
        "kg_user_id": outcome.kg_user_id,
        "render_user_id": NARUTO_RENDER_UUID,
        "composite": composite,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
