# Reddit Brief Scorecard (Reddit #5)

Scorecard template for evaluating the **brief** field of a Reddit summary.
Pairs with `rubric_reddit.yaml` (`brief_summary` component) and
`reddit_cluster_rebalance.yaml` (multi-cluster trigger thresholds).
Evaluators fill out one scorecard per Reddit fixture.

---

## 1. Sentence-Count Contract

The brief MUST be **5–7 sentences**. Hard rules:

| Sentence count | Action |
|----------------|--------|
| `< 5`          | **Hard fail.** Composite forced to `0`. Do not score remaining sections. |
| `5`            | Pass. No deduction. |
| `6`            | Pass. No deduction. Preferred when caveat sentence is required. |
| `7`            | Pass. No deduction. Use only when open question adds real signal. |
| `> 7`          | Soft fail. Cap composite at `70`. |

Sentence boundary is detected on `.`, `?`, `!` followed by whitespace or EOS.
Quoted sentences inside one logical statement count as one.

## 2. Required Sentence Types (in order)

Brief sentences must appear in this canonical order. Out-of-order sequences
incur a `-10` deduction per displaced sentence.

| # | Type               | Required? | Description |
|---|--------------------|-----------|-------------|
| 1 | OP intent          | Always    | Neutral restatement of OP's question, claim, or situation. |
| 2 | Dominant pattern   | Always    | The plurality response cluster. |
| 3 | Dissent            | If present in thread | Substantively different counter-position. |
| 4 | Consensus          | Always    | Where commenters agree (or explicit "no consensus reached"). |
| 5 | Caveat             | Conditional (see §3) | Moderation, regional, legal, or risk caveat. |
| 6 | Open question      | Optional  | Genuinely unresolved question worth surfacing. |

If dissent is genuinely absent, sentence 3 is omitted and sentence 4 shifts up.
Score the remaining sentences against their canonical position.

## 3. Moderation-Context Rule

If `moderation_divergence_pct > 20`, the **caveat sentence is required**
and must explicitly mention removed/missing comments or moderator action.

| Condition                                    | Penalty |
|----------------------------------------------|---------|
| Divergence > 20% AND caveat present + correct| `0`     |
| Divergence > 20% AND caveat missing          | `-15`   |
| Divergence > 20% AND caveat present but vague| `-8`    |
| Divergence > 40% AND caveat missing          | Cap composite at `60`. |

"Vague" = mentions moderation but does not quantify or qualify the divergence.

## 4. Per-Sentence Rubric (0–4)

Each sentence is scored on three axes. Sum is the per-sentence subtotal (max 12).

| Axis                  | 0                                | 2                              | 4                                       |
|-----------------------|----------------------------------|--------------------------------|-----------------------------------------|
| Thesis clarity        | Unclear, multi-claim, rambling   | One main claim, slightly fuzzy | Single, crisp, evaluable thesis         |
| Hedged attribution    | Bare assertion of comment claim  | Partial hedge ("some say")     | Explicit attribution ("commenters argue", "OP reports") |
| Source grounding      | No traceable source in thread    | Loose paraphrase of thread     | Directly traceable to OP / specific comment cluster |

## 5. Anti-Patterns (Score Caps)

These cap the composite regardless of per-sentence scores.

| Anti-pattern                                          | Cap |
|-------------------------------------------------------|-----|
| Placeholder speakers ("a user said", "someone wrote") | `65` |
| Unhedged commenter claims as fact                     | `60` |
| Missing moderation caveat when required (§3)          | `65` |
| Editorialized stance not present in thread            | `55` |
| Dominant cluster mislabeled as consensus              | `60` |
| Joke/meme content elevated as substantive response    | `70` |
| Fabricated external reference                         | `50` |

The lowest applicable cap wins.

## 6. Composite Scoring Formula

```
per_sentence_total   = sum(per_sentence_subtotals)             # max = 12 * sentence_count
sentence_quality_pct = per_sentence_total / (12 * sentence_count)

base_score   = 100 * sentence_quality_pct
adjusted     = base_score
             + structure_bonus          # +0 if §2 order followed, else negative
             - moderation_penalty       # from §3
composite    = min(adjusted, lowest_anti_pattern_cap)
composite    = 0 if hard_fail else composite
```

Where:
- `structure_bonus` ∈ `{0, -10, -20, -30}` based on displaced sentences.
- `moderation_penalty` ∈ `{0, 8, 15}` per §3.
- `lowest_anti_pattern_cap` defaults to `100` if no anti-pattern hits.

## 7. Output Schema

Each scored fixture writes one JSON record to `_cache/reddit_brief_scores/<fixture_id>.json`:

```json
{
  "fixture_id": "askhistorians_first_person_001",
  "sentence_count": 6,
  "hard_fail": false,
  "sentence_order_correct": true,
  "moderation_required": true,
  "moderation_caveat_present": true,
  "per_sentence_scores": [
    {"index": 1, "type": "op_intent", "thesis": 4, "hedge": 4, "grounding": 4},
    {"index": 2, "type": "dominant_pattern", "thesis": 3, "hedge": 4, "grounding": 4}
  ],
  "anti_patterns_hit": [],
  "composite": 92
}
```
