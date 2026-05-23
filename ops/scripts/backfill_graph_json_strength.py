"""LD-3 one-shot: backfill graph.json links with strength + tier + relation_source.

Every link in the file-store graph gets:
  - connection_strength = 1.0  (LD-3: demo/marketing surface renders at full strength)
  - tier = "strong"
  - relation_source = "tag_coincidence"  (audit trail; never renders)

Idempotent: re-running on an already-backfilled file is a no-op.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    path = Path(__file__).resolve().parent.parent.parent / "website" / "features" / "knowledge_graph" / "content" / "graph.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for link in graph.get("links", []):
        if "connection_strength" not in link:
            link["connection_strength"] = 1.0
            changed += 1
        if "tier" not in link:
            link["tier"] = "strong"
        if "relation_source" not in link:
            link["relation_source"] = "tag_coincidence"
    path.write_text(
        json.dumps(graph, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"graph.json: backfilled {changed} link(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
