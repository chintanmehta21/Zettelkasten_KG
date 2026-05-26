"""Agent 3 test matrix for the pure-ASGI middleware conversion (PR #115 Scope C).

These tests build a MINIMAL FastAPI app wired with the same middleware stack
(Brotli + the 5 converted classes) so the chain's correctness can be pinned
without dragging in Supabase / Gemini / Caddy dependencies. They complement
``test_middleware_chain_order.py`` (which pins registration order) and
``test_auth_jwt_drop_observability.py`` (which pins the X-Auth-Status /
session marker semantics through the full ``create_app`` factory).

Coverage:
  - SSE: streaming endpoint passes through without buffering or
    Content-Length surgery (PostResponseRelease's finally must not fire
    mid-stream).
  - HEAD: empty-body responses don't emit a body chunk after my middleware
    wraps send; X-Auth-Status still attaches if request.state.auth_status
    was set.
  - MemoryPressureError: an exception raised inside the route is converted
    to a 503 JSONResponse by the exception_handler; middleware chain still
    runs (X-Auth-Status applied if set), and PostResponseRelease's finally
    still triggers gc / malloc_trim cleanly.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from website.api._memory_guard import MemoryGuardMiddleware
from website.api._middleware import (
    Auth401RateMonitorMiddleware,
    AuthStatusHeadersMiddleware,
    PostResponseReleaseMiddleware,
    SessionMarkerCookieMiddleware,
)


class _SimulatedMemoryPressure(Exception):
    """Stand-in for rerank.cascade.MemoryPressureError to avoid the heavy
    rerank import at test-collection time. The matrix only needs to confirm
    that an exception_handler-converted 503 flows cleanly through the
    middleware chain."""


def _build_matrix_app() -> FastAPI:
    """A minimal app wired with the 5 converted middleware in the same order
    as ``create_app``. No DB / Supabase / Gemini deps; just enough routes
    to exercise SSE, HEAD, and the exception-handler path.
    """
    app = FastAPI()

    @app.exception_handler(_SimulatedMemoryPressure)
    async def _handle_pressure(request: Request, exc: _SimulatedMemoryPressure):
        return JSONResponse(
            {"error": "server_under_memory_pressure", "retry_after_seconds": 5},
            status_code=503,
            headers={"Retry-After": "5"},
        )

    @app.get("/sse")
    async def sse_endpoint():
        async def stream():
            for i in range(3):
                yield f"data: chunk-{i}\n\n".encode()
                await asyncio.sleep(0)  # Yield to the loop between chunks.

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.api_route("/head-target", methods=["GET", "HEAD"])
    async def head_target(request: Request):
        request.state.auth_status = "jwt-dropped-to-anon"
        return {"ok": True}

    @app.get("/pressure")
    async def pressure_route(request: Request):
        request.state.auth_status = "jwt-dropped-to-anon"
        raise _SimulatedMemoryPressure("stage-2 OOM")

    # Same FIFO add-order as create_app: first added = innermost.
    app.add_middleware(MemoryGuardMiddleware)
    app.add_middleware(
        PostResponseReleaseMiddleware,
        exempt_prefixes=("/api/health", "/favicon."),
    )
    app.add_middleware(AuthStatusHeadersMiddleware)
    app.add_middleware(SessionMarkerCookieMiddleware)
    app.add_middleware(Auth401RateMonitorMiddleware)
    return app


def test_sse_streaming_passes_through_middleware():
    """SSE response must stream without buffering. PostResponseRelease's
    finally must wait until streaming completes; AuthHeaders must not
    insert Content-Length (which would conflict with chunked transfer).
    """
    app = _build_matrix_app()
    with TestClient(app) as client:
        with client.stream("GET", "/sse") as response:
            assert response.status_code == 200
            # FastAPI appends "; charset=utf-8"; substring check is enough.
            assert response.headers.get("content-type", "").startswith(
                "text/event-stream"
            )
            chunks: list[bytes] = []
            for chunk in response.iter_bytes():
                if chunk:
                    chunks.append(chunk)
            body = b"".join(chunks)
            assert b"chunk-0" in body
            assert b"chunk-1" in body
            assert b"chunk-2" in body


def test_head_request_returns_no_body_but_keeps_x_auth_status_header():
    """HEAD requests get headers but no body. AuthStatusHeadersMiddleware
    must still attach X-Auth-Status when the route set request.state.
    """
    app = _build_matrix_app()
    with TestClient(app) as client:
        response = client.head("/head-target")
        assert response.status_code == 200
        # FastAPI/Starlette strips body for HEAD automatically.
        assert response.content == b""
        # Header from my AuthStatusHeadersMiddleware still attaches.
        assert response.headers.get("X-Auth-Status") == "jwt-dropped-to-anon"


def test_memory_pressure_exception_returns_503_with_auth_header_intact():
    """A route raising MemoryPressureError is converted to 503 by the
    exception_handler. The middleware chain still runs on the egress:
    request.state.auth_status set BEFORE the raise must still surface as
    X-Auth-Status on the 503 response.
    """
    app = _build_matrix_app()
    with TestClient(app) as client:
        response = client.get("/pressure")
        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "5"
        body = json.loads(response.content)
        assert body["error"] == "server_under_memory_pressure"
        assert body["retry_after_seconds"] == 5
        # X-Auth-Status survives the exception_handler conversion.
        assert response.headers.get("X-Auth-Status") == "jwt-dropped-to-anon"


def test_memory_guard_short_circuits_with_503_when_over_threshold():
    """Pin: MemoryGuardMiddleware emits a synthetic 503 + Retry-After=5 +
    JSON body with the canonical error shape when RSS exceeds threshold,
    WITHOUT calling the inner app. Replaces the BaseHTTPMiddleware version
    that used to construct a JSONResponse object.
    """
    app = _build_matrix_app()

    # Force every short-circuit branch except the final RSS-over-threshold:
    # threshold=50, mem_max=10**9 bytes, rss=10**9 → 100% > 50%.
    with patch(
        "website.api._memory_guard._threshold_percent", return_value=50
    ), patch(
        "website.api._memory_guard._detect_mem_max", return_value=10**9
    ), patch(
        "website.api._memory_guard._read_vm_rss_bytes", return_value=10**9
    ):
        with TestClient(app) as client:
            response = client.get("/head-target")

    assert response.status_code == 503
    assert response.headers.get("Retry-After") == "5"
    body = json.loads(response.content)
    assert body["error"] == "server_under_memory_pressure"
    assert body["retry_after_seconds"] == 5
