"""v2 unit tests for `graph_score.py` (Phase 2.3 — supabase_kg purge).

Verifies the refactored `LocalizedPageRankScorer`:

  1. delegates the usage-edge bonus to the v2 RPC `rag.search_signal_weights`
     via `RAGRepository.search_signal_weights` (NOT the retired
     `public.kg_usage_edges_agg` MV);
  2. preserves the decay-weight scoring math byte-for-byte
     (`0.10 / (1.0 + exp(-weight / 5.0)) - 0.05`);
  3. no longer imports from ``website.core.supabase_kg``.

Mocks follow the `_Client` / `_Schema` idiom from
`tests/unit/supabase_v2/test_repositories.py`.
"""
from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from website.features.rag_pipeline.retrieval import graph_score as graph_score_module
from website.features.rag_pipeline.retrieval.graph_score import (
    LocalizedPageRankScorer,
    _usage_weight_bonus,
)
from website.features.rag_pipeline.types import (
    ChunkKind,
    QueryClass,
    RetrievalCandidate,
    SourceType,
)


# ---------------------------------------------------------------------------
# v2 supabase-py client mocks (sync) — surface graph_score touches:
#   * client.rpc("rag_subgraph_for_pagerank", ...).execute()
#   * client.schema("rag").rpc("search_signal_weights", ...).execute()
# ---------------------------------------------------------------------------


class _Execute:
    def __init__(self, data, raise_exc: BaseException | None = None):
        self._data = data
        self._raise = raise_exc

    def execute(self):
        if self._raise is not None:
            raise self._raise
        return SimpleNamespace(data=self._data)


class _RagSchema:
    def __init__(self, calls, schema, signal_weight_rows, signal_raise):
        self.calls = calls
        self.schema = schema
        self._rows = signal_weight_rows
        self._raise = signal_raise

    def rpc(self, name, params):
        self.calls.append(("schema_rpc", self.schema, name, params))
        # Filter by p_target_chunk_ids so each per-target lookup gets only its
        # rows (matches the SQL `target = ANY (...)` filter and lets the
        # _usage_weight_bonus per-target call return a deterministic scalar).
        targets = set(params.get("p_target_chunk_ids") or [])
        filtered = [r for r in self._rows if str(r["target_canonical_chunk_id"]) in targets]
        return _Execute(filtered, self._raise)


class _Client:
    """Mimics the bits of `supabase.Client` LocalizedPageRankScorer touches."""

    def __init__(
        self,
        *,
        edges=None,
        signal_weight_rows=None,
        signal_raise: BaseException | None = None,
    ):
        self.calls: list = []
        self._edges = edges or []
        self._signal_rows = signal_weight_rows or []
        self._signal_raise = signal_raise

    # Unscoped rpc for the legacy public schema RPC `rag_subgraph_for_pagerank`.
    # Phase 2.3 brief is scoped to the usage-edge MV purge — the PageRank RPC
    # is not in the v2 schema yet, so this path is unchanged.
    def rpc(self, name, params):
        self.calls.append(("rpc", name, params))
        assert name == "rag_subgraph_for_pagerank", (
            f"unexpected unscoped rpc({name!r}); v2 reads must go through schema('rag')"
        )
        return _Execute(self._edges)

    # v2 contract: usage-edge weights via schema('rag').rpc('search_signal_weights', ...)
    def schema(self, name):
        self.calls.append(("schema", name))
        return _RagSchema(self.calls, name, self._signal_rows, self._signal_raise)


def _candidate(node_id: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=None,
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content="content",
        rrf_score=0.5,
    )


# ---------------------------------------------------------------------------
# Static / file-level guarantees
# ---------------------------------------------------------------------------


def test_graph_score_module_does_not_import_supabase_kg():
    """File-level grep: `supabase_kg` and the legacy MV must not appear."""
    src_path = Path(graph_score_module.__file__)
    text = src_path.read_text(encoding="utf-8")
    assert "from website.core.supabase_kg" not in text, (
        "graph_score.py must not import from supabase_kg after v2 purge"
    )
    assert "kg_usage_edges_agg" not in text, (
        "graph_score.py must not reference the legacy v1 MV after v2 purge"
    )


# ---------------------------------------------------------------------------
# Decay-weight math snapshot — captured from the original v1 implementation
# (sigmoid: 0.10 / (1 + exp(-w / 5.0)) - 0.05). Byte-for-byte preservation
# requirement from Phase 2.3 brief.
# ---------------------------------------------------------------------------


def _expected_bonus(total_weight: float) -> float:
    return 0.10 / (1.0 + math.exp(-total_weight / 5.0)) - 0.05


@pytest.mark.parametrize(
    "weights,expected_total",
    [
        ([], 0.0),                  # empty rows → bonus == 0
        ([1.0], 1.0),
        ([2.5, 7.5], 10.0),
        ([10.0, 8.0], 18.0),
        ([-3.0, 1.5], -1.5),        # negative-weight rows still flow through
    ],
)
def test_usage_weight_bonus_math_byte_for_byte(weights, expected_total):
    """Decay-weight scoring math is preserved byte-for-byte against v1."""

    class _Repo:
        def __init__(self, rows):
            self.rows = rows
            self.calls = []

        def search_signal_weights(self, *, workspace_id, target_chunk_ids, query_class):
            self.calls.append((str(workspace_id), list(map(str, target_chunk_ids)), query_class))
            return self.rows

    rows = [
        {
            "source_canonical_chunk_id": str(uuid4()),
            "target_canonical_chunk_id": "chunk-T",
            "weight": w,
        }
        for w in weights
    ]
    repo = _Repo(rows)
    user = uuid4()

    bonus = _usage_weight_bonus(
        repo,
        user_id=user,
        target_node_id="chunk-T",
        query_class=QueryClass.MULTI_HOP,
    )

    assert bonus == pytest.approx(_expected_bonus(expected_total), abs=1e-12)
    # Single delegated call with the right shape.
    assert repo.calls == [(str(user), ["chunk-T"], "multi_hop")]


def test_usage_weight_bonus_returns_zero_on_repo_error():
    """Identity contract from v1: any failure → 0.0 bonus."""

    class _Repo:
        def search_signal_weights(self, *, workspace_id, target_chunk_ids, query_class):
            raise RuntimeError("simulated postgrest 5xx")

    bonus = _usage_weight_bonus(
        _Repo(),
        user_id=uuid4(),
        target_node_id="chunk-T",
        query_class=QueryClass.LOOKUP,
    )
    assert bonus == 0.0


def test_usage_weight_bonus_disabled_short_circuits(monkeypatch):
    """RAG_USAGE_EDGES_ENABLED=false → 0.0 bonus, no repo call."""
    monkeypatch.setattr(graph_score_module, "_USAGE_EDGES_ENABLED", False)

    class _Repo:
        def __init__(self):
            self.called = False

        def search_signal_weights(self, **_kw):
            self.called = True
            raise AssertionError("repo must NOT be called when usage edges disabled")

    repo = _Repo()
    bonus = _usage_weight_bonus(
        repo,
        user_id=uuid4(),
        target_node_id="chunk-T",
        query_class=QueryClass.MULTI_HOP,
    )
    assert bonus == 0.0
    assert repo.called is False


# ---------------------------------------------------------------------------
# Integration through LocalizedPageRankScorer.score(): new RPC must be wired
# instead of the legacy MV read.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_delegates_to_search_signal_weights_rpc():
    """Verify the public scoring path calls schema('rag').rpc('search_signal_weights', ...)."""
    edges = [
        {"source_node_id": "node-1", "target_node_id": "node-2", "weight": 1.0},
        {"source_node_id": "node-2", "target_node_id": "node-3", "weight": 1.0},
    ]
    signal_rows = [
        # Decayed weight for target node-3 only.
        {
            "source_canonical_chunk_id": "node-1",
            "target_canonical_chunk_id": "node-3",
            "weight": 10.0,
        },
        {
            "source_canonical_chunk_id": "node-2",
            "target_canonical_chunk_id": "node-3",
            "weight": 8.0,
        },
    ]
    fake = _Client(edges=edges, signal_weight_rows=signal_rows)

    # Baseline: no query_class → no SEARCH_SIGNAL_WEIGHTS RPC must be called.
    # The pagerank RPC (subgraph_for_pagerank) legitimately fires every score()
    # call post P1-1 fix and is intentionally NOT gated by query_class — so we
    # filter the recorded schema_rpc calls by rpc-name, not the bare kind.
    baseline_candidates = [_candidate("node-1"), _candidate("node-2"), _candidate("node-3")]
    scorer_baseline = LocalizedPageRankScorer(supabase=fake)
    await scorer_baseline.score(user_id=uuid4(), candidates=baseline_candidates)
    signal_calls_baseline = [
        c for c in fake.calls if c[0] == "schema_rpc" and c[2] == "search_signal_weights"
    ]
    assert signal_calls_baseline == [], (
        f"no signal-weight RPC expected without query_class, got {signal_calls_baseline!r}"
    )
    # P1-1 lock-in: pagerank centrality RPC must fire regardless of query_class.
    pagerank_calls_baseline = [
        c for c in fake.calls if c[0] == "schema_rpc" and c[2] == "subgraph_for_pagerank"
    ]
    assert pagerank_calls_baseline, (
        "subgraph_for_pagerank must be called every score() (centrality is "
        f"query_class-independent), got {fake.calls!r}"
    )
    baseline_scores = {c.node_id: c.graph_score for c in baseline_candidates}

    # Boosted: query_class supplied → schema('rag').rpc('search_signal_weights', ...)
    fake2 = _Client(edges=edges, signal_weight_rows=signal_rows)
    boosted = [_candidate("node-1"), _candidate("node-2"), _candidate("node-3")]
    workspace_id = uuid4()
    await LocalizedPageRankScorer(supabase=fake2).score(
        user_id=workspace_id,
        candidates=boosted,
        query_class=QueryClass.MULTI_HOP,
    )
    signal_calls = [
        c for c in fake2.calls if c[0] == "schema_rpc" and c[2] == "search_signal_weights"
    ]
    assert signal_calls, "expected schema('rag').rpc(search_signal_weights) under query_class"
    # Every signal-weight RPC must hit the v2 schema + name + workspace_id binding.
    for kind, schema_name, rpc_name, params in signal_calls:
        assert schema_name == "rag"
        assert rpc_name == "search_signal_weights"
        assert params["p_workspace_id"] == str(workspace_id)
        assert params["p_query_class"] == "multi_hop"
        assert isinstance(params["p_target_chunk_ids"], list)
    # P1-1 lock-in: pagerank centrality RPC fires here too.
    assert [
        c for c in fake2.calls if c[0] == "schema_rpc" and c[2] == "subgraph_for_pagerank"
    ], "subgraph_for_pagerank must also be called when query_class is set"
    # Boost lifts node-3 above its PageRank-only baseline (sum weight 18 → +ve sigmoid bonus).
    boosted_scores = {c.node_id: c.graph_score for c in boosted}
    assert boosted_scores["node-3"] > baseline_scores["node-3"]
    assert boosted_scores["node-3"] - baseline_scores["node-3"] == pytest.approx(
        _expected_bonus(18.0), abs=1e-9,
    )


@pytest.mark.asyncio
async def test_score_with_no_signal_rows_preserves_baseline():
    """Empty RPC rows → bonus == sigmoid(0) - 0.05 == 0; baseline unchanged."""
    edges = [
        {"source_node_id": "node-1", "target_node_id": "node-2", "weight": 1.0},
        {"source_node_id": "node-2", "target_node_id": "node-3", "weight": 1.0},
    ]
    baseline = [_candidate("node-1"), _candidate("node-2"), _candidate("node-3")]
    await LocalizedPageRankScorer(supabase=_Client(edges=edges)).score(
        user_id=uuid4(), candidates=baseline,
    )
    base_scores = {c.node_id: c.graph_score for c in baseline}

    new = [_candidate("node-1"), _candidate("node-2"), _candidate("node-3")]
    await LocalizedPageRankScorer(supabase=_Client(edges=edges, signal_weight_rows=[])).score(
        user_id=uuid4(),
        candidates=new,
        query_class=QueryClass.LOOKUP,
    )
    new_scores = {c.node_id: c.graph_score for c in new}
    for node_id in base_scores:
        assert new_scores[node_id] == pytest.approx(base_scores[node_id])


@pytest.mark.asyncio
async def test_score_falls_back_gracefully_when_rpc_raises():
    """v1 identity preserved: RPC raises (e.g. PostgREST 5xx) → no crash, baseline preserved."""
    edges = [
        {"source_node_id": "node-1", "target_node_id": "node-2", "weight": 1.0},
        {"source_node_id": "node-2", "target_node_id": "node-3", "weight": 1.0},
    ]
    baseline = [_candidate("node-1"), _candidate("node-2"), _candidate("node-3")]
    await LocalizedPageRankScorer(supabase=_Client(edges=edges)).score(
        user_id=uuid4(), candidates=baseline,
    )
    base_scores = {c.node_id: c.graph_score for c in baseline}

    boom = RuntimeError("simulated postgrest 5xx")
    new = [_candidate("node-1"), _candidate("node-2"), _candidate("node-3")]
    fake = _Client(edges=edges, signal_raise=boom)
    # Must not raise.
    await LocalizedPageRankScorer(supabase=fake).score(
        user_id=uuid4(),
        candidates=new,
        query_class=QueryClass.MULTI_HOP,
    )
    new_scores = {c.node_id: c.graph_score for c in new}
    for node_id in base_scores:
        assert new_scores[node_id] == pytest.approx(base_scores[node_id])


@pytest.mark.asyncio
async def test_score_no_query_class_skips_signal_weight_lookup():
    """Backward compat: when query_class not passed, no search_signal_weights RPC fires.

    Post P1-1, the pagerank RPC (subgraph_for_pagerank) DOES fire every score()
    call regardless of query_class — centrality is unconditional. Only the
    usage-edge signal lookup is gated. We assert exactly that split.
    """
    edges = [
        {"source_node_id": "node-1", "target_node_id": "node-2", "weight": 1.0},
    ]
    candidates = [_candidate("node-1"), _candidate("node-2")]
    fake = _Client(edges=edges)
    await LocalizedPageRankScorer(supabase=fake).score(
        user_id=uuid4(), candidates=candidates,
    )
    assert candidates[0].graph_score is not None
    assert candidates[1].graph_score is not None
    # Centrality RPC fired (unconditional)...
    assert [
        c for c in fake.calls if c[0] == "schema_rpc" and c[2] == "subgraph_for_pagerank"
    ], "pagerank centrality RPC must run even without query_class"
    # ...but the usage-edge signal lookup did NOT (query_class-gated).
    assert [
        c for c in fake.calls if c[0] == "schema_rpc" and c[2] == "search_signal_weights"
    ] == []


# ---------------------------------------------------------------------------
# Phase D P2-5 — class-gated KG-aware proximity blend
#   graph_score = clamp01(0.7*pr_norm + 0.3*prox_norm) for MULTI_HOP/THEMATIC
#   pure pr_norm (byte-identical to pre-Phase-D) for every other class
# ---------------------------------------------------------------------------

import networkx as nx  # noqa: E402

from website.features.rag_pipeline.retrieval.graph_score import (  # noqa: E402
    _PROX_PR_W,
    _PROX_W,
)

# A deterministic 4-node subgraph: node-2 is the hub (degree 3), so its
# proximity (degree centrality) clearly diverges from pr_norm — proving the
# blend term is actually applied.
_PHASE_D_EDGES = [
    {"source_node_id": "node-1", "target_node_id": "node-2", "weight": 1.0},
    {"source_node_id": "node-2", "target_node_id": "node-3", "weight": 1.0},
    {"source_node_id": "node-2", "target_node_id": "node-4", "weight": 1.0},
]


class _PhaseDSchema:
    """schema('rag') mock that returns subgraph EDGES for the pagerank RPC and
    [] for search_signal_weights — exercises the real pagerank computation."""

    def __init__(self, calls, edges, raise_exc=None):
        self._calls = calls
        self._edges = edges
        self._raise = raise_exc

    def rpc(self, name, params):
        self._calls.append(("schema_rpc", "rag", name, params))
        if name == "subgraph_for_pagerank":
            return _Execute(self._edges, self._raise)
        return _Execute([], None)  # search_signal_weights -> no bonus


class _PhaseDClient:
    def __init__(self, *, edges=None, raise_exc=None):
        self.calls: list = []
        self._edges = edges or []
        self._raise = raise_exc

    def schema(self, name):
        self.calls.append(("schema", name))
        return _PhaseDSchema(self.calls, self._edges, self._raise)


def _pure_pr_norm(edges, node_ids):
    """Re-implement the EXACT pre-Phase-D formula for byte-identical asserts."""
    g = nx.Graph()
    g.add_nodes_from(node_ids)
    for e in edges:
        g.add_edge(e["source_node_id"], e["target_node_id"], weight=e.get("weight") or 1.0)
    pr = nx.pagerank(g, alpha=0.85, weight="weight")
    mx = max(pr.values()) or 1.0
    return {n: pr.get(n, 0.0) / mx for n in node_ids}


@pytest.mark.parametrize("gated_class", [QueryClass.MULTI_HOP, QueryClass.THEMATIC])
@pytest.mark.asyncio
async def test_phase_d_gated_classes_blend_proximity(gated_class):
    """MULTI_HOP / THEMATIC -> clamp01(0.7*pr + 0.3*prox); value in [0,1] and
    the hub node's score reflects the proximity term (differs from pure pr)."""
    node_ids = ["node-1", "node-2", "node-3", "node-4"]
    cands = [_candidate(n) for n in node_ids]
    fake = _PhaseDClient(edges=_PHASE_D_EDGES)
    await LocalizedPageRankScorer(supabase=fake).score(
        user_id=uuid4(), candidates=cands, query_class=gated_class,
    )
    pure = _pure_pr_norm(_PHASE_D_EDGES, node_ids)
    g = nx.Graph()
    g.add_nodes_from(node_ids)
    for e in _PHASE_D_EDGES:
        g.add_edge(e["source_node_id"], e["target_node_id"], weight=1.0)
    prox = nx.degree_centrality(g)
    mxp = max(prox.values()) or 1.0
    for c in cands:
        assert 0.0 <= c.graph_score <= 1.0
        expected = max(
            0.0,
            min(1.0, _PROX_PR_W * pure[c.node_id] + _PROX_W * (prox[c.node_id] / mxp)),
        )
        assert c.graph_score == pytest.approx(expected, abs=1e-9)
    # Blend genuinely differs from the pure-pr baseline for at least one node
    # whose normalized degree != normalized pagerank (a leaf like node-1: low
    # degree centrality but a non-trivial pr_norm — proves prox term applied).
    leaf = next(c for c in cands if c.node_id == "node-1")
    assert leaf.graph_score != pytest.approx(pure["node-1"], abs=1e-6)


@pytest.mark.parametrize(
    "ungated_class",
    [QueryClass.LOOKUP, QueryClass.VAGUE, QueryClass.STEP_BACK],
)
@pytest.mark.asyncio
async def test_phase_d_ungated_classes_byte_identical_pure_pr(ungated_class):
    """LOOKUP / VAGUE / STEP_BACK -> pure pr_norm, byte-identical to pre-Phase-D
    (no proximity term, no clamp divergence)."""
    node_ids = ["node-1", "node-2", "node-3", "node-4"]
    cands = [_candidate(n) for n in node_ids]
    fake = _PhaseDClient(edges=_PHASE_D_EDGES)
    await LocalizedPageRankScorer(supabase=fake).score(
        user_id=uuid4(), candidates=cands, query_class=ungated_class,
    )
    pure = _pure_pr_norm(_PHASE_D_EDGES, node_ids)
    for c in cands:
        # Exact equality with the pre-change formula (signal rows empty so the
        # usage bonus == sigmoid(0)-0.05 == 0.0 exactly, leaving pure pr_norm).
        assert c.graph_score == pytest.approx(pure[c.node_id], abs=1e-12)


@pytest.mark.asyncio
async def test_phase_d_no_extra_db_call_for_gated_classes():
    """Proximity reuses the in-memory subgraph: exactly ONE pagerank RPC, no
    extra retrieval round (same call shape as before Phase D)."""
    node_ids = ["node-1", "node-2", "node-3", "node-4"]
    cands = [_candidate(n) for n in node_ids]
    fake = _PhaseDClient(edges=_PHASE_D_EDGES)
    await LocalizedPageRankScorer(supabase=fake).score(
        user_id=uuid4(), candidates=cands, query_class=QueryClass.MULTI_HOP,
    )
    pagerank_calls = [
        c for c in fake.calls if c[0] == "schema_rpc" and c[2] == "subgraph_for_pagerank"
    ]
    assert len(pagerank_calls) == 1, (
        f"exactly one subgraph RPC expected (no extra DB call for proximity), "
        f"got {pagerank_calls!r}"
    )


@pytest.mark.asyncio
async def test_phase_d_cold_subgraph_degrades_to_zero_for_gated_class():
    """<2 candidates -> early 0.0 degrade contract preserved even for gated."""
    cands = [_candidate("only-node")]
    fake = _PhaseDClient(edges=[])
    await LocalizedPageRankScorer(supabase=fake).score(
        user_id=uuid4(), candidates=cands, query_class=QueryClass.THEMATIC,
    )
    assert cands[0].graph_score == 0.0


@pytest.mark.asyncio
async def test_phase_d_zero_edge_subgraph_degrades_to_zero_for_gated_class():
    """0-edge subgraph -> 0.0 (degrade contract) even for THEMATIC/MULTI_HOP."""
    cands = [_candidate("node-1"), _candidate("node-2")]
    fake = _PhaseDClient(edges=[])
    await LocalizedPageRankScorer(supabase=fake).score(
        user_id=uuid4(), candidates=cands, query_class=QueryClass.MULTI_HOP,
    )
    for c in cands:
        assert c.graph_score == 0.0


@pytest.mark.asyncio
async def test_phase_d_rpc_failure_degrades_to_zero_for_gated_class():
    """subgraph RPC raises -> 0.0 for gated class (failure contract intact)."""
    class _BoomClient(_Client):
        def rpc(self, name, params):  # unscoped path unused here
            raise RuntimeError("boom")

        def schema(self, name):
            self.calls.append(("schema", name))

            class _S:
                def rpc(_self, n, p):
                    self.calls.append(("schema_rpc", name, n, p))

                    class _E:
                        def execute(_e):
                            raise RuntimeError("simulated postgrest 5xx")

                    return _E()

            return _S()

    cands = [_candidate("node-1"), _candidate("node-2"), _candidate("node-3")]
    fake = _BoomClient(edges=_PHASE_D_EDGES)
    await LocalizedPageRankScorer(supabase=fake).score(
        user_id=uuid4(), candidates=cands, query_class=QueryClass.THEMATIC,
    )
    for c in cands:
        assert c.graph_score == 0.0


@pytest.mark.asyncio
async def test_score_caches_per_node_signal_weight_lookup():
    """Bonus cache: multiple chunk-candidates sharing a node_id → 1 RPC per unique node_id."""
    # 3 candidates, 2 unique node_ids → at most 2 signal-weight RPC calls.
    edges = [
        {"source_node_id": "node-1", "target_node_id": "node-2", "weight": 1.0},
    ]
    candidates = [
        _candidate("node-1"),
        _candidate("node-1"),  # duplicate node — must hit cache, not RPC.
        _candidate("node-2"),
    ]
    fake = _Client(edges=edges, signal_weight_rows=[])
    await LocalizedPageRankScorer(supabase=fake).score(
        user_id=uuid4(),
        candidates=candidates,
        query_class=QueryClass.THEMATIC,
    )
    # Filter to search_signal_weights only — the unconditional pagerank RPC
    # (subgraph_for_pagerank) also lands in fake.calls post P1-1 and must NOT
    # pollute the per-node cache-count assertion.
    signal_rpc_calls = [
        c for c in fake.calls if c[0] == "schema_rpc" and c[2] == "search_signal_weights"
    ]
    # Two unique node_ids ("node-1", "node-2") → exactly two RPC dispatches.
    assert len(signal_rpc_calls) == 2, (
        f"expected 2 unique-node signal RPCs, got {len(signal_rpc_calls)}: {signal_rpc_calls!r}"
    )
