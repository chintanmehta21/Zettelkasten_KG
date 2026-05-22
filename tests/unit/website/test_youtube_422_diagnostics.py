"""UX-4: /api/zettels/add 422 diagnostic payload for extraction failures.

PR #39 / Wave-1 A1 (2026-05-20): the route is now always-async (HTTP 202)
and surfaces extraction errors via the operations row's `error` payload,
read by `GET /api/operations/{id}`. These tests intercept the finalize RPC
to assert the same RFC 9457 problem-detail contract on the *background*
write — the same payload the GET endpoint subsequently returns.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from website.app import create_app
from website.features.summarization_engine.core.errors import ExtractionConfidenceError


@pytest.fixture
def client() -> TestClient:
    from website.api import zettels_routes

    zettels_routes._RATE_STORE.clear()
    return TestClient(create_app())


def _drive_bg_to_finalize(
    post_json: dict, captured: dict, user_dict: dict | None = None,
    *, settle_s: float = 2.5,
) -> None:
    """PR #40 hotfix (2026-05-21): cross-platform deterministic finalize.

    On Windows / macOS dev hosts, starlette's TestClient happens to drive
    the route's ``asyncio.create_task(_run(...))`` bg task to completion
    before ``client.post()`` returns (or shortly thereafter). On Linux
    GitHub Actions runners it does NOT — the per-request loop is torn
    down and the bg task is orphaned, never running.

    This helper handles BOTH paths cleanly:
      1. Poll ``captured`` for up to ``settle_s`` seconds. If the route's
         bg task already fired finalize (Windows/macOS path), return.
      2. Otherwise drive ``_run`` SYNCHRONOUSLY via ``asyncio.run`` in
         the test thread (Linux CI path) so finalize fires exactly once.

    Calling ``asyncio.run`` after the route already fired would
    double-run the pipeline and break call-count assertions; the polling
    guard is what prevents that on platforms where the bg task IS run.

    ADR-3 (2026-05-22): ``_run`` is now pipeline-agnostic — it takes a
    zero-arg ``pipeline`` callable instead of ``body``/``user``. The
    pipeline here is the URL ``_run_add_zettel`` wrapper, matching what
    the route spawns."""
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


_YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _yt_tier_results() -> list[dict]:
    return [
        {
            "tier": "ytdlp_player_rotation",
            "status": "failed",
            "reason": "all player clients failed",
            "latency_ms": 1200,
        },
        {"tier": "transcript_api_direct", "status": "failed", "reason": "no captions", "latency_ms": 300},
        {"tier": "piped_pool", "status": "failed", "reason": "all instances unhealthy", "latency_ms": 50},
        {"tier": "invidious_pool", "status": "failed", "reason": "all instances unhealthy", "latency_ms": 50},
        {"tier": "gemini_audio", "status": "failed", "reason": "yt-dlp blocked", "latency_ms": 800},
        {"tier": "metadata_only", "status": "failed", "reason": "oembed 429", "latency_ms": 200},
    ]


class TestYouTube422Diagnostics:
    def test_youtube_extraction_failure_returns_problem_detail(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Route 202s immediately (A1); the structured 422 problem-detail
        lands in the operations row's `error` column via _run -> finalize.
        We intercept finalize to assert the contract on the canonical
        background write, which is what GET /api/operations/{id} returns."""
        from website.api import zettels_routes
        from website.api.module_runners import summarization as runner
        from website.core import persist as persist_mod

        exc = ExtractionConfidenceError(
            "Insufficient content extracted (12 chars). Reason: All tiers failed",
            source_type="youtube",
            reason="All tiers failed",
            tier_results=_yt_tier_results(),
            url=_YT_URL,
        )
        # Force the URL dedup gate off-path: with no v2 scope, the pipeline
        # skips dedup and proceeds straight to require_entitlement + summarize.
        monkeypatch.setattr(persist_mod, "get_supabase_v2_scope", lambda *_a, **_k: None)
        monkeypatch.setattr(runner, "require_entitlement", AsyncMock())
        monkeypatch.setattr(runner, "resolve_redirects", AsyncMock(return_value=_YT_URL))
        monkeypatch.setattr(runner, "normalize_url", lambda url: url)
        monkeypatch.setattr(zettels_routes, "_gemini_client", lambda: object())
        monkeypatch.setattr(runner, "summarize_url_bundle", AsyncMock(side_effect=exc))

        captured: dict = {}

        def _finalize(**kw):
            captured["called"] = True
            captured.update(kw)
            return True

        monkeypatch.setattr(zettels_routes.operations_repo, "accept",
                            lambda **kw: (kw["operation_id"], True))
        monkeypatch.setattr(zettels_routes.operations_repo, "start",
                            lambda **kw: True)
        monkeypatch.setattr(zettels_routes.operations_repo, "finalize", _finalize)
        monkeypatch.setattr(zettels_routes, "check_async_backpressure",
                            AsyncMock(return_value=None))

        post_json = {
            "url": _YT_URL,
            "client_action_id": "yt-422",
            "persist": True,
            "surface": "landing",
        }
        resp = client.post("/api/zettels/add", json=post_json)

        assert resp.status_code == 202
        _drive_bg_to_finalize(post_json, captured)

        assert captured.get("target") == "failed"
        error = captured.get("error") or {}
        # The RFC 9457 problem body is preserved in the operations row's
        # error column; the GET handler emits it verbatim.
        assert error.get("title") == "Insufficient content"
        # `reason` + `tier_results` are passed via extra fields on the
        # async-failure error payload (mirrors the sync _problem() shape).
        extras = error.get("detail") if isinstance(error.get("detail"), dict) else error
        # The tier_results survive via either the top-level error dict or
        # a nested detail object — accept whichever the assembler used.
        tier_names: list[str] = []
        for candidate in (error, extras):
            if isinstance(candidate, dict) and isinstance(candidate.get("tier_results"), list):
                tier_names = [t["tier"] for t in candidate["tier_results"]]
                break
        assert "ytdlp_player_rotation" in tier_names
        assert "metadata_only" in tier_names

    def test_successful_youtube_add_zettel_returns_202_then_succeeded(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Route 202s immediately (A1). The succeeded body is written to the
        operations row's `response` column by the background _run task and
        returned by the subsequent GET /api/operations/{id} as 200."""
        from website.api import zettels_routes
        from website.api.module_runners import summarization as runner
        from website.core import persist as persist_mod
        from website.features.summarization_engine.core.models import (
            IngestResult,
            SourceType,
            SummaryMetadata,
            SummaryResult,
        )

        # Force the URL dedup gate off-path so the pipeline runs the
        # mocked summarize_url_bundle instead of returning _cache_hit_output.
        monkeypatch.setattr(persist_mod, "get_supabase_v2_scope", lambda *_a, **_k: None)

        metadata = SummaryMetadata(
            source_type=SourceType.YOUTUBE,
            url=_YT_URL,
            extraction_confidence="high",
            confidence_reason="ok",
            total_tokens_used=50,
            total_latency_ms=250,
        )
        bundle = SimpleNamespace(
            summary_result=SummaryResult(
                mini_title="YT Title",
                brief_summary="Brief",
                detailed_summary=[],
                tags=["source/youtube"],
                metadata=metadata,
            ),
            ingest_result=IngestResult(
                source_type=SourceType.YOUTUBE,
                url=_YT_URL,
                original_url=_YT_URL,
                raw_text="youtube content " * 20,
                metadata={"tier_used": "primary"},
                extraction_confidence="high",
                confidence_reason="ok",
                fetched_at=datetime.now(timezone.utc),
            ),
        )
        monkeypatch.setattr(runner, "require_entitlement", AsyncMock())
        monkeypatch.setattr(runner, "consume_entitlement", AsyncMock())
        monkeypatch.setattr(runner, "resolve_redirects", AsyncMock(return_value=_YT_URL))
        monkeypatch.setattr(runner, "normalize_url", lambda url: url)
        monkeypatch.setattr(zettels_routes, "_gemini_client", lambda: object())
        monkeypatch.setattr(runner, "summarize_url_bundle", AsyncMock(return_value=bundle))
        monkeypatch.setattr(
            runner,
            "persist_summarized_result",
            AsyncMock(
                return_value=SimpleNamespace(
                    result={},
                    file_node_id="yt-title",
                    supabase_node_id=None,
                    file_saved=True,
                    supabase_saved=False,
                    supabase_duplicate=False,
                )
            ),
        )

        captured: dict = {}

        def _finalize(**kw):
            captured["called"] = True
            captured.update(kw)
            return True

        monkeypatch.setattr(zettels_routes.operations_repo, "accept",
                            lambda **kw: (kw["operation_id"], True))
        monkeypatch.setattr(zettels_routes.operations_repo, "start",
                            lambda **kw: True)
        monkeypatch.setattr(zettels_routes.operations_repo, "finalize", _finalize)
        monkeypatch.setattr(zettels_routes, "check_async_backpressure",
                            AsyncMock(return_value=None))

        post_json = {
            "url": _YT_URL,
            "client_action_id": "yt-ok",
            "persist": True,
            "surface": "landing",
        }
        resp = client.post("/api/zettels/add", json=post_json)

        assert resp.status_code == 202
        _drive_bg_to_finalize(post_json, captured)

        assert captured.get("target") == "succeeded"
        response_payload = captured.get("response") or {}
        assert response_payload.get("status") == "succeeded"
        assert response_payload.get("summary", {}).get("title") == "YT Title"
