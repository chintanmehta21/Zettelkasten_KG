# iter-11 Research Reference

This document is the consolidated research artefact for iter-11. Audiences:

1. **Future humans / agents looking back at iter-11** — to understand what we knew, what we tried, and what we deliberately rejected.
2. **The plan executor (subagent or human running [PLAN.md](PLAN.md))** — to look up rationale, edge cases, and "why not X" decisions when a phase task references them.

**Cross-reference:** [PLAN.md](PLAN.md) — implementation tasks. This file is the *why*; PLAN.md is the *how*.

**Sister artefacts (read before any phase):**
- `iter-10/scores.md` — final iter-10 metrics + per-query forensic
- `iter-10/RESEARCH.md` — iter-10 RES-1..RES-11 rationale (especially RES-3 magnet gate, RES-4 anchor un-gate, RES-7 deepdive correction, RES-8 chunk-quartile tiebreaker)
- `iter-10/PLAN.md` — what iter-10 implemented (avoid duplicate work)
- `iter-09/iter09_failure_deepdive.md` — per-query forensic (note: deepdive's auto-title-Gemini claim is INCORRECT, see iter-10 RES-7 correction)
- `CLAUDE.md` root — Critical Infra Decision Guardrails

---

## How the executor should use this file

Before implementing any PLAN.md phase:

1. Read the matching `Class` section here.
2. If a task is unclear, look up "Pitfalls" and "Cons NOT to take" — they capture every dead end already explored.
3. If a test fails in an unexpected way, check "Edge cases" for that class.
4. If you encounter a decision point not covered here, **stop and ask the user** rather than improvising. Beyond-plan decisions require explicit chat-confirmed approval per CLAUDE.md.

---

## Iter-10 outcome that motivates iter-11

| Metric | iter-09 audited | iter-10 final | iter-11 target |
|---|---:|---:|---:|
| Composite | 65.32 | 66.10 | ≥ 85 |
| chunking | 40.43 | 40.43 | held |
| retrieval | 97.08 | 78.26 | ≥ 80 |
| reranking | 57.14 | 59.75 | ≥ 70 |
| synthesis | 56.85 | 67.87 | ≥ 75 |
| gold@1 (unconditional) | 0.6429 | 0.6429 | ≥ 0.85 |
| within_budget | 0.0714 (mis-reported) | 0.6429 | ≥ 0.85 |
| answer_relevancy (RAGAS) | 74.29 | 80.00 | ≥ 80 (held) |
| faithfulness (RAGAS) | 87.50 | 97.14 | held |
| burst 503 rate | 0.50 | 0.50 | ≥ 0.08 (held) |
| burst 502 rate | 0.25 | 0.25 | 0% |

**Per-query failure mode after iter-10 (verified disk facts from `iter-10/verification_results.json`):**

| qid | class | gold@1 | budget | failure root cause (verified) | iter-11 class |
|---|---|:-:|:-:|---|---|
| q1  | multi_hop | T | F | over-budget but correct; cold-start | none |
| q2-q4 | lookup | T | T | pass | none |
| q5  | thematic | T | T | retrieval ✓ but synth refused (`unsupported_no_retry`) | **F** |
| q6  | multi_hop | T | F | over-budget but correct (recovery from iter-09) | none |
| q7  | thematic | F | T | wrong primary; gold at pos 3; rewriter kept "commencement" literal | **D** |
| q8  | thematic | F | F | gh-zk-org-zk demoted by iter-10 P3 magnet gate but IS the gold | **A** |
| q9  | thematic | n/a | T | refusal-expected; primary=None CORRECT; mechanically false-fails | **E1** |
| q10 | lookup | F | T | pool size 1; anchor-seed didn't fire; entity-resolve gap | **C** |
| q11 | lookup | T | T | pass | none |
| q12 | thematic | F | T | yt-programming-workflow-is at pos 4; THEMATIC tiebreak inverted away from named multi-chunk gold | **B** |
| q13-q14 | multi_hop | T | F | over-budget but correct | none |

`latency_ms_server` for ALL fast queries: 0.9-1.9 s. The 22-37 s ttft seen in `p_user_first_token_ms` is **wire-side gap** (Cloudflare/Caddy SSE buffering OR Playwright `getReader()` artefact) — Class **E2** investigates which.

---

## Class A — entity-anchor exemption on the magnet gate

**Verdict: ✓ ship Phase 2.**

**The problem (iter-10 q8 regression):** iter-10's P3 magnet gate (`_apply_score_rank_demote` in `hybrid.py`) damps any candidate whose post-boost rank is disproportionate to its base rrf percentile in THEMATIC/STEP_BACK. For q8 ("What should I install tonight to start a personal wiki?"), `gh-zk-org-zk` was correctly identified as a statistical magnet (top-1 in 3/14 iter-09 queries) and damped from top-1 to position 4 — but for q8 it IS the legitimate answer.

**The fix:** in `_apply_score_rank_demote`, add an "earned exemption" carve-out — skip the demote when:
1. `candidate.node_id in anchor_nodes` (the resolved-entity set from `entity_anchor.resolve_anchor_nodes`), OR
2. `candidate.metadata["_title_overlap_boost"] > 0` (query verbatim names this zettel).

Statistical detection remains necessary; the carve-out gives "earned" candidates a path through. Title-overlap secondary demote (the `>= 0.10` threshold) is also exempted via the same check.

**Class scope:** the exemption applies in THEMATIC and STEP_BACK (where the gate fires); it has no effect on LOOKUP/VAGUE/MULTI_HOP since those classes bypass the gate entirely.

**Knobs:**
- `RAG_SCORE_RANK_PROTECT_ANCHORED=true` (default) — env-flag the new behaviour for one iter so a regression can be reverted operationally without a code revert.

**Pitfalls / cons NOT to take:**
- DO NOT remove the magnet gate (would re-introduce iter-09 q5 failure where unanchored small-chunk magnets win top-1).
- DO NOT widen the exemption to "any candidate with non-zero `_title_overlap_boost`" without the floor — short-name accidental matches ("X" in "X-rays" matching "X" zettel) shouldn't get exemption. The `> 0` threshold only fires when `_title_match_boost` returned a real signal, which already has its own floor.
- DO NOT extend exemption to anchor_neighbours (1-hop nodes). Neighbours are weaker signal; only direct anchor nodes earn exemption.

**Edge cases:**
- A candidate that's BOTH anchored AND a statistical magnet → exempted (correct: q8 case).
- A candidate that's anchored but NOT a magnet → unaffected by this change.
- A candidate that has `_title_overlap_boost = 0.0001` (tiny floating-point) → exempted (any positive boost, however small, counts as title-overlap).

**Observability (also iter-11 win):** the demote helper grows a structured log line `score_rank_demote class=%s n_demoted=%d title_demoted=%d mean_factor=%.3f anchored_n=%d`. iter-10 added the gate but no observability. This closes that gap.

**Where this lands:** [PLAN.md](PLAN.md) Phase 2 / Task 3.

---

## Class B — name-overlap override on THEMATIC tiebreaker

**Verdict: ✓ ship Phase 3.**

**The problem (iter-10 q12 regression):** iter-10's Item 3 chunk-count-quartile tiebreaker (`_tiebreak_key` in `hybrid.py`) inverts THEMATIC/MULTI_HOP/STEP_BACK to prefer LOWER chunk-count (broad coverage > deep monoculture per RES-8). For q12 ("How does the **programming-workflow zettel** characterise..."), this pushed `nl-the-pragmatic-engineer-t` (single-essay, 1 chunk) above `yt-programming-workflow-is` (multi-chunk transcript) when their rrf scores were close — but the query *literally references* the multi-chunk zettel by name.

**The fix:** in `_tiebreak_key`, accept a `title_overlap_boost` parameter. When `title_overlap_boost > 0`, skip the THEMATIC-class inversion for that candidate (use the LOOKUP-style higher-quartile preference). Pass the value from `candidate.metadata["_title_overlap_boost"]` at the call site in `_dedup_and_fuse`.

**Why this is the right primitive:** name-overlap is a strong signal that the user is targeting a specific zettel, not asking for cross-corpus coverage. The THEMATIC inversion's broad-coverage prior is correct as a default but harmful when a single-zettel target is implied.

**Pitfalls / cons NOT to take:**
- DO NOT remove the THEMATIC inversion entirely — it correctly resolves q5/q7-shape ties where there's no named target and broad coverage matters. Only the named-target sub-case needs override.
- DO NOT make the override depend on `_title_overlap_boost >= 0.10` (the magnet-damp floor) — even a tiny title-overlap boost indicates the user named the zettel; act on it.
- DO NOT replace the bias direction from inverted-low to non-inverted-high based on `query.split()` length or other heuristics; name-overlap is the cleanest disambiguator.

**Edge cases:**
- Two candidates both with name-overlap → both prefer higher chunk-count (LOOKUP-style); ties resolved by stable sort (insertion order).
- LOOKUP candidates with name-overlap → no behaviour change (LOOKUP already prefers higher quartile).
- A query with name-overlap to a LOW-chunk zettel → that zettel's quartile is naturally low; tiebreak still gives the right answer (LOOKUP-style preference for higher quartile in rrf-tied case is harmless because the LOW-chunk zettel will win on rrf if rrf isn't tied).

**Cross-class regression net:** add a fixture case to `tests/unit/rag/integration/test_class_x_source_matrix.py` covering "thematic, named-zettel" — a rrf-tied pool where a 12-chunk named zettel must beat 1-3-5-chunk competitors.

**Where this lands:** [PLAN.md](PLAN.md) Phase 3 / Task 4.

---

## Class C — per-entity anchor union with diagnostic logging

**Verdict: ✓ ship Phase 1, after the Phase 0 scout disambiguates the actual root cause.**

**The problem (iter-10 q10 persistent):** q10 ("Steve Jobs and Naval Ravikant both speak about meaningful work...") returned a 1-row pool with `web-transformative-tools-for` only. The expected `yt-steve-jobs-2005-stanford` was nowhere in the pool. iter-10 P4 anchor-seed un-gate (Task 6) was supposed to cover this, but the inject didn't fire.

**Why the obvious diagnosis doesn't quite fit:** the existing `rag_resolve_entity_anchors` RPC already uses OR-semantics over `unnest(p_entities)`. So passing `["Steve Jobs", "Naval Ravikant"]` SHOULD return at least the Jobs node. The fact that q10's pool was empty of Jobs suggests one of three failure modes:

1. **Metadata extractor didn't surface the entities** — `query_metadata.authors` and `.entities` were both empty for q10 → the resolver was never called (the gate `if metadata.authors or metadata.entities` short-circuited).
2. **Resolver was called but RPC returned [] despite the OR semantics** — perhaps name normalisation differs ("Steve Jobs" vs "steve jobs" vs "Jobs"), perhaps the kg_nodes.name format differs from the entity string.
3. **Resolver returned nodes but anchor-seed `fetch_anchor_seeds` returned empty** — the seed-fetch RPC has its own scoping logic that could be the culprit.

**The Phase 0 scout in PLAN.md disambiguates** by adding a temporary log line that prints `(authors, entities, anchor_nodes, anchor_seeds_n)` per query, then running the eval and inspecting q10's record. The fix branches on the actual signal:

- **Mode 1 (metadata gap):** fix the metadata extractor to surface "Steve Jobs" / "Naval Ravikant" as authors when the query says "Steve Jobs and Naval Ravikant both speak about...". This may already work for `compare_intent` detection — needs verification.
- **Mode 2 (resolver gap):** switch from batched RPC to per-entity loop with structured logging — even if the RPC behaves correctly, per-entity calls give us forensic visibility on which entities resolved.
- **Mode 3 (seed-fetch gap):** investigate `rag_fetch_anchor_seeds` directly.

The **iter-11 ship is Mode 2 (per-entity loop)** because:
- It's defence-in-depth regardless of which mode is the actual root cause — making the resolver per-entity adds observability without changing the OR semantics.
- It's a small, isolated change with a unit test contract.
- Operator already approved it as Class C ("per-entity anchor resolution + union").

If the scout reveals Mode 1 or Mode 3 is the dominant cause, the per-entity loop in Mode 2 is still useful (it's the structured-log primitive iter-12+ needs); but additional fixes go to Mode 1 / Mode 3 paths.

**Pitfalls / cons NOT to take:**
- DO NOT keep the batched RPC for "performance" — the round-trip cost is 30-90 ms total for typical 2-3 entities; the observability win is worth it.
- DO NOT extend the loop to also call `get_one_hop_neighbours` per-entity — that adds 1-hop graph traversal cost that scales N². Single batched neighbours call still works correctly (it ORs internally).
- DO NOT broaden the P5 dense-fallback threshold to `total_rows <= N` for any N > 0 in iter-11 — that's a separate question (item 9 in iter-10 carryover) and risks turning the fallback into the primary path.

**Edge cases:**
- Entity strings with leading/trailing whitespace → strip before passing to RPC; skip empty strings.
- Duplicate entity strings in input → don't dedupe BEFORE the loop (each one might give different RPC results due to fuzzy matching nuance); dedupe AFTER on the result set (set semantics).
- RPC raises for ONE entity → log+skip that entity, continue with the rest.

**Where this lands:** [PLAN.md](PLAN.md) Phase 0 / Task 2 (scout) + Phase 1 / Task 2 (impl).

---

## Class D — short-query entity-hint expansion in the rewriter

**Verdict: ✓ ship Phase 4.**

**The problem (iter-10 q7 persistent):** q7 ("Anything about commencement?") was router-classified as THEMATIC, not VAGUE. The iter-07 gazetteer expansion (`expand_vague` in `query/vague_expander.py`) is gated to `cls is QueryClass.VAGUE`, so it didn't fire for q7. The THEMATIC branch produces 3 paraphrases via `_multi_query` — but paraphrasing "Anything about commencement?" doesn't surface "Stanford 2005 / Steve Jobs / graduation". Retrieval can't find what the query never described.

**The fix:** in `transformer.py:transform()`, gate the gazetteer + HyDE path by **class OR length**, not class alone. New rule: if `cls is QueryClass.VAGUE OR (cls is QueryClass.THEMATIC AND len(query.split()) <= RAG_SHORT_THEMATIC_THRESHOLD)`, run the gazetteer and HyDE expansion in addition to the normal multi-query paraphrases.

**Why a length threshold (not router fix):** the router lives upstream and has its own rule-set; reclassifying "Anything about commencement?" as VAGUE could ripple into other code paths that branch on QueryClass. The cleanest insertion point is the rewriter itself, where the expansion path already exists for VAGUE — we're just extending eligibility. Default threshold 4 words (covers q7's 3-word case; doesn't sweep up genuinely cross-corpus 5+ word queries).

**Why gazetteer + HyDE specifically:** the gazetteer is deterministic (fast, cheap, no LLM); HyDE adds one Gemini-2.5-flash-lite call (~200 ms, ~$0.0001/query) for queries that lack any gazetteer keyword. Together they convert "commencement" into a richer set of variants that BM25 and embedding retrieval can both hit.

**Pitfalls / cons NOT to take:**
- DO NOT broaden to `cls is QueryClass.MULTI_HOP AND short` — multi-hop queries break-down via `_decompose` already; gazetteer wouldn't help and HyDE could pull off-topic.
- DO NOT raise the threshold to 6 or 7 words — empirically, 4 is the right cut-off for "vague-shape" queries; 5+ word THEMATIC queries usually carry enough signal for paraphrase to work.
- DO NOT remove the original `_multi_query` paraphrase variants when adding the gazetteer/HyDE path — both are needed (paraphrases handle long-query nuance, gazetteer handles vague tokens).

**Edge cases:**
- A 4-word THEMATIC query that has NO gazetteer key (e.g. "AI tools for productivity") → `expand_vague` returns []; HyDE alone runs; paraphrases still run. Net = standard THEMATIC path + 1 HyDE variant.
- A 1-word query → check that the gazetteer + HyDE both handle it gracefully (no division-by-zero, no empty-prompt errors). Existing `expand_vague` already handles single-token gracefully.

**Where this lands:** [PLAN.md](PLAN.md) Phase 4 / Task 5.

---

## Class F — class-conditional critic threshold (operator-approved)

**Verdict: ✓ ship Phase 5 (with explicit operator approval recorded).**

**The problem (iter-10 q5 persistent):** q5 ("Across these zettels, what is the implicit theory of how a knowledge worker should structure a day...") had retrieval surface the gold (`nl-the-pragmatic-engineer-t` at top-1, full kasten members in top-5) — iter-10's P3 + Item 3 + P9 fixes successfully demoted the iter-09 magnet (`gh-zk-org-zk`) and surfaced the right pool. But the synth critic emitted `unsupported_no_retry`. The user sees a refusal even though gold was retrieved.

**Why the critic refuses:** `_PARTIAL_NO_RETRY_FLOOR=0.5` and `_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR=0.7` are calibrated against single-zettel LOOKUP queries where one strong chunk grounds the answer at >= 0.5 / 0.7 cross-encoder score. Cross-corpus THEMATIC synthesis lacks single-chunk grounding even when 4-5 zettels collectively support the answer — no individual chunk crosses the floor.

**The fix:** add a per-class **additive offset** that LOWERS the effective floor for THEMATIC/STEP_BACK only — LOOKUP and VAGUE keep the original floor. Hard-clamped to >= 0.3 so the gate can never be disabled outright.

**Mechanism:**
```
_effective_partial_floor(cls) = max(0.3, _PARTIAL_NO_RETRY_FLOOR + offset_for(cls))
```
where `offset_for(THEMATIC) = float(env["RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC"], default 0.0)`.

The default offset is **0.0** (no behaviour change unless operator sets the env var). iter-11 operator-approved value is `-0.1` (effective threshold 0.4 for THEMATIC/STEP_BACK).

**Operator approval (CLAUDE.md guardrail interaction):** the `_PARTIAL_NO_RETRY_FLOOR` family is in CLAUDE.md's "HARD RULES — never silently undo" list. iter-11 has explicit chat-confirmed approval to introduce the additive-offset path BUT NOT to lower the LOOKUP-default literal value. The implementation must:
1. Keep `_PARTIAL_NO_RETRY_FLOOR = 0.5` as the LITERAL (not lowered).
2. Add `_effective_partial_floor(cls)` helper that branches on class.
3. Apply the helper at every call site that previously used the literal.
4. Hard-clamp the effective floor to >= 0.3 so the gate cannot be disabled even with extreme env values.

**Pitfalls / cons NOT to take:**
- DO NOT change the literal `_PARTIAL_NO_RETRY_FLOOR = 0.5` — the LOOKUP default must stay at 0.5 per CLAUDE.md guardrail. Only the per-class effective value changes.
- DO NOT add an offset for LOOKUP or VAGUE classes — those queries have single-chunk grounding; lowering their floor risks hallucination.
- DO NOT use a multiplicative factor (e.g. `floor * 0.8`) — additive offsets are easier to reason about and clamp.
- DO NOT remove the hard-clamp `max(0.3, ...)` — without it, an env mistake could disable the entire gate.

**Edge cases:**
- An operator sets `OFFSET_THEMATIC=-0.99` (extreme) → effective floor clamps to 0.3, NOT 0.0 or negative.
- A new query class added to the enum (e.g. `EXPLAIN`) → falls through `_offset_for_class` returning 0.0, gets the LOOKUP-default floor. Safe by default.
- Both partial and unsupported floors share the same offset env var convention but DIFFERENT env keys — `RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC` vs `RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR_OFFSET_THEMATIC`. Don't conflate.

**Where this lands:** [PLAN.md](PLAN.md) Phase 5 / Task 6.

---

## Class E1 — scorer N/A handling for `expected=[]`

**Verdict: ✓ ship Phase 6.**

**The problem (iter-10 q9 cosmetic):** q9 ("Summarize what this Kasten says about Notion's database features.") has `expected=[]` — it's an adversarial-by-design refusal-expected query. iter-10 produced primary=None with `unsupported_no_retry`, which is the canonical refusal flow — **correct behaviour**. But `_aggregate_gold_metrics` treats `gold_at_1=False` mechanically, so q9 depresses the headline gold@1 from 0.7143 (10/14) to 0.6429 (9/14) for what is actually a passing test.

**The fix:** in `_aggregate_gold_metrics`, segregate rows where `expected_empty == True`. They contribute to a separate `gold_at_1_not_applicable` count; they're EXCLUDED from numerator AND denominator of `gold_at_1_unconditional` and `gold_at_1_within_budget`.

`_holistic_metrics` is the upstream caller; it must set `r["expected_empty"] = not bool(d.get("expected"))` per row before delegating to `_aggregate_gold_metrics`.

The scores.md template gets one new line: `- gold@1 not applicable: <count> (refusal-expected)`.

**Pitfalls / cons NOT to take:**
- DO NOT count `expected_empty` rows as gold_at_1=True — they're not "passing", they're "not applicable". Putting them in the numerator inflates the metric.
- DO NOT silently drop the row from the report — the operator wants to know how many adversarial queries ran (count is shown separately).
- DO NOT widen N/A treatment to other "soft fail" cases (e.g. budget violations) — `expected=[]` is a precise contract; other failure modes have their own metrics.

**Where this lands:** [PLAN.md](PLAN.md) Phase 6 / Task 7.

---

## Class E2 — SSE buffering investigation (must-do before iter-11 closes)

**Verdict: ⚠ investigate, then decide whether to count buffer-wait in `p_user`.**

**The problem (iter-10 fact):** server-side `latency_ms_server` is 0.9-1.9 s for every query; client-side `p_user_first_token_ms` is 22-37 s. The 25-30 s gap happens between server response-write and JS reader receiving the first SSE token. It could be:

- **H1 — Cloudflare buffers SSE until upstream completes:** real browsers using `EventSource` would also wait. → user-perceived; `p_user` is honest.
- **H2 — Caddy buffers responses larger than its sse-buffer config:** same as H1.
- **H3 — Playwright `fetch().getReader()` doesn't fire until full response is buffered, but a real `EventSource` consumer flushes on each frame:** synthetic harness artefact; `p_user` overstated.

**The investigation (PLAN.md Phase 7 / Task 8):**

1. Open DevTools console on `https://zettelkasten.in/home/rag` while signed in.
2. Open a real `new EventSource(...)` against `/api/rag/adhoc?...` and time first `token` event.
3. Compare to Playwright's `p_user_first_token_ms` for the same query.

**Decision rule:**
- If real-browser ttft is 1-3 s → H3 (harness artefact). The server is fast; iter-12 should switch the harness to use `EventSource` (or fetch with proper streaming flush) so `p_user` matches user reality. **iter-11 leaves `p_user` as-is** but documents the artefact in `iter-11/scores.md` so the headline `ttft_avg` isn't taken at face value.
- If real-browser ttft is also 22-37 s → H1/H2 (real wait). The user IS waiting through the buffer. **iter-11 keeps `p_user` honest;** iter-12 needs a Caddy/Cloudflare config investigation (probably `flush_interval` or `X-Accel-Buffering` already-set; or Cloudflare's SSE handling).

**Pitfalls / cons NOT to take:**
- DO NOT change `p_user` reporting in iter-11 based on a guess — actually run the DevTools experiment.
- DO NOT switch the harness to non-streaming mode (`stream=false`) as a workaround — that hides ttft entirely; iter-09 had this and it lost the signal. SSE is the right primitive; the question is just where the gap comes from.
- DO NOT try to fix Caddy / Cloudflare buffering in iter-11 even if H1/H2 is confirmed — that's iter-12 infra work and needs separate guardrail review (touching Caddy upstream config interacts with the `read_timeout 240s` guardrail).

**Where this lands:** [PLAN.md](PLAN.md) Phase 7 / Task 8.

---

## Already-merged context (background for executor)

| Commit | Subject | Status |
|---|---|---|
| `f54a3e6` | docs: iter-10 scores top5 dynamic fixes (REVERTED to canonical template via `e699760`) | iter-10 cleanup |
| `e699760` | docs: iter-10 scores canonical template | iter-10 final |
| `77f786d` | fix: dedup retrieval recall plus clamp 0 100 | iter-10 final |
| `aea614d` | fix: stub supabase in cross class fixture for ci | iter-10 final |
| `f245c6b` | docs: iter-10 env flags | iter-10 final |

iter-10 shipped: harness `t0` arithmetic fix (P1), gold@1 split (P6), anchor-seed un-gate + 4 mitigations (P4), post-answer side-effects fire-and-forget (P2), chunk_count_quartile tiebreak (Item 3), dense-only fallback + Supabase migration (P5), score-rank magnet gate (P3), pre-rerank floor (P9), clause-coverage in SYSTEM_PROMPT (P13), RSS slot logging (P8), chunk_share TTL + THEMATIC empty logs (P12), CI grep guard for unwrapped @router.post, per-stage timing (P17). Skipped: P11 auto-title pin (Task 7) — RES-7 premise was wrong.

---

## Quick-reference: env flags introduced or modified by iter-11

| Flag | Default | Phase / Task | Purpose |
|---|---|---|---|
| `RAG_SCORE_RANK_PROTECT_ANCHORED` | `true` | 2 / 3 | Class A — anchor / title-overlap exemption on score-rank gate |
| `RAG_SHORT_THEMATIC_THRESHOLD` | `4` | 4 / 5 | Class D — word-count threshold for short-THEMATIC gazetteer expansion |
| `RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC` | `0.0` (recommended `-0.1` for iter-11 eval) | 5 / 6 | Class F — additive offset on partial-no-retry floor |
| `RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR_OFFSET_THEMATIC` | `0.0` (recommended `-0.1` for iter-11 eval) | 5 / 6 | Class F — additive offset on unsupported-with-gold-skip floor |

Class B (name-overlap tiebreak override) ships without an env flag — it's a structural-correctness fix that should not be revertible operationally.

Class C (per-entity anchor union) ships without an env flag — same reason.

Class E1 (scorer N/A) is a scorer change, no runtime env flag.

Class E2 (SSE investigation) may produce a harness change (`ops/scripts/eval_iter_03_playwright.py`) but no runtime env flag.

---

## Quick-reference: Supabase migrations introduced by iter-11

None expected. All five fixes are app-side only. (Class C touches `entity_anchor.py` which calls existing RPCs; no new SQL.)

---

## Success criteria

iter-11 final eval MUST hit ALL of:

| Metric | Target | Source |
|---|---|---|
| Composite | ≥ 85 | Approved by user |
| gold@1_unconditional | ≥ 0.85 | Approved by user (excludes `expected_empty` rows post-E1) |
| gold@1_within_budget | ≥ 0.85 | Approved by user (same exclusion) |
| within_budget (alone) | ≥ 0.85 | Implicit from above |
| Burst 503 rate | ≥ 0.08 | Held from iter-10 |
| Burst 502 rate | 0% | Multi-user safety; iter-12 carry-over if not met |
| Per-query failures (q1-q14, q9 expected_empty) | 0 | All non-adversarial queries pass |
| Worker OOM events during eval | 0 | Multi-user safety |

If any one of these fails (excluding burst 502 which has separate iter-12 carry-over status), iter-11 is incomplete and iter-12 carries the remainder.

**Projected gold@1 trajectory** (one fix at a time, no regression, post-E1 N/A treatment):

| After fix | gold@1 | within_budget | Comments |
|---|---:|---:|---|
| iter-10 baseline | 0.6429 | 0.6429 | flat headline |
| + E1 (q9 N/A excluded) | 0.6923 | 0.6923 | 9/13 (q9 removed from denominator) |
| + Class C (q10 recovers) | 0.7692 | 0.7692 | 10/13 |
| + Class A (q8 recovers) | 0.8462 | 0.8462 | 11/13 |
| + Class D (q7 recovers) | 0.9231 | 0.9231 | 12/13 ✓ |
| + Class B (q12 recovers) | 1.0000 | 1.0000 | 13/13 ✓ |
| + Class F (q5 synth no longer refuses) | 1.0000 | 1.0000 | gold@1 unchanged but user sees an answer |

The exact trajectory assumes no regressions; the cross-class regression fixture is the safety net.
