# 05 Scorecard

**Composite:** 77.95  (weights={'chunking': 0.1, 'retrieval': 0.25, 'reranking': 0.2, 'synthesis': 0.45}, hash=422403f9d47a)

## Components
- chunking:    31.94
- retrieval:   97.70
- reranking:   77.86
- synthesis:   77.25

## RAGAS sidecar (0..100)
- faithfulness:      100.00
- answer_relevancy:  96.43

## Latency
- p50: 57033 ms
- p95: 76328 ms

## Coverage
- total queries:        14
- refusal-expected:     1
- eval_divergence:      False

## Holistic monitoring (iter-04)
- gold@1: 0.6429    gold@3: 0.6429    gold@8: 0.7857
- within_budget_rate: 0.1429
- refused_count: 2

### critic_verdict distribution
- partial: 5
- supported: 5
- unsupported_no_retry: 4

### query_class distribution
- lookup: 7
- thematic: 5
- multi_hop: 2

### magnet-spotter (>=25% top-1 share)
- ⚠️ yt-programming-workflow-is: top-1 in 3/14 queries
- ⚠️ web-transformative-tools-for: top-1 in 3/14 queries

### burst pressure
- by_status: {'524': 11, '200': 1}
- 503 rate (target ≥0.08): 0.0
- 502 rate (target 0.0):  0.0

## Per-query (RAGAS overall is dataset-level)

| qid | retrieval | rerank | gold_in_retrieved | cites |
|---|---:|---:|:-:|---:|
| q1 | 140.0 | 114.9 | ✓ | 4 |
| q2 | 100.0 | 100.0 | ✓ | 1 |
| q3 | 220.0 | 178.1 | ✓ | 1 |
| q4 | 80.0 | 80.7 | ✓ | 1 |
| q5 | 92.0 | 93.4 | ✓ | 4 |
| q6 | 73.3 | 73.5 | ✓ | 1 |
| q7 | 0.0 | 0.0 | ✓ | 4 |
| q8 | 77.5 | 21.5 | ✓ | 5 |
| q9 | 0.0 | 0.0 | ✓ | 5 |
| q10 | 0.0 | 0.0 | ✓ | 1 |
| q11 | 180.0 | 156.5 | ✓ | 1 |
| q12 | 85.0 | 0.0 | ✓ | 5 |
| q13 | 180.0 | 156.5 | ✓ | 1 |
| q14 | 140.0 | 114.9 | ✓ | 4 |
