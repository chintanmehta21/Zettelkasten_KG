# PageIndex iter-05 vs iter-04

Important scope note: iter-05 intentionally runs on the new Naruto `urban-climate-resilience` Kasten, while iter-04 ran on `knowledge-management`. This table is a cross-Kasten comparison, not an apples-to-apples content comparison. PageIndex iter-06 and later should compare against this iter-05 fixture for apples-to-apples tracking.

| Metric | iter-04 Knowledge Management | iter-05 Urban Climate | Delta |
|---|---:|---:|---:|
| Total queries | 14 | 14 | +0 |
| Gold@1 | 0.9286 | 1.0000 | +0.0714 |
| Infra failures | 0 | 0 | +0 |
| Recall@5 | 0.8905 | 0.8929 | +0.0024 |
| MRR | 0.9286 | 0.9286 | +0.0000 |
| NDCG@5 | 0.9686 | 0.9665 | -0.0022 |
| p50 latency ms | 15736 | 22960 | +7223 |
| p95 latency ms | 47346 | 41398 | -5948 |
| p95 under 30s | false | false | same |
| RAGAS proxy | 0.8752 | 0.9200 | +0.0448 |
| Overall strength | 0.5775 | 0.8610 | +0.2835 |
| Faithfulness proxy | 0.9714 | 1.0000 | +0.0286 |
| Coverage | 0.2157 | 0.7508 | +0.5352 |
| Answer correctness proxy | 0.2044 | 0.7508 | +0.5464 |
| Citation grounding | 0.9286 | 1.0000 | +0.0714 |
| Answer relevancy proxy | 0.6703 | 0.8207 | +0.1504 |

Iter-05 verdict: no infra failures, all 14 queries gold@1, and materially stronger final-answer metrics on the new Kasten.
