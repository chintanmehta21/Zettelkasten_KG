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
returns a **normalized** `{code:'quota_exhausted', meter, recommended_products}` object
from any of the known shapes, else `null`. It probes a small fixed set of locations and
**matches by exact equality only** — never substring / `includes` / regex / prose
(sweep‑check B: over‑broad matching could misclassify a future `quota_*` sibling such as
a soft‑limit warning). Accepted shapes:
- `x.detail` where `x.detail.code === 'quota_exhausted'` (sync 402),
- `x.error.detail` where that `.code === 'quota_exhausted'` (raw failed‑op body),
- `x.error` / top‑level `x` where `code === 'quota-exhausted'` (the hyphen slug form) **and**
  a nested `detail.meter` is present → normalize to the underscore shape.
It always **returns the single canonical underscore form**, so call‑sites are written
against the end state and the deferred server canonicalization only deletes a fallback
arm. Add a header comment: *"Tolerates two wire spellings of the quota code during the
canonicalization migration — remove the slug/`detail.detail` arms after the server
canonicalization PR ships and its deprecation window closes (tracking: <issue>)."*
(sweep‑check B — RFC 9413 removal‑planning; Expand/Contract cleanup phase.) Replaces the
per‑consumer `err.detail.code === 'quota_exhausted'` checks.

**(b) Pre‑add guard** — `ZKQuotaGate.guard({ feature, token, source, action, onBlocked })`
→ `Promise`:
1. **Pre‑flight:** `GET /api/quota/snapshot?feature=<feature>` (Authorization: Bearer
   token), with a tight client timeout (~1.5s, `AbortController`). Collapse rapid
   double‑clicks with a short in‑flight de‑dupe (~150–300ms memo keyed by
   `feature`+token) so a double‑submit issues **one** read — TTL effectively zero, never
   a balance cache (sweep‑check C).
   - **Well‑formed verdict — `effective_available <= 0`** → `show({ detail: { code:'quota_exhausted', meter:feature, recommended_products } , source })`,
     call `onBlocked` if provided, and **do not** run `action`. Resolve without running.
   - **Well‑formed verdict — `effective_available > 0`** (or `null` = unknown) → proceed
     to step 2.
   - **Fail‑open — ONLY on a non‑verdict:** transport error / timeout / 5xx / malformed
     body. Proceed to step 2 (authoritative server gate + backstop still protect
     correctness). A *successful* `0` payload is a verdict, **not** an error — it must
     show the modal, never fail open (sweep‑check A: distinguish "couldn't get an answer"
     from "answer is zero").
2. **Run + backstop:** `await action()`. If it throws, run the error through
   `extractQuotaDetail`; if it yields a quota detail → `show({ detail, source })` and
   swallow (handled); otherwise rethrow so the caller's existing error UI runs. The
   backstop is **load‑bearing** — it is the only thing that surfaces the rare TOCTOU
   denial that passed pre‑flight, so its end‑to‑end behavior (server 402, sync *and*
   normalized‑async) is a hard test requirement, not a nicety (sweep‑check A).

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

- **Auth:** required. A missing / invalid / expired token returns a **generic `401`**
  (uniform body — never distinguish "no token" vs "expired" vs "no profile"; sweep‑check
  D, avoids account‑state probing).
- **Identity:** resolve caller profile strictly from the verified JWT `sub` (same pattern
  as `require_entitlement._profile_uuid`). **No user/object id parameter is accepted, ever**
  — this is the strongest BOLA mitigation (`/me` pattern); adding an id param later would
  reactivate OWASP API1 and must be a *separate* role‑checked endpoint (sweep‑check D).
  An authenticated‑but‑non‑UUID sub (e.g. anonymous/Zoro mapping) → `{ effective_available: null }`
  (client treats `null` as "unknown → proceed", matching `require_entitlement`'s non‑UUID skip).
- **Input:** `feature` ∈ `functional_gates.config.FEATURES` (`zettel|kasten|rag_question`);
  anything else → `422` (server‑side allowlist).
- **Compute:** `FunctionalGates.quota_snapshot(profile_id=..., feature=...)` — read‑only,
  **no consume, no row locks** (plain consistent read; `SELECT FOR UPDATE` is wrong here —
  it dirties buffers, sweep‑check C). Wrap the read in a tight **statement timeout (~1–2s)**
  so a stuck read fails fast (client then fails open).
- **Response body — minimal, owner‑only (no infra disclosure):**
  ```jsonc
  { "feature": "zettel", "effective_available": 7, "remaining_plan": 5, "remaining_wallet": 2 }
  ```
  Return **only** these four fields — never plan name/tier, reset timestamps, ledger ids,
  or other workspaces' numbers (sweep‑check D API3 + the No‑Infra‑Disclosure rule).
- **Caching:** `Cache-Control: private, no-store` (belt‑and‑suspenders; `private` keeps it
  out of Cloudflare/Caddy shared caches, `no-store` forbids any storage — sweep‑check C/D,
  RFC 9111 §3.5/§5.2.2.5).
- **Abuse:** a per‑subject rate limit (OWASP API4) is **deferred to a follow‑up** per
  operator decision 2026‑05‑30 (§8). The endpoint ships auth‑required + cheap read; revisit
  if QPS/abuse ever appears (`pg_stat_statements`).

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

**JS (confirm runner during planning — repo convention):**
- `add_zettel_api` normalizer: sync‑402 body, async failed‑op envelope, both code
  spellings, non‑quota failure (real title surfaced, rethrows).
- `extractQuotaDetail`: each accepted shape → canonical quota dict; **near‑miss negatives
  must return null** — `quota_warning`, a non‑quota error whose `detail`/`title` prose
  merely contains the word "quota", and a bare slug with no nested `detail.meter`
  (sweep‑check B over‑broad‑matching guard).
- `guard`: `effective_available>0` → runs action; `<=0` (well‑formed) → popup + action
  **NOT** run; **`null`/unknown → runs action**; **transport error/timeout/5xx/malformed
  → fail‑open runs action**; but **well‑formed `0` never fails open** (distinct test);
  action throws quota → backstop popup; action throws non‑quota → rethrows;
  double‑submit within the de‑dupe window → **one** snapshot read.

**Python (pytest):**
- `GET /api/quota/snapshot`: **generic 401** for missing / invalid / expired token
  (assert identical body across all three — no state leak); returns
  `effective_available` for a minted user; **no consume** (balance byte‑identical before
  vs after the call); invalid `feature` → 422; authenticated non‑UUID sub → `{effective_available: null}`;
  response contains **only** the four allowed fields (assert no plan name/timestamp/ledger
  keys); `Cache-Control: private, no-store` present; no user‑supplied id param accepted (BOLA).
- Reuse `tests/integration/v2` mint fixtures where a live profile is needed; otherwise
  mock `FunctionalGates.quota_snapshot`.

## 8. Out of scope (recorded so deferral is explicit)

- Server admission‑402 pre‑flight before 202.
- Server wire‑format canonicalization (single top‑level `code`, `detail` as human
  string) — deprecation‑window migration, operator sign‑off. **This PR's
  `extractQuotaDetail` header comment must reference the tracking issue for that PR so the
  tolerant arms get deleted in its Contract phase** (sweep‑check B).
- Wiring `user_kastens` / `kasten_modal` / `user_rag` through `guard` (they already
  handle their sync 402; can adopt `extractQuotaDetail` later).
- **Per‑subject rate limit on `GET /api/quota/snapshot`** (OWASP API4, sweep‑check D) —
  deferred per operator decision 2026‑05‑30.

## 9. Sweep‑check verdicts (research round 2, 2026‑05‑30)

Four web‑search subagents validated the concrete decisions. All four returned **proceed /
correct**; no architectural change. Verdicts + primary citations:

- **A — Fail‑open on pre‑flight: CORRECT.** It is an availability gate, not an authz gate;
  the atomic RPC is the gate of record. Conditions (met): atomic gate unconditional; 402
  always surfaced (the normalization + backstop). Fail open only on non‑verdict, never on
  a well‑formed `0`. *Cites:* OWASP "Fail Securely" (scoped to security controls) +
  Authorization Cheat Sheet; Stripe rate‑limiters (fail‑open on Redis down, 2017); Google
  SRE graceful degradation; AWS REL05‑BP01; AuthZed fail‑open/closed (2021).
- **B — Tolerant client + deferred server canonicalization: CORRECT.** RFC 9413 sanctions
  *documented, removal‑planned* workarounds; breaking the wire code needs a deprecation
  window. Conditions: exact‑equality matching + tracked cleanup. *Cites:* RFC 9413 (2023);
  RFC 9457 §3; Google AIP‑180/AIP‑193; Stripe API versioning; Pete Hodgson Expand/Contract
  (2023); Fowler Tolerant Reader.
- **C — Per‑submit read, no cache, `private,no-store`, no locks: CORRECT for our scale.**
  Caching is premature (Stripe/LaunchDarkly cache to avoid *cross‑network* hops at massive
  fan‑out; ours is a local indexed read at human pace). *Cites:* Stripe Entitlements;
  LaunchDarkly polling→streaming; RFC 9111 §3.5/§5.2.2.5; Cloudflare cache‑control;
  CYBERTEC "SELECT FOR UPDATE considered harmful"; Postgres §13.3.
- **D — New read endpoint security: SAFE as designed.** JWT‑derived id w/ no id param =
  strongest BOLA mitigation; own‑balance is owner data (API3 fine); self‑disclosure ≈
  `RateLimit-Remaining`. Must‑dos folded into §4.3 (generic 401, allowlist, minimal
  payload, `no-store`); rate‑limit per §8.1. *Cites:* OWASP API1/API3/API4 (2023); OWASP
  Auth Cheat Sheet; Stripe rate‑limit headers; Authress 401/403/404.

Source‑age note: a few foundational refs (Stripe 2017, Google SRE 2016‑17, Fowler 2011,
Shkedy BOLA ~2020) are >5yr but remain the canonical, un‑superseded references; all other
primaries are 2022‑2026.
