"""Phase B — KG-population async hook unit coverage (no live Supabase).

A hand-rolled fake PostgREST client models the chained
``.schema().table().select().eq()...execute()`` + ``.rpc().execute()``
surface so the hook runs fully offline. Embedding generation is patched.

Covered (per task spec):
- fire-and-forget contract: an exception inside the hook never raises out;
- pipelines idempotency: a 'succeeded' run -> skip, no duplicate edges;
- bounded-K: never scores more than K candidates;
- D-KG-1 wired: edge written only when >= EDGE_CREATION_THRESHOLD,
  matched_via populated with per-signal sub-scores;
- two-level columns: workspace_strength set, global_strength NULL;
- workspace isolation: hook for workspace A never reads/writes B
  (UUID-leak assertion on every write payload);
- persist.py wiring fires the task without awaiting it.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from website.features.kg_features import scoring
from website.features.rag_pipeline.ingest import kg_population

_WS_A = UUID("00000000-0000-0000-0000-00000000000A")
_WS_B = UUID("00000000-0000-0000-0000-00000000000B")
_PROFILE = UUID("00000000-0000-0000-0000-000000000001")
_ZID = UUID("00000000-0000-0000-0000-0000000000C1")


# --------------------------------------------------------------------------
# Fake PostgREST client
# --------------------------------------------------------------------------


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
        self._filters = {}

    # builder no-ops that return self
    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, **_k):
        self._op = "upsert"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._filters[col] = list(vals)
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        self._c.calls.append(
            (self._schema, self._table, self._op, self._payload, dict(self._filters))
        )
        if self._op in ("insert", "update", "upsert"):
            self._c.writes.append(
                (self._schema, self._table, self._op, self._payload)
            )
        return self._c._respond(self)


class _SchemaProxy:
    def __init__(self, client, schema):
        self._c = client
        self._schema = schema

    def table(self, name):
        return _Query(self._c, self._schema, name)

    def rpc(self, name, params):
        self._c.rpc_calls.append((self._schema, name, params))
        return _RpcQuery(self._c, name)


class _RpcQuery:
    def __init__(self, client, name):
        self._c = client
        self._name = name

    def execute(self):
        return _Resp(self._c.rpc_data.get(self._name, []))


class FakeClient:
    """Configurable fake. ``responses`` maps (schema,table,op) -> data."""

    def __init__(self):
        self.calls = []
        self.writes = []
        self.rpc_calls = []
        self.rpc_data = {}
        self._succeeded_run = False
        self._candidate_meta = []  # rows for kg.kg_nodes metadata select
        self._next_node_id = 9001
        self.fail_on = None  # (schema, table, op) to raise on

    def schema(self, name):
        return _SchemaProxy(self, name)

    def _respond(self, q: _Query):
        key = (q._schema, q._table, q._op)
        if self.fail_on and key == self.fail_on:
            raise RuntimeError("injected failure")

        if q._schema == "pipelines" and q._table == "pipeline_runs":
            if q._op == "select":  # has_succeeded_run
                return _Resp([{"id": "run-x"}] if self._succeeded_run else [])
            if q._op == "insert":  # start_run
                return _Resp([{"id": "11111111-1111-1111-1111-111111111111"}])
            if q._op == "update":  # finish_run
                return _Resp([{"id": "run-x"}])

        if q._schema == "kg" and q._table == "kg_nodes":
            if q._op == "upsert":  # upsert_node
                nid = self._next_node_id
                self._next_node_id += 1
                return _Resp([{"id": nid}])
            if q._op == "select":  # candidate metadata batch
                return _Resp(list(self._candidate_meta))

        if q._schema == "kg" and q._table == "kg_edges":
            if q._op == "upsert":  # upsert_edge
                return _Resp([{"id": 7777}])

        return _Resp([])


@pytest.fixture(autouse=True)
def _patch_embeddings(monkeypatch):
    # Deterministic non-empty embedding so the similarity path runs.
    monkeypatch.setattr(
        "website.features.kg_features.embeddings.generate_embedding",
        lambda *_a, **_k: [0.1] * 768,
    )


async def _run(client, **over):
    kwargs = dict(
        workspace_id=_WS_A,
        profile_id=_PROFILE,
        canonical_zettel_id=_ZID,
        title="Deep Learning",
        summary="A talk about transformers and attention.",
        tags=["ml", "ai"],
        url="https://youtube.com/watch?v=1",
        source_type="youtube",
        supabase_client=client,
        metadata={"channel_name": "Lex Fridman"},
    )
    kwargs.update(over)
    return await kg_population.populate_kg_for_zettel(**kwargs)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_succeeded_run_skips(monkeypatch):
    c = FakeClient()
    c._succeeded_run = True
    m = await _run(c)
    assert m["skipped"] is True
    # no node/edge writes at all
    assert not [w for w in c.writes if w[1] in ("kg_nodes", "kg_edges")]


@pytest.mark.asyncio
async def test_fire_and_forget_swallows_internal_error():
    c = FakeClient()
    c.fail_on = ("kg", "kg_nodes", "upsert")  # blow up mid-pipeline
    m = await _run(c)  # must NOT raise
    assert "error" in m
    # run was marked failed (idempotency + observability preserved)
    assert any(
        w[0:3] == ("pipelines", "pipeline_runs", "update") for w in c.writes
    )


@pytest.mark.asyncio
async def test_bounded_k_never_scores_more_than_k(monkeypatch):
    monkeypatch.setenv("KG_POPULATION_TOP_K", "5")
    c = FakeClient()
    # RPC returns far more than K; hook must cap at K.
    c.rpc_data["match_kg_nodes"] = [
        {"node_id": i, "score": 0.99} for i in range(100)
    ]
    c._candidate_meta = [
        {"id": i, "metadata": {"embedding": [0.1] * 768, "tags": ["ml"],
                               "created_at": "2026-05-17T00:00:00+00:00"}}
        for i in range(100)
    ]
    m = await _run(c)
    assert m["scored"] <= 5
    assert m["candidates"] <= 5


@pytest.mark.asyncio
async def test_dkg1_threshold_gates_edge_and_matched_via():
    c = FakeClient()
    # One strong candidate (identical embedding+tags -> high score),
    # one weak (orthogonal-ish, no tags -> below threshold).
    c.rpc_data["match_kg_nodes"] = [
        {"node_id": 10, "score": 0.99},
        {"node_id": 20, "score": 0.10},
    ]
    c._candidate_meta = [
        {"id": 10, "metadata": {"embedding": [0.1] * 768, "tags": ["ml", "ai"],
                                "created_at": "2026-05-17T00:00:00+00:00"}},
        {"id": 20, "metadata": {"embedding": [0.0] * 768, "tags": [],
                                "created_at": "2020-01-01T00:00:00+00:00"}},
    ]
    m = await _run(c)
    edge_writes = [w for w in c.writes if w[1] == "kg_edges"]
    assert m["scored"] == 2
    assert m["edges"] == len(edge_writes) >= 1
    payload = edge_writes[0][3]
    # D-KG-1 wired: strength >= creation threshold
    assert payload["connection_strength"] >= scoring.EDGE_CREATION_THRESHOLD
    # matched_via populated with the per-signal sub-scores
    mv = payload["matched_via"]
    assert set(mv) >= {"embedding", "tag", "structural", "temporal", "composite"}
    assert 0.0 <= mv["embedding"] <= 1.0


@pytest.mark.asyncio
async def test_two_level_columns_workspace_set_global_null():
    c = FakeClient()
    c.rpc_data["match_kg_nodes"] = [{"node_id": 10, "score": 0.99}]
    c._candidate_meta = [
        {"id": 10, "metadata": {"embedding": [0.1] * 768, "tags": ["ml", "ai"],
                                "created_at": "2026-05-17T00:00:00+00:00"}},
    ]
    await _run(c)
    edge = [w for w in c.writes if w[1] == "kg_edges"][0][3]
    assert edge["workspace_strength"] is not None
    assert edge["global_strength"] is None


@pytest.mark.asyncio
async def test_workspace_isolation_no_uuid_leak():
    c = FakeClient()
    c.rpc_data["match_kg_nodes"] = [{"node_id": 10, "score": 0.99}]
    c._candidate_meta = [
        {"id": 10, "metadata": {"embedding": [0.1] * 768, "tags": ["ml", "ai"],
                                "created_at": "2026-05-17T00:00:00+00:00"}},
    ]
    await _run(c, workspace_id=_WS_A)
    # Every kg write payload must carry ONLY workspace A; never B.
    for schema, table, _op, payload in c.writes:
        if schema == "kg" and isinstance(payload, dict):
            assert payload.get("workspace_id") == str(_WS_A)
            assert str(_WS_B) not in str(payload)
    # Candidate metadata select is fenced to workspace A.
    sel = [
        f for (s, t, op, _p, f) in c.calls
        if s == "kg" and t == "kg_nodes" and op == "select"
    ]
    assert sel and all(f.get("workspace_id") == str(_WS_A) for f in sel)
    # match RPC keyed off the owner profile (its workspace fence).
    rpc = [p for (s, n, p) in c.rpc_calls if n == "match_kg_nodes"]
    assert rpc and rpc[0]["p_user_id"] == str(_PROFILE)


@pytest.mark.asyncio
async def test_isolation_drops_candidate_not_in_workspace():
    c = FakeClient()
    c.rpc_data["match_kg_nodes"] = [
        {"node_id": 10, "score": 0.99},
        {"node_id": 999, "score": 0.99},  # not in this workspace's kg_nodes
    ]
    c._candidate_meta = [
        {"id": 10, "metadata": {"embedding": [0.1] * 768, "tags": ["ml", "ai"],
                                "created_at": "2026-05-17T00:00:00+00:00"}},
    ]  # 999 absent -> must be skipped, never edged
    await _run(c)
    edged_dsts = {
        w[3]["dst_node_id"] for w in c.writes if w[1] == "kg_edges"
    }
    assert 999 not in edged_dsts


@pytest.mark.asyncio
async def test_persist_wiring_fires_task_without_awaiting(monkeypatch):
    """persist._schedule_kg_population fires the task fire-and-forget."""
    from website.core import persist

    started = asyncio.Event()
    released = asyncio.Event()

    async def _fake_populate(**_k):
        started.set()
        await released.wait()
        return {}

    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.kg_population.populate_kg_for_zettel",
        _fake_populate,
    )
    monkeypatch.setattr(
        "website.core.supabase_v2.client.get_v2_client", lambda: object()
    )

    persist._schedule_kg_population(
        payload={"source_url": "https://e.com", "source_type": "web", "tags": []},
        workspace_id=_WS_A,
        profile_id=_PROFILE,
        canonical_zettel_id=_ZID,
        title="T",
        summary="S",
    )
    # Returned immediately (not awaited); task runs on the loop.
    await asyncio.wait_for(started.wait(), timeout=1.0)
    released.set()
    await asyncio.sleep(0)  # let the task finish cleanly


@pytest.mark.asyncio
async def test_persist_wiring_skips_when_no_profile():
    from website.core import persist

    # No profile -> skipped silently (no task, no raise).
    persist._schedule_kg_population(
        payload={"tags": []},
        workspace_id=_WS_A,
        profile_id=None,
        canonical_zettel_id=_ZID,
        title="T",
        summary="S",
    )
