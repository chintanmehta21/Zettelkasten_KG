import asyncio
import json
from unittest.mock import MagicMock

import pytest

from ops.scripts.apply_kg_recommendations import apply_recommendations


def test_apply_recommendations_purged_raises(tmp_path):
    # DB-v2 purge: add_link/add_tag/orphan_warning wrote to legacy per-user
    # slug-keyed kg_links/kg_nodes, DROPPED in the v2 purge with no v2
    # equivalent. The legacy write path (and its dead skip-loop) was fully
    # purged; apply_recommendations now exposes one honest seam: it raises
    # NotImplementedError instead of fabricating cross-tenant writes.
    recs_path = tmp_path / "kg_recommendations.json"
    recs_path.write_text(json.dumps([
        {"type": "add_link", "payload": {"from_node": "a", "to_node": "b",
         "suggested_relation": "rel"}, "evidence_query_ids": ["q1"],
         "confidence": 0.8, "status": "auto_apply"},
        {"type": "merge_nodes", "payload": {"node_a": "x", "node_b": "y",
         "similarity": 0.9}, "evidence_query_ids": ["q1"],
         "confidence": 0.9, "status": "quarantined"},
    ]), encoding="utf-8")
    with pytest.raises(NotImplementedError, match="rag_eval_v2"):
        asyncio.run(apply_recommendations(
            recs_path=recs_path, user_id="user-uuid", supabase=None,
            dry_run=False,
        ))


def test_apply_recommendations_purged_raises_even_on_dry_run(tmp_path):
    # The legacy dry-run branch was part of the purged write path; the seam
    # raises regardless of dry_run (no fabricated writes are possible).
    recs_path = tmp_path / "kg_recommendations.json"
    recs_path.write_text(json.dumps([
        {"type": "add_link", "payload": {"from_node": "a", "to_node": "b",
         "suggested_relation": "rel"}, "evidence_query_ids": ["q1"],
         "confidence": 0.8, "status": "auto_apply"},
    ]), encoding="utf-8")
    with pytest.raises(NotImplementedError, match="rag_eval_v2"):
        asyncio.run(apply_recommendations(
            recs_path=recs_path, user_id="user-uuid", supabase=None,
            dry_run=True,
        ))
