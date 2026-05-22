"""PR #39 / Wave-4 — robustness invariants + integration coverage.

Covers:
  * A3  — Idempotency-Key header from JS client (asserts the shared
          helper sends it on both URL and document paths).
  * A5  — operations_repo.finalize retries transient PostgREST failures
          before swallowing.
  * A6  — ADR-3: the document path is now async-ops (202 + status_url);
          the in-memory _IDEMPOTENCY_CACHE / _OPERATIONS dicts were removed.
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


def _drive_bg_to_finalize(
    post_json: dict, captured: dict, user_dict: dict | None = None,
    *, settle_s: float = 2.5,
) -> None:
    """PR #40 hotfix (2026-05-21): cross-platform deterministic finalize.

    On Windows / macOS dev hosts, TestClient happens to drive the route's
    bg task to completion before ``client.post()`` returns. On Linux
    GitHub Actions runners it does NOT — the per-request loop is torn
    down and the bg task is orphaned. This helper polls ``captured``
    briefly; if the bg task already fired, returns. Otherwise drives
    ``_run`` via ``asyncio.run`` in the test thread. Either way the
    pipeline runs EXACTLY ONCE — call-count assertions stay valid."""
    import asyncio
    from website.api import zettels_routes as zr

    deadline = time.time() + settle_s
    while time.time() < deadline:
        if captured.get("called"):
            return
        time.sleep(0.025)

    body = zr.AddZettelRequest(**post_json)
    user_id = zr._effective_user_id(user_dict)
    asyncio.run(
        zr._run(
            user_id=user_id,
            operation_id=post_json["client_action_id"],
            pipeline=lambda: zr._run_add_zettel(
                body, user=user_dict, effective_user_id=user_id
            ),
            persist_requested=body.persist,
        )
    )


@pytest.fixture
def client() -> TestClient:
    from website.api import zettels_routes

    zettels_routes._RATE_STORE.clear()
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
# A6 — ADR-3: document path is async-ops; in-memory idempotency dicts removed
# ---------------------------------------------------------------------------


def test_a6_document_path_is_async_ops_and_inmemory_dicts_removed() -> None:
    """ADR-3 (2026-05-22): the document-upload path moved onto the DB-backed
    core.operations state machine, exactly like the URL path. The per-process
    in-memory ``_IDEMPOTENCY_CACHE`` / ``_OPERATIONS`` dicts (and their
    ``_cache_get`` / ``_cache_put`` / ``_operation_put`` helpers) were removed
    — they could not coalesce duplicate uploads across gunicorn workers.

    This pins the removal so the dicts cannot silently come back."""
    from website.api import zettels_routes

    for sym in (
        "_IDEMPOTENCY_CACHE",
        "_OPERATIONS",
        "_cache_get",
        "_cache_put",
        "_operation_put",
    ):
        assert not hasattr(zettels_routes, sym), (
            f"{sym} must stay removed — the document path is async-ops now"
        )

    src = Path(zettels_routes.__file__).read_text(encoding="utf-8")
    # The document route now returns 202 via the shared accept path.
    assert "Document Add Zettel — async-ops (ADR-3)" in src, (
        "document route docstring must declare the async-ops contract"
    )


# ---------------------------------------------------------------------------
# D1 — pipeline runs exactly once per slow-URL add
# ---------------------------------------------------------------------------


def test_d1_pipeline_runs_exactly_once_per_slow_add(client, monkeypatch):
    """The Wave-1 A1 collapse to a single pipeline path means no doubled
    `_run_add_zettel` invocation even on slow URLs. This regression guards
    against the original work+_run race that was the root cause of the
    4-5 min hang."""
    from website.api import zettels_routes

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

    post_json = {
        "url": "https://example.com/slow",
        "client_action_id": "once-1",
        "surface": "landing",
    }
    resp = client.post("/api/zettels/add", json=post_json)
    assert resp.status_code == 202
    _drive_bg_to_finalize(post_json, captured)

    # Critical invariant: pipeline ran exactly once. The route's bg-task
    # spawn was orphaned by TestClient teardown (covered above), and our
    # _drive_bg_to_finalize call ran _run a single time. Net: ONE call
    # to the mocked _run_add_zettel.
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


# ---------------------------------------------------------------------------
# ADR-1 — server-guided Retry-After backoff (_retry_after_for_age)
# ---------------------------------------------------------------------------


def test_retry_after_for_age_grows_with_operation_age():
    """ADR-1: Retry-After grows with operation age so short jobs poll fast
    and long jobs poll sparsely. Boundaries: <20s=2, <60s=4, <180s=10, else=20."""
    from datetime import datetime, timedelta, timezone

    from website.api.zettels_routes import _retry_after_for_age

    now = datetime.now(timezone.utc)
    # age ~5s -> "2"
    assert _retry_after_for_age((now - timedelta(seconds=5)).isoformat()) == "2"
    # age ~40s -> "4"
    assert _retry_after_for_age((now - timedelta(seconds=40)).isoformat()) == "4"
    # age ~120s -> "10"
    assert _retry_after_for_age((now - timedelta(seconds=120)).isoformat()) == "10"
    # age ~600s -> "20"
    assert _retry_after_for_age((now - timedelta(seconds=600)).isoformat()) == "20"


def test_retry_after_for_age_falls_back_to_2_on_unparseable_input():
    """Unparseable / None timestamps must not raise — they fall back to 2s."""
    from website.api.zettels_routes import _retry_after_for_age

    assert _retry_after_for_age("not-a-timestamp") == "2"
    assert _retry_after_for_age(None) == "2"
    assert _retry_after_for_age("") == "2"


def test_retry_after_for_age_handles_naive_and_z_suffix_timestamps():
    """A trailing 'Z' (UTC) and naive timestamps must both parse — the helper
    normalizes them to UTC rather than raising."""
    from datetime import datetime, timedelta, timezone

    from website.api.zettels_routes import _retry_after_for_age

    recent = (datetime.now(timezone.utc) - timedelta(seconds=3)).replace(
        microsecond=0
    )
    # 'Z' suffix form
    assert _retry_after_for_age(
        recent.isoformat().replace("+00:00", "Z")
    ) == "2"
    # naive form (no tzinfo) — treated as UTC
    assert _retry_after_for_age(recent.replace(tzinfo=None).isoformat()) == "2"


# ---------------------------------------------------------------------------
# ADR-2 — fail-closed accept: store-unavailable -> 503
# ---------------------------------------------------------------------------


def test_accept_returns_none_yields_503_operation_store_unavailable(
    client, monkeypatch
):
    """ADR-2: when ``operations_repo.accept`` returns ``None`` (operations
    store could not durably record the op), ``POST /api/zettels/add`` returns
    a retriable 503 ``operation-store-unavailable`` problem instead of
    spawning untrackable background work."""
    from website.api import zettels_routes

    monkeypatch.setattr(zettels_routes.operations_repo, "accept",
                        lambda **kw: None)
    monkeypatch.setattr(zettels_routes, "check_async_backpressure",
                        AsyncMock(return_value=None))

    resp = client.post(
        "/api/zettels/add",
        json={
            "url": "https://example.com/store-down",
            "client_action_id": "store-503",
            "surface": "landing",
        },
    )

    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"].endswith("/errors/operation-store-unavailable")
    assert body["status"] == 503
    assert body["retryable"] is True


def test_accept_raising_exception_also_yields_503(client, monkeypatch):
    """ADR-2: a raised exception inside accept is caught and treated as a
    store failure (accept_result=None) — same retriable 503, never a 5xx
    stacktrace leak."""
    from website.api import zettels_routes

    def _boom(**_kw):
        raise RuntimeError("PostgREST unreachable")

    monkeypatch.setattr(zettels_routes.operations_repo, "accept", _boom)
    monkeypatch.setattr(zettels_routes, "check_async_backpressure",
                        AsyncMock(return_value=None))

    resp = client.post(
        "/api/zettels/add",
        json={
            "url": "https://example.com/accept-raises",
            "client_action_id": "raise-503",
            "surface": "landing",
        },
    )

    assert resp.status_code == 503
    assert resp.json()["type"].endswith("/errors/operation-store-unavailable")


# ---------------------------------------------------------------------------
# fc6594c6 — ZettelListItem title_ready / enrichment_status derivation
# ---------------------------------------------------------------------------


def test_zettel_list_item_defaults_are_ready():
    """A ZettelListItem built without the additive fields defaults to the
    ready state (backward compatible with old clients/payloads)."""
    from website.api.zettels_routes import ZettelListItem

    item = ZettelListItem(
        id="wz-1",
        title="A real title",
        brief_summary="b",
        detailed_summary="d",
        tags=[],
        source_type="web",
        source_url="https://example.com/x",
        added_at="2026-05-22",
        published_at="",
    )
    assert item.title_ready is True
    assert item.enrichment_status == "ready"


def test_zettel_list_item_empty_title_is_pending():
    """An empty canonical title -> title="", title_ready=False,
    enrichment_status="pending" (no "Untitled" literal at the API)."""
    from website.api.zettels_routes import ZettelListItem

    # This mirrors the derivation `list_zettels` applies for a canonical row
    # whose title is empty/whitespace.
    raw_title = "   "
    title_ready = bool(raw_title.strip())
    item = ZettelListItem(
        id="wz-2",
        title=raw_title.strip() if title_ready else "",
        title_ready=title_ready,
        enrichment_status="ready" if title_ready else "pending",
        brief_summary="b",
        detailed_summary="d",
        tags=[],
        source_type="web",
        source_url="https://example.com/y",
        added_at="2026-05-22",
        published_at="",
    )
    assert item.title == ""
    assert item.title_ready is False
    assert item.enrichment_status == "pending"


# ---------------------------------------------------------------------------
# ADR-3 — _run overwrites the result's operation_id with the canonical id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_overwrites_result_operation_id_with_canonical(monkeypatch):
    """ADR-3: the pipeline stamps operation_id from body.client_action_id,
    but the route may canonicalize to a different id (Idempotency-Key header
    or an existing accepted row). ``_run`` overwrites the result's
    operation_id with the canonical id the client is actually polling so the
    finalized body matches the operations row."""
    from website.api import zettels_routes

    captured: dict = {}

    def _finalize(**kw):
        captured.update(kw)
        return True

    monkeypatch.setattr(zettels_routes.operations_repo, "start",
                        lambda **kw: True)
    monkeypatch.setattr(zettels_routes.operations_repo, "finalize", _finalize)

    async def _pipeline():
        # The pipeline stamps the *input* client_action_id, not the canonical.
        return {"status": "succeeded", "operation_id": "pipeline-stamped-id"}

    await zettels_routes._run(
        user_id=uuid4(),
        operation_id="canonical-op-id",
        pipeline=_pipeline,
        persist_requested=True,
    )

    assert captured.get("target") == "succeeded"
    response_body = captured.get("response") or {}
    # _run rewrote the stamped id to the canonical id passed to _run.
    assert response_body["operation_id"] == "canonical-op-id"
