"""rag_eval_v2 harness wiring tests — pure functions + lazy-import wiring.

No live Supabase / LLM / Playwright. The orchestrator, EvalRunner, repos and
v2 client are mocked; rag_pipeline imports are lazy (inside run()), so the
module file loads without pulling the pipeline.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[3]


# ── env bootstrap ──────────────────────────────────────────────────────────


def test_bootstrap_env_pins_model_dir_to_worktree(run_eval_v2, monkeypatch):
    monkeypatch.delenv("RAG_MODEL_DIR", raising=False)
    run_eval_v2.bootstrap_env()
    expected = str(ROOT / "models")
    assert os.environ["RAG_MODEL_DIR"] == expected
    assert os.environ["DB_SCHEMA_VERSION"] == "v2"
    assert str(ROOT) in sys.path


def test_bootstrap_env_forces_model_dir_even_if_preset(run_eval_v2, monkeypatch):
    # Brief: RAG_MODEL_DIR must point at the worktree models/ — a stale
    # pre-set value (e.g. /app/models from a prior import) must be overridden.
    monkeypatch.setenv("RAG_MODEL_DIR", "/app/models")
    run_eval_v2.bootstrap_env()
    assert os.environ["RAG_MODEL_DIR"] == str(ROOT / "models")


# ── expected-citation resolution (title substring -> zettel id) ────────────


def test_resolve_expected_str_and_list(run_eval_v2):
    t2z = {
        "The Strangest Drug Ever Studied": "z-strange",
        "Science of Micro-dosing": "z-micro",
    }
    assert run_eval_v2._resolve_expected("Strangest Drug", t2z) == ["z-strange"]
    assert run_eval_v2._resolve_expected(
        ["micro-dosing", "Strangest Drug"], t2z
    ) == ["z-micro", "z-strange"]
    # refusal query: empty expected -> empty list (NOT a crash)
    assert run_eval_v2._resolve_expected([], t2z) == []
    assert run_eval_v2._resolve_expected(None, t2z) == []
    # unmatched needle dropped, not raised
    assert run_eval_v2._resolve_expected("nonexistent topic", t2z) == []


# ── chunk_id -> canonical_zettel_id remap (the load-bearing step) ──────────


def test_build_chunk_to_zettel(run_eval_v2):
    by_zettel = {
        "zA": [{"chunk_id": "c1", "chunk_idx": 0, "content": "x"},
               {"chunk_id": "c2", "chunk_idx": 1, "content": "y"}],
        "zB": [{"chunk_id": "c3", "chunk_idx": 0, "content": "z"}],
    }
    m = run_eval_v2._build_chunk_to_zettel(by_zettel)
    assert m == {"c1": "zA", "c2": "zA", "c3": "zB"}


def test_build_answer_record_remaps_chunk_ids_and_builds_contexts(run_eval_v2):
    # AnswerTurn.retrieved_node_ids / Citation.node_id are CHUNK uuids.
    # The record must come back keyed by canonical_zettel_id.
    cite = types.SimpleNamespace(node_id="c1", snippet="snippet one")
    turn = types.SimpleNamespace(
        content="the answer",
        citations=[cite],
        retrieved_node_ids=["c1", "c2", "c9_unknown"],
        query_class=types.SimpleNamespace(value="lookup"),
        critic_verdict="supported",
        latency_ms=1234,
    )
    chunk_to_zettel = {"c1": "zA", "c2": "zB"}  # c9_unknown intentionally absent
    by_zettel = {
        "zA": [{"chunk_id": "c1", "chunk_idx": 0, "content": "alpha body"}],
        "zB": [{"chunk_id": "c2", "chunk_idx": 0, "content": "beta body"}],
    }
    rec = run_eval_v2._build_answer_record(
        turn, chunk_to_zettel=chunk_to_zettel, by_zettel=by_zettel
    )
    # remapped to zettel ids, unknown chunk dropped, order/dedup preserved
    assert rec["retrieved_node_ids"] == ["zA", "zB"]
    assert rec["reranked_node_ids"] == ["zA", "zB"]
    assert rec["citations"] == [{"node_id": "zA", "title": ""}]
    # contexts populated (snippet + backfilled chunk text) — never empty
    assert rec["contexts"]
    assert "snippet one" in rec["contexts"]
    assert rec["_meta"]["primary_citation"] == "zA"
    assert rec["_meta"]["query_class"] == "lookup"


def test_build_answer_record_empty_citations_still_has_contexts(run_eval_v2):
    turn = types.SimpleNamespace(
        content="ans", citations=[],
        retrieved_node_ids=["c1"],
        query_class=types.SimpleNamespace(value="vague"),
        critic_verdict="partial", latency_ms=10,
    )
    rec = run_eval_v2._build_answer_record(
        turn,
        chunk_to_zettel={"c1": "zA"},
        by_zettel={"zA": [{"chunk_id": "c1", "chunk_idx": 0, "content": "body text"}]},
    )
    assert rec["contexts"] == ["body text"]
    assert rec["_meta"]["primary_citation"] is None


# ── member resolution shape ────────────────────────────────────────────────


def test_resolve_members_maps_rpc_rows(run_eval_v2):
    rag_repo = MagicMock()
    rag_repo.list_kasten_zettels.return_value = [
        {"canonical_zettel_id": "z1", "workspace_zettel_id": "w1",
         "title": "  Title One  ", "source_type": "youtube"},
        {"canonical_zettel_id": None, "workspace_zettel_id": "w2",
         "title": "skip me", "source_type": "web"},  # no canonical -> dropped
    ]
    out = run_eval_v2._resolve_members(rag_repo, "kid")
    assert out == [{
        "canonical_zettel_id": "z1", "workspace_zettel_id": "w1",
        "title": "Title One", "source_type": "youtube",
    }]


def test_fetch_chunks_batches_and_sorts(run_eval_v2):
    client = MagicMock()
    resp = MagicMock()
    resp.data = [
        {"id": "c2", "canonical_zettel_id": "zA", "chunk_idx": 1, "content": "second"},
        {"id": "c1", "canonical_zettel_id": "zA", "chunk_idx": 0, "content": "first"},
    ]
    client.schema.return_value.table.return_value.select.return_value.in_.return_value.execute.return_value = resp
    by = run_eval_v2._fetch_chunks_for_zettels(client, ["zA"])
    assert [c["chunk_idx"] for c in by["zA"]] == [0, 1]  # sorted by chunk_idx


def test_fetch_chunks_empty_input_no_db_call(run_eval_v2):
    client = MagicMock()
    assert run_eval_v2._fetch_chunks_for_zettels(client, []) == {}
    client.schema.assert_not_called()


# ── settle/poll ────────────────────────────────────────────────────────────


def test_settle_returns_immediately_when_all_have_chunks(run_eval_v2, monkeypatch):
    monkeypatch.setattr(
        run_eval_v2, "_fetch_chunks_for_zettels",
        lambda client, ids: {z: [{"chunk_id": "c", "chunk_idx": 0, "content": "x"}] for z in ids},
    )
    slept = []
    monkeypatch.setattr(run_eval_v2.time, "sleep", lambda s: slept.append(s))
    have = run_eval_v2._settle(MagicMock(), ["z1", "z2"], settle_seconds=30)
    assert have == 2
    assert slept == []  # no polling needed


def test_settle_times_out_without_infinite_loop(run_eval_v2, monkeypatch):
    monkeypatch.setattr(
        run_eval_v2, "_fetch_chunks_for_zettels",
        lambda client, ids: {z: [] for z in ids},  # never ready
    )
    monkeypatch.setattr(run_eval_v2.time, "sleep", lambda s: None)
    t = {"v": 0.0}
    monkeypatch.setattr(run_eval_v2.time, "monotonic", lambda: t.__setitem__("v", t["v"] + 5) or t["v"])
    have = run_eval_v2._settle(MagicMock(), ["z1"], settle_seconds=10)
    assert have == 0  # timed out, did not hang


# ── scope_filter wiring: sandbox_id is the real scope ──────────────────────


@pytest.mark.asyncio
async def test_answer_one_passes_sandbox_id_and_scope_filter(run_eval_v2, monkeypatch):
    """The brief's grounded fact says scope via scope_filter.node_ids; the
    verified code scopes via ChatQuery.sandbox_id (the node_ids knob is
    retired). The harness MUST set sandbox_id (real) AND node_ids (harmless)."""
    from uuid import UUID

    captured = {}

    class _Orch:
        async def answer(self, *, query, user_id):
            captured["query"] = query
            captured["user_id"] = user_id
            return "TURN"

    kid = UUID("11111111-1111-1111-1111-111111111111")
    uid = UUID("22222222-2222-2222-2222-222222222222")
    out = await run_eval_v2._answer_one(
        _Orch(), text="q?", kasten_id=kid,
        member_zettel_ids=["zA", "zB"], user_uuid=uid,
    )
    assert out == "TURN"
    q = captured["query"]
    assert q.sandbox_id == kid           # REAL scoping mechanism
    assert q.scope_filter.node_ids == ["zA", "zB"]  # belt-and-suspenders
    assert q.quality == "fast"
    assert q.stream is False
    assert captured["user_id"] == uid
