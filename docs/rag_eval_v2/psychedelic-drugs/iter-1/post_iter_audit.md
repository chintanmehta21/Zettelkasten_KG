# Post-iter audit report

## 1. Scores summary

- **Composite:** 34.76
- **within_budget_rate:** 1.0000

## 2. Per-stage runtime + memory

_No per-stage timing in verification_results.json — check Class P log artifact._

## 3. Failed gold@1 queries (0 total)

_None._
## 4. Monitor status (Tasks 14, 25, 30, 31, 35)

- **Task 14 — accuracy_user_visible (Class S):** MISSING — Class S not surfaced in scores.md
- **Task 25 — primary_citation headline (I9):** MISSING — I9 retrieval_recall split not in scores.md
- **Task 30 — coverage_blind audit (R3 Tier-1):** NOT RUN — operator must invoke audit_gold_expectations.py
- **Task 31 — anchor_seed_bandit telemetry (R4):** OK if log line `anchor_seed_bandit qid=...` present in droplet logs (manual check)
- **Task 35 — retry_outcome_class + per-stage timing (R1):** MISSING — verify orchestrator emits the log line and verification_results includes the field

## 5. Live env-during-eval monitor (user-mandated)

**Source:** gh workflow run 25994385232 log

| knob | expected | actual | MATCH |
|---|---|---|:---:|
| `RAG_ANCHOR_BOOST_ENABLED` | `true` | `true` | ✓ |
| `RAG_ANCHOR_SEED_INJECTION_ENABLED` | `true` | `true` | ✓ |
| `RAG_EXECUTOR_MAX_WORKERS` | `8` | `8` | ✓ |
| `RAG_RPC_GLOBAL_SEMAPHORE` | `8` | `8` | ✓ |
| `RAG_HTTPX_MAX_CONNECTIONS` | `16` | `16` | ✓ |
| `RAG_HTTPX_MAX_KEEPALIVE` | `8` | `8` | ✓ |
| `RAG_ENTITY_GATHER_SEMAPHORE` | `3` | `3` | ✓ |
| `RAG_SCORE_RANK_GAP_BYPASS` | `1.5` | `1.5` | ✓ |
| `RAG_RETRY_GAP_BYPASS` | `1.5` | `1.5` | ✓ |
| `RAG_TITLE_OVERLAP_PERCENTILE` | `75` | `75` | ✓ |
| `RAG_TITLE_OVERLAP_FLOOR_FALLBACK` | `0.10` | `0.10` | ✓ |
| `RAG_ROUTER_VERSION` | `v4` | `v4` | ✓ |
| `RAG_SCORE_RANK_DEMOTE_SLOPE` | `0.20` | `0.20` | ✓ |
| `RAG_ANCHOR_BANDIT_ENABLED` | `true` | `true` | ✓ |

_All expected knobs matched. Live env verified._
