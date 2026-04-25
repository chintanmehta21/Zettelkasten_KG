import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import json
import asyncio

from ops.scripts.apply_kg_recommendations import apply_recommendations


def test_apply_only_auto_apply_status(tmp_path):
    recs_path = tmp_path / "kg_recommendations.json"
    recs_path.write_text(json.dumps([
        {"type": "add_link", "payload": {"from_node": "a", "to_node": "b", "suggested_relation": "rel"},
         "evidence_query_ids": ["q1"], "confidence": 0.8, "status": "auto_apply"},
        {"type": "merge_nodes", "payload": {"node_a": "x", "node_b": "y", "similarity": 0.9},
         "evidence_query_ids": ["q1"], "confidence": 0.9, "status": "quarantined"},
    ]), encoding="utf-8")
    supabase = MagicMock()
    supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
    summary = asyncio.run(apply_recommendations(
        recs_path=recs_path, user_id="user-uuid", supabase=supabase, dry_run=False,
    ))
    assert summary["applied_count"] == 1
    assert summary["skipped_count"] == 1


def test_dry_run_makes_no_writes(tmp_path):
    recs_path = tmp_path / "kg_recommendations.json"
    recs_path.write_text(json.dumps([
        {"type": "add_link", "payload": {"from_node": "a", "to_node": "b", "suggested_relation": "rel"},
         "evidence_query_ids": ["q1"], "confidence": 0.8, "status": "auto_apply"},
    ]), encoding="utf-8")
    supabase = MagicMock()
    summary = asyncio.run(apply_recommendations(
        recs_path=recs_path, user_id="user-uuid", supabase=supabase, dry_run=True,
    ))
    supabase.table.return_value.insert.assert_not_called()
    assert summary["applied_count"] == 0
    assert summary["dry_run"] is True
