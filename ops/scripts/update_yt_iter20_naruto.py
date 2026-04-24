"""Update Naruto's YT petrodollar node with iter-20 payload (in-place)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

MAIN_ROOT = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault")
load_dotenv(MAIN_ROOT / "supabase" / ".env", override=False)

WORKTREE = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.worktrees\eval-summary-engine-v2-scoring")
sys.path.insert(0, str(WORKTREE))

from website.core.supabase_kg.repository import KGRepository  # noqa: E402

NARUTO_RENDER_UUID = "f2105544-b73d-4946-8329-096d82f070d3"
ITER_DIR = WORKTREE / "docs" / "summary_eval" / "youtube" / "iter-20"
NODE_ID = "yt-petrodollar-system-mechanism-benefits-v"


def main() -> int:
    summary = json.loads((ITER_DIR / "summary.json").read_text(encoding="utf-8"))
    eval_data = json.loads((ITER_DIR / "eval.json").read_text(encoding="utf-8"))

    meta = summary.get("metadata", {}) or {}
    mini_title = summary.get("mini_title") or "Petrodollar s Decline US Dominance"
    brief = summary.get("brief_summary") or ""
    detailed = summary.get("detailed_summary") or []
    tags = summary.get("tags") or []
    url = meta.get("url") or "https://www.youtube.com/watch?v=CtrhU7GOjOg"

    comps = eval_data.get("rubric", {}).get("components", [])
    raw_sum = sum(c.get("score", 0) for c in comps)
    caps = eval_data.get("rubric", {}).get("caps_applied", {}) or {}
    applied = [v for v in caps.values() if isinstance(v, (int, float))]
    composite = min(raw_sum, min(applied)) if applied else raw_sum

    summary_blob = json.dumps({
        "brief_summary": brief,
        "detailed_summary": detailed,
    })

    repo = KGRepository()
    naruto = repo.get_user_by_render_id(NARUTO_RENDER_UUID)
    user_uuid: UUID = naruto.id if isinstance(naruto.id, UUID) else UUID(str(naruto.id))

    now = datetime.now(timezone.utc).isoformat()
    update = {
        "name": mini_title,
        "summary": summary_blob,
        "tags": list(tags),
        "url": url,
        "source_type": "youtube",
        "metadata": {
            "eval_iter": 20,
            "eval_source": "youtube",
            "composite": composite,
            "raw_rubric_sum": raw_sum,
            "caps_applied": caps,
            "eval_branch": "codex/summarization-engine-execution",
            "fail_reason": "speakers_absent -> generic_cap=75",
            "extraction_confidence": meta.get("extraction_confidence") or "high",
            "engine_version": meta.get("engine_version") or "2.0.0",
        },
        "updated_at": now,
    }

    res = (
        repo._client.table("kg_nodes")
        .update(update)
        .eq("id", NODE_ID)
        .eq("user_id", str(user_uuid))
        .execute()
    )

    rows = res.data or []
    print(json.dumps({
        "status": "updated" if rows else "no_match",
        "node_id": NODE_ID,
        "user_id": str(user_uuid),
        "render_user_id": NARUTO_RENDER_UUID,
        "rows": len(rows),
        "composite": composite,
        "raw_rubric_sum": raw_sum,
    }))
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
