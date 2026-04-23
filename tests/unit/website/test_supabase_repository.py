from uuid import UUID

from website.core.supabase_kg.models import KGNodeCreate
from website.core.supabase_kg.repository import KGRepository


class _Execute:
    def __init__(self, table, payload):
        self._table = table
        self._payload = payload

    def execute(self):
        self._table.payloads.append(self._payload)
        if self._table.fail_missing_engine_version:
            self._table.fail_missing_engine_version = False
            raise RuntimeError(
                "Could not find the 'engine_version' column of 'kg_nodes' in the schema cache"
            )
        return type("Resp", (), {"data": [self._payload]})()


class _Table:
    def __init__(self):
        self.payloads = []
        self.fail_missing_engine_version = True

    def insert(self, payload):
        return _Execute(self, dict(payload))


class _Client:
    def __init__(self):
        self.nodes = _Table()

    def table(self, name):
        assert name == "kg_nodes"
        return self.nodes


def test_add_node_retries_without_missing_optional_v2_column():
    repo = KGRepository.__new__(KGRepository)
    repo._client = _Client()
    user_id = UUID("a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e")

    created = repo.add_node(
        user_id,
        KGNodeCreate(
            id="nl-test",
            name="Newsletter Test",
            source_type="newsletter",
            summary="Summary",
            tags=[],
            url="https://example.com/p/test",
            engine_version="2.0.0",
            summary_v2={"mini_title": "Newsletter Test"},
        ),
    )

    first, second = repo._client.nodes.payloads
    assert "engine_version" in first
    assert "engine_version" not in second
    assert second["summary_v2"] == {"mini_title": "Newsletter Test"}
    assert created.id == "nl-test"
