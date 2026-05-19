"""D5 — stale higher-idx chunk prune on re-ingest.

``upsert_chunks`` upserts ON CONFLICT(canonical_zettel_id, chunk_idx) but
never prunes. Re-ingesting a zettel that now yields FEWER chunks left the
old higher-idx rows orphaned (stale retrieval candidates + dangling
workspace_chunk_membership). Fix: after the upsert, issue a second
PostgREST call ``DELETE WHERE canonical_zettel_id=? AND chunk_idx >= N``
(N = number of fresh chunks). Mirrors the delete-then-state pattern the
v2 re-chunk backfill proved.
"""
from __future__ import annotations

from uuid import UUID

from website.core.supabase_v2.models import CanonicalChunkCreate
from website.core.supabase_v2.repositories.content_repository import (
    ContentRepository,
)

_CANON = UUID("00000000-0000-0000-0000-000000000111")


class _Execute:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return type("Resp", (), {"data": self.data})()


class _DeleteQuery:
    def __init__(self, calls):
        self.calls = calls
        self._filters = {}

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def gte(self, col, val):
        self._filters[("gte", col)] = val
        self.calls.append(("delete_gte", dict(self._filters)))
        return self

    def execute(self):
        return type("Resp", (), {"data": []})()


class _Table:
    def __init__(self, calls, table):
        self.calls = calls
        self.table = table

    def upsert(self, payload, **kwargs):
        self.calls.append(("upsert", self.table, payload, kwargs))
        rows = payload if isinstance(payload, list) else [payload]
        return _Execute(
            [
                {"id": f"00000000-0000-0000-0000-0000000003{idx:02d}"}
                for idx, _ in enumerate(rows)
            ]
        )

    def delete(self):
        self.calls.append(("delete", self.table))
        return _DeleteQuery(self.calls)


class _Schema:
    def __init__(self, calls):
        self.calls = calls

    def table(self, table):
        return _Table(self.calls, table)


class _Client:
    def __init__(self):
        self.calls = []

    def schema(self, _schema):
        return _Schema(self.calls)


def _chunks(n: int):
    return [
        CanonicalChunkCreate(
            chunk_idx=i,
            content=f"chunk {i}",
            content_hash=b"h" + bytes([i]),
            chunk_type="atomic",
            token_count=3,
            embedding=[0.0] * 768,
            embedding_model_version="gemini-001-mrl-768",
        )
        for i in range(n)
    ]


def test_upsert_chunks_prunes_stale_higher_idx_rows():
    fake = _Client()
    repo = ContentRepository(fake)

    repo.upsert_chunks(_CANON, _chunks(3))

    delete_gte = [c for c in fake.calls if c[0] == "delete_gte"]
    assert delete_gte, "a stale-chunk prune DELETE must follow the upsert"
    flt = delete_gte[0][1]
    assert flt["canonical_zettel_id"] == str(_CANON)
    # chunk_idx >= 3 (number of fresh chunks) -> removes any old idx 3,4,...
    assert flt[("gte", "chunk_idx")] == 3


def test_prune_runs_after_upsert_not_before():
    fake = _Client()
    repo = ContentRepository(fake)
    repo.upsert_chunks(_CANON, _chunks(2))
    kinds = [c[0] for c in fake.calls]
    assert "upsert" in kinds and "delete_gte" in kinds
    assert kinds.index("upsert") < kinds.index("delete_gte")


def test_empty_chunk_list_is_a_noop_no_prune():
    """No chunks handed in -> the persist path is in the embed-or-skip
    'leave existing chunks for backfill' contract; we must NOT delete
    everything (that would destroy recoverable rows)."""
    fake = _Client()
    repo = ContentRepository(fake)
    assert repo.upsert_chunks(_CANON, []) == []
    assert not any(c[0] in ("upsert", "delete", "delete_gte") for c in fake.calls)


def test_prune_is_idempotent_on_repeat_same_count():
    fake = _Client()
    repo = ContentRepository(fake)
    repo.upsert_chunks(_CANON, _chunks(3))
    repo.upsert_chunks(_CANON, _chunks(3))
    deletes = [c for c in fake.calls if c[0] == "delete_gte"]
    assert all(d[1][("gte", "chunk_idx")] == 3 for d in deletes)
