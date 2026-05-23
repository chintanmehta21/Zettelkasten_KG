"""Unit tests for the Phase C create-Kasten runner.

Fully mocked — NO live Supabase, NO real Gemini. Patches:

* ``create_kasten.run_add_zettel_pipeline`` (the per-link Add Zettel facade)
* ``create_kasten.RAGRepository`` (kasten create / list / bulk-add)
* ``persist.get_supabase_v2_scope`` (workspace scope + ContentRepository)
* ``routes.invalidate_user_graph`` (graph cache invalidation)

Covers: happy path create+ingest, invalid inputs, idempotent re-submit,
dup-name reuse (D2, not 409), per-link failure isolation, the dedup caveat
(canonical id never reaches bulk_add), persist/effective_user_id propagation,
and graph-cache invalidation.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from website.api.module_runners import create_kasten as ck
from website.api.module_runners.create_kasten import (
    IdempotencyConflict,
    run_create_kasten_pipeline,
)

NARUTO = uuid.UUID("f2105544-b73d-4946-8329-096d82f070d3")
WS_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PROFILE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture(autouse=True)
def _clear_idempotency_state():
    """Each test starts with an empty in-flight singleflight map.

    D4 (locked 2026-05-23): the per-process ``_IDEMPOTENCY_CACHE`` was
    removed — the DB-backed ``core.operations`` row is the cross-worker
    truth, and a per-worker OrderedDict was invisible to other gunicorn
    workers. ``_IN_FLIGHT`` stays as the same-worker singleflight that
    coalesces concurrent same-key requests on ONE worker before they
    reach the DB.
    """
    ck._IN_FLIGHT.clear()
    yield
    ck._IN_FLIGHT.clear()


def _kasten_row(name: str, kid: uuid.UUID | None = None) -> dict:
    return {
        "id": str(kid or uuid.uuid4()),
        "name": name,
        "description": "",
        "icon": "stack",
        "color": "#14b8a6",
        "default_quality": "fast",
        "created_at": "2026-05-18T00:00:00Z",
        "updated_at": "2026-05-18T00:00:00Z",
        "last_used_at": None,
    }


def _pipeline_out(*, url: str, duplicate: bool = False, node_id: str = "web-x") -> dict:
    # Mirrors AddZettelPipelineOutput.model_dump(mode="json"). The
    # ``workspace_zettel_id`` here is deliberately the *canonical* id on a
    # dedup hit — the runner must NOT trust it (dedup caveat).
    return {
        "status": "succeeded",
        "operation_id": "op",
        "summary": {"source_url": url},
        "persistence": {
            "requested": True,
            "persisted": True,
            "file_store": True,
            "supabase": True,
            "duplicate": duplicate,
        },
        "quality": {"confidence": "ok"},
        "node_id": node_id,
        "workspace_zettel_id": "CANONICAL-ID-NOT-OVERLAY",
    }


def _patched(rag_repo: MagicMock, content_repo: MagicMock):
    """Return the standard patch stack as context managers."""
    return (
        patch.object(ck, "RAGRepository", return_value=rag_repo),
        patch(
            "website.core.persist.get_supabase_v2_scope",
            return_value=(content_repo, PROFILE_ID, WS_ID),
        ),
        patch("website.api.routes.invalidate_user_graph", return_value=1),
    )


@pytest.mark.asyncio
async def test_happy_path_create_and_ingest():
    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = _kasten_row("research")
    rag_repo.add_zettels_to_kasten.return_value = 2
    content_repo = MagicMock()
    wz1, wz2 = uuid.uuid4(), uuid.uuid4()
    content_repo.resolve_workspace_zettel_id_by_url.side_effect = [wz1, wz2]

    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3, patch.object(
        ck, "run_add_zettel_pipeline"
    ) as mock_pipe:
        mock_pipe.side_effect = [
            _pipeline_out(url="https://a.example.com/"),
            _pipeline_out(url="https://b.example.com/"),
        ]
        out = await run_create_kasten_pipeline(
            name="research",
            links=["https://a.example.com/", "https://b.example.com/"],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-1",
        )

    assert out["status"] == "succeeded"
    assert out["kasten"]["name"] == "research"
    assert len(out["ingested"]) == 2
    assert out["failed"] == []
    # Per-link persist + correct effective_user_id propagated.
    for call in mock_pipe.call_args_list:
        assert call.kwargs["persist"] is True
        assert call.kwargs["effective_user_id"] == NARUTO
    # Dedup caveat: only resolved overlay ids reach bulk_add — never the
    # canonical id the pipeline returned.
    added_ids = rag_repo.add_zettels_to_kasten.call_args.kwargs["workspace_zettel_ids"]
    assert set(added_ids) == {wz1, wz2}
    assert "CANONICAL-ID-NOT-OVERLAY" not in {str(i) for i in added_ids}


@pytest.mark.asyncio
async def test_empty_name_rejected():
    with pytest.raises(ValueError, match="name is required"):
        await run_create_kasten_pipeline(
            name="   ",
            links=[],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-2",
        )


@pytest.mark.asyncio
async def test_oversize_name_rejected():
    with pytest.raises(ValueError, match="name is too long"):
        await run_create_kasten_pipeline(
            name="x" * 81,
            links=[],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-3",
        )


@pytest.mark.asyncio
async def test_malformed_url_rejected_no_partial_kasten():
    rag_repo = MagicMock()
    content_repo = MagicMock()
    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3:
        with pytest.raises(ValueError, match="must start with http"):
            await run_create_kasten_pipeline(
                name="k",
                links=["not-a-url"],
                user={"sub": str(NARUTO)},
                effective_user_id=NARUTO,
                client_action_id="cak-4",
            )
    # Validation happens BEFORE any Kasten write — no partial leak.
    rag_repo.create_kasten.assert_not_called()


@pytest.mark.asyncio
async def test_create_only_empty_links_succeeds():
    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = _kasten_row("empty")
    content_repo = MagicMock()
    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3:
        out = await run_create_kasten_pipeline(
            name="empty",
            links=[],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-5",
        )
    assert out["status"] == "succeeded"
    assert out["ingested"] == []
    assert out["failed"] == []
    rag_repo.add_zettels_to_kasten.assert_not_called()


@pytest.mark.asyncio
async def test_sequential_resubmit_reruns_dedup_at_db_layer():
    """D4 (locked 2026-05-23): the runner no longer caches per-call results.

    A SEQUENTIAL second submit with the same client_action_id re-executes
    the runner — cross-call dedup is now the DB layer's job (route uses
    ``operations_repo.accept`` whose partial unique index on
    ``(user_id, request_hash)`` collapses retries to one canonical op).
    The kasten itself stays idempotent in-DB via the ``UNIQUE(workspace_id,
    name)`` recovery (``_create_or_get_kasten`` reuses the existing same-
    name row on dup-key), so end-state convergence is preserved.

    See also ``test_concurrent_identical_submit_dedups_via_in_flight_shield``
    for the SAME-WORKER, SAME-INSTANT race that ``_IN_FLIGHT`` still
    coalesces — a different concern (singleflight, complementary to the
    DB layer).
    """
    rag_repo = MagicMock()
    kid = uuid.uuid4()
    rag_repo.create_kasten.return_value = _kasten_row("idem", kid)
    rag_repo.add_zettels_to_kasten.return_value = 1
    content_repo = MagicMock()
    wz = uuid.uuid4()
    content_repo.resolve_workspace_zettel_id_by_url.return_value = wz

    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3, patch.object(ck, "run_add_zettel_pipeline") as mock_pipe:
        mock_pipe.return_value = _pipeline_out(url="https://a.example.com/")
        kwargs = dict(
            name="idem",
            links=["https://a.example.com/"],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-idem",
        )
        first = await run_create_kasten_pipeline(**kwargs)
        second = await run_create_kasten_pipeline(**kwargs)

    # Both submissions produced the SAME kasten id (DB-layer reuse via
    # UNIQUE(workspace_id, name) — the runner re-ran but converged on the
    # same row).
    assert first["kasten"]["id"] == str(kid)
    assert second["kasten"]["id"] == str(kid)
    # No result cache anymore → pipeline runs twice (once per submit).
    assert mock_pipe.call_count == 2
    # create_kasten is called twice; the second call hits the dup-key
    # path and recovers via get_kasten_by_name (verified separately by
    # test_dup_name_reuses_existing_not_409).


@pytest.mark.asyncio
async def test_concurrent_identical_submit_dedups_via_in_flight_shield():
    """Two simultaneous identical submits → ONE Kasten, ONE pipeline run.

    Exercises the ``_IN_FLIGHT`` + ``asyncio.shield(running_task)`` path
    (mirror of ``zettels_routes._IN_FLIGHT``). The second concurrent caller
    must attach to the first's in-flight task, NOT start a second build —
    otherwise a double-submit race would create a duplicate Kasten and
    double-run the Add Zettel pipeline (and double-charge ZETTEL).
    """
    import asyncio

    rag_repo = MagicMock()
    kid = uuid.uuid4()
    rag_repo.create_kasten.return_value = _kasten_row("race", kid)
    rag_repo.add_zettels_to_kasten.return_value = 1
    content_repo = MagicMock()
    wz = uuid.uuid4()
    content_repo.resolve_workspace_zettel_id_by_url.return_value = wz

    pipeline_calls = 0

    async def _slow_pipe(*, url, **_kw):
        nonlocal pipeline_calls
        pipeline_calls += 1
        await asyncio.sleep(0.05)  # widen the race window
        return _pipeline_out(url=url)

    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3, patch.object(
        ck, "run_add_zettel_pipeline", side_effect=_slow_pipe
    ):
        kwargs = dict(
            name="race",
            links=["https://a.example.com/"],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-race",
        )
        first, second = await asyncio.gather(
            run_create_kasten_pipeline(**kwargs),
            run_create_kasten_pipeline(**kwargs),
        )

    # Identical result; build ran exactly once (no duplicate Kasten, no
    # double pipeline run, no double ZETTEL charge).
    assert first == second
    assert first["kasten"]["id"] == str(kid)
    assert pipeline_calls == 1
    assert rag_repo.create_kasten.call_count == 1
    assert rag_repo.add_zettels_to_kasten.call_count == 1


@pytest.mark.asyncio
async def test_bulk_add_failure_keeps_kasten_in_response():
    """A ``bulk_add_to_kasten`` driver error must not lose the created Kasten.

    The Kasten + zettels are already persisted; only the join failed. The
    response must still carry the Kasten (callers can retry the add) with a
    ``<bulk_add_to_kasten>`` failure marker — never a 5xx that hides the
    successfully-created Kasten.
    """
    rag_repo = MagicMock()
    kid = uuid.uuid4()
    rag_repo.create_kasten.return_value = _kasten_row("ba", kid)
    rag_repo.add_zettels_to_kasten.side_effect = RuntimeError("join table locked")
    content_repo = MagicMock()
    content_repo.resolve_workspace_zettel_id_by_url.return_value = uuid.uuid4()

    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3, patch.object(
        ck, "run_add_zettel_pipeline",
        return_value=_pipeline_out(url="https://a.example.com/"),
    ):
        out = await run_create_kasten_pipeline(
            name="ba",
            links=["https://a.example.com/"],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-ba",
        )
    assert out["status"] == "succeeded"
    assert out["kasten"]["id"] == str(kid)
    assert any(f["url"] == "<bulk_add_to_kasten>" for f in out["failed"])


@pytest.mark.asyncio
async def test_concurrent_body_mismatch_raises_singleflight_conflict():
    """D4 (locked 2026-05-23): IdempotencyConflict now fires ONLY in the
    same-worker concurrent race window.

    The runner-level result cache that used to detect body mismatch across
    SEQUENTIAL submits was removed (cross-worker dedup belongs to the DB
    layer). The remaining ``_IN_FLIGHT`` singleflight still raises on a
    same-key-different-body race when two submits arrive on ONE worker at
    the same time — exercise that here with a slow first submit racing a
    body-mismatched second submit.
    """
    import asyncio as _aio

    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = _kasten_row("c")
    content_repo = MagicMock()

    # Hold the first build open with a sleepable mock so the second submit
    # arrives while the first is still in _IN_FLIGHT.
    async def _slow_drain(*_a, **_kw):
        await _aio.sleep(0.05)

    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3, patch.object(
        ck, "_drain_pending_enrichment_tasks", side_effect=_slow_drain,
    ):
        first_task = _aio.create_task(run_create_kasten_pipeline(
            name="c",
            links=[],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-conflict",
        ))
        # Tiny yield so the first call registers in _IN_FLIGHT before the
        # second arrives (deterministic ordering on the asyncio loop).
        await _aio.sleep(0)
        with pytest.raises(IdempotencyConflict):
            await run_create_kasten_pipeline(
                name="c-DIFFERENT",
                links=[],
                user={"sub": str(NARUTO)},
                effective_user_id=NARUTO,
                client_action_id="cak-conflict",
            )
        # Drain the in-flight first build so the test loop exits cleanly.
        await first_task


@pytest.mark.asyncio
async def test_dup_name_reuses_existing_not_409():
    rag_repo = MagicMock()
    existing_id = uuid.uuid4()
    rag_repo.create_kasten.side_effect = RuntimeError(
        'duplicate key value violates unique constraint "kastens_workspace_id_name_key"'
    )
    # Codex #3262317336: dup-key recovery now uses the scale-proof direct
    # get_kasten_by_name lookup, not a capped list_kastens scan.
    rag_repo.get_kasten_by_name.return_value = _kasten_row("dup", existing_id)
    content_repo = MagicMock()
    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3:
        out = await run_create_kasten_pipeline(
            name="dup",
            links=[],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-dup",
        )
    # D2: re-use the existing Kasten, no exception, no 409.
    assert out["status"] == "succeeded"
    assert out["kasten"]["id"] == str(existing_id)


@pytest.mark.asyncio
async def test_per_link_failure_isolation():
    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = _kasten_row("iso")
    rag_repo.add_zettels_to_kasten.return_value = 1
    content_repo = MagicMock()
    good_wz = uuid.uuid4()
    content_repo.resolve_workspace_zettel_id_by_url.return_value = good_wz

    def _pipe(*, url, **_kw):
        if "bad" in url:
            raise RuntimeError("extraction failed")
        return _pipeline_out(url=url)

    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3, patch.object(ck, "run_add_zettel_pipeline", side_effect=_pipe):
        out = await run_create_kasten_pipeline(
            name="iso",
            links=["https://bad.example.com/", "https://good.example.com/"],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-iso",
        )
    # One bad link did NOT abort the build.
    assert out["status"] == "succeeded"
    assert out["kasten"]["name"] == "iso"
    assert len(out["failed"]) == 1
    assert out["failed"][0]["url"] == "https://bad.example.com/"
    assert len(out["ingested"]) == 1
    assert out["ingested"][0]["url"] == "https://good.example.com/"


@pytest.mark.asyncio
async def test_dedup_caveat_resolves_real_workspace_zettel_id():
    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = _kasten_row("dd")
    rag_repo.add_zettels_to_kasten.return_value = 1
    content_repo = MagicMock()
    real_wz = uuid.uuid4()
    content_repo.resolve_workspace_zettel_id_by_url.return_value = real_wz

    p1, p2, p3 = _patched(rag_repo, content_repo)
    with p1, p2, p3, patch.object(ck, "run_add_zettel_pipeline") as mock_pipe:
        # was_new=False (duplicate) → pipeline returns the canonical id.
        mock_pipe.return_value = _pipeline_out(
            url="https://dup-link.example.com/", duplicate=True
        )
        out = await run_create_kasten_pipeline(
            name="dd",
            links=["https://dup-link.example.com/"],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-dd",
        )
    # Resolver was called with the normalized URL + workspace.
    content_repo.resolve_workspace_zettel_id_by_url.assert_called_once()
    rkw = content_repo.resolve_workspace_zettel_id_by_url.call_args.kwargs
    assert rkw["normalized_url"] == "https://dup-link.example.com/"
    assert rkw["workspace_id"] == WS_ID
    # The REAL overlay id (not the canonical id) reached bulk_add.
    added = rag_repo.add_zettels_to_kasten.call_args.kwargs["workspace_zettel_ids"]
    assert added == [real_wz]
    assert out["ingested"][0]["was_new"] is False
    assert out["ingested"][0]["workspace_zettel_id"] == str(real_wz)


@pytest.mark.asyncio
async def test_graph_cache_invalidated_after_ingest():
    rag_repo = MagicMock()
    rag_repo.create_kasten.return_value = _kasten_row("g")
    rag_repo.add_zettels_to_kasten.return_value = 1
    content_repo = MagicMock()
    content_repo.resolve_workspace_zettel_id_by_url.return_value = uuid.uuid4()

    with patch.object(ck, "RAGRepository", return_value=rag_repo), patch(
        "website.core.persist.get_supabase_v2_scope",
        return_value=(content_repo, PROFILE_ID, WS_ID),
    ), patch(
        "website.api.routes.invalidate_user_graph", return_value=1
    ) as mock_inv, patch.object(
        ck, "run_add_zettel_pipeline",
        return_value=_pipeline_out(url="https://a.example.com/"),
    ):
        await run_create_kasten_pipeline(
            name="g",
            links=["https://a.example.com/"],
            user={"sub": str(NARUTO)},
            effective_user_id=NARUTO,
            client_action_id="cak-g",
        )
    mock_inv.assert_called_once_with(str(NARUTO))


@pytest.mark.asyncio
async def test_no_v2_scope_raises():
    with patch(
        "website.core.persist.get_supabase_v2_scope", return_value=None
    ):
        with pytest.raises(ValueError, match="DB v2 workspace scope"):
            await run_create_kasten_pipeline(
                name="ns",
                links=[],
                user={"sub": str(NARUTO)},
                effective_user_id=NARUTO,
                client_action_id="cak-ns",
            )


def test_runner_has_cli_entrypoint_and_conventions():
    source = open(
        "website/api/module_runners/create_kasten.py", encoding="utf-8"
    ).read()
    assert "argparse.ArgumentParser" in source
    assert 'if __name__ == "__main__"' in source
    assert "asyncio.Semaphore(2)" in source
    assert "run_add_zettel_pipeline(" in source
    assert ".model_dump(mode=\"json\")" in source
