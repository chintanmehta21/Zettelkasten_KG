"""Verify iter-10 newsletter zettel exists under Naruto."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

MAIN_ROOT = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault")
load_dotenv(MAIN_ROOT / "supabase" / ".env", override=False)

WORKTREE = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.worktrees\eval-summary-engine-v2-scoring")
sys.path.insert(0, str(WORKTREE))

from website.core.supabase_kg.repository import KGRepository  # noqa: E402

NARUTO_RENDER_UUID = "f2105544-b73d-4946-8329-096d82f070d3"
URL = "https://newsletter.pragmaticengineer.com/p/the-product-minded-engineer"


def main() -> int:
    repo = KGRepository()
    naruto = repo.get_user_by_render_id(NARUTO_RENDER_UUID)
    user_uuid = str(naruto.id)
    rows = (
        repo._client.table("kg_nodes")
        .select("id, name, source_type, tags, url, metadata, created_at, updated_at")
        .eq("user_id", user_uuid)
        .eq("url", URL)
        .execute()
    )
    print(json.dumps({
        "query_time": datetime.now(timezone.utc).isoformat(),
        "user_id": user_uuid,
        "rows": rows.data,
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
