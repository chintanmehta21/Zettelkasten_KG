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
        # 2026-05-23 — list_node_zettel_mapping now drives a TWO-STEP
        # single-schema query (PR #69 hardening: master's `!fk_column`
        # syntax still 500s with PGRST200 live, so we stopped relying on
        # PostgREST cross-schema FK embed entirely). Inject canned rows
        # for BOTH steps so the test's _Client can fold them into the
        # final {node_id: [zettel_id]} return.
        #   Step 1: kg.chunk_node_mentions → bare (kg_node_id, canonical_chunk_id).
        #   Step 2: content.canonical_chunks → (id, canonical_zettel_id).
        if self.schema == "kg" and self.table == "chunk_node_mentions":
            self._data = [
                {"kg_node_id": 101, "canonical_chunk_id": "chunk-aaa"},
                {"kg_node_id": 102, "canonical_chunk_id": "chunk-bbb"},
            ]
        elif self.schema == "content" and self.table == "canonical_chunks":
            self._data = [
                {"id": "chunk-aaa", "canonical_zettel_id": "00000000-0000-0000-0000-000000000aaa"},
                {"id": "chunk-bbb", "canonical_zettel_id": "00000000-0000-0000-0000-000000000bbb"},
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


def test_list_kastens_flattens_postgrest_count_embed() -> None:
    """Regression for the 2026-05-24 /home/kastens "0 zettels" bug.

    The legacy ``select('*')`` left ``member_count`` unset; the serializer
    defaulted it to 0 even when ``rag.kasten_zettels`` had rows. Fix is the
    same-schema PostgREST embed ``select=*,kasten_zettels(count)`` — this
    test pins both the select string AND the flattening (embed list →
    flat ``member_count`` int) so a future "tidy-up" PR can't drop either.
    """
    captured: dict = {}

    class _ChainK:
        def __init__(self):
            self._data: list[dict] = []

        def select(self, columns):
            captured["select_columns"] = columns
            return self

        def eq(self, col, val):
            captured.setdefault("eqs", []).append((col, val))
            return self

        def order(self, col, **kw):
            captured.setdefault("orders", []).append((col, kw))
            return self

        def limit(self, n):
            captured["limit"] = n
            return self

        def execute(self):
            # Canned response: 3 kastens — one with 10 members, one with
            # 0 members (empty embed list), one with the singleton-dict
            # shape PostgREST sometimes returns to exercise the defensive
            # branch.
            return type("Resp", (), {"data": [
                {"id": "k-1", "name": "Economics & Markets",
                 "kasten_zettels": [{"count": 10}]},
                {"id": "k-2", "name": "Empty Kasten",
                 "kasten_zettels": []},
                {"id": "k-3", "name": "Single-dict shape",
                 "kasten_zettels": {"count": 4}},
            ]})()

    class _SchemaK:
        def table(self, _name):
            captured["table"] = _name
            return _ChainK()

    class _ClientK:
        def schema(self, name):
            captured["schema"] = name
            return _SchemaK()

    repo = RAGRepository(_ClientK())
    rows = repo.list_kastens(UUID("00000000-0000-0000-0000-000000000001"))

    # Wire contract: PostgREST same-schema count-embed must be in the select.
    assert captured["schema"] == "rag"
    assert captured["table"] == "kastens"
    assert "kasten_zettels(count)" in captured["select_columns"], (
        "list_kastens MUST embed kasten_zettels(count) so the card widget "
        f"can render real member counts. saw: {captured['select_columns']!r}"
    )

    # Flattening contract: embed shape collapses to a flat int per row,
    # and the embed key is stripped so downstream readers see only the
    # legacy flat shape.
    assert rows[0]["member_count"] == 10
    assert "kasten_zettels" not in rows[0]
    assert rows[1]["member_count"] == 0   # empty embed list → 0
    assert "kasten_zettels" not in rows[1]
    assert rows[2]["member_count"] == 4   # dict-only fallback shape
    assert "kasten_zettels" not in rows[2]


def test_chat_repository_uses_rag_schema() -> None:
    client = _Client()
    repo = ChatRepository(client)
    session_id = repo.create_session(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        profile_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    assert str(session_id) == "00000000-0000-0000-0000-000000000007"
    assert ("table", "rag", "chat_sessions") in client.calls


def test_list_node_zettel_mapping_uses_two_step_no_fk_embed() -> None:
    """Regression for PGRST200 on /api/graph (kg_repository.py).

    Two prior attempts at one-shot PostgREST FK embed both failed live:
      * `canonical_chunks:canonical_chunk_id(...)` — `:` is the alias
        separator, PGRST searched for a relationship literally named
        ``canonical_chunk_id`` and 500'd.
      * `canonical_chunks!canonical_chunk_id(...)` — the canonical `!`
        disambiguator. Still 500'd live with the same PGRST200, because
        the cross-schema FK ``kg.chunk_node_mentions.canonical_chunk_id
        → content.canonical_chunks(id)`` does not appear in PostgREST's
        schema cache regardless of syntax (Supabase pooler / cache
        interplay; PostgREST issues #1438, #2123 family).

    Bulletproof contract (PR #69): TWO explicit single-schema selects +
    Python stitch. No FK embed. This test pins that contract so a
    future "tidy-up" PR cannot silently reintroduce either of the
    broken one-shot embed shapes.
    """
    client = _Client()
    repo = KGRepository(client)
    mapping = repo.list_node_zettel_mapping(
        UUID("00000000-0000-0000-0000-000000000001"),
        [101, 102, 999],
    )

    # Step 1: a single select on kg.chunk_node_mentions with NO embed.
    mentions_selects = [
        call for call in client.calls
        if call[0] == "select"
        and call[1] == "kg"
        and call[2] == "chunk_node_mentions"
    ]
    assert len(mentions_selects) == 1, (
        f"expected exactly one kg.chunk_node_mentions select; got {mentions_selects}"
    )
    columns_step1 = mentions_selects[0][3]
    assert "canonical_chunks" not in columns_step1, (
        "Step 1 must NOT embed canonical_chunks — both `:` and `!` embed "
        "variants 500 live with PGRST200. Use a separate Step-2 select "
        f"in `content` instead. saw: {columns_step1!r}"
    )

    # Step 2: a single select on content.canonical_chunks with NO embed.
    chunks_selects = [
        call for call in client.calls
        if call[0] == "select"
        and call[1] == "content"
        and call[2] == "canonical_chunks"
    ]
    assert len(chunks_selects) == 1, (
        f"expected exactly one content.canonical_chunks select; got {chunks_selects}"
    )
    columns_step2 = chunks_selects[0][3]
    assert "id" in columns_step2 and "canonical_zettel_id" in columns_step2, (
        f"Step 2 must select id + canonical_zettel_id; saw: {columns_step2!r}"
    )

    # End-to-end shape: stitched rows fold into {node_id: [zettel_uuid_str]}.
    assert mapping == {
        101: ["00000000-0000-0000-0000-000000000aaa"],
        102: ["00000000-0000-0000-0000-000000000bbb"],
    }

