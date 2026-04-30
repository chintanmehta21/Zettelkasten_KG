# PageIndex iter-02 vs Common KM Baseline

Apples-to-apples fields use the same 14 query bodies and the same 7-node Naruto Knowledge Management Kasten.

| metric | Common KM baseline | PageIndex KM iter-02 |
|---|---:|---:|
| total queries | 14 | 14 |
| end-to-end gold@1 | 0.6429 | 0.9286 |
| infra failures | 4 | 0 |
| p95 latency ms | 58138 | 46169.0 |
| p95 under 30s | False | False |

Infra failures remain in the denominator for both systems.
