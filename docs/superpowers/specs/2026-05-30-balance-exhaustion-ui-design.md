# Surface balance exhaustion in the UI — design spec

**Date:** 2026-05-30
**Branch:** `fix/balance-exhaustion-ui-gate`
**Status:** design approved, pending spec review

## 1. Problem

When a user runs out of Zettel balance, the Add‑Zettel summary fails **silently** — no
"out of balance" popup, no error. The reported symptom: "balance exhaustion not shown on
UI; summaries silently failing."

### Verified root cause (traced end‑to‑end)

The `Meter.ZETTEL` quota gate fires **inside the background pipeline**
(`website/api/module_runners/summarization.py:182`, via
`user_pricing.entitlements.require_entitlement` →
`functional_gates.reserve_and_consume`), i.e. **after** the route already returned
HTTP `202 Accepted`. On exhaustion it raises `HTTPException(402)` with the
`quota_exhausted` detail. The background worker (`zettels_routes.py::_run` →
`_failed_response_for` → `_async_failure_error_payload` → `_problem_dict`) persists a
terminal **failed** operation whose body is:

```jsonc
{
  "status": "failed",
  "operation_id": "...",
  "quality": { "confidence": "failed", "confidence_reason": "..." },
  "error": {                                   // RFC 9457 problem object
    "type": ".../errors/quota-exhausted",
    "title": "You have used your included zettels.",
    "status": 402,
    "detail": { "code": "quota_exhausted", "meter": "zettel", "recommended_products": [...] },
    "code": "quota-exhausted",                 // top-level slug (HYPHEN)
    "operation_id": "..."
  }
}
```

The client poller (`website/static/js/add_zettel_api.js::pollAccepted`, line ~100) does:

```js
failErr.detail = next.detail || next.error || next;   // -> next.error (the wrapper)
```

So `failErr.detail` becomes the **problem wrapper**, whose `.code` is
`"quota-exhausted"` (the hyphen slug), while the real machine code
`"quota_exhausted"` (underscore) is nested one level deeper at `failErr.detail.detail.code`.

Every consumer gates on the **sync** shape:

```js
// home.js:1494, user_zettels.js:1053, user_kastens.js:300, kasten_modal.js:93, user_rag.js:554
var quotaDetail = err && err.detail && err.detail.code === 'quota_exhausted' ? err.detail : null;
```

On the async path `err.detail.code === 'quota_exhausted'` is **false** (it is
`"quota-exhausted"`), so `ZKQuotaGate` never opens and the failure falls through to
generic/empty handling → **silent failure**. The sync 402 path works only because it
sets `error.detail = body.detail` (the quota dict directly).

The full popup machinery already exists and is unchanged:
`website/features/functional_gates/js/quota_gate.js` (`ZKQuotaGate.show({detail})`,
`isQuotaDetail()`) + `css/quota_gate.css` (teal/amber, no purple).

## 2. Scope

**In scope (this PR — client gate + one read endpoint):**

1. **Envelope normalization** (bug fix) in the shared poller.
2. **Single reusable pre‑add gate** built on the existing `functional_gates` balance
   check + `ZKQuotaGate` popup, wired into Home, My Zettels, and Mobile add paths.
3. **One read‑only endpoint** `GET /api/quota/snapshot` wrapping the existing
   `FunctionalGates.quota_snapshot`.

**Explicitly deferred (separate, sign‑off‑gated PRs):**

- **Server admission‑402 pre‑flight** before the `202` (research "admission control"
  layer). Deferred per operator decision 2026‑05‑30.
- **Server wire‑format canonicalization** — collapse the duplicated `code`
  (`"quota-exhausted"` top‑level slug vs `detail.code:"quota_exhausted"`) into a single
  top‑level `code` and make `detail` a human string per RFC 9457. Breaking wire change;
  needs a deprecation window. This PR makes the **client robust to both shapes** instead.

**Hard guardrails honored:** the atomic `billing.pricing_reserve_and_consume` RPC stays
the **sole authority** and is untouched; no entitlement seeding, no plan‑name invention,
no "fixing" of 402, no change to consume/decrement logic; gate logic lives in
`functional_gates` and is reused (one impl, all surfaces); UI stays teal/amber, never
purple.

## 3. Research basis (industry standard, <5yr sources)

Four web‑search subagents (2026‑05‑30). Convergent verdicts:

- **Pre‑flight + authoritative atomic gate is defense‑in‑depth** (AWS Well‑Architected
  REL05‑BP02 admission control; Stripe meters‑but‑you‑build‑the‑gate; GitHub Actions
  rejects at admission). The pre‑flight read is **advisory only**; the atomic RPC remains
  truth.
- **One framework‑agnostic gate module** every surface calls (OpenFeature/LaunchDarkly
  "single evaluation point"); client gate is UX only, must also **catch the server 402**
  as backstop; snapshot must return **server‑computed** remaining so the client never
  re‑derives thresholds.
- **RFC 9457:** machine code belongs in **one** top‑level extension member; duplicating it
  at two levels with two spellings is an anti‑pattern; async‑failure must embed the
  problem object verbatim so one client handler serves sync + async. (Canonicalizing the
  wire format is breaking → deferred with a deprecation window.)
- **TOCTOU is safe** when the atomic, `action_id`‑idempotent RPC stays authoritative
  (MITRE CWE‑367; IETF RateLimit‑headers draft: a positive "remaining" is never a
  guarantee). Rules: never gate solely on the snapshot; reconcile on the atomic decision;
  short TTL; snapshot takes **no row locks**; **fail open** on snapshot error.

Citations retained in the session research record (AWS REL05‑BP02; Stripe Entitlements
docs + stripe.dev blog Oct 2024; GitHub Actions billing docs 2025; RFC 9457 §3 2023;
Google AIP‑193; IETF draft‑ietf‑httpapi‑ratelimit‑headers §4.1.1/§7.3; MITRE CWE‑367;
Stripe idempotency).

## 4. Design

### 4.1 Component 1 — Envelope normalization (bug fix)

**File:** `website/static/js/add_zettel_api.js`, `pollAccepted` failed branch (~line 97).

When a polled op is terminal `failed`, expose the **inner problem detail** so it matches
the sync path byte‑for‑byte:

- `var problem = next.error || next;` — the RFC 9457 problem object.
- `failErr.detail =` the canonical detail: if `problem.detail` is an **object** use it
  (the quota dict); else fall back to `problem` then `next`.
- `failErr.message =` `problem.title` || existing `cleanProblemDetail` result || `'Summary failed.'`
  (Q3: real titles for **all** async failures, not just quota).
- `failErr.problem = problem;` (unchanged — richer handlers can still read it).

This single change makes `err.detail.code === 'quota_exhausted'` true on the async path
for every existing consumer, and surfaces real failure titles generally.

### 4.2 Component 2 — Single reusable pre‑add gate

**File:** `website/features/functional_gates/js/quota_gate.js` — extend `ZKQuotaGate`.

Add two pieces:

**(a) Robust detail extractor** — `ZKQuotaGate.extractQuotaDetail(errOrBody)`:
returns the `{code:'quota_exhausted', meter}` object from **any** shape:
- `x.detail` when `x.detail.code === 'quota_exhausted'` (sync),
- `x.detail.detail` when nested (normalized async, defensive),
- `x.error.detail` / `x.error` when given a raw failed‑op body,
- also accepts the top‑level slug form (`code === 'quota-exhausted'` with a nested
  `detail`) and normalizes it.
Returns `null` if not a quota detail. Replaces the per‑consumer
`err.detail.code === 'quota_exhausted'` checks.

**(b) Pre‑add guard** — `ZKQuotaGate.guard({ feature, token, source, action, onBlocked })`
→ `Promise`:
1. **Pre‑flight:** `GET /api/quota/snapshot?feature=<feature>` (Authorization: Bearer
   token). Tight timeout (~2.5s).
   - If `effective_available <= 0` → `show({ detail: { code:'quota_exhausted', meter:feature, recommended_products } , source })`,
     call `onBlocked` if provided, and **do not** run `action`. Resolve without running.
   - Else proceed to step 2.
   - **Fail‑open:** any snapshot error/timeout → skip the pre‑flight verdict and proceed
     to step 2 (the authoritative server gate + the backstop still protect correctness).
2. **Run + backstop:** `await action()`. If it throws, run the result through
   `extractQuotaDetail`; if it yields a quota detail → `show({ detail, source })` and
   swallow (handled); otherwise rethrow so the caller's existing error UI runs.

The guard is the **single** place the three add surfaces call. A new surface inherits
correct behavior by calling `guard(...)`.

**Wiring (callers):**
- `website/features/user_home/js/home.js` — wrap the `ZKAddZettel.add/uploadDocument`
  submit in `ZKQuotaGate.guard({feature:'zettel', ...})`; replace the inline
  `quotaDetail` check (1494, 1878) with `extractQuotaDetail`.
- `website/features/user_zettels/js/user_zettels.js` — same (replaces check at 1053).
- `website/mobile/js/summarizer.js` — same for the mobile URL + document submit.

Out of scope for wiring this PR (different features, already handle sync 402 and are not
the reported bug): `user_kastens.js`, `kasten_modal.js`, `user_rag.js`. They keep working
via the existing sync path and the `extractQuotaDetail` helper remains available to them
in a follow‑up.

### 4.3 Component 3 — Read‑only snapshot endpoint

**New route:** `GET /api/quota/snapshot?feature=zettel` (auth required).

- Resolve caller profile from the verified JWT `sub` (same pattern as
  `require_entitlement._profile_uuid`); non‑UUID/anonymous → `{ effective_available: null }`
  (treated as "unknown → fail‑open" by the client).
- `feature` ∈ `functional_gates.config.FEATURES` (`zettel|kasten|rag_question`); reject
  others with 422.
- Call `FunctionalGates.quota_snapshot(profile_id=..., feature=...)` (read‑only; no
  consume; no row locks).
- Response body:
  ```jsonc
  { "feature": "zettel", "effective_available": 7, "remaining_plan": 5, "remaining_wallet": 2 }
  ```
- `Cache-Control: no-store` (always fresh at gate time, per research).
- **BOLA:** the snapshot is computed strictly for the caller's own `profile_id`; no
  user‑supplied id is accepted.

Placement: new `website/api/quota_routes.py`, registered in `website/app.py` alongside
the other API routers. (Thin adapter; the balance logic stays in `functional_gates`.)

## 5. Data flow

```
User submits Add‑Zettel (home / my‑zettels / mobile)
  └─ ZKQuotaGate.guard({feature:'zettel'})
       ├─ GET /api/quota/snapshot?feature=zettel  ── effective_available <= 0 ─→ ZKQuotaGate popup (Buy CTA); STOP
       │                                           └─ error/timeout ─→ FAIL‑OPEN ↓
       └─ action():  POST /api/zettels/add → 202 → poll /api/operations/{id}
             ├─ succeeded → render card
             └─ failed (quota raced through atomic gate) → normalized envelope
                   → extractQuotaDetail → ZKQuotaGate popup (backstop)
Authority at all times: billing.pricing_reserve_and_consume (atomic, idempotent on action_id)
```

## 6. Error handling / edge cases

- **TOCTOU race** (snapshot says ≥1, atomic consume denies): the async‑fail backstop
  (4.1 + 4.2b) surfaces the popup. Reconciles on the authoritative decision.
- **Snapshot endpoint down / slow:** client fails open → add proceeds → atomic gate +
  backstop still correct. Snapshot is never the gate of record.
- **Anonymous / non‑UUID sub:** snapshot returns `effective_available: null` → client
  treats as unknown → fail‑open (matches `require_entitlement` skipping the gate for
  non‑UUID subs).
- **Unlimited plan granularity (`None` cap):** `effective_available` reflects
  `min(remaining_*)` + wallet from the existing snapshot RPC; `None`/large → never blocks.
- **Both code spellings on the wire:** `extractQuotaDetail` handles slug and underscore;
  no server wire change required.
- **Document upload path:** same guard wraps `uploadDocument` (feature `zettel`).

## 7. Testing

**JS (vitest/jest per repo convention):**
- `add_zettel_api` normalizer: sync‑402 body, async failed‑op envelope, both code
  spellings, non‑quota failure (real title surfaced, rethrows).
- `extractQuotaDetail`: each accepted shape → quota dict; non‑quota → null.
- `guard`: `effective_available>0` → runs action; `<=0` → popup + action NOT run;
  snapshot error → fail‑open runs action; action throws quota → backstop popup;
  action throws non‑quota → rethrows.

**Python (pytest):**
- `GET /api/quota/snapshot`: auth required (401 unauth); returns `effective_available`
  for a minted user; **no consume** (balance unchanged after call); invalid `feature` →
  422; anonymous/non‑UUID → `null`; cross‑tenant — no user‑supplied id accepted (BOLA).
- Reuse `tests/integration/v2` mint fixtures where a live profile is needed; otherwise
  mock `FunctionalGates.quota_snapshot`.

## 8. Out of scope (recorded so deferral is explicit)

- Server admission‑402 pre‑flight before 202.
- Server wire‑format canonicalization (single top‑level `code`, `detail` as human
  string) — deprecation‑window migration, operator sign‑off.
- Wiring `user_kastens` / `kasten_modal` / `user_rag` through `guard` (they already
  handle their sync 402; can adopt `extractQuotaDetail` later).
