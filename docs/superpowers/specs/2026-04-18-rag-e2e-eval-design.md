# RAG End-to-End Evaluation & Module Refactor Loop — Design

**Date:** 2026-04-18
**Owner:** Chintan
**Status:** Approved (awaiting implementation plan)
**Supersedes:** N/A — complements `2026-04-12-rag-chatbot-design.md` (the build spec) by adding the eval/refactor layer.

## Problem

The RAG pipeline in `website/features/rag_pipeline/` is fully built and unit-tested but has never been evaluated end-to-end on real user data against production Supabase. We do not know:

1. Whether ingest actually fires on the live website capture path (the flag `rag_chunks_enabled` is currently `false`).
2. How well retrieval / rerank / generation actually answer questions against a real user's corpus.
3. Which module is the bottleneck when answers are wrong.

Without an answer-level score per module, "improve the RAG pipeline" is unfalsifiable. This spec defines the harness, dataset, scoring rubric, and loop mechanics that make improvement measurable.

## Non-Goals

- Building a new RAG architecture. The pipeline stays; we tune it.
- Frontend changes to `/chat` or `/knowledge-graph`. Eval runs against `/api/rag/adhoc`.
- Multi-user evaluation. Naruto's 34-zettel corpus is the target.
- Telegram bot wiring. Website is the primary surface.

## Design

### Scope phases

The work splits into three phases with hard gates between them.

**Phase A — Unblock prod ingest (in-conversation).** Without this, nothing else matters.
- Finish refactor from prior session: `website/experimental_features/nexus/service/persist.py` imports `ingest_node_chunks` from `website.features.rag_pipeline.ingest.hook` and deletes its local `_maybe_ingest_rag_chunks`. The `rag_chunks_enabled` feature-flag check stays at the call site (inside `_persist_supabase_node`).
- Migrate `tests/unit/rag/test_persist_ingest.py` → `tests/unit/rag/ingest/test_hook.py`, adapt to the public symbol, keep both the "flag on → ingest fires" and "flag off → no-op" cases.
- Flip `rag_chunks_enabled: true` in `ops/config.yaml` and document the env override (`RAG_CHUNKS_ENABLED`).
- Commit, deploy via the existing GitHub Actions → droplet blue/green path.
- **Gate:** verify one fresh Naruto capture on `https://zettelkasten.in` writes ≥1 row into `kg_node_chunks` in prod Supabase. No Phase B work until this passes.

**Phase B — Eval harness (in-conversation).** New in-tree package so it can be run by `ops/scripts/rag_module_loop.py` against prod.

Layout:
```
website/features/rag_pipeline/evaluation/
  __init__.py
  corpus.py          # cluster Naruto's 34 zettels into 5-6 Kastens
  questions.py       # loader + schema for questions.yaml
  rubric_b.py        # active rubric (4-axis, 0-5 each, /20 total)
  rubric_c.py        # RAGAS scaffold — NotImplementedError with wiring points
  judge.py           # Claude-as-judge call (separate key-pool slot)
  runner.py          # run 120 Qs through /api/rag/adhoc, collect results
  scorecard.py       # JSON report → markdown scorecard
docs/superpowers/rag_eval/
  questions.yaml     # the 120-Q dataset, reviewable via git diff
  reports/           # per-iteration scorecards
  FINAL_REPORT.md    # written at loop exit
ops/scripts/
  rag_module_loop.py # the loop controller
```

**Corpus clustering (`corpus.py`).** Loads Naruto's 34 `kg_nodes` from prod Supabase. Clusters into 5–6 topic Kastens of 5–7 zettels by Jaccard similarity on normalized tags, falling back to title-bigram overlap for ties. Deterministic — no random seed — so the same corpus produces the same Kastens across iterations.

**Question dataset (`questions.yaml`).** 120 questions, 8 categories × 15 each:
1. `single_zettel_factual` — "What did zettel X say about Y?"
2. `multi_zettel_synthesis` — needs ≥2 zettels fused
3. `cross_source` — YouTube + GitHub + Substack on one topic
4. `temporal` — "latest," "most recent," "before X"
5. `out_of_corpus` — hallucination bait; correct answer is refusal
6. `adversarial` — leading questions, false premises, ambiguous referents
7. `numeric` — counts, dates, quantities
8. `negation` — "which zettel does NOT mention…"

Each question carries: `id`, `category`, `kasten_id`, `question`, `expected_zettel_ids` (for citation-accuracy scoring), `expected_behavior` (answer / refuse / partial).

**Rubric B (active).** Each answer scored on 4 axes, 0–5 each (total /20):
- **Faithfulness** — no hallucination, everything grounded in retrieved chunks
- **Relevance** — directly addresses the question
- **Completeness** — covers the key facts the corpus contains
- **Citation accuracy** — cites the correct zettel(s)

Scoring deltas (for loop advance decisions):
- Module "improved" iff mean total rose ≥0.5 AND no axis regressed >1.0.
- Module "plateaued" iff 2 consecutive iters show <0.2 mean-total gain.

**Rubric C (scaffold).** `rubric_c.py` exposes the same interface as `rubric_b.py` but raises `NotImplementedError("RAGAS integration pending ground-truth answers")` in its `score()` method. Config flag `RAG_EVAL_RUBRIC=b|c` selects which runs. This lets us swap later with no runner changes.

**Judge (`judge.py`).** The judging model is Claude Sonnet via Anthropic API directly — not the Gemini key pool. This keeps judge and generation orthogonal so a key exhaustion in one doesn't corrupt the other. Judge prompt includes: question, expected_zettel_ids, the retrieved chunks (as the pipeline delivered them), and the generated answer. Judge returns JSON with the 4 axis scores plus a 1-sentence rationale per axis.

**Runner (`runner.py`).** For each question:
1. Obtains a Supabase JWT for Naruto via `/auth/v1/token?grant_type=password`. Caches for 50 min.
2. Calls `POST /api/rag/adhoc` with Bearer JWT + the question. Captures the full response including `retrieved_chunks`, `answer`, `latency_ms`.
3. Calls the judge.
4. Appends to `report.json`: `{id, category, kasten_id, question, answer, chunks, judge_scores, latency_ms, error?}`.

Runs sequentially (not concurrently) — we need stable latency numbers and we don't want to hammer the judge API. Full run target: ~18 min for 120 Qs.

**Scorecard (`scorecard.py`).** Emits a markdown file per iteration to `docs/superpowers/rag_eval/reports/YYYY-MM-DD-iterNN-<module>.md` with: aggregate mean, per-axis mean, per-category breakdown, per-Kasten breakdown, top-10 worst answers with judge rationale, latency p50/p95.

**Phase C — Module refactor loop (subagent-driven).**

`ops/scripts/rag_module_loop.py` holds state in `.rag_loop_state.json`:
```json
{"current_module": "ingest", "iter_in_module": 0, "total_iters": 0, "baseline_mean": null, "last_mean": null}
```

Each iteration:
1. **Plan refactor** — subagent reads the last scorecard's worst-performing category for the current module, proposes the minimal change that targets that failure mode.
2. **Implement + ship** — subagent makes the code change, runs targeted unit tests, commits, pushes (triggers droplet deploy).
3. **Wait for deploy** — loop polls `/api/health` until the `git_sha` matches the pushed commit (max 5 min wait).
4. **Run eval** — `runner.py` full 120-Q pass.
5. **Score** — `scorecard.py` writes iteration report.
6. **Decide advance** — update state:
   - If global stop met (mean ≥17/20 OR total_iters ≥20): exit, write `FINAL_REPORT.md`.
   - Else if `iter_in_module >= 5` OR module plateaued: advance to next module, reset `iter_in_module`.
   - Else: `iter_in_module += 1`, loop continues.

**Module order** (by leverage; not all will be reached within the 20-iter cap):
1. `ingest/` (chunker + embedder)
2. `retrieval/` + `query/`
3. `rerank/`
4. `context/`
5. `generation/` + `critic/`
6. `memory/`, `orchestrator.py` (budget-permitting)

**Subagent model (per iteration):**
- **Refactor subagent** — owns module-specific code changes; reads last scorecard; constrained to one module at a time.
- **Verify subagent** — runs `runner.py` + `scorecard.py`; reports delta.
- **Review subagent** — diffs vs previous iteration; flags regressions on untouched categories.
- **Main loop controller** — orchestrates subagents, updates state, decides advance.

### Data flow

```
Naruto captures URL on zettelkasten.in
  → website/api/routes.py::summarize_endpoint
  → website/core/pipeline.py::summarize_url (produces raw_text + summary)
  → persist_summarized_result (nexus/persist.py)
  → _persist_supabase_node
    → rag_chunks_enabled gate
    → ingest_node_chunks (rag_pipeline/ingest/hook.py)   ← Phase A wires this
      → ZettelChunker.chunk
      → ChunkEmbedder (Gemini via pool)
      → upsert_chunks → kg_node_chunks table

Eval runner
  → POST /api/rag/adhoc with Bearer JWT
  → website/api/chat_routes.py::adhoc_endpoint
  → rag_pipeline/orchestrator.py::answer
    → query/  → retrieval/  → rerank/  → context/  → generation/  → critic/
  → returns {answer, retrieved_chunks, latency_ms}

Judge
  → Anthropic Claude Sonnet (separate from Gemini key pool)
  → 4-axis scores + rationale

Scorecard → markdown → git diff-reviewable
```

### Error handling

- **JWT refresh failure** — runner aborts iteration, marks report `inconclusive`, loop controller does not advance and does not count toward `iter_in_module`.
- **API 5xx during eval** — retry once with backoff, then mark that Q `error`. Per-Q errors are allowed up to 5% (6/120); beyond that the iteration is inconclusive.
- **Judge API failure** — same retry-once policy; on persistent failure, judge scores default to `null` and that Q is excluded from means (not counted as 0).
- **Deploy failure** — loop controller pauses and surfaces the failure to the user; no eval runs against a stale deploy.
- **Regression detection** — if any category drops >1.0 mean total vs baseline, the iteration is flagged red in the scorecard and the loop advances immediately (we don't compound regressions).

### Security

- Naruto's password lives in `docs/login_details.txt` (already in `.gitignore` — verify before Phase B).
- JWT is never logged. Runner config reads password from env var `NARUTO_SUPABASE_PASSWORD`, falls back to prompt in interactive mode.
- Anthropic judge API key lives in `ANTHROPIC_API_KEY` env var; never written to disk.
- Eval reports may contain zettel content — reports are committed to git, which is fine because the repo is private and this is Naruto's own data.

### Testing

- Unit tests for each new module in `tests/unit/rag/evaluation/`:
  - `test_corpus.py` — deterministic clustering
  - `test_rubric_b.py` — axis scoring math + thresholds
  - `test_rubric_c.py` — raises NotImplementedError
  - `test_judge.py` — mock Anthropic client, verify prompt shape
  - `test_runner.py` — mock `/api/rag/adhoc`, verify report schema
  - `test_scorecard.py` — JSON → markdown snapshot test
- No live integration test for the runner itself — we rely on the Phase A gate (real capture → real chunks) + the first iteration's eval being the effective integration test.

## Open questions

None at spec-approval time. Future work:
- Populating `expected_answers` per Q unlocks Rubric C (RAGAS).
- Multi-user eval: same harness, different corpus cluster, no code changes expected.

## Rollback

Every phase ships as its own commit on `master`:
- Phase A = 1 commit (refactor + flag flip + test migration).
- Phase B = 1–2 commits (harness skeleton, questions.yaml).
- Phase C = N commits, one per iteration.

Any commit can be reverted independently. The `rag_chunks_enabled` flag can be flipped to `false` via env override (`RAG_CHUNKS_ENABLED=false`) without a redeploy — droplet restart picks it up in <30s.
