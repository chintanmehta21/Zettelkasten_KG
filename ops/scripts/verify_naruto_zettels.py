"""Verify YT iter-20 and Reddit iter-10 zettels under Naruto user."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

MAIN_ROOT = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault")
load_dotenv(MAIN_ROOT / "supabase" / ".env", override=False)

WORKTREE = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.worktrees\eval-summary-engine-v2-scoring")
sys.path.insert(0, str(WORKTREE))

from website.core.supabase_kg.repository import KGRepository  # noqa: E402

NARUTO_RENDER_UUID = "f2105544-b73d-4946-8329-096d82f070d3"


def main() -> int:
    repo = KGRepository()
    naruto = repo.get_user_by_render_id(NARUTO_RENDER_UUID)
    if naruto is None:
        print(json.dumps({"error": "naruto user not found", "render_uuid": NARUTO_RENDER_UUID}))
        return 1
    user_uuid: UUID = naruto.id if isinstance(naruto.id, UUID) else UUID(str(naruto.id))
    print(json.dumps({
        "naruto_user_id": str(user_uuid),
        "naruto_render_id": NARUTO_RENDER_UUID,
        "naruto_name": getattr(naruto, "name", None) or getattr(naruto, "display_name", None),
    }))

    # Load iter summary URLs
    yt_summary = json.loads((WORKTREE / "docs" / "summary_eval" / "youtube" / "iter-20" / "summary.json").read_text(encoding="utf-8"))
    rd_summary = json.loads((WORKTREE / "docs" / "summary_eval" / "reddit" / "iter-10" / "summary.json").read_text(encoding="utf-8"))

    yt_url = (yt_summary.get("metadata", {}) or {}).get("url") or ""
    rd_url = (rd_summary.get("metadata", {}) or {}).get("url") or ""

    print(json.dumps({"yt_url": yt_url, "rd_url": rd_url}))

    # List all Naruto nodes sorted by created_at desc
    res = (
        repo._client.table("kg_nodes")
        .select("id,name,url,source_type,created_at,updated_at,metadata")
        .eq("user_id", str(user_uuid))
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )
    nodes = res.data or []
    print(f"--- Total nodes under Naruto: {len(nodes)} (showing up to 50, sorted by created_at desc) ---")
    for n in nodes[:20]:
        meta = n.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        eval_iter = meta.get("eval_iter") if isinstance(meta, dict) else None
        eval_source = meta.get("eval_source") if isinstance(meta, dict) else None
        print(f"  {n['created_at']}  [{n['source_type']}]  {n['id']}  iter={eval_iter}/{eval_source}  url={n['url'][:80]}")

    # Check for YT and Reddit iter URLs specifically
    print("--- Lookup by URL ---")
    if yt_url:
        yt_match = [n for n in nodes if n.get("url") == yt_url]
        print(f"YT iter-20 URL match: {len(yt_match)} node(s)")
        for n in yt_match:
            meta = n.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            print(f"   id={n['id']}  created={n['created_at']}  updated={n['updated_at']}  iter_meta={meta.get('eval_iter')}/{meta.get('eval_source')}")
    if rd_url:
        rd_match = [n for n in nodes if n.get("url") == rd_url]
        print(f"RD iter-10 URL match: {len(rd_match)} node(s)")
        for n in rd_match:
            meta = n.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            print(f"   id={n['id']}  created={n['created_at']}  updated={n['updated_at']}  iter_meta={meta.get('eval_iter')}/{meta.get('eval_source')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
