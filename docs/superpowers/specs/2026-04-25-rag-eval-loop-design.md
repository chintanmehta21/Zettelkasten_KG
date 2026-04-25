# RAG Pipeline Evaluation Loop — Design Spec

**Date:** 2026-04-25
**Author:** chintanmehta21 (assisted)
**Status:** Approved (verbal); pending plan verification before execution
**Mirrors:** `docs/summary_eval/` methodology
**Code root:** `website/features/rag_pipeline/`
**Artifact root:** `docs/rag_eval/`

---

## 1. Scope & North Star

Build a `rag_eval` loop framework that mirrors `summary_eval`'s discipline (two-phase state machine, blind manual review with hash-stamp enforcement, dead-data logging, halt mechanism, per-source synthesis), but for the RAG pipeline at `website/features/rag_pipeline/`. The loop must also evolve the Knowledge Graph (KG) bidirectionally — the KG informs RAG retrieval (already wired via `LocalizedPageRankScorer`), and the RAG eval must feed KG mutations back so both surfaces co-improve.

**Unit-of-work shift from summary_eval:**

| `summary_eval` | `rag_eval` |
|---|---|
| One URL per iter | One **Kasten** (set of Zettels) per iter |
| One summary output | Five **(query, answer, citations)** outputs per iter (bumped from the template's 3 — see §2) |
| `summary.json` + `eval.json` | `kasten.json` + `queries.json` + `answers.json` + `eval.json` + KG sidecars |
| Per-source rubric (brief/detailed/tags) | Per-stage component scores (chunking / retrieval / rerank / synthesis) plus KG↔RAG cohesion sidecars |
| RAGAS not used | RAGAS = primary; DeepEval = supplementary |

**Decision: artifact root is `docs/rag_eval/`.**
Why: parallel structure to `docs/summary_eval/` lets reviewers context-switch without remapping mental models.
How to apply: every artifact path in this spec lives under that root.

**Decision: code modifications scoped to `website/features/rag_pipeline/`.**
Why: matches user-stated `@rag_pipeline` constraint and keeps eval code colocated with the pipeline under test.
How to apply: new evaluation harness lives at `website/features/rag_pipeline/evaluation/`. Never modify `summarization_engine` or `summary_eval` from this loop.

---

## 2. Per-Iteration Kasten Allocation (the schedule)

Adapted from `summary_eval` §4.1. Each source gets a **fixed Kasten** test fixture; iterations grow the Kasten in controlled steps so score deltas attribute cleanly to either the *pipeline change* or the *new Zettel*.

**YouTube schedule (5 iters):**

| iter | Kasten state | Queries | Role |
|---|---|---|---|
| 01 | 5 seed Zettels | 5 fixed seed queries | Baseline measurement |
| 02 | Same Kasten | Same 5 queries | Tune (after pipeline edit) |
| 03 | Same Kasten | Same 5 queries | Tune (after pipeline edit) |
| 04 | **+1 semantically similar Zettel** (now 6 Zettels) | Same 5 queries | Probe — does retrieval still pick the right doc when a similar distractor is present? |
| 05 | **+1 unseen Zettel** (now 7 Zettels) | **3 fresh held-out queries** targeting the unseen Zettel | Generalization — measures overfitting |

**Reddit / GitHub / Newsletter schedule (3 iters):**

| iter | Kasten state | Queries | Role |
|---|---|---|---|
| 01 | 5 seed Zettels | 5 fixed seed queries | Baseline measurement |
| 02 | **+1 semantically similar Zettel** (now 6 Zettels) | Same 5 queries | Combined tune + probe (single tuning opportunity) |
| 03 | **+1 unseen Zettel** (now 7 Zettels) | **3 fresh held-out queries** | Generalization |

**Decision: seed queries 1–5 are frozen across all tuning iters of a source.**
Why: drift in the question set obscures whether a code change improved the pipeline.
How to apply: the eval CLI rejects edits to `_config/queries/<source>/seed.yaml` after iter-01 commits. Held-out queries live in `_config/queries/<source>/heldout.yaml` and are sealed until the final iter runs.

**Decision: 5 seed queries (not the template's 3).**
Why: 5 gives denser per-iter signal without bloating runtime; aligns with user direction.
How to apply: `gold_loader.py` validates exactly 5 entries in `seed.yaml` and exactly 3 in `heldout.yaml`.

---

## 3. Per-Stage Scoring

Five independent component scores, each on a 0–100 scale, combined into a composite.

### 3a. Composite weights

**Decision: composite weights are `chunking 10 / retrieval 25 / reranking 20 / synthesis 45` by default; dynamic but strict across iters.**
Why: synthesis is the user-visible artifact and gets the largest slice; retrieval+rerank determine what synthesis can say; chunking is upstream and harder to attribute to single-iter changes.
How to apply:
- Weights live in `docs/rag_eval/_config/composite_weights.yaml`.
- Mid-loop reweighting is BLOCKED. The CLI re-hashes the weights file at the start of each Phase A and refuses to proceed if the hash differs from the locked value in iter-01's `input.json`.
- Weights MAY change between full per-source loops (e.g., after YouTube finishes iter-05, before Reddit starts iter-01) only when justified by a `decision` observation explaining the rationale.
- Any weight change that does not move the composite by ≥1 absolute point on the prior iter's data is rejected as cosmetic.

### 3b. Component formulas

| Stage | Metric source | Component score formula (0–100) |
|---|---|---|
| **Chunking** | Internal probe (no LLM) | Mean of: token-budget compliance, semantic coherence (cosine sim of adjacent chunks via existing embedder), boundary integrity (no mid-sentence/code-fence cuts), de-dup rate. |
| **Retrieval** | Gold node IDs in `seed.yaml` | `0.4·Recall@10 + 0.3·MRR + 0.3·Hit@5`, scaled ×100. |
| **Reranking** | Gold node IDs + gold ranking | `0.5·NDCG@5 + 0.3·Precision@3 + 0.2·(1 − FP_rate@3)`, scaled ×100. |
| **Synthesis** | RAGAS + DeepEval | `0.3·faithfulness + 0.2·answer_correctness + 0.2·context_precision + 0.15·answer_relevancy + 0.15·DeepEval_semantic_similarity`. RAGAS metrics 0–1, scaled ×100. |
| **Composite** | Weighted | Per §3a weights, normalized to 0–100. |

### 3c. Gold-data schema (per query)

`seed.yaml` and `heldout.yaml` entries:

```yaml
- id: q1
  question: "What's the consensus on DMT's mechanism in the brain?"
  gold_node_ids: ["yt-strangest-drug-ever-studied"]
  gold_ranking: ["yt-strangest-drug-ever-studied", "yt-insanity-of-salvia"]
  reference_answer: |
    DMT acts primarily as a 5-HT2A receptor agonist...
  atomic_facts:
    - "DMT is a 5-HT2A receptor agonist"
    - "Endogenous DMT presence in mammalian brain is debated"
```

### 3d. RAGAS / DeepEval division of labor

**Decision: RAGAS = authoritative; DeepEval = sanity check.**
Why: RAGAS owns the standard retrieval-quality metrics (context_precision, context_recall) the user named; DeepEval gives semantic similarity that RAGAS does less well.
How to apply: if RAGAS and DeepEval disagree by >0.2 on overlapping signals (faithfulness vs. hallucination, answer_relevancy vs. answer_relevance), `eval.json` flags `eval_divergence: true` and `next_actions.md` surfaces the disagreement for the next iter.

---

## 4. Two-Phase State Machine

Mirror of `summary_eval` `eval_loop.py`. Same four states:

| State | Detected when | What CLI does |
|---|---|---|
| `PHASE_A_REQUIRED` | iter dir empty or only partial artifacts | Builds Kasten, ingests Zettels into RAG (chunk → embed → upsert), runs queries (with-graph + ablated), writes `kasten.json`, `ingest.json`, `queries.json`, `answers.json`, `eval.json`, `ablation_eval.json`, `kg_snapshot.json`, `manual_review_prompt.md`, `run.log` |
| `AWAITING_MANUAL_REVIEW` | `manual_review_prompt.md` exists, no `manual_review.md` | Prints prompt path, exits 0 |
| `PHASE_B_REQUIRED` | `manual_review.md` exists | Verifies blind-review hash stamp, runs determinism gate (re-evals iter n-1, halts on >3pt drift), writes `diff.md` + `next_actions.md` + `improvement_delta.json` + `kg_health_delta.json` + `kg_recommendations.json`, applies KG mutations (autonomous — see §8), commits |
| `ALREADY_COMMITTED` | `diff.md` exists | Noop |

**Manual review schema (blind-stamped):**

```markdown
# iter-NN manual review — <source> — <date>

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: <0–100>
estimated_retrieval: <0–100>
estimated_synthesis: <0–100>

## Per-query observations
- Q1: <did the right Zettel get cited? was the answer faithful?>
- Q2: ...
- Q3: ...
- Q4: ...
- Q5: ...

## Per-stage observations
- Chunking: ...
- Retrieval: ...
- Reranking: ...
- Synthesis: ...
- KG signal (graph_lift): ...
```

Phase B rejects the file if the hash stamp is anything other than `"NOT_CONSULTED"`, or if `estimated_composite` is missing.

**Decision: `manual_review.md` is written by a Claude subagent (cross-LLM blind review), not by a human.**
Why: user direction "blind-stamped manual review remains" + "no manual intervention now" — the discipline survives only via a separate-context, separate-LLM reviewer. The eval pipeline runs on Gemini; the reviewer runs on Claude (different model family, different provenance), preventing model-bias collusion between evaluator and reviewer.
How to apply:
- Phase A's CLI dispatches a `Claude subagent` (model: `claude-haiku-4-5` to conserve API budget) via the Agent tool with isolation: the subagent receives ONLY `manual_review_prompt.md`, `queries.json`, `answers.json`, `kasten.json`, `kg_snapshot.json`. It MUST NOT receive `eval.json`, `ablation_eval.json`, or `kg_recommendations.json`.
- The subagent's system prompt enforces: "Stamp `eval_json_hash_at_review: \"NOT_CONSULTED\"`. You have not seen any evaluator output. Estimate composite scores from your own reading of the answers vs. reference_answer + atomic_facts. Be honest about uncertainty."
- The subagent writes `manual_review.md` to the iter directory and exits.
- Phase B verifies the hash stamp + estimate fields as before. Subagent transcripts are saved to `iter-NN/_review_subagent_transcript.json` for audit.
- Cross-LLM disagreement (subagent estimate vs. computed composite) is logged in `improvement_delta.json` under `review_divergence_band` (≤5pt = AGREEMENT, 5–10pt = MINOR, >10pt = MAJOR). MAJOR triggers a pessimistic next-iter target per `summary_eval` precedent.

**Decision: determinism tolerance = 3pt (vs `summary_eval`'s 2pt).**
Why: RAG synthesis adds an LLM call atop summarization → more variance per run.
How to apply: `--skip-determinism` allowed only on iter-01; otherwise CLI re-runs iter-(n-1) and halts if composite |Δ| > 3.

---

## 5. Data Sources for Zettels

**Decision: primary source = Naruto user's existing Zettels in Supabase KG; supplementary = `docs/research/Chintan_Testing.md`.**
Why: Naruto is an established fixture user (existing scripts: `naruto_cleanup.py`, `naruto_diag.py`, `reassign_yt_to_naruto.py`, `register_iter20_naruto.py`). Chintan_Testing is a curated link list ideal for filling Kasten gaps.
How to apply:
- Kasten builder reads from Supabase via `KGRepository.get_graph(naruto_user_id)`.
- If a semantically-similar Zettel (cosine ≥0.75 against the seed Kasten centroid) is needed for iter-04 probe and the Naruto pool lacks one, the builder ingests a fresh URL from `Chintan_Testing.md`.
- Chintan-sourced Zettels are stamped with `metadata.source_provenance: "chintan_testing"` so KG analysis can distinguish them from organic Naruto Zettels.

**Per-source seed Kastens:**

| Source | Seed theme | Fallback rationale |
|---|---|---|
| YouTube | Psychedelics & neuroscience (Huberman / Joe Rogan / Vsauce-style) | Chintan_Testing entries 1, 27, 29 |
| Reddit | Indian sociopolitics (r/IndiaSpeaks, r/hinduism, r/CritiqueIslam) | Chintan_Testing entries 11, 12, 19, 25 |
| GitHub | RAG / LLM tooling repos | Falls back to Chintan if Naruto pool is thin |
| Newsletter | Tech strategy (Stratechery, Pragmatic Engineer, Lenny's) | Wired in `summary_eval/_config/branded_newsletter_sources.yaml` |

If the Naruto pool is empty for a theme, `kasten.json` flags `creation_rationale: "auto-bootstrapped from Chintan_Testing.md entries [n,m,...]"`.

**Decision: Naruto Zettels are STRONGLY preferred over Chintan_Testing fallback for billing-key conservation.**
Why: each Chintan-sourced Zettel forces a fresh URL ingestion (extraction + summarization + embedding = ~5 LLM calls per Zettel) which charges against the paid Gemini billing key when free-tier keys are exhausted. Naruto Zettels are already ingested.
How to apply:
- Kasten builder lists Naruto's existing Zettels for the source FIRST and exhausts that pool before considering Chintan_Testing.
- Probe iters (iter-04) prefer a Naruto Zettel with cosine ≥0.65 (relaxed from the 0.75 threshold) before falling back to a fresh Chintan ingestion.
- Held-out iters (final) prefer a Naruto Zettel with cosine 0.50–0.70 (semantically nearby but distinct) before falling back.
- The CLI logs `_billing_key_warning.md` if any iter's run requires Chintan ingestion, with rationale for review.

---

## 6. File Layout

```
docs/rag_eval/
  _config/
    composite_weights.yaml          # 10/25/20/45 baseline
    rubric_chunking.yaml
    rubric_retrieval.yaml
    rubric_rerank.yaml
    rubric_synthesis.yaml           # RAGAS metric mapping
    queries/
      youtube/seed.yaml             # frozen 5 queries + gold
      youtube/heldout.yaml          # 3 fresh queries for final iter
      reddit/seed.yaml ...
  _cache/
    embeddings/                     # cached chunk embeddings (LRU)
    rag_runs/                       # cached pipeline runs by config-hash
  _dead_zettels/                    # zettels that failed ingestion
  _kg_changelog.md                  # cross-source KG mutation log
  <source>/
    iter-01/
      kasten.json                   # zettel list, source URLs, ingestion status
      ingest.json                   # chunk count per zettel, embedding model, latency
      queries.json                  # the queries + gold answers (machine-readable)
      answers.json                  # pipeline outputs (machine-readable)
      qa_pairs.md                   # HUMAN-READABLE: pairs each Q with system answer, gold answer, citations, per-query scores side-by-side
      eval.json                     # RAGAS + DeepEval + per-stage component scores + graph_lift
      scores.md                     # HUMAN-READABLE scorecard: per-stage scores, composite, deltas vs prior iter
      ablation_eval.json            # eval re-run with graph_weight=0
      atomic_facts.json
      kg_snapshot.json              # pre-iter KG slice (Kasten + 1-hop neighbors)
      kg_health_delta.json          # vs iter-(NN-1)
      kg_recommendations.json       # advisory + auto-applied mutations
      kg_changes.md                 # HUMAN-READABLE: KG mutations applied this iter
      pipeline_changes.md           # HUMAN-READABLE: code changes made before this iter (the "wide-net" change manifest)
      manual_review_prompt.md
      manual_review.md
      _review_subagent_transcript.json  # audit trail for cross-LLM blind review
      diff.md
      next_actions.md
      improvement_delta.json
      run.log
      input.json                    # config snapshot for replay
    iter-02/ ...
    iter-05/ (or 03)                # held-out final iter, contains held_out/ subdir like summary_eval
  _synthesis.md                     # cross-source closure (manually written after final iter)

ops/scripts/
  rag_eval_loop.py                  # the CLI (mirrors eval_loop.py)
  apply_kg_recommendations.py       # autonomous KG-mutation applicator (§8b)
  lib/
    rag_eval_state.py               # state machine
    rag_eval_kasten.py              # Kasten builder + ingestion
    rag_eval_metrics.py             # RAGAS + DeepEval glue + component scorers
    rag_eval_diff.py                # iter-NN vs iter-(NN-1) diff
    rag_eval_kg.py                  # KG snapshot + recommendation engine

website/features/rag_pipeline/evaluation/
  __init__.py
  types.py                          # extend with EvalResult, ComponentScores, GoldQuery
  ragas_runner.py                   # wraps RAGAS + key-pool integration
  deepeval_runner.py                # DeepEval glue
  component_scorers.py              # chunking/retrieval/rerank scorers
  gold_loader.py                    # loads queries/<src>/seed.yaml, validates
  composite.py                      # weighted composite + delta arithmetic
  ablation.py                       # graph_weight=0 ablation harness
  kg_recommender.py                 # generates kg_recommendations.json
```

---

## 7. Build Sequence (phased delivery)

Phases ship behind tests; each phase commits independently with `feat:` / `test:` / `docs:` prefixes per CLAUDE.md (5–10 word subjects, no AI attribution).

| Phase | Deliverable | Verification gate |
|---|---|---|
| **0** | Discovery & contracts: pin RAGAS/DeepEval API surface, freeze YAML schemas, document Naruto user's KG state | Schema files validate against pydantic models; no impl code yet |
| **1** | Evaluation harness in `website/features/rag_pipeline/evaluation/`: ragas_runner, deepeval_runner, component_scorers, composite, gold_loader | Unit tests against fixture pipeline outputs; ≥90% line coverage on new modules |
| **1.5** | KG ablation harness (`ablation.py`) — runs eval with graph_weight=0 | Unit test confirms identical retrieval candidate set with and without graph weight on a fixed seed |
| **2** | Kasten builder (`rag_eval_kasten.py`): load Zettels from Supabase / Chintan_Testing, drive ingestion via existing `rag_pipeline.service`, write `kasten.json` + `ingest.json` | Integration test against a stubbed Supabase client + mock Naruto Zettels |
| **2.5** | KG snapshot + recommendation engine (`rag_eval_kg.py`, `kg_recommender.py`) — read-only Supabase access for snapshots; `apply_kg_recommendations.py` autonomous mutator with dry-run flag for verification | Unit tests for each recommendation type's trigger condition |
| **3** | CLI + state machine (`rag_eval_loop.py`): PHASE_A/B detection, dry-run, halt, blind-review enforcement, determinism gate | State-machine tests cover all four states + edge transitions |
| **4** | Configs + seed data: `rubric_*.yaml` (×4), `queries/<source>/seed.yaml` (×4 with 5 queries each + gold), `queries/<source>/heldout.yaml` (×4 with 3 queries each), `composite_weights.yaml` | YAML schema validation in CI; gold queries dry-runnable through ingestion |
| **5** | Smoke run + iter-01 baseline for YouTube end-to-end | Full pipeline round-trip green; eval.json produced; manual_review_prompt.md emitted |
| **6a** | YouTube iteration loop only: iters 1→5 end-to-end, then HALT and report. | Determinism gate green between consecutive iters; held-out scores within 5pt of seed-iter mean (else flagged as overfit) |
| **6b** | (gated on user approval after 6a) Reddit / GitHub / Newsletter iter loops 1→3. | Same gate as 6a, applied per source |

**Decision: Phase 6 splits into 6a (YouTube only, autonomous) and 6b (other sources, gated on user review).**
Why: user direction — run all YouTube iters end-to-end, stop, let user review, then continue. Limits blast radius of any pipeline-edit regression and lets the user catch systemic issues before three more loops compound them.
How to apply: after iter-05 commits and `_synthesis.md` is written for YouTube, the CLI emits `RAG_EVAL_HALT_FOR_REVIEW` to stdout, writes `docs/rag_eval/.youtube_complete` sentinel file, and exits 0. Reddit/GitHub/Newsletter loops will not start until the user explicitly removes the sentinel or invokes `--source reddit --iter 1` directly.

**Decision: each tuning iter REQUIRES wide-net multi-component changes; single-line tweaks are blocked.**
Why: user direction — "robust, wide-net changes across each iteration", "do not proceed with minimal adjustments". Phase B's `improvement_delta.json` captures a `change_breadth` metric and the CLI rejects iters that don't meet the threshold.
How to apply (the change-breadth gate):
- Each tuning iter (YouTube 02/03/04, Reddit/GitHub/Newsletter 02) MUST modify ≥3 of these 6 RAG components: `ingest/chunker.py`, `ingest/embedder.py`, `retrieval/hybrid.py`, `rerank/cascade.py`, `query/rewriter.py`/`query/router.py`, `generation/prompts.py`.
- Each tuning iter MUST also touch ≥1 config or weight surface (composite_weights.yaml, fusion_weights in cascade.py, depth_by_class in hybrid.py, top_k limits, MMR lambda).
- The CLI runs `git diff iter-(n-1)..HEAD --stat` at the start of Phase B and writes `pipeline_changes.md`. If <3 components touched OR no config/weight change, Phase B refuses to commit and emits `CHANGE_BREADTH_INSUFFICIENT`; the human must either expand the change or document a `decision` rationale for the narrow scope.
- `qa_pairs.md` and `scores.md` are AUTO-GENERATED (not committed by hand) — they're rendered from `answers.json` + `eval.json` + `queries.json` for human review.

**Decision: each tuning iter targets specific known weaknesses surfaced by the prior iter's `next_actions.md`.**
Why: wide-net changes without direction become churn. Each iter's `pipeline_changes.md` MUST cite which `next_actions.md` items it addresses.
How to apply: `next_actions.md` items are tagged with IDs (`NA-iter02-01`, `NA-iter02-02`, ...); `pipeline_changes.md` references them in its commit body and Phase B verifies coverage.

---

## 8. KG↔RAG Co-evolution Layer

### 8a. KG → RAG: explicit lift measurement

Each iter runs eval **twice**: once with graph-signal weight at production levels, once with `graph_weight = 0` (ablation). Delta = `graph_lift`:

```
graph_lift_composite     = composite_with_graph − composite_ablated
graph_lift_retrieval     = retrieval_score_with_graph − retrieval_score_ablated
graph_lift_rerank        = rerank_score_with_graph − rerank_score_ablated
```

Recorded in `eval.json` as a top-level `graph_lift: { ... }` block. Sign + magnitude indicate whether the KG is currently a net asset for this Kasten.

**Decision: graph_lift is reported separately, NOT folded into the composite.**
Why: folding it in would double-count the graph signal (already inside retrieval/rerank scores). Sidecar reporting makes it actionable — negative lift triggers a `next_actions` item targeting the KG, not the pipeline.
How to apply: composite weights stay 10/25/20/45; `graph_lift` lives next to but not inside the composite.

### 8b. RAG → KG: the autonomous recommendation stream

Each iter writes `kg_recommendations.json`:

| Type | Trigger | Payload |
|---|---|---|
| `add_link` | Right gold Zettel had retrieval rank > 5 AND was graph-distant from query-best Zettel | `{from_node, to_node, suggested_relation, evidence_query_ids}` |
| `add_tag` | Atomic-fact named entity not in any Kasten Zettel's `tags` | `{node_id, suggested_tag, evidence_atomic_fact}` |
| `merge_nodes` | Two Zettels co-cited in ≥2 of 5 answers AND content cosine > 0.85 | `{node_a, node_b, similarity, evidence_query_ids}` |
| `reingest_node` | Zettel cited in synthesis but RAGAS faithfulness < 0.5 for that answer | `{node_id, low_faithfulness_count, evidence_query_ids}` |
| `orphan_warning` | Kasten Zettel with degree 0 in `kg_links` | `{node_id, current_tags}` |

**Decision: `apply_kg_recommendations.py` runs AUTONOMOUSLY between iters by default.**
Why: user direction — "minimal manual work". Autonomous application closes the co-evolution loop tightly (iter-NN's recommendations land in the KG before iter-(NN+1) runs).
How to apply:
- `apply_kg_recommendations.py --iter <N>` is invoked automatically by the CLI at the end of Phase B.
- The applicator runs in two modes via separate confidence thresholds:
  - **High-confidence auto-apply (default)**: `add_link` (with cosine evidence ≥0.7), `add_tag` (atomic-fact match score ≥0.8), `orphan_warning` (annotation only — adds metadata, no edges).
  - **Quarantine for review**: `merge_nodes`, `reingest_node`. These mutations write to `kg_recommendations.json` with `status: "quarantined"` and append to `_kg_changelog.md` with rationale; the user can apply them via `apply_kg_recommendations.py --iter <N> --types merge_nodes,reingest_node --confirm` between sessions.
- All applied mutations are reversible via Supabase audit logs (each mutation writes a `kg_audit` row capturing the prior value).
- A safety brake: if an iter's `kg_recommendations.json` proposes >5 mutations of any single type, the applicator halts and quarantines the entire batch for human review (catches runaway recommendation generators).

### 8c. Per-iter KG snapshot + delta

`kg_snapshot.json` captures the Kasten Zettels + their 1-hop neighbors (pre-iter):

```json
{
  "node_count": 18, "edge_count": 47, "mean_degree": 5.2,
  "orphan_count": 1, "tag_count": 23,
  "tag_histogram": { "psychedelics": 4, "neuroscience": 6 },
  "kasten_node_ids": [...], "neighborhood_node_ids": [...]
}
```

`kg_health_delta.json` captures iter-NN vs iter-(NN-1) diff: edges added (from new Zettel's tag-shared links), orphan rate change, mean-degree drift, applied-mutation list. Pipeline metrics improving while KG health degrades is a **red flag** logged in `next_actions.md`.

### 8d. Closure section in `_synthesis.md`

After each per-source loop ends, the synthesis doc answers:
1. Did `graph_lift` trend positive across iters? (KG getting more useful)
2. How many `kg_recommendations.json` items were applied between iters? (RAG actively improving KG)
3. Did orphan rate decrease across iters? (mutual pull toward density)
4. Did retrieval recover when a "wrong" Zettel was de-emphasized via `reingest_node`? (closing the loop)

---

## 9. Verification Checkpoints (per iter, before advancing)

- ✓ All 5 (seed) or 3 (held-out) queries evaluated with scores recorded
- ✓ All pipeline component scores documented in `eval.json`
- ✓ Ablation eval (`ablation_eval.json`) present; `graph_lift` block populated
- ✓ Determinism gate green (or `--skip-determinism` justification logged for iter-01)
- ✓ KG snapshot + delta files present
- ✓ KG recommendations applied or quarantined per §8b
- ✓ `improvement_delta.json` shows non-cosmetic delta (≥1pt absolute composite change) OR root-cause analysis is documented in `next_actions.md`
- ✓ Code committed with change log and improvement rationale

---

## 10. Out of Scope

- Modifying `website/features/summarization_engine/` (frozen for this loop)
- Modifying `docs/summary_eval/` (the prior loop's artifacts stay sealed)
- Re-architecting the existing `rag_pipeline/orchestrator.py`, `service.py`, or `types.py` interfaces (we extend, not replace)
- Building a UI for eval results (CLI + JSON artifacts are sufficient; KG UI already shows applied mutations via existing graph rendering)
- LLM-judge live-eval (deferred per `summary_eval/_synthesis.md` rationale; deterministic component scoring + RAGAS is sufficient signal)

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| RAGAS API instability across versions | Pin RAGAS version in `ops/requirements-dev.txt`; wrap in `ragas_runner.py` with a versioned adapter |
| Naruto user's Supabase state drift between sessions | Snapshot `kg_snapshot.json` at iter-01; halt CLI if mid-loop snapshot diverges by >10% on node count or >20% on edge count without an applied recommendation explaining it |
| Autonomous KG mutations cascade incorrectly | Safety brake (>5 mutations of one type halts batch); audit-log reversibility; quarantine for `merge_nodes` / `reingest_node` |
| Gemini key-pool exhaustion during multi-iter eval runs | **Two-tier escalation policy:** (1) Free-tier keys (key1, key2 in `api_env`) handle baseline traffic via the existing `GeminiKeyPool` key-first traversal. (2) When BOTH free-tier keys hit 429 within a single iter, the CLI auto-promotes the **billing key (key3)** to exclusive use for the rest of that iter and logs `_billing_key_active.md`. (3) When the billing key itself reports 429 / quota-exhausted, the CLI writes `.halt` (with state for resume after quota reset) and exits 1. Billing-key calls are minimized by: preferring Naruto Zettels over Chintan ingestion (§5), caching RAGAS run hashes in `_cache/rag_runs/`, and skipping ablation eval (`graph_weight=0`) on billing key — the ablation re-runs once free-tier quota recovers. |
| RAGAS metric values drift due to LLM stochasticity | Determinism gate (3pt tolerance); cache RAGAS run hashes by `(query, answer, context)` tuple in `_cache/rag_runs/` |
| Held-out queries leak into seed via reviewer memory | `heldout.yaml` is sealed (read-permission stripped) until the final iter's Phase A; CLI verifies file mode at run start |

---

## 12. Execution Checkpoint Policy (this run)

For the first execution of this design (2026-04-25 onward), the autonomous flow is:

1. Spec written + committed (this document)
2. Implementation plan produced via `superpowers:writing-plans`
3. **Independent subagent verification of the plan** (gate; user-imposed)
4. Implementation phases 0–5 land sequentially with their own test gates
5. Phase 6a: YouTube iters 1→5 run end-to-end autonomously (cross-LLM blind reviews per §4; KG mutations applied autonomously per §8b)
6. **HARD HALT**: write `.youtube_complete` sentinel + emit `RAG_EVAL_HALT_FOR_REVIEW`. User reviews YouTube `_synthesis.md` before authorizing 6b.
7. Phase 6b runs only on explicit user authorization.

Subsequent runs (after the YouTube → user review handshake) may operate the loop autonomously per source without re-gating, since the framework's correctness will have been validated by the YouTube loop.

---

## 13. Glossary

- **Zettel** — a single captured note (one URL → summary + chunks + KG node)
- **Kasten** — a topic-coherent collection of Zettels evaluated together as a RAG knowledge base
- **graph_lift** — composite-score delta between (graph weight = production) and (graph weight = 0)
- **Naruto user** — established fixture user in Supabase (`naruto_*` scripts in `ops/scripts/`)
- **Gold node IDs** — the Zettel IDs a query SHOULD retrieve, hand-curated in `seed.yaml`
- **Held-out** — the final iter's unseen Zettel + 3 fresh queries; measures generalization
- **Determinism gate** — re-runs iter-(n-1) eval at the start of iter-n's Phase A; halts on >3pt drift

---

## Appendix A — RAGAS Metric Mapping

| RAGAS metric | Maps to component | Weight in synthesis score |
|---|---|---|
| `faithfulness` | Synthesis | 0.30 |
| `answer_correctness` | Synthesis | 0.20 |
| `context_precision` | Synthesis (and Retrieval cross-check) | 0.20 |
| `answer_relevancy` | Synthesis | 0.15 |
| `context_recall` | Retrieval cross-check (NOT in synthesis) | sidecar |

DeepEval contributes `semantic_similarity` (0.15 of synthesis) and `hallucination` (cross-check vs `faithfulness`; flagged on disagreement >0.2).

---

## Appendix B — Open Questions Deferred to Implementation

These are NOT design questions; they're implementation details to resolve during Phase 1:

- Embedding model for component_scorers' chunk-coherence calculation (re-use existing `ChunkEmbedder` if available)
- LRU cache size for `_cache/rag_runs/` (start at 1000 entries, tune from observed hit rate)
- Specific RAGAS version pin (latest stable as of 2026-04-25 plus the version that supports async evaluation natively)
- Concrete YAML schema for each `rubric_*.yaml` — derive from existing `summary_eval/_config/rubric_*.yaml` patterns
