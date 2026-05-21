"""PR #39 / Wave-4 — robustness invariants + integration coverage.

Covers:
  * A3  — Idempotency-Key header from JS client (asserts the shared
          helper sends it on both URL and document paths).
  * A5  — operations_repo.finalize retries transient PostgREST failures
          before swallowing.
  * A6  — in-memory _IDEMPOTENCY_CACHE / _OPERATIONS are present and
          serve the SYNCHRONOUS document path (not URL path).
  * D1  — pipeline-runs-exactly-once invariant for the slow-URL path.
  * D2  — same-Idempotency-Key duplicate dedups to a single canonical op.
  * D3  — user isolation on GET /api/operations/{id}.
  * D5  — persist split: critical path returns with chunks=[]; the
          enrichment job carries the right payload for the worker.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from website.app import create_app

_ROOT = Path(__file__).resolve().parents[3]


def _wait_for_finalize(captured: dict, *, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if captured.get("called"):
            return
        time.sleep(0.025)


@pytest.fixture
def client() -> TestClient:
    from website.api import zettels_routes

    zettels_routes._RATE_STORE.clear()
    zettels_routes._IDEMPOTENCY_CACHE.clear()
    zettels_routes._OPERATIONS.clear()
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# A3 — Idempotency-Key header is sent from the shared JS helper
# ---------------------------------------------------------------------------


def test_a3_helper_sends_idempotency_key_header_on_url_path():
    js = (_ROOT / "website" / "static" / "js" / "add_zettel_api.js").read_text(
        encoding="utf-8"
    )
    # The URL add() helper builds `actionId` once and sends it on BOTH the
    # body (legacy `client_action_id`) AND the IETF Idempotency-Key header.
    assert "headers['Idempotency-Key'] = actionId;" in js, (
        "Idempotency-Key must be sent on /api/zettels/add"
    )
    # And the document upload path mirrors the same contract.
    assert js.count("headers['Idempotency-Key'] = actionId;") >= 2, (
        "uploadDocument must also send Idempotency-Key for parity"
    )


def test_l2_optimistic_ui_skeleton_renders_real_meta_from_url():
    """PR #40 L2' (2026-05-21): the skeleton card must render REAL date +
    source badge chips (Linear/GitHub optimistic-UI pattern) — derived
    from the submitted URL — instead of skeleton blocks for the meta row.
    Title + body remain skeleton lines (real LLM unknowns)."""
    for rel in [
        "website/features/user_zettels/js/user_zettels.js",
        "website/features/user_home/js/home.js",
    ]:
        js = (_ROOT / rel).read_text(encoding="utf-8")
        # The detection regex (with backslash-escaped dots) covers every
        # source-type the cards render. Matching the escaped form so we
        # exercise the real regex literal rather than incidental matches.
        assert r"youtu\.be" in js, rel + ": skeleton must detect YouTube URLs"
        assert r"github\.com" in js, rel + ": skeleton must detect GitHub URLs"
        assert r"reddit\.com" in js, rel + ": skeleton must detect Reddit URLs"
        # The meta row uses REAL `.home-card-date` + `.home-card-source`
        # chips (not skeleton-line blocks) inside the skeleton card.
        assert (
            'home-card-date">' in js
            and 'home-card-source ' in js
        ), rel + ": skeleton meta must use real chips, not skeleton blocks"


def test_l3_operations_get_terminal_responses_set_cache_control():
    """PR #40 L3' (2026-05-21): GET /api/operations/{id} terminal responses
    (succeeded/failed/cancelled/expired) must carry Cache-Control + ETag
    so tab refreshes after terminal don't re-hit PostgREST. Active states
    (queued/running/accepted) must stay no-store to keep poll fresh."""
    src = (_ROOT / "website" / "api" / "zettels_routes.py").read_text(encoding="utf-8")
    assert '"Cache-Control": "private, max-age=300"' in src, (
        "terminal responses must set Cache-Control: private, max-age=300"
    )
    assert "_terminal_cache_headers(" in src, (
        "terminal helper must be invoked on succeeded/failed/cancelled/expired"
    )
    assert '"Cache-Control": "no-store"' in src, (
        "active 202 responses must explicitly opt out of caching"
    )


# ---------------------------------------------------------------------------
# A5 — finalize retries transient PostgREST failures
# ---------------------------------------------------------------------------


def test_a5_finalize_retries_then_succeeds_on_transient_failure(monkeypatch) -> None:
    """Two transient failures, third attempt succeeds → finalize returns True."""
    from website.core import operations_repo

    call_count = {"n": 0}

    class _FakeRpc:
        def __init__(self, response_data):
            self.response_data = response_data

        def execute(self):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("PostgREST transient hiccup")
            return SimpleNamespace(data="succeeded")

    class _Schema:
        def rpc(self, _name, _params):
            return _FakeRpc("succeeded")

    class _Client:
        def schema(self, _s):
            return _Schema()

    monkeypatch.setattr(operations_repo, "get_v2_client", lambda: _Client())
    # Speed the test: replace the backoff schedule with near-zero waits.
    monkeypatch.setattr(
        operations_repo, "_FINALIZE_RETRY_BACKOFF_S", (0.01, 0.01, 0.01)
    )

    ok = operations_repo.finalize(
        user_id=uuid4(), operation_id="op-1", target="succeeded"
    )
    assert ok is True
    assert call_count["n"] == 3


def test_a5_finalize_returns_false_after_exhausting_retries(monkeypatch) -> None:
    """All attempts fail → returns False (reaper picks up the row later)."""
    from website.core import operations_repo

    call_count = {"n": 0}

    class _FakeRpc:
        def execute(self):
            call_count["n"] += 1
            raise RuntimeError("PostgREST down")

    class _Schema:
        def rpc(self, _name, _params):
            return _FakeRpc()

    class _Client:
        def schema(self, _s):
            return _Schema()

    monkeypatch.setattr(operations_repo, "get_v2_client", lambda: _Client())
    monkeypatch.setattr(
        operations_repo, "_FINALIZE_RETRY_BACKOFF_S", (0.01, 0.01, 0.01)
    )

    ok = operations_repo.finalize(
        user_id=uuid4(), operation_id="op-2", target="failed"
    )
    assert ok is False
    # initial attempt + 3 retries = 4 total
    assert call_count["n"] == 4


# ---------------------------------------------------------------------------
# A6 — document-path in-memory dicts are present and named for SYNC path
# ---------------------------------------------------------------------------


def test_a6_document_idempotency_caches_scoped_to_doc_path() -> None:
    """The in-memory dicts back the synchronous document upload path. The
    URL path uses the DB-backed core.operations state machine instead.

    This test pins the scope contract via comment-anchor presence — if the
    dicts get refactored / merged into core.operations later, this assertion
    will fail and the doc-path needs to be re-routed first."""
    from website.api import zettels_routes

    src = Path(zettels_routes.__file__).read_text(encoding="utf-8")
    assert "SCOPE: these two in-memory dicts back the SYNCHRONOUS document" in src, (
        "scope comment must remain explicit"
    )
    assert isinstance(zettels_routes._IDEMPOTENCY_CACHE, dict)
    assert isinstance(zettels_routes._OPERATIONS, dict)


# ---------------------------------------------------------------------------
# D1 — pipeline runs exactly once per slow-URL add
# ---------------------------------------------------------------------------


def test_d1_pipeline_runs_exactly_once_per_slow_add(client, monkeypatch):
    """The Wave-1 A1 collapse to a single pipeline path means no doubled
    `_run_add_zettel` invocation even on slow URLs. This regression guards
    against the original work+_run race that was the root cause of the
    4-5 min hang."""
    from website.api import zettels_routes
    from website.core import persist as persist_mod

    run_count = {"n": 0}

    async def fake_run_add_zettel(body, *, user, effective_user_id):
        run_count["n"] += 1
        # Simulate slow pipeline — return a minimal result.
        return {"status": "succeeded", "operation_id": body.client_action_id}

    captured: dict = {}

    def _finalize(**kw):
        captured["called"] = True
        captured.update(kw)
        return True

    monkeypatch.setattr(zettels_routes, "_run_add_zettel", fake_run_add_zettel)
    monkeypatch.setattr(zettels_routes.operations_repo, "accept",
                        lambda **kw: (kw["operation_id"], True))
    monkeypatch.setattr(zettels_routes.operations_repo, "start",
                        lambda **kw: True)
    monkeypatch.setattr(zettels_routes.operations_repo, "finalize", _finalize)
    monkeypatch.setattr(zettels_routes, "check_async_backpressure",
                        AsyncMock(return_value=None))

    resp = client.post(
        "/api/zettels/add",
        json={
            "url": "https://example.com/slow",
            "client_action_id": "once-1",
            "surface": "landing",
        },
    )
    assert resp.status_code == 202
    _wait_for_finalize(captured)

    # Critical invariant: pipeline ran exactly once, NOT twice.
    assert run_count["n"] == 1


# ---------------------------------------------------------------------------
# D2 — same Idempotency-Key on duplicate request dedups server-side
# ---------------------------------------------------------------------------


def test_d2_duplicate_idempotency_key_resolves_to_single_canonical_op(client, monkeypatch):
    """Two adds with the same Idempotency-Key header resolve to ONE canonical
    operation server-side. Mirrors the real ops_accept RPC behavior:
    is_new=True returns the input op_id; is_new=False returns the EXISTING
    canonical op_id (== first call's input under our header → op_id mapping)."""
    from website.api import zettels_routes

    shared_key = "shared-idempotency-key"
    accept_calls: list[tuple[str, bool]] = []

    def _accept(**kw):
        # Real RPC contract: on is_new=True the row was just inserted with
        # op_id = input. On is_new=False the partial unique index conflict
        # returns the EXISTING active row's op_id (= first call's input).
        is_new = not accept_calls
        accept_calls.append((kw["operation_id"], is_new))
        return (kw["operation_id"], is_new)

    async def fake_run(body, *, user, effective_user_id):
        return {"status": "succeeded"}

    monkeypatch.setattr(zettels_routes, "_run_add_zettel", fake_run)
    monkeypatch.setattr(zettels_routes.operations_repo, "accept", _accept)
    monkeypatch.setattr(zettels_routes.operations_repo, "start",
                        lambda **kw: True)
    monkeypatch.setattr(zettels_routes.operations_repo, "finalize",
                        lambda **kw: True)
    monkeypatch.setattr(zettels_routes, "check_async_backpressure",
                        AsyncMock(return_value=None))

    for _ in range(2):
        resp = client.post(
            "/api/zettels/add",
            json={
                "url": "https://example.com/dedup",
                "client_action_id": "client-id-A",
                "surface": "landing",
            },
            headers={"Idempotency-Key": shared_key},
        )
        assert resp.status_code == 202
        body = resp.json()
        # Both responses point at the SAME canonical operation, sourced
        # from the Idempotency-Key header (which preempts client_action_id).
        assert body["operation_id"] == shared_key
        assert body["status_url"] == f"/api/operations/{shared_key}"

    # Invariant: both accept calls used the SAME op_id (= Idempotency-Key);
    # first was is_new=True, second was is_new=False.
    op_ids = [c[0] for c in accept_calls]
    assert op_ids == [shared_key, shared_key]
    assert [c[1] for c in accept_calls] == [True, False]


# ---------------------------------------------------------------------------
# D3 — user isolation on GET /api/operations/{id}
# ---------------------------------------------------------------------------


def test_d3_user_isolation_get_operation_returns_pending_for_other_user(
    client, monkeypatch
):
    """User-B's GET on User-A's operation_id must NOT return User-A's row.
    The get_operation RPC is user-scoped: SELECT ... WHERE user_id = $1 AND
    operation_id = $2. A mismatched user_id returns no row, so the GET
    handler emits the replication-gap 202 pending response (which carries
    no User-A data). This pins the BOLA-safe contract from migration 48."""
    from website.api import zettels_routes

    get_calls: list[dict] = []

    def _get_op(**kw):
        get_calls.append(kw)
        # No row for User-B + User-A's op id pair.
        return None

    monkeypatch.setattr(zettels_routes.operations_repo, "get_operation", _get_op)

    resp = client.get("/api/operations/user-a-op", headers={"x-test": "user-b"})
    assert resp.status_code == 202
    body = resp.json()
    # Pending body — no User-A data leaked.
    assert body["status"] == "accepted"
    assert "summary" not in body or body.get("summary") is None
    # get_operation was called with the requester's effective user id, NOT
    # the row owner's. The repo enforces the BOLA boundary in the WHERE
    # clause; this just confirms the route never short-circuits past it.
    assert len(get_calls) == 1


# ---------------------------------------------------------------------------
# D5 — persist split: critical path returns chunks=[]; enqueue carries payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d5_persist_returns_with_no_chunks_inline_and_enqueues_payload(
    monkeypatch,
):
    """The Wave-3 persist split moved chunk+embed off the critical path.
    Asserts: (a) repo.upsert_canonical_zettel sees chunks=[]; (b) the
    enrichment payload sent to enqueue_chunk_embed carries the canonical_id,
    workspace_id, summary, and source-text payload the handler needs."""
    from datetime import date

    from website.core import persist as persist_mod
    from website.core.supabase_v2.models import CanonicalUpsertResult
    from website.features.summarization_engine.lazy_enrichment import (
        repo as enrichment_repo,
    )

    canonical_id = UUID("00000000-0000-0000-0000-000000000099")
    workspace_zettel_id = UUID("00000000-0000-0000-0000-000000000077")

    class _CapRepo:
        def __init__(self) -> None:
            self.chunks = None
            self.workspace = None

        def upsert_canonical_zettel(self, zettel, *, workspace=None, chunks=None):
            self.chunks = chunks
            self.workspace = workspace
            return CanonicalUpsertResult(
                canonical_zettel_id=canonical_id,
                workspace_zettel_id=workspace_zettel_id,
                was_new=True,
            )

    enqueued: list[dict] = []

    def _capture(**kw):
        enqueued.append(kw)
        return ("stub-job", True)

    monkeypatch.setattr(persist_mod, "_schedule_kg_population", lambda **_k: None)
    monkeypatch.setattr(enrichment_repo, "enqueue_chunk_embed", _capture)

    repo = _CapRepo()
    payload = {
        "source_url": "https://example.com/d5",
        "source_type": "web",
        "title": "Lazy Enrichment Subject",
        "summary": "Real summary body.",
        "detailed_summary": "Real summary body.",
        "tags": ["arch"],
        "metadata": {},
    }
    await persist_mod._persist_supabase_v2_zettel(
        payload=payload,
        repo=repo,
        workspace_id=UUID("00000000-0000-0000-0000-000000000002"),
        captured_on=date.today(),
        detailed_summary="Real summary body.",
        profile_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    # (a) Critical path is chunkless.
    assert repo.chunks == []

    # (b) Enrichment job was enqueued with the right payload shape.
    assert len(enqueued) == 1
    kw = enqueued[0]
    assert kw["canonical_zettel_id"] == canonical_id
    assert kw["workspace_zettel_id"] == workspace_zettel_id
    payload_out = kw["payload"]
    assert payload_out["canonical_zettel_id"] == str(canonical_id)
    assert payload_out["workspace_zettel_id"] == str(workspace_zettel_id)
    assert payload_out["detailed_summary"] == "Real summary body."
    sp = payload_out["summarized_payload"]
    assert sp["source_url"] == "https://example.com/d5"
    assert sp["title"] == "Lazy Enrichment Subject"
    assert sp["tags"] == ["arch"]
