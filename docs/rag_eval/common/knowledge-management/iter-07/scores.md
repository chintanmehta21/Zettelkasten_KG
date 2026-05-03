# 06 Scorecard

**Composite:** 62.88  (weights={'chunking': 0.1, 'retrieval': 0.25, 'reranking': 0.2, 'synthesis': 0.45}, hash=422403f9d47a)

## Components
- chunking:    31.94
- retrieval:   78.51
- reranking:   62.48
- synthesis:   61.26

## RAGAS sidecar (0..100)
- faithfulness:      82.14
- answer_relevancy:  82.14

## Latency
- p50: 36142 ms
- p95: 55901 ms

## Coverage
- total queries:        14
- refusal-expected:     1
- eval_divergence:      False

## Holistic monitoring (iter-04)
- gold@1: 0.4286    gold@3: 0.5714    gold@8: 0.7143
- within_budget_rate: 0.2857
- refused_count: 1

### critic_verdict distribution
- partial: 6
- unsupported_no_retry: 3
- supported: 3
- unknown: 2

### query_class distribution
- lookup: 5
- thematic: 5
- multi_hop: 2
- unknown: 2

### magnet-spotter (>=25% top-1 share)
- ⚠️ gh-zk-org-zk: top-1 in 3/14 queries
- ⚠️ yt-effective-public-speakin: top-1 in 3/14 queries

### burst pressure
- by_status: {'402': 12}
- 503 rate (target ≥0.08): 0.0
- 502 rate (target 0.0):  0.0

## Per-query (RAGAS overall is dataset-level)

| qid | retrieval | rerank | gold_in_retrieved | cites |
|---|---:|---:|:-:|---:|
| q1 | 44.3 | 0.0 | ✓ | 6 |
| q2 | 100.0 | 100.0 | ✓ | 1 |
| q3 | 220.0 | 178.1 | ✓ | 1 |
| q4 | 80.0 | 80.7 | ✓ | 1 |
| q5 | 84.0 | 86.1 | ✓ | 3 |
| q6 | 113.3 | 109.1 | ✓ | 3 |
| q7 | 80.0 | 41.7 | ✓ | 4 |
| q8 | 80.0 | 41.7 | ✓ | 4 |
| q9 | 0.0 | 0.0 | ✓ | 5 |
| q10 | 0.0 | 0.0 | ✓ | 1 |
| q11 | 180.0 | 156.5 | ✓ | 1 |
| q12 | 117.5 | 40.9 | ✓ | 3 |
| q13 | 0.0 | 20.0 | — | 0 |
| q14 | 0.0 | 20.0 | — | 0 |
