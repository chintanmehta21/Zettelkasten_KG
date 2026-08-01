"""2026-08-01: /api/readyz — "can this worker serve?" separate from "is it alive?".

The 2026-08-01T04:08Z deploy smoke probe fired against a worker that reported
``/api/health`` 200 while its retrieval path was still cold, and got HTTP 200
with zero citations. Liveness and readiness are different questions and were
being answered by the same endpoint.

Contract:
  * ``/api/health`` stays SHALLOW. It is the restart trigger for Docker/Caddy;
    a liveness probe that touches dependencies turns a soft dependency into a
    hard one and can take the whole service down (AWS Builders' Library, and
    the same caution in the Kubernetes probe docs).
  * ``/api/readyz`` is DEEP but non-destructive: 200 only once the reranker
    session is loaded and the data path has been exercised in this process.
  * ``pid`` is reported because gunicorn round-robins across workers, so one
    200 proves exactly one worker is ready.
"""
from __future__ import annotations

import os
from unittest.mock import patch

for _k, _v in (
    ("GEMINI_API_KEY", "ci-stub"),
    ("SUPABASE_V2_URL", "https://ci-stub.supabase.co"),
    ("SUPABASE_V2_ANON_KEY", "a"),
    ("SUPABASE_V2_SERVICE_ROLE_KEY", "s"),
    ("NEXUS_TOKEN_ENCRYPTION_KEY", "7TgtMgeR5dMTnXxW6ULICwhf66A1VpzwuNFuIBqmoe4="),
):
    os.environ.setdefault(_k, _v)

import pytest  # noqa: E402
from fastapi import Response  # noqa: E402

from website.api import routes as routes_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_warm_state():
    routes_mod._WARMED.clear()
    yield
    routes_mod._WARMED.clear()


async def test_readyz_503_when_nothing_warmed():
    resp = Response()
    with patch.object(routes_mod, "_WARMED", {}):
        body = await routes_mod.readyz(resp)
    assert resp.status_code == 503
    assert body["ready"] is False


async def test_readyz_503_when_only_reranker_ready():
    """Reranker loaded but data path cold — exactly the 04:08Z failure shape."""
    from website.features.rag_pipeline.rerank import cascade as cascade_mod

    resp = Response()
    with patch.object(cascade_mod, "_STAGE2_SESSION", object()):
        body = await routes_mod.readyz(resp)
    assert resp.status_code == 503
    assert body["reranker"] is True
    assert body["data_path"] is False
    assert body["ready"] is False


async def test_readyz_200_when_both_ready():
    from website.features.rag_pipeline.rerank import cascade as cascade_mod

    resp = Response()
    routes_mod._WARMED["db"] = True
    with patch.object(cascade_mod, "_STAGE2_SESSION", object()):
        body = await routes_mod.readyz(resp)
    assert resp.status_code != 503
    assert body["ready"] is True


async def test_readyz_reports_worker_pid():
    resp = Response()
    body = await routes_mod.readyz(resp)
    assert body["pid"] == os.getpid()


async def test_warm_marks_the_data_path_ready():
    """/api/health/warm is what flips readiness for this worker."""
    from unittest.mock import MagicMock

    with patch("website.core.supabase_v2.client.is_v2_configured", return_value=True), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=MagicMock()):
        await routes_mod.warm()
    assert routes_mod._WARMED.get("db") is True


async def test_failed_warm_does_not_mark_ready():
    """A warm-up that errored must not advertise the worker as ready."""
    with patch("website.core.supabase_v2.client.is_v2_configured", return_value=True), \
         patch(
             "website.core.supabase_v2.client.get_v2_client",
             side_effect=RuntimeError("db down"),
         ):
        await routes_mod.warm()
    assert routes_mod._WARMED.get("db") is not True


def test_health_stays_shallow():
    """Liveness must not acquire DB/LLM dependencies."""
    import inspect

    src = inspect.getsource(routes_mod.health)
    for banned in ("get_v2_client", "supabase", "gemini", "_WARMED"):
        assert banned not in src, (
            f"/api/health must stay shallow — found {banned!r}. A liveness probe "
            "that checks dependencies can restart-loop the whole service."
        )
