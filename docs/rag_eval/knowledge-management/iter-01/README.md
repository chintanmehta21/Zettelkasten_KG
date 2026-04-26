# RAG iter-01 Eval — `knowledge-management` Kasten (Naruto)

**Status:** Pre-deploy. Question set + protocol pre-staged. Run executes after T26 deploy + T27 verify.

## What's already done

- **Kasten built** via Chrome MCP on 2026-04-26. 7 zettels, 4 source types (yt × 4, nl × 1, web × 1, gh × 1). Composition + member node IDs in [`queries.json`](./queries.json).
- **Question set designed** — 10 queries covering all 5 query classes the orchestrator routes (LOOKUP / VAGUE / MULTI_HOP / THEMATIC / STEP_BACK) plus 2 adversarial probes (negative-evidence + partial-coverage).
- **Pre-staged ground-truth** for each query; expected-citation set; expected `critic_verdict` for adversarial cases.

## Execution protocol (STRICT — Chrome MCP UI only)

This iter's eval differs from iter-06's `youtube/` eval in one critical way: **no direct `/api/rag/sessions` calls**. Every query goes through the production chat UI exactly the way an end-user would experience it. This catches:

- streaming UX (does the answer arrive incrementally; is there a visible spinner/typing-state?)
- citation rendering (do citation tiles link correctly? Are they reordered between SSE chunks and final state?)
- token-count surfacing (does the UI expose the per-tier model used + token totals?)
- the dormant T24 `query_class` flow being activated by T20 — we observe through the chat side-effects, not raw RPC calls.

For each query in `queries.json`:

1. Navigate to `/home/rag` (or whatever the chat route is — verify post-deploy).
2. Confirm the active sandbox is the `Knowledge Management & Personal Productivity` Kasten (not the global graph).
3. Type the query into the chat input; click Send.
4. Capture timestamps: `t_send`, `t_first_token`, `t_complete`.
5. Scrape the rendered DOM for: answer text, citation list (node_ids + ranks), critic verdict badge (if surfaced), model used (if surfaced).
6. Take a screenshot saved as `screenshots/q<N>.png`.
7. Append the result to `answers.json` (created during the run).

**No clipboard, no copy-paste shortcuts, no JS console workarounds** — if the UI doesn't expose something we need, that's a UX bug that gets logged in `manual_review.md` and folded into iter-02.

## Per-Q-A-page UX audit (parallel deliverable)

User directive (2026-04-26): every query in the strict-Chrome run MUST also produce a UI audit of the Kasten chat page (`/home/rag` or whatever route surfaces in T27). The eval is the *vehicle*; the UX audit is the *insurance* against shipping iter-02 with avoidable end-user friction. The bar is: **report ALL issues no matter how minor**.

For each query, capture in `kasten_qa_ux_audit.md`:

| dimension | what to log |
|---|---|
| chat-input affordance | placeholder copy, focus state, character limit visible? Enter-to-send vs explicit button, Shift+Enter newline behavior, paste handling |
| send-button feedback | disabled-while-streaming? loading icon? cancel/stop affordance? |
| streaming render | first-token latency, smoothness, cursor blink, typing indicator |
| citation tiles | rank order stable across SSE chunks? clickable? hover-tooltips? source-type badge correct? open-in-new-tab vs in-place? |
| critic-verdict surfacing | shown to user at all? color coding? hover-explain? |
| model/tier disclosure | does UI tell user which model handled the query (flash-lite vs flash vs pro)? token-count? cost? |
| empty-state / no-evidence | how does q9 (adversarial-negative) render? graceful refusal vs hallucinated answer vs error? |
| error-state | network drop, slow stream, model-error, 429 — does the UI handle gracefully? |
| keyboard accessibility | full keyboard nav? aria-live for streaming? reduced-motion respect? |
| mobile/responsive | resize the viewport mid-query (320×600, 768×1024, 1920×1080) and screenshot |
| copy-to-clipboard | answer copyable as Markdown? citations preserved? |
| follow-up affordance | can user ask a follow-up in same session? prior-turn citations still visible? |
| session memory | refresh page mid-conversation — is state preserved? URL shareable? |
| dark mode | if a theme toggle exists, both themes render the chat correctly? |
| visual nits | spacing, alignment, color contrast, font size jumps, broken icons, loading spinners that don't stop, layout shift |

Severity tags: 🚨 blocker / 🔴 high / 🟡 medium / 🟢 low / 💅 cosmetic.

The audit becomes a feeder list for iter-02's fix gate (same pattern as the iter-01 walkthrough fed UX-1..UX-8).

## Output artifact map (filled during/after the run)

| File | Phase | Producer | Consumer |
|---|---|---|---|
| `queries.json` | pre-stage ✓ | main agent | run + scoring |
| `qa_pairs.md` | pre-stage (next) | main agent | manual review |
| `kasten.json` | post-build | Chrome scrape | composition snapshot |
| `kg_snapshot.json` | pre-run | `/api/graph?view=my` snapshot | drift detection |
| `ingest.json` | pre-run | per-zettel summarizer trace (chunks + tokens + tier hits) | atomic-fact eval |
| `atomic_facts.json` | post-ingest | atomic-fact extractor (Gemini structured) | answer overlap eval |
| `answers.json` | run | Chrome scrape per query | scoring + manual review |
| `eval.json` | post-run | `eval_runner` (citation precision, recall, MRR, faithfulness via Ragas) | scores + delta |
| `ablation_eval.json` | post-run | feature-flag ablation: T8 / T9 / T15 / T20 OFF one at a time | improvement attribution |
| `scores.md` | post-run | scorer summary | reviewer |
| `kg_changes.md` | post-run | KG diff vs `kg_snapshot.json` | next-iter targeting |
| `kg_recommendations.json` | post-run | per-node "needs better tags / re-summarize" | iter-02 backlog |
| `diff.md` | post-run | iter-01 vs the existing AI/ML iter-06 baseline (cross-Kasten regression guard) | regression gate |
| `improvement_delta.json` | post-run | composite-score delta vs iter-06 baseline | T29 regression-gate (>5% drop = revert) |
| `manual_review.md` | post-run | qualitative notes per query (hallucination flags, UX friction) | iter-02 plan |
| `next_actions.md` | post-run | informed iter-02 task list | T31-T37 |
| `screenshots/q*.png` | run | Chrome MCP | manual review |

## Tricky-question rationale

| qid | class | what it stresses |
|---|---|---|
| q1 | lookup | baseline citation accuracy on a single GitHub source |
| q2 | lookup | T9 author-boost activation (named author) |
| q3 | lookup | T9 source-type boost (query says "YouTube") |
| q4 | multi_hop | T18 expand_subgraph + T20 planner; must combine 2 zettels |
| q5 | thematic | T15 EvidenceCompressor under budget pressure across 5+ zettels |
| q6 | step_back | abstract-from-concrete reasoning |
| q7 | vague | rewriter quality (3-word query → useful retrieval) |
| q8 | lookup_recency | T8 recency boost on a generic "latest" query |
| q9 | adversarial_negative | hallucination resistance — Kasten has neither Roam nor Logseq |
| q10 | adversarial_partial | partial-coverage detection — half-grounded query |

## Pass / fail gates (T29 regression)

- **Hard fail (auto-revert)**: composite score drops >5% vs iter-06 AI/ML baseline.
- **Hard fail (manual review)**: any adversarial query (q9 / q10) gets `critic_verdict='supported'` with hallucinated content.
- **Hard fail**: any UX-1..UX-8 bug we just fixed regresses on the live walkthrough.
- **Soft fail (folds to iter-02 plan)**: any single query scores below the iter-06 mean for its class.

## Readiness checklist (before kicking off the run)

- [ ] T26 deploy completes (master squash-merge → blue/green cutover → /api/health 200).
- [ ] T27 Chrome verify run on `/home`: Add Zettel works without JS workaround (UX-1 fixed live).
- [ ] T27 Chrome verify run on `/home/kastens`: Create Kasten chooser shows fresh data (UX-3 fixed live).
- [ ] T22 backfill cron + T13 backfill-on-deploy hook ran; `metadata_enriched_at IS NOT NULL` for ≥95% of `kg_node_chunks`.
- [ ] `kg_usage_edges_agg` MV refreshes successfully (dry-run verifies; T23 nightly cron lands).
- [ ] All 5 query classes present in `queries.json` (✓).
