"""2026-08-01: /api/health/warm must warm the data path, and never gate on it.

deploy.sh calls this endpoint before the RAG smoke probe, and its comment
claimed the call warmed "cold Supabase RPC pools, cold pgvector index pages,
and cold Gemini key-pool selectors". It warmed exactly ONE thing — the stage-2
ONNX rerank session — so the retrieval path was still cold when the graded
smoke probe fired. That is a live candidate for the 2026-08-01T04:08Z failure
(HTTP 200, answer present, zero citations).

Two properties are load-bearing and must not regress:
  1. the DB round-trip happens (otherwise the warm-up is a no-op for retrieval);
  2. it can NEVER fail the request — this endpoint is called on the deploy
     critical path, so a soft dependency being down must not abort a cutover.
     (AWS Builders' Library: deep health checks convert soft dependencies into
     hard ones and take the whole fleet down together.)

Also asserted: we do NOT warm Gemini. RAG questions are metered per user and
the smoke account is on a free plan, so warming the LLM on every deploy would
burn real quota and make a paid API a hard dependency of the health signal.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

for _k, _v in (
    ("GEMINI_API_KEY", "ci-stub"),
    ("SUPABASE_V2_URL", "https://ci-stub.supabase.co"),
    ("SUPABASE_V2_ANON_KEY", "a"),
    ("SUPABASE_V2_SERVICE_ROLE_KEY", "s"),
    ("NEXUS_TOKEN_ENCRYPTION_KEY", "7TgtMgeR5dMTnXxW6ULICwhf66A1VpzwuNFuIBqmoe4="),
):
    os.environ.setdefault(_k, _v)

from website.api.routes import warm  # noqa: E402


async def test_warm_performs_a_db_round_trip():
    client = MagicMock()
    with patch("website.core.supabase_v2.client.is_v2_configured", return_value=True), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=client):
        body = await warm()

    assert body["warmed"] is True
    assert body["db_detail"] == "ok"
    client.schema.assert_called_once_with("core")
    # A cheap, bounded query — not a table scan.
    client.schema.return_value.table.return_value.select.return_value.limit.assert_called_once_with(1)


async def test_warm_never_fails_when_db_is_down():
    """The deploy critical path must not abort because a soft dep is down."""
    with patch("website.core.supabase_v2.client.is_v2_configured", return_value=True), \
         patch(
             "website.core.supabase_v2.client.get_v2_client",
             side_effect=RuntimeError("supabase unreachable"),
         ):
        body = await warm()

    assert body["warmed"] is True, "warm must stay 200 even when the DB is down"
    assert body["db_detail"].startswith("db_warm_failed")


async def test_warm_skips_cleanly_when_v2_unconfigured():
    with patch("website.core.supabase_v2.client.is_v2_configured", return_value=False):
        body = await warm()
    assert body["warmed"] is True
    assert body["db_detail"] == "v2_not_configured"


async def test_warm_reports_worker_pid():
    """gunicorn round-robins; one warm request warms one worker.

    Surfacing the pid is what lets the deploy script (and an operator) confirm
    every worker was actually covered instead of assuming it.
    """
    with patch("website.core.supabase_v2.client.is_v2_configured", return_value=False):
        body = await warm()
    assert body["pid"] == os.getpid()


def test_warm_does_not_touch_the_metered_llm_path():
    """Warming Gemini would burn metered quota on every deploy and probe."""
    import inspect

    src = inspect.getsource(warm)
    for banned in ("gemini", "GeminiKeyPool", "generate_content", "embed_content"):
        assert banned not in src, (
            f"/api/health/warm must not exercise {banned!r} — RAG questions are "
            "metered and the smoke account is free-plan."
        )


@pytest.mark.parametrize("exc", [RuntimeError("boom"), ValueError("bad"), OSError()])
async def test_warm_swallows_any_db_exception_type(exc):
    with patch("website.core.supabase_v2.client.is_v2_configured", return_value=True), \
         patch("website.core.supabase_v2.client.get_v2_client", side_effect=exc):
        body = await warm()
    assert body["warmed"] is True
