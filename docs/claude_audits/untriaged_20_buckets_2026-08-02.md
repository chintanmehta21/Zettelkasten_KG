# Untriaged live-test failures — bucketed by traceback signature (2026-08-02)

Source run: `live-tests` [30703846563](https://github.com/chintanmehta21/Zettelkasten_KG/actions/runs/30703846563)
(`master@3c3044dd`, 34 failed / 5402 passed / 182 skipped, 45m34s).

Method: group by exception class + message before opening a single test file.
That has held three times this session — 228 failures were one bug, 52 were one
bug, 9 were one line. Reading test-by-test would have re-derived the same root
cause eight times over in bucket 1 alone.

> *Source:* Software Engineering at Google Ch. 23 (Continuous Integration) and
> Dropbox's "Athena" (2019-05-22) both describe burn-down by *class*, not by
> individual test. Treat the signature as the unit of work.

**Result: the 20 untriaged failures are 6 root causes.**

| # | Signature | Tests | Verdict |
|---|---|---|---|
| 1 | `DataError: invalid input for query argument $N: 0 (expected str, got int)` | 8 | Test-fixture bug — identical to the already-fixed `seed_kg_graph` line |
| 2 | `UndefinedColumnError: column "accepted" of relation "operations"` | 3 | Test asserts a column that does not exist in the live schema |
| 3 | `UndefinedColumnError: column "sandbox_id" of relation "chat_sessions"` | 2 | Same class as #2 |
| 4 | `RaiseError: only kasten owners can grant memberships` | 2 | Test grants membership as the wrong principal |
| 5 | `ForeignKeyViolationError: profiles_id_fkey → users` | 4 | Fixture inserts `core.profiles` without the `auth.users` parent |
| 6 | `assert 5 >= 8` (tag count, `fallback_reason='gemini-2.5-pro-rate-limited'`) | 1 | Register's earlier note was wrong — see below |

---

## Bucket 1 — asyncpg TEXT-inference (8 tests) — CONFIRMED, one line per fixture

`test_profile_stats_rpc` ×6, `test_profile_stats_endpoint` ×2.

Postgres infers a parameter's type from its use. In

```sql
'seed-' || $1::text,
now() - ($1 || ' days')::interval
```

the `::text` cast and the `||` concatenation both force `$1` to TEXT, so asyncpg
requires a `str` and rejects the Python `int`. The fix is `str(i)` at the call
site, **not** a cast change — exactly the fix already applied to `seed_kg_graph`
in `tests/integration/v2/conftest.py`, which carries the explanatory comment.

Affected fixtures, all in `tests/integration/v2/conftest.py`:

| Fixture | Bad param | Used by |
|---|---|---|
| `seed_zettels` | `$1` (canonical), `$3` (workspace overlay) | 6 of the 8 |
| `seed_kastens` | `$2` | main_board, kasten |
| `seed_chat_messages` | `$3` | kasten, activity |
| `seed_zettels_with_tags` | `$4` | domain |

**The `$4` in the traceback is the proof, not a detail.** `test_domain_section`
is the only failure reporting `$4`, and it is the only test using
`seed_zettels_with_tags` — the one fixture whose day-offset parameter sits at
position 4. Every other failure reports `$1`, matching `seed_zettels`, whose
offset is at position 1 and which runs first. A single hypothesis explains both
the grouping and the exception.

---

## Bucket 2 — `operations.accepted` does not exist (3 tests)

`test_stuck_running_reaper` ×3. The reaper tests insert or assert on an
`accepted` column that the live `operations` table does not have. Needs the live
schema checked before deciding whether the column was renamed/dropped (test is
stale) or never shipped (the reaper feature is incomplete). **Do not add a
column to production to satisfy a test.**

## Bucket 3 — `chat_sessions.sandbox_id` does not exist (2 tests)

`test_user_rag_kasten_bola` ×2. Same class as bucket 2. These are **BOLA /
cross-tenant denial tests** — security coverage that is currently not running at
all. Rank above the cosmetic buckets for that reason.

## Bucket 4 — "only kasten owners can grant memberships" (2 tests)

`test_user_zettels_bola` ×2. A DB guard is firing, which means the guard works.
The test is granting membership while connected as a non-owner. Likely the
fixture needs to grant as the owner profile. Also security coverage.

## Bucket 5 — `profiles_id_fkey` violation (4 tests)

`test_workspace_zettel_upsert` ×4. The fixture inserts into `core.profiles` with
a fresh UUID that has no matching `auth.users` row. Either mint through the
existing `mint_test_user_with_workspaces` helper, or create the `auth.users`
parent first. Includes `test_concurrent_inserters_exactly_one_wins_others_update`
— a concurrency-correctness test, so this bucket is not cosmetic either.

## Bucket 6 — `test_live_engine` tag count (1 test)

**Correction to the register.** `open_issues_2026-08-02.md` recorded this as
"`example.com` yields 112 chars, below the thin-extraction floor". The actual
assertion is `assert 5 >= 8` on `SummaryResult.tags`, with
`fallback_reason='gemini-2.5-pro-rate-limited'`. The pipeline produced a
perfectly good summary from a deliberately minimal page; it just produced 5 tags
instead of 8, having fallen back off a rate-limited Pro model. The earlier note
was wrong and is corrected here.

Verdict: a real page yields more tags, and a tag-count floor asserted against
`example.com` is testing the fixture, not the engine.

---

## Also corrected while reading the tracebacks

Two bucket-A pricing entries were recorded as "absolute count on a shared live
table". Their real signatures are different, and materially so:

* `test_pricing_entitlements_unchanged_count` →
  `UndefinedTableError: relation "billing.pricing_plan_entitlements" does not exist`
* `test_pricing_consume_entitlement_body_unchanged` →
  `UndefinedFunctionError: function "billing.pricing_consume_entitlement(uuid,text,text)" does not exist`

These are **not** pricing-policy questions — the test is referencing a table and
a function signature that are not in the live schema. That said, they stay
operator-locked: a golden-md5 guard reporting "the function does not exist"
means the guard is not guarding anything, and which side is wrong (schema drift
vs. stale test) is your call, not mine.

`test_pricing_subscriptions_unchanged_count` is confirmed as originally
described — drifted 0 → **336** (not 26; that figure was from an earlier run).

One more: only the *first* `test_rag_rerank_queue_503` failure is
"RAG runtime is not available". The second fails on
`assert None == '5'` for a missing `Retry-After` header. Same file, two causes.

---

# Outcome (2026-08-02, PR #168)

`tests/known_failures.txt`: **34 → 19** entries (17 removed, 2 added for a new finding).

| Bucket | Tests | Result |
|---|---|---|
| 1 — asyncpg TEXT inference | 8 | **Fixed & verified** — 13 passed live |
| 2 — `operations.accepted` | 3 | **Fixed & verified** — all XPASS |
| 3 — `chat_sessions.sandbox_id` | 2 | **Fixed & verified** |
| 4 — kasten membership grant | 2 | Root cause fixed & proven in isolation; **still listed**, CI verifies |
| 5 — `profiles_id_fkey` | 4 | **Fixed & verified** — 4 passed live |
| 6 — tag-count floor | 1 | **Not changed — needs your call** |

## Bucket 6 needs a decision, not a fix

`>= 8` tags is a **real product contract**, not test noise:
`summarization/common/__init__.py:51` instructs the model to emit
`"tags": array of 8-15 lowercase hyphenated tags`. So the assertion is correct
and the engine (5 tags, `fallback_reason='gemini-2.5-pro-rate-limited'`)
under-delivered against its own spec.

The flaw is the **fixture URL**: `https://example.com` is a placeholder page with
roughly one sentence of text. No compliant engine can derive 8 meaningful tags
from it, so the test currently measures the fixture, not the pipeline.

Two options, both defensible — this is a quality-bar decision, so it is yours:

* **Keep `>= 8`, change the URL** to a stable content-rich page. Preserves the
  quality gate; adds a live-network dependency and some flake risk.
* **Keep `example.com`, assert shape** (tags non-empty and well-formed) and move
  the `>= 8` contract to a test with real content. Removes flake; the ≥8 bar
  then needs a home, or it stops being enforced anywhere.

I did not pick one: lowering a summary-quality bar unasked is exactly the kind of
silent scope reduction that needs sign-off.

## New finding surfaced by the bucket-3 fix

Fixing the stale column un-skipped two BOLA tests that then failed for a real
reason. `POST /api/rag/sessions` writes the caller-supplied `kasten_id` with **no
ownership check** (`session_store.create_session` — only an FK-existence guard,
which passes for a Kasten that exists but belongs to someone else). User B can
mint a session, in B's own workspace, bound to user A's Kasten.

**Not a data leak.** `ask_kasten._gate_kasten_ownership` (ask_kasten.py:345)
rejects a cross-tenant `kasten_id` with 403 before retrieval runs, and the second
failure is only the server echoing back the ID B itself supplied. This is a
defence-in-depth / input-validation gap at write time.

Left unfixed deliberately: adding an authz check is a security-model change and
CLAUDE.md requires explicit approval.

**The reason this was invisible matters more than the gap itself.** Both tests
`pytest.skip` on `503 RAG runtime unavailable`, which is exactly bucket C's
condition. So bucket C is not "two confusing status codes" — it is **silently
disabling BOLA coverage in CI**, and should be re-ranked accordingly.

## Also corrected

`_REAPER_SQL` in `test_stuck_running_reaper.py` is a hand-copy of migration 57's
SQL, so the test verifies its own copy rather than the deployed reaper. It passes
either way; worth noting as a separate weakness, not fixed here.
