# YouTube iter-06 vs PageIndex iter-02 Answer Strength

YouTube iter-06 did not persist structured RAGAS/DeepEval JSON; the available answer-strength signal is the scorecard synthesis estimate and per-query citation/rerank notes. PageIndex iter-02 now persists deterministic no-external-judge proxies so future runs can compare final-answer strength without extra infra.

| metric | YouTube iter-06 available signal | PageIndex iter-02 |
|---|---:|---:|
| external RAGAS judge run | not run | not run |
| RAGAS-style proxy score | n/a | 0.817 |
| overall answer strength | ~0.920 synthesis estimate | 0.395 |
| faithfulness | described as faithful/full citations on 4 successful answers | 0.771 |
| final-answer coverage | substantive 600-1700 char successful answers; no separate score | 0.115 |
| answer correctness proxy | n/a | 0.067 |
| citation grounding | 4/4 successful answers cited gold | 0.429 |
| context recall | 1.000 successful / 0.667 infra-counted | 0.890 |
| context precision | ~0.950 rerank estimate | 0.969 |

Important: the PageIndex RAGAS-style number is a deterministic proxy, not an external RAGAS judge score. It is intentionally local-only to avoid judge/API overhead.
