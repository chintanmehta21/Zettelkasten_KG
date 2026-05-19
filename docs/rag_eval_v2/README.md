# rag_eval_v2 — Phase E (offline in-process eval)

DB-v2 successor to `docs/rag_eval/`. The v1 loop drove the RAG pipeline
through a live Playwright browser session and scored the resulting
`verification_results.json`. Post-DB-v2 that path is broken
(`score_rag_eval._fetch_chunks_for_nodes` is a Phase-A stub returning empty
contexts; the slug-keyed `kg_nodes` driver was purged). **rag_eval_v2 drives
the in-process orchestrator directly** and rebuilds RAGAS contexts from real
chunk text, so faithfulness is not degraded.

## Tree

```
docs/rag_eval_v2/
  README.md                     <- this file
  scripts/
    run_eval_v2.py              offline in-process harness (the deliverable)
    compare_baseline.py         baseline delta + cross-Kasten aggregate
    post_iter_v2.py             thin wrapper over post_iter_audit.run_audit
  psychedelic-drugs/
    links.txt                   8 curated URLs (operator ingests these)
    INGEST.md                   exact create_kasten CLI for the operator
    queries.json                12 queries (iter-11 schema)
    baseline_score.json         iter-11 legacy composite reference
    iter-<N>/                   written by run_eval_v2.py per run
  economics/
    links.txt                   9 curated URLs
    INGEST.md
    queries.json                12 queries
    baseline_score.json
    iter-<N>/
```

### Per-iter artifact set (`<kasten>/iter-<N>/`, mirrors iter-11/iter-06)

| file | producer | content |
|---|---|---|
| `baseline_score.json` | copied from Kasten root | iter-11 legacy reference |
| `queries.json` | harness (copy + resolved members) | run-time `members_node_ids`, `kasten_id` |
| `expected_vs_actual.json` | harness | per-query expected vs retrieved/primary/verdict |
| `eval.json` | harness (`EvalRunner` + holistic) | composite + component + holistic |
| `scores.md` | harness (`_render_scores_md`) | the scorecard (same renderer as v1) |
| `failure_analysis.md` | harness | per-query exceptions + gold-primary misses |
| `improvement_notes.md` | harness | auto-suggested next-iter levers |
| `post_iter_audit.md` | harness (`post_iter_audit.run_audit`) | offline audit roll-up |

## Offline-harness design

`run_eval_v2.py`:

1. **Env bootstrap before any rag import.** Loads the vault-root `.env`
   (`SUPABASE_V2_*`) + `api_env` (3 Gemini keys), and **forces**
   `RAG_MODEL_DIR` to the worktree `models/` dir (ms-marco-MiniLM-L-12-v2 +
   calibration; BGE stage-2 auto-downloads or RRF-falls-back). The runtime
   factory + reranker read `RAG_MODEL_DIR` at first import under `lru_cache`,
   so this must precede the import — enforced by importing inside `run()`
   after `bootstrap_env()`.
2. **Resolve the Kasten.** `RAGRepository.list_kastens` by name (Naruto =
   `f2105544-...`), then `list_kasten_zettels(kasten_id)` →
   `[{canonical_zettel_id, workspace_zettel_id, title, source_type}]`.
3. **Scope to the Kasten via `ChatQuery.sandbox_id`.** This is the *real*
   scoping mechanism: `HybridRetriever._resolve_nodes` calls
   `rag.resolve_effective_nodes_v2(p_kasten_id=...)`. The v2 RPC **retired**
   the free-form `scope_filter.node_ids` knob (hybrid.py:1088-1091) — a
   non-empty `node_ids` "degrades gracefully to the unfiltered kasten member
   list." The harness still passes the resolved member zettel ids in
   `scope_filter.node_ids` as harmless, self-documenting belt-and-suspenders,
   but `sandbox_id` is what actually scopes retrieval.
4. **chunk_id → canonical_zettel_id remap (the load-bearing step).**
   `AnswerTurn.retrieved_node_ids` and `Citation.node_id` are
   `canonical_chunk_id` values (chunk UUIDs — orchestrator.py:1168/1316,
   hybrid.py:685/757), **not** zettel ids or slugs. Gold is keyed by zettel.
   The harness reads `content.canonical_chunks` for the Kasten's canonical
   zettels, builds `{chunk_id: canonical_zettel_id}`, and remaps every answer
   id to a zettel id before scoring. **Without this remap retrieval/rerank
   scores are structurally ~0** (chunk-uuid never equals zettel-uuid).
5. **RAGAS contexts.** Built by the harness from citation snippets, backfilled
   from `canonical_chunks` text for retrieved zettels (target ≥3, cap 8).
   `AnswerTurn` does not expose chunk text, so empty contexts would crater
   faithfulness — this is why the harness re-fetches.
6. **Settle/poll.** KG + chunk population after `create_kasten` is
   fire-and-forget; `--settle-seconds` polls `canonical_chunks` until every
   member zettel has ≥1 chunk (or timeout) before querying.
7. **Score.** `expected_primary_citation` (a case-insensitive title
   substring) → `canonical_zettel_id` via `list_kasten_zettels` title match,
   fed as the verification-style `expected` override into the reused
   `_build_gold_queries`; then `EvalRunner.evaluate(...)` (LEGACY composite
   weights `chunking 0.1 / retrieval 0.25 / reranking 0.2 / synthesis 0.45`,
   hash via `composite.hash_weights_file`) + reused `_holistic_metrics` /
   `_render_scores_md`.
8. **Deterministic, resumable, never-crash.** Each query is isolated in a
   try/except — one failure is captured into `failure_analysis.md` and the
   run continues. Re-running overwrites `iter-<N>/` idempotently.

Reused offline-safe helpers (no live Playwright, no `score_rag_eval.main`):
`_load_weights`, `_build_gold_queries`, `_holistic_metrics`,
`_aggregate_gold_metrics`, `_per_class_breakdown`, `_render_scores_md`,
`post_iter_audit.run_audit`.

## Baseline cross-mapping

The v1 loop converged at **iter-11, composite 60.26 (LEGACY weights)**:

| stage | iter-11 |
|---|---|
| chunking | 40.43 |
| retrieval | 64.26 |
| reranking | 52.45 |
| synthesis | 65.92 |
| **composite** | **60.26** |
| faithfulness (sidecar) | 87.86 |
| answer_relevancy (sidecar) | 85.71 |

`baseline_score.json` in each Kasten carries this. **The mapping is NOT
1:1** and `compare_baseline.py` says so explicitly:

* The iter-11 baseline is the *knowledge-management* Kasten — a different
  corpus, query set, and member set than psychedelic-drugs / economics.
  Neither v2 Kasten has a prior run, so there is no per-Kasten baseline.
* It is carried as the **pipeline-quality bar to beat**, scored under the
  *same* LEGACY composite definition the v1 loop optimized, so iter-1 of each
  v2 Kasten is comparable to where v1 left off — not as an expected score.
* Exactly as iter-12 does, v2 reports the LEGACY composite **and** the
  trust-first holistic block (`gold@1`, `accuracy_user_visible`,
  `over_refusal_rate`, `under_refusal_rate`) alongside, so an improvement is
  never judged on the legacy composite alone. The composite-weights yaml
  (`docs/rag_eval/_config/composite_weights.yaml`) keeps the `legacy` block
  applying through iter-11 and `trust_first` from iter-12; v2 deliberately
  reuses the **legacy** block for cross-loop continuity and surfaces
  trust-first as the holistic sidecar.
* `compare_baseline.py` adds a **cross-Kasten aggregate** (mean composite,
  `min(delta)` overfit guardrail, mean gold@1) so a gain that lands on only
  one Kasten is flagged rather than celebrated.

## Operator run order (gated — not run here)

1. `docs/rag_eval_v2/psychedelic-drugs/INGEST.md` → `create_kasten` CLI.
2. `docs/rag_eval_v2/economics/INGEST.md` → `create_kasten` CLI.
3. `python docs/rag_eval_v2/scripts/run_eval_v2.py --kasten psychedelic-drugs --iter 1 --settle-seconds 45`
4. `python docs/rag_eval_v2/scripts/run_eval_v2.py --kasten economics --iter 1 --settle-seconds 45`
5. `python docs/rag_eval_v2/scripts/compare_baseline.py --iter 1`

The harness is offline/in-process: no Playwright, no browser, no HTTP — it
calls `orchestrator.answer` directly. It still needs live Supabase v2 reads +
live Gemini for synthesis, which is why ingestion + the real run are
operator-gated.
