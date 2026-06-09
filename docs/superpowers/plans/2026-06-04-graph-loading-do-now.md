# Graph-Loading "Do-Now" Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four zero-new-infra graph-loading improvements decided in `docs/claude_audits/graph_loading_industry_research_2026-06-04.md` — a private-cache + weak-ETag contract on `/api/graph`, removal of in-process HTTP compression (Caddy/Cloudflare own it), a faster/calmer client settle, and three flip-metric log lines.

**Architecture:** Backend changes are in `website/api/routes.py` (the `/api/graph` handler) and `website/app.py` (middleware registration); frontend changes are in `website/features/knowledge_graph/js/app.js`. Compression moves entirely to the existing Caddy `encode zstd gzip` + Cloudflare edge layer. Observability is plain `logger.info` (server) + one `console.log` (client) — no new endpoints, no new infra.

**Tech Stack:** FastAPI + Starlette (Python 3.12), python-igraph, Supabase/PostgREST, vanilla-JS `3d-force-graph` (Three.js + d3-force-3d), Caddy 2 + Cloudflare, pytest (`asyncio_mode=auto`), vitest for JS.

**Out of scope (deferred, do NOT implement here):** the cold-build `asyncio.to_thread`/parallel-DB fix; server-side precomputed layout; LOD/focal subsetting; personal-subgraph progressive reveal; materialized analytics columns; mobile graph (`website/mobile/js/graph.js`). These are tracked in the audit doc behind named flip-metrics.

**Protected knobs — MUST NOT touch:** SSE heartbeat wrapper (`website/api/chat_routes.py::_heartbeat_wrapper`), `GUNICORN_WORKERS≥2`, `--preload`, gunicorn/Caddy timeouts, the rerank semaphore, the schema-drift / `kg_users` allowlist gates. Teal on Kasten surfaces; amber only on `/knowledge-graph`; never purple.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `website/api/routes.py` | `/api/graph` handler `graph_data()` (line ~1318); `_enrich_graph_with_analytics()` (line ~183) | Modify: emit weak ETag + `Cache-Control: private` + 304; log node-count + analytics wall-time |
| `website/app.py` | App factory `create_app()` (compression middleware at lines 458–472) | Modify: delete the in-process compression block |
| `website/features/knowledge_graph/js/app.js` | KG 3D viewer; `test-exports` fence (ends line 103); `loadGraphData()` (line 717); `initGraph()` settle (lines 1148–1149) | Modify: add tiering + metric helpers to the fence; retune settle; log client load metric |
| `ops/requirements.txt` | Runtime deps (lines 52–57) | Modify: drop `brotli-asgi` (keep `brotli` decoder) |
| `tests/unit/website/test_graph_etag.py` | ETag/private-cache contract for `/api/graph` | Create |
| `tests/unit/website/test_middleware_chain_order.py` | Pins middleware order (line 20 lists `BrotliMiddleware`) | Modify: drop Brotli from expectation; add no-compression guard |
| `tests/integration/v2/test_kg_payload.py` | `/api/graph` payload trim + (stale) Brotli-negotiation tests | Modify: drop Brotli tests/fixture; rewrite size budget; keep trim tests |
| `tests/unit/website/test_middleware_asgi_matrix.py` | Pure-ASGI middleware matrix (docstring only mentions Brotli) | Modify: one-line docstring fix |
| `tests/unit/website/test_graph_metrics_logging.py` | Server flip-metric logs (node-count, analytics ms) | Create |
| `tests/js/knowledge_graph/settle_tuning.test.js` | `warmupTicksForNodeCount` + cooldown literal | Create |
| `tests/js/knowledge_graph/graph_load_metric.test.js` | `formatGraphLoadMetric` | Create |

---

## PHASE 1 — Keystone: private cache + weak-ETag + 304 on `/api/graph`

### Task 1: ETag + `Cache-Control: private` + 304 on `/api/graph`

**Files:**
- Test: `tests/unit/website/test_graph_etag.py` (create)
- Modify: `website/api/routes.py` (the `graph_data` handler, lines ~1317–1394)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/website/test_graph_etag.py`:

```python
"""GET /api/graph conditional-request + private-cache contract.

Ties the audit decision (docs/claude_audits/graph_loading_industry_research_2026-06-04.md):
- Per-user graph data MUST be `Cache-Control: private`. Cloudflare shipped async
  stale-while-revalidate on 2026-02-26 and would otherwise edge-cache and serve
  one user's graph to another (BOLA / data leak).
- A weak ETag + 304 collapses the 2-3 duplicate /api/graph fetches per visit.
- Weak comparison (RFC 7232) so a Cloudflare-stripped strong validator still 304s.

view=global is anonymous + deterministic (file-store), so no auth mocking needed.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from website.app import create_app


def _get(client, **headers):
    return client.get("/api/graph", params={"view": "global"}, headers=headers or None)


def test_graph_sets_private_cache_and_weak_etag():
    with TestClient(create_app()) as client:
        resp = _get(client)
    assert resp.status_code == 200, resp.text
    cc = resp.headers.get("cache-control", "")
    assert "private" in cc, f"per-user graph must be private; got {cc!r}"
    assert "max-age=30" in cc
    assert "stale-while-revalidate=300" in cc
    assert "public" not in cc, "graph must NEVER be public (CDN cross-user leak)"
    etag = resp.headers.get("etag", "")
    assert etag.startswith('W/"') and etag.endswith('"'), f"expected weak etag, got {etag!r}"


def test_graph_etag_304_roundtrip():
    with TestClient(create_app()) as client:
        first = _get(client)
        etag = first.headers["etag"]
        second = _get(client, **{"If-None-Match": etag})
    assert second.status_code == 304, second.text
    assert second.headers.get("etag") == etag
    cc = second.headers.get("cache-control", "")
    assert "private" in cc and "stale-while-revalidate=300" in cc


def test_graph_strong_inm_still_304s_under_weak_compare():
    """Cloudflare may echo our weak ETag back as its strong form; RFC 7232 weak
    comparison (shared if_none_match gate) must still 304 (mirrors /api/avatars)."""
    with TestClient(create_app()) as client:
        first = _get(client)
        weak = first.headers["etag"]      # W/"<hash>"
        strong = weak[2:]                  # "<hash>"
        second = _get(client, **{"If-None-Match": strong})
    assert second.status_code == 304, second.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && pytest tests/unit/website/test_graph_etag.py -v`
Expected: FAIL — no `etag` header and no 304 (handler returns a plain dict, 200 every time).

- [ ] **Step 3: Implement the ETag/cache contract in `graph_data`**

In `website/api/routes.py`, the handler currently starts:

```python
@router.get("/graph")
async def graph_data(
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
    view: str | None = None,
```

Add `request: Request` as the first parameter:

```python
@router.get("/graph")
async def graph_data(
    request: Request,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
    view: str | None = None,
```

Then replace the final `try/except` block (currently the last statement of the handler):

```python
    try:
        return await run_view_graph(
            user=user,
            view=view,  # type: ignore[arg-type]
            kasten_id=parsed_kasten_id,
            limit=limit,
            offset=offset,
            min_strength=min_strength,
        )
    except KastenNotFoundError:
        # BOLA mitigation: 403 (never reveal whether the kasten exists in
        # another tenant; mirrors ask_kasten / sandbox_routes pattern).
        raise HTTPException(status_code=403, detail="Forbidden") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

with:

```python
    try:
        payload = await run_view_graph(
            user=user,
            view=view,  # type: ignore[arg-type]
            kasten_id=parsed_kasten_id,
            limit=limit,
            offset=offset,
            min_strength=min_strength,
        )
    except KastenNotFoundError:
        # BOLA mitigation: 403 (never reveal whether the kasten exists in
        # another tenant; mirrors ask_kasten / sandbox_routes pattern).
        raise HTTPException(status_code=403, detail="Forbidden") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Conditional-request + private-cache contract (audit 2026-06-04).
    # `private` is mandatory: per-user graphs must never be edge-cached
    # (Cloudflare async-SWR, 2026-02-26, would otherwise serve A's graph to B).
    # ETag is a weak validator over the FINAL serialized body, so it reflects
    # the exact view/min_strength/limit slice the client received; weak so a
    # Cloudflare-rewritten validator still matches via if_none_match (RFC 7232).
    body = json.dumps(
        jsonable_encoder(payload), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    etag = 'W/"' + hashlib.blake2s(body, digest_size=16).hexdigest() + '"'
    cache_headers = {
        "Cache-Control": "private, max-age=30, stale-while-revalidate=300",
        "ETag": etag,
        "Vary": "Accept-Encoding",
    }
    if if_none_match(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=cache_headers)
    return Response(content=body, media_type="application/json", headers=cache_headers)
```

(No new imports: `json`, `hashlib`, `jsonable_encoder`, `Response`, `Request`, and `if_none_match` are already imported at the top of `routes.py`.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && pytest tests/unit/website/test_graph_etag.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the existing graph payload tests to confirm no regression**

Run: `pytest tests/integration/v2/test_kg_payload.py -v`
Expected: PASS — the trim tests call `r.json()`, which still works on the new `Response`.

- [ ] **Step 6: Commit**

```bash
git add website/api/routes.py tests/unit/website/test_graph_etag.py
git commit -m "feat: private cache + weak-ETag on /api/graph"
```

---

## PHASE 2 — Drop in-process compression (Caddy/Cloudflare own it)

> Compression moves to Caddy (`ops/caddy/Caddyfile:13` already has `encode zstd gzip`) + Cloudflare edge Brotli. On 1 vCPU, compressing inside the Python worker steals event-loop CPU. End-client payloads are unchanged because Cloudflare applies edge Brotli regardless of origin encoding.

### Task 2: Update the middleware-order pin and remove the compression block

**Files:**
- Modify: `tests/unit/website/test_middleware_chain_order.py`
- Modify: `website/app.py` (lines 458–472)

- [ ] **Step 1: Update the expected middleware order + add a no-compression guard (test-first)**

In `tests/unit/website/test_middleware_chain_order.py`, remove `"BrotliMiddleware",` from the list (line 20) so it reads:

```python
EXPECTED_MIDDLEWARE_ORDER: list[str] = [
    "MemoryGuardMiddleware",
    "PostResponseReleaseMiddleware",
    "AuthStatusHeadersMiddleware",
    "SessionMarkerCookieMiddleware",
    "AnonSessionCookieMiddleware",
    "Auth401RateMonitorMiddleware",
]
```

Update the module docstring (lines 3–9): delete the clause "Brotli must be the innermost compressor; " so the remaining text reads "The chain order is correctness-critical (AuthHeaders/SessionMarker/Auth401 must wrap the response after the body has been built; MemoryGuard must short-circuit BEFORE any route work happens)."

Append a new guard test at the end of the file:

```python
def test_no_app_level_compression_middleware():
    """Compression is owned by Caddy `encode zstd gzip` + Cloudflare edge Brotli
    (audit 2026-06-04). No ASGI compressor may sit in the app — on 1 vCPU it
    steals event-loop CPU, and a buffering compressor would risk the SSE
    heartbeat stream. This guard fails the build if one is re-added.
    """
    names = {m.cls.__name__ for m in create_app().user_middleware}
    assert "BrotliMiddleware" not in names, "drop brotli-asgi; Caddy/CF compress"
    assert "GZipMiddleware" not in names, "drop GZipMiddleware; Caddy/CF compress"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && pytest tests/unit/website/test_middleware_chain_order.py -v`
Expected: FAIL — `test_middleware_registration_order_pinned` sees an extra `BrotliMiddleware`, and `test_no_app_level_compression_middleware` finds it registered.

- [ ] **Step 3: Remove the in-process compression block from `create_app`**

In `website/app.py`, delete lines 458–472 in their entirety — the comment block plus the `try/except` that registers `BrotliMiddleware`/`GZipMiddleware`:

```python
    # WAVE-C 1c-A.4 (D-KG-8): payload compression with Accept-Encoding
    # negotiation. brotli-asgi serves br when supported, falls back to gzip,
    # else identity. Compresses /api/graph (often >100KB) by ~3-5x. Threshold
    # = 1024 bytes so tiny health-check responses skip compression.
    try:
        from brotli_asgi import BrotliMiddleware

        app.add_middleware(BrotliMiddleware, minimum_size=1024, quality=4)
    except ImportError:
        # Fallback: stdlib GZipMiddleware. Lower compression ratio but no
        # extra dep. Logged once at startup so the deploy bot can flag.
        from fastapi.middleware.gzip import GZipMiddleware

        app.add_middleware(GZipMiddleware, minimum_size=1024)
        logger.info("brotli-asgi unavailable — using GZipMiddleware fallback")

```

Leave the following `# API routes` / `app.include_router(...)` lines untouched.

- [ ] **Step 4: Run to verify it passes (and the ASGI matrix is unaffected)**

Run: `pytest tests/unit/website/test_middleware_chain_order.py tests/unit/website/test_middleware_asgi_matrix.py -v`
Expected: PASS — the matrix file never registered Brotli, so it is unaffected.

- [ ] **Step 5: Commit**

```bash
git add website/app.py tests/unit/website/test_middleware_chain_order.py
git commit -m "chore: drop in-process compression; Caddy and CF own it"
```

### Task 3: Update `test_kg_payload.py` and remove the dead `brotli-asgi` dep

**Files:**
- Modify: `tests/integration/v2/test_kg_payload.py`
- Modify: `ops/requirements.txt` (lines 52–57)
- Modify: `tests/unit/website/test_middleware_asgi_matrix.py` (docstring, line 4)

- [ ] **Step 1: Rewrite the test fixture and compression-coupled tests**

In `tests/integration/v2/test_kg_payload.py`:

(a) Replace the module docstring (lines 1–10) with:

```python
"""WAVE-C 1c-A.4 — /api/graph payload trim + compressibility budget.

Locked decisions covered:
- D-KG-9: drop embedding, raw scores, raw timestamps, model_version
- Payload size budget: the trimmed graph must compress well under 300 KB at
  1k nodes (compression itself is now owned by Caddy/Cloudflare, audit
  2026-06-04 — we verify the body is *compressible* under budget, not that the
  app compresses it).

Strategy: black-box the response shape via FastAPI TestClient + monkey-patch
the upstream graph loader. Avoids any Supabase round-trip (these are NOT
@live tests) so they run in the regular suite.
"""
```

(b) Replace `_build_test_app` (lines 18–37) with a version that registers **no** compression middleware (mirrors new production wiring):

```python
def _build_test_app():
    """Construct a minimal FastAPI app exposing /api/graph against an
    in-memory file-store stub. Avoids Supabase / auth / lifespan startup.
    Compression is owned by Caddy/Cloudflare now, so no compressor is wired
    here (audit 2026-06-04).
    """
    from fastapi import FastAPI

    from website.api import routes as routes_module

    app = FastAPI()
    app.include_router(routes_module.router)
    return app
```

(c) Delete the entire "Brotli content-encoding negotiation" section — the comment header (line 196) and both tests `test_brotli_negotiation_returns_br` (lines 199–236) and `test_gzip_negotiation_returns_gzip` (lines 239–259).

(d) Keep `test_payload_trims_embedding_via_endpoint` unchanged.

(e) Replace `test_payload_under_300kb_at_1k_nodes` (lines 294–343) with a version that compresses the body itself (no reliance on app/Content-Length):

```python
def test_payload_under_300kb_brotli_at_1k_nodes(monkeypatch) -> None:
    """The trimmed /api/graph body must compress to <300 KB at 1k nodes so the
    Caddy/Cloudflare layer keeps it small at 10k-user scale. We brotli-compress
    the response body ourselves (the app no longer compresses)."""
    import brotli  # type: ignore

    import website.api.routes as routes_module

    n = 1000
    fixture = {
        "nodes": [
            {
                "id": f"n-{i}",
                "name": f"node-{i}",
                "group": "web",
                "summary": "summary " * 20,
                "tags": [f"tag-{i % 25}"],
                "url": f"https://example.com/{i}",
                "date": "2026-01-01",
                "node_date": "2026-01-01",
            }
            for i in range(n)
        ],
        "links": [
            {
                "source": f"n-{i}",
                "target": f"n-{(i + 1) % n}",
                "relation": "shared_tag",
                "connection_strength": 0.65,
            }
            for i in range(n)
        ],
    }
    monkeypatch.setattr(routes_module, "get_graph", lambda: fixture)
    monkeypatch.setattr(routes_module, "_enrich_graph_with_analytics", lambda d, **_kw: d)

    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/api/graph", params={"view": "global"})
    assert r.status_code == 200
    raw_size = len(brotli.compress(r.content, quality=4))
    assert raw_size < 300 * 1024, (
        f"brotli-compressed /api/graph payload is {raw_size} bytes at 1k nodes; "
        f"budget is <300 KB"
    )
```

- [ ] **Step 2: Remove the dead `brotli-asgi` dependency (keep the `brotli` codec)**

In `ops/requirements.txt`, lines 52–57 currently are:

```
# WAVE-C 1c-A.4: payload compression for /api/graph (D-KG-8). brotli-asgi
# does Accept-Encoding negotiation (br > gzip > identity); brotli is the
# native codec. If brotli-asgi is unavailable at runtime (older lockfiles),
# the app falls back to stdlib gzip.
brotli>=1.1
brotli-asgi>=1.4
```

Replace with (drop `brotli-asgi`; `brotli` stays — `website/core/safe_http.py` decodes brotli responses from upstream fetches):

```
# brotli native codec — used by safe_http to decode br responses from upstream
# fetches (Wikipedia/Google) and by tests to size graph payloads. In-process
# response compression was removed 2026-06-04; Caddy `encode zstd gzip` +
# Cloudflare edge Brotli own it now.
brotli>=1.1
```

- [ ] **Step 3: Fix the stale docstring in the ASGI matrix test**

In `tests/unit/website/test_middleware_asgi_matrix.py`, line 4, change `(Brotli + the 5 converted classes)` to `(the 5 converted pure-ASGI classes)`.

- [ ] **Step 4: Run the affected suites**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && pytest tests/integration/v2/test_kg_payload.py tests/unit/website/test_middleware_asgi_matrix.py -v`
Expected: PASS — trim tests + the rewritten size budget pass; no Brotli imports remain.

- [ ] **Step 5: Confirm no remaining `brotli_asgi` import anywhere**

Run: `grep -rn "brotli_asgi" website tests ops` (PowerShell: `Select-String -Pattern "brotli_asgi" -Path website,tests,ops -Recurse`)
Expected: no matches.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/v2/test_kg_payload.py ops/requirements.txt tests/unit/website/test_middleware_asgi_matrix.py
git commit -m "test: retire brotli-asgi negotiation tests and dep"
```

### Task 4: Verify the SSE heartbeat path still streams (protected knob)

**Files:** none changed — verification only.

- [ ] **Step 1: Run the SSE streaming matrix test**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && pytest tests/unit/website/test_middleware_asgi_matrix.py::test_sse_streaming_passes_through_middleware -v`
Expected: PASS — confirms the middleware chain (now with no compressor) passes a `text/event-stream` response through chunk-by-chunk.

- [ ] **Step 2: Confirm the SSE responses still declare anti-buffering headers**

Run: `grep -n "X-Accel-Buffering\|text/event-stream" website/api/chat_routes.py` (PowerShell: `Select-String -Pattern "X-Accel-Buffering|text/event-stream" -Path website/api/chat_routes.py`)
Expected: the StreamingResponse blocks still set `media_type="text/event-stream"` and `X-Accel-Buffering: no` — unchanged by this plan.

- [ ] **Step 3: Manual smoke (run before deploy)**

Document in the PR description: against a locally running instance (`ENV=dev python run.py`), open `/knowledge-graph` and the chat UI; confirm streamed answers arrive token-by-token (not in one buffered burst) and the graph loads. Rationale: Caddy `encode` is flush-aware and already fronted SSE in production with `X-Accel-Buffering: no`; removing the app compressor only reduces buffering risk. No code change — this is a pre-deploy gate.

- [ ] **Step 4: No commit** (verification task; nothing changed).

---

## PHASE 3 — Retune the client settle (faster, calmer, still "alive")

### Task 5: Tier `warmupTicks` by node count and shorten `cooldownTime`

**Files:**
- Test: `tests/js/knowledge_graph/settle_tuning.test.js` (create)
- Modify: `website/features/knowledge_graph/js/app.js` (fence before line 103; `initGraph` lines 1148–1149)

- [ ] **Step 1: Write the failing test**

Create `tests/js/knowledge_graph/settle_tuning.test.js`:

```javascript
/**
 * KG settle tuning (audit 2026-06-04): pre-settle warmup is tiered by node
 * count (floor 60, cap 250) so the first painted frame is near-final without
 * delaying first paint on big graphs; the visible drift is shortened from
 * 2500ms to GRAPH_COOLDOWN_MS. "Alive but fast."
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const APP_SRC = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8',
);

// Extract the pure-helper fence and eval it (same harness as sibling tests).
const FENCE = APP_SRC.match(
  /\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//,
)[1];
const exported = new Function(
  FENCE + '\nreturn { warmupTicksForNodeCount, GRAPH_COOLDOWN_MS };',
)();

describe('settle tuning helpers', () => {
  it('floors warmup at 60 for tiny graphs', () => {
    expect(exported.warmupTicksForNodeCount(0)).toBe(60);
    expect(exported.warmupTicksForNodeCount(10)).toBe(60);
  });
  it('scales warmup with node count in the middle band', () => {
    expect(exported.warmupTicksForNodeCount(200)).toBe(120);
    expect(exported.warmupTicksForNodeCount(300)).toBe(180);
  });
  it('caps warmup at 250 for large graphs (bounds first-paint delay)', () => {
    expect(exported.warmupTicksForNodeCount(800)).toBe(250);
    expect(exported.warmupTicksForNodeCount(5000)).toBe(250);
  });
  it('tolerates non-numeric input', () => {
    expect(exported.warmupTicksForNodeCount(undefined)).toBe(60);
    expect(exported.warmupTicksForNodeCount('x')).toBe(60);
  });
  it('shortens the visible cooldown from the old 2500ms', () => {
    expect(exported.GRAPH_COOLDOWN_MS).toBeLessThanOrEqual(1200);
    expect(exported.GRAPH_COOLDOWN_MS).toBeGreaterThanOrEqual(800);
  });
});

describe('settle tuning is wired into initGraph', () => {
  it('initGraph uses the tiered warmup, not the old flat .warmupTicks(100)', () => {
    expect(APP_SRC).toMatch(/\.warmupTicks\(\s*warmupTicksForNodeCount\(/);
    expect(APP_SRC).not.toMatch(/\.warmupTicks\(\s*100\s*\)/);
  });
  it('initGraph uses GRAPH_COOLDOWN_MS, not the old flat .cooldownTime(2500)', () => {
    expect(APP_SRC).toMatch(/\.cooldownTime\(\s*GRAPH_COOLDOWN_MS\s*\)/);
    expect(APP_SRC).not.toMatch(/\.cooldownTime\(\s*2500\s*\)/);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && npx vitest run tests/js/knowledge_graph/settle_tuning.test.js`
Expected: FAIL — `warmupTicksForNodeCount`/`GRAPH_COOLDOWN_MS` are not defined in the fence; `initGraph` still uses the flat literals.

- [ ] **Step 3: Add the helpers to the `test-exports` fence**

In `website/features/knowledge_graph/js/app.js`, immediately BEFORE the `/* test-exports:end */` marker (line 103), insert:

```javascript
// Settle tuning (audit 2026-06-04): tier the off-screen pre-settle by node
// count so the FIRST painted frame is near-final (no chaotic churn), capped so
// first paint is never delayed on big graphs / low-end devices. The visible
// drift-to-rest is governed by GRAPH_COOLDOWN_MS (down from the old 2500ms) —
// keeps the "alive" feel but reads as "ready" not "loading".
const GRAPH_COOLDOWN_MS = 1100;
function warmupTicksForNodeCount(n) {
  const count = Number(n) || 0;
  return Math.min(250, Math.max(60, Math.round(count * 0.6)));
}
```

- [ ] **Step 4: Wire the helpers into `initGraph`**

In `website/features/knowledge_graph/js/app.js`, line 1148, change:

```javascript
      .warmupTicks(100)
      .cooldownTime(2500)
```

to:

```javascript
      .warmupTicks(warmupTicksForNodeCount(graphData.nodes.length))
      .cooldownTime(GRAPH_COOLDOWN_MS)
```

(Leave `.d3AlphaDecay(0.025)`, `.d3AlphaMin(0.01)`, `.linkDirectionalParticles(1)`, and the rest of `initGraph` unchanged — particles and the gentle drift stay.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && npx vitest run tests/js/knowledge_graph/settle_tuning.test.js`
Expected: PASS.

- [ ] **Step 6: Run the existing KG JS tests for no regression**

Run: `npx vitest run tests/js/knowledge_graph/`
Expected: PASS (filter_ux, web_worker_perf, settle_tuning all green).

- [ ] **Step 7: Commit**

```bash
git add website/features/knowledge_graph/js/app.js tests/js/knowledge_graph/settle_tuning.test.js
git commit -m "feat: faster calmer knowledge-graph settle on load"
```

---

## PHASE 4 — Flip-metric observability (no behavior change)

### Task 6: Server logs — node count + analytics wall-time

**Files:**
- Test: `tests/unit/website/test_graph_metrics_logging.py` (create)
- Modify: `website/api/routes.py` (`graph_data` ~line 1318; `_enrich_graph_with_analytics` ~lines 213–217)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/website/test_graph_metrics_logging.py`:

```python
"""Flip-metric logs (audit 2026-06-04) — watch these to decide when scale-gate
work trips: kg_graph_nodes (per-user node count) and kg_analytics_ms (igraph
wall-time). Observability only; no behavior change."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from website.app import create_app


def test_graph_response_logs_node_count(caplog):
    with caplog.at_level(logging.INFO, logger="website.api"):
        with TestClient(create_app()) as client:
            resp = client.get("/api/graph", params={"view": "global"})
    assert resp.status_code == 200, resp.text
    assert any("kg_graph_nodes" in r.getMessage() for r in caplog.records), \
        "expected a kg_graph_nodes flip-metric log line"


def test_analytics_compute_logs_wall_time(caplog):
    """A fresh (unique) topology misses the metrics memo and computes igraph
    analytics, which must log kg_analytics_ms. Skips if igraph is unavailable."""
    from website.api.routes import _enrich_graph_with_analytics

    graph = {
        "nodes": [
            {"id": "ulo-a", "name": "A", "group": "web", "tags": []},
            {"id": "ulo-b", "name": "B", "group": "web", "tags": []},
        ],
        "links": [
            {"source": "ulo-a", "target": "ulo-b", "relation": "shared_tag",
             "connection_strength": 0.6},
        ],
    }
    with caplog.at_level(logging.INFO, logger="website.api"):
        out = _enrich_graph_with_analytics(graph, min_strength=None)
    if out.get("meta", {}).get("analytics_status") != "ok":
        pytest.skip("igraph analytics unavailable in this env")
    assert any("kg_analytics_ms" in r.getMessage() for r in caplog.records), \
        "expected a kg_analytics_ms flip-metric log line on a cache-miss compute"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && pytest tests/unit/website/test_graph_metrics_logging.py -v`
Expected: FAIL — neither log line exists yet.

- [ ] **Step 3: Add the node-count log to `graph_data`**

In `website/api/routes.py`, inside `graph_data`, immediately AFTER the `try/except` that assigns `payload` (added in Task 1) and BEFORE the `body = json.dumps(...)` line, insert:

```python
    # Flip-metric #2 (audit 2026-06-04): node count per response. Watch the max
    # per-user value; >~500 trips the personal-subgraph progressive-reveal work.
    logger.info(
        "kg_graph_nodes view=%s nodes=%d",
        view or "auto",
        len((payload or {}).get("nodes", []) or []),
    )
```

- [ ] **Step 4: Add the analytics wall-time log to `_enrich_graph_with_analytics`**

In `website/api/routes.py`, in `_enrich_graph_with_analytics`, the cache-miss branch currently reads:

```python
        metrics = get_cached_metrics(graph_hash)
        if metrics is None:
            from website.features.kg_features.analytics import compute_graph_metrics
            kg_graph = KGGraph(**graph_dict)
            metrics = compute_graph_metrics(kg_graph)
            put_cached_metrics(graph_hash, metrics)
```

Replace with:

```python
        metrics = get_cached_metrics(graph_hash)
        if metrics is None:
            from website.features.kg_features.analytics import compute_graph_metrics
            kg_graph = KGGraph(**graph_dict)
            _t0 = time.perf_counter()
            metrics = compute_graph_metrics(kg_graph)
            # Flip-metric #3 (audit 2026-06-04): igraph wall-time on a cache
            # miss. Watch p95; >1s for any graph (or >~500 shared nodes) trips
            # the materialized-analytics-columns work.
            logger.info(
                "kg_analytics_ms ms=%.1f nodes=%d",
                (time.perf_counter() - _t0) * 1000.0,
                len(graph_dict.get("nodes", []) or []),
            )
            put_cached_metrics(graph_hash, metrics)
```

(`time` is already imported at the top of `routes.py`.)

- [ ] **Step 5: Run to verify it passes**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && pytest tests/unit/website/test_graph_metrics_logging.py -v`
Expected: PASS (or the analytics test skips if igraph is absent).

- [ ] **Step 6: Commit**

```bash
git add website/api/routes.py tests/unit/website/test_graph_metrics_logging.py
git commit -m "chore: log graph node-count and analytics wall-time"
```

### Task 7: Client log — payload size + load time

**Files:**
- Test: `tests/js/knowledge_graph/graph_load_metric.test.js` (create)
- Modify: `website/features/knowledge_graph/js/app.js` (fence before line 103; `loadGraphData` lines 717–736)

- [ ] **Step 1: Write the failing test**

Create `tests/js/knowledge_graph/graph_load_metric.test.js`:

```javascript
/**
 * KG client load flip-metric (audit 2026-06-04): one console line per graph
 * load with decoded payload size + wall time + node count, so the LOD /
 * progressive-reveal thresholds can be watched from real post-CDN client data.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const APP_SRC = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8',
);
const FENCE = APP_SRC.match(
  /\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//,
)[1];
const exported = new Function(
  FENCE + '\nreturn { formatGraphLoadMetric };',
)();

describe('formatGraphLoadMetric', () => {
  it('formats bytes as KB, ms rounded, node count', () => {
    const s = exported.formatGraphLoadMetric({ bytes: 204800, ms: 123.7, nodes: 42 });
    expect(s).toContain('42 nodes');
    expect(s).toContain('200 KB');
    expect(s).toContain('124 ms');
  });
  it('tolerates missing/garbage fields without throwing', () => {
    expect(() => exported.formatGraphLoadMetric(undefined)).not.toThrow();
    expect(exported.formatGraphLoadMetric({})).toContain('0 nodes');
  });
});

describe('client metric is wired into loadGraphData', () => {
  it('loadGraphData logs the formatted metric', () => {
    expect(APP_SRC).toMatch(/formatGraphLoadMetric\(/);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && npx vitest run tests/js/knowledge_graph/graph_load_metric.test.js`
Expected: FAIL — `formatGraphLoadMetric` not defined; not referenced in `loadGraphData`.

- [ ] **Step 3: Add the formatter to the `test-exports` fence**

In `website/features/knowledge_graph/js/app.js`, immediately BEFORE the `/* test-exports:end */` marker (line 103, after the settle helpers from Task 5), insert:

```javascript
// Observability (audit 2026-06-04, flip-metric #1): one console line per graph
// load — decoded payload size + wall time + node count. Watched to decide when
// LOD/progressive-reveal trips (payload measured client-side, post-CDN).
function formatGraphLoadMetric(stats) {
  const kb = Math.round((Number(stats && stats.bytes) || 0) / 1024);
  const ms = Math.round(Number(stats && stats.ms) || 0);
  const nodes = Number(stats && stats.nodes) || 0;
  return '[kg] graph loaded: ' + nodes + ' nodes, ' + kb + ' KB, ' + ms + ' ms';
}
```

- [ ] **Step 4: Wire it into `loadGraphData`**

In `website/features/knowledge_graph/js/app.js`, `loadGraphData` begins (line 717):

```javascript
  function loadGraphData() {
    showOverlay('overlay-loading');
```

Change to capture a start timestamp:

```javascript
  function loadGraphData() {
    const _kgLoadT0 = (window.performance && performance.now) ? performance.now() : Date.now();
    showOverlay('overlay-loading');
```

Then locate the line `fullData = data;` (line 736) inside the `.then(data => {...})` handler and insert the metric log immediately after it:

```javascript
        fullData = data;
        try {
          const _ms = ((window.performance && performance.now) ? performance.now() : Date.now()) - _kgLoadT0;
          let _bytes;
          try { _bytes = new Blob([JSON.stringify(data)]).size; }
          catch (_e) { _bytes = JSON.stringify(data).length; }
          console.log(formatGraphLoadMetric({ bytes: _bytes, ms: _ms, nodes: (data.nodes || []).length }));
        } catch (_e) { /* metric must never break the load path */ }
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && npx vitest run tests/js/knowledge_graph/`
Expected: PASS (all KG JS tests).

- [ ] **Step 6: Commit**

```bash
git add website/features/knowledge_graph/js/app.js tests/js/knowledge_graph/graph_load_metric.test.js
git commit -m "chore: log client graph payload size and load time"
```

---

## Final verification (run before opening the PR)

- [ ] **Full backend suite (stubbed, no live):**
  Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\competent-cohen-74c95f && pytest tests/ -m "not live" -q`
  Expected: all pass (in particular `test_graph_etag`, `test_middleware_chain_order`, `test_kg_payload`, `test_graph_metrics_logging`).
- [ ] **Full KG JS suite:**
  Run: `npx vitest run tests/js/knowledge_graph/`
  Expected: all pass.
- [ ] **No stray compression imports:**
  Run: `grep -rn "brotli_asgi\|GZipMiddleware" website` — expected: no matches.
- [ ] **Manual:** `/knowledge-graph` loads with a calm ~1s settle; revisiting the page issues a `304` on `/api/graph` (DevTools Network); chat SSE streams token-by-token.

---

## Self-Review (completed by plan author)

**1. Spec coverage:**
- Item 1 (keystone ETag/private/SWR) → Phase 1 / Task 1. ✓
- Item 2 (drop in-process compression) → Phase 2 / Tasks 2–4 (incl. the 4 coupled test files + dep removal + SSE verification). ✓
- Item 3 (client settle retune) → Phase 3 / Task 5. ✓
- Item 4 (3 flip-metric logs) → Phase 4 / Tasks 6 (node-count + analytics-ms, server) & 7 (payload-size + load-time, client). ✓

**2. Placeholder scan:** No TBD/"add error handling"/"similar to Task N". Every code step shows full code; every deletion names exact functions + line ranges.

**3. Type/name consistency:** `warmupTicksForNodeCount`, `GRAPH_COOLDOWN_MS`, `formatGraphLoadMetric` are defined once (fence) and referenced with the same names in `initGraph`/`loadGraphData` and both JS tests. Log keys `kg_graph_nodes` / `kg_analytics_ms` match between impl and `test_graph_metrics_logging.py`. ETag is weak (`W/"…"`) in both impl and `test_graph_etag.py`.

**Deviations from the original ask (intentional, with rationale):**
- The ETag is computed from the **final serialized body in the handler**, not "cached alongside the payload in `graph_cache.py`". Reason: `run_view_graph` applies the exact `min_strength` filter AFTER the cache lookup, so two requests in the same cache bucket can have different bodies — a cache-fill-time ETag would 304 incorrectly. Hashing the final body (cheap blake2s over a small payload) is correct and avoids touching `graph_cache.py`.
- Dropping compression expanded to **4 test files + `ops/requirements.txt`** (not just `app.py`) because `test_middleware_chain_order.py` pins Brotli and `test_kg_payload.py` registers it + asserts negotiation. Resolved in-PR (no silent deferral).
