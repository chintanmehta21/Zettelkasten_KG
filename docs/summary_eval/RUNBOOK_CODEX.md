# Codex Execution Runbook — Plans 6–9 Iteration Loops

This runbook is the **single source of truth** for running Plans 6–9 (YouTube, Reddit, GitHub, Newsletter iteration loops) end-to-end. Every command below has been dry-run-validated and the pipeline has been smoke-tested live against real Gemini. Your job: execute the commands in order and **focus on summarization quality**, not plumbing.

---

## 0. Pre-flight (do this once per session — 30 seconds)

```bash
# from the worktree root
cd C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.worktrees/eval-summary-engine-v2-scoring

# 1. Verify api_env is populated (3 Gemini keys, one per line)
head -1 api_env | head -c 20 && echo "..."   # expect "AIzaSy..." prefix

# 2. Unit tests must pass (fast sanity)
python -m pytest tests/unit tests/eval -q | tail -3
# expect: "327 passed in ~27s"

# 3. Dry-run any source/iter to confirm URLs + state
python ops/scripts/eval_loop.py --source youtube --iter 1 --dry-run
# expect JSON with status=dry_run, state=phase_a_required
```

If any of the above fails, **STOP** and read the error. Do not proceed until pre-flight is clean.

---

## 1. The iteration state machine (how the CLI works)

Each iter directory (`docs/summary_eval/<source>/iter-NN/`) has four states. The CLI auto-detects which one you're in and does the next thing.

| State | Detected when | What the CLI does |
|---|---|---|
| `PHASE_A_REQUIRED` | iter dir empty or only has partial artifacts | Runs summarizer + evaluator, writes `summary.json`, `eval.json`, `manual_review_prompt.md`, `source_text.md`, `atomic_facts.json`, `input.json` |
| `AWAITING_MANUAL_REVIEW` | `manual_review_prompt.md` exists, no `manual_review.md` | Prints the prompt path and exits 0. **You write** `manual_review.md` by hand |
| `PHASE_B_REQUIRED` | `manual_review.md` exists | Verifies blind-review stamp, writes `diff.md` + `next_actions.md`, commits |
| `ALREADY_COMMITTED` | `diff.md` exists | Noop |

**So the full two-phase loop for one iteration is:**

```bash
# Phase A — invoke LLM
python ops/scripts/eval_loop.py --source <s> --iter <n>

# Read manual_review_prompt.md, write manual_review.md (by hand)
# The review file MUST contain: eval_json_hash_at_review: "NOT_CONSULTED"
# and: estimated_composite: <float>

# Phase B — diff + commit (auto-detects state)
python ops/scripts/eval_loop.py --source <s> --iter <n>
```

---

## 2. The manual_review.md template (copy this exactly)

Every `manual_review.md` you write MUST start with these two lines (blind-review enforcement — Phase B rejects otherwise):

```markdown
# iter-NN manual review — <source> — <date>

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: <your_blind_score_0_to_100>

## Your observations
- <what the summary did well>
- <what the summary missed>
- <hallucinations, omissions, anti-patterns you saw>

## Per-criterion notes (optional)
- brief.thesis_capture: <your read>
- detailed.coverage: <your read>
```

**Rules:**
- Write the review **before** opening `eval.json`. If you peek, the stamp is a lie and Phase B catches the divergence.
- `estimated_composite` is your best-guess composite on the 0–100 scale **without looking at the evaluator output**.
- Phase B compares your estimate to the computed composite. Bands: ≤5pt = AGREEMENT, 5–10pt = MINOR_DISAGREEMENT, >10pt = MAJOR_DISAGREEMENT (triggers pessimistic next tuning target).

---

## 3. Per-loop schedule (Plans 6, 7, 8, 9 — same shape per source)

Per spec §4.1 the URL allocation per loop is:

| iter | URLs | Role |
|---|---|---|
| 1 | 1 (training URL #1) | Baseline measurement |
| 2 | 1 (same #1) | Tune (re-run after code edit) |
| 3 | 1 (same #1) | Tune (re-run after code edit) |
| 4 | 2 (#1, #2) | Probe — does tuning generalize? |
| 5 | 3 (#1, #2, #3) | Joint tune |
| 6 | all held-out (#4+) | **Held-out measurement** (no code edits between 5 and 6) |
| 7 | all held-out (#4+) with `--env prod-parity` | Prod-parity check |
| 8 | 3 training + failed held-out | Conditional tune if iter 7 regressed |
| 9 | all held-out | Conditional final measurement |

Iters 8 and 9 are **conditional** — skip them if iter 7 shows no regression vs iter 6.

---

## 4. The exact commands per source (copy-paste order)

Replace `<s>` with one of: `youtube`, `reddit`, `github`, `newsletter`.

### Training loops (iters 1–3) — same URL

```bash
# iter 1: baseline
python ops/scripts/eval_loop.py --source <s> --iter 1 --skip-determinism
# → write manual_review.md (template above)
python ops/scripts/eval_loop.py --source <s> --iter 1

# iter 2: after your first tuning edit
python ops/scripts/eval_loop.py --source <s> --iter 2
# → write manual_review.md
python ops/scripts/eval_loop.py --source <s> --iter 2

# iter 3: second tuning pass
python ops/scripts/eval_loop.py --source <s> --iter 3
# → write manual_review.md
python ops/scripts/eval_loop.py --source <s> --iter 3
```

The `--skip-determinism` flag is only needed for iter 1 (no prior iter to compare). From iter 2 onward the CLI automatically re-evaluates iter-(n-1) and halts if composite drifts >2pt (catches accidental evaluator changes).

### Probe / joint tune (iters 4–5)

```bash
python ops/scripts/eval_loop.py --source <s> --iter 4   # 2 URLs
# → one manual_review.md aggregating both URLs
python ops/scripts/eval_loop.py --source <s> --iter 4

python ops/scripts/eval_loop.py --source <s> --iter 5   # 3 URLs
# → one manual_review.md aggregating all three
python ops/scripts/eval_loop.py --source <s> --iter 5
```

The manual_review_prompt.md that Phase A emits contains **per-URL sections** — review each URL, then give one aggregate `estimated_composite`.

### Held-out measurement (iter 6) — NO CODE EDITS between iter 5 and iter 6

```bash
python ops/scripts/eval_loop.py --source <s> --iter 6
# Held-out layout: iter-06/held_out/<url_sha>/summary.json + eval.json
# + iter-06/aggregate.md
# → manual_review.md covering aggregate + any outliers
python ops/scripts/eval_loop.py --source <s> --iter 6
```

### Prod-parity (iter 7)

```bash
python ops/scripts/eval_loop.py --source <s> --iter 7 --env prod-parity
# → manual_review.md
python ops/scripts/eval_loop.py --source <s> --iter 7 --env prod-parity
```

Compare iter 7 composite to iter 6 composite. If delta < 3pt → **stop**, source is done. If delta ≥ 3pt → run iters 8 and 9.

### Conditional (iters 8–9)

Only if iter 7 regressed vs iter 6:

```bash
python ops/scripts/eval_loop.py --source <s> --iter 8
# → manual_review.md → Phase B
python ops/scripts/eval_loop.py --source <s> --iter 8

python ops/scripts/eval_loop.py --source <s> --iter 9
# → manual_review.md → Phase B
python ops/scripts/eval_loop.py --source <s> --iter 9
```

### Final scorecard

```bash
python ops/scripts/eval_loop.py --source <s> --report | tee docs/summary_eval/<s>/scorecard.json
```

---

## 5. What to do **between** iters (tuning loop)

After Phase B commits iter-N, before running Phase A of iter-(N+1):

1. Open `docs/summary_eval/<s>/iter-NN/next_actions.md` — it lists the lowest 3 rubric components and missed criteria.
2. Open the relevant summarizer prompt file:
   - YouTube: `website/features/summarization_engine/summarization/youtube/prompts.py`
   - Reddit: `website/features/summarization_engine/summarization/reddit/prompts.py`
   - GitHub: `website/features/summarization_engine/summarization/github/prompts.py`
   - Newsletter: `website/features/summarization_engine/summarization/newsletter/prompts.py`
3. Make **one targeted prompt edit** addressing the lowest-scoring component. Keep it minimal — big rewrites make diffs hard to attribute.
4. Record the targeted criterion + files touched by editing `docs/summary_eval/<s>/edit_ledger.json` (the CLI maintains this file; you can set `targeted_criterion` + `files` for the next iter's row to aid churn detection).
5. Run Phase A of the next iter.

**Churn guard:** if you edit the same file in 3 consecutive iters with <1.0 total composite movement, the CLI flags it as churning. At that point **stop editing that file** and write `docs/summary_eval/<s>/iter-NN/new_angle.md` describing a different approach.

---

## 6. Recovering from common failures

| Symptom | Cause | Fix |
|---|---|---|
| `rubric not found: ...yaml` | wrong `--source` spelling | Check `ls docs/summary_eval/_config/rubric_*.yaml` |
| `No Gemini API keys found` | `api_env` missing or empty | `head api_env` — should have `AIzaSy...` lines |
| `evaluator_drift` (exit 2) | Prior iter composite drifted >2pt on re-eval | Check if you edited `evaluator/prompts.py`; if yes bump `PROMPT_VERSION` in `evaluator/consolidated.py`; otherwise investigate determinism |
| `blind_review_violation` | `manual_review.md` missing `eval_json_hash_at_review: "NOT_CONSULTED"` line | Add the exact stamp line (with quotes) |
| `missing_manual_review` | Phase B ran before you wrote the review | Write `manual_review.md`, re-run the Phase B command |
| 429 from Gemini during Phase A | Free-tier Pro quota exhausted | Wait 60s, re-run (key pool auto-rotates; `GeminiKeyPool` switches to next key) |
| `awaiting_manual_review` | Normal Phase A completion signal | Write the review, re-run the same command |
| All URLs in iter-06 fail | Held-out URLs unreachable | Edit `docs/testing/links.txt` to swap broken URLs; delete iter-06 dir and re-run |

**Halt switch:** `touch docs/summary_eval/.halt` — the CLI exits with `status=halted` on next run. Remove it to resume.

---

## 7. Expected final artifacts per source

After iters 1–7 (or 1–9 if conditional), the source dir should contain:

```
docs/summary_eval/<source>/
├── iter-01/ (summary, eval, review, diff, next_actions, input, source_text, atomic_facts)
├── iter-02/
├── ...
├── iter-07/ (prod-parity)
├── [iter-08/, iter-09/ if conditional]
├── edit_ledger.json
├── scorecard.json
└── phase0.5-ingest/ (already populated from Plans 1–4)
```

Each iter dir also has `run.log` (stdout transcript) and `manual_review_prompt.md`.

---

## 8. When you're done (all 4 sources)

1. Verify every source has at minimum iters 1–7 committed: `for s in youtube reddit github newsletter; do ls docs/summary_eval/$s/ | grep iter-; done`
2. Run the full test suite: `python -m pytest tests/unit tests/eval -q`
3. Report back: composite progression per source, total Gemini tokens used (from `cost_ledger.json` if maintained), any anti-patterns still firing.

You're handing back to the main coordinator, who will drive Plans 10–17 (KG backfill, evaluator promotion, prod eval endpoint, academic validation, monitoring, UI, rollback, security).

---

## Appendix A — Files the main coordinator has already verified

- `ops/scripts/eval_loop.py` — CLI rewritten + dry-run wired
- `ops/scripts/lib/phases.py` — Phase A/B orchestration, determinism, replay
- `ops/scripts/lib/{artifacts,churn_ledger,git_helper,gemini_factory,state_detector,links_parser,cost_ledger,server_manager}.py` — support modules
- `docs/summary_eval/_config/rubric_{youtube,reddit,github,newsletter,universal}.yaml` — rubrics live
- `docs/testing/links.txt` — 5–6 URLs per source (enough for iters 1–9)
- `api_env` — 3 Gemini keys (gitignored)
- `tests/eval/test_eval_loop_lib.py` — 30 unit tests cover the state machine
- `tests/unit/` — 289 tests collect cleanly (`__init__.py` stubs added to resolve basename collisions)

Pipeline has been smoke-tested end-to-end on YouTube iter-01. Codex can start immediately.
