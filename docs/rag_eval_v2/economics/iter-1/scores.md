# iter-1 Scorecard

**Composite:** 40.97  (weights={'chunking': 0.1, 'retrieval': 0.25, 'reranking': 0.2, 'synthesis': 0.45}, hash=c2d3783e5c0b)

## Components
- chunking:    20.00
- retrieval:   25.00
- reranking:   35.56
- synthesis:   56.92

## RAGAS sidecar (0..100)
- faithfulness:      92.50
- answer_relevancy:  87.50

## Latency
- p50: 2804 ms
- p95: 8808 ms

## Coverage
- total queries:        12
- refusal-expected:     1
- eval_divergence:      False

## Holistic monitoring (iter-04)
- gold@1 (unconditional):  0.3333
- gold@1 within budget:    0.3333
- gold@1 not applicable:   6 (refusal-expected)
- gold@3: 0.3333    gold@8: 0.3333
- within_budget_rate: 1.0
- refused_count: 0

### critic_verdict distribution
- supported: 12

### query_class distribution
- lookup: 5
- multi_hop: 5
- thematic: 1
- vague: 1

### magnet-spotter (>= 0.25 (static fallback, n<20))
- (none — magnet bias under threshold)

## Per-query (RAGAS overall is dataset-level)

| qid | retrieval | rerank | gold_in_retrieved | cites |
|---|---:|---:|:-:|---:|
| q1 | 0.0 | 20.0 | — | 0 |
| q2 | 0.0 | 20.0 | — | 0 |
| q3 | 0.0 | 20.0 | — | 0 |
| q4 | 100.0 | 66.7 | ✓ | 4 |
| q5 | 0.0 | 20.0 | — | 0 |
| q6 | 0.0 | 20.0 | — | 0 |
| q7 | 0.0 | 20.0 | — | 0 |
| q8 | 0.0 | 20.0 | — | 0 |
| q9 | 0.0 | 0.0 | ✓ | 1 |
| q10 | 0.0 | 20.0 | — | 0 |
| q11 | 100.0 | 100.0 | — | 0 |
| q12 | 100.0 | 100.0 | ✓ | 1 |
