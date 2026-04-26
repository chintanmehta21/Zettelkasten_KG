"""Unit tests for ops/scripts/backfill_metadata.py.

Mocks the Supabase client + MetadataEnricher. No network, no LLM calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.scripts import backfill_metadata as bm  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Supabase client
# ---------------------------------------------------------------------------
class _FakeQuery:
    def __init__(self, table: "_FakeTable", op: str, payload=None):
        self._table = table
        self._op = op
        self._payload = payload
        self._filters: list[tuple] = []
        self._range: tuple[int, int] | None = None
        self._eq_filter: tuple[str, object] | None = None  # for update().eq()

    def select(self, *_a, **_k):
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, val))
        return self

    def eq(self, col, val):
        if self._op == "update":
            self._eq_filter = (col, val)
        else:
            self._filters.append(("eq", col, val))
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, lo, hi):
        self._range = (lo, hi)
        return self

    def execute(self):
        if self._op == "select":
            data = list(self._table.select_rows)
            for kind, col, val in self._filters:
                if kind == "is" and val is None:
                    data = [r for r in data if r.get(col) is None]
                elif kind == "eq":
                    data = [r for r in data if r.get(col) == val]
            if self._range is not None:
                lo, hi = self._range
                data = data[lo : hi + 1]
            return SimpleNamespace(data=data)
        if self._op == "update":
            assert self._eq_filter is not None, "update() requires .eq()"
            col, val = self._eq_filter
            updated = 0
            for row in self._table.select_rows:
                if row.get(col) == val:
                    row.update(self._payload)
                    updated += 1
            self._table.update_calls.append(
                {"filter": (col, val), "payload": dict(self._payload)}
            )
            if self._table.update_raises:
                exc = self._table.update_raises
                self._table.update_raises = None  # only raise once
                raise exc
            return SimpleNamespace(data=[{"updated": updated}])
        return SimpleNamespace(data=[])


class _FakeTable:
    def __init__(self, name: str, select_rows=None):
        self.name = name
        self.select_rows = select_rows or []
        self.update_calls: list[dict] = []
        self.update_raises: Exception | None = None

    def select(self, *_a, **_k):
        return _FakeQuery(self, "select")

    def update(self, payload):
        return _FakeQuery(self, "update", payload=payload)


class _FakeSupabase:
    def __init__(self, tables: dict[str, _FakeTable]):
        self.tables = tables

    def table(self, name):
        if name not in self.tables:
            self.tables[name] = _FakeTable(name)
        return self.tables[name]


# ---------------------------------------------------------------------------
# Fake enricher: deterministic, captures calls, no LLM.
# ---------------------------------------------------------------------------
class _FakeEnricher:
    def __init__(self, *, raise_on_batch: bool = False):
        self.calls: list[list[dict]] = []
        self._raise = raise_on_batch

    async def enrich_chunks(self, chunks):
        self.calls.append(list(chunks))
        if self._raise:
            raise RuntimeError("boom-enrich")
        for c in chunks:
            md = c.get("metadata") or {}
            md["domains"] = ["example.com"]
            c["metadata"] = md
        return chunks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")


def _chunk(idx: int, enriched: bool = False, user="u1") -> dict:
    return {
        "id": f"chunk-{idx}",
        "content": f"body {idx} mentioning example.com",
        "metadata": {},
        "metadata_enriched_at": "2026-04-25T00:00:00+00:00" if enriched else None,
        "user_id": user,
    }


def _build_fake(rows: list[dict]) -> _FakeSupabase:
    return _FakeSupabase(
        tables={"kg_node_chunks": _FakeTable("kg_node_chunks", select_rows=rows)}
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_dry_run_counts_without_writing(fake_env, caplog):
    """--dry-run logs the pending count and writes nothing."""
    rows = [_chunk(i) for i in range(5)]
    fake = _build_fake(rows)
    enricher = _FakeEnricher()

    with patch.object(bm, "create_client", return_value=fake), patch.object(
        bm, "_build_enricher", return_value=enricher
    ):
        with caplog.at_level("INFO"):
            rc = bm.main(["--dry-run", "--batch-size", "10"])

    assert rc == 0
    # No writes happened
    assert fake.tables["kg_node_chunks"].update_calls == []
    # Enricher was NOT invoked in dry-run
    assert enricher.calls == []
    # Log mentions count
    joined = " ".join(r.message for r in caplog.records)
    assert "would enrich 5 chunks" in joined


def test_live_run_updates_metadata_and_sentinel(fake_env):
    rows = [_chunk(i) for i in range(3)]
    fake = _build_fake(rows)
    enricher = _FakeEnricher()

    with patch.object(bm, "create_client", return_value=fake), patch.object(
        bm, "_build_enricher", return_value=enricher
    ), patch.object(bm, "_build_key_pool", return_value=None):
        rc = bm.main(["--batch-size", "100"])

    assert rc == 0
    calls = fake.tables["kg_node_chunks"].update_calls
    # Three chunks = three update calls, each scoped to one id
    assert len(calls) == 3
    for call in calls:
        col, _val = call["filter"]
        assert col == "id"
        payload = call["payload"]
        assert payload["metadata"] == {"domains": ["example.com"]}
        # Sentinel set
        assert payload["metadata_enriched_at"] is not None
        assert "T" in payload["metadata_enriched_at"]  # ISO-8601
    # Enricher saw exactly one batch of 3
    assert len(enricher.calls) == 1
    assert len(enricher.calls[0]) == 3


def test_idempotent_skips_already_enriched(fake_env):
    """The pending query filters on metadata_enriched_at IS NULL; a
    re-invocation after a successful pass finds zero rows and does nothing.
    """
    # Mix of enriched + pending. Only pending rows should be picked.
    rows = [
        _chunk(0, enriched=True),
        _chunk(1, enriched=False),
        _chunk(2, enriched=True),
        _chunk(3, enriched=False),
    ]
    fake = _build_fake(rows)
    enricher = _FakeEnricher()

    with patch.object(bm, "create_client", return_value=fake), patch.object(
        bm, "_build_enricher", return_value=enricher
    ), patch.object(bm, "_build_key_pool", return_value=None):
        rc = bm.main(["--batch-size", "100"])
    assert rc == 0
    # Only the two un-enriched rows were sent to the enricher.
    assert len(enricher.calls) == 1
    seen_ids = {c["id"] for c in enricher.calls[0]}
    assert seen_ids == {"chunk-1", "chunk-3"}

    # Second invocation: every row is now enriched; backfill is a no-op.
    enricher2 = _FakeEnricher()
    with patch.object(bm, "create_client", return_value=fake), patch.object(
        bm, "_build_enricher", return_value=enricher2
    ), patch.object(bm, "_build_key_pool", return_value=None):
        rc2 = bm.main(["--batch-size", "100"])
    assert rc2 == 0
    assert enricher2.calls == []


def test_batch_size_paged(fake_env):
    """20 pending rows + --batch-size=5 => 4 batches."""
    rows = [_chunk(i) for i in range(20)]
    fake = _build_fake(rows)
    enricher = _FakeEnricher()

    with patch.object(bm, "create_client", return_value=fake), patch.object(
        bm, "_build_enricher", return_value=enricher
    ), patch.object(bm, "_build_key_pool", return_value=None):
        rc = bm.main(["--batch-size", "5"])
    assert rc == 0
    assert len(enricher.calls) == 4
    assert all(len(b) == 5 for b in enricher.calls)
    # All 20 rows updated
    assert len(fake.tables["kg_node_chunks"].update_calls) == 20


def test_limit_caps_total(fake_env):
    rows = [_chunk(i) for i in range(50)]
    fake = _build_fake(rows)
    enricher = _FakeEnricher()
    with patch.object(bm, "create_client", return_value=fake), patch.object(
        bm, "_build_enricher", return_value=enricher
    ), patch.object(bm, "_build_key_pool", return_value=None):
        rc = bm.main(["--batch-size", "10", "--limit", "12"])
    assert rc == 0
    # First batch: 10. Second batch capped to 2. Total = 12.
    total_processed = sum(len(b) for b in enricher.calls)
    assert total_processed == 12


def test_user_id_scopes_query(fake_env):
    rows = [_chunk(0, user="u1"), _chunk(1, user="u2"), _chunk(2, user="u1")]
    fake = _build_fake(rows)
    enricher = _FakeEnricher()
    with patch.object(bm, "create_client", return_value=fake), patch.object(
        bm, "_build_enricher", return_value=enricher
    ), patch.object(bm, "_build_key_pool", return_value=None):
        rc = bm.main(["--user-id", "u1"])
    assert rc == 0
    # Only u1 rows reach the enricher.
    assert len(enricher.calls) == 1
    seen_users = {c["user_id"] for c in enricher.calls[0]}
    assert seen_users == {"u1"}


def test_write_back_failure_skips_chunk_and_continues(fake_env):
    """A single failing UPDATE doesn't halt the batch."""
    rows = [_chunk(i) for i in range(3)]
    fake = _build_fake(rows)
    fake.tables["kg_node_chunks"].update_raises = RuntimeError("write-fail-once")
    enricher = _FakeEnricher()

    with patch.object(bm, "create_client", return_value=fake), patch.object(
        bm, "_build_enricher", return_value=enricher
    ), patch.object(bm, "_build_key_pool", return_value=None):
        rc = bm.main(["--batch-size", "100"])
    assert rc == 0
    # All three updates were attempted even though the first raised.
    assert len(fake.tables["kg_node_chunks"].update_calls) == 3


def test_enricher_exception_skips_batch(fake_env):
    """A top-level enricher failure logs + skips the batch, returns 0."""
    rows = [_chunk(i) for i in range(3)]
    fake = _build_fake(rows)
    enricher = _FakeEnricher(raise_on_batch=True)
    with patch.object(bm, "create_client", return_value=fake), patch.object(
        bm, "_build_enricher", return_value=enricher
    ), patch.object(bm, "_build_key_pool", return_value=None):
        rc = bm.main(["--batch-size", "100", "--limit", "3"])
    # Enricher raised; no writes; loop exited via --limit cap (next batch
    # would re-fetch the same un-enriched rows otherwise).
    assert rc == 0
    assert fake.tables["kg_node_chunks"].update_calls == []


def test_missing_supabase_creds_returns_2(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    rc = bm.main(["--dry-run"])
    assert rc == 2
