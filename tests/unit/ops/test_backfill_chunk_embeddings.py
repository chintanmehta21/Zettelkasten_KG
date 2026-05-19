"""Unit coverage for ops/scripts/backfill_chunk_embeddings.py (no live DB).

A hand-rolled fake PostgREST client models the chained
``.schema().table().select().eq().gt().order().limit().execute()`` +
``.update().eq().execute()`` surface so the backfill runs fully offline.
``embed_chunk_texts`` is monkeypatched (no live Gemini).

Covered (per task spec):
- only NULL-embedding rows are embedded by default; --force re-embeds all;
- idempotent re-run: a second default run is a no-op once rows are embedded;
- workspace fencing: a workspace-B chunk is never read or written when
  scoped to profile A (UUID-leak assertion on the read filter);
- --dry-run performs ZERO writes AND ZERO embed calls;
- correct dim/format + model-version stamp on the written row;
- unbounded run (no --profile/--workspace) is refused (exit 2);
- whole-batch embed failure writes no NULL-embedding row (left for retry).
"""
from __future__ import annotations

from uuid import UUID

import pytest

from ops.scripts import backfill_chunk_embeddings as bf

_PROFILE = str(UUID("00000000-0000-0000-0000-0000000000a1"))
_WS_A = str(UUID("00000000-0000-0000-0000-00000000000a"))
_WS_B = str(UUID("00000000-0000-0000-0000-00000000000b"))


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, schema, table):
        self._c = client
        self._schema = schema
        self._table = table
        self._op = None
        self._payload = None
        self._eq = {}
        self._gt = {}
        self._limit = None

    def select(self, *_cols, **_k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def gt(self, col, val):
        self._gt[col] = val
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        if self._table == "workspaces":
            # core.workspaces select filtered by owner_profile_id.
            self._c.workspace_reads.append(dict(self._eq))
            prof = self._eq.get("owner_profile_id")
            rows = [
                {"id": ws}
                for ws, owner in self._c.workspaces.items()
                if owner == prof
            ]
            return _Resp(rows)

        if self._table == "workspace_chunk_membership" and self._op == "select":
            ws = self._eq.get("workspace_id")
            self._c.membership_reads.append(ws)
            after = self._gt.get("canonical_chunk_id")
            out = []
            for cid in sorted(self._c.membership.get(ws, [])):
                if after is not None and cid <= after:
                    continue
                cc = self._c.chunks[cid]
                out.append(
                    {
                        "canonical_chunk_id": cid,
                        "canonical_chunks": {
                            "id": cid,
                            "content": cc["content"],
                            "embedding": cc["embedding"],
                            "embedding_model_version": cc["mv"],
                        },
                    }
                )
                if self._limit and len(out) >= self._limit:
                    break
            return _Resp(out)

        if self._table == "canonical_chunks" and self._op == "update":
            cid = self._eq["id"]
            self._c.writes.append((cid, dict(self._payload)))
            self._c.chunks[cid]["embedding"] = self._payload["embedding"]
            self._c.chunks[cid]["mv"] = self._payload["embedding_model_version"]
            return _Resp([{"id": cid}])

        return _Resp([])


class _Schema:
    def __init__(self, client, schema):
        self._c = client
        self._schema = schema

    def table(self, name):
        return _Query(self._c, self._schema, name)


class _FakeClient:
    def __init__(self):
        # workspace_id -> owner_profile_id
        self.workspaces = {_WS_A: _PROFILE, _WS_B: "other-profile"}
        # workspace_id -> [canonical_chunk_id]
        self.membership = {_WS_A: ["c1", "c2"], _WS_B: ["cz"]}
        self.chunks = {
            "c1": {"content": "naruto one", "embedding": None,
                   "mv": "gemini-001-mrl-768"},
            "c2": {"content": "naruto two", "embedding": None,
                   "mv": "gemini-001-mrl-768"},
            "cz": {"content": "OTHER TENANT", "embedding": None,
                   "mv": "gemini-001-mrl-768"},
        }
        self.writes = []
        self.workspace_reads = []
        self.membership_reads = []

    def schema(self, name):
        return _Schema(self, name)


@pytest.fixture
def fake_embed(monkeypatch):
    calls = {"n": 0, "batches": []}

    async def _embed(texts):
        calls["n"] += 1
        calls["batches"].append(list(texts))
        return [[0.02] * 768 for _ in texts]

    # bf imports embed_chunk_texts lazily from website.core.persist inside
    # _process_workspace; patch at the source module.
    import website.core.persist as p

    monkeypatch.setattr(p, "embed_chunk_texts", _embed)
    return calls


def _args(**kw):
    base = dict(
        profile=_PROFILE,
        workspace=None,
        batch_size=64,
        limit=None,
        force=False,
        dry_run=False,
    )
    base.update(kw)
    import argparse

    return argparse.Namespace(**base)


def test_embeds_only_null_rows_and_writes_correct_format(fake_embed) -> None:
    client = _FakeClient()
    rc = bf._run(_args(), client)
    assert rc == 0
    # Only WS_A's two NULL chunks embedded; WS_B (other profile) untouched.
    written_ids = sorted(cid for cid, _ in client.writes)
    assert written_ids == ["c1", "c2"]
    for _cid, payload in client.writes:
        assert len(payload["embedding"]) == 768
        assert payload["embedding_model_version"] == "gemini-001-mrl-768"
    # workspace-B chunk never read (tenant fence) — no read for WS_B.
    assert _WS_B not in client.membership_reads
    assert "cz" not in {cid for cid, _ in client.writes}


def test_idempotent_second_run_is_noop(fake_embed) -> None:
    client = _FakeClient()
    assert bf._run(_args(), client) == 0
    n_after_first = len(client.writes)
    assert n_after_first == 2
    # Second default run: c1/c2 now have embeddings -> skipped.
    assert bf._run(_args(), client) == 0
    assert len(client.writes) == n_after_first  # zero new writes


def test_force_reembeds_already_embedded(fake_embed) -> None:
    client = _FakeClient()
    bf._run(_args(), client)
    bf._run(_args(force=True), client)
    # c1+c2 written once each on the first run, again under --force.
    assert len([1 for cid, _ in client.writes if cid == "c1"]) == 2


def test_dry_run_zero_writes_zero_embed_calls(fake_embed) -> None:
    client = _FakeClient()
    rc = bf._run(_args(dry_run=True), client)
    assert rc == 0
    assert client.writes == []
    assert fake_embed["n"] == 0  # no quota burned on dry-run


def test_unbounded_run_refused() -> None:
    client = _FakeClient()
    rc = bf._run(_args(profile=None, workspace=None), client)
    assert rc == 2
    assert client.writes == []


def test_workspace_scope_overrides_profile(fake_embed) -> None:
    client = _FakeClient()
    rc = bf._run(_args(profile=None, workspace=_WS_A), client)
    assert rc == 0
    assert sorted(cid for cid, _ in client.writes) == ["c1", "c2"]
    # No core.workspaces lookup when an explicit workspace is given.
    assert client.workspace_reads == []


def test_batch_embed_failure_writes_no_row(monkeypatch) -> None:
    client = _FakeClient()

    async def _fail(_texts):
        return None

    import website.core.persist as p

    monkeypatch.setattr(p, "embed_chunk_texts", _fail)
    rc = bf._run(_args(), client)
    # Whole-batch failure -> no NULL-embedding+model_version row written,
    # non-zero exit so the operator notices.
    assert client.writes == []
    assert rc == 1


def test_invalid_profile_uuid_refused() -> None:
    client = _FakeClient()
    assert bf._run(_args(profile="not-a-uuid"), client) == 2
