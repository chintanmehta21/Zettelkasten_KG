"""Each document-failure scenario fires a DISTINCT #app-errors alert.

`DocumentUploadError` subclasses ValueError, which the async-ops `_run` worker
normally SUPPRESSES from #app-errors (4xx business errors). This contract
guarantees document failures are the deliberate exception: every scenario
fires `maybe_fire_app_error` with a per-scenario `dedup_key`
(`add_zettel_document:<ErrorClass>`) so the channel shows WHICH scenario.

Recoverable modes (NoTextLayerError / GarbageTextError) only reach `_run` when
vision recovery ALSO failed — i.e. the terminal outcome — which is exactly when
an alert is warranted.
"""

import uuid

import pytest

from website.api import zettels_routes as zr
import website.features.web_monitor as wm
from website.features.summarization_engine.source_ingest.document import (
    CorruptDocumentError,
    DocumentTooComplexError,
    DocumentUploadError,
    EncryptedDocumentError,
    GarbageTextError,
    NoTextLayerError,
)

SCENARIOS = [
    EncryptedDocumentError,
    NoTextLayerError,
    GarbageTextError,
    CorruptDocumentError,
    DocumentTooComplexError,
    DocumentUploadError,
]


async def _drive(exc_cls, monkeypatch):
    """Run `_run` with a pipeline that raises `exc_cls`; capture alert calls."""
    calls: list[dict] = []
    monkeypatch.setattr(wm, "maybe_fire_app_error", lambda **kw: calls.append(kw) or True)
    # No-op the durable state transitions (run in a thread via asyncio.to_thread).
    monkeypatch.setattr(zr.operations_repo, "start", lambda **kw: True)
    monkeypatch.setattr(zr.operations_repo, "finalize", lambda **kw: True)

    async def _boom(_e=exc_cls):
        raise _e("scenario boom")

    await zr._run(
        user_id=uuid.uuid4(),
        operation_id=f"op-{exc_cls.__name__}",
        pipeline=_boom,
        persist_requested=False,
    )
    return calls


@pytest.mark.parametrize("exc_cls", SCENARIOS, ids=lambda c: c.__name__)
async def test_each_document_scenario_fires_distinct_alert(exc_cls, monkeypatch):
    calls = await _drive(exc_cls, monkeypatch)
    assert len(calls) == 1
    call = calls[0]
    assert call["dedup_key"] == f"add_zettel_document:{exc_cls.__name__}"
    assert call["exc_type"] == exc_cls.__name__
    assert call["fields"]["scenario"] == exc_cls.__name__
    assert call["route"] == "/api/zettels/add/document[async]"
    assert call["severity"] == "warning"
    # BOLA-safe: the raw user UUID must never appear in the alert payload.
    assert "user_hash" in call["fields"]


async def test_distinct_dedup_keys_across_all_scenarios(monkeypatch):
    keys = set()
    for exc_cls in SCENARIOS:
        calls = await _drive(exc_cls, monkeypatch)
        keys.add(calls[0]["dedup_key"])
    assert len(keys) == len(SCENARIOS)  # every scenario is its own bucket


async def test_non_document_valueerror_is_still_suppressed(monkeypatch):
    """Guard: the carve-out is scoped to DocumentUploadError only — a plain
    ValueError (e.g. URL RoutingError class) stays suppressed from #app-errors."""
    calls: list[dict] = []
    monkeypatch.setattr(wm, "maybe_fire_app_error", lambda **kw: calls.append(kw) or True)
    monkeypatch.setattr(zr.operations_repo, "start", lambda **kw: True)
    monkeypatch.setattr(zr.operations_repo, "finalize", lambda **kw: True)

    async def _boom():
        raise ValueError("not a document error")

    await zr._run(
        user_id=uuid.uuid4(),
        operation_id="op-plain-ve",
        pipeline=_boom,
        persist_requested=False,
    )
    assert calls == []
