# Open issues register — opened 2026-08-02

Tick these off one at a time. Every entry carries a **verdict** (what I'd do)
and a **source** (what the recommendation rests on), so none of it has to be
re-derived later.

Live-test baseline at `master@fb363a11`: **34 failed / 5402 passed / 0 errors**
(down from 248 / 5128 / 35 on 2026-08-01). The ratchet in
`tests/known_failures.txt` + `tests/conftest.py` holds that line — CI now goes
red only on NEW failures.

Status key: `[ ]` open · `[~]` blocked on a decision · `[x]` done

---

## P0 — security

- [ ] **Rotate the 3 leaked Gemini API keys.**
  They were printed in clear text into workflow logs on a **public** repo, on
  every weekly `live-tests` run from 2026-05-31 to 2026-08-01 (~13 runs).
  **Verdict: rotate today, before anything else here.** Assume compromised —
  leaked keys on public GitHub are scraped within minutes. The code leak is
  already closed (`monkeypatch.delenv` in `tests/test_key_pool.py`, verified
  with a canary env var: 0 occurrences in output).
  Then update the `GEMINI_API_KEYS` secret and the droplet's
  `/etc/secrets/api_env`, delete the affected run logs, and check billing for
  the exposure window.
  **Source:** mechanism, not opinion — GitHub masks a secret's whole string,
  never its comma-split components, so each individual key rendered unmasked in
  the pytest assertion diff.
  *Operator-only: I do not handle key material.*

---

## A — Pricing / entitlements (5 failures) — OPERATOR-LOCKED

- [~] **`pricing_subscriptions` count drifted 0 → 26.**
  **Verdict: the test is wrong, independently of the pricing question.** It
  asserts an *absolute row count on a shared, live table with real
  subscribers*, so it can only ever fail. Rescope it to the test's own minted
  tenant, or express it as a delta (`after == before + 1`). Do **not** reset
  production data to satisfy a test.
  **Source:** *SWE at Google* Ch. 14 (Larger Testing) — shared environments
  cause test-vs-test interference and cannot gate; Supabase's own testing docs —
  application tests "should not rely on a clean database state… use unique user
  IDs for each test case."
- [~] `test_pricing_entitlements_unchanged_count` — same class as above.
- [~] `test_pricing_consume_entitlement_body_unchanged` — golden-md5 guard.
  Verify whether Phase 9 legitimately changed the body before touching either
  side.
- [~] **Free-tier day cap not enforced** — 3rd call returned 202, expected 402.
  Possibly a real product bug.
- [~] **Order-create returns 502** — `test_create_order_..._proceeds_to_razorpay`.
  Possibly a real product bug.

**Blocking constraint:** CLAUDE.md pricing authority — never seed entitlements,
alter the golden-protected RPC bodies, or invent plan state without your
explicit sign-off. The last two may be genuine bugs but need approval before
anyone investigates with write access.

---

## B — Flaky under load (3 failures) — classified, not broken

- [x] **Classified and quarantined non-strict.**
  `test_burst_capacity` ×2 and `test_chat_concurrency` ×1 pass **8/8 in
  isolation** (15s) and in the mocked CI, and fail only inside the long live
  run. Confirmed again while building the ratchet: 2 of the 3 xfailed under the
  full suite but xpassed in isolation — load-dependent, textbook.
  `test_chat_concurrency` **already carries** the autouse `reset_for_tests()`
  fixture that was proposed as "the fix", so that proposal was wrong. **No
  speculative change made.**
- [ ] **Optional follow-up:** if they become annoying, isolate them into their
  own job rather than reruns.
  **Source:** Google Testing Blog (2016-05-27) — rerun mitigation applies only
  to tests *already marked* flaky, never as a global default. Do **not** add
  global `--reruns`: these call real Gemini, so reruns multiply paid API usage
  to paper over a classification you already have.

---

## C — CI environment (2 failures)

- [ ] **RAG runtime cannot be built in the live CI runner.**
  Both tests expect `503 queue saturated` and instead receive
  `503 "RAG runtime is not available"` (`chat_routes.py:91`). Same status code,
  different cause — which is why it reads as confusing rather than obvious.
  **Verdict: not a product bug.** Needs one CI run with debug output around
  `get_rag_runtime`; most likely a missing credential or model artifact in the
  live-test env. Not diagnosable from outside CI.

---

## D — Behaviour needs confirming before the expectation is rewritten (4)

- [~] **URL dedup vs content hash.**
  `test_same_url_different_hash_creates_new_row` asserts a new row; PR #25
  introduced `UNIQUE(normalized_url)` dedup. **Verdict: if URL now wins, the
  test is stale and I'll update it — but which side is intentional is a product
  decision, not something to infer from the code.**
- [~] **Naruto's avatar pin.** Migration 78 pins `avatar_01`; production holds
  `avatar_41` (both verified directly). The pin is a **one-time backfill** and
  the avatar picker shipped afterwards, so a user changing their avatar is
  legitimate and nothing enforces the pin.
  **Verdict: relax the assertion to a shape match (`AVATAR_PATTERN`); do not
  re-pin production data.** If the fixture identity must be stable, enforce it
  in the database, not in a test expectation.
  **Source:** Fowler, *ContractTest* — "the format of the data matters rather
  than the actual data"; Pact's *Matching* guidance — be as loose as possible on
  the response so checks aren't brittle. Same principle already applied to the
  deploy smoke gate, which is what stopped fixture rot breaking deploys.
  *(The stale-column half is already fixed: reads now target
  `core.profiles.avatar_url`, since migration 78 cleared the `auth.users` copy.)*
- [ ] `test_api_graph_v2_seeded_zettel_appears_in_nodes` — seeded zettel absent
  from the v2 graph.
- [ ] `test_uz03_xss_payload_returned_as_json_not_html` — expected ≥5 nodes, got 0.

---

## E — Untriaged (20) — first candidates next session

`test_profile_stats_rpc` ×6 · `test_profile_stats_endpoint` ×2 ·
`test_stuck_running_reaper` ×3 · `test_workspace_zettel_upsert` ×4 ·
`test_user_rag_kasten_bola` ×2 · `test_user_zettels_bola` ×2 ·
`test_live_engine` ×1 (the `example.com` fixture yields 112 chars, below the
thin-extraction floor — product working as designed, wrong fixture URL).

**Verdict: bucket by traceback signature before reading a single test.** These
are almost certainly far fewer than 20 root causes — that has held every time
so far this session (228 failures were one bug; 52 were one bug; 9 were one line).

**Source:** the burn-down pattern in *SWE at Google* Ch. 23 and Dropbox's
Athena — group and treat classes, don't grind test-by-test.

---

## F — Not mine

- [ ] **`ops/Dockerfile`, `requirements.txt`, `requirements.in`,
  `requirements-dev.txt`** — your parallel agent's work. I kept every commit
  clear of these all session. They are still **uncommitted** in the working
  tree, so they have never reached production.

---

## Structural work already done (for reference)

- [x] Ratchet installed — `tests/known_failures.txt` + `pytest_collection_modifyitems`
      in `tests/conftest.py`. Strict xfail by default (an unexpected pass FAILS
      the run, so the list self-cleans); `# flaky` opts into non-strict.
      Both halves proven empirically before commit.
- [x] Scheduled-CI failure alerting (deduped GitHub issue) + a dead-man's-switch
      canary, because a *dropped* scheduled run is indistinguishable from a
      passing one — and this repo is public, so GitHub disables cron after 60
      days of inactivity.
- [x] `ops/scripts/check_deploy_clear.sh` — exits non-zero while a deploy is in
      flight. Use as `check_deploy_clear.sh && git push`, never by eye.
