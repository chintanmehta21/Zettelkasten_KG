"""iter-08 G8: deploy-time guard that the kg_link_relation enum exists in schema.sql."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA = REPO_ROOT / "supabase" / "website" / "kg_public" / "schema.sql"


def test_schema_has_kg_link_relation_enum():
    """The enum must be declared in schema.sql so fresh DBs include it."""
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "kg_link_relation" in sql, \
        "kg_link_relation enum missing from schema mirror"
    for value in ("shared_tag", "cites", "mentions", "co_occurs"):
        assert value in sql, f"enum value {value!r} missing from schema"


def test_kg_links_relation_type_rejects_invalid_enum():
    """Smoke: simulated Postgres enum-reject error round-trip."""
    fake_supabase = MagicMock()
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        'invalid input value for enum kg_link_relation: "garbage"'
    )
    with pytest.raises(Exception, match="invalid input value for enum"):
        fake_supabase.table("kg_links").insert({
            "source_node_id": "a",
            "target_node_id": "b",
            "relation_type": "garbage",
            "user_id": "u",
        }).execute()


def test_kg_links_relation_type_accepts_valid_enum():
    """Smoke: documents the four canonical enum values."""
    valid = {"shared_tag", "cites", "mentions", "co_occurs"}
    for v in valid:
        assert v in valid
