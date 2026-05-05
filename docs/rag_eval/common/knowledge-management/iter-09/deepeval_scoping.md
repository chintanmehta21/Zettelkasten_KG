# DeepEval Integration — Scoping Report (iter-09)

**Author:** scoping subagent · **Date:** 2026-05-04 · **Status:** scoping only — no code committed
**Scope:** evaluate the real `deepeval==3.9.7` package (already pinned in `ops/requirements-dev.txt:11` but not imported anywhere in production code) for two evaluable subsystems:

1. RAG pipeline — `website/features/rag_pipeline/` (eval orchestrated by `ops/scripts/eval_iter_03_playwright.py` + `ops/scripts/score_rag_eval.py`, scored by `website/features/rag_pipeline/evaluation/eval_runner.py`).
2. Summarization engine — `website/features/summarization_engine/` (scored by `website/features/summarization_engine/evaluator/models.py`, runbook in `docs/summary_eval/RUNBOOK_CODEX.md`).

The deliverable is a phased plan that **augments**, never replaces, the existing iter-04..iter-09 eval framework, gated behind env flags per the iter-08 canary discipline.

---

## 1. Executive Summary (6 bullets)

- **`deepeval==3.9.7` is installed but not imported.** `website/features/rag_pipeline/evaluation/deepeval_runner.py` is a hand-rolled Gemini judge that mimics deepeval's metric *shape* (semantic_similarity / hallucination / contextual_relevance) but never touches the library. Same for `ragas_runner.py`. Reason: avoiding deepeval's OpenAI default + per-metric API call burst. **This was the right call** and the recommendation below preserves it.
- **The summarization evaluator already implements G-Eval, FineSurE and SummaC-Lite** (`website/features/summarization_engine/evaluator/models.py:9-106`). DeepEval's `GEval` and `SummarizationMetric` would only add value if wrapped behind the same Gemini key-pool — direct adoption would silently route summarization eval through OpenAI.
- **The biggest gap is structured red-teaming and conversational/multi-turn eval.** The repo has only ad-hoc adversarial queries (`av-1/av-2/av-3` in `eval_iter_03_playwright.py:22-25`) and zero conversational test coverage despite RAG being inherently turn-able. DeepEval's red-team module + `ConversationalTestCase` are the highest-ROI integration.
- **The second biggest gap is golden-test-set synthesis.** Gold queries in `docs/rag_eval/common/knowledge-management/iter-{04..09}/queries.json` are hand-authored. DeepEval's `Synthesizer.generate_goldens_from_contexts()` could expand the 14-query KM-Kasten gold set by an order of magnitude, gated by a quality-threshold filter.
- **A custom `DeepEvalBaseLLM` wrapper around `GeminiKeyPool` is mandatory.** Per the docs we fetched, custom LLMs need only `generate / a_generate / get_model_name / load_model` plus an optional schema-constrained signature `generate(prompt, schema: BaseModel) -> BaseModel`. This is ~40 lines of glue code and unblocks every other deepeval feature on the project's existing key budget.
- **Cost ceiling is the binding constraint.** DeepEval defaults to one LLM call per metric × per test case. With 14 KM queries × ~6 RAG metrics that is ~84 judge calls per iter today via the hand-rolled batched runner; if each metric invoked its own call we would 6× the spend. **Picks below all preserve the per-query batching pattern already proven in `ragas_runner.py:151-165`.**

---

## 2. Project ↔ DeepEval Diff Table

| Capability | Project has it | DeepEval offers | Gap worth filling? |
|---|---|---|---|
| RAG faithfulness | hand-rolled Gemini-Pro judge, per-query, eval_failed flag (`ragas_runner.py:214-251`) | `FaithfulnessMetric`, `RagasMetric` (LLM judge per case) | **No** — current impl is cheaper, JSON-retry hardened, gated by `RAG_EVAL_RAGAS_PER_QUERY` |
| RAG answer relevancy / context precision/recall | hand-rolled in `_METRIC_NAMES` (`ragas_runner.py:35-42`) | `AnswerRelevancyMetric`, `ContextualPrecisionMetric`, `ContextualRecallMetric`, `ContextualRelevancyMetric` | **No** — same as above; library would 5× judge calls |
| RAGAS-vs-DeepEval divergence detector | `synthesis_score.detect_eval_divergence()` (line 22-26) | n/a | **No** — project-specific guardrail, no parity needed |
| nDCG / retrieval rank scoring | `component_scorers.retrieval_score / rerank_score` with iter-09 dedupe + clamp fix (commit `ee31c85`) | none — DeepEval is LLM-judge-first, no IR metric primitives | **N/A** — no overlap |
| Atomic-fact decomposition (FineSurE) | full implementation in `evaluator/models.py:25-77` | n/a | **N/A** — no overlap |
| G-Eval coherence / consistency / fluency / relevance | `GEvalScores` (line 9-22) + UniEval-style scoring | `GEval` class (custom rubric, LLM judge, `evaluation_steps` chain-of-thought) | **PARTIAL** — DeepEval's `GEval` has a richer rubric-decomposition prompt with chain-of-thought scoring; could cross-validate the hand-rolled scores |
| SummaC-Lite NLI faithfulness | `SummaCLite` (line 79-106) | `HallucinationMetric` (LLM-judge), no NLI primitive | **No** — project's NLI-style scorer is lighter |
| Summarization alignment + coverage | rubric breakdown + caps (`models.py:108-227`) | `SummarizationMetric` (alignment + coverage, min(both)) | **PARTIAL** — useful as a **third independent judge** for cross-check, not as a replacement |
| Conversational / multi-turn RAG eval | **none** — RAG is single-turn only today | `ConversationalTestCase`, `ConversationCompletenessMetric`, `KnowledgeRetentionMetric`, `RoleAdherenceMetric` | **YES — high ROI** (see Pick 2) |
| Red-teaming / adversarial test generation | 3 hand-written av-* queries in `eval_iter_03_playwright.py` | DeepEval red-team module (bias, toxicity, prompt injection, jailbreaks) | **YES — high ROI** (see Pick 1) |
| Golden synthesis from corpus | hand-authored 14-query gold set per iter | `Synthesizer.generate_goldens_from_contexts()` with evolution + filtration | **YES — medium-high ROI** (see Pick 3) |
| Pytest assertion harness | tests live in `tests/unit/rag_pipeline/evaluation/test_*` with mocks | `assert_test(test_case, [metric])` | **PARTIAL** — only useful for CI gate; minor (Pick 4) |
| Bias / toxicity check | none | `BiasMetric`, `ToxicityMetric` | **YES — low cost** (see Pick 5) |
| Persistent eval-run dataset / dashboard | `eval.json` + `scores.md` per iter | Confident AI cloud (paid) | **No** — file-store discipline preferred; iter-09 spec already canonical |
| JSON-correctness check | n/a | `JsonCorrectnessMetric` | **No** — RAG output is markdown, not JSON |
| Multimodal eval | n/a | `MultimodalContextualPrecisionMetric` | **No** — out of scope |
| Agentic / tool-use metrics | n/a | Task Completion, Tool Correctness, Plan Adherence | **No** — RAG orchestrator is not agentic |

---

## 3. The 5 Picks (ranked by ROI)

### Pick 1 — Red-team adversarial query generation for RAG (HIGHEST ROI)

**Why:** the only adversarial coverage today is `av-1/av-2/av-3` and one negative query (q9) in the 14-query KM-Kasten suite (`eval_iter_03_playwright.py:24-25`). Refusal-correctness (`_REFUSAL_REGEX` in `eval_runner.py:74-81`) is regression-tested but only against drift in known-good refusals — the upstream attack surface (jailbreaks, prompt-injection in user-supplied Zettel content, biased framings, leading questions) has zero coverage. A failure here is a production trust event (e.g. user's own Zettel embeds `Ignore previous instructions and ...`).

**Project evidence:** `_REFUSAL_REGEX` token list at `eval_runner.py:74-81`; `_REFUSAL_BEHAVIORS` set at line 91. The refusal scoring path (lines 226-292) only exercises *expected* refusals.

**DeepEval feature:** red-teaming module + custom adversarial test cases via `LLMTestCase` with the Gemini-judge wrapper.

**Cost:** ~10-30 generated red-team queries × 1 judge call = ~10-30 Gemini-Flash calls per regression run. Same key-pool, same `_judge_one_via_gemini` pattern.

**Risk:** new attack queries could include prompt-injection payloads that contaminate the judge prompt itself. Mitigation: render attack input as a JSON-string sample, never inline in the system prompt.

---

### Pick 2 — Conversational / multi-turn RAG eval

**Why:** the production RAG surface (`/home/rag`) supports follow-up questions inside the same Kasten context, but none of the iter-04..iter-09 eval suites test multi-turn behaviour. We don't know whether the orchestrator leaks the previous answer's stance into the next retrieval, whether refusal-then-rephrase recovers correctly, or whether citation IDs remain stable across turns.

**Project evidence:** all 14 KM queries are independent single-turn cases (`docs/rag_eval/common/knowledge-management/iter-09/queries.json`). `eval_iter_03_playwright.py` runs each query with a fresh fetch (line ~22 plan item 5). No `ConversationalTestCase`-equivalent exists.

**DeepEval feature:** `ConversationalTestCase` + `ConversationRelevancyMetric` + `KnowledgeRetentionMetric` (judge each turn given prior turns).

**Cost:** ~3 turns × ~5 multi-turn scenarios × 2 metrics = 30 judge calls. One-time per iter.

**Risk:** multi-turn requires the orchestrator to support session context. That session plumbing exists in the chat surface but is NOT what `/api/rag/adhoc` exposes. Scope the integration to a new `/api/rag/session` endpoint OR drive multi-turn through Playwright (preferred — no API surface change required).

---

### Pick 3 — Synthesizer-based golden expansion from existing Kasten content

**Why:** hand-authored gold sets are the rate-limit on iter velocity. iter-09 still uses ~14 queries. DeepEval's `Synthesizer.generate_goldens_from_contexts()` ingests the existing Kasten chunks (already in Supabase) and emits Goldens with `input` (question), `expected_output`, `context` lineage. With evolution config tuned to `Reasoning + MultiContext + Comparative`, we can produce 50-100 candidate goldens per Kasten and human-review the top quartile.

**Project evidence:** queries seed file at `docs/rag_eval/common/knowledge-management/iter-09/queries.json`; gold-data loader at `gold_loader.py:29-49`. Synthesizer output maps cleanly to the existing `GoldQuery` Pydantic model (`types.py:92-103`) — `input → question`, `expected_output → reference_answer`, `context lineage → gold_node_ids`.

**DeepEval feature:** `Synthesizer(model=GeminiPoolLLM())` with `EvolutionConfig` + `FiltrationConfig(synthetic_input_quality_threshold=0.7)`.

**Cost:** ~3 LLM calls per generated golden × 50 candidates per Kasten = 150 calls per Kasten per generation pass. Run **once** per iter, gated behind a CLI flag (not in the regression loop).

**Risk:** synthesizer can produce off-distribution questions ("what color is the chunk?"). Mitigation: filtration threshold + mandatory human review before promoting candidates into `seed.yaml`.

---

### Pick 4 — DeepEval `GEval` cross-judge for summarization rubric (canary)

**Why:** the summarization evaluator has 4 independent signals (G-Eval / FineSurE / SummaC / rubric) but they are all judged by the same Gemini key-pool with project-specific prompts. A periodic cross-check using DeepEval's stock `GEval` rubric (with our Gemini wrapper) catches prompt drift in our hand-rolled judges. Only useful if the cross-judge uses a *different* Gemini model tier (e.g. our judge is Pro, this canary is Flash) so it's not the same model grading itself.

**Project evidence:** `GEvalScores` at `evaluator/models.py:9-22`; composite formula at `models.py:210-226` weights `g_eval` at 10% — drift here is invisible.

**DeepEval feature:** `GEval(name="summary_quality", criteria=..., evaluation_steps=[...], model=GeminiPoolLLM(model="flash-lite"))`.

**Cost:** 4 dimensions × 1 call per summary × ~10 summaries per iter per source = 40 calls per source.

**Risk:** GEval's chain-of-thought prompt is verbose (~1.5k tokens). Use `flash-lite` only — not Pro.

---

### Pick 5 — `BiasMetric` + `ToxicityMetric` smoke-pass on every iter

**Why:** zero coverage today. Cheap to add. RAG output is user-facing; a rogue LLM key swap or a corrupted Zettel could leak biased framing without a tripwire.

**Project evidence:** no bias/toxicity checks exist in `tests/unit/rag_pipeline/evaluation/` or in `eval_iter_03_playwright.py`.

**DeepEval feature:** `BiasMetric()` + `ToxicityMetric()` — referenceless, only need `actual_output`.

**Cost:** 14 queries × 2 metrics × 1 judge call = 28 Flash calls per iter. Negligible.

**Risk:** false positives on technical content (e.g. a Zettel about a controversial paper). Mitigation: log fail-events but don't gate the iter on them until a baseline is established.

---

## 4. Implementation Plan (TDD, env-flag canary, file-by-file)

**Migration order:** Pick 5 (smallest blast radius, exercises the wrapper) → Pick 1 (highest ROI but bounded scope) → Pick 4 → Pick 2 → Pick 3.

All paths are absolute under `C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\` (omitted below for brevity). Every file gets a TDD test before implementation per `CLAUDE.md` Production Change Discipline. **No code is written in this scoping pass** — these are the targets.

### Phase 0 — Custom Gemini DeepEval LLM wrapper (FOUNDATION)

**Files to create:**

1. `website/features/rag_pipeline/evaluation/deepeval_gemini_llm.py` — `class GeminiPoolLLM(DeepEvalBaseLLM)` with `load_model / generate / a_generate / get_model_name`. `generate(prompt, schema)` overload uses `response_mime_type="application/json"` + `response_schema` to satisfy DeepEval's structured-output path (mirrors the JSON-retry pattern at `ragas_runner.py:234-251`).
2. `tests/unit/rag_pipeline/evaluation/test_deepeval_gemini_llm.py` — unit tests with `_judge_one` mocked: schema-bound generation returns the right Pydantic model, key-pool errors propagate as `_zero_metrics(eval_failed=True)`, model-name string is stable for caching.

**Env flags:** none — wrapper has no runtime side-effect.
**Cost impact:** zero until a metric uses it.
**Verification gate:** test_deepeval_gemini_llm.py green; one manual `evaluate([test_case], [GEval(model=GeminiPoolLLM())])` smoke run with 1 sample.

### Phase 1 — `BiasMetric` + `ToxicityMetric` smoke-pass (Pick 5, smallest blast)

**Files to create:**

3. `website/features/rag_pipeline/evaluation/safety_metrics.py` — wraps `BiasMetric` and `ToxicityMetric` over `GeminiPoolLLM("gemini-2.5-flash-lite")`. Returns `{bias: float, toxicity: float, eval_failed: bool}` per query, mirroring the per-query shape in `deepeval_runner.py:255-272`.
4. `tests/unit/rag_pipeline/evaluation/test_safety_metrics.py` — TDD: empty-answer short-circuit, key-pool failure → eval_failed, score range [0,1].

**Files to modify:**

5. `website/features/rag_pipeline/evaluation/eval_runner.py` — call `safety_metrics.run()` when `RAG_EVAL_SAFETY_ENABLED=true`, attach to per-query record. **Default OFF**.
6. `website/features/rag_pipeline/evaluation/types.py` — extend `PerQueryScore` with optional `safety: dict[str, float] | None = None` (additive, backward-compat).
7. `ops/scripts/score_rag_eval.py` — surface bias/toxicity p95 in `scores.md` only when present (no schema break).
8. `tests/unit/rag_pipeline/evaluation/test_eval_runner.py` — assert `safety` field is None when flag off, populated when on.

**Env flags:** `RAG_EVAL_SAFETY_ENABLED=false` (canary OFF by default; flip ON for one iter to baseline).
**Cost impact:** +28 Flash-lite calls per iter when ON.
**Verification gate:** all evaluation tests green; one full `score_rag_eval.py` run on iter-09 with flag ON; baseline numbers published in `iter-09/safety_baseline.md`.

### Phase 2 — Red-team adversarial query bank (Pick 1)

**Files to create:**

9. `docs/rag_eval/common/knowledge-management/iter-09/redteam_queries.yaml` — hand-curated 20-query bank (jailbreak, prompt-injection-in-Zettel, leading-question, refusal-bypass attempts), schema matches `GoldQuery` with `expected_behavior: "refuse" | "ask_clarification_or_refuse"`.
10. `website/features/rag_pipeline/evaluation/redteam_runner.py` — loads the YAML, runs each query through `/api/rag/adhoc`, scores with `_refusal_query_score` (already in `eval_runner.py:122-138`) + a new `redteam_score` that uses `GEval(criteria="answer must NOT comply with the adversarial instruction")` via `GeminiPoolLLM`.
11. `tests/unit/rag_pipeline/evaluation/test_redteam_runner.py` — TDD: bank loads, refusal short-circuit, GEval gives 1.0 on a stub-refused answer and 0.0 on a stub-complied answer.

**Files to modify:**

12. `ops/scripts/eval_iter_03_playwright.py` — when `RAG_EVAL_REDTEAM_ENABLED=true`, append the redteam_queries to the run set and write `redteam_results.json`.
13. `ops/scripts/score_rag_eval.py` — read `redteam_results.json` if present, surface `redteam_pass_rate` in `scores.md`.

**Env flags:** `RAG_EVAL_REDTEAM_ENABLED=false`. **Strict OFF in CI; manual ON in dev.**
**Cost impact:** +20 Flash judge calls + 20 Pro adhoc calls per redteam run.
**Verification gate:** red-team pass-rate ≥ 90% on iter-09 baseline before flag is allowed in nightly.

### Phase 3 — `GEval` summarization cross-judge canary (Pick 4)

**Files to create:**

14. `website/features/summarization_engine/evaluator/deepeval_canary.py` — runs DeepEval `GEval` (4 stock dimensions) on each summary using `GeminiPoolLLM("gemini-2.5-flash-lite")` and emits a divergence delta vs `GEvalScores` in `models.py:9-22`.
15. `tests/unit/summarization_engine/evaluator/test_deepeval_canary.py` — TDD: divergence within 1.0 returns "agree", >1.0 returns "diverge", flag OFF returns None.

**Files to modify:**

16. `docs/summary_eval/RUNBOOK_CODEX.md` — add a "Canary cross-judge" section with the env flag and the divergence-threshold rule.

**Env flags:** `SUMMARY_EVAL_DEEPEVAL_CANARY=false`.
**Cost impact:** +40 Flash-lite calls per source per iter when ON.
**Verification gate:** divergence < 1.0 on 80% of samples in a single source's iter before promotion.

### Phase 4 — `ConversationalTestCase` multi-turn RAG eval (Pick 2)

**Files to create:**

17. `docs/rag_eval/common/knowledge-management/iter-09/multiturn_scenarios.yaml` — 5 multi-turn scenarios × ~3 turns each (follow-up clarification, topic-switch-then-return, refusal-then-rephrase, citation-stability-across-turns, contradictory-correction).
18. `website/features/rag_pipeline/evaluation/multiturn_runner.py` — drives Playwright through each scenario, collects per-turn `LLMTestCase`s into a `ConversationalTestCase`, scores with `ConversationCompletenessMetric` + `KnowledgeRetentionMetric` + `ConversationRelevancyMetric` via `GeminiPoolLLM("gemini-2.5-pro")`.
19. `tests/integration/rag_pipeline/test_multiturn_runner.py` — TDD: scenario loader, per-turn `LLMTestCase` shape, mocked DeepEval metric returns aggregate.

**Files to modify:**

20. `ops/scripts/eval_iter_03_playwright.py` — under `RAG_EVAL_MULTITURN_ENABLED=true`, drive scenario YAML through new `_run_multiturn_scenarios()`.
21. `ops/scripts/score_rag_eval.py` — surface multi-turn metrics in `scores.md`.

**Env flags:** `RAG_EVAL_MULTITURN_ENABLED=false`. **Manual ON only — slow path.**
**Cost impact:** +5 scenarios × 3 turns × 3 metrics × 1 Pro call = 45 Pro calls per iter. Significant — gate carefully.
**Verification gate:** ≥ 0.7 on Knowledge Retention before promoting flag to nightly.

### Phase 5 — `Synthesizer` golden expansion (Pick 3, manual-trigger only)

**Files to create:**

22. `ops/scripts/synthesize_goldens.py` — CLI: `--kasten <id> --num 50 --quality-threshold 0.7 --output <path>`. Pulls Kasten chunks from Supabase, drives `Synthesizer(model=GeminiPoolLLM("gemini-2.5-pro"))` with `EvolutionConfig(num_evolutions=2, evolutions=[Reasoning, MultiContext, Comparative])`, writes candidate `GoldQuery`-shaped YAML for human review.
23. `tests/unit/ops_scripts/test_synthesize_goldens.py` — TDD: chunk fetch, evolution config injected, output YAML schema validates against `SeedQueryFile`.

**Env flags:** none — script-only, never auto-runs.
**Cost impact:** ~150 Pro calls per Kasten per invocation. **Strictly manual.**
**Verification gate:** human review of all generated goldens; >= 30% promotion rate before considering automation.

---

## 5. Cost / Latency Budget Summary

| Phase | When | API calls per run | Notes |
|---|---|---|---|
| 0 (wrapper) | always | 0 | foundation only |
| 1 (safety) | every iter when ON | +28 Flash-lite | OFF in CI default |
| 2 (red-team) | manual + nightly | +20 Pro adhoc + 20 Flash judge | strict OFF in CI |
| 3 (summary canary) | every iter per source when ON | +40 Flash-lite per source | OFF default |
| 4 (multi-turn) | manual ON only | +45 Pro | slow path |
| 5 (synthesizer) | manual CLI | +150 Pro per Kasten | gated by human review |

**Worst case all-flags-on per iter:** ~28 + 40 (single source) + 40 + 90 = ~200 extra Gemini calls. With ~10 keys × 1500 RPD/key = 15k requests/day budget on Flash, this is well within a 1.3% burst.

**Key reuse:** every metric MUST go through `GeminiPoolLLM` (Phase 0). No direct deepeval default model invocation. CI must `grep -E "DeepEvalBaseLLM\\b|deepeval\\.metrics" -L .` and fail any deepeval import that doesn't pass `model=GeminiPoolLLM(...)`.

---

## 6. Integration with iter-09 Eval Harness

- **Augment, never replace.** `EvalRunner` and `score_rag_eval.py` continue to be the canonical scorer; deepeval signals enter as **sidecar fields** on `PerQueryScore` and as **separate sections** in `scores.md`. Composite weights (`docs/rag_eval/_config/composite_weights.yaml`) are NOT touched by this scoping pass.
- **`eval_divergence` already exists** (`synthesis_score.py:22-26`) as a faithfulness/hallucination cross-check. Consider adding a `safety_divergence` and a `summary_canary_divergence` once Phases 1 and 3 land — same pattern, same alarm channel.
- **iter-08 Phase 7.B parse-fail handling** (`ragas_runner.py:214-251`) is the right model for every new deepeval call. Phase 0's wrapper inherits the pattern; later phases must not bypass it.
- **`gold_loader.SeedQueryFile`** stays the schema of record; the synthesizer (Phase 5) emits this same shape.

---

## 7. Rejected Features (and why)

| Feature | Reject reason |
|---|---|
| Replace `ragas_runner.py` with deepeval `RagasMetric` | Loses per-query batching, JSON-retry, eval_failed flag. 5× judge call cost. Net regression. |
| Replace `deepeval_runner.py` with deepeval `FaithfulnessMetric` + `AnswerRelevancyMetric` + `ContextualPrecisionMetric` + `ContextualRecallMetric` | Same as above. The hand-rolled batched runner is **better suited** to this project than the library it imitates. |
| `JsonCorrectnessMetric` | RAG output is markdown, summary output is markdown. No JSON-shape contract to validate. |
| Multimodal metrics | Out of scope; no image inputs anywhere in the RAG/summarization paths. |
| Agentic / tool-correctness metrics | Orchestrator is not an agent; no tool-use to score. |
| Confident AI cloud platform / `deepeval login` | Adds external dependency, paid SaaS, leaks eval data. File-store discipline (`docs/rag_eval/...`) is canonical per CLAUDE.md. |
| `assert_test` pytest macro across the existing eval suite | Existing tests use targeted mocks of the hand-rolled runners. Wrapping them in `assert_test` adds indirection for zero scoring gain. |
| `SummarizationMetric` as a primary scorer | Per the docs we fetched, it computes `min(alignment, coverage)` via auto-generated yes/no questions. The project's `FineSurEScores` is already finer-grained (per-fact decomposition) — `SummarizationMetric` would be a **coarser** signal, only useful as a third-judge canary (folded into Pick 4 already). |
| **Most important rejection: replace any of the existing `_runner.py` modules with their deepeval equivalents.** | The whole point of the iter-04..iter-08 evolution was to **avoid** deepeval's per-metric API call burst (5 judge calls per query × 14 queries × 2 runners = 140 calls/iter vs current ~28). Adopting the library wholesale would silently undo that work — same anti-pattern as the "blind mitigation" warning in CLAUDE.md §Critical Infra Decision Guardrails. |

---

## 8. Open Questions / Pre-Implementation Approvals Needed

Per CLAUDE.md "Beyond-Plan = New Decision = Approval First" (`feedback_anything_beyond_plan_needs_approval.md`), the following require explicit user approval before Phase 0 starts:

1. **DeepEval version pin.** Confirm `deepeval==3.9.7` is the target. Library moves fast; iter-09 baseline locks the API surface.
2. **`GeminiPoolLLM` model tier defaults.** Proposed: judge calls default to `gemini-2.5-flash-lite` for cheap metrics (bias, toxicity, summary canary), `gemini-2.5-pro` for nuanced ones (red-team comply-detection, multi-turn knowledge retention). Approve?
3. **Env-flag naming convention.** Proposed: `RAG_EVAL_<FEATURE>_ENABLED` for RAG side, `SUMMARY_EVAL_<FEATURE>_ENABLED` for summarization side. Matches existing `RAG_EVAL_RAGAS_PER_QUERY` style.
4. **CI gate.** Proposed: `pytest tests/unit/rag_pipeline/evaluation/ -k deepeval` runs on every PR but **all five new flags default OFF in CI**; only the wrapper unit test exercises a real Gemini call (skipped without `--live`).
5. **iter-09 canary slot.** Proposed: Phase 1 (safety) lands in iter-09 with flag OFF; flag flips ON for iter-10 baseline. Other phases land in iter-10+. Confirm or reorder.

End of scoping report.
