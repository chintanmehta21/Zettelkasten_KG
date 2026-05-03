# Iter-08 Research Reference

This document is the consolidated research artefact for iter-08. It exists for two audiences:

1. **Future humans / agents looking back at iter-08** — to understand what we knew, what we tried, and what we deliberately rejected.
2. **The plan executor (subagent or human running [PLAN.md](PLAN.md))** — to look up rationale, edge cases, and "why not X" decisions when a phase task references them.

Each section below corresponds to one research agent's verdict (RES-1..7, ACT-1, ACT-5). When a PLAN.md task references "RESEARCH.md §N", consult the corresponding section here for full context.

**Cross-reference:** [PLAN.md](PLAN.md) — implementation tasks. This file is the why; PLAN.md is the how.

---

## How the executor should use this file

When implementing any PLAN.md phase, **before writing code or tests for that phase**:

1. Read the matching `RES-N` or `ACT-N` section here.
2. If a task is unclear, look up "Pitfalls" and "Cons NOT to take" — they capture every dead end already explored.
3. If a test fails in an unexpected way, check "Edge cases" for that section — many edge cases were already mapped during research.
4. If you encounter a decision point not covered here, **stop and ask the user** rather than improvising — the user has explicitly required approval before any beyond-plan decision.

---

## RES-1 — cite-filter direct vs gated

**Question:** how should `_build_citations` (orchestrator.py:1030+) be filtered to drop cites the LLM didn't actually use?

**Two designs evaluated:**
- **Design A — direct filter:** drop cites whose `rerank_score < 0.5` AND not the primary, always.
- **Design B — gated filter:** filter to LLM-cited ids, with a min-N safety net.

**Verdict: Hybrid B (NOT A).** BGE int8 rerank scores in our cascade are uncalibrated against the fusion stage (cascade.py:737 multiplies raw rerank by 0.60 for fusion — treats them as relative, not absolute probabilities). A hard 0.5 threshold would silently drop legitimately-supporting hops on multi-hop / thematic queries — exactly the "fixes one class, breaks another" trap.

**Critical follow-up:** does `a["contexts"]` (the array passed to RAGAS) flow from `used_candidates` or from `citations`? Answer **confirmed in RES-5**: from `citations` (proof: `ops/scripts/rag_eval_loop.py:122` builds `contexts = [c.get("snippet")... for c in citations]`). So filtering moves RAGAS `context_precision` (big lever).

**Cons NOT to take:**
- Design A direct 0.5 cut — uncalibrated scores, regression risk on q4/q5/q6.
- Per-class hardcoded minimums (LOOKUP=1, MULTI_HOP=2, THEMATIC=3) — `expected_minimum_citations` lives only in `queries.json` fixtures, not in production code; baking those numbers in production silently overfits the eval.
- Atomic-claim parsing + re-cite — too invasive.

**Where this lands in PLAN.md:** Phase 5.

---

## RES-2 — kasten_freq dead-prior diagnosis

**Question:** has the iter-04 `kasten_freq` anti-magnet penalty been a no-op for 6 iters?

**Verdict: confirmed dead. Replace, don't tune.**

**Evidence:**
- `_MIN_TOTAL_HITS_FOR_PENALTY = 50` (kasten_freq.py:34); below the floor, `compute_frequency_penalty` returns 1.0 (multiplicative identity).
- KM Kasten = 7 zettels. ~12 successful queries × 4 iters = ~48 record_hit attempts max. Distributed evenly = ~7 per node. Far below 50 floor.
- `record_hit` is fire-and-forget (`asyncio.create_task` at orchestrator.py:914-919), gated by `verdict ∈ {supported, partial, retried_supported}` AND non-empty citations. Refusals don't write.
- Migration `2026-04-30_kasten_node_frequency.sql` exists in repo (`supabase/website/kg_public/migrations/`); production-applied state cannot be verified from this side.
- Both read and write paths swallow errors silently — if the migration was never applied, no user-visible failure surfaces.
- Floor=50 was a guess in commit `8f4eada` with no empirical grounding.

**Replacement (RES-4 + Phase 4):** per-zettel chunk-share normalization — `rrf_score *= 1/sqrt(chunk_count_per_node)`. Orthogonal to history, no cold-start, structurally attacks the magnet root cause confirmed in RES-4.

**Cons NOT to take:**
- Lower the kasten_freq floor to 5 (option a) — band-aid that keeps every other weakness of the freq-prior (cold-start fragile, persistence-dependent, lagging indicator).
- Pre-seed from kg_node telemetry (option b) — mixes user-engagement signal with retrieval-magnet signal.
- Compute on-the-fly per-query (option c) — doesn't help; magnets are visible across queries, not within one (already MMR's job).

**Where this lands in PLAN.md:** Phase 4.

---

## RES-3 — thematic n=5→3 revert effects

**Question:** should we revert iter-07's THEMATIC `_multi_query` n=5 back to n=3?

**Verdict: UNCONDITIONAL REVERT.**

**Evidence:**
- iter-06 (n=3) and iter-07 (n=5) retrieved IDENTICAL `retrieved_node_ids` on q5 — the only query n=5 was added for. Same 5 ids, same order. **n=5 added zero retrieval delta.**
- The +2 LLM reformulations were either deduped (`_dedupe`, transformer.py:58) or rerank-eliminated by stage-2 BGE int8.
- Cost: linear stage-2 rerank time (sub-batched at 5, sequential per sub-batch — cascade.py:312); +1 RPC variant; larger downstream synth context that contributed to q13/q14 → 402 quota burn.
- The real q5 fix lives at BM25/embedding-recall level — Stanford / Walker / transformative-tools never reached the rerank pool, so variant count isn't the lever.

**Pitfalls:**
- Do NOT remove the `RAG_THEMATIC_MULTIQUERY_N` env knob — keep it for future A/B once retrieval recall is fixed.
- Do NOT change MULTI_HOP n=3 (it's correct as-is).

**Cons NOT to take:**
- Scale n with Kasten size — RES-3 verified more variants don't generate new node_ids when they're not in the rerank pool to begin with.
- Keep n=5 + add quota safeguard — pays recurring cost (rerank time, RPC, downstream synth tokens) for a feature that demonstrably does nothing on its target query.

**Where this lands in PLAN.md:** Phase 1.

---

## RES-4 — magnet hypothesis + KG opportunities

**Question:** why do `yt-effective-public-speakin` and `web-transformative-tools-for` keep winning top-1 across queries that aren't about them?

**Verified chunk counts (KM Kasten, 7 zettels):**

| node_id | chunks | summary chars | total chunk chars | tags |
|---|---:|---:|---:|---:|
| yt-effective-public-speakin (magnet) | **16** | 5,372 | 5,774 | 10 |
| yt-steve-jobs-2005-stanford | 13 | 4,084 | 4,364 | 10 |
| nl-the-pragmatic-engineer-t | 10 | 3,948 | 4,413 | 10 |
| yt-programming-workflow-is (magnet) | 6 | 2,099 | 2,417 | 8 |
| web-transformative-tools-for (magnet) | 6 | 1,913 | 2,266 | 8 |
| yt-matt-walker-sleep-depriv | 3 | 705 | 1,239 | 15 |
| gh-zk-org-zk | 2 | 4,107 | 9,311 | 10 |

**Three hypotheses tested:**
- A — chunk-count bias: PARTIALLY CONFIRMED (yt-effective-public-speakin has 16 chunks, 2.5× the median).
- B — broad/encyclopedic content: STRONGLY CONFIRMED. `web-transformative-tools-for` summary tagged `tools-for-thought, cognitive-enhancement, augmented-learning` — theme-of-Kasten tags overlap with almost any THEMATIC query.
- C — query-side bias: NOT THE ROOT CAUSE. `_dedupe_variants` + consensus-suppress already mitigate it.

**Recommended bundle (in priority order):**
- **B3** class-aware `_cap_per_node`: cap=1 for THEMATIC/LOOKUP, keep cap=3 for MULTI_HOP/STEP_BACK. Direct hit on chunk-count advantage.
- **B5** xQuAD λ=0.5 for THEMATIC (today uniform 0.7). Buy more diversity for cross-corpus need.
- **B4** text-only compare-intent regex (closes iter-07 Fix B's "Naval not in Kasten" hole on q10).
- **C** KG entity-anchor boost: when `metadata.authors|entities` non-empty, add `+0.05 * is_1hop_neighbour` to candidate.rrf_score. Only proposed change that adds NEW signal vs damping existing.

**Cons NOT to take:**
- **B1 sqrt(chunk_count)** on rrf_score — punishes legitimately rich content like nl-pragmatic-engineer-t (10 chunks, currently correct top-1 6/12 times). Note: chunk-share normalization shipped in Phase 4 INSTEAD, gated separately + suppressed under compare-intent.
- **B2 token-overlap floor** — slugified titles + thematic tags overlap too often to fire reliably.
- **Edge-type weighted PageRank** — currently only "shared-tag" edges exist; needs schema migration first (deferred to Phase 8).
- **Modify PageRank graph build** — too invasive.

**Where this lands in PLAN.md:** Phase 3 (B3+B5+B4) + Phase 6 (KG anchor) + Phase 4 (chunk-share). Phase 8 lays the schema groundwork for future edge-type weighting.

---

## RES-5 — cite hygiene safety gate design

**Question:** how to ship "cite hygiene" (filter `_build_citations` to LLM-cited ids) without regressing q1/q4/q11?

**CRITICAL FINDING:** `a["contexts"]` (RAGAS input) IS sourced from `citations` (proof: `ops/scripts/rag_eval_loop.py:122`). Filtering `_build_citations` directly moves RAGAS `context_precision` — big lever, not just critic verdict.

**Approved design:**
- Plug filter inside `_build_citations` AFTER existing dedup/sort, BEFORE returning the Citation list.
- Parser regex: `r'\[id\s*=\s*["\']?([a-zA-Z0-9_\-]+)["\']?\]'` — matches the canonical syntax in `prompts.py:22`.
- Intersect ranked_candidates with cited_ids by node_id.
- Safety gate: if filtered list has < `_CITE_HYGIENE_MIN_KEEP` (default 1), fall back to top-K (`_CITE_HYGIENE_FALLBACK_TOPK=3`).
- If LLM cited nothing inline (cited_ids empty), keep ranked_candidates as-is — no regression vs today.
- Env flags: `RAG_CITE_HYGIENE_ENABLED` (**default false** for dark canary), `RAG_CITE_HYGIENE_MIN_KEEP=1`, `RAG_CITE_HYGIENE_FALLBACK_TOPK=3`.

**Edge cases mapped:**
1. Fabricated id — already dropped from `answer_text` at `orchestrator.py:768` (existing `strip_invalid_citations`) before critic runs.
2. Same id 3× in a row — set semantics dedupe.
3. LLM cites no ids inline — `cited_ids == set()` → skip filter → no regression.
4. Refused answer — existing `_SUPPRESS_CITATIONS_ON_REFUSAL` gate fires before this path.

**Pitfalls:**
- Default OFF for first deploy. Flip on via env-only after iter-08 reproducer passes.
- Do NOT hardcode per-class minimums.
- Do NOT move filter to `_finalize_answer` — forks streaming/non-streaming paths.
- Do NOT reuse critic's `_find_bad_citations` regex (legacy `[id,id]` form).

**Cons NOT to take:**
- Direct 0.5 score cut (Design A) — see RES-1.
- Per-class minimums — overfits eval fixture.
- Atomic-claim parsing — too invasive.

**Canary procedure:** flip `RAG_CITE_HYGIENE_ENABLED=true` on droplet via env-var only (no redeploy), run iter-08 eval, compare q1/q4/q11. Roll back via env flip if regression.

**Where this lands in PLAN.md:** Phase 5.

---

## RES-6 — RAGAS JSON parse-fail handling

**Question:** what's the ideal handling when the RAGAS judge returns malformed JSON?

**Today:** `ragas_runner.py:83` returns `{name: 0.0}` for all 5 metrics on parse failure. The per-query refactor (commit `adeafe9`) confines the blast radius to one sample, but a single zero on faithfulness/correctness still drops that query's synthesis sub-score.

**Three options evaluated:**
- (a) 1 retry with stricter prompt
- (b) Default-to-0.5 (neutral)
- (c) Mark `eval_failed` and exclude from cohort

**Verdict: mix (a)+(c).** Retry once with stricter prompt; if still fails, mark `eval_failed=True`. Cohort mean excludes flagged rows. Mirrors RAGAS upstream behaviour (`np.nan` + `pd.DataFrame.mean()` excludes NaN by default) and the existing empty-answer pattern from `adeafe9`.

**Industry alignment:** LangChain `OutputFixingParser`, Instructor's `max_retries`, OpenAI structured-outputs cookbook all use retry-then-mark-failure. None recommend fabricated neutral default.

**Pitfalls:**
- `synthesis_score.py` and `eval_runner.py` consumers MUST treat the `eval_failed` flag — otherwise `0.0` still leaks.
- Schema drift: per-query record gains a key — bump JSON schema/contract test.
- Don't retry on every exception — gate on `JSONDecodeError`/empty rows. 429/5xx already has key-pool retry semantics.
- Cap retry at 1 (not 2+). 14 queries × 1 retry = ~$0.07 max, ~30s extra latency worst case.
- Apply identically to `deepeval_runner.py` (same contract).

**Why not (b) default-to-0.5:** fabricates a metric the judge never produced; pollutes cohort with synthetic prior; hides bugs (broken prompt becomes invisible because everything looks "average"); contradicts the determinism goal.

**Why not (a) alone:** still ends in 0.0 on retry-fail, just delayed.

**Where this lands in PLAN.md:** Phase 7.B.

---

## RES-7 — NDCG normaliser asymmetry fix

**Question:** how to fix the NDCG asymmetry where multi-source queries face a harder ideal_dcg than single-source?

**Today (`component_scorers.py:99`):** `ideal_dcg = dcg(gold_ranking[:k_ndcg])` with `k_ndcg=5`.

| `\|gold\|` | ideal_dcg | example queries (iter-07) |
|---|---|---|
| 1 | 1.000 | 10× lookup |
| 2 | 1.631 | 2× multi-source |
| 4 | 2.564 | 1× thematic |
| 5 | 2.949 | (none in iter-07) |

**Asymmetry:** a multi-source query that retrieves 1/2 gold at rank 1 scores `1.0/1.631 = 0.613`; a single-source query that retrieves 1/1 gold at rank 1 scores `1.000`. Same retrieval skill, different score — purely an artifact of `|gold|`.

**Three options evaluated:**
- (a) `min(k_ndcg, len(gold_ranking))` — per-query achievable max
- (b) NDCG@1
- (c) Average Precision

**Verdict: (a).** Standard textbook fix (Järvelin & Kekäläinen 2002, sklearn.metrics.ndcg_score, pytrec_eval). One-line patch:

```python
ideal_k = min(k_ndcg, len(gold_ranking))
ideal_dcg = dcg(gold_ranking[:ideal_k])
ndcg = actual_dcg / ideal_dcg if ideal_dcg else 0.0
```

**Side-effect to expect:** factoid scores rise modestly while thematic scores rise more (narrowing the gap). May be misread as a "rerank regression" in iter-08 vs iter-07 — actually it's the normaliser becoming honest.

**Pitfalls:**
- For `|gold|=1` the metric collapses to "hit at rank 1 with positional discount" — correct: there's only one right answer; "nearby" gold beyond rank 1 can't be rewarded.
- Document the side-effect in iter-08/scores.md.
- Add safety assert: `actual_dcg <= ideal_dcg` (cannot violate with binary rel + same gold_set).

**Why not (b) NDCG@1:** throws away ranking signal between positions 2-5; degenerates to binary Hit@1; duplicates `hit_at_k` in `retrieval_score`.

**Why not (c) Average Precision:** double-counts the "fraction of gold in top-k" axis (existing `0.3·P@3 + 0.2·(1-FP@3)` already covers precision); collapses NDCG-vs-P@k orthogonality.

**Where this lands in PLAN.md:** Phase 7.D.

---

## ACT-1 — component scorer audit (top 3 + others)

**Top 3 by composite impact (combined +12 to +18):**

| # | Issue | File:line | Affected | Δ composite |
|---|---|---|---|---:|
| 1 | Boundary regex `[.!?\n]\s*$` rejects `)`/`*`/`]`/`|`/code-fence/headings | component_scorers.py:34-36 | every non-refusal query, 30% chunking weight | **+6 to +9** |
| 2 | `target_tokens=512` hard-coded; chunker emits 200-400 tokens | eval_runner.py:167 × component_scorers.py:27-31 | every Kasten, 40% chunking weight | **+4 to +6** |
| 3 | Coherence pinned at 50 (embeddings never passed) | component_scorers.py:39-49 × eval_runner.py:166 | every Kasten, 20% chunking weight | **+2 to +3** |

**Other findings (smaller deltas, all in PLAN.md Phase 7):**
- Empty-list cliff (`component_scorers.py:24`): empty chunks → 0 instead of skip-from-mean. **Phase 7.E.**
- Refusal-path retrieval scoring (`eval_runner.py:117-119`): binary 100/0; punishes correct end-to-end refusals when retrieval surfaces decoys.
- NDCG asymmetry (`component_scorers.py:98-100`). **Phase 7.D.**
- FP-rate redundant with P@k (effectively 0.5*P).
- RAGAS JSON-parse zero cliff. **Phase 7.B.**
- DeepEval same parse-fail pattern.
- `answer_relevancy` aggregation mixes RAGAS dataset-mean with refusal per-query unit. **Phase 7.C.**
- Refusal phrase exact-match brittle. **Phase 7.A.**
- RAGAS `context_recall` computed but unused.
- RAGAS `context_precision` capped at 4 chunks/node — gold info beyond chunk 5 invisible.
- `eval_divergence` threshold arbitrary (informational only).
- p50/p95 latency no outlier cap. **Phase 7.H.**
- Composite `compute_composite` no NaN/None guard. **Phase 7.F.**
- `score_rag_eval.py:240-248` qid join silently drops unscored queries. **Phase 7.G.**

**Cons NOT to take:**
- Replace boundary regex with token-aware boundary detection — chunker already enforces semantic boundaries via Phase 2.4; soft-regex is sufficient.
- Drop coherence weight to 0 — would lose the only semantic-similarity signal in chunking score; better to fetch real embeddings (Phase 2.3).
- Add RAGAS `context_recall` to synthesis weight — judge already computes it; just adding more weight without verifying it correlates with quality is overfitting risk.

**Where this lands in PLAN.md:** Phase 2 (top 3) + Phase 7.

---

## ACT-5 — chunker boundary + KG-RAG audit

**Chunker analysis:**
- Location: `website/features/rag_pipeline/ingest/chunker.py:99` (`ZettelChunker`).
- Dispatch: short-form sources (reddit/twitter/github/generic) → `_atomic_chunk` (line 187). Long-form (youtube/substack/medium/web) → Late → Semantic → Recursive → Token cascade (lines 144-161).
- Default config: `LONG_CHUNK_TOKENS=512`, `LONG_OVERLAP_TOKENS=64`. All Chonkie chunkers are token-budget driven, NOT sentence-aware.

**Sampled 90 actual chunks from `kg_node_chunks`:**
- Hard boundary (`[.!?\n]\s*$`) match rate: **50.0%**
- Soft-boundary endings (`,;:>]"'`): additional **14.4%** → 64.4% combined
- ~36% mid-word/mid-token (e.g. `'cheap but prone to errors, and a slower, multi-step \\'`)

**Representative endings (real DB samples):**
- `yt-andrej-karpathy-s-llm-in[1]`: `…multi-step \\` (mid-word)
- `yt-andrej-karpathy-s-llm-in[2]`: `…current text-only limi` (mid-word)
- `yt-software-1-0-vs-software[0]`: `…the efficacy of the Softwa` (mid-word)
- `yt-transformer-architecture[0]`: `…### Tokenization and Positional Encodin` (mid-word, mid-heading)
- `web-digital-gardening[2]`: `…'Building a Second Brain' and 'Learn in Public' philosophies.` (clean ✓)

**Why score is frozen at 31.94:** `eval_runner.py:167` calls `chunking_score(target_tokens=512)` — many real chunks are 16, 364, 479, 511 tokens — most fail the budget test (≥30% pass), and ~50% fail boundary, plus coherence defaults to 50. The 31.94 ≈ 0.4·30 + 0.3·50 + 0.2·50 + 0.1·100 ≈ 32. Frozen because chunking pipeline hasn't changed across iter-03→07.

**Recommended fix: BOTH (a) and (b), weighted.**
- (a) Relax scorer regex to accept `[.!?,;:>]"'`*\|<code-fence>]` as soft-boundaries. Cheap, immediate +5 component (~+0.5 composite). Justified because Chonkie's Recursive/Token chunkers split on semantic separators (commas, sentences, paragraphs).
- (b) Snap chunker output to nearest sentence boundary within ~10% token slack. Real win: 50 → 80+. Also improves retrieval relevance (mid-word chunks lose lexical signal).

**KG Usage Edges workflow:** wired via `ops/scripts/recompute_usage_edges.py` + `.github/workflows/recompute_usage_edges.yml` (cron `0 2 * * *`). Bonus is bounded ±0.05 vs RRF magnitudes ~0.5-1.0 — small effect. Not urgent; widen to ±0.10 once ≥30 days of supported-verdict data accumulates.

**RAG-KG improvement opportunities:**
1. **Per-zettel chunk-share normalization** at `hybrid.py:307` — direct attack on chunk-count bias (Phase 4).
2. **Edge-type-weighted PageRank** — currently every kg_link edge has weight=1.0. Today only "shared-tag" edges exist; needs `kg_link.relation` enum + RPC change. **Phase 8** lays the schema groundwork; consumer code defers to iter-09.
3. **Cite-graph for compare queries** — when `query_metadata.authors >= 2`, fetch each author's canonical node_id, intersect with `kg_expand_subgraph(seeds=[author1_node, author2_node], depth=1)`, bump `rrf_score += 0.05` for candidates in the intersection. (Subset of Phase 6 KG entity-anchor boost.)

**Cons NOT to take:**
- Replace Chonkie wholesale — too invasive.
- Drop coherence weight — see ACT-1 cons.
- Snap-to-sentence on short atomic-chunk sources (reddit/twitter/github) — already one chunk per zettel, no benefit.
- Modify the PageRank graph build directly — too invasive.

**Where this lands in PLAN.md:** Phase 2.4 (snap chunker) + Phase 4 (chunk-share) + Phase 6 (entity-anchor) + Phase 8 (edge-type schema).

---

## Already-merged context (background for executor)

These two commits landed during the research phase and are already on master. PLAN.md depends on them being present.

| Commit | Subject | What it does | Files |
|---|---|---|---|
| `adeafe9` | per-query RAGAS so empty answers don't dilute cohort | Replaces single-batched gemini-2.5-pro call with per-query calls. Empty answers (HTTP 402 / refused) get zeros without polluting batch-mean. New `RAG_EVAL_RAGAS_PER_QUERY` env flag (default true). | `evaluation/ragas_runner.py`, `evaluation/deepeval_runner.py`, `evaluation/eval_runner.py` + tests |
| `cc04b1e` | retry guard partial-with-gold + suppress citations on refusal | (Fix A) `_should_skip_retry` short-circuits when `first_verdict == "partial"` AND top rerank ≥ 0.5; (Fix B) `_build_citations` returns `[]` when `verdict == unsupported_no_retry` or `refused == True`. Both env-gated. | `orchestrator.py` + tests |

Phase 5 (cite hygiene) extends `_build_citations` from `cc04b1e` with the LLM-cited filter; the `answer_text` kwarg is new.

Phase 7.B (RAGAS parse-fail) extends the per-query path from `adeafe9` with retry-then-eval_failed.

---

## Quick-reference: env flags introduced by iter-08

| Flag | Default | Phase | Purpose |
|---|---|---|---|
| `RAG_THEMATIC_MULTIQUERY_N` | 3 | 1 | thematic variant count (was 5 in iter-07) |
| `RAG_CHUNKER_SENTENCE_SNAP_ENABLED` | true | 2.4 | snap long-form chunks to sentence ends |
| `RAG_CHUNK_SHARE_NORMALIZATION_ENABLED` | true | 4 | per-zettel chunk-share anti-magnet |
| `RAG_CITE_HYGIENE_ENABLED` | **false** (dark) | 5 | filter cites to LLM-cited only |
| `RAG_CITE_HYGIENE_MIN_KEEP` | 1 | 5 | min cites after filter to apply |
| `RAG_CITE_HYGIENE_FALLBACK_TOPK` | 3 | 5 | fallback top-K when filter degenerate |
| `RAG_ANCHOR_BOOST_ENABLED` | true | 6 | KG entity-anchor 1-hop bonus |
| `RAG_ANCHOR_BOOST_AMOUNT` | 0.05 | 6 | per-neighbour rrf bump |

These should be added to `ops/.env.example` in Phase 9 alongside the deploy.

---

## Quick-reference: Supabase migrations introduced by iter-08

| File | Phase | Purpose | Risk |
|---|---|---|---|
| `2026-05-03_rag_kasten_chunk_counts.sql` | 4 | RPC: per-Kasten chunk count for chunk-share normalization | low (read-only, additive) |
| `2026-05-03_rag_entity_anchor.sql` | 6 | RPCs: entity → anchor-node + 1-hop neighbours | low (read-only, additive) |
| `2026-05-03_kg_link_relation_enum.sql` | 8 | Adds `kg_link.relation` enum column with `shared_tag` default | low (additive column with default) |

All three must be manually applied to production Supabase per CLAUDE.md (migrations don't auto-deploy). See PLAN.md Phase 9.2 step 2.
