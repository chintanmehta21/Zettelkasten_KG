"""Diagnose Naruto user rows + where the 3 new iter zettels actually landed."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

MAIN_ROOT = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault")
load_dotenv(MAIN_ROOT / "supabase" / ".env", override=False)

WORKTREE = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.worktrees\eval-summary-engine-v2-scoring")
sys.path.insert(0, str(WORKTREE))

from website.core.supabase_kg.repository import KGRepository  # noqa: E402


def main() -> int:
    repo = KGRepository()
    sb = repo._client

    # ALL users whose render_user_id or display_name contains "naruto"
    res = (
        sb.table("kg_users")
        .select("id,render_user_id,display_name,created_at")
        .execute()
    )
    users = res.data or []
    naruto_like = [u for u in users if ("naruto" in str(u.get("render_user_id", "")).lower() or "naruto" in str(u.get("display_name", "") or "").lower())]
    print("=== Naruto-like kg_users rows ===")
    for u in naruto_like:
        print(json.dumps(u, default=str))

    # For each naruto-like user, count nodes + show latest 5
    for u in naruto_like:
        uid = u["id"]
        cnt = sb.table("kg_nodes").select("id", count="exact").eq("user_id", uid).execute()
        print(f"\n--- user_id={uid} render_user_id={u.get('render_user_id')} node_count={cnt.count} ---")
        latest = (
            sb.table("kg_nodes")
            .select("id,url,source_type,created_at,updated_at,metadata")
            .eq("user_id", uid)
            .order("updated_at", desc=True)
            .limit(8)
            .execute()
        )
        for n in latest.data or []:
            meta = n.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            iter_ = meta.get("eval_iter") if isinstance(meta, dict) else None
            src = meta.get("eval_source") if isinstance(meta, dict) else None
            print(f"  upd={n['updated_at']} src={n['source_type']} iter={iter_}/{src} id={n['id']} url={n['url'][:70]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
