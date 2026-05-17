"""Autonomous KG-recommendation applicator with audit logging."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def apply_recommendations(
    *,
    recs_path: Path,
    user_id: str,
    supabase: Any,
    dry_run: bool = False,
) -> dict:
    """Apply KG recommendations to the user's Zettel graph.

    The legacy applicator mutated per-user slug-keyed ``public.kg_links`` /
    ``public.kg_nodes``, both dropped in the DB-v2 purge with no v2
    equivalent (workspace_zettels is UUID/workspace-scoped with no
    relation/slug; kg.kg_edges is the unrelated entity graph). The legacy
    write path is purged rather than retained behind dead skip-loops;
    re-applying recs requires a v2 KG-recommendation model that does not
    exist yet. Args are retained for CLI/test call-contract stability.
    """
    del recs_path, user_id, supabase, dry_run  # contract parity
    raise NotImplementedError(
        "apply_kg_recommendations.apply_recommendations: v2 eval-driver "
        "rebuild pending — legacy slug-keyed kg_links/kg_nodes write path "
        "purged; see rag_eval_v2 (Phase E)"
    )


def _changelog_append(path: Path, summary: dict, iter_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [f"\n## {iter_id} — {ts}\n"]
    for app in summary.get("applied", []):
        lines.append(f"- APPLIED `{app['type']}` — {json.dumps(app['payload'])}\n")
    for skip in summary.get("skipped", []):
        lines.append(f"- SKIPPED `{skip['type']}` — reason: {skip.get('reason')}\n")
    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iter", required=True, help="e.g. youtube/iter-02")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true",
                        help="Required for merge_nodes / reingest_node application.")
    args = parser.parse_args()

    # apply_recommendations raises NotImplementedError (legacy slug-keyed
    # write path purged with DB v2). No Supabase client is constructed here
    # because there is no v2 write path to reach.
    recs_path = Path("docs/rag_eval") / args.iter / "kg_recommendations.json"
    summary = asyncio.run(apply_recommendations(
        recs_path=recs_path, user_id=args.user_id, supabase=None, dry_run=args.dry_run,
    ))
    print(json.dumps(summary, indent=2))
    if not args.dry_run and summary.get("applied_count", 0) > 0:
        _changelog_append(Path("docs/rag_eval/_kg_changelog.md"), summary, args.iter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
