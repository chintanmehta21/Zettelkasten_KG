"""One-shot: register iter-20 youtube zettel under Naruto via KGRepository."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

# Load supabase/.env from the main (non-worktree) project root
MAIN_ROOT = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault")
load_dotenv(MAIN_ROOT / "supabase" / ".env", override=False)

WORKTREE = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.worktrees\eval-summary-engine-v2-scoring")
sys.path.insert(0, str(WORKTREE))

from website.core.supabase_kg.repository import KGRepository  # noqa: E402
from website.core.supabase_kg.models import KGNodeCreate  # noqa: E402

NARUTO_RENDER_UUID = "f2105544-b73d-4946-8329-096d82f070d3"

ITER_DIR = WORKTREE / "docs" / "summary_eval" / "youtube" / "iter-20"


def main() -> int:
    summary = json.loads((ITER_DIR / "summary.json").read_text(encoding="utf-8"))
    eval_data = json.loads((ITER_DIR / "eval.json").read_text(encoding="utf-8"))

    meta = summary.get("metadata", {})
    sp = meta.get("structured_payload", {}) or {}
    mini_title = summary.get("mini_title") or sp.get("mini_title") or "untitled"
    brief = summary.get("brief_summary") or sp.get("brief_summary") or ""
    detailed = summary.get("detailed_summary") or sp.get("detailed_summary") or ""
    tags = summary.get("tags") or sp.get("tags") or []

    url = meta.get("url") or "https://www.youtube.com/watch?v=CtrhU7GOjOg"
    source_type = meta.get("source_type") or "youtube"
    confidence = meta.get("extraction_confidence") or "high"
    engine_version = meta.get("engine_version") or "2.0.0"

    # Compute node id the same way graph_store does: yt- + slugify(title, 24)
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", mini_title.lower()).strip("-")[:24].rstrip("-")
    node_id = f"yt-{slug}"

    composite = 0.0
    try:
        comps = eval_data.get("rubric", {}).get("components", [])
        composite = sum(c.get("score", 0) for c in comps)
        caps = eval_data.get("rubric", {}).get("caps_applied", {}) or {}
        applied = [v for v in caps.values() if isinstance(v, (int, float))]
        if applied:
            composite = min(composite, min(applied))
    except Exception:
        pass

    summary_blob = json.dumps({
        "brief_summary": brief,
        "detailed_summary": detailed,
    })

    payload = KGNodeCreate(
        id=node_id,
        name=mini_title,
        source_type=source_type,
        summary=summary_blob,
        tags=list(tags),
        url=url,
        extraction_confidence=confidence,
        engine_version=engine_version,
        metadata={
            "eval_iter": 20,
            "eval_source": "youtube",
            "composite": composite,
            "eval_branch": "codex/summarization-engine-execution",
        },
    )

    repo = KGRepository()
    naruto = repo.get_user_by_render_id(NARUTO_RENDER_UUID)
    if naruto is None:
        raise RuntimeError(f"Naruto user not found for render_user_id={NARUTO_RENDER_UUID}")
    user_uuid: UUID = naruto.id if isinstance(naruto.id, UUID) else UUID(str(naruto.id))

    if repo.node_exists(user_uuid, url):
        existing = (
            repo._client.table("kg_nodes")
            .select("id")
            .eq("user_id", str(user_uuid))
            .eq("url", url)
            .limit(1)
            .execute()
        )
        existing_id = existing.data[0]["id"] if existing.data else node_id
        print(json.dumps({
            "status": "already_exists",
            "node_id": existing_id,
            "user_id": str(user_uuid),
            "render_user_id": NARUTO_RENDER_UUID,
        }))
        return 0

    try:
        node = repo.add_node(user_uuid, payload)
        print(json.dumps({
            "status": "created",
            "node_id": node.id,
            "user_id": str(user_uuid),
            "render_user_id": NARUTO_RENDER_UUID,
            "composite": composite,
        }))
        return 0
    except Exception as exc:
        if "duplicate key" in str(exc).lower() or "kg_nodes_pkey" in str(exc).lower():
            print(json.dumps({
                "status": "duplicate_id",
                "node_id": node_id,
                "user_id": str(user_uuid),
                "render_user_id": NARUTO_RENDER_UUID,
            }))
            return 0
        raise


if __name__ == "__main__":
    sys.exit(main())
