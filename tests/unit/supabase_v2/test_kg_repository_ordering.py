"""B1: list_workspace_edges must emit a deterministic ORDER BY (workspace_strength → connection_strength → id) and SELECT created_at (B7-a)."""
from unittest.mock import MagicMock

from website.core.supabase_v2.repositories.kg_repository import KGRepository


def _build_fake_client():
    fake = MagicMock()
    # Build a chain that supports .schema().table().select().eq().order().order().order().limit().execute()
    select = fake.schema.return_value.table.return_value.select
    chain = select.return_value.eq.return_value
    chain.order.return_value = chain
    chain.limit.return_value.execute.return_value.data = []
    return fake, select, chain


def test_list_workspace_edges_uses_strength_then_id_order():
    fake, _select, chain = _build_fake_client()
    repo = KGRepository(fake)
    repo.list_workspace_edges("00000000-0000-0000-0000-000000000001")
    calls = chain.order.call_args_list
    order_keys = [c.args[0] for c in calls]
    assert "workspace_strength" in order_keys
    assert "connection_strength" in order_keys
    assert "id" in order_keys


def test_list_workspace_edges_selects_created_at():
    fake, select, _chain = _build_fake_client()
    repo = KGRepository(fake)
    try:
        repo.list_workspace_edges("00000000-0000-0000-0000-000000000001")
    except Exception:
        pass
    select_arg = select.call_args.args[0]
    assert "created_at" in select_arg, "B7-a: created_at must be in SELECT list"
