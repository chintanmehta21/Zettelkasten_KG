"""Unit tests for the lazy-enrichment subsystem (PR #39 Wave-3).

Covers:
  * `repo.enqueue_chunk_embed` — defensive shape on RPC success / failure.
  * `repo.claim_next` / `repo.finalize` / `repo.requeue` — scalar decoders.
  * `worker._process_one` — handler dispatch, retry/dead-letter routing,
    unknown-kind dead-lettering.
  * `worker.is_disabled` — env-var gate.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from website.features.summarization_engine.lazy_enrichment import repo, worker
from website.features.summarization_engine.lazy_enrichment.handlers import chunk_embed


# ---------------------------------------------------------------------------
# repo helpers
# ---------------------------------------------------------------------------


class _FakeRpc:
    def __init__(self, data: Any = None, raises: Exception | None = None) -> None:
        self.data = data
        self.raises = raises
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name: str, params: dict) -> "_FakeRpc":
        self.calls.append((name, params))
        return self

    def execute(self) -> SimpleNamespace:
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(data=self.data)


class _FakeSchemaClient:
    def __init__(self, rpc: _FakeRpc) -> None:
        self._rpc = rpc

    def schema(self, _name: str) -> "_FakeSchemaClient":
        return self

    def rpc(self, name: str, params: dict) -> _FakeRpc:
        return self._rpc(name, params)


def _patch_client(monkeypatch, rpc: _FakeRpc) -> None:
    monkeypatch.setattr(
        "website.features.summarization_engine.lazy_enrichment.repo.get_v2_client",
        lambda: _FakeSchemaClient(rpc),
    )


# ---------------------------------------------------------------------------
# enqueue_chunk_embed
# ---------------------------------------------------------------------------


def test_enqueue_chunk_embed_returns_new_job_id(monkeypatch) -> None:
    job_id = str(uuid4())
    rpc = _FakeRpc(data=[{"job_id": job_id, "status": "queued", "is_new": True}])
    _patch_client(monkeypatch, rpc)

    canonical = uuid4()
    workspace = uuid4()
    out, is_new = repo.enqueue_chunk_embed(
        user_id=uuid4(),
        canonical_zettel_id=canonical,
        workspace_zettel_id=workspace,
        payload={"detailed_summary": "x"},
    )
    assert out == job_id
    assert is_new is True
    name, params = rpc.calls[0]
    assert name == "enrich_enqueue"
    assert params["p_kind"] == repo.KIND_CHUNK_EMBED
    assert params["p_canonical_zettel_id"] == str(canonical)
    assert params["p_workspace_zettel_id"] == str(workspace)


def test_enqueue_chunk_embed_duplicate_returns_is_new_false(monkeypatch) -> None:
    job_id = str(uuid4())
    rpc = _FakeRpc(data=[{"job_id": job_id, "status": "running", "is_new": False}])
    _patch_client(monkeypatch, rpc)

    out, is_new = repo.enqueue_chunk_embed(
        user_id=uuid4(),
        canonical_zettel_id=uuid4(),
        workspace_zettel_id=None,
        payload={},
    )
    assert out == job_id
    assert is_new is False


def test_enqueue_chunk_embed_fails_open_on_exception(monkeypatch) -> None:
    """Critical invariant: enqueue failure must NEVER 5xx Add Zettel."""
    rpc = _FakeRpc(raises=RuntimeError("PostgREST down"))
    _patch_client(monkeypatch, rpc)

    out, is_new = repo.enqueue_chunk_embed(
        user_id=uuid4(),
        canonical_zettel_id=uuid4(),
        workspace_zettel_id=None,
        payload={},
    )
    assert out is None
    assert is_new is False


# ---------------------------------------------------------------------------
# claim_next / finalize / requeue
# ---------------------------------------------------------------------------


def test_claim_next_returns_row_dict(monkeypatch) -> None:
    job_id = str(uuid4())
    row = {
        "job_id": job_id,
        "user_id": str(uuid4()),
        "canonical_zettel_id": str(uuid4()),
        "workspace_zettel_id": None,
        "kind": "chunk_embed",
        "payload": {"detailed_summary": "x"},
        "attempts": 1,
        "max_attempts": 3,
    }
    rpc = _FakeRpc(data=[row])
    _patch_client(monkeypatch, rpc)

    out = repo.claim_next()
    assert out is not None
    assert out["job_id"] == job_id
    assert out["payload"] == {"detailed_summary": "x"}


def test_claim_next_returns_none_on_empty_queue(monkeypatch) -> None:
    rpc = _FakeRpc(data=[])
    _patch_client(monkeypatch, rpc)
    assert repo.claim_next() is None


def test_finalize_decodes_scalar_returning(monkeypatch) -> None:
    rpc = _FakeRpc(data="succeeded")
    _patch_client(monkeypatch, rpc)
    assert repo.finalize(job_id=str(uuid4()), target="succeeded") is True

    rpc2 = _FakeRpc(data=None)
    _patch_client(monkeypatch, rpc2)
    assert repo.finalize(job_id=str(uuid4()), target="succeeded") is False


def test_finalize_rejects_bad_target() -> None:
    with pytest.raises(ValueError):
        repo.finalize(job_id="x", target="completed")


def test_requeue_returns_new_status(monkeypatch) -> None:
    rpc = _FakeRpc(data="queued")
    _patch_client(monkeypatch, rpc)
    assert repo.requeue(job_id=str(uuid4())) == "queued"


def test_requeue_returns_dead_letter_on_attempts_exhausted(monkeypatch) -> None:
    rpc = _FakeRpc(data="dead_letter")
    _patch_client(monkeypatch, rpc)
    assert repo.requeue(job_id=str(uuid4())) == "dead_letter"


# ---------------------------------------------------------------------------
# worker._process_one — handler dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_one_dispatches_known_kind_and_finalizes(monkeypatch) -> None:
    finalize_calls: list[dict] = []

    monkeypatch.setattr(
        repo, "finalize", lambda **kw: finalize_calls.append(kw) or True
    )

    async def fake_handler(_payload: dict) -> None:
        return None

    monkeypatch.setitem(worker._HANDLERS, repo.KIND_CHUNK_EMBED, fake_handler)

    job = {
        "job_id": str(uuid4()),
        "kind": repo.KIND_CHUNK_EMBED,
        "payload": {},
        "attempts": 1,
        "max_attempts": 3,
    }
    await worker._process_one(job)

    assert len(finalize_calls) == 1
    assert finalize_calls[0]["target"] == "succeeded"


@pytest.mark.asyncio
async def test_process_one_unknown_kind_dead_letters(monkeypatch) -> None:
    finalize_calls: list[dict] = []
    monkeypatch.setattr(
        repo, "finalize", lambda **kw: finalize_calls.append(kw) or True
    )

    job = {
        "job_id": str(uuid4()),
        "kind": "never-heard-of-this-kind",
        "payload": {},
        "attempts": 1,
        "max_attempts": 3,
    }
    await worker._process_one(job)
    assert finalize_calls[0]["target"] == "dead_letter"


@pytest.mark.asyncio
async def test_process_one_handler_error_requeues_if_attempts_remain(monkeypatch) -> None:
    requeue_calls: list[dict] = []
    finalize_calls: list[dict] = []
    monkeypatch.setattr(repo, "requeue", lambda **kw: requeue_calls.append(kw) or "queued")
    monkeypatch.setattr(repo, "finalize", lambda **kw: finalize_calls.append(kw) or True)

    async def raising_handler(_payload: dict) -> None:
        raise RuntimeError("Gemini blew up")

    monkeypatch.setitem(worker._HANDLERS, repo.KIND_CHUNK_EMBED, raising_handler)

    job = {
        "job_id": str(uuid4()),
        "kind": repo.KIND_CHUNK_EMBED,
        "payload": {},
        "attempts": 1,
        "max_attempts": 3,
    }
    await worker._process_one(job)

    assert len(requeue_calls) == 1
    assert len(finalize_calls) == 0  # not yet dead-lettered


@pytest.mark.asyncio
async def test_process_one_handler_error_dead_letters_on_exhausted_attempts(monkeypatch) -> None:
    finalize_calls: list[dict] = []
    monkeypatch.setattr(repo, "requeue", lambda **kw: pytest.fail("should not requeue"))
    monkeypatch.setattr(repo, "finalize", lambda **kw: finalize_calls.append(kw) or True)

    async def raising_handler(_payload: dict) -> None:
        raise RuntimeError("Gemini blew up forever")

    monkeypatch.setitem(worker._HANDLERS, repo.KIND_CHUNK_EMBED, raising_handler)

    job = {
        "job_id": str(uuid4()),
        "kind": repo.KIND_CHUNK_EMBED,
        "payload": {},
        "attempts": 3,  # at the limit
        "max_attempts": 3,
    }
    await worker._process_one(job)

    assert finalize_calls[0]["target"] == "dead_letter"


# ---------------------------------------------------------------------------
# worker.is_disabled
# ---------------------------------------------------------------------------


def test_is_disabled_honors_env(monkeypatch) -> None:
    monkeypatch.setenv("ZK_LAZY_ENRICHMENT_DISABLED", "1")
    assert worker.is_disabled() is True
    monkeypatch.setenv("ZK_LAZY_ENRICHMENT_DISABLED", "off")
    assert worker.is_disabled() is False
    monkeypatch.delenv("ZK_LAZY_ENRICHMENT_DISABLED", raising=False)
    assert worker.is_disabled() is False


# ---------------------------------------------------------------------------
# chunk_embed handler input guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_embed_handler_requires_canonical_id() -> None:
    with pytest.raises(ValueError):
        await chunk_embed.handle({"detailed_summary": "x"})
