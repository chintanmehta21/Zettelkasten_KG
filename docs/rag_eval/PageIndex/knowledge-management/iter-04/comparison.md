# PageIndex KM iter-04 vs iter-03

Iter-04 uses the same 14 Common KM query bodies, the same 7 zettels, and the same deterministic answer-strength metrics as iter-03. The run was executed with only the third Gemini key loaded into the process.

| Metric | iter-03 | iter-04 | Delta |
|---|---:|---:|---:|
| Gold@1 | 0.9286 | 0.9286 | +0.0000 |
| Infra failures | 0 | 0 | +0 |
| Recall@5 | 0.8905 | 0.8905 | +0.0000 |
| MRR | 0.9286 | 0.9286 | +0.0000 |
| NDCG@5 | 0.9686 | 0.9686 | +0.0000 |
| p50 latency ms | 13468 | 15736 | +2268 |
| p95 latency ms | 25460 | 47346 | +21885 |
| RAGAS proxy | 0.8335 | 0.8752 | +0.0417 |
| Overall strength | 0.4289 | 0.5775 | +0.1486 |
| Faithfulness proxy | 0.8000 | 0.9714 | +0.1714 |
| Coverage | 0.1454 | 0.2157 | +0.0703 |
| Answer correctness proxy | 0.0813 | 0.2044 | +0.1231 |
| Citation grounding | 0.5000 | 0.9286 | +0.4286 |
| Answer relevancy proxy | 0.6750 | 0.6703 | -0.0048 |

Gate result: pass. Coverage and answer correctness both improved over iter-03.
