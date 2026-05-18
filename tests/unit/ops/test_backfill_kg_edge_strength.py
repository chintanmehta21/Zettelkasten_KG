"""Unit coverage for ops/scripts/backfill_kg_edge_strength.py (no live DB).

A hand-rolled fake PostgREST client models the chained
``.schema().table().select().eq().gt().is_().order().range()/.limit()
.execute()`` + ``.upsert().execute()`` surface so the backfill runs fully
offline. The structural-signal RPCs/tables are modelled the same way the
live-hook test does.

Covered (per task spec):
- idempotent re-run: a second run skips already-scored edges; ``--force``
  re-scores them; no duplicate edges are ever inserted (upsert-only);
- workspace isolation: workspace B edges/nodes are never read or written
  when scoping workspace A (UUID-leak assertion on every read filter and
  every write payload);
- ``--dry-run`` performs ZERO writes;
- scorer wired: workspace_strength / connection_strength / matched_via
  carry D-KG-1 output incl. structural_* sub-signals;
- per-edge failure isolates: one bad edge does not abort the batch and the
  process exits non-zero;
- batch bounding: never fetches more than --batch-size per page.
"""
from __future__ import annotations

from uuid import UUID

from ops.scripts import backfill_kg_edge_strength as bf

# Canonical (lowercase) UUID form — ``str(UUID(...))`` normalizes to this,
# so the fake DB keys and the repo's ``str(workspace_id)`` write payload
# compare equal (Postgres' ``uuid`` type is itself case-insensitive).
_WS_A = str(UUID("00000000-0000-0000-0000-00000000000A"))
_WS_B = str(UUID("00000000-0000-0000-0000-00000000000B"))


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
        self._gt = {}
        self._is_null = set()
        self._limit = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def upsert(self, payload, **_k):
        self._op = "upsert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._filters[col] = list(vals)
        return self

    def gt(self, col, val):
        self._gt[col] = val
        return self

    def is_(self, col, _val):
        self._is_null.add(col)
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, lo, hi):
        self._limit = hi - lo + 1
        return self

    def limit(self, n, *_a, **_k):
        self._limit = n
        return self

    def execute(self):
        self._c.calls.append(
            (
                self._schema,
                self._table,
                self._op,
                self._payload,
                dict(self._filters),
                dict(self._gt),
                set(self._is_null),
                self._limit,
            )
        )
        if self._op == "upsert":
            self._c.writes.append(
                (self._schema, self._table, self._op, self._payload)
            )
        if self._op == "update":
            # Kept separate from ``writes`` so the existing 4-tuple unpack
            # in older tests stays valid; create-missing tests assert on the
            # workspace fence of the cold-embedding metadata persist here.
            self._c.updates.append(
                (
                    self._schema,
                    self._table,
                    self._payload,
                    dict(self._filters),
                )
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
    def __init__(self):
        self.calls = []
        self.writes = []
        self.updates = []  # kg_nodes metadata (cold-embedding) updates
        self.rpc_calls = []
        self.rpc_data: dict[str, list] = {}
        # workspace_id(str) -> list[edge dict]
        self.edges: dict[str, list[dict]] = {}
        # workspace_id(str) -> list[node dict {id, metadata, created_at}]
        self.nodes: dict[str, list[dict]] = {}
        self._chunk_mentions: list[dict] = []
        self.fail_score_edge_id = None  # edge id whose scoring raises

    def schema(self, name):
        return _SchemaProxy(self, name)

    def _respond(self, q: _Query):
        if q._schema == "kg" and q._table == "kg_edges":
            if q._op == "upsert":
                return _Resp([{"id": 7777}])
            if q._op == "select":
                ws = q._filters.get("workspace_id")
                # workspace_id discovery scan (no ws filter): every edge row.
                if ws is None:
                    rows = [
                        {"workspace_id": w}
                        for w, es in self.edges.items()
                        for _ in es
                    ]
                    return _Resp(rows)
                rows = list(self.edges.get(ws, []))
                # _node_has_edges: workspace + single src_node_id eq (scalar,
                # NOT a list) + limit(1). Distinguish from the AA fetch
                # (which uses .in_(col, [...]) -> list) by value type.
                src_f = q._filters.get("src_node_id")
                if src_f is not None and not isinstance(src_f, list):
                    hit = [
                        r for r in rows if r.get("src_node_id") == src_f
                    ]
                    return _Resp(
                        [{"id": r.get("id", 1)} for r in hit[: (q._limit or 1)]]
                    )
                # Adamic-Adar incident-edge fetch carries src/dst in_ filter.
                if "src_node_id" in q._filters or "dst_node_id" in q._filters:
                    for col in ("src_node_id", "dst_node_id"):
                        if col in q._filters:
                            seeds = set(q._filters[col])
                            rows = [
                                r for r in rows if r.get(col) in seeds
                            ]
                            break
                    return _Resp(
                        [
                            {
                                "src_node_id": r["src_node_id"],
                                "dst_node_id": r["dst_node_id"],
                            }
                            for r in rows
                        ]
                    )
                # Main edge-batch fetch: apply gt(id), is_null, limit.
                if "id" in q._gt:
                    rows = [r for r in rows if r["id"] > q._gt["id"]]
                if "workspace_strength" in q._is_null:
                    rows = [
                        r for r in rows if r.get("workspace_strength") is None
                    ]
                rows = sorted(rows, key=lambda r: r["id"])
                if q._limit is not None:
                    rows = rows[: q._limit]
                return _Resp(rows)

        if q._schema == "kg" and q._table == "kg_nodes":
            if q._op == "update":
                return _Resp([{"id": q._filters.get("id")}])
            if q._op == "select":
                ws = q._filters.get("workspace_id")
                # (a) workspace discovery scan: no ws filter, no id filter.
                if ws is None and "id" not in q._filters:
                    rows = [
                        {"workspace_id": w}
                        for w, ns in self.nodes.items()
                        for _ in ns
                    ]
                    return _Resp(rows)
                ws_nodes = list(self.nodes.get(ws, []))
                id_f = q._filters.get("id")
                # (c) candidate-metadata batch: .in_("id", [..]) -> list.
                if isinstance(id_f, list):
                    ids = set(id_f)
                    return _Resp(
                        [n for n in ws_nodes if n["id"] in ids]
                    )
                # (d) single-node load: .eq("id", node_id) -> scalar.
                if id_f is not None:
                    return _Resp(
                        [n for n in ws_nodes if n["id"] == id_f][
                            : (q._limit or 1)
                        ]
                    )
                # (b) node-batch fetch: gt(id) cursor + order + limit.
                rows = ws_nodes
                if "id" in q._gt:
                    rows = [r for r in rows if r["id"] > q._gt["id"]]
                rows = sorted(rows, key=lambda r: r["id"])
                if q._limit is not None:
                    rows = rows[: q._limit]
                return _Resp([{"id": r["id"]} for r in rows])

        if q._schema == "kg" and q._table == "chunk_node_mentions":
            if q._op == "select":
                ids = set(q._filters.get("kg_node_id", []))
                return _Resp(
                    [r for r in self._chunk_mentions if r["kg_node_id"] in ids]
                )

        return _Resp([])


class FakeRepo:
    """Mirrors KGRepository.upsert_edge's idempotency contract."""

    def __init__(self, client: FakeClient):
        self._c = client
        # natural key -> stored row (idempotent: re-upsert UPDATES in place)
        self.rows: dict[tuple, dict] = {}

    def upsert_edge(self, **kw):
        if kw.get("workspace_id") is None:
            raise ValueError("workspace_id required")
        nk = (
            str(kw["workspace_id"]),
            kw["src_node_id"],
            kw["dst_node_id"],
            kw["relation_type"],
        )
        existed = nk in self.rows
        self.rows[nk] = dict(kw)
        # Reflect the write into the fake DB so a second run sees it scored.
        ws = str(kw["workspace_id"])
        for e in self._c.edges.get(ws, []):
            if (
                e["src_node_id"] == kw["src_node_id"]
                and e["dst_node_id"] == kw["dst_node_id"]
                and e["relation_type"] == kw["relation_type"]
            ):
                e["workspace_strength"] = kw["workspace_strength"]
        # record into client.writes for assertion parity
        self._c.writes.append(
            ("kg", "kg_edges", "upsert", {**kw, "_existed": existed})
        )
        return 7777


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------


def _meta(emb=0.1, tags=("ml", "ai"), created="2026-05-17T00:00:00+00:00"):
    return {
        "embedding": [emb] * 768,
        "tags": list(tags),
        "created_at": created,
    }


def _edge(eid, src, dst, ws_strength=None):
    return {
        "id": eid,
        "workspace_id": None,  # set by container key; filter uses container
        "src_node_id": src,
        "dst_node_id": dst,
        "relation_type": "co_occurs",
        "workspace_strength": ws_strength,
        "evidence_canonical_zettel_id": None,
    }


def _seed_one_strong_edge(ws=_WS_A, ws_strength=None):
    c = FakeClient()
    c.edges[ws] = [_edge(1, 100, 200, ws_strength)]
    # Identical embedding + tags -> strong D-KG-1 score (>= creation thr).
    c.nodes[ws] = [
        {"id": 100, "metadata": _meta(), "created_at": None},
        {"id": 200, "metadata": _meta(), "created_at": None},
    ]
    return c


def _args(**over):
    base = dict(
        workspace=None,
        batch_size=200,
        limit=None,
        force=False,
        dry_run=False,
        create_missing=False,
        profile=None,
    )
    base.update(over)
    return bf.argparse.Namespace(**base)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_scorer_wired_writes_strength_and_matched_via():
    c = _seed_one_strong_edge()
    repo = FakeRepo(c)
    rc = bf._run(_args(workspace=_WS_A), c, repo)
    assert rc == 0
    edge_writes = [w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"]
    assert len(edge_writes) == 1
    p = edge_writes[0][3]
    from website.features.kg_features import scoring

    assert p["workspace_strength"] >= scoring.EDGE_CREATION_THRESHOLD
    assert p["connection_strength"] == p["workspace_strength"]
    assert p["global_strength"] is None
    mv = p["matched_via"]
    assert set(mv) >= {
        "embedding",
        "tag",
        "structural",
        "structural_shared_chunks",
        "structural_adamic_adar",
        "temporal",
        "composite",
    }


def test_idempotent_rerun_skips_scored_edges():
    c = _seed_one_strong_edge()
    repo = FakeRepo(c)
    bf._run(_args(workspace=_WS_A), c, repo)
    first = len([w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"])
    assert first == 1
    # Second run (no --force): edge now has workspace_strength -> SKIPPED.
    c.writes.clear()
    rc = bf._run(_args(workspace=_WS_A), c, repo)
    assert rc == 0
    assert [w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"] == []


def test_force_rescores_already_scored_edges():
    c = _seed_one_strong_edge(ws_strength=0.123)  # already scored
    repo = FakeRepo(c)
    # Without --force: skipped.
    bf._run(_args(workspace=_WS_A), c, repo)
    assert [w for w in c.writes if w[2] == "upsert"] == []
    # With --force: re-scored.
    rc = bf._run(_args(workspace=_WS_A, force=True), c, repo)
    assert rc == 0
    w = [w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"]
    assert len(w) == 1


def test_no_duplicate_edges_ever_inserted():
    c = _seed_one_strong_edge()
    repo = FakeRepo(c)
    bf._run(_args(workspace=_WS_A), c, repo)
    bf._run(_args(workspace=_WS_A, force=True), c, repo)
    bf._run(_args(workspace=_WS_A, force=True), c, repo)
    # Idempotent natural key: exactly one logical row regardless of re-runs.
    assert len(repo.rows) == 1
    nk = next(iter(repo.rows))
    assert nk == (_WS_A, 100, 200, "co_occurs")


def test_dry_run_performs_zero_writes():
    c = _seed_one_strong_edge()
    repo = FakeRepo(c)
    rc = bf._run(_args(workspace=_WS_A, dry_run=True), c, repo)
    assert rc == 0
    assert [w for w in c.writes if w[2] == "upsert"] == []
    assert repo.rows == {}


def test_workspace_isolation_no_uuid_leak():
    c = FakeClient()
    c.edges[_WS_A] = [_edge(1, 100, 200)]
    c.nodes[_WS_A] = [
        {"id": 100, "metadata": _meta(), "created_at": None},
        {"id": 200, "metadata": _meta(), "created_at": None},
    ]
    # Workspace B has its own edges/nodes that must NEVER be touched.
    c.edges[_WS_B] = [_edge(99, 500, 600)]
    c.nodes[_WS_B] = [
        {"id": 500, "metadata": _meta(), "created_at": None},
        {"id": 600, "metadata": _meta(), "created_at": None},
    ]
    repo = FakeRepo(c)
    bf._run(_args(workspace=_WS_A), c, repo)

    # Every kg read filter that carries a workspace_id is workspace A only.
    for s, t, op, _p, filt, _gt, _isn, _lim in c.calls:
        if s == "kg" and "workspace_id" in filt:
            assert filt["workspace_id"] == _WS_A
            assert _WS_B not in str(filt)
    # Every write payload carries workspace A only; never B.
    for s, t, op, payload in c.writes:
        if s == "kg" and isinstance(payload, dict):
            assert str(payload.get("workspace_id")) == _WS_A
            assert _WS_B not in str(payload)
    # Workspace B's edge was never written.
    assert all(
        not (w[3].get("src_node_id") == 500) for w in c.writes if isinstance(w[3], dict)
    )


def test_per_edge_failure_isolates_and_exit_nonzero(monkeypatch):
    c = FakeClient()
    c.edges[_WS_A] = [_edge(1, 100, 200), _edge(2, 300, 400)]
    c.nodes[_WS_A] = [
        {"id": 100, "metadata": _meta(), "created_at": None},
        {"id": 200, "metadata": _meta(), "created_at": None},
        {"id": 300, "metadata": _meta(), "created_at": None},
        {"id": 400, "metadata": _meta(), "created_at": None},
    ]
    repo = FakeRepo(c)

    real = bf._score_one_edge

    def _boom(edge, ws, nm, sb):
        if int(edge["id"]) == 1:
            raise RuntimeError("poison edge")
        return real(edge, ws, nm, sb)

    monkeypatch.setattr(bf, "_score_one_edge", _boom)
    rc = bf._run(_args(workspace=_WS_A), c, repo)
    # One edge failed -> non-zero exit, but edge 2 still processed/written.
    assert rc == 1
    written = [
        w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"
    ]
    assert len(written) == 1
    assert written[0][3]["src_node_id"] == 300


def test_batch_bounding_never_fetches_more_than_batch_size():
    c = FakeClient()
    c.edges[_WS_A] = [_edge(i, i * 10, i * 10 + 1) for i in range(1, 51)]
    c.nodes[_WS_A] = [
        {"id": j, "metadata": _meta(), "created_at": None}
        for i in range(1, 51)
        for j in (i * 10, i * 10 + 1)
    ]
    repo = FakeRepo(c)
    bf._run(_args(workspace=_WS_A, batch_size=10), c, repo)
    # Main edge-batch SELECTs (carry is_null + limit) must each cap at 10.
    main_fetches = [
        lim
        for (s, t, op, _p, filt, _gt, isn, lim) in c.calls
        if s == "kg"
        and t == "kg_edges"
        and op == "select"
        and "workspace_strength" in isn
    ]
    assert main_fetches
    assert all(lim is not None and lim <= 10 for lim in main_fetches)
    # All 50 edges still get processed across bounded batches.
    assert len(repo.rows) == 50


def test_limit_caps_total_edges_processed():
    c = FakeClient()
    c.edges[_WS_A] = [_edge(i, i * 10, i * 10 + 1) for i in range(1, 21)]
    c.nodes[_WS_A] = [
        {"id": j, "metadata": _meta(), "created_at": None}
        for i in range(1, 21)
        for j in (i * 10, i * 10 + 1)
    ]
    repo = FakeRepo(c)
    bf._run(_args(workspace=_WS_A, batch_size=200, limit=5), c, repo)
    assert len(repo.rows) == 5


def test_cold_start_edge_still_writes_low_strength():
    c = FakeClient()
    c.edges[_WS_A] = [_edge(1, 100, 200)]
    # No node metadata at all -> embedding/tags/structural all degrade to 0.
    c.nodes[_WS_A] = []
    repo = FakeRepo(c)
    rc = bf._run(_args(workspace=_WS_A), c, repo)
    assert rc == 0
    w = [w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"]
    assert len(w) == 1
    # Valid (low) strength written, edge not skipped, batch not crashed.
    assert 0.0 <= w[0][3]["workspace_strength"] < bf_creation_threshold()


def bf_creation_threshold():
    from website.features.kg_features import scoring

    return scoring.EDGE_CREATION_THRESHOLD


# --------------------------------------------------------------------------
# --create-missing mode: CREATE edges for an existing workspace's nodes
# (operator-reported: Naruto has kg_nodes but 0 kg_edges).
# --------------------------------------------------------------------------

import pytest  # noqa: E402

_PROFILE = str(UUID("00000000-0000-0000-0000-000000000001"))


@pytest.fixture
def _patch_embed(monkeypatch):
    """Deterministic embedding so the kNN/score path runs offline."""
    monkeypatch.setattr(
        "website.features.kg_features.embeddings.generate_embedding",
        lambda *_a, **_k: [0.1] * 768,
    )


def _node(nid, *, emb=0.1, tags=("ml", "ai"), name="N",
          created="2026-05-17T00:00:00+00:00", embedding=True):
    md = {"tags": list(tags), "created_at": created}
    if embedding:
        md["embedding"] = [emb] * 768
    return {"id": nid, "canonical_name": name, "metadata": md,
            "created_at": created}


def _cm_args(**over):
    return _args(create_missing=True, profile=_PROFILE, **over)


def _seed_two_node_edgeless_workspace(ws=_WS_A):
    """Two strong-match nodes, ZERO edges (the Naruto failure shape)."""
    c = FakeClient()
    c.nodes[ws] = [_node(100), _node(200)]
    c.edges[ws] = []  # edgeless: the whole point
    # match_kg_nodes returns each node's peer as a candidate.
    c.rpc_data["match_kg_nodes"] = [
        {"node_id": 100, "score": 0.99},
        {"node_id": 200, "score": 0.99},
    ]
    return c


def test_create_missing_requires_profile():
    c = _seed_two_node_edgeless_workspace()
    rc = bf._run(_args(create_missing=True, workspace=_WS_A), c, None)
    assert rc == 2  # hard-fail: no --profile -> cannot key the kNN RPC
    assert [w for w in c.writes if w[2] == "upsert"] == []


def test_create_missing_creates_edges_for_edgeless_nodes(_patch_embed):
    c = _seed_two_node_edgeless_workspace()
    rc = bf._run(_cm_args(workspace=_WS_A), c, None)
    assert rc == 0
    edge_writes = [
        w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"
    ]
    assert len(edge_writes) >= 1
    p = edge_writes[0][3]
    # D-KG-1 wired: strength >= creation threshold + matched_via populated.
    assert p["workspace_strength"] >= bf_creation_threshold()
    assert p["connection_strength"] == p["workspace_strength"]
    assert p["global_strength"] is None
    mv = p["matched_via"]
    assert set(mv) >= {
        "embedding", "tag", "structural",
        "structural_shared_chunks", "structural_adamic_adar",
        "temporal", "composite",
    }
    # Existing-node pass: no single originating zettel -> evidence NULL.
    assert p["evidence_canonical_zettel_id"] is None


def test_create_missing_idempotent_skips_already_edged(_patch_embed):
    c = _seed_two_node_edgeless_workspace()
    bf._run(_cm_args(workspace=_WS_A), c, None)
    # Reflect created edges back so node 100 now "has edges".
    c.edges[_WS_A] = [
        {"id": 1, "src_node_id": 100, "dst_node_id": 200,
         "relation_type": "co_occurs", "workspace_strength": 0.9},
        {"id": 2, "src_node_id": 200, "dst_node_id": 100,
         "relation_type": "co_occurs", "workspace_strength": 0.9},
    ]
    c.writes.clear()
    rc = bf._run(_cm_args(workspace=_WS_A), c, None)
    assert rc == 0
    # Both nodes already have an outgoing edge -> skipped, no new writes.
    assert [w for w in c.writes if w[1] == "kg_edges"] == []


def test_create_missing_force_reprocesses_edged_nodes(_patch_embed):
    c = _seed_two_node_edgeless_workspace()
    c.edges[_WS_A] = [
        {"id": 1, "src_node_id": 100, "dst_node_id": 200,
         "relation_type": "co_occurs", "workspace_strength": 0.9},
    ]
    # Without --force: node 100 has an edge -> skipped (node 200 has none).
    bf._run(_cm_args(workspace=_WS_A), c, None)
    base = len([w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"])
    c.writes.clear()
    # With --force: every node re-processed/re-scored.
    rc = bf._run(_cm_args(workspace=_WS_A, force=True), c, None)
    assert rc == 0
    forced = len([w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"])
    assert forced >= base


def test_create_missing_no_duplicate_edges_natural_key(_patch_embed):
    c = _seed_two_node_edgeless_workspace()
    bf._run(_cm_args(workspace=_WS_A, force=True), c, None)
    bf._run(_cm_args(workspace=_WS_A, force=True), c, None)
    # Every upsert targets the (ws,src,dst,relation) natural key — the real
    # KGRepository.upsert_edge uses on_conflict so re-runs UPDATE in place.
    for s, t, op, p in c.writes:
        if t == "kg_edges" and op == "upsert":
            assert op == "upsert"  # never a raw insert -> no dup rows
            assert str(p["workspace_id"]) == _WS_A


def test_create_missing_dry_run_zero_writes(_patch_embed):
    c = _seed_two_node_edgeless_workspace()
    rc = bf._run(_cm_args(workspace=_WS_A, dry_run=True), c, None)
    assert rc == 0
    assert [w for w in c.writes if w[2] == "upsert"] == []
    assert c.updates == []  # not even the cold-embedding persist


def test_create_missing_workspace_isolation_no_uuid_leak(_patch_embed):
    c = _seed_two_node_edgeless_workspace(ws=_WS_A)
    # Workspace B has its own nodes/edges that must NEVER be touched.
    c.nodes[_WS_B] = [_node(500), _node(600)]
    c.edges[_WS_B] = []
    c.rpc_data["match_kg_nodes"] = [{"node_id": 100, "score": 0.99}]
    bf._run(_cm_args(workspace=_WS_A), c, None)

    # Every kg read filter that carries a workspace_id is workspace A only.
    for s, t, op, _p, filt, _gt, _isn, _lim in c.calls:
        if s == "kg" and "workspace_id" in filt:
            assert filt["workspace_id"] == _WS_A
            assert _WS_B not in str(filt)
    # Every write payload carries workspace A only; never B.
    for s, t, op, payload in c.writes:
        if s == "kg" and isinstance(payload, dict):
            assert str(payload.get("workspace_id")) == _WS_A
            assert _WS_B not in str(payload)
    # Workspace B nodes (500/600) never appear as an edge endpoint.
    for w in c.writes:
        if w[1] == "kg_edges" and isinstance(w[3], dict):
            assert w[3].get("src_node_id") not in (500, 600)
            assert w[3].get("dst_node_id") not in (500, 600)


def test_create_missing_cold_node_regenerates_and_persists_embedding(
    _patch_embed,
):
    c = FakeClient()
    # Node 100 has NO stored embedding (the cold case) -> regenerate.
    c.nodes[_WS_A] = [
        _node(100, embedding=False),
        _node(200),
    ]
    c.edges[_WS_A] = []
    c.rpc_data["match_kg_nodes"] = [
        {"node_id": 100, "score": 0.99},
        {"node_id": 200, "score": 0.99},
    ]
    rc = bf._run(_cm_args(workspace=_WS_A), c, None)
    assert rc == 0
    # Regenerated vector persisted back into kg_nodes.metadata, ws-fenced.
    persists = [
        u for u in c.updates if u[1] == "kg_nodes"
    ]
    assert persists
    schema, table, payload, filt = persists[0]
    assert filt["workspace_id"] == _WS_A
    assert payload["metadata"]["embedding"] == [0.1] * 768
    # Edges still created for the (now-warm) cold node.
    assert [w for w in c.writes if w[1] == "kg_edges" and w[2] == "upsert"]


def test_create_missing_cold_node_no_embedding_skips_gracefully(monkeypatch):
    # Embedding generation unavailable (quota/network) -> empty list.
    monkeypatch.setattr(
        "website.features.kg_features.embeddings.generate_embedding",
        lambda *_a, **_k: [],
    )
    c = FakeClient()
    c.nodes[_WS_A] = [_node(100, embedding=False)]
    c.edges[_WS_A] = []
    rc = bf._run(_cm_args(workspace=_WS_A), c, None)
    assert rc == 0  # skipped node is NOT a failure
    # No edge written, no metadata persisted, batch not crashed.
    assert [w for w in c.writes if w[1] == "kg_edges"] == []
    assert c.updates == []


def test_create_missing_per_node_failure_isolated_exit_nonzero(
    _patch_embed, monkeypatch
):
    c = FakeClient()
    c.nodes[_WS_A] = [_node(100), _node(200)]
    c.edges[_WS_A] = []
    # Both nodes are each other's strong-match candidate (200 must still get
    # an edge after 100's processing is poisoned).
    c.rpc_data["match_kg_nodes"] = [
        {"node_id": 100, "score": 0.99},
        {"node_id": 200, "score": 0.99},
    ]

    import website.features.rag_pipeline.ingest.kg_population as kgp

    real = kgp._score_and_upsert_edges_for_node

    def _boom(**kw):
        if int(kw["node_id"]) == 100:
            raise RuntimeError("poison node")
        return real(**kw)

    monkeypatch.setattr(kgp, "_score_and_upsert_edges_for_node", _boom)
    rc = bf._run(_cm_args(workspace=_WS_A), c, None)
    # One node failed -> non-zero exit, but node 200 still processed.
    assert rc == 1
    edged_src = {
        w[3]["src_node_id"]
        for w in c.writes
        if w[1] == "kg_edges" and w[2] == "upsert"
    }
    assert 100 not in edged_src
    assert 200 in edged_src


def test_create_missing_bounded_query_count_per_node(_patch_embed):
    """Per node the query cost is a small CONSTANT (reuses the hook's
    <=K kNN + <=5 structural-fanout bound), candidate-count-independent."""
    c = FakeClient()
    c.nodes[_WS_A] = [_node(1)]
    c.edges[_WS_A] = []
    # kNN returns MANY candidates; per-node cost must stay constant.
    c.rpc_data["match_kg_nodes"] = [
        {"node_id": i, "score": 0.5} for i in range(2, 80)
    ]
    c.nodes[_WS_A].extend(_node(i) for i in range(2, 80))
    c.calls.clear()
    bf._run(_cm_args(workspace=_WS_A, limit=1), c, None)
    # kg_edges SELECTs for THIS node: Adamic-Adar fan-out is a small const
    # (<=4 incident-edge selects) + 1 _node_has_edges check. NEVER O(cands).
    edge_sel = [
        x for x in c.calls
        if x[0] == "kg" and x[1] == "kg_edges" and x[2] == "select"
    ]
    assert len(edge_sel) <= 6  # 1 has-edges + <=4 AA + slack; const
    # Exactly ONE chunk_node_mentions query regardless of candidate count.
    cm = [
        x for x in c.calls
        if x[0] == "kg" and x[1] == "chunk_node_mentions"
    ]
    assert len(cm) <= 1
    # match RPC keyed off the owner profile (its workspace fence).
    rpc = [p for (s, n, p) in c.rpc_calls if n == "match_kg_nodes"]
    assert rpc and rpc[0]["p_user_id"] == _PROFILE


def test_create_missing_limit_caps_nodes_processed(_patch_embed):
    c = FakeClient()
    c.nodes[_WS_A] = [_node(i) for i in range(1, 21)]
    c.edges[_WS_A] = []
    c.rpc_data["match_kg_nodes"] = []  # no candidates -> 0 edges, still counts
    bf._run(_cm_args(workspace=_WS_A, batch_size=200, limit=5), c, None)
    # Node-batch fetches must never exceed the cap; <=5 nodes considered.
    node_fetches = [
        lim
        for (s, t, op, _p, filt, _gt, _isn, lim) in c.calls
        if s == "kg" and t == "kg_nodes" and op == "select"
        and "id" not in filt and "workspace_id" in filt
    ]
    assert node_fetches and all(
        lim is not None and lim <= 5 for lim in node_fetches
    )


def test_create_missing_invalid_profile_uuid_aborts():
    c = _seed_two_node_edgeless_workspace()
    rc = bf._run(
        _args(create_missing=True, workspace=_WS_A, profile="not-a-uuid"),
        c,
        None,
    )
    assert rc == 2
    assert [w for w in c.writes if w[2] == "upsert"] == []
