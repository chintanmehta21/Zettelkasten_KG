# Improvement notes — psychedelic-drugs iter-1

- composite (legacy weights): 34.764583333333334
- gold@1 unconditional: 0.0
- accuracy_user_visible: 0.0
- over_refusal_rate: 0.0
- under_refusal_rate: 0.0

## Next-iter levers (auto-suggested)

- Composite below the iter-11 legacy bar (60.26): inspect per-stage component scores in scores.md; the lowest stage is the iteration target.
- gold@1 < 0.6: check failure_analysis.md gold-primary misses — retrieval-miss (gold not retrieved) vs rerank-miss (retrieved but not top-1) need different fixes.

_Operator fills concrete decisions here before the next iter._
