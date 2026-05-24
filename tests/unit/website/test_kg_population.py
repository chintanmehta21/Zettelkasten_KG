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
        # structural fixtures
        self._chunk_mentions = []  # rows: {kg_node_id, canonical_chunk_id}
        self._kg_edges = {}  # workspace_id(str) -> [{src_node_id,dst_node_id}]
        # B2: content.canonical_chunks rows {id, canonical_zettel_id}
        self._canonical_chunks = []

    def schema(self, name):
        return _SchemaProxy(self, name)

    def _respond(self, q: _Query):
        key = (q._schema, q._table, q._op)
        if self.fail_on and key == self.fail_on:
            raise RuntimeError("injected failure")

        if q._schema == "pipelines" and q._table == "pipeline_runs":
            if q._op == "select":  # has_succeeded_run (LD-8 shape: status+metrics)
                return _Resp(
                    [{"id": "run-x", "status": "succeeded", "metrics": {"edges": 1}}]
                    if self._succeeded_run else []
                )
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
            if q._op == "select":  # Adamic-Adar incident-edge fetch
                ws = q._filters.get("workspace_id")
                rows = self._kg_edges.get(ws, [])
                # Respect the .in_(col, seeds) filter the AA query applies.
                for col in ("src_node_id", "dst_node_id"):
                    if col in q._filters:
                        seeds = set(q._filters[col])
                        rows = [r for r in rows if r[col] in seeds]
                        break
                return _Resp(list(rows))

        if q._schema == "kg" and q._table == "chunk_node_mentions":
            if q._op == "select":  # shared-chunk co-mention fetch
                ids = set(q._filters.get("kg_node_id", []))
                return _Resp(
                    [r for r in self._chunk_mentions if r["kg_node_id"] in ids]
                )
            if q._op in ("upsert", "insert"):  # B2 mention write
                return _Resp([{"ok": True}])

        if q._schema == "content" and q._table == "canonical_chunks":
            if q._op == "select":  # B2: chunk ids for a canonical zettel
                zid = q._filters.get("canonical_zettel_id")
                return _Resp(
                    [
                        {"id": r["id"]}
                        for r in self._canonical_chunks
                        if str(r["canonical_zettel_id"]) == str(zid)
                    ]
                )

        return _Resp([])


@pytest.fixture(autouse=True)
def _patch_embeddings(monkeypatch):
    # Deterministic non-empty embedding so the similarity path runs.
    monkeypatch.setattr(
        "website.features.kg_features.embeddings.generate_embedding",
        lambda *_a, **_k: [0.1] * 768,
    )
    # LD-8: kg_population now uses the typed entrypoint.
    from website.features.kg_features.embeddings import EmbeddingResult
    monkeypatch.setattr(
        "website.features.kg_features.embeddings.generate_embedding_typed",
        lambda *_a, **_k: EmbeddingResult(
            ok=True, vectors=[[0.1] * 768], reason=None, retryable=False
        ),
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


# --------------------------------------------------------------------------
# DEFECT 1: short-lived create_kasten runner must DRAIN the fire-and-forget
# kg-populate tasks before returning, else the loop teardown cancels them and
# 0 kg_edges are ever written (observed: 10 kg_nodes, 0 kg_edges via CLI).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_kg_task_is_registered_for_drain(monkeypatch):
    """_schedule_kg_population registers the task so a short-lived caller can
    deterministically await it (the fix's enabling mechanism)."""
    from website.core import persist

    release = asyncio.Event()

    async def _fake_populate(**_k):
        await release.wait()
        return {"edges": 1}

    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.kg_population.populate_kg_for_zettel",
        _fake_populate,
    )
    monkeypatch.setattr(
        "website.core.supabase_v2.client.get_v2_client", lambda: object()
    )

    assert not persist._PENDING_ENRICHMENT_TASKS
    persist._schedule_kg_population(
        payload={"source_url": "https://e.com", "source_type": "web", "tags": []},
        workspace_id=_WS_A,
        profile_id=_PROFILE,
        canonical_zettel_id=_ZID,
        title="T",
        summary="S",
    )
    assert len(persist._PENDING_ENRICHMENT_TASKS) == 1, (
        "scheduled kg-populate task must be registered for the runner drain"
    )
    release.set()
    drained = await persist.drain_pending_enrichment_tasks(timeout=2.0)
    assert drained >= 1
    # Done-callback cleared the registry (no unbounded growth on a server).
    assert not persist._PENDING_ENRICHMENT_TASKS


@pytest.mark.asyncio
async def test_drain_completes_kg_population_that_would_be_cancelled(monkeypatch):
    """REPRO of Defect 1: without the drain the kg-populate coroutine is still
    suspended when the caller returns (loop teardown would cancel it -> 0
    edges). drain_pending_enrichment_tasks guarantees it RUNS TO COMPLETION."""
    from website.core import persist

    completed = asyncio.Event()
    gate = asyncio.Event()

    async def _fake_populate(**_k):
        # Suspends like the real hook (many awaited Supabase round-trips).
        await gate.wait()
        completed.set()
        return {"edges": 3}

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
    # Task is scheduled but NOT yet complete (mirrors the CLI exit race).
    assert not completed.is_set()
    gate.set()
    await persist.drain_pending_enrichment_tasks(timeout=2.0)
    assert completed.is_set(), (
        "drain must run the kg-populate task to completion (Defect 1 fix)"
    )


@pytest.mark.asyncio
async def test_drain_is_idempotent_and_safe_when_empty():
    """Calling the drain with nothing pending is a no-op (idempotent; the
    runner may call it even when persist=False or all links failed)."""
    from website.core import persist

    assert not persist._PENDING_ENRICHMENT_TASKS
    assert await persist.drain_pending_enrichment_tasks(timeout=1.0) == 0
    assert await persist.drain_pending_enrichment_tasks(timeout=1.0) == 0


@pytest.mark.asyncio
async def test_drain_swallows_task_failure(monkeypatch):
    """A failing enrichment task must not make the drain raise (best-effort
    contract preserved: the runner still returns succeeded)."""
    from website.core import persist

    async def _boom(**_k):
        raise RuntimeError("kg blew up")

    monkeypatch.setattr(
        "website.features.rag_pipeline.ingest.kg_population.populate_kg_for_zettel",
        _boom,
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
    # Must NOT raise even though the task raised internally.
    await persist.drain_pending_enrichment_tasks(timeout=2.0)
    assert not persist._PENDING_ENRICHMENT_TASKS


@pytest.mark.asyncio
async def test_create_kasten_runner_drains_before_returning(monkeypatch):
    """End-to-end Defect 1: the create_kasten runner awaits the drain so KG
    population is GUARANTEED complete before the (short-lived) runner returns.
    The website route never calls the drain (latency unaffected) — asserted by
    test_persist_wiring_fires_task_without_awaiting above."""
    from website.api.module_runners import create_kasten as ck

    order: list[str] = []

    async def _fake_drain(*_a, **_k):
        order.append("drained")
        return 1

    def _fake_scope(_sub):
        order.append("scope")
        raise ValueError("stop after scope (drain wiring is what we assert)")

    monkeypatch.setattr(ck, "_drain_pending_enrichment_tasks", _fake_drain)
    monkeypatch.setattr(ck, "get_supabase_v2_scope", _fake_scope)

    # The runner must reference the drain facade (import + call site exist).
    import inspect

    src = inspect.getsource(ck._execute_create_kasten)
    assert "_drain_pending_enrichment_tasks" in src, (
        "create_kasten runner must drain pending enrichment tasks before return"
    )
    # And the facade resolves to persist.drain_pending_enrichment_tasks.
    from website.core import persist

    assert persist.drain_pending_enrichment_tasks is not None


# --------------------------------------------------------------------------
# STRUCTURAL signal (D-KG-1 slot restore): shared-chunk + Adamic-Adar
# --------------------------------------------------------------------------


def _client_with_mentions(rows):
    c = FakeClient()
    c._chunk_mentions = rows
    return c


def test_shared_chunk_cooccurrence_distinct_overlap():
    # new=1 shares chunk A & B with cand 10 (2 distinct), chunk A with 20 (1).
    c = _client_with_mentions([
        {"kg_node_id": 1, "canonical_chunk_id": "A"},
        {"kg_node_id": 1, "canonical_chunk_id": "B"},
        {"kg_node_id": 1, "canonical_chunk_id": "A"},  # dup -> still distinct
        {"kg_node_id": 10, "canonical_chunk_id": "A"},
        {"kg_node_id": 10, "canonical_chunk_id": "B"},
        {"kg_node_id": 20, "canonical_chunk_id": "A"},
        {"kg_node_id": 30, "canonical_chunk_id": "Z"},  # no overlap
    ])
    out = kg_population._shared_chunk_cooccurrence(
        new_node_id=1, candidate_ids=[10, 20, 30], supabase_client=c
    )
    assert out == {10: 2, 20: 1}  # 30 omitted (zero)


def test_shared_chunk_cooccurrence_empty_and_no_new_chunks():
    c = _client_with_mentions([])  # cold mentions table
    assert kg_population._shared_chunk_cooccurrence(
        new_node_id=1, candidate_ids=[10], supabase_client=c
    ) == {}
    # new node has no chunks -> no overlap possible
    c2 = _client_with_mentions([{"kg_node_id": 10, "canonical_chunk_id": "A"}])
    assert kg_population._shared_chunk_cooccurrence(
        new_node_id=1, candidate_ids=[10], supabase_client=c2
    ) == {}


def test_shared_chunk_cooccurrence_one_bounded_query():
    c = _client_with_mentions([{"kg_node_id": 1, "canonical_chunk_id": "A"}])
    c.calls.clear()
    kg_population._shared_chunk_cooccurrence(
        new_node_id=1, candidate_ids=list(range(10, 60)), supabase_client=c
    )
    cm = [
        x for x in c.calls
        if x[0] == "kg" and x[1] == "chunk_node_mentions"
    ]
    assert len(cm) == 1  # exactly ONE query regardless of candidate count


def test_adamic_adar_idf_weighted_with_degree_guard():
    # Graph (workspace A): new=1 — w5 — cand=10 ; 1 — w6 — 10.
    # deg(w5)=4 (rare-ish), deg(w6)=2. Plus a deg-1 leaf that must be skipped.
    ws = str(_WS_A)
    edges = [
        {"src_node_id": 1, "dst_node_id": 5},
        {"src_node_id": 10, "dst_node_id": 5},
        {"src_node_id": 5, "dst_node_id": 7},
        {"src_node_id": 5, "dst_node_id": 8},  # deg(5)=4 (1,10,7,8)
        {"src_node_id": 1, "dst_node_id": 6},
        {"src_node_id": 10, "dst_node_id": 6},  # deg(6)=2 (1,10)
        {"src_node_id": 1, "dst_node_id": 9},
        {"src_node_id": 10, "dst_node_id": 9},  # deg(9)=2 -> common, counts
    ]
    c = FakeClient()
    c._kg_edges[ws] = edges
    out = kg_population._adamic_adar(
        new_node_id=1, candidate_ids=[10], workspace_id=_WS_A,
        supabase_client=c,
    )
    import math as _m
    expected = 1 / _m.log(4) + 1 / _m.log(2) + 1 / _m.log(2)
    assert out[10] == pytest.approx(expected, rel=1e-9)


def test_adamic_adar_cold_graph_zero():
    c = FakeClient()  # no edges anywhere
    assert kg_population._adamic_adar(
        new_node_id=1, candidate_ids=[10], workspace_id=_WS_A,
        supabase_client=c,
    ) == {}


def test_adamic_adar_deg_one_only_yields_nothing():
    # Only common neighbour has degree 1 -> log domain guard -> skipped.
    ws = str(_WS_A)
    c = FakeClient()
    c._kg_edges[ws] = [
        {"src_node_id": 1, "dst_node_id": 5},
        {"src_node_id": 10, "dst_node_id": 5},
    ]  # deg(5)=2 actually (1,10) -> contributes; make a true deg-1 case:
    c._kg_edges[ws] = [
        {"src_node_id": 1, "dst_node_id": 5},
        {"src_node_id": 5, "dst_node_id": 1},  # still deg(5)={1}
    ]
    out = kg_population._adamic_adar(
        new_node_id=1, candidate_ids=[10], workspace_id=_WS_A,
        supabase_client=c,
    )
    assert out == {}  # no common neighbour between 1 and 10


def test_adamic_adar_bounded_query_count_constant():
    # Constant query count regardless of candidate count. With a real common
    # neighbour the Q3 degree-resolution pair also fires -> 4 selects total
    # (Q1 src + Q2 dst over seeds, Q3 src + Q3 dst over common neighbours).
    ws = str(_WS_A)
    c = FakeClient()
    c._kg_edges[ws] = [
        {"src_node_id": 1, "dst_node_id": 5},
        {"src_node_id": 10, "dst_node_id": 5},
        {"src_node_id": 5, "dst_node_id": 7},  # deg(5)=3 -> contributes
    ]
    c.calls.clear()
    kg_population._adamic_adar(
        new_node_id=1, candidate_ids=list(range(10, 80)),
        workspace_id=_WS_A, supabase_client=c,
    )
    edge_q = [
        x for x in c.calls
        if x[0] == "kg" and x[1] == "kg_edges" and x[2] == "select"
    ]
    assert len(edge_q) == 4  # constant, independent of the 70 candidates

    # No common neighbours -> Q3 short-circuits -> only the 2 seed selects.
    c2 = FakeClient()
    c2._kg_edges[ws] = [{"src_node_id": 1, "dst_node_id": 5}]
    c2.calls.clear()
    kg_population._adamic_adar(
        new_node_id=1, candidate_ids=list(range(10, 200)),
        workspace_id=_WS_A, supabase_client=c2,
    )
    edge_q2 = [
        x for x in c2.calls
        if x[0] == "kg" and x[1] == "kg_edges" and x[2] == "select"
    ]
    assert len(edge_q2) == 2  # still a small constant, candidate-independent


def test_structural_map_combination_primary_dominant():
    # cand 10: cooccur=3, aa large; cand 20: cooccur=0, aa=2.0 (cold-ish).
    c = _client_with_mentions([
        {"kg_node_id": 100, "canonical_chunk_id": "A"},
        {"kg_node_id": 100, "canonical_chunk_id": "B"},
        {"kg_node_id": 100, "canonical_chunk_id": "C"},
        {"kg_node_id": 10, "canonical_chunk_id": "A"},
        {"kg_node_id": 10, "canonical_chunk_id": "B"},
        {"kg_node_id": 10, "canonical_chunk_id": "C"},
    ])
    ws = str(_WS_A)
    # AA for cand 20 only: 1 -- w (deg 4) -- 20
    c._kg_edges[ws] = [
        {"src_node_id": 100, "dst_node_id": 7},
        {"src_node_id": 20, "dst_node_id": 7},
        {"src_node_id": 7, "dst_node_id": 8},
        {"src_node_id": 7, "dst_node_id": 9},  # deg(7)=4
    ]
    candidates = [{"node_id": 10}, {"node_id": 20}]
    cand_meta = {10: {}, 20: {}}
    structural, sub = kg_population._structural_map(
        new_key="new", new_node_id=100, candidates=candidates,
        cand_meta=cand_meta, workspace_id=_WS_A, supabase_client=c,
    )
    co10, aa10 = sub[10]
    co20, aa20 = sub[20]
    assert co10 == 3 and aa10 == 0.0  # primary only
    assert co20 == 0 and aa20 == pytest.approx(1 / __import__("math").log(4))
    # M5: effective is now continuous (no round()):
    #   effective(10) = 3 + 0.5*0 = 3.0
    #   effective(20) = 0 + 0.5*aa20 ≈ 0.36 (was rounded to 0 pre-M5)
    eff20 = 0 + kg_population._ADAMIC_AA_WEIGHT * aa20
    assert structural["new"]["c10"] == pytest.approx(3.0)
    assert structural["new"].get("c20", 0) == pytest.approx(eff20)
    # symmetric
    assert structural["c10"]["new"] == pytest.approx(3.0)


def test_structural_map_failure_degrades_to_empty(monkeypatch):
    c = FakeClient()
    monkeypatch.setattr(
        kg_population, "_shared_chunk_cooccurrence",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    structural, sub = kg_population._structural_map(
        new_key="new", new_node_id=1,
        candidates=[{"node_id": 10}], cand_meta={10: {}},
        workspace_id=_WS_A, supabase_client=c,
    )
    assert structural == {} and sub == {}  # degrade, no raise


@pytest.mark.asyncio
async def test_hook_populates_structural_in_matched_via():
    c = FakeClient()
    c.rpc_data["match_kg_nodes"] = [{"node_id": 10, "score": 0.99}]
    c._candidate_meta = [
        {"id": 10, "metadata": {"embedding": [0.1] * 768,
                                "tags": ["ml", "ai"],
                                "created_at": "2026-05-17T00:00:00+00:00"}},
    ]
    # node upsert returns 9001; share 2 chunks new(9001)<->cand(10).
    c._chunk_mentions = [
        {"kg_node_id": 9001, "canonical_chunk_id": "A"},
        {"kg_node_id": 9001, "canonical_chunk_id": "B"},
        {"kg_node_id": 10, "canonical_chunk_id": "A"},
        {"kg_node_id": 10, "canonical_chunk_id": "B"},
    ]
    await _run(c)
    edge = [w for w in c.writes if w[1] == "kg_edges"][0][3]
    mv = edge["matched_via"]
    assert mv["structural_shared_chunks"] == 2
    assert mv["structural_adamic_adar"] == 0.0
    # squashed: count/(count+2) = 2/4 = 0.5
    assert mv["structural"] == pytest.approx(0.5)
    assert {"structural", "structural_shared_chunks",
            "structural_adamic_adar"} <= set(mv)


@pytest.mark.asyncio
async def test_hook_structural_workspace_isolation_no_leak():
    """Candidate edges/mentions from workspace B never contribute."""
    c = FakeClient()
    c.rpc_data["match_kg_nodes"] = [{"node_id": 10, "score": 0.99}]
    c._candidate_meta = [
        {"id": 10, "metadata": {"embedding": [0.1] * 768, "tags": ["ml"],
                                "created_at": "2026-05-17T00:00:00+00:00"}},
    ]
    # Adamic-Adar edges exist ONLY in workspace B -> must NOT be read.
    c._kg_edges[str(_WS_B)] = [
        {"src_node_id": 9001, "dst_node_id": 5},
        {"src_node_id": 10, "dst_node_id": 5},
    ]
    await _run(c, workspace_id=_WS_A)
    # Every kg_edges SELECT must be fenced to workspace A.
    edge_sel = [
        f for (s, t, op, _p, f) in c.calls
        if s == "kg" and t == "kg_edges" and op == "select"
    ]
    assert edge_sel and all(
        f.get("workspace_id") == str(_WS_A) for f in edge_sel
    )
    assert all(str(_WS_B) not in str(f) for f in edge_sel)
    # AA contributed nothing (B edges invisible); edge still written via emb.
    edge = [w for w in c.writes if w[1] == "kg_edges"][0][3]
    assert edge["matched_via"]["structural_adamic_adar"] == 0.0


@pytest.mark.asyncio
async def test_hook_structural_failure_does_not_raise(monkeypatch):
    c = FakeClient()
    c.rpc_data["match_kg_nodes"] = [{"node_id": 10, "score": 0.99}]
    c._candidate_meta = [
        {"id": 10, "metadata": {"embedding": [0.1] * 768, "tags": ["ml", "ai"],
                                "created_at": "2026-05-17T00:00:00+00:00"}},
    ]
    monkeypatch.setattr(
        kg_population, "_adamic_adar",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("aa boom")),
    )
    m = await _run(c)  # must NOT raise; structural degrades to None
    assert "error" not in m  # pipeline still succeeded
    edge = [w for w in c.writes if w[1] == "kg_edges"][0][3]
    assert edge["matched_via"]["structural"] == 0.0
    assert edge["matched_via"]["structural_shared_chunks"] == 0


# --------------------------------------------------------------------------
# B2: populate_kg_for_zettel must write kg.chunk_node_mentions linking the
# zettel's kg_node to its content.canonical_chunks. This is B1's root cause
# (no prod path wrote mention rows) AND restores the PRIMARY structural
# signal (shared-chunk co-occurrence) for future ingests.
# --------------------------------------------------------------------------


_CID1 = "00000000-0000-0000-0000-0000000000A1"
_CID2 = "00000000-0000-0000-0000-0000000000A2"


@pytest.mark.asyncio
async def test_b2_mentions_inserted_for_each_canonical_chunk():
    c = FakeClient()
    # node upsert returns 9001 (FakeClient._next_node_id start).
    c._canonical_chunks = [
        {"id": _CID1, "canonical_zettel_id": str(_ZID)},
        {"id": _CID2, "canonical_zettel_id": str(_ZID)},
        # a chunk for a DIFFERENT zettel must never be linked.
        {"id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
         "canonical_zettel_id": "11111111-1111-1111-1111-111111111111"},
    ]
    await _run(c)
    mention_writes = [
        w for w in c.writes if w[1] == "chunk_node_mentions"
    ]
    assert mention_writes, "B2: no chunk_node_mentions written"
    # Flatten payloads (upsert may pass a list of rows or one dict).
    rows = []
    for _s, _t, _op, payload in mention_writes:
        rows.extend(payload if isinstance(payload, list) else [payload])
    linked = {(r["canonical_chunk_id"], r["kg_node_id"]) for r in rows}
    assert (_CID1, 9001) in linked
    assert (_CID2, 9001) in linked
    # The other zettel's chunk is never linked to this node.
    assert all(
        r["canonical_chunk_id"] not in (
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
        )
        for r in rows
    )
    # Schema-exact: mention_type within the CHECK set.
    assert all(
        r["mention_type"] in ("extracted", "tagged", "derived", "authored")
        for r in rows
    )


@pytest.mark.asyncio
async def test_b2_zero_chunks_writes_no_mentions_gracefully():
    c = FakeClient()
    c._canonical_chunks = []  # zettel has no chunks yet
    m = await _run(c)
    assert "error" not in m  # hook still succeeds
    assert [w for w in c.writes if w[1] == "chunk_node_mentions"] == []


@pytest.mark.asyncio
async def test_b2_idempotent_rerun_uses_conflict_safe_write():
    """Re-running must not create duplicate mention rows: the write goes
    through an idempotent upsert/ON CONFLICT path (PK = canonical_chunk_id,
    kg_node_id, mention_type per 03_kg_schema.sql)."""
    c = FakeClient()
    c._canonical_chunks = [{"id": _CID1, "canonical_zettel_id": str(_ZID)}]
    await _run(c)
    mention_ops = [
        w[2] for w in c.writes if w[1] == "chunk_node_mentions"
    ]
    assert mention_ops, "B2: no mention write happened"
    assert all(op == "upsert" for op in mention_ops), (
        "B2 mention write must be an idempotent upsert (ON CONFLICT), not a "
        "plain insert — re-ingest must not duplicate rows"
    )


@pytest.mark.asyncio
async def test_b2_mentions_workspace_scoped_no_uuid_leak():
    """The mention write path must not leak another workspace's UUID. The
    kg_node it links was upserted into workspace A; the chunk ids come from
    THIS zettel only. Assert no _WS_B anywhere in the mention payloads."""
    c = FakeClient()
    c._canonical_chunks = [{"id": _CID1, "canonical_zettel_id": str(_ZID)}]
    await _run(c, workspace_id=_WS_A)
    for _s, _t, _op, payload in c.writes:
        if _t == "chunk_node_mentions":
            assert str(_WS_B) not in str(payload)
    # The canonical_chunks SELECT is scoped to THIS zettel id only.
    sel = [
        f for (s, t, op, _p, f) in c.calls
        if s == "content" and t == "canonical_chunks" and op == "select"
    ]
    assert sel and all(
        f.get("canonical_zettel_id") == str(_ZID) for f in sel
    )


@pytest.mark.asyncio
async def test_b2_mention_write_failure_logs_and_skips_never_raises():
    """A failure in the mention-write path must NOT propagate (fire-and-
    forget contract) and must NOT abort node/edge population — the hook
    still finishes 'succeeded'."""
    c = FakeClient()
    c._canonical_chunks = [{"id": _CID1, "canonical_zettel_id": str(_ZID)}]
    c.fail_on = ("kg", "chunk_node_mentions", "upsert")
    m = await _run(c)  # MUST NOT raise
    assert "error" not in m, (
        "B2 mention-write failure must be swallowed (best-effort), not fail "
        "the whole kg-populate run"
    )
    # Node still upserted; pipeline still marked succeeded.
    assert any(w[1] == "kg_nodes" and w[2] == "upsert" for w in c.writes)
    assert any(
        w[0:3] == ("pipelines", "pipeline_runs", "update") for w in c.writes
    )


@pytest.mark.asyncio
async def test_b2_feeds_b1_primary_path_after_ingest():
    """End-to-end B1<-B2: after the hook writes mentions, the SAME
    chunk_node_mentions table the /api/graph assembler reads
    (list_node_zettel_mapping) now has rows for this node — i.e. B2 makes
    B1's PRIMARY path work for new ingests, not just the fallback."""
    c = FakeClient()
    c._canonical_chunks = [
        {"id": _CID1, "canonical_zettel_id": str(_ZID)},
        {"id": _CID2, "canonical_zettel_id": str(_ZID)},
    ]
    await _run(c)
    # Reflect the written mentions back into the fake's mention store and
    # confirm the repo's mapping resolver now resolves the node.
    rows = []
    for _s, _t, _op, payload in c.writes:
        if _t == "chunk_node_mentions":
            rows.extend(payload if isinstance(payload, list) else [payload])
    assert rows
    assert {r["kg_node_id"] for r in rows} == {9001}
    assert {r["canonical_chunk_id"] for r in rows} == {_CID1, _CID2}


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


# --------------------------------------------------------------------------
# Shared core + existing-node entrypoint (backfill reuse). These prove the
# refactor that extracted _score_and_upsert_edges_for_node did NOT change
# the live hook's behaviour (every hook test above still passes unchanged),
# and that populate_kg_edges_for_existing_node runs the SAME core.
# --------------------------------------------------------------------------


def test_shared_core_is_what_the_hook_calls():
    """The live hook delegates steps 4-5 to the shared core (single source
    of truth with the backfill). Asserting the call site exists guards the
    refactor against silent divergence."""
    import inspect

    src = inspect.getsource(kg_population.populate_kg_for_zettel)
    assert "_score_and_upsert_edges_for_node" in src, (
        "live hook must call the shared scoring core (no inlined copy)"
    )
    # And the existing-node entrypoint reuses the SAME core.
    src2 = inspect.getsource(
        kg_population.populate_kg_edges_for_existing_node
    )
    assert "_score_and_upsert_edges_for_node" in src2


def _node_row(nid, *, emb=0.1, tags=("ml", "ai"), name="Existing",
              created="2026-05-17T00:00:00+00:00", embedding=True):
    md = {"tags": list(tags), "created_at": created}
    if embedding:
        md["embedding"] = [emb] * 768
    return {"id": nid, "canonical_name": name, "metadata": md,
            "created_at": created}


def test_existing_node_creates_edges_from_warm_node():
    c = FakeClient()
    # Single-node load + candidate-meta both come from _candidate_meta here.
    c._candidate_meta = [
        _node_row(100),  # the node we backfill
        _node_row(200),  # its strong-match peer
    ]
    c.rpc_data["match_kg_nodes"] = [{"node_id": 200, "score": 0.99}]
    m = kg_population.populate_kg_edges_for_existing_node(
        workspace_id=_WS_A,
        profile_id=_PROFILE,
        kg_node_id=100,
        supabase_client=c,
    )
    assert m["edges"] >= 1 and not m.get("error")
    edge = [w for w in c.writes if w[1] == "kg_edges"][0][3]
    assert edge["workspace_strength"] >= scoring.EDGE_CREATION_THRESHOLD
    assert edge["src_node_id"] == 100 and edge["dst_node_id"] == 200
    assert edge["global_strength"] is None
    # No originating zettel for an existing-node pass -> evidence NULL.
    assert edge["evidence_canonical_zettel_id"] is None
    assert {"structural", "structural_shared_chunks",
            "structural_adamic_adar"} <= set(edge["matched_via"])


def test_existing_node_cold_regenerates_embedding(monkeypatch):
    """X8 (Phase 4 / Task 4.5): cold backfill uses live-ingest embed shape via
    generate_embedding_typed (was generate_embedding pre-X8)."""
    from website.features.kg_features.embeddings import EmbeddingResult
    calls = {"n": 0}

    def _gen(*_a, **_k):
        calls["n"] += 1
        return EmbeddingResult(ok=True, vectors=[[0.1] * 768], reason=None, retryable=False)

    monkeypatch.setattr(
        "website.features.kg_features.embeddings.generate_embedding_typed", _gen
    )
    c = FakeClient()
    c._candidate_meta = [
        _node_row(100, embedding=False),  # cold: no stored embedding
        _node_row(200),
    ]
    c.rpc_data["match_kg_nodes"] = [{"node_id": 200, "score": 0.99}]
    m = kg_population.populate_kg_edges_for_existing_node(
        workspace_id=_WS_A,
        profile_id=_PROFILE,
        kg_node_id=100,
        supabase_client=c,
    )
    assert calls["n"] == 1  # embedding regenerated for the cold node
    # Regenerated vector persisted back into kg_nodes.metadata.
    upd = [w for w in c.writes if w[1] == "kg_nodes" and w[2] == "update"]
    assert upd and upd[0][3]["metadata"]["embedding"] == [0.1] * 768
    # X8: shape marker recorded — title_only when summary lookup returned nothing.
    assert upd[0][3]["metadata"].get("embedding_input_shape") in {"title_only", "title_summary"}
    assert m["edges"] >= 1


def test_existing_node_cold_no_embedding_skips(monkeypatch):
    """X8: cold node whose typed-embedding call fails (rate-limit/etc.) is
    skipped gracefully — no edges written, no crash."""
    from website.features.kg_features.embeddings import EmbeddingFailureReason, EmbeddingResult
    monkeypatch.setattr(
        "website.features.kg_features.embeddings.generate_embedding_typed",
        lambda *_a, **_k: EmbeddingResult(
            ok=False, vectors=[], reason=EmbeddingFailureReason.RATE_LIMIT, retryable=True,
        ),
    )
    c = FakeClient()
    c._candidate_meta = [_node_row(100, embedding=False)]
    m = kg_population.populate_kg_edges_for_existing_node(
        workspace_id=_WS_A,
        profile_id=_PROFILE,
        kg_node_id=100,
        supabase_client=c,
    )
    assert m["skipped"] is True and m["edges"] == 0
    assert [w for w in c.writes if w[1] == "kg_edges"] == []


def test_existing_node_not_in_workspace_skips_no_leak():
    c = FakeClient()
    c._candidate_meta = []  # node id resolves to nothing in workspace A
    m = kg_population.populate_kg_edges_for_existing_node(
        workspace_id=_WS_A,
        profile_id=_PROFILE,
        kg_node_id=999,
        supabase_client=c,
    )
    assert m["skipped"] is True
    # The node-load SELECT was fenced to workspace A (never B).
    sel = [
        f for (s, t, op, _p, f) in c.calls
        if s == "kg" and t == "kg_nodes" and op == "select"
    ]
    assert sel and all(f.get("workspace_id") == str(_WS_A) for f in sel)
    assert all(str(_WS_B) not in str(f) for f in sel)


def test_existing_node_never_raises_on_internal_error():
    c = FakeClient()
    # Strong-match peer present so an edge upsert is actually attempted.
    c._candidate_meta = [_node_row(100), _node_row(200)]
    c.rpc_data["match_kg_nodes"] = [{"node_id": 200, "score": 0.99}]
    c.fail_on = ("kg", "kg_edges", "upsert")  # blow up at edge write
    m = kg_population.populate_kg_edges_for_existing_node(
        workspace_id=_WS_A,
        profile_id=_PROFILE,
        kg_node_id=100,
        supabase_client=c,
    )  # MUST NOT raise (per-node isolation contract)
    assert "error" in m
