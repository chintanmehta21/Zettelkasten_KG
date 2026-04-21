# Summarization Engine Scoring Optimization — Design

**Status:** Approved for implementation planning
**Date:** 2026-04-21
**Feature branch:** `eval/summary-engine-v2-scoring`
**PR strategy:** One PR per major source (YouTube → Reddit → GitHub → Newsletter), plus a final polish PR bundling the 6 unscoped sources
**Primary author workflow:** Codex Desktop, iteration-driven
**Reference rubric:** `docs/research/summarization-criteria.md`
**Target engine:** `website/features/summarization_engine/` (v2), NOT the legacy `telegram_bot/` pipeline

---

## 1. Goal & scope

Raise the v2 summarization engine's per-source output quality to:

- **Composite ≥ 92/100** (source-specific 100-point rubric, from `docs/research/summarization-criteria.md`) on training URLs
- **RAGAS faithfulness ≥ 0.95** on held-out URLs
- **Held-out mean ≥ 88 composite** across the full held-out set for each source
- **Prod-parity delta ≤ 5 points** between local-dev and `SUMMARIZE_ENV=prod-parity` runs

Across **4 documented sources** with full 7-loop optimization cycles (YouTube → Reddit → GitHub → Newsletter), followed by **2–3 polish loops per source** for the 6 sources without explicit rubrics in the research doc (HackerNews, LinkedIn, Arxiv, Podcast, Twitter, Web).

**Expected runtime:** 2–4 wall-clock days of iteration.
**Expected Gemini cost:** ~285–305 Pro calls + ~200–260 Flash calls on free-tier keys; ~$0.50 worst-case on the one billing key (during loop 7 prod-parity and quota-exhaustion spillover).

**Explicit non-goals:**
- Migrating the `telegram_bot/` legacy pipeline to the v2 engine (deferred; recorded in `final_scorecard.md` as a follow-up).
- Touching the Supabase KG schema (`kg_nodes.detailed_summary` on-wire shape is preserved).
- Adding reference-based metrics (ROUGE, BLEU, BERTScore) — we have no gold summaries.
- Training or fine-tuning any model.
- Any edit to `telegram_bot/**` is forbidden during this program. The CLI's "reserved file list" guard explicitly blocks changes there. If a legitimate bugfix surfaces in the legacy pipeline mid-program, it lands on a separate branch and a separate PR, outside this program's feature branch.

**`SUMMARIZE_ENV=prod-parity` semantics (used in loop 7 of each source):**
- Bypasses all three caches (`--no-cache` is implied).
- Merges `ops/config.prod-overrides.yaml` (if present) on top of `config.yaml` — this file is where any production-specific overrides live (e.g., a narrower Piped/Invidious pool that we've verified works in prod).
- Enables per-URL correlation-id logging (`logging.per_url_correlation_id: true`).
- Uses the production Gemini model-chain ordering (identical today, but lets us swap models in future without code changes).
- Does NOT hit the real prod droplet or prod Supabase — still entirely local. The goal is "dev environment running with prod-equivalent config", not deploying.

---

## 2. Architecture overview

Five moving parts:

1. **Engine refactor** (`website/features/summarization_engine/`). Replace the thin-wrapper pattern in `summarization/_wrappers.py` with real per-source summarizer classes that each own their CoD prompt, self-check prompt, and structured-extract schema. Route output caps through `config.yaml` via a factory (`build_summary_result_model(cfg)`). Add a three-layer content-hashed cache (ingest / summary / atomic-facts) under `docs/summary_eval/_cache/`.
2. **Evaluator module** — new package `website/features/summarization_engine/evaluator/`. One consolidated Gemini-Pro call (temperature 0.0, JSON response) returns G-Eval 4-dimension scores, FineSurE 3-dimension scores, SummaC-lite per-sentence NLI verdicts, and the full 100-point source-specific rubric breakdown. RAGAS `Faithfulness` hooked in conditionally when rubric-faithfulness < 0.9. RAGAS `AspectCritic` runs the rubric a second time as an independent LLM-judge; disagreements > 10 points flagged for review.
3. **Iteration CLI** — new `ops/scripts/eval_loop.py`. Single entrypoint Codex drives: reads URL from `docs/testing/links.txt`, manages FastAPI server lifecycle, hits `/api/v2/summarize`, runs evaluator, writes 6-file artifact set to `docs/summary_eval/<source>/iter-<N>/`, emits next-iteration hints.
4. **Ingest unblocker (Phase 0.5)** — per-source, one-time, before iteration 1 for each source. YouTube gets the heaviest work: a 5-tier free-only fallback chain that handles datacenter-IP transcript blocks. Reddit, GitHub, Newsletter get smaller targeted fixes.
5. **Key-role aware pool** — extension to existing `GeminiKeyPool`. Tag keys with `role=free` or `role=billing` in `api_env`. Pool prefers free keys, auto-falls back to billing when all free exhausted (preserves existing behavior, now role-aware). Evaluator and summarizer tiers tuned so Pro is concentrated in high-reasoning phases only.

---

## 3. Evaluator module design

### 3.1 Module structure

```
website/features/summarization_engine/evaluator/
├── __init__.py                # Public API: evaluate(summary, ingest, source_type) -> EvalResult
├── models.py                  # Pydantic: RubricCriterion, CriterionScore, EvalResult, composite_score()
├── rubric_loader.py           # Loads + validates docs/summary_eval/_config/rubric_*.yaml
├── consolidated.py            # Single Gemini-Pro structured-JSON call (G-Eval + FineSurE + rubric + SummaC-lite)
├── ragas_bridge.py            # RAGAS Faithfulness + AspectCritic wrapped around TieredGeminiClient
├── atomic_facts.py            # Source-claim extraction + cache (Flash tier, once per URL)
├── manual_review.py           # Independent LLM reviewer (second-opinion prose markdown)
├── next_actions.py            # Synthesizes ranked edit proposals
├── prompts.py                 # Evaluator prompt templates (versioned; hash recorded in artifacts)
└── cache.py                   # Content-hashed on-disk cache shim
```

### 3.2 Consolidated evaluator call — output shape

Single Gemini-Pro request with `response_mime_type=application/json`, `temperature=0.0`. Response schema:

```json
{
  "g_eval": {
    "coherence": 0.0-5.0,
    "consistency": 0.0-5.0,
    "fluency": 0.0-5.0,
    "relevance": 0.0-5.0,
    "reasoning": "1-2 sentence justification per dimension, concatenated"
  },
  "finesure": {
    "faithfulness": {"score": 0.0-1.0, "unsupported_claims": [{"claim": "...", "span": "..."}]},
    "completeness": {"score": 0.0-1.0, "missing_keyfacts": [{"fact": "...", "importance": 1-5}]},
    "conciseness":  {"score": 0.0-1.0, "non_keyfact_sentences": ["..."]}
  },
  "summac_lite": {
    "score": 0.0-1.0,
    "contradicted_sentences": [{"sentence": "...", "contradiction_reason": "..."}],
    "neutral_sentences": [{"sentence": "...", "support_gap": "..."}]
  },
  "rubric": {
    "brief_summary":    {"score_of_25": 0-25, "criteria_fired": [...], "criteria_missed": [...]},
    "detailed_summary": {"score_of_45": 0-45, "covered_units": [...], "missed_units": [...]},
    "tags":             {"score_of_15": 0-15, "generic_tags": [...], "specificity_issues": [...]},
    "label":            {"score_of_15": 0-15, "issues": [...]},
    "caps_applied":     {"hallucination_cap": null|60, "omission_cap": null|75, "generic_cap": null|90},
    "anti_patterns_triggered": [{"id": "production_ready_claim_no_evidence", "source_region": "...", "auto_cap": 60}]
  },
  "maps_to_metric_summary": {
    "g_eval_composite":   0.0-100.0,  // weighted aggregate of criteria whose maps_to_metric includes "g_eval.*"
    "finesure_composite": 0.0-100.0,
    "qafact_composite":   0.0-100.0,
    "summac_composite":   0.0-100.0
  },
  "editorialization_flags": [
    {"sentence": "...", "flag_type": "added_stance" | "added_judgment" | "added_framing", "explanation": "..."}
  ],
  "evaluator_metadata": {
    "prompt_version": "evaluator.v1",
    "rubric_version": "rubric_<source>.v1",
    "atomic_facts_hash": "<sha256>",
    "model_used": "gemini-2.5-pro",
    "total_tokens_in": 0,
    "total_tokens_out": 0,
    "latency_ms": 0
  }
}
```

**New fields introduced (criteria2.md integration):**

- `anti_patterns_triggered` — every rubric YAML lists source-specific anti-patterns (GitHub: "claiming production-ready without evidence"; YouTube: "clickbait phrasing in label"; Reddit: "asserting unverified comment claims as truth"; Newsletter: "misrepresenting stance optimistic/skeptical"). When the consolidated call detects one, it's listed here and `caps_applied.hallucination_cap` is set to 60 automatically.
- `maps_to_metric_summary` — every rubric criterion carries a `maps_to_metric: list[str]` field (see §5 YAML structure). The consolidated call aggregates criterion scores along four axes (G-Eval / FineSurE / QAFactEval / SummaC) so future sessions can claim "rubric composite 87 implies FineSurE faithfulness ≥ 0.94" without running the academic metrics separately.
- `editorialization_flags` — per §I6, the evaluator prompt now includes a universal "does the summary introduce stance, judgment, or framing absent from the source?" check. Flagged sentences are listed with a taxonomy tag. Triggering any flag contributes to the `finesure.faithfulness` score penalty; accumulating ≥ 3 flags triggers the hallucination cap (60).

### 3.3 Atomic-fact extraction (cached)

One Flash call per URL, cached at `docs/summary_eval/_cache/atomic_facts/<url_sha>.json`. Prompt asks for **importance-ranked source-grounded claims** (entities, numbers, constraints, conclusions). Output is a list of `{claim, importance: 1-5}` items, capped at 30 per source. Fed into the consolidated evaluator prompt so FineSurE's completeness scoring is grounded on a **fixed** keyfact set, not re-extracted each iteration — this prevents "atomic-facts drift" where the same source produces different keyfact lists across eval runs.

### 3.4 RAGAS integration

```python
# ragas_bridge.py — conceptual
from ragas.metrics import Faithfulness, AspectCritic
from ragas.llms.base import BaseRagasLLM

class GeminiRagasLLM(BaseRagasLLM):
    """Proxies ragas LLM calls through TieredGeminiClient, honoring key pool + tier policy."""
    def __init__(self, client: TieredGeminiClient, tier: str = "pro"): ...
    async def generate_text(self, prompt, ...) -> LLMResult: ...

class RagasBridge:
    async def faithfulness(self, summary: str, source: str) -> float: ...
    async def aspect_critic_rubric(self, summary: str, source: str, rubric_yaml: dict) -> dict: ...
```

- **Faithfulness** triggered only when `rubric.faithfulness` from the consolidated call OR `finesure.faithfulness` < 0.9. Saves ~60% of RAGAS Pro calls.
- **AspectCritic** runs every iteration with the rubric YAML as its criteria — produces an independent rubric score. If |consolidated_composite − aspect_critic_composite| > 10 points, `eval.json` gets `rubric_disagreement_flag: true` and the discrepancy is surfaced in `next_actions.md`.
- **Not used: RAGAS `SummarizationScore`.** Overlaps heavily with consolidated call's question-generation style scoring; doubles Pro cost for marginal gain.

### 3.5 SummaC-lite

Implemented inside the consolidated prompt (not a separate call). The prompt instructs Gemini Pro: for each sentence in the summary, classify its relationship to the source as `entailed` | `contradicted` | `neutral`. Score = `count(entailed) / count(total_sentences)`. This is a zero-extra-call approximation of SummaC-ZS's sentence-pair NLI formulation. No separate HuggingFace model.

### 3.6 Composite score formula

```python
def composite_score(eval_result: EvalResult) -> float:
    base = (
        0.60 * eval_result.rubric.total_of_100
      + 0.20 * eval_result.finesure.faithfulness.score * 100
      + 0.10 * eval_result.finesure.completeness.score * 100
      + 0.10 * mean([
            eval_result.g_eval.coherence,
            eval_result.g_eval.consistency,
            eval_result.g_eval.fluency,
            eval_result.g_eval.relevance,
        ]) * 20
    )
    return apply_caps(base, eval_result.rubric.caps_applied)

def apply_caps(score: float, caps: dict) -> float:
    if caps.get("hallucination_cap"):
        return min(score, 60)
    if caps.get("omission_cap"):
        return min(score, 75)
    if caps.get("generic_cap"):
        return min(score, 90)
    return score
```

Cap dominance rule: **a single invented fact caps the composite at 60, regardless of how polished everything else is**. Directly implements the research-doc cap rules.

### 3.7 Manual review step (cross-model independence — Codex, not Gemini)

**Design principle: two independent model families score each iteration** — Gemini (consolidated evaluator in §3.2) vs OpenAI (Codex's underlying model, currently `gpt-5.3-codex`). This gives genuine model-family independence rather than same-model-different-prompt pseudo-independence. Codex is already running the iteration loop; using its model as the manual reviewer adds zero extra API surface or cost.

**Handoff protocol — file-based, no cross-model API calls:**

1. After the consolidated Gemini evaluator completes (step 6 of the per-iteration runbook in §8.2), the CLI writes `docs/summary_eval/<source>/iter-<N>/manual_review_prompt.md` containing:
   - The source rubric YAML for this source
   - The summary JSON (but NOT `eval.json` — reviewer stays blind to Gemini's scoring)
   - The atomic facts list
   - The source raw text
   - Explicit instructions: "Score each criterion independently. Produce a self-estimated composite score. Save as `manual_review.md` in this directory. Do NOT look at `eval.json`."
2. CLI exits with `status=awaiting_manual_review` and prints the prompt path. **No Gemini call is made for manual review.**
3. Codex (the agent driving the program) reads `manual_review_prompt.md` and produces `docs/summary_eval/<source>/iter-<N>/manual_review.md` using its own model. Codex treats this as a required step in every tuning iteration's runbook. Codex **must not** consult `eval.json` while writing the review — enforced by hash check (see below).
4. Codex re-invokes `eval_loop.py --source <s> --iter N` (same command, any number of times). The CLI auto-detects state: if `summary.json` + `eval.json` + `manual_review.md` exist but `diff.md` doesn't, it runs the "finalize" phase (steps 7-11).
5. Finalize phase reads `manual_review.md`, extracts the self-estimated composite, computes `divergence_score = |eval.json.composite - manual_review.estimated_composite|`, flags divergence > 10 pts at the top of `manual_review.md` AND in `next_actions.md`.

**Blind-review enforcement.** At the top of `manual_review_prompt.md`, the CLI writes a SHA256 of the CURRENT `eval.json`. When Codex submits `manual_review.md`, it must include a stamp `eval_json_hash_at_review: "NOT_CONSULTED"`. Any other value (or an actual hash match) indicates Codex consulted `eval.json`, invalidating the blind-review protocol. CLI fails finalize with `status=blind_review_violation` in that case. This is honor-system enforced (Codex could lie), but the guard is visible and documented.

**Output format (`manual_review.md`):**
- Criterion-by-criterion prose assessment (5–15 sentences per criterion, source-grounded)
- Per-criterion estimated score (matches rubric YAML's `max_points`)
- Summary composite score (0–100)
- Short free-form "most impactful improvement" note
- Final line: `estimated_composite: NN.N` (parseable by the CLI)

**Divergence handling:**
- 0 ≤ divergence ≤ 5: `manual_review.md` stamped `AGREEMENT`
- 5 < divergence ≤ 10: stamped `MINOR_DISAGREEMENT`
- divergence > 10: stamped `MAJOR_DISAGREEMENT`, both scores logged separately in `next_actions.md`, and the LOWER of the two becomes the reference score the next iteration tries to beat (pessimistic). After two consecutive MAJOR_DISAGREEMENT loops, `status=evaluator_codex_disagreement` and Codex must write a one-line explanation in `docs/summary_eval/<source>/iter-<N>/disagreement_analysis.md` (not an automatic halt, just an attention anchor).

**Why this fulfills the cross-model isolation requirement:**
- Gemini Pro evaluates the summary via the consolidated call + RAGAS (same model family).
- Codex (OpenAI `gpt-5.3-codex`) independently evaluates via `manual_review.md`.
- Gemini cannot influence Codex's review (file-based handoff, blind to `eval.json`).
- Codex cannot influence Gemini's scoring (Gemini call already complete before handoff).
- Two model families, two independent scoring passes, divergence as the bias-detection signal.

**Cost impact:**
- Removes ~50 Gemini Pro calls across the program (manual-review phase no longer uses Gemini).
- Zero added cost (Codex is the driver regardless).
- Net savings ~50 Pro calls; billing cost projection in §9.6 updated accordingly.

### 3.8 Stop / pass criterion (per source)

A source is "done" iterating when ALL of:
1. In the last 5 tuning iterations where URL #1 was run, ≥ 3 had `composite ≥ 92 AND ragas_faithfulness ≥ 0.95` on URL #1.
2. Loop-5 had URLs #1, #2, #3 each ≥ 88 composite.
3. Loop-6 held-out mean ≥ 88 AND no single held-out URL < 0.95 faithfulness.

If (1) or (2) fails at loop 5: continue to loops 6-7 normally. If (3) fails at loop 6: CLI auto-triggers extension loops 8-9.

### 3.9 Design choices worth preserving

- `temperature=0.0` for evaluator (near-deterministic); `0.3` for summarizer (unchanged from current).
- No rouge / BLEU / BERTScore — reference-based, unusable here.
- RAGAS `Faithfulness` conditional, not unconditional — saves calls.
- Atomic-facts cached once per URL, lifetime — prevents extractor drift.
- Hallucination cap at 60 is **non-negotiable** — this is the single biggest guard against rewarded-but-wrong summaries.

---

## 4. Multi-URL loop allocation

### 4.1 Per-source loop shape (7 base + up to 2 extension)

| Loop | Purpose | URLs | Code edits? | Early-stop possible? |
|---|---|---|---|---|
| **1 — Baseline** | Measure current engine on URL #1, no tuning | URL #1 | No | No |
| **2 — First tune (single-URL)** | Codex edits prompts/config targeting lowest-scoring criteria | URL #1 | Yes | No |
| **3 — Second tune (single-URL)** | Another pass on URL #1's remaining weaknesses | URL #1 | Yes | No |
| **4 — Cross-URL probe** | Run current prompts on URL #2 — no edits. Measures overfitting to URL #1 | URLs #1, #2 | No | No |
| **5 — Joint tune (multi-URL)** | Tune so URLs #1, #2, #3 all pass. Core cross-URL coverage step. | URLs #1, #2, #3 | Yes | Yes (if all 3 ≥ 92/0.95) |
| **6 — Held-out validation** | Run all remaining URLs for this source in `links.txt`, no edits | All remaining | No | Yes (if thresholds pass) |
| **7 — Prod-parity validation** | `SUMMARIZE_ENV=prod-parity` env flag on same local server, re-run held-out set | All remaining | No | Final; no early-stop |
| **8 (extension, auto-triggered)** | Only if loop-6 aggregate < 88 OR any held-out URL < 0.95 faithfulness. Root-cause + joint re-tune on all URLs. | URLs #1–#3 + failing held-out URLs | Yes | Yes |
| **9 (extension, auto-triggered)** | Only if loop 8 ran. Final cross-URL validation + prod-parity re-run. | All | No | Final |

### 4.2 URL inventory policy

`docs/testing/links.txt` migrated to section-headered format during Phase 0:

```
# YouTube
https://www.youtube.com/watch?v=hhjhU5MXZOo
https://www.youtube.com/watch?v=HBTYVVUBAGs
...

# Twitter
https://x.com/arrgnt_sanatan/status/1854027462042321075

# Reddit
https://www.reddit.com/r/IndianStockMarket/comments/1getc4l/...
...

# GitHub
# (user adds before GitHub cycle starts; else CLI auto-discovers 3 URLs)

# Newsletter
# (user adds before Newsletter cycle starts; else CLI auto-discovers)

... etc. for HackerNews, LinkedIn, Arxiv, Podcast, Web
```

On every `eval_loop.py` invocation, `_check_url_inventory(source)`:
1. Parses `links.txt` by `# <source>` headers (case-insensitive).
2. If ≥ 3 URLs: use them, log `url_source=user`.
3. If < 3: call `ops/scripts/lib/url_discovery.py` — Gemini Flash prompt + WebSearch + WebFetch proposes 3 canonical rubric-fit URLs. Uses discovered URLs **live** (no approval gate). Writes `docs/summary_eval/<source>/auto_discovered_urls.md` with URLs + rationale + rubric-relevance score.
4. Records `url_provenance` in every `iter-N/input.json`.

---

## 5. Artifact layout

All outputs live permanently under `docs/summary_eval/`. No purges between iterations or between sources. This folder doubles as the historical eval dataset for future sessions to replay and diff against.

```
docs/summary_eval/
├── README.md                                  # Auto-regenerated leaderboard + index
├── _config/
│   ├── rubric_youtube.yaml                    # 100-pt rubric: criteria + maps_to_metric + anti_patterns (see below)
│   ├── rubric_reddit.yaml
│   ├── rubric_github.yaml
│   ├── rubric_newsletter.yaml
│   └── rubric_universal.yaml                  # Applied to hackernews/linkedin/arxiv/podcast/twitter/web
│   └── branded_newsletter_sources.yaml        # List of recurring/branded newsletters triggering publication+thesis label
├── _cache/                                    # Content-hashed; never purged
│   ├── ingests/<url_sha256>.json
│   ├── atomic_facts/<url_sha256>.json
│   ├── summaries/<summary_hash>.json
│   └── youtube_instance_health.json           # 1-hour TTL for Piped/Invidious pool health
├── youtube/
│   ├── phase0.5-ingest/
│   │   ├── websearch-notes.md                 # 2026-era transcript-fetch landscape
│   │   ├── candidates/
│   │   │   ├── 01-ytdlp-player-rotation.json
│   │   │   ├── 02-transcript-api.json
│   │   │   ├── 03-piped-pool.json
│   │   │   ├── 04-invidious-pool.json
│   │   │   ├── 05-gemini-audio-file-api.json
│   │   │   └── 06-metadata-only.json
│   │   └── decision.md
│   ├── edit_ledger.json                       # Cross-iteration file-edit tracking (see §6.4)
│   ├── iter-01/
│   │   ├── input.json                         # URL + all hashes + config snapshot + cost ledger
│   │   ├── summary.json                       # Raw /api/v2/summarize response
│   │   ├── eval.json                          # Consolidated Gemini evaluator output
│   │   ├── manual_review_prompt.md            # CLI-written handoff to Codex (incl. eval.json hash)
│   │   ├── manual_review.md                   # Codex-written independent rubric pass (OpenAI model; blind to eval.json)
│   │   ├── diff.md                            # Scores + code diff vs iter-(N-1)
│   │   ├── next_actions.md                    # Ranked edit proposals (incl. divergence analysis)
│   │   └── run.log                            # Full stdout from the CLI run (both phases)
│   ├── iter-02/ ... iter-05/                  # Tuning loops
│   ├── iter-06/
│   │   ├── held_out/<url_sha256>/
│   │   │   ├── summary.json
│   │   │   └── eval.json
│   │   └── aggregate.md
│   ├── iter-07/                               # Same structure, prod-parity env
│   ├── iter-08/ iter-09/                      # Extension loops (only if triggered)
│   └── final_scorecard.md                     # Baseline → final delta + lessons + open issues
├── reddit/ github/ newsletter/                # Same structure as youtube/
├── polish/
│   ├── hackernews/
│   │   ├── iter-01/ iter-02/ iter-03/         # 2-3 touch-up loops
│   │   └── final_scorecard.md
│   ├── linkedin/ arxiv/ podcast/ twitter/ web/
│   └── cross_source_lessons.md                # Synthesis across all 10 sources at program end
└── .halt                                       # Optional; presence halts the CLI on next invocation
```

### 5.1 Rubric YAML structure (post-criteria2 integration)

Every `_config/rubric_<source>.yaml` follows this schema:

```yaml
version: "rubric_youtube.v1"
source_type: "youtube"
composite_max_points: 100
components:
  - id: "brief_summary"
    max_points: 25
    criteria:
      - id: "brief.thesis_capture"
        description: "Brief summary states the video's central thesis or promise in one sentence."
        max_points: 5
        maps_to_metric: ["g_eval.relevance", "finesure.completeness"]
        examples_pass:
          - "The video argues that transformer attention is computationally equivalent to kernel regression."
        examples_fail:
          - "The video covers several machine learning topics."  # too vague
      - id: "brief.format_identified"
        description: "Brief identifies the video format (tutorial/interview/lecture/etc.) explicitly."
        max_points: 3
        maps_to_metric: ["g_eval.relevance"]
      - id: "brief.speakers_captured"
        description: "Brief mentions the host/speaker + any guests + key products/libraries discussed."
        max_points: 4
        maps_to_metric: ["finesure.completeness", "qafact"]
      # ... etc., totaling max_points = 25 for this component
  - id: "detailed_summary"
    max_points: 45
    criteria: [...]
  - id: "tags"
    max_points: 15
    criteria: [...]
  - id: "label"
    max_points: 15
    criteria: [...]

anti_patterns:
  - id: "clickbait_label_retention"
    description: "Label retains YouTube clickbait phrasing (e.g., 'You won't believe...', 'This changes EVERYTHING')."
    auto_cap: 90                                   # triggers generic_cap
    detection_hint: "Look for exclamation marks, superlatives, curiosity-gap phrasing in label."
  - id: "example_verbatim_reproduction"
    description: "Brief or detailed summary reproduces an example/analogy verbatim instead of summarizing its purpose."
    auto_cap: null                                 # penalty, not cap: subtracts 3 from finesure.conciseness
    penalty_points: 3
  - id: "editorialized_stance"
    description: "Summary introduces stance/framing not present in source (e.g., calling neutral content 'bullish')."
    auto_cap: 60                                   # triggers hallucination_cap
    detection_hint: "Check for evaluative adjectives absent from source transcript."

global_rules:
  editorialization_penalty:
    threshold_flags: 3                             # accumulating this many editorialization_flags triggers hallucination_cap
    cap_on_trigger: 60
```

Per-source rubric YAML follows this structure. `rubric_universal.yaml` (for the 6 polish sources) uses a leaner version with generic criteria per component.

`branded_newsletter_sources.yaml` lists publications that trigger C2's hybrid label format (publication+thesis). Starting list: `stratechery.com`, `platformer.news`, `lennysnewsletter.com`, `notboring.co`, `mattklein.com`, `thedispatch.com`, `rogerabout.substack.com`. Codex can extend the list during Newsletter-phase iterations; this is a plain YAML edit, no rubric-softening concern.

---

## 6. Phase 0 — engine refactor (one-time)

### 6.1 Per-source summarizer classes

Delete `summarization/_wrappers.py` `make_wrapper` factory. Each source gets a real class + module:

```
summarization/
├── base.py                     # unchanged: BaseSummarizer ABC
├── common/
│   ├── cod.py                  # unchanged
│   ├── self_check.py           # unchanged
│   ├── patch.py                # unchanged
│   ├── structured.py           # refactor: accepts a per-source StructuredSummaryPayload class
│   └── prompts.py              # refactor: SYSTEM_PROMPT stays; SOURCE_CONTEXT deleted (moves per-source)
├── youtube/
│   ├── __init__.py
│   ├── summarizer.py           # class YouTubeSummarizer(BaseSummarizer)
│   ├── prompts.py              # YouTube-specific CoD/self-check/structured-extract prompts
│   └── schema.py               # YouTube Pydantic StructuredSummaryPayload with typed required fields
├── reddit/ github/ newsletter/ # same structure
├── default/
│   └── summarizer.py           # generic DefaultSummarizer, parametrized by SourceType
│                               # used by the 6 polish-phase sources (hackernews/linkedin/arxiv/podcast/twitter/web)
```

Per-source `schema.py` examples:

**GitHub** (`summarization/github/schema.py`):
```python
class GitHubStructuredPayload(StructuredSummaryPayload):
    mini_title: constr(regex=r"^[^/]+/[^/]+$")  # owner/repo format enforced
    architecture_overview: constr(min_length=50, max_length=500)  # NEW (I3): prose, 1-3 sentences
                                                                   # describing major directories/modules and how they interact
    benchmarks_tests_examples: list[str] | None = None            # NEW (I3): what benchmarks/tests/examples demonstrate,
                                                                   # populated when those dirs exist in the repo
    detailed_summary: list[GitHubDetailedSection]

class GitHubDetailedSection(DetailedSummarySection):
    module_or_feature: str
    main_stack: list[str]
    public_interfaces: list[str]   # API routes, CLI commands, package exports, Pages URL
    usability_signals: list[str]   # releases, CI, docs presence, test coverage hints
```

**Reddit** (`summarization/reddit/schema.py`):
```python
class RedditStructuredPayload(StructuredSummaryPayload):
    mini_title: constr(regex=r"^r/[^ ]+ .+$")  # r/subreddit + compact title
    detailed_summary: RedditDetailedPayload

class RedditDetailedPayload(BaseModel):
    op_intent: str
    reply_clusters: list[RedditCluster]
    counterarguments: list[str]
    unresolved_questions: list[str]
    moderation_context: str | None = None
```

**YouTube** (`summarization/youtube/schema.py`):
```python
class YouTubeStructuredPayload(StructuredSummaryPayload):
    mini_title: constr(max_length=50)
    speakers: list[str] = Field(..., min_length=1)                 # NEW (I4): host/channel + guests + key referenced people
    guests: list[str] | None = None                                # NEW (I4): explicit guest list, None when single-host
    entities_discussed: list[str] = Field(default_factory=list)    # NEW (I4): products, libraries, datasets, case studies
    detailed_summary: YouTubeDetailedPayload

class YouTubeDetailedPayload(BaseModel):
    thesis: str
    format: Literal["tutorial", "interview", "commentary", "lecture", "review", "debate", "walkthrough", "reaction", "vlog", "other"]
    chapters_or_segments: list[ChapterBullet]
    demonstrations: list[str]
    closing_takeaway: str
```

**Newsletter** (`summarization/newsletter/schema.py`):
```python
class NewsletterStructuredPayload(StructuredSummaryPayload):
    mini_title: str  # C2 hybrid: "publication + thesis" IF publication is in branded_newsletter_sources.yaml,
                     # ELSE thesis-only. Validator checks against YAML list at build time.
    detailed_summary: NewsletterDetailedPayload

class NewsletterDetailedPayload(BaseModel):
    publication_identity: str
    issue_thesis: str
    sections: list[NewsletterSection]
    conclusions_or_recommendations: list[str] = Field(default_factory=list)  # NEW (I5): author's main conclusions
                                                                              # or recommendations, DISTINCT from descriptive
                                                                              # background; evaluator checks this is populated
                                                                              # when the source offers actionable guidance
    stance: Literal["optimistic", "skeptical", "cautionary", "neutral", "mixed"]  # NEW (I5): source's apparent stance;
                                                                                    # rubric penalizes mismatch between detected
                                                                                    # stance and summary tone (editorialization_flag)
    cta: str | None = None
```

**`mini_title` validator logic (C2 hybrid):**
```python
def _validate_newsletter_title(cls, value: str, info: ValidationInfo) -> str:
    publication = info.data.get("publication_identity", "")
    branded_sources = load_branded_newsletter_sources()  # reads branded_newsletter_sources.yaml
    is_branded = any(bs in publication.lower() for bs in branded_sources)
    if is_branded and not any(token in value for token in publication.split()):
        raise ValueError(f"Branded source '{publication}' requires publication name in label")
    # Non-branded: thesis-only is acceptable; no enforcement on publication inclusion.
    return value
```

**On-wire compatibility:** `SummaryResult.detailed_summary` remains `list[DetailedSummarySection]` at the API boundary. Per-source typed fields live inside `DetailedSummarySection.sub_sections` (already a `dict[str, list[str]]`). The structured-extract call uses the source-specific `StructuredSummaryPayload` for validation, then projects into the generic on-wire shape before returning. Supabase KG writer unchanged, no migration.

### 6.2 Config-driven output caps

`core/models.py` currently hard-codes:
```python
mini_title: str = Field(..., max_length=60)
brief_summary: str = Field(..., max_length=400)
tags: list[str] = Field(..., min_length=8, max_length=15)
```

Refactor into a factory:
```python
def build_summary_result_model(cfg: EngineConfig) -> type[BaseModel]:
    cls = type(
        "SummaryResult",
        (SummaryResultBase,),
        {
            "__annotations__": {
                "mini_title": str,
                "brief_summary": str,
                "tags": list[str],
                "detailed_summary": list[DetailedSummarySection],
                "metadata": SummaryMetadata,
            },
            "mini_title": Field(..., max_length=cfg.structured_extract.mini_title_max_chars),
            "brief_summary": Field(..., max_length=cfg.structured_extract.brief_summary_max_chars),
            "tags": Field(..., min_length=cfg.structured_extract.tags_min, max_length=cfg.structured_extract.tags_max),
            ...
        }
    )
    return cls
```

New `config.yaml` keys (defaults preserve current behavior except for tag counts):
```yaml
structured_extract:
  mini_title_max_chars: 60
  brief_summary_max_chars: 400
  brief_summary_max_sentences: 7             # NEW — soft cap, enforced in validator
  brief_summary_min_sentences: 5             # NEW
  detailed_summary_max_bullets_per_section: 8  # NEW
  detailed_summary_min_bullets_per_section: 1  # NEW
  tags_min: 7                                # CHANGED from 8 (rubric: 7-10)
  tags_max: 10                               # CHANGED from 15 (rubric: 7-10)
```

**Behavior change:** tag counts drop from 8–15 to 7–10. Downstream Supabase KG writer has no tag-count validation; migration-free.

### 6.3 Three-layer content cache

New `website/features/summarization_engine/core/cache.py`:

```python
class FsContentCache:
    def __init__(self, root: Path, namespace: str): ...
    def get(self, key_tuple: tuple) -> dict | None: ...
    def put(self, key_tuple: tuple, payload: dict) -> None: ...
    def key_hash(self, key_tuple: tuple) -> str:  # stable SHA256 of canonicalized JSON
        ...
```

Three instances wired into the orchestrator and evaluator:

- **Ingest cache** — `(url_canonical, ingestor_version, source_config_hash)` → `IngestResult`. Path: `docs/summary_eval/_cache/ingests/<hash>.json`.
- **Summary cache** — `(ingest_hash, engine_config_hash, summarizer_prompts_hash)` → `SummaryResult`. Path: `docs/summary_eval/_cache/summaries/<hash>.json`. Rarely hits during tuning (prompts change); useful for evaluator-only re-runs.
- **Atomic-facts cache** — `(ingest_hash, atomic_facts_prompt_hash)` → `list[{claim, importance}]`. Path: `docs/summary_eval/_cache/atomic_facts/<hash>.json`. Massive savings (~7×).

Override: `eval_loop.py --no-cache`. Global: `CACHE_DISABLED=1` env var.

### 6.4 URL inventory check

`ops/scripts/lib/url_discovery.py` (new):
```python
async def discover_urls(source_type: SourceType, count: int = 3) -> list[dict]:
    """
    Uses Gemini Flash with the google_search grounding tool to find `count` canonical URLs
    for the given source type that match its rubric's diversity signals
    (e.g., GitHub: one popular monorepo + one simple library + one minimal-README repo).
    Returns [{"url": ..., "rationale": ..., "rubric_fit_score": 0-100}].
    Writes result to docs/summary_eval/<source>/auto_discovered_urls.md.
    """
```

**Discovery mechanism:** Gemini 2.5's built-in `google_search` tool, passed as `tools=[{"google_search": {}}]` to `client.models.generate_content`. The prompt is a rubric-templated request like:

> *"Find 3 canonical GitHub repository URLs for summarization-engine testing. Coverage target: one popular multi-module repo (>5k stars, active), one simple single-purpose library (<1k stars), one minimal-README repo (README <200 words). Return as JSON array of objects with keys `url`, `rationale`, `rubric_fit_score` (0-100). The URLs must resolve to real public repos."*

The grounding API returns URLs that Gemini has actually seen via search — not hallucinated. A validator step HEAD-checks each URL before accepting (HTTP 200 required). Discovered URLs are used **live**, no approval gate, per the Section 3.6 decision.

**Fallback if google_search grounding fails** (quota, tool deprecation, etc.): Gemini Flash is prompted with its training-data canonical URLs for the source type (e.g., "facebook/react", "pallets/flask" for GitHub) + validator HEAD-check. Less fresh but deterministic.

### 6.5 Evaluator + CLI scaffolding

Create skeletons of `website/features/summarization_engine/evaluator/` and `ops/scripts/eval_loop.py`. No real logic yet — returns stubs. Real implementation lands in Phase 0.5 (evaluator) and during per-source iterations (CLI features).

### 6.6 Phase 0 exit criteria

Phase 0 is complete when:

1. `pytest tests/unit/ -q` passes (existing tests updated for new per-source classes + tag-count change).
2. `curl -X POST http://127.0.0.1:10000/api/v2/summarize -d '{"url":"https://www.youtube.com/watch?v=hhjhU5MXZOo"}'` returns a valid `SummaryResult` with YouTube-specific schema structure. Server started via `python run.py`.
3. The three caches create their directories under `docs/summary_eval/_cache/` on first use.
4. `python ops/scripts/eval_loop.py --source youtube --list-urls` correctly parses section-headered `links.txt`.
5. `docs/testing/links.txt` migrated to section-headered format (Codex task in Phase 0): current numbered URLs partitioned into `# YouTube`, `# Twitter`, `# Reddit` sections; empty sections stubbed for `# GitHub`, `# Newsletter`, `# HackerNews`, `# LinkedIn`, `# Arxiv`, `# Podcast`, `# Web` with a comment explaining user-add-or-auto-discover behavior. Old numbered format gone; single commit records the migration.
6. Evaluator prompts include a `PROMPT_VERSION = "evaluator.v1"` constant in `website/features/summarization_engine/evaluator/prompts.py`. Any edit to evaluator prompts after Phase 0 requires bumping this constant, which invalidates the determinism cache and forces rescoring of prior summaries on next iteration start.
7. A single commit lands: `refactor: per-source summarizers + engine caches`.

**Cost:** 3-4 Pro + ~5 Flash (smoke test only).

---

## 7. Phase 0.5 — per-source ingest unblocker

Runs once per source, first thing in its cycle, before iteration 1. A/B benchmarks fallback strategies, picks one, logs rationale.

### 7.1 YouTube — free-only fallback chain

**WebSearch phase (zero Gemini cost):**
- "youtube-transcript-api datacenter IP blocked 2026 solutions"
- "yt-dlp youtube transcript player client android_embedded"
- "Piped Invidious public instance transcript API 2026"

Captures `docs/summary_eval/youtube/phase0.5-ingest/websearch-notes.md`.

**Fallback chain (all free, ordered):**

| Tier | Strategy | Reliability | Latency | Cost |
|---|---|---|---|---|
| Primary | `yt-dlp` with **player-client rotation** (`android_embedded` → `ios` → `tv_embedded` → `mweb` → `web`) using `--write-auto-sub --sub-langs en.* --skip-download`, parse `.vtt` locally | 80-90% | 5-10s | $0 |
| Fallback 1 | `youtube-transcript-api` direct (kept for occasional wins) | 10-30% | 2s | $0 |
| Fallback 2 | Piped public instance pool — 8 instances, 10s timeout, round-robin, health-cache | 60-70% aggregate | 10-30s | $0 |
| Fallback 3 | Invidious public instance pool — 6 instances, same rotation | 40-50% | 10-30s | $0 |
| Fallback 4 | **Gemini Flash audio transcription** — `yt-dlp -f bestaudio --max-filesize 50M` → `files.upload(path, mime_type="audio/mp4")` → Flash transcription prompt | ~95% | 30-90s | Free-tier Flash quota; ~$0.01-0.05/hr on billing if quota exhausted. Lifetime cached per URL. |
| Fallback 5 | `yt-dlp` metadata-only (title + description) | 100% | 2s | $0. Stamps `extraction_confidence="low"`; evaluator caps composite at 75. |

**Critical implementation note on Fallback 4:** upload actual audio bytes via `client.files.upload(path, mime_type="audio/mp4")`. **Do NOT use `Part.from_uri` with YouTube watch URLs** — that's the previously-disabled broken path; it made Gemini hallucinate unrelated content. A prominent comment in the code must prevent regression.

**Config additions:**
```yaml
sources:
  youtube:
    transcript_languages: ["en", "en-US", "en-GB"]
    ytdlp_player_clients: ["android_embedded", "ios", "tv_embedded", "mweb", "web"]
    transcript_budget_ms: 90000                # 90s total before giving up
    # Starting instance lists — validated and pruned during Phase 0.5 via liveness benchmark.
    # Both pools are expected to churn; Codex refreshes the list from the public Piped/Invidious
    # instance registries (https://github.com/TeamPiped/Piped/wiki/Instances, https://api.invidious.io/)
    # if Phase 0.5 shows >50% of initial list dead.
    piped_instances:
      - pipedapi.kavin.rocks
      - pipedapi.adminforge.de
      - pipedapi.r4fo.com
      - pipedapi.syncpundit.io
      - pipedapi.in.projectsegfau.lt
      - pipedapi.us.projectsegfau.lt
      - pipedapi.smnz.de
      - pipedapi.drgns.space
    invidious_instances:
      - invidious.fdn.fr
      - yewtu.be
      - inv.tux.pizza
      - iv.melmac.space
      - invidious.privacydev.net
      - vid.puffyan.us
    instance_health_ttl_hours: 1
    enable_gemini_audio_fallback: true
    gemini_audio_max_duration_min: 60
    gemini_audio_max_filesize_mb: 50
```

**Health-check cache:** `docs/summary_eval/_cache/youtube_instance_health.json`, 1-hour TTL per instance. Dead instances drop out of rotation temporarily.

**Acceptance:** chosen chain gets `extraction_confidence=high` on ≥ 2 of 3 YouTube benchmark URLs, `≥ medium` on the 3rd.

### 7.2 Reddit

Current anonymous-JSON ingest works but misses removed-comment recovery (rubric requires tracking `num_comments` vs rendered-count divergence). Candidates:

- **A. Anonymous JSON + UA rotation** (current, keep as primary)
- **B. PRAW with OAuth** (already coded; gated on `REDDIT_CLIENT_ID/SECRET` — only if A blocks in prod)
- **C. pullpush.io for removed-comment recovery** (free third-party archive; adds recovered text with explicit `(removed, recovered from pullpush.io)` tag so evaluator scores consensus/dissent correctly)

**Recommended:** A as primary + C as enrichment. Verified on both `r/IAmA` heroin threads in `links.txt` (both contain removed comments).

### 7.3 GitHub

Current ingest captures README + issues + commits. Rubric-driven gaps:
- ❌ Pages deployment URL (rubric: "important public-facing surface")
- ❌ GitHub Actions workflow presence (proxy for "state of usability")
- ❌ Releases (proxy for maturity)
- ❌ Language composition percentages (rubric: "major programming languages" with specificity)

**Fix:** add 4 GitHub REST API calls per ingest: `/repos/{owner}/{repo}/pages`, `/actions/workflows`, `/releases`, `/languages`. Authenticated rate limit is 5000/hr; well within budget.

**Additional (I3 integration):** add 1 more GitHub REST API call — `/repos/{owner}/{repo}/contents/` (root directory listing) — to detect presence of `benchmarks/`, `tests/`, `examples/`, `docs/`, `demo/` directories. Populates `IngestResult.metadata` with boolean flags `has_benchmarks`, `has_tests`, `has_examples`, `has_docs_dir`, `has_demo`. Used by the summarizer to fill the `GitHubStructuredPayload.benchmarks_tests_examples` field — if no such directory exists, the field is `None` and the rubric's "benchmarks/tests/examples" criterion scores 0 without penalizing the summary for omitting what wasn't there. If the directory exists but the summarizer can't describe what it contains, that's a completeness failure worth penalizing. Total GitHub API calls per ingest: 5 (was 4), still well under the 5000/hr limit.

### 7.4 Newsletter

Current extractors drop subject + preheader + CTA structure. **Fixes:**
- Site-specific selectors layered over trafilatura (Substack: `h1.post-title`, `h3.subtitle`, `.post-footer a[href]`; Beehiiv and Medium equivalents).
- Preheader fallback: first 150 chars of body if no structured preheader.
- CTA extraction: parse `<a>` with text matching `/subscribe|sign up|read|learn|join|try|start/i`, rank by position + heading level + button class.
- **Conclusions/recommendations detection (I5 integration):** scan the final 30% of body text for imperative-mood sentences, sentences starting with "I recommend" / "You should" / "The key takeaway is", and bullet lists under headers like "Takeaways", "What to do", "Action items". Populates `IngestResult.metadata.conclusions_candidates` which the summarizer uses as input to `NewsletterDetailedPayload.conclusions_or_recommendations`.
- **Stance detection (I5 integration):** a one-shot Gemini Flash call classifies the source's overall stance (`optimistic` / `skeptical` / `cautionary` / `neutral` / `mixed`) based on tone markers. Stored in `IngestResult.metadata.detected_stance`. Used by the evaluator's editorialization check: if the summary's implied stance differs from source's detected stance, that's an `editorialization_flag`.
- **Branded-source list (C2 hybrid):** Phase 0.5 creates `docs/summary_eval/_config/branded_newsletter_sources.yaml` seeded with the starting list documented in §5.1. CLI exits with `status=awaiting_branded_list_review` on first newsletter Phase 0.5 run for Codex to extend/trim the list once based on which newsletter URLs the user added.

### 7.5 Polish-phase sources (HackerNews, LinkedIn, Arxiv, Podcast, Twitter, Web)

No dedicated Phase 0.5. Existing ingestors are assumed adequate. If scores plateau below 85 during their 2-3 polish iterations, retroactive Phase 0.5 is added then (documented in `polish/<source>/final_scorecard.md`). Twitter adds 3 extra Nitter instances to the pool (`nitter.tiekoetter.com`, `nitter.net`, `nitter.salastil.com`) plus instance-health cache.

### 7.6 Phase 0.5 cost summary

- YouTube: ~40-60 Pro + 15-20 Flash (5 candidates × 3 URLs × 1 summary + 1 eval each)
- Reddit: ~15 Pro + 10 Flash
- GitHub: ~10 Pro + 5 Flash
- Newsletter: ~20 Pro + 10 Flash

**Total: ~85-105 Pro + ~40-45 Flash.** Comfortable on a single free key over 1 day.

---

## 8. Iteration loop contract

### 8.1 CLI spec

```
ops/scripts/eval_loop.py
  --source {youtube,reddit,github,newsletter,hackernews,linkedin,arxiv,podcast,twitter,web}
  [--iter N]                      # Explicit loop number; else auto-detect next
  [--phase {0, 0.5, iter, extension}]
  [--env {dev, prod-parity}]      # Default dev; loop 7 sets prod-parity
  [--url URL]                     # Single-URL override
  [--no-cache]                    # Bypass all caches
  [--server URL]                  # Default http://127.0.0.1:10000
  [--manage-server]               # Restart FastAPI before Phase A (default on)
  [--auto]                        # Auto-trigger extension loops when loop 6 fails thresholds
  [--dry-run]                     # Parse inputs, print plan, exit without Gemini calls
  [--force-phase-a]               # Re-run Phase A even if summary.json + eval.json exist
                                  # (use when re-summarizing after a code change without clearing the iter folder)
  [--force-phase-b]               # Re-run Phase B (finalize) even if diff.md exists
                                  # (use after editing manual_review.md retroactively)
  [--emit-review-prompt-only]     # Run Phase A through step 6 only; skip determinism + engine (for Codex debugging)
  [--rebuild-index]               # Rebuild docs/summary_eval/README.md leaderboard
  [--list-urls]                   # Print parsed URL list for a source, exit
  [--report [--since DATE]]       # Cost ledger aggregate
  [--replay]                      # Re-run a prior iteration from artifact for reproducibility check
  [--stop-server]                 # Clean shutdown of managed FastAPI server
```

**Auto-resume state detection (default behavior):**
- No `summary.json` → run Phase A from step 1.
- `summary.json` + `eval.json` + NO `manual_review.md` → exit immediately with `status=awaiting_manual_review`, pointing to the existing `manual_review_prompt.md`.
- `summary.json` + `eval.json` + `manual_review.md` + NO `diff.md` → run Phase B.
- All files present including `diff.md` → iteration already finalized; refuse with `status=iteration_already_committed`, suggest `--iter <N+1>` or `--force-phase-b`.

### 8.2 Per-iteration runbook (two-phase, auto-resumed)

The CLI runs in TWO phases per iteration, with Codex's manual-review step in between. A single `eval_loop.py --source <s> --iter N` invocation runs Phase A, exits, then Codex writes `manual_review.md` using its own model, then Codex re-invokes the same command — the CLI auto-detects state and runs Phase B.

**Phase A — Standard evaluation (Gemini)**

1. **State check.** Read `docs/summary_eval/<source>/`, locate prior iteration, validate `iter-(N-1)` exists + committed. Refuse if prior loop's `eval.json` has `status=error`. If current `iter-<N>/` already has `summary.json` + `eval.json` + `manual_review.md` but no `diff.md`, SKIP to Phase B (auto-resume).
1.5. **Server lifecycle.** If `--manage-server` (default), gracefully restart FastAPI: SIGTERM, 5s wait, SIGKILL if needed, respawn `python run.py`, poll `GET /api/health` every 1s until 200 or 30s timeout. Skip if server already up AND no `website/**/*.py` or `config.yaml` changed since last iter (measurement-only loops 4, 6, 7).
2. **URL selection.** Per §4.1 allocation.
3. **Determinism check.** Re-run evaluator on iter-(N-1)'s `summary.json`. If new composite differs from stored composite by > 2 pts, write `status=evaluator_drift` to `next_actions.md` and halt.
4. **Engine invocation.** For each URL: `POST /api/v2/summarize {"url": ...}`. Store response as `summary.json`. Ingest cache hits skip Gemini ingest calls.
5. **Evaluator invocation.** `evaluator.evaluate(summary, ingest, source_type)` → consolidated Pro call → `eval.json`. Conditional RAGAS faithfulness + AspectCritic per §3.4.
6. **Manual-review prompt emission.** Write `manual_review_prompt.md` containing: rubric YAML for this source, `summary.json` content, atomic facts list, source raw text, the `eval.json` SHA256 hash (for blind-review enforcement), and clear instructions to Codex (see §3.7).
7. **Exit with `status=awaiting_manual_review`.** Prints the prompt path to stdout. CLI terminates cleanly; no error.

**Codex phase (between Phase A and Phase B)**

Codex (driving the program) reads `iter-<N>/manual_review_prompt.md`, produces `iter-<N>/manual_review.md` using its own model (`gpt-5.3-codex` or successor). Codex must include the stamp `eval_json_hash_at_review: "NOT_CONSULTED"` and must NOT read `eval.json` during this step. This is a required step in every tuning iteration (loops 2, 3, 5, 8). For measurement-only loops (1, 4, 6, 7), Codex still produces `manual_review.md` — the review is valuable at every iteration, including the ones with no code edits, because it's cross-checking the evaluator's scores.

Codex re-invokes the same CLI command: `eval_loop.py --source <s> --iter N`.

**Phase B — Finalization (triggered by state check)**

8. **Read manual review.** Parse `manual_review.md`. Verify the `eval_json_hash_at_review` stamp is `"NOT_CONSULTED"` (blind-review enforcement). If it's anything else, write `status=blind_review_violation` to `next_actions.md` and halt.
9. **Divergence computation.** `divergence_score = |eval.json.composite - manual_review.estimated_composite|`. Stamp `AGREEMENT` / `MINOR_DISAGREEMENT` / `MAJOR_DISAGREEMENT` at top of `manual_review.md`. After two consecutive MAJOR_DISAGREEMENT loops, request `disagreement_analysis.md` from Codex (soft-gate, not a halt).
10. **Diff computation.** Score deltas vs iter-(N-1). Git diff of edited files between iter-(N-1) and iter-N commits. Writes `diff.md`.
11. **Next-actions synthesis.** Flash call (not Pro): *"For every rubric criterion scoring below full credit, and every module in the engine that could plausibly affect that criterion, list one concrete edit. Rank the full list by expected impact × implementation cost. Do not cap the count."* Writes `next_actions.md`. Top-level `status=` field: `continue` | `converged` | `extension_required` | `blocker`.
12. **Input snapshot.** Write `input.json` with all hashes (incl. `manual_review.md` hash), URLs, config/prompt versions, Gemini cost ledger, divergence score.
13. **Index rebuild.** Auto-update `docs/summary_eval/README.md` with new row (shows both Gemini composite and Codex-review composite side-by-side).
14. **Commit.** `git add docs/summary_eval/<source>/iter-<N>/ docs/summary_eval/README.md` and commit `test: <source> iter-<N> score <prev>→<cur>` per CLAUDE.md commit rules.

Any step failure → `status=error` in `next_actions.md` + non-zero exit.

### 8.3 Codex edit cycle (between tuning loops 2, 3, 5, 8)

1. Read `next_actions.md` + `manual_review.md` + `eval.json` + `edit_ledger.json`.
2. **Edit any/all files that might move the score.** Allowed surfaces (wide, unbounded — no file or line cap):
   - `website/features/summarization_engine/summarization/<source>/prompts.py`
   - `website/features/summarization_engine/summarization/<source>/schema.py`
   - `website/features/summarization_engine/summarization/<source>/summarizer.py`
   - `website/features/summarization_engine/summarization/common/` (cross-cutting changes allowed; affects all sources but fine during one source's cycle)
   - `website/features/summarization_engine/source_ingest/<source>/ingest.py`
   - `website/features/summarization_engine/config.yaml`
   - `docs/summary_eval/_config/rubric_<source>.yaml` (rubric-misspecification fixes only; not grading softening)
   - `website/features/summarization_engine/core/orchestrator.py` (ingest-threshold / confidence-gating)
   - `website/features/summarization_engine/core/models.py` (only via `build_summary_result_model` factory)
3. **Reserved off-limits** during iteration loops:
   - `website/features/summarization_engine/evaluator/` — if buggy, Codex opens a dedicated "evaluator fix" commit outside the iteration cycle and bumps `PROMPT_VERSION` in `evaluator/prompts.py` if the fix changed any prompt text.
   - `telegram_bot/**` — entire legacy pipeline off-limits during this program (see non-goals in Section 1).
   - `website/api/routes.py` — the `/api/summarize` and `/api/v2/summarize` route declarations stay stable. Only the summarization engine internals change.
   - `website/features/api_key_switching/` — changes allowed only for the key-role extension in Phase 0; after that, off-limits during iteration loops.
   - `docs/summary_eval/<source>/iter-<N>/manual_review.md` — Codex's output only, written once per iteration during the between-phases Codex step. The CLI NEVER writes or overwrites this file (only reads it in Phase B). The CLI never submits `manual_review.md` content to Gemini. This is the cross-model isolation boundary (§3.7).
4. **Rubric editing constraint.** `docs/summary_eval/_config/rubric_<source>.yaml` may be edited only to fix misspecifications, not to soften grading. Concretely, the following rubric edits are forbidden during iteration:
   - Raising a criterion's `weight` / `max_points` above the research-doc baseline.
   - Lowering the `hallucination_cap` (60), `omission_cap` (75), or `generic_cap` (90) thresholds.
   - Removing a criterion listed in the research doc.
   - Relaxing a `criteria_fired` requirement (e.g., changing "must capture central thesis" to "optionally captures central thesis").
   Allowed: adding clarifying examples to a criterion, fixing typos, splitting an ambiguously-worded criterion into two sharper ones with combined weight equal to the original. Every rubric edit must include a commit message starting with `docs: rubric fix <source>:` and a 1-line rationale.
5. `pytest tests/unit/ -q --ignore=tests/integration_tests`. Fix regressions.
6. Commit with descriptive tags per CLAUDE.md. Multiple commits per loop allowed.
7. `eval_loop.py --source <s> --iter <N+1>`.

### 8.4 Churn protection (the only scope-limit guard)

`edit_ledger.json` tracks every file touched per iteration, intended target criterion, and subsequent criterion movement:

```json
{
  "iter_02": [
    {"file": "summarization/youtube/prompts.py",
     "targeted_criteria": ["rubric.brief.thesis_capture", "g_eval.relevance"],
     "lines_changed": 47,
     "commit": "a3f21b"}
  ],
  "iter_03": [...],
  "churn_flags": {
    "summarization/youtube/prompts.py": {
      "consecutive_edits": 3,
      "targeted_criteria_history": ["rubric.brief.thesis_capture", "rubric.brief.thesis_capture", "rubric.brief.thesis_capture"],
      "criterion_movement": [+0.2, -0.1, +0.05],
      "status": "churning"
    }
  }
}
```

**Churn rule:** a file is flagged `churning` if edited in ≥ 3 consecutive tuning iterations AND the targeted criterion moved by < 1.0 pt (absolute) combined across those iterations.

When flagged:
1. `next_actions.md` prints a `CHURN ALERT` banner.
2. Codex either:
   - **Skips it this loop** (recommended default), OR
   - **Edits it with a new angle** by creating `docs/summary_eval/<source>/iter-<N+1>/new_angle.md` explaining the structural difference (e.g., "previous 3 iters tuned prompt wording; this iter changes prompt structure from single-pass to multi-turn refinement").
3. Without `new_angle.md` on a churning file, CLI refuses to run with `status=churn_unresolved`.
4. Non-churn iteration (file skipped, OR `new_angle.md` present AND criterion moved ≥ 1.0) resets the churn counter.

### 8.5 Guardrails

- **No autonomous code edits by the CLI.** `next_actions.md` proposes, Codex decides.
- **Reserved file list.** CLI refuses if files outside §8.3 allowed surfaces changed between iter-(N-1) and iter-N without `docs/summary_eval/<source>/iter-<N>/override.md`.
- **Determinism check** (step 3 of runbook) — ±2 pt tolerance on re-running prior eval.
- **`.halt` kill switch** — presence of `docs/summary_eval/.halt` causes immediate exit on next CLI invocation.
- **Convergence early-stop** — if §3.8 gate passes at loop 5, CLI writes `status=converged` and skips loops 6/7 unless `--force` given.

### 8.6 Reproducibility contract

`eval_loop.py --source youtube --iter 3 --replay` re-runs the iteration from its `input.json` + cached ingest + commit SHA. Must produce `composite_score` within ±1 pt of original. Enables "is this signal or eval noise" debugging late in the program.

---

## 9. Budget controls & key-role enforcement

### 9.1 Key pool extension

`api_env` format (backward-compatible — untagged lines default to `role=free`):

```
AIzaSy...key1...                 role=free
AIzaSy...key2...                 role=free
AIzaSy...key3...                 role=billing
```

Pool traversal order:
```
Attempt 1:  key1/<model>             [role=free]
Attempt 2:  key2/<model>             [role=free]
Attempt 3:  key1/<downgrade_model>   [role=free]
Attempt 4:  key2/<downgrade_model>   [role=free]
Attempt 5:  key3/<model>             [role=billing]    ← only if all free exhausted
Attempt 6:  key3/<downgrade_model>   [role=billing]
```

Preserves existing free→billing auto-fallback behavior, now role-aware.

### 9.2 Per-phase tier policy

| Phase | Default tier | Downgrade chain | Rationale |
|---|---|---|---|
| CoD densify (summarizer) | pro | → flash → flash-lite | High reasoning for compression |
| Self-check (summarizer) | pro | → flash | NLI-style claim-matching |
| Summary patcher (summarizer) | pro | → flash | Rare trigger |
| Structured extract (summarizer) | flash | → flash-lite | Pure JSON shaping |
| Consolidated evaluator | pro | → flash (logged warning) | Multi-dim rubric scoring |
| RAGAS faithfulness (conditional) | pro | → flash | Per-claim NLI |
| RAGAS AspectCritic | pro | → flash | Independent rubric grading (Gemini-family) |
| Atomic-fact extraction (cached) | flash | → flash-lite | One-shot list |
| Manual review | **Codex (OpenAI)** | n/a — not a Gemini call | Cross-model independence (§3.7); zero Gemini budget |
| Next-actions synthesis | flash | → flash-lite | List generation |
| Newsletter stance detection (Phase 0.5 only) | flash | → flash-lite | One-shot classifier |
| Gemini File API audio transcription | flash | (no downgrade; Flash is the model) | Transcription accuracy |

### 9.3 Atomic-fact cache economics

Without cache: 7 iterations × 3 URLs × 4 sources = 84 Flash extraction calls.
With cache: 3 URLs × 4 sources = 12 Flash extraction calls lifetime. **7× savings + stable keyfact set across iterations.**

### 9.4 Cost ledger

Every `input.json` records:
```json
{
  "gemini_calls": {
    "summarizer": {"pro": {"key1": 2, "key2": 0, "key3": 0}, "flash": {"key1": 1}, "tokens_in": 0, "tokens_out": 0, "est_cost_usd": 0.00},
    "evaluator":  {"pro": {"key1": 1}, "flash": {"key1": 2}, "tokens_in": 0, "tokens_out": 0, "est_cost_usd": 0.00},
    "ragas":      {"pro": {}, "triggered": false},
    "total_cost_usd_billing": 0.00,
    "total_cost_usd_free_quota_used": 0.00
  },
  "role_breakdown": {"free_tier_calls": 6, "billing_calls": 0},
  "quota_exhausted_events": []
}
```

`eval_loop.py --report [--since DATE]` aggregates across all iterations. Warns when any free key exceeds 1400 calls in last 24h (RPD-based heuristic).

### 9.5 Rate-limit backoff

On 429 the pool cycles to next key per existing behavior. On 3rd 429 in a single generate call (all free keys exhausted, billing next), a `quota_exhausted_event` is logged with timestamp, model, phase, and a user-visible message. No pause — silently continues per Q3a.

### 9.6 Total program budget (updated post cross-model isolation)

Manual reviews move to Codex (§3.7) — saves ~50 Gemini Pro calls across the program. Newsletter stance detection (§7.4) adds ~12 Flash calls (3 URLs × 4 Newsletter iters). Net: ~50 fewer Pro calls, ~12 more Flash calls.

| Phase | Pro | Flash | Billing Pro (loop 7) | Est $ billing |
|---|---|---|---|---|
| Phase 0 | 2 | 2 | 0 | $0 |
| Phase 0.5 × 4 majors (incl. newsletter stance) | 80-100 | 52-72 | 0 | $0 |
| Iterations × 4 majors | ~110 | ~110 | 0 | $0 |
| Loop 7 prod-parity × 4 | 0 | 0 | ~50 | ~$0.20–0.50 |
| Polish × 6 (2-3 iters each) | ~45 | ~45 | 0 | $0 |
| ~~Manual reviews~~ (now Codex; zero Gemini cost) | 0 | 0 | 0 | $0 |
| **Free-tier total** | **~235–255** | **~210–230** | — | — |
| **Billing total** | — | — | **~50** | **≈ $0.50 worst case** |

Cross-model isolation is a **net free-tier Pro-quota savings** of ~50 calls, pushing free-tier completion from 2-3 days to ~1.5-2 days.

---

## 10. Acceptance criteria

### 10.1 Per-source "production-grade"

All of:
- Training-URL composite ≥ 92 in ≥ 3 of last 5 tuning iters
- Training-URL RAGAS faithfulness ≥ 0.95 on the loop where composite ≥ 92
- URLs #1, #2, #3 each ≥ 88 composite in loop 5
- Held-out mean ≥ 88 composite, no single held-out URL < 0.95 faithfulness (loop 6)
- Prod-parity delta ≤ 5 points (loop 7)
- No iteration in loops 5-7 triggers the 60-pt hallucination cap
- Rubric label format exact match in 100% of loop-6 held-out runs

Failing criteria → extension loops 8-9. If those fail too, source marked `degraded` in `final_scorecard.md`; program continues.

### 10.2 Program-level "done"

- All 4 major sources reach `production-grade` OR `degraded` with documented root cause
- All 6 polish sources have 2-3 iters with composite ≥ 85 OR are `ingest-blocked`
- `docs/summary_eval/cross_source_lessons.md` written
- Changes on `eval/summary-engine-v2-scoring` feature branch (single long-lived branch throughout the program; no intermediate merges to master). At program end, commits are partitioned into 5 PR branches via targeted cherry-pick:
  - `eval/summary-engine-v2-scoring-phase0-youtube` ← Phase 0 refactor + Phase 0.5 YouTube + YouTube iterations 1-7. **PR 1 merged first** (Phase 0 refactor must land before any source can benefit).
  - `eval/summary-engine-v2-scoring-reddit` ← rebased on master after PR 1 merges. Reddit-only commits. **PR 2.**
  - `eval/summary-engine-v2-scoring-github` ← rebased on master after PR 2 merges. GitHub-only commits. **PR 3.**
  - `eval/summary-engine-v2-scoring-newsletter` ← rebased on master after PR 3 merges. **PR 4.**
  - `eval/summary-engine-v2-scoring-polish` ← rebased on master after PR 4 merges. All 6 polish sources + `cross_source_lessons.md`. **PR 5.**
- This sequential-merge approach triggers 5 production deploys, one per source, each gated on the preceding source's prod verification. No mid-program master-branch commits.
- ~530 existing unit tests pass + new evaluator unit tests pass

---

## 11. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Evaluator drift mid-program (prompt edited, scoring unstable) | Medium | Determinism check per iteration; rubric YAML changes require `override.md` |
| YouTube Fallback 4 (Gemini audio) consumes more billing than estimated | Low | Hard caps: 50MB filesize, 60min duration, lifetime cache; ~$0.50 worst case |
| Per-source Pydantic schemas reject valid LLM output → validation-retry spam | Medium | Soft-coercion via `model_validator`; fallback to default payload with `schema_validation_failed=true` metadata flag |
| Supabase KG compatibility break | Low | On-wire JSON shape preserved; per-source typed fields live inside `sub_sections` dict |
| Pushing to `master` triggers prod deploys | HIGH | **All work on `eval/summary-engine-v2-scoring` branch**; per-major-source PRs at end |
| Telegram bot keeps using legacy `telegram_bot/` pipeline | Out of scope | Logged as follow-up in `cross_source_lessons.md`: "migrate bot capture to v2 `summarize_url`" |
| Free-tier quota exhaustion stalls progress | Medium | Daily `--report` flags at 1400 calls/key; billing auto-fallback already configured |
| Gemini model deprecation mid-program | Low | `config.yaml → gemini.model_chains` is already the fallback vector |
| YouTube `yt-dlp` itself blocked on DO IP (audio CDN too) | Very low | All 5 tiers independently-failing; worst case = metadata-only summary with capped confidence |
| Piped/Invidious pools all down during a run | Low-medium | Two pools × 14 instances + health cache; even 50% dead rate leaves ~7 live. Fallback 4 (audio transcription) always works. |
| Codex applies too many simultaneous edits in a single tuning iter, breaking unit tests | Medium | Required pytest green gate in §8.3 step 4 before CLI re-invocation |
| Codex skips or rushes the manual-review step, violating cross-model isolation | Medium | Blind-review hash stamp (§3.7); divergence tracking across iterations exposes lazy reviews (always agreeing ≈ not independent); after 3 consecutive AGREEMENT stamps with score diff < 1 pt, CLI emits `status=possibly_cursory_review` for Codex to consciously re-engage |
| Codex manual review unavailable due to Codex session restart mid-iteration | Low | File-based handoff means Codex can resume from the existing `manual_review_prompt.md` after any session restart; no in-memory state |
| Cross-model disagreement (Gemini vs Codex) becomes systematic, suggesting one evaluator is broken | Low-Medium | `disagreement_analysis.md` soft-gate after 2 consecutive MAJOR_DISAGREEMENTs; pessimistic score rule (lower of the two wins) means disagreements never inflate the measured score |

---

## 12. Open follow-ups after program end

Recorded for future sessions; not blocking this program's completion:

1. Migrate `telegram_bot/` capture handler to use v2 `summarize_url` so Telegram captures benefit from rubric-tuned summaries.
2. Backfill existing Supabase KG nodes via `summarize_url` — re-summarize historical captures that were written by the legacy pipeline pre-optimization.
3. Promote the evaluator module to a standalone package under `website/features/evaluation/` so it can be reused for RAG answer evaluation + chat response evaluation.
4. Consider adding real HuggingFace SummaC + QAFactEval as final-validation-only checks at the end of the polish phase — low-volume, confidence-of-results boost.
5. Productize the eval loop as an HTTP endpoint (`POST /api/v2/eval`) so prod can self-monitor summary quality on sampled daily captures.

---

## 13. Summary of commitments

- **Engine refactor** lands in Phase 0: per-source classes, config-driven caps, three-layer cache, scaffolded evaluator + CLI.
- **Per-source Phase 0.5** resolves ingest blockers — YouTube gets a 5-tier free-only transcript chain; Reddit/GitHub/Newsletter get smaller targeted fixes (GitHub root-dir scan for benchmarks/tests/examples; Newsletter stance detection + branded-sources list).
- **Iteration cycle**: loops 1, 4, 6, 7 are measurement; loops 2, 3, 5 are tuning (Codex edits wide, churn protection the only scope guard); loops 8, 9 are auto-triggered extensions. Every iteration has a two-phase CLI invocation with Codex's manual review in between (§3.7, §8.2).
- **Cross-model isolation**: Gemini Pro does the standard evaluation; Codex (OpenAI model) does the manual review. File-based handoff, blind-review hash stamp, pessimistic score-of-two-models rule. Less bias, zero extra cost.
- **Criteria2 integration**: every rubric criterion now maps to one or more academic metrics (G-Eval / FineSurE / QAFactEval / SummaC); `maps_to_metric_summary` in eval.json aggregates per-metric scores. Per-source `anti_patterns` concretize the hallucination cap. Editorialization checks block stance injection. GitHub/YouTube/Newsletter schemas enriched with criteria2-driven fields.
- **Multi-URL coverage** baked into loop 5 (joint tune on URLs #1+#2+#3) and loop 6 (held-out validation).
- **Artifact root**: `docs/summary_eval/` — permanent, content-hashed caches, per-iteration folders (now 7 files: summary, eval, manual_review, manual_review_prompt, diff, next_actions, input), per-source + cross-source scorecards.
- **Budget**: ~235-255 Pro + ~210-230 Flash across free keys (reduced from earlier estimate via cross-model isolation); ~$0.50 worst-case billing. Free auto-fallback to billing on quota exhaustion, visible in `--report` output.
- **Branch**: `eval/summary-engine-v2-scoring` (single long-lived). At program end, 5 cherry-pick PR branches against `master` (Phase 0 + YouTube → Reddit → GitHub → Newsletter → Polish). Sequential-merge, each PR gated on the prior's prod verification.
- **Target**: 4 major sources `production-grade`, 6 polish sources ≥ 85 composite, all before merge.
