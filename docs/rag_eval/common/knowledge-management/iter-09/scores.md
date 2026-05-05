# 06 Scorecard

**Composite:** 65.32  (weights={'chunking': 0.1, 'retrieval': 0.25, 'reranking': 0.2, 'synthesis': 0.45}, hash=422403f9d47a)

## Components
- chunking:    40.43
- retrieval:   97.08
- reranking:   57.14
- synthesis:   56.85

## RAGAS sidecar (0..100)
- faithfulness:      87.50
- answer_relevancy:  74.29

## Latency
- p50: 34260 ms
- p95: 41067 ms

## Coverage
- total queries:        14
- refusal-expected:     1
- eval_divergence:      False

## Holistic monitoring (iter-04)
- gold@1: 0.5714    gold@3: 0.6429    gold@8: 0.7857
- within_budget_rate: 0.0714
- refused_count: 3

### critic_verdict distribution
- partial: 5
- supported: 4
- unsupported_no_retry: 3
- unsupported_with_gold_skip: 1
- unknown: 1

### query_class distribution
- lookup: 6
- thematic: 4
- multi_hop: 3
- unknown: 1

### magnet-spotter (>=25% top-1 share)
- ⚠️ gh-zk-org-zk: top-1 in 3/14 queries

### burst pressure
- by_status: {'503': 6, '502': 3, '200': 3}
- 503 rate (target ≥0.08): 0.5
- 502 rate (target 0.0):  0.25

## Per-query (RAGAS overall is dataset-level)

| qid | retrieval | rerank | gold_in_retrieved | cites |
|---|---:|---:|:-:|---:|
| q1 | 84.3 | 0.0 | ✓ | 6 |
| q2 | 100.0 | 100.0 | ✓ | 1 |
| q3 | 140.0 | 100.0 | ✓ | 1 |
| q4 | 80.0 | 80.7 | ✓ | 1 |
| q5 | 84.0 | 40.9 | ✓ | 4 |
| q6 | 73.3 | 73.5 | — | 0 |
| q7 | 0.0 | 0.0 | — | 0 |
| q8 | 80.0 | 41.7 | ✓ | 4 |
| q9 | 100.0 | 100.0 | — | 0 |
| q10 | 0.0 | 0.0 | — | 0 |
| q11 | 140.0 | 100.0 | ✓ | 1 |
| q12 | 117.5 | 21.5 | ✓ | 4 |
| q13 | 140.0 | 66.7 | ✓ | 4 |
| q14 | 220.0 | 75.0 | ✓ | 2 |
