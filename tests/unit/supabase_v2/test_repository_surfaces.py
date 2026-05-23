from __future__ import annotations

from uuid import UUID

from website.core.supabase_v2.repositories.chat_repository import ChatRepository
from website.core.supabase_v2.repositories.kg_repository import KGRepository
from website.core.supabase_v2.repositories.rag_repository import RAGRepository


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
        self.calls.append(("insert", self.schema, self.table, payload))
        return _Execute([{"id": 7 if self.schema == "kg" else "00000000-0000-0000-0000-000000000007"}])

    def upsert(self, payload, **kwargs):
        self.calls.append(("upsert", self.schema, self.table, payload, kwargs))
        return _Execute([{"id": 8 if self.schema == "kg" else "00000000-0000-0000-0000-000000000008"}])

    def select(self, columns):
        self.calls.append(("select", self.schema, self.table, columns))
        return _SelectChain(self.calls, self.schema, self.table)


class _SelectChain:
    """Captures the .in_(...).limit(...).execute() suffix after .select(...)."""

    def __init__(self, calls, schema, table):
        self.calls = calls
        self.schema = schema
        self.table = table
        self._data: list[dict] = []

    def in_(self, col, vals):
        self.calls.append(("in_", self.schema, self.table, col, list(vals)))
        # Inject canned chunk_node_mentions rows so list_node_zettel_mapping
        # has data to fold into the {node_id: [zettel_id]} return value.
        if self.schema == "kg" and self.table == "chunk_node_mentions":
            self._data = [
                {
                    "kg_node_id": 101,
                    "canonical_chunk_id": "chunk-aaa",
                    "canonical_chunks": {
                        "canonical_zettel_id": "00000000-0000-0000-0000-000000000aaa"
                    },
                },
                {
                    "kg_node_id": 102,
                    "canonical_chunk_id": "chunk-bbb",
                    "canonical_chunks": {
                        "canonical_zettel_id": "00000000-0000-0000-0000-000000000bbb"
                    },
                },
            ]
        return self

    def limit(self, n):
        self.calls.append(("limit", self.schema, self.table, n))
        return self

    def execute(self):
        return _Execute(self._data).execute()


class _Schema:
    def __init__(self, calls, schema):
        self.calls = calls
        self.schema = schema

    def table(self, table):
        self.calls.append(("table", self.schema, table))
        return _Table(self.calls, self.schema, table)

    def rpc(self, name, params):
        self.calls.append(("rpc", self.schema, name, params))
        return _Execute([{"id": 1}, {"id": 2}])


class _Client:
    def __init__(self):
        self.calls = []

    def schema(self, schema):
        self.calls.append(("schema", schema))
        return _Schema(self.calls, schema)

    def table(self, name):  # pragma: no cover
        raise AssertionError(f"unscoped table call: {name}")


def test_kg_repository_uses_kg_schema() -> None:
    client = _Client()
    repo = KGRepository(client)
    node_id = repo.upsert_node(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        node_type="tag",
        canonical_name="AI",
        slug="ai",
    )
    assert node_id == 8
    assert ("table", "kg", "kg_nodes") in client.calls


def test_rag_repository_uses_rag_schema() -> None:
    client = _Client()
    repo = RAGRepository(client)
    kasten_row = repo.create_kasten(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        name="Research",
    )
    assert kasten_row["id"] == "00000000-0000-0000-0000-000000000007"
    assert ("table", "rag", "kastens") in client.calls


def test_chat_repository_uses_rag_schema() -> None:
    client = _Client()
    repo = ChatRepository(client)
    session_id = repo.create_session(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        profile_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    assert str(session_id) == "00000000-0000-0000-0000-000000000007"
    assert ("table", "rag", "chat_sessions") in client.calls


def test_list_node_zettel_mapping_uses_fk_hint_not_alias_separator() -> None:
    """Regression for PGRST200 on /api/graph (kg_repository.py).

    PostgREST embed disambiguation MUST use `!fk_column` — `:fk_column` is
    the *alias* separator, so `canonical_chunks:canonical_chunk_id(...)`
    makes PGRST search for a relationship literally named
    `canonical_chunk_id` and 500 with
    "Could not find a relationship between 'chunk_node_mentions' and
    'canonical_chunk_id' in the schema cache". This test captures the
    exact select string so a future "tidy-up" PR can't silently flip the
    `!` back to `:`.
    """
    client = _Client()
    repo = KGRepository(client)
    mapping = repo.list_node_zettel_mapping(
        UUID("00000000-0000-0000-0000-000000000001"),
        [101, 102, 999],
    )
    # Locate the select(...) call against kg.chunk_node_mentions.
    selects = [
        call for call in client.calls
        if call[0] == "select"
        and call[1] == "kg"
        and call[2] == "chunk_node_mentions"
    ]
    assert len(selects) == 1, f"expected exactly one select; got {selects}"
    columns = selects[0][3]
    assert "canonical_chunks!canonical_chunk_id(canonical_zettel_id)" in columns, (
        f"PostgREST embed must use the `!fk_column` hint; saw: {columns!r}"
    )
    assert "canonical_chunks:canonical_chunk_id" not in columns, (
        "`:` is the alias separator and triggers PGRST200; use `!` "
        f"instead. select string: {columns!r}"
    )
    # End-to-end shape: rows fold into {node_id: [zettel_uuid_str]}.
    assert mapping == {
        101: ["00000000-0000-0000-0000-000000000aaa"],
        102: ["00000000-0000-0000-0000-000000000bbb"],
    }

