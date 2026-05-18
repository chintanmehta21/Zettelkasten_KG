# URL Dedup → Cache-Hit Redesign (Add-Zettel pipeline)

**Date:** 2026-05-18
**Branch / PR:** `codex/exec-summarization-pipeline-final-fix` / PR #25
**Status:** Design approved (operator), pending spec review → implementation plan

## Problem

Dedup is keyed `UNIQUE(content.canonical_zettels.normalized_url, content_hash)`
where `content_hash = sha256(body_md)` (`website/core/persist.py:488`) and the
upsert conflicts on `(normalized_url, content_hash)`
(`supabase/website/_v2/17_content_rpcs.sql:29`). Any extraction variance on a
re-add of the same URL (YouTube transcripts, dynamic pages) ⇒ new hash ⇒ no
conflict ⇒ a new canonical is inserted and `summarize_url_bundle` re-runs,
wasting LLM spend. The summarization engine also runs *before* any dedup check
(orchestrator → engine → persist), so dedup never saves engine cost. There is
no cross-user "link existing canonical + charge quota + stay unaware" path.

## Goal / Required Behavior (operator-locked)

1. Dedup on URL identity (`normalize_url`), not content hash.
2. A known `normalized_url` ALWAYS reuses the existing canonical summary — the
   engine never re-runs for it (always cache-hit; no refresh/TTL path).
3. Cross-user: when user Y adds a URL user X already ingested, link the
   existing canonical into Y's workspace as if Y ingested it; Y's zettel quota
   decrements by 1; Y is unaware it was a cache hit (UX identical to fresh).
4. Same-user re-add of a URL the user already owns: no DB write, no-op, **no
   quota/balance reduction**.

## Architecture — request flow

Single pre-engine **dedup gate** at the top of
`website/api/module_runners/summarization.py::run_add_zettel_pipeline` (the
chokepoint every Add-Zettel surface funnels through; same gate also applied in
`summarization_engine/api/routes.py` `/api/v2/summarize`, before its engine
call).

**P1 reorder (verified):** today the pipeline charges `require_entitlement`
at `module_runners/summarization.py:133` *before* `resolve_redirects` (L135),
`normalize_url` (L136), and `summarize_url_bundle` (L139). The gate moves
entitlement to *after* the dedup decision so the same-user no-op never charges.

**P1 dedup key:** the key is `normalize_url(resolve_redirects(url))` — the
**post-redirect** normalized URL — so shorteners / tracking-param / redirect
variants converge to one canonical (the pipeline already resolves at L135).

```
key = normalize_url(resolve_redirects(url))   →  canonical exists for key?
  NO  → require_entitlement(user) → summarize_url_bundle → persist new canonical+workspace row   [FRESH]
  YES → user's workspace already has a workspace_zettels row for this canonical?
          YES → return existing DTO; NO entitlement call; NO DB write           [SAME-USER NO-OP]
          NO  → require_entitlement(user)            (charged 1, identical to fresh)
                → insert workspace_zettels(user.workspace, existing canonical_id)
                → build response DTO from existing canonical's stored ai_summary [CACHE-HIT / CROSS-USER LINK]
```

Invariants:
- `summarize_url_bundle` is invoked ONLY on the FRESH branch (the LLM saving).
- Pricing untouched: cache-hit cross-user calls the *same*
  `require_entitlement(Meter.ZETTEL, …)` a fresh add uses. `consume_entitlement`
  and plan definitions are never modified (hard guardrail). Quota-exhausted on a
  cache-hit returns the same `402` as fresh.
- Same-user no-op short-circuits BEFORE entitlement → no charge, no DB change.
- Response DTO on cache-hit is reconstructed from the existing canonical via the
  same `extract_summary_parts`/render path as fresh → byte-identical wire shape.
  No "cached" indicator exposed (no-infra-disclosure rule).

## P2 hardening (in this PR)

- **Internal counters/logs** at the gate: `fresh`, `same_user_noop`,
  `cross_user_cache_hit` (tagged `source_type`). Structured logs only —
  never surfaced in any API DTO (no-infra-disclosure rule). Used to verify the
  LLM-cost savings and that no-ops behave.
- **Extend `tests/unit/website/test_url_utils.py`** for dedup-critical
  `normalize_url` cases: tracking-param strip, scheme/host case, default-port,
  query-key ordering, trailing slash — since the key is now load-bearing for
  dedup correctness (over/under-collapse risk).

## Declined (P3 — out of scope, locked)

- Refresh-support fields (`captured_at`/version-driven re-summarize): conflicts
  with operator-locked "always cache-hit, no refresh path". YAGNI.
- "same normalized_url, different content_hash" metric and pre/post-normalize
  shadow-log: future notes only; not built. content_hash already retained for
  later analytics if needed.

## Components

| Component | Change |
|---|---|
| `url_utils.normalize_url` | Reused unchanged — dedup identity key. |
| `V2ContentRepository.find_canonical_by_url(normalized_url)` (new) | Read-only; returns canonical id + stored `ai_summary`/title/source_type/tags or `None`. Backed by new `UNIQUE(normalized_url)`. |
| `V2ContentRepository.link_existing_canonical(workspace_id, canonical_id, …)` (new) | Inserts one `workspace_zettels` row referencing the existing canonical; idempotent on `UNIQUE(workspace_id, canonical_zettel_id)`. |
| `run_add_zettel_pipeline` | Adds the dedup gate; builds cache-hit DTO from existing canonical. |
| `persist._persist_supabase_v2_zettel` | `content_hash` still computed/stored (analytics) but not part of dedup. |
| upsert RPC `17_content_rpcs.sql` | `ON CONFLICT` target → `(normalized_url)`. |
| `/api/v2/summarize` route | Same gate before its engine call. |

## Schema migration (new versioned `supabase/website/_v2/<n>_url_dedup.sql`)

1. Collapse the 2 URLs that currently have >1 canonical: keep the
   most-recently-created canonical; `UPDATE` `workspace_zettels` and
   `canonical_chunks` referencing the loser → keeper; `DELETE` loser canonical.
   Idempotent; backup-first; gated (operator-run, not autonomous).
2. `ALTER TABLE content.canonical_zettels DROP CONSTRAINT <old (normalized_url,
   content_hash)>; ADD CONSTRAINT canonical_zettels_normalized_url_key
   UNIQUE (normalized_url);`
3. Update upsert RPC conflict target. Follows migration-discipline conventions
   (versioned, manifest regen, migration-CI gate, Squawk lint).

## Backward compatibility

32 live rows (Naruto 27 + Zoro 5). Zoro's two `iana.org/help/example-domains`
rows differ by query string; `normalize_url` keeps them distinct → no
unintended collapse. Existing `ai_summary` envelopes are consumed unchanged by
the cache-hit DTO builder.

## Concurrency (2 gunicorn workers, scale-proof)

Two users adding the same NEW URL within ms could both miss the existence check
and both run the engine. The DB `UNIQUE(normalized_url)` makes the second
canonical insert hit `ON CONFLICT`; we catch it, fall back to the link path,
discard the redundant engine output. Rare, self-correcting; a distributed lock
is overkill at this scale.

## Testing (TDD)

- Gate unit tests: fresh / same-user no-op / cross-user link.
- Entitlement called exactly once on cross-user cache-hit; never on same-user
  no-op; once on fresh.
- Concurrency: `ON CONFLICT` fallback path links instead of erroring.
- Migration: dup-collapse idempotency + child re-point correctness + constraint
  swap; migration-CI gate green.
- DTO wire-parity: cache-hit response shape == fresh response shape.
- Dedup key is post-redirect: `resolve_redirects` mocked → key uses resolved URL.
- Extended `test_url_utils.py` normalize_url cases (P2).
- Gate emits the three counters with correct labels; none leak into the DTO.
- Regression: full `pytest`, `ruff`, GitHub checks green before merge.

## Out of scope

Refresh/re-summarize action; staleness TTL; distributed locking; any pricing
plan/`consume_entitlement` change; deleting/altering the 32 live real rows
beyond the documented dup-collapse.
