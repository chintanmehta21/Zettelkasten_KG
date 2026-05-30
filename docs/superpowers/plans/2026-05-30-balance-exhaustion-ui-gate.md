# Balance Exhaustion UI Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Zettel balance exhaustion in the UI — a quick pre-add balance check that pops the existing `ZKQuotaGate` modal, plus a fix so the post-202 async failure stops failing silently.

**Architecture:** Three pieces, atomic server gate stays the sole authority. (1) Normalize the async failed-op envelope in the shared poller so the inner quota detail reaches every consumer's catch. (2) Extend `ZKQuotaGate` with one shared `precheck()` (pre-flight balance read → modal if exhausted) + `extractQuotaDetail()` (robust backstop), wired into Home / My Zettels / Mobile. (3) New read-only `GET /api/quota/snapshot` wrapping `FunctionalGates.quota_snapshot`.

> **Spec refinement (vs `2026-05-30-balance-exhaustion-ui-design.md` §4.2b):** the spec described a single `guard({action})` wrapper. During planning the three surfaces were found to build optimistic skeleton UI around the submit, making an action-wrapping guard invasive. This plan instead ships the SAME single shared gate as two composable entry points — `precheck()` (pre-flight) + `extractQuotaDetail()` (backstop). Identical behavior, identical "one gate, all surfaces" principle, minimal diff. No architectural or infra change.

**Tech Stack:** Python 3.12 / FastAPI (pytest, `asyncio_mode=auto`); vanilla browser JS (Vitest + jsdom, tests in `tests/js/**`). Existing modules: `website/static/js/add_zettel_api.js`, `website/features/functional_gates/js/quota_gate.js`, `website/features/functional_gates/gates.py`.

---

## File Structure

**Create:**
- `website/api/quota_routes.py` — thin FastAPI router for `GET /api/quota/snapshot` (balance logic stays in `functional_gates`).
- `tests/js/functional_gates/extract_quota_detail.test.js` — `extractQuotaDetail` unit tests.
- `tests/js/functional_gates/precheck.test.js` — `precheck` unit tests (mocked fetch).
- `tests/js/add_zettel/normalize_failure.test.js` — async-failure normalizer unit tests.
- `tests/js/functional_gates/wiring.test.js` — source-assertion tests that all 3 surfaces call `precheck` + `extractQuotaDetail`.
- `tests/unit/api/test_quota_routes.py` — endpoint unit tests.

**Modify:**
- `website/static/js/add_zettel_api.js` — add `_normalizeFailure`, use it in `pollAccepted`'s `failed` branch, export it.
- `website/features/functional_gates/js/quota_gate.js` — add `extractQuotaDetail` + `precheck` to `window.ZKQuotaGate`.
- `website/features/user_home/js/home.js` — precheck before submit; swap catch check to `extractQuotaDetail`.
- `website/features/user_zettels/js/user_zettels.js` — same.
- `website/mobile/js/summarizer.js` — precheck + quota handling in both catches (URL + document).
- `website/mobile/index.html` — include `quota_gate.css` + `quota_gate.js`.
- `website/app.py` — register `quota_router`.

---

## Task 1: Async-failure normalizer (Component 1 — the silent-failure fix)

**Files:**
- Modify: `website/static/js/add_zettel_api.js`
- Test: `tests/js/add_zettel/normalize_failure.test.js`

**Background:** `pollAccepted` (~line 97) currently sets `failErr.detail = next.detail || next.error || next`. For an async failed op the body is `{status:'failed', error:<RFC9457 problem>, quality, ...}`, so `failErr.detail` becomes the problem wrapper, whose `.code` is the hyphen slug `"quota-exhausted"`, not the inner `detail.code:"quota_exhausted"` consumers check. We extract the inner detail + real title into a tested helper.

- [ ] **Step 1: Write the failing test**

Create `tests/js/add_zettel/normalize_failure.test.js`:

```js
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(
  resolve(__dirname, '../../../website/static/js/add_zettel_api.js'),
  'utf8',
);

function load() {
  delete window.ZKAddZettel;
  // eslint-disable-next-line no-new-func
  new Function('window', SRC).call(window, window);
  return window.ZKAddZettel;
}

describe('ZKAddZettel._normalizeFailure', () => {
  let api;
  beforeEach(() => { api = load(); });

  it('extracts the inner quota detail from an async failed-op envelope', () => {
    const next = {
      status: 'failed',
      operation_id: 'op1',
      error: {
        type: '.../quota-exhausted',
        title: 'You have used your included zettels.',
        status: 402,
        detail: { code: 'quota_exhausted', meter: 'zettel', recommended_products: ['zettel_10'] },
        code: 'quota-exhausted',
      },
    };
    const n = api._normalizeFailure(next);
    expect(n.detail.code).toBe('quota_exhausted');
    expect(n.detail.meter).toBe('zettel');
    expect(n.message).toBe('You have used your included zettels.');
  });

  it('uses the problem title for non-quota failures (string detail)', () => {
    const next = {
      status: 'failed',
      error: { title: 'Insufficient content', status: 422,
               detail: 'Could not extract enough content.', code: 'insufficient-content' },
    };
    const n = api._normalizeFailure(next);
    expect(n.message).toBe('Insufficient content');
    // string detail => keep the problem object as detail (no false quota match)
    expect(n.detail.code).toBe('insufficient-content');
  });

  it('falls back to a generic message when no title is present', () => {
    const n = api._normalizeFailure({ status: 'failed' });
    expect(n.message).toBe('Summary failed.');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/js/add_zettel/normalize_failure.test.js`
Expected: FAIL — `api._normalizeFailure is not a function`.

- [ ] **Step 3: Add the helper and use it**

In `website/static/js/add_zettel_api.js`, add this function near `cleanProblemDetail` (after it):

```js
  // Normalize a terminal failed-op envelope ({status:'failed', error:<RFC9457
  // problem>, ...}) into the SAME shape a sync 4xx rejection produces, so one
  // consumer catch works for both paths. Inner object `detail` (quota) is
  // surfaced directly; a string `detail` keeps the problem object (no false
  // quota match). Title becomes the user-facing message.
  function _normalizeFailure(next) {
    var problem = (next && typeof next.error === 'object' && next.error) ? next.error : next;
    var inner = (problem && typeof problem.detail === 'object' && problem.detail) ? problem.detail : null;
    return {
      message: (problem && problem.title) || cleanProblemDetail(next, 'Summary failed.'),
      detail: inner || problem || next,
      problem: problem,
    };
  }
```

Replace the `failed` branch inside `pollAccepted` (currently):

```js
        if (next.status === 'failed') {
          var failErr = new Error(cleanProblemDetail(next, 'Summary failed.'));
          failErr.status = 200;
          failErr.detail = next.detail || next.error || next;
          failErr.problem = next;
          throw failErr;
        }
```

with:

```js
        if (next.status === 'failed') {
          var n = _normalizeFailure(next);
          var failErr = new Error(n.message);
          failErr.status = 200;
          failErr.detail = n.detail;
          failErr.problem = n.problem;
          throw failErr;
        }
```

Add `_normalizeFailure` to the public object (so it is testable). Change:

```js
  window.ZKAddZettel = {
    add: add,
    uploadDocument: uploadDocument,
    makeActionId: makeActionId,
    continueInBackground: continueInBackground,
    _parseResponse: parseResponse
  };
```

to additionally expose it:

```js
  window.ZKAddZettel = {
    add: add,
    uploadDocument: uploadDocument,
    makeActionId: makeActionId,
    continueInBackground: continueInBackground,
    _parseResponse: parseResponse,
    _normalizeFailure: _normalizeFailure
  };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/js/add_zettel/normalize_failure.test.js`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add website/static/js/add_zettel_api.js tests/js/add_zettel/normalize_failure.test.js
git commit -m "fix: normalize async failed-op envelope for quota surfacing"
```

---

## Task 2: `GET /api/quota/snapshot` endpoint (Component 3)

**Files:**
- Create: `website/api/quota_routes.py`
- Modify: `website/app.py` (register router)
- Test: `tests/unit/api/test_quota_routes.py`

**Background:** `FunctionalGates.quota_snapshot(*, profile_id, feature, plan=None) -> QuotaSnapshot` (read-only; `gates.py:178`) returns `effective_available`, `remaining_plan`, `remaining_wallet`. Auth via `get_current_user` (`website/api/auth.py:159`; raises 401 on missing/invalid/expired). `FEATURES = ("zettel","kasten","rag_question")` (`functional_gates/config.py:58`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_quota_routes.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.api.auth import get_current_user


class _FakeSnap:
    def __init__(self, effective_available, remaining_plan, remaining_wallet):
        self.feature = "zettel"
        self.effective_available = effective_available
        self.remaining_plan = remaining_plan
        self.remaining_wallet = remaining_wallet


class _FakeGates:
    def __init__(self, snap):
        self._snap = snap
        self.consume_called = False

    async def quota_snapshot(self, *, profile_id, feature, plan=None):
        return self._snap

    async def reserve_and_consume(self, *args, **kwargs):  # must never be called
        self.consume_called = True
        raise AssertionError("snapshot endpoint must not consume")


def _client(monkeypatch, snap, sub="11111111-1111-1111-1111-111111111111"):
    import website.api.quota_routes as qr
    gates = _FakeGates(snap)
    monkeypatch.setattr(qr, "get_functional_gates", lambda: gates)
    app = FastAPI()
    app.include_router(qr.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": sub}
    return TestClient(app), gates


def test_returns_effective_available(monkeypatch):
    client, gates = _client(monkeypatch, _FakeSnap(7, 5, 2))
    r = client.get("/api/quota/snapshot?feature=zettel")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "feature": "zettel", "effective_available": 7,
        "remaining_plan": 5, "remaining_wallet": 2,
    }
    assert gates.consume_called is False
    assert r.headers["cache-control"] == "private, no-store"


def test_invalid_feature_422(monkeypatch):
    client, _ = _client(monkeypatch, _FakeSnap(7, 5, 2))
    r = client.get("/api/quota/snapshot?feature=bogus")
    assert r.status_code == 422


def test_non_uuid_sub_returns_null(monkeypatch):
    client, _ = _client(monkeypatch, _FakeSnap(7, 5, 2), sub="zoro")
    r = client.get("/api/quota/snapshot?feature=zettel")
    assert r.status_code == 200
    assert r.json()["effective_available"] is None


def test_auth_required_401(monkeypatch):
    # No dependency override -> real get_current_user with no token -> 401.
    import website.api.quota_routes as qr
    monkeypatch.setattr(qr, "get_functional_gates", lambda: _FakeGates(_FakeSnap(1, 1, 0)))
    app = FastAPI()
    app.include_router(qr.router)
    r = TestClient(app).get("/api/quota/snapshot?feature=zettel")
    assert r.status_code == 401


def test_payload_has_no_extra_fields(monkeypatch):
    client, _ = _client(monkeypatch, _FakeSnap(0, 0, 0))
    body = client.get("/api/quota/snapshot?feature=zettel").json()
    assert set(body.keys()) == {"feature", "effective_available", "remaining_plan", "remaining_wallet"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\busy-spence-2816ad ; python -m pytest tests/unit/api/test_quota_routes.py -q`
Expected: FAIL — `ModuleNotFoundError: website.api.quota_routes`.

- [ ] **Step 3: Create the router**

Create `website/api/quota_routes.py`:

```python
"""Read-only quota snapshot for the client pre-add gate.

Thin adapter over ``FunctionalGates.quota_snapshot`` (read-only; no consume,
no row locks). Identity is derived strictly from the verified JWT subject —
no user/object id is accepted (BOLA-safe /me pattern). Authoritative quota
enforcement remains the atomic ``billing.pricing_reserve_and_consume`` RPC
reached via ``require_entitlement``; this endpoint never consumes.
"""
from __future__ import annotations

import uuid as _uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from website.api.auth import get_current_user
from website.features.functional_gates import get_functional_gates
from website.features.functional_gates.config import FEATURES

router = APIRouter(prefix="/api/quota", tags=["quota"])


def _profile_uuid(sub: str) -> str | None:
    try:
        return str(_uuid.UUID(sub))
    except (ValueError, AttributeError):
        return None


@router.get("/snapshot")
async def get_quota_snapshot(
    response: Response,
    user: Annotated[dict, Depends(get_current_user)],
    feature: Annotated[str, Query()],
) -> dict[str, Any]:
    """Return the caller's own remaining balance for ``feature`` (advisory).

    `effective_available` is null for a non-UUID subject (anonymous/Zoro
    mapping) — the client treats null as "unknown" and proceeds (fail-open).
    """
    if feature not in FEATURES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown feature {feature!r}",
        )

    response.headers["Cache-Control"] = "private, no-store"

    sub = str(user.get("sub") or "")
    profile_id = _profile_uuid(sub)
    if profile_id is None:
        return {
            "feature": feature, "effective_available": None,
            "remaining_plan": None, "remaining_wallet": None,
        }

    snap = await get_functional_gates().quota_snapshot(
        profile_id=profile_id, feature=feature,
    )
    return {
        "feature": feature,
        "effective_available": int(snap.effective_available),
        "remaining_plan": int(snap.remaining_plan),
        "remaining_wallet": int(snap.remaining_wallet),
    }
```

- [ ] **Step 4: Register the router in `website/app.py`**

Add the import next to the other API-router imports (after `website/app.py:39`):

```python
from website.api.quota_routes import router as quota_router
```

Add the registration next to the others (after `website/app.py:480` `app.include_router(profile_router)`):

```python
    app.include_router(quota_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\busy-spence-2816ad ; python -m pytest tests/unit/api/test_quota_routes.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add website/api/quota_routes.py website/app.py tests/unit/api/test_quota_routes.py
git commit -m "feat: add read-only quota snapshot endpoint"
```

---

## Task 3: `extractQuotaDetail` shared extractor (Component 2a)

**Files:**
- Modify: `website/features/functional_gates/js/quota_gate.js`
- Test: `tests/js/functional_gates/extract_quota_detail.test.js`

**Background:** consumers currently inline `err.detail.code === 'quota_exhausted'`. This single extractor recognizes the quota error across all shapes (sync detail, normalized async detail, raw failed-op body, hyphen-slug form) using **exact-equality only** (never substring) and returns the canonical underscore dict, else `null`.

- [ ] **Step 1: Write the failing test**

Create `tests/js/functional_gates/extract_quota_detail.test.js`:

```js
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(
  resolve(__dirname, '../../../website/features/functional_gates/js/quota_gate.js'),
  'utf8',
);

function load() {
  delete window.ZKQuotaGate;
  // eslint-disable-next-line no-new-func
  new Function('window', SRC).call(window, window);
  return window.ZKQuotaGate;
}

describe('ZKQuotaGate.extractQuotaDetail', () => {
  let g;
  beforeEach(() => { g = load(); });

  it('matches the sync/normalized detail dict', () => {
    const d = g.extractQuotaDetail({ detail: { code: 'quota_exhausted', meter: 'zettel' } });
    expect(d).toEqual({ code: 'quota_exhausted', meter: 'zettel', recommended_products: undefined });
  });

  it('matches a direct quota dict', () => {
    const d = g.extractQuotaDetail({ code: 'quota_exhausted', meter: 'kasten' });
    expect(d.meter).toBe('kasten');
  });

  it('matches a raw failed-op body via error.detail', () => {
    const d = g.extractQuotaDetail({ status: 'failed', error: {
      code: 'quota-exhausted', detail: { code: 'quota_exhausted', meter: 'zettel' } } });
    expect(d.code).toBe('quota_exhausted');
    expect(d.meter).toBe('zettel');
  });

  it('normalizes the hyphen-slug form to the underscore canonical', () => {
    const d = g.extractQuotaDetail({ code: 'quota-exhausted', detail: { meter: 'rag_question' } });
    expect(d.code).toBe('quota_exhausted');
    expect(d.meter).toBe('rag_question');
  });

  it('returns null for near-misses (no false positives)', () => {
    expect(g.extractQuotaDetail({ detail: { code: 'quota_warning', meter: 'zettel' } })).toBeNull();
    expect(g.extractQuotaDetail({ detail: { code: 'insufficient-content' }, title: 'quota? no' })).toBeNull();
    expect(g.extractQuotaDetail({ code: 'quota-exhausted' })).toBeNull(); // slug w/o meter
    expect(g.extractQuotaDetail(null)).toBeNull();
    expect(g.extractQuotaDetail('quota_exhausted')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/js/functional_gates/extract_quota_detail.test.js`
Expected: FAIL — `g.extractQuotaDetail is not a function`.

- [ ] **Step 3: Implement `extractQuotaDetail`**

In `website/features/functional_gates/js/quota_gate.js`, add this function just before the existing `isQuotaDetail` function:

```js
  // Single shared recognizer for the quota_exhausted condition across every
  // shape the error can arrive in. EXACT equality only (never substring) so a
  // future `quota_*` sibling (e.g. a soft-limit warning) cannot false-match.
  // Always returns the canonical underscore dict {code:'quota_exhausted',
  // meter, recommended_products} or null.
  // NOTE: tolerates two wire spellings of the quota code (top-level
  // 'quota-exhausted' slug + nested detail.code 'quota_exhausted') during the
  // quota-code canonicalization migration. Remove the slug arms after the
  // server canonicalization PR ships and its deprecation window closes
  // (tracking: server wire-format canonicalization follow-up, spec §8).
  function _asQuota(meter, recs) {
    return { code: 'quota_exhausted', meter: meter, recommended_products: recs };
  }
  function extractQuotaDetail(x) {
    if (!x || typeof x !== 'object') return null;
    // 1. direct canonical dict
    if (x.code === 'quota_exhausted' && x.meter) return x;
    // 2. error/body whose .detail is the canonical dict (sync + normalized async)
    var d = x.detail;
    if (d && typeof d === 'object' && d.code === 'quota_exhausted' && d.meter) return d;
    // 3. raw failed-op body: { error: <problem> }
    var p = (x.error && typeof x.error === 'object') ? x.error : null;
    if (p) {
      if (p.detail && typeof p.detail === 'object'
          && p.detail.code === 'quota_exhausted' && p.detail.meter) return p.detail;
      if (p.code === 'quota-exhausted' && p.detail && p.detail.meter) {
        return _asQuota(p.detail.meter, p.detail.recommended_products);
      }
    }
    // 4. hyphen-slug at this level with nested meter
    if (x.code === 'quota-exhausted' && d && typeof d === 'object' && d.meter) {
      return _asQuota(d.meter, d.recommended_products);
    }
    return null;
  }
```

Export it by adding to the `window.ZKQuotaGate` object:

```js
  window.ZKQuotaGate = {
    show: show,
    close: function () { closeWith('programmatic'); },
    isQuotaDetail: isQuotaDetail,
    extractQuotaDetail: extractQuotaDetail
  };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/js/functional_gates/extract_quota_detail.test.js`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add website/features/functional_gates/js/quota_gate.js tests/js/functional_gates/extract_quota_detail.test.js
git commit -m "feat: add shared extractQuotaDetail recognizer to quota gate"
```

---

## Task 4: `precheck` pre-flight gate (Component 2b)

**Files:**
- Modify: `website/features/functional_gates/js/quota_gate.js`
- Test: `tests/js/functional_gates/precheck.test.js`

**Background:** `precheck({feature, token, source}) -> Promise<boolean>`. Reads `GET /api/quota/snapshot`; returns `false` (blocked, modal shown) ONLY on a well-formed `effective_available <= 0`; returns `true` (proceed) on sufficient balance, `null`/unknown, OR any non-verdict (transport error / timeout / non-2xx / malformed) = fail-open. Collapses double-submits with a short in-flight de-dupe.

- [ ] **Step 1: Write the failing test**

Create `tests/js/functional_gates/precheck.test.js`:

```js
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(
  resolve(__dirname, '../../../website/features/functional_gates/js/quota_gate.js'),
  'utf8',
);

function load() {
  delete window.ZKQuotaGate;
  // eslint-disable-next-line no-new-func
  new Function('window', SRC).call(window, window);
  return window.ZKQuotaGate;
}

describe('ZKQuotaGate.precheck', () => {
  let g, shown;
  beforeEach(() => {
    g = load();
    shown = [];
    g.show = (opts) => { shown.push(opts); return Promise.resolve('dismiss'); };
  });

  function mockFetch(impl) { window.fetch = vi.fn(impl); }

  it('blocks and shows the modal when effective_available <= 0', async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ feature: 'zettel', effective_available: 0 }) }));
    const ok = await g.precheck({ feature: 'zettel', token: 't', source: 'home' });
    expect(ok).toBe(false);
    expect(shown).toHaveLength(1);
    expect(shown[0].detail).toEqual({ code: 'quota_exhausted', meter: 'zettel' });
  });

  it('proceeds when balance is sufficient (no modal)', async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ effective_available: 3 }) }));
    const ok = await g.precheck({ feature: 'zettel', token: 't' });
    expect(ok).toBe(true);
    expect(shown).toHaveLength(0);
  });

  it('fail-open proceeds on null (unknown) balance', async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ effective_available: null }) }));
    expect(await g.precheck({ feature: 'zettel', token: 't' })).toBe(true);
    expect(shown).toHaveLength(0);
  });

  it('fail-open proceeds on a non-2xx response', async () => {
    mockFetch(async () => ({ ok: false, status: 500, json: async () => ({}) }));
    expect(await g.precheck({ feature: 'zettel', token: 't' })).toBe(true);
    expect(shown).toHaveLength(0);
  });

  it('fail-open proceeds on a transport error', async () => {
    mockFetch(async () => { throw new Error('network down'); });
    expect(await g.precheck({ feature: 'zettel', token: 't' })).toBe(true);
    expect(shown).toHaveLength(0);
  });

  it('a well-formed 0 NEVER fails open (modal shown, blocked)', async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ effective_available: 0 }) }));
    expect(await g.precheck({ feature: 'zettel', token: 't' })).toBe(false);
  });

  it('collapses concurrent double-submits into one fetch', async () => {
    let calls = 0;
    mockFetch(async () => { calls += 1; return { ok: true, json: async () => ({ effective_available: 5 }) }; });
    const [a, b] = await Promise.all([
      g.precheck({ feature: 'zettel', token: 't' }),
      g.precheck({ feature: 'zettel', token: 't' }),
    ]);
    expect(a).toBe(true); expect(b).toBe(true);
    expect(calls).toBe(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/js/functional_gates/precheck.test.js`
Expected: FAIL — `g.precheck is not a function`.

- [ ] **Step 3: Implement `precheck`**

In `website/features/functional_gates/js/quota_gate.js`, add near the top of the IIFE (after `var _activeResolve = null;`):

```js
  var _snapInFlight = {};  // de-dupe concurrent pre-checks by feature+token
```

Add this function just before the `window.ZKQuotaGate = {...}` export:

```js
  // Pre-flight balance check. Resolves true => proceed (sufficient, unknown,
  // or any non-verdict = FAIL-OPEN); false => blocked (well-formed
  // effective_available <= 0) and the modal has been shown. The authoritative
  // atomic server gate still runs on the action regardless — this is advisory
  // UX only. A successful "0" payload is a VERDICT, never a fail-open.
  function precheck(opts) {
    opts = opts || {};
    var feature = opts.feature;
    var token = opts.token || '';
    var source = opts.source;
    var key = feature + '|' + token;
    if (_snapInFlight[key]) return _snapInFlight[key];

    var p = (function () {
      var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
      var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 1500) : null;
      return Promise.resolve()
        .then(function () {
          return window.fetch('/api/quota/snapshot?feature=' + encodeURIComponent(feature), {
            headers: token ? { Authorization: 'Bearer ' + token } : {},
            signal: ctrl ? ctrl.signal : undefined
          });
        })
        .then(function (resp) {
          if (timer) clearTimeout(timer);
          if (!resp || !resp.ok) return null;          // non-2xx => fail-open
          return resp.json();
        })
        .then(function (body) {
          var avail = (body && typeof body.effective_available === 'number')
            ? body.effective_available : null;
          if (avail !== null && avail <= 0) {
            show({ detail: { code: 'quota_exhausted', meter: feature }, source: source });
            return false;                              // verdict: blocked
          }
          return true;                                 // sufficient OR unknown
        })
        .catch(function () { if (timer) clearTimeout(timer); return true; });  // transport/timeout => fail-open
    })();

    _snapInFlight[key] = p;
    p.then(function () {
      setTimeout(function () { delete _snapInFlight[key]; }, 250);
    }, function () { delete _snapInFlight[key]; });
    return p;
  }
```

Add `precheck` to the export:

```js
  window.ZKQuotaGate = {
    show: show,
    close: function () { closeWith('programmatic'); },
    isQuotaDetail: isQuotaDetail,
    extractQuotaDetail: extractQuotaDetail,
    precheck: precheck
  };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/js/functional_gates/precheck.test.js`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add website/features/functional_gates/js/quota_gate.js tests/js/functional_gates/precheck.test.js
git commit -m "feat: add precheck pre-flight balance gate to quota gate"
```

---

## Task 5: Wire Home + My Zettels surfaces

**Files:**
- Modify: `website/features/user_home/js/home.js`
- Modify: `website/features/user_zettels/js/user_zettels.js`
- Test: `tests/js/functional_gates/wiring.test.js` (created here; mobile asserts added in Task 6)

**Background:** both surfaces already show `ZKQuotaGate` on `e.detail.code === 'quota_exhausted'` — Task 1 makes that fire on the async path, but we swap the inline check for the shared `extractQuotaDetail` so the hyphen-slug/raw-body shapes also match. We add `precheck` before the submit so exhaustion shows the modal BEFORE any work. `precheck` failing open means a snapshot blip never blocks a paying user.

- [ ] **Step 1: Write the failing source-assertion test**

Create `tests/js/functional_gates/wiring.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

function src(rel) {
  return readFileSync(resolve(__dirname, '../../../', rel), 'utf8');
}
const HOME = src('website/features/user_home/js/home.js');
const ZETTELS = src('website/features/user_zettels/js/user_zettels.js');

describe('quota gate wiring — Home & My Zettels', () => {
  it('home.js calls precheck and uses extractQuotaDetail', () => {
    expect(HOME).toMatch(/ZKQuotaGate\.precheck\s*\(/);
    expect(HOME).toMatch(/ZKQuotaGate\.extractQuotaDetail\s*\(/);
    // the brittle inline check is gone
    expect(HOME).not.toMatch(/e\.detail\.code\s*===\s*['"]quota_exhausted['"]/);
  });
  it('precheck runs before the add/upload call in home.js', () => {
    expect(HOME.indexOf('ZKQuotaGate.precheck')).toBeGreaterThan(-1);
    expect(HOME.indexOf('ZKQuotaGate.precheck'))
      .toBeLessThan(HOME.indexOf('ZKAddZettel.add'));
  });
  it('user_zettels.js calls precheck and uses extractQuotaDetail', () => {
    expect(ZETTELS).toMatch(/ZKQuotaGate\.precheck\s*\(/);
    expect(ZETTELS).toMatch(/ZKQuotaGate\.extractQuotaDetail\s*\(/);
    expect(ZETTELS).not.toMatch(/err\.detail\.code\s*===\s*['"]quota_exhausted['"]/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/js/functional_gates/wiring.test.js`
Expected: FAIL — `precheck(` not found in either file.

- [ ] **Step 3a: Home — add precheck before submit**

In `website/features/user_home/js/home.js`, immediately BEFORE the `var apiPromise = isDocument` assignment (the `ZKAddZettel.add/uploadDocument` call, ~line 1334), insert:

```js
    // Pre-flight balance gate (advisory; server stays authoritative). On a
    // well-formed exhausted verdict the modal is shown and we abort before any
    // skeleton/network work. Fail-open on any non-verdict.
    if (window.ZKQuotaGate && typeof window.ZKQuotaGate.precheck === 'function') {
      var _proceed = await window.ZKQuotaGate.precheck({
        feature: 'zettel', token: token, source: 'home:add-zettel'
      });
      if (!_proceed) {
        if (addError) addError.textContent = '';
        return;
      }
    }
```

- [ ] **Step 3b: Home — swap the catch check to the shared extractor**

In the same file, replace this line (~1494):

```js
      var quotaDetail = e && e.detail && e.detail.code === 'quota_exhausted' ? e.detail : null;
```

with:

```js
      var quotaDetail = (window.ZKQuotaGate && window.ZKQuotaGate.extractQuotaDetail)
        ? window.ZKQuotaGate.extractQuotaDetail(e) : null;
```

- [ ] **Step 3c: My Zettels — add precheck at the top of the submit path**

In `website/features/user_zettels/js/user_zettels.js`, locate `function addZettel(` and insert at the very top of its body (BEFORE any skeleton/spacer DOM creation), using the function's own `url`, `_token`, `file` vars:

```js
    if (window.ZKQuotaGate && typeof window.ZKQuotaGate.precheck === 'function') {
      var _proceed = await window.ZKQuotaGate.precheck({
        feature: 'zettel', token: _token, source: 'my-zettels:add-zettel'
      });
      if (!_proceed) { if (addUrlInput) addUrlInput.value = ''; return; }
    }
```

- [ ] **Step 3d: My Zettels — swap the catch check**

Replace this line (~1053):

```js
      var quotaDetail = err && err.detail && err.detail.code === 'quota_exhausted' ? err.detail : null;
```

with:

```js
      var quotaDetail = (window.ZKQuotaGate && window.ZKQuotaGate.extractQuotaDetail)
        ? window.ZKQuotaGate.extractQuotaDetail(err) : null;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/js/functional_gates/wiring.test.js`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add website/features/user_home/js/home.js website/features/user_zettels/js/user_zettels.js tests/js/functional_gates/wiring.test.js
git commit -m "feat: wire pre-add quota gate into home and my-zettels"
```

---

## Task 6: Wire Mobile surface

**Files:**
- Modify: `website/mobile/js/summarizer.js`
- Modify: `website/mobile/index.html`
- Test: `tests/js/functional_gates/wiring.test.js` (extend)

**Background:** mobile currently has NO quota handling — both catches call `showError` only — and `index.html` does not load the quota gate. Add the asset includes, a precheck before each submit, and quota handling in both catches (URL + document) that shows `ZKQuotaGate` and re-runs the submit on resume, falling back to `showError` for non-quota errors. `quota_gate.js` already falls back to a `/pricing` redirect if `ZKPricing` is absent (`quota_gate.js:142`), so mobile works without ZKPricing.

- [ ] **Step 1: Extend the wiring test (failing)**

Append to `tests/js/functional_gates/wiring.test.js`:

```js
describe('quota gate wiring — Mobile', () => {
  const MOBILE = readFileSync(
    resolve(__dirname, '../../../website/mobile/js/summarizer.js'), 'utf8');
  const INDEX = readFileSync(
    resolve(__dirname, '../../../website/mobile/index.html'), 'utf8');

  it('summarizer.js calls precheck and extractQuotaDetail', () => {
    expect(MOBILE).toMatch(/ZKQuotaGate\.precheck\s*\(/);
    expect(MOBILE).toMatch(/ZKQuotaGate\.extractQuotaDetail\s*\(/);
  });
  it('index.html loads the quota gate assets', () => {
    expect(INDEX).toMatch(/quota_gate\.js/);
    expect(INDEX).toMatch(/quota_gate\.css/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/js/functional_gates/wiring.test.js`
Expected: FAIL — mobile assertions fail.

- [ ] **Step 3a: Add a shared quota-or-error helper + precheck in `summarizer.js`**

In `website/mobile/js/summarizer.js`, inside the IIFE (near the other helpers, before `attach`), add:

```js
  // Show the quota modal for a quota error, else fall back to showError.
  function handleAddError(submitBtn, originalLabel, err, retry) {
    var qd = (window.ZKQuotaGate && window.ZKQuotaGate.extractQuotaDetail)
      ? window.ZKQuotaGate.extractQuotaDetail(err) : null;
    if (qd && window.ZKQuotaGate) {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = originalLabel; }
      window.ZKQuotaGate.show({ detail: qd, source: 'mobile:add', onResume: retry });
      return;
    }
    showError(submitBtn, originalLabel, err);
  }

  // Returns true if the caller should proceed (sufficient/unknown/fail-open),
  // false if blocked (modal shown). Re-enables the button on block.
  async function quotaProceed(submitBtn, originalLabel) {
    if (!(window.ZKQuotaGate && typeof window.ZKQuotaGate.precheck === 'function')) return true;
    var token = await getAuthToken();
    var ok = await window.ZKQuotaGate.precheck({ feature: 'zettel', token: token, source: 'mobile:add' });
    if (!ok && submitBtn) { submitBtn.disabled = false; submitBtn.textContent = originalLabel; }
    return ok;
  }
```

- [ ] **Step 3b: Use them in the document-upload handler**

In the `fileInput` change handler, replace:

```js
        if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Summarizing…'; }
        try {
          if (!window.ZKAddZettel || typeof window.ZKAddZettel.uploadDocument !== 'function') {
            throw new Error('ZKAddZettel helper not loaded');
          }
          var token = await getAuthToken();
          var data = await window.ZKAddZettel.uploadDocument({
            file: file,
            token: token,
            clientActionId: 'mobile-document',
            persist: true,
            surface: 'mobile',
          });
          redirectAfterSuccess(data);
        } catch (err) {
          showError(submitBtn, originalLabel, err);
          fileInput.value = '';
        }
```

with:

```js
        if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Summarizing…'; }
        try {
          if (!window.ZKAddZettel || typeof window.ZKAddZettel.uploadDocument !== 'function') {
            throw new Error('ZKAddZettel helper not loaded');
          }
          if (!(await quotaProceed(submitBtn, originalLabel))) { fileInput.value = ''; return; }
          var token = await getAuthToken();
          var data = await window.ZKAddZettel.uploadDocument({
            file: file,
            token: token,
            clientActionId: 'mobile-document',
            persist: true,
            surface: 'mobile',
          });
          redirectAfterSuccess(data);
        } catch (err) {
          handleAddError(submitBtn, originalLabel, err, function () { fileInput.dispatchEvent(new Event('change')); });
          fileInput.value = '';
        }
```

- [ ] **Step 3c: Use them in the URL-submit handler**

Replace:

```js
      try {
        if (!window.ZKAddZettel || typeof window.ZKAddZettel.add !== 'function') {
          throw new Error('ZKAddZettel helper not loaded');
        }
        var token = await getAuthToken();
        var data = await window.ZKAddZettel.add({
          url: url,
          token: token,
          clientActionId: 'mobile-url',
          persist: true,
          surface: 'mobile',
        });
        redirectAfterSuccess(data);
      } catch (err) {
        showError(submitBtn, originalLabel, err);
      }
```

with:

```js
      try {
        if (!window.ZKAddZettel || typeof window.ZKAddZettel.add !== 'function') {
          throw new Error('ZKAddZettel helper not loaded');
        }
        if (!(await quotaProceed(submitBtn, originalLabel))) return;
        var token = await getAuthToken();
        var data = await window.ZKAddZettel.add({
          url: url,
          token: token,
          clientActionId: 'mobile-url',
          persist: true,
          surface: 'mobile',
        });
        redirectAfterSuccess(data);
      } catch (err) {
        handleAddError(submitBtn, originalLabel, err, function () { form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true })); });
      }
```

- [ ] **Step 3d: Load the quota-gate assets in `website/mobile/index.html`**

The served path for these assets is `/functional-gates/...` (hyphen) — verified against the 5 desktop pages that already include them, e.g. `website/features/user_home/index.html:306-307`. `mobile/index.html` already loads `add_zettel_api.js` at line 44.

Add the CSS in `<head>` (next to the other `<link rel="stylesheet">` tags):

```html
<link rel="stylesheet" href="/functional-gates/css/quota_gate.css?v=20260530a">
```

Add the script immediately BEFORE the existing `<script src="/js/add_zettel_api.js...">` tag (line ~44), so `ZKQuotaGate` is defined before `summarizer.js` runs:

```html
<script src="/functional-gates/js/quota_gate.js?v=20260530a"></script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/js/functional_gates/wiring.test.js`
Expected: PASS (5 tests total).

- [ ] **Step 5: Commit**

```bash
git add website/mobile/js/summarizer.js website/mobile/index.html tests/js/functional_gates/wiring.test.js
git commit -m "feat: wire pre-add quota gate into mobile summarizer"
```

---

## Task 7: Cache-bust + full-suite verification

**Files:**
- Modify: HTML includes of the two modified JS assets (cache-bust `?v=` tokens).

**Background:** static JS is cache-busted via a `?v=<date>` query. Because Task 1 modifies `add_zettel_api.js` (`?v=20260522a`) and Tasks 3–4 modify `quota_gate.js` (`?v=20260517d`), returning browsers would serve stale assets unless the token is bumped. Bump all of them to `v=20260530a` (already used for the new mobile include in Task 6).

- [ ] **Step 1: Bump the `add_zettel_api.js` version (4 files)**

Replace `?v=20260522a` → `?v=20260530a` on the `add_zettel_api.js` `<script>` tag in:
`website/static/index.html:235`, `website/features/user_zettels/index.html:187`,
`website/mobile/index.html:44`, `website/features/user_home/index.html:313`.

- [ ] **Step 2: Bump the `quota_gate.js`/`quota_gate.css` version (2 wired desktop files only)**

Replace `?v=20260517d` → `?v=20260530a` on BOTH the `quota_gate.css` `<link>` and the
`quota_gate.js` `<script>` in ONLY the two pages that use the new `precheck`/`extractQuotaDetail`:
`website/features/user_home/index.html:306-307` and `website/features/user_zettels/index.html:180-181`.
(The mobile include added in Task 6 already uses `v=20260530a`.)

Do NOT touch `knowledge_graph`/`user_rag`/`user_kastens` — they use only the unchanged
`ZKQuotaGate.show`, so their cached copy stays valid (the server serves the new file to
fresh visitors regardless of `?v=`; the query only controls browser cache reuse). Leaving
them out keeps the diff inside this feature's surfaces.

- [ ] **Step 3: Run the full JS suite**

Run: `npx vitest run`
Expected: PASS — all `tests/js/**` including the 4 new files (normalize_failure, extract_quota_detail, precheck, wiring), no regressions.

- [ ] **Step 4: Run the touched Python tests**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\busy-spence-2816ad ; python -m pytest tests/unit/api/test_quota_routes.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Import-sanity the new router (lightweight — no full app boot)**

Run: `cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\busy-spence-2816ad ; python -c "from website.api.quota_routes import router; print([r.path for r in router.routes])"`
Expected: prints `['/api/quota/snapshot']` (imports cleanly, route present). Avoids `create_app()` which needs full env/secrets.

- [ ] **Step 6: Lint pass (single final pass) + commit**

Per repo convention (batch ruff at end). Run: `ruff check website/api/quota_routes.py --fix` then re-run Step 4 if anything changed.

```bash
git add -A && git commit -m "chore: cache-bust assets + lint for quota gate"
```

---

## Notes for the executor

- **Authority invariant (do not touch):** the atomic `billing.pricing_reserve_and_consume` via `require_entitlement` stays the sole enforcer. `precheck`/the snapshot endpoint are advisory only. Never gate solely on the snapshot; never add consume logic to the snapshot path.
- **Guardrails:** no entitlement seeding, no plan-name changes, no edits to `pricing_consume_entitlement`/`reserve_and_consume`. UI stays teal/amber (the modal is unchanged). Do not modify `get_current_user` (shared auth).
- **Deferred (out of scope — do NOT implement here):** server admission-402 pre-flight; server wire-format canonicalization; per-subject rate-limit on the snapshot endpoint; wiring `user_kastens`/`kasten_modal`/`user_rag` through the gate. See spec §8.
- **If a step's anchor line has drifted,** locate by the quoted surrounding code, not the line number.
