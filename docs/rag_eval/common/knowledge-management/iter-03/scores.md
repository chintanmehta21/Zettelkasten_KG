# 03 Scorecard

**Composite:** 70.93  (weights={'chunking': 0.1, 'retrieval': 0.25, 'reranking': 0.2, 'synthesis': 0.45}, hash=422403f9d47a)

## Components
- chunking:    31.94
- retrieval:   91.89
- reranking:   63.19
- synthesis:   71.38

## RAGAS sidecar (0..100)
- faithfulness:      86.92
- answer_relevancy:  76.92

## Latency
- p50: 50419 ms
- p95: 86769 ms

## Coverage
- total queries:        13
- refusal-expected:     1
- eval_divergence:      False

## Holistic monitoring (iter-04)
- gold@1: 0.3846    gold@3: 0.6154    gold@8: 0.8462
- within_budget_rate: 0.1538
- refused_count: 1

### critic_verdict distribution
- partial: 7
- supported: 5
- retried_supported: 1

### query_class distribution
- multi_hop: 5
- thematic: 4
- lookup: 3
- step_back: 1

### magnet-spotter (>=25% top-1 share)
- ⚠️ gh-zk-org-zk: top-1 in 7/13 queries

### burst pressure
- by_status: {'502': 12}
- 503 rate (target ≥0.08): 0.0
- 502 rate (target 0.0):  1.0

## Per-query (RAGAS overall is dataset-level)

| qid | retrieval | rerank | gold_in_retrieved | cites |
|---|---:|---:|:-:|---:|
| q1 | 44.3 | 0.0 | ✓ | 6 |
| q2 | 140.0 | 131.5 | ✓ | 1 |
| q3 | 220.0 | 178.1 | ✓ | 3 |
| q4 | 100.0 | 32.0 | ✓ | 7 |
| q5 | 64.0 | 39.0 | ✓ | 3 |
| q6 | 140.0 | 110.1 | ✓ | 5 |
| q7 | 117.5 | 40.9 | ✓ | 5 |
| q8 | 100.0 | 100.0 | ✓ | 1 |
| q9 | 0.0 | 0.0 | ✓ | 4 |
| q10 | 0.0 | 0.0 | ✓ | 3 |
| av-1 | 125.0 | 89.9 | ✓ | 5 |
| av-2 | 100.0 | 100.0 | ✓ | 1 |
| av-3 | 43.8 | 0.0 | ✓ | 6 |
