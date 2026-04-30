# iter-06 — Knowledge Management Kasten eval

**Scope:** Validate the iter-05 deep-dive's burst-pressure fix + log-cleanup. Content failures (q5/q7/q10/q2/q3) are documented but NOT yet patched in this iter — they require code changes that need separate review.

## What changed vs iter-05

| Layer | Change | File:line |
|---|---|---|
| Admission control | `RAG_QUEUE_MAX: 8 → 3` (per worker; cluster cap 6) | [`ops/docker-compose.blue.yml:15`](../../../../../ops/docker-compose.blue.yml), [`ops/docker-compose.green.yml:15`](../../../../../ops/docker-compose.green.yml) |
| Env template | Documented `RAG_QUEUE_MAX` + `RAG_RERANK_CONCURRENCY` | [`ops/.env.example`](../../../../../ops/.env.example) |
| Eval scoring logs | Suppressed `httpx`/`google.*`/`supabase`/`key_pool` chatter; expanded summary to one line with p50/p95/gold@k/within_budget/refused/verdict-split/burst | [`ops/scripts/score_rag_eval.py`](../../../../../ops/scripts/score_rag_eval.py) |
| Queries | Identical to iter-05 — validates fixes don't regress content quality | [`queries.json`](queries.json) |

## Expected results

| Phase | iter-05 actual | iter-06 target |
|---|---|---|
| `burst_pressure` | `{200:1, 524:11}`, **0× 503**, target failed | `{200:N, 503:M}`, **≥1× 503 with Retry-After**, **0× 524**, target passed |
| `rag_qa_chain` end-to-end gold@1 | 0.7857 | ≥ 0.7857 (unchanged — content fixes deferred) |
| `infra_failures` | 0 | 0 |
| Final scoring log | Multi-line, third-party chatter | Single-line: `composite=… faithfulness=… answer_relevancy=… p50=… p95=… gold@1=… gold@3=… gold@8=… within_budget=… refused=N/M verdict=supported:S/partial:P/unsupported:U burst=…` |

## Deferred content fixes (next iters)

Tracked in the iter-05 deep-dive Top-K table:

| qid | Failure | Proposed fix | Risk |
|---|---|---|:-:|
| q5 | thematic recall (3 of 5 expected sources missed) | bump `_multi_query` n=3 → n=5; lower `_DIVERSITY_FLOOR_SCORE_MIN` 0.05 → 0.02 (or scale by Kasten size) | M |
| q7 | vague single-token query refused | add deterministic VAGUE override in `apply_class_overrides` for queries with ≤4 content words and no synthesis pattern | S |
| q10 | Steve Jobs zettel not surfaced under ≥2-person LOOKUP override | raise anti-magnet penalty floor `max(0.5, raw)` → `max(0.7, raw)` so legitimate magnet queries still see the magnet | S |
| q2/q3 | over-literal token-presence refusal | replace literal-presence gate with critic semantic-coverage re-check | M |

## Run command

Bash (local):

```bash
cd /c/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault
python ops/scripts/eval_iter_03_playwright.py --iter iter-06
```

PowerShell (Windows native):

```powershell
cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault
python ops\scripts\eval_iter_03_playwright.py --iter iter-06
```

## Pre-flight checklist

- [ ] Compose change merged + deployed (so the active color picks up `RAG_QUEUE_MAX=3`).
- [ ] On droplet, after deploy: `docker exec zettelkasten-blue env | grep RAG_QUEUE_MAX` shows `3`.
- [ ] Caddy upstream still has its 240s read_timeout (guardrail unchanged).
- [ ] No purple anywhere; amber confined to `/knowledge-graph` (color-audit phase).
