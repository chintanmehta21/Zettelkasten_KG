"""Phase B — two-level KG connection strength: schema + repository layer.

Covers:
  * KGRepository.upsert_edge / upsert_node write the right columns, including
    the two-level workspace_strength/global_strength and matched_via provenance.
  * Idempotent re-upsert: same natural key -> UPSERT (ON CONFLICT) not INSERT,
    so the scorer pass is replay-safe (no duplicate rows).
  * Workspace isolation (OWASP API1:2023 BOLA): an upsert for workspace A is
    scoped by workspace_id in BOTH the payload and the ON CONFLICT target, so
    workspace B's UUID never leaks into A's write and vice-versa.
  * Migration 46 structural invariants (idempotency guards, range CHECKs,
    natural-key UNIQUE for ON CONFLICT, render/analytics doc comments).

All Supabase access is mocked; no live DB.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from website.core.supabase_v2.repositories.kg_repository import KGRepository

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "supabase" / "website" / "_v2" / "46_kg_two_level_strength.sql"

WS_A = UUID("00000000-0000-0000-0000-00000000000a")
WS_B = UUID("00000000-0000-0000-0000-00000000000b")
EVIDENCE = UUID("00000000-0000-0000-0000-0000000000ee")


class _Execute:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return type("Resp", (), {"data": self.data})()


class _Table:
    def __init__(self, calls, schema, table):
        self.calls = calls
        self.schema = schema
        self.table = table

    def insert(self, payload):
        self.calls.append(("insert", self.schema, self.table, payload, {}))
        return _Execute([{"id": 7}])

    def upsert(self, payload, **kwargs):
        self.calls.append(("upsert", self.schema, self.table, payload, kwargs))
        return _Execute([{"id": 8}])


class _Schema:
    def __init__(self, calls, schema):
        self.calls = calls
        self.schema = schema

    def table(self, table):
        self.calls.append(("table", self.schema, table))
        return _Table(self.calls, self.schema, table)


class _Client:
    def __init__(self):
        self.calls = []

    def schema(self, schema):
        self.calls.append(("schema", schema))
        return _Schema(self.calls, schema)

    def table(self, name):  # pragma: no cover - must always be schema-scoped
        raise AssertionError(f"unscoped table call: {name}")


def _writes(client, op):
    return [c for c in client.calls if c[0] == op]


# ---------------------------------------------------------------------------
# Repository: column-write correctness
# ---------------------------------------------------------------------------

def test_upsert_edge_writes_two_level_strength_and_matched_via() -> None:
    client = _Client()
    repo = KGRepository(client)

    edge_id = repo.upsert_edge(
        workspace_id=WS_A,
        src_node_id=1,
        dst_node_id=2,
        relation_type="shared_tag",
        connection_strength=0.62,
        workspace_strength=0.71,
        global_strength=0.48,
        matched_via={"embedding": 0.55, "tag": 0.25, "structural": 0.15, "temporal": 0.05},
        evidence_canonical_zettel_id=EVIDENCE,
        shared_tag_label="ai",
        weight=3.0,
    )

    assert edge_id == 8
    op, schema, table, payload, kwargs = _writes(client, "upsert")[0]
    assert (schema, table) == ("kg", "kg_edges")
    assert payload["workspace_id"] == str(WS_A)
    assert payload["connection_strength"] == 0.62
    assert payload["workspace_strength"] == 0.71
    assert payload["global_strength"] == 0.48
    assert payload["matched_via"] == {
        "embedding": 0.55,
        "tag": 0.25,
        "structural": 0.15,
        "temporal": 0.05,
    }
    assert payload["evidence_canonical_zettel_id"] == str(EVIDENCE)
    assert payload["shared_tag_label"] == "ai"
    # ON CONFLICT must target the per-workspace natural key.
    assert kwargs["on_conflict"] == (
        "workspace_id,src_node_id,dst_node_id,relation_type"
    )


def test_upsert_edge_defaults_matched_via_and_nullable_strengths() -> None:
    client = _Client()
    repo = KGRepository(client)

    repo.upsert_edge(
        workspace_id=WS_A,
        src_node_id=1,
        dst_node_id=2,
        relation_type="shared_tag",
    )

    payload = _writes(client, "upsert")[0][3]
    assert payload["matched_via"] == {}  # NOT NULL DEFAULT '{}' parity
    assert payload["workspace_strength"] is None
    assert payload["global_strength"] is None
    assert payload["connection_strength"] is None
    assert payload["evidence_canonical_zettel_id"] is None


def test_upsert_edge_rejects_none_workspace_id() -> None:
    repo = KGRepository(_Client())
    with pytest.raises(ValueError):
        repo.upsert_edge(
            workspace_id=None,  # type: ignore[arg-type]
            src_node_id=1,
            dst_node_id=2,
            relation_type="shared_tag",
        )


def test_upsert_node_idempotent_on_workspace_slug() -> None:
    client = _Client()
    repo = KGRepository(client)
    node_id = repo.upsert_node(
        workspace_id=WS_A,
        node_type="tag",
        canonical_name="AI",
        slug="ai",
    )
    assert node_id == 8
    op, schema, table, payload, kwargs = _writes(client, "upsert")[0]
    assert (schema, table) == ("kg", "kg_nodes")
    assert kwargs["on_conflict"] == "workspace_key,slug"
    assert payload["workspace_id"] == str(WS_A)


# ---------------------------------------------------------------------------
# Idempotency: re-upsert same key -> UPSERT, never duplicate INSERT
# ---------------------------------------------------------------------------

def test_reupsert_same_edge_key_uses_upsert_not_insert() -> None:
    client = _Client()
    repo = KGRepository(client)

    for strength in (0.40, 0.81):  # scorer pass re-runs over the same edge
        repo.upsert_edge(
            workspace_id=WS_A,
            src_node_id=1,
            dst_node_id=2,
            relation_type="shared_tag",
            workspace_strength=strength,
        )

    assert len(_writes(client, "upsert")) == 2
    assert _writes(client, "insert") == []  # never a duplicate INSERT path
    # Same conflict target every time -> DB collapses to one row, UPDATEd.
    targets = {c[4]["on_conflict"] for c in _writes(client, "upsert")}
    assert targets == {"workspace_id,src_node_id,dst_node_id,relation_type"}


# ---------------------------------------------------------------------------
# Workspace isolation (OWASP API1:2023 BOLA) — UUID-leak assertion
# ---------------------------------------------------------------------------

def test_upsert_edge_workspace_isolation_no_cross_tenant_leak() -> None:
    client = _Client()
    repo = KGRepository(client)

    repo.upsert_edge(
        workspace_id=WS_A,
        src_node_id=10,
        dst_node_id=20,
        relation_type="shared_tag",
        workspace_strength=0.9,
    )
    repo.upsert_edge(
        workspace_id=WS_B,
        src_node_id=10,
        dst_node_id=20,
        relation_type="shared_tag",
        workspace_strength=0.1,
    )

    a_payload = _writes(client, "upsert")[0][3]
    b_payload = _writes(client, "upsert")[1][3]

    # A's write must carry ONLY A's workspace id (no B UUID anywhere).
    assert a_payload["workspace_id"] == str(WS_A)
    assert str(WS_B) not in a_payload.values()
    # B's write must carry ONLY B's workspace id (no A UUID anywhere).
    assert b_payload["workspace_id"] == str(WS_B)
    assert str(WS_A) not in b_payload.values()
    # Conflict target is workspace-prefixed -> same (src,dst,rel) in two
    # workspaces are distinct rows; neither upsert can update the other's.
    for _, _, _, _, kwargs in _writes(client, "upsert"):
        assert kwargs["on_conflict"].startswith("workspace_id,")


def test_upsert_node_workspace_isolation_no_cross_tenant_leak() -> None:
    client = _Client()
    repo = KGRepository(client)

    repo.upsert_node(workspace_id=WS_A, node_type="tag", canonical_name="AI", slug="ai")
    repo.upsert_node(workspace_id=WS_B, node_type="tag", canonical_name="AI", slug="ai")

    a_payload = _writes(client, "upsert")[0][3]
    b_payload = _writes(client, "upsert")[1][3]
    assert a_payload["workspace_id"] == str(WS_A)
    assert str(WS_B) not in a_payload.values()
    assert b_payload["workspace_id"] == str(WS_B)
    assert str(WS_A) not in b_payload.values()


# ---------------------------------------------------------------------------
# Migration 46 structural invariants
# ---------------------------------------------------------------------------

def test_migration_46_is_idempotent_and_non_destructive() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    # Forward-only column adds.
    assert "ADD COLUMN IF NOT EXISTS workspace_strength NUMERIC(4, 3)" in sql
    assert "ADD COLUMN IF NOT EXISTS global_strength    NUMERIC(4, 3)" in sql
    assert "ADD COLUMN IF NOT EXISTS matched_via" in sql
    assert "jsonb NOT NULL DEFAULT '{}'::jsonb" in sql
    # No destructive ops.
    for bad in ("DROP TABLE", "DROP COLUMN", "DROP CONSTRAINT", "TRUNCATE", "DELETE FROM"):
        assert bad not in sql.upper()


def test_migration_46_range_checks_and_natural_key() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    # 42-style pg_constraint existence probe (ADD CONSTRAINT has no IF NOT EXISTS).
    assert "kg_edges_workspace_strength_range" in sql
    assert "kg_edges_global_strength_range" in sql
    assert sql.count("FROM pg_constraint") >= 3  # 2 ranges + natural key
    assert "workspace_strength >= 0 AND workspace_strength <= 1" in sql
    assert "global_strength >= 0 AND global_strength <= 1" in sql
    # Natural key for ON CONFLICT idempotency must match the repo's target.
    assert "kg_edges_natural_key" in sql
    assert (
        "UNIQUE (workspace_id, src_node_id, dst_node_id, relation_type)" in sql
    )


def test_migration_46_index_and_render_vs_analytics_comments() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "idx_kg_edges_workspace_two_level_strength" in sql
    assert "workspace_key, workspace_strength DESC NULLS LAST" in sql
    # Comments must distinguish render-driving vs analytics-only.
    assert "DRIVES RENDERING" in sql
    assert "CROSS-USER ANALYTICS ONLY" in sql
    assert "NOTIFY pgrst, 'reload schema';" in sql
