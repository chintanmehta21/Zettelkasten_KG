# iter-03 — Handoff to Next Agent (2026-04-29)

> Iter-03 is **NOT shipped**. Deploys land successfully through stage2 + cgroup
> assertions but the [rag-smoke] gate keeps failing because q1 (multi-hop
> 2-fact lookup) OOMs the worker. This handoff captures everything done so far
> + the exact remaining steps to ship.

## Branch state

- Branch: `master` (commits 909abe3 → 7fcaaa0; 14 commits since 2260ea1)
- Live: blue serving caddy traffic on caaad53 (smoke-WARN-skipped, pre-self-mint)
- Latest deploy: 7fcaaa0 (in flight at handoff time — push 17:59 UTC ish)
- ALL iter-03 plan/spec are committed; current iter-03 dir has NO Q-A scoring

## What's done

| Phase | Status | Commits |
|---|---|---|
| 0 Pre-flight | ✓ | 909abe3 archive iter-03 → iter-03-stale, fresh dir, lfs verified |
| 1 Model artifacts | ✓ | eadf4a0 (267 MB int8 onnx + parquet via LFS, 17 MB tokenizer plain, FlashRank dir, baseline.json with sha256s) |
| 2 Dockerfile bake | ✓ | 298baad (COPY models/ /app/models/) |
| 3 Compose mounts | ✓ | 050bc17 (removed /app/models mount, added /app/runtime mount) |
| 4 cascade.py refactor | ✓ | d98d4c8 (rip lazy fp32, decouple DegradationLogger to /app/runtime, eager _STAGE2_TOKENIZER) |
| 5 Workflow LFS + smoke env | ✓ | 4fce4c2 (lfs:true on build checkout) |
| 6 deploy.sh stage2/smoke gates | ✓ | 2fa97f1 (exit 88/89, fail-loud-no-rollback) |
| 7 Drift cron | ✓ | 02b6cac (check_corpus_drift.py, refresh_calibration_and_int8.py, weekly cron + auto-PR workflow) |
| 8 Droplet cleanup | ✓ | operator (rm __MACOSX, mkdir /opt/zettelkasten/data/runtime owned by uid 1000) |
| 9 Local validate | ✓ | 1443+5 stress tests pass; lint/yaml/bash all green |
| 10 RAG_SMOKE_TOKEN secret | ✓ → REPLACED | First static GH secret (expired in 1h causing all deploys to fail). Replaced with self-mint via NARUTO_SMOKE_PASSWORD + SUPABASE_ANON_KEY_LEGACY_JWT secrets in e2f58eb |
| **11 Push + deploy + watch** | **partial** | 24c48fa, e2f58eb, cdc688a, 01dcb61, 830d053, 2e36dd5, 7fcaaa0 — smoke probe blocking caddy flip |
| **12 Playwright eval** | **NOT STARTED** | depends on Phase 11 success |
| **13 Squash + 24h obs** | NOT STARTED | post-eval |

## Critical bug fixes landed during iter-03

| # | Bug | Fix commit | What |
|---|---|---|---|
| A | `'GeminiKeyPool' object has no attribute 'generate_structured'` | included in 7fcaaa0 chain | Added method to `website/features/api_key_switching/key_pool.py` (wraps generate_content with response_mime_type+schema). Was causing query metadata A-pass to fail and degrade to slower C-pass on every query — increased Gemini retry pressure → memory pressure. Tests in `tests/unit/api_key_switching/test_generate_structured.py`. |
| B | `hybrid_kg_search RPC failed: Object of type UUID is not JSON serializable` | 830d053 | Coerce UUID args to str at RPC boundary in `website/features/kg_features/retrieval.py`. Was causing all hybrid retrievals to fail on every query. Tests in `tests/unit/rag/retrieval/test_hybrid_uuid_serialization.py`. |
| C | Static `RAG_SMOKE_TOKEN` GH secret expires after 1h | e2f58eb | deploy.sh now mints fresh JWT inline every deploy via Supabase password grant. New GH secrets: `NARUTO_SMOKE_PASSWORD`, `SUPABASE_ANON_KEY_LEGACY_JWT`. The legacy JWT is also stored locally in `new_envs.txt` (gitignored, never goes to GH Actions container env via deploy script — it's a Supabase-side secret only used by deploy.sh to mint user JWTs and by local dev). |
| D | `[Errno 30] Read-only file system: '/home/appuser/.gunicorn'` | NOT FIXED | Compose `read_only:true` blocks gunicorn control socket. Log noise only, not failing. Add to iter-04. |
| E | `TWO simultaneous containers OOM 2 GB droplet during smoke probe` | 830d053 | deploy.sh now stops ACTIVE BEFORE starting IDLE (sequential blue/green). 30-60s 502 window during cutover; acceptable for single-droplet 2 GB target. retire_color.sh invocation removed since ACTIVE is already stopped. Tests in `tests/unit/website/test_deploy_sequential_blue_green.py`. |
| F | Cgroup ceiling 1300m too tight for q1 stage-2 BGE rerank | cdc688a + 01dcb61 | Bumped to 1600m + matching cgroup-assert. STILL not enough — system RAM ~1.5 GB is the real ceiling on this 2 GB droplet. |
| G | stage1_k=15 batch causes +684 MB temp tensor spike during ONNX forward pass | 7fcaaa0 | Reduced to stage1_k=10 (default in CascadeReranker.__init__). Should bring peak under 1.5 GB system ceiling. **NEEDS Phase 12 eval to validate quality didn't regress.** |
| H | No memory profiling visibility in cascade.py | 7fcaaa0 | Added `_log_rss(label)` helper + 4 trace points in `_stage2_rank` (enter/encoded/ran/scored). Grep container logs for `[mem-trace]` to compute per-stage deltas. |
| I | favicon + page titles inconsistent | 2e36dd5 | All 13 HTML pages now have `<link rel="icon" type="image/svg+xml" href="/favicon.svg">` + standardized `Page \| Zettelkasten` titles. |

## Memory reality (profiled 2026-04-28 16:49 UTC on blue cgroup=1.3GB)

| time | cgroup_mem | event |
|---|---|---|
| baseline | 188 MB | idle, 2 workers |
| +15s | 242 MB | query rewriter (Gemini calls start) |
| +19s | 427 MB | retrieval starts |
| +25s | 507 MB | retrieval continues |
| **+28s** | **1191 MB** | **+684 MB SPIKE — stage-2 BGE rerank ONNX forward pass on batch=15** |
| +44s | — | worker SIGKILLed by cgroup OOM |

After Phase 1 fixes (sequential deploy + 1.6 GB cgroup), worker STILL OOMs because system RAM ~1.5 GB is the absolute physical ceiling on this 2 GB droplet (caddy + system kernel takes ~400 MB). cgroup ceiling above system available is theoretical only.

stage1_k 15→10 should drop the spike to roughly +456 MB (linear with batch), bringing peak to ~963 MB → fits 1.5 GB system ceiling with ~500 MB headroom.

## Critical infra knobs (from CLAUDE.md "Critical Infra Decision Guardrails")

DO NOT touch without explicit user approval per occurrence:

- `GUNICORN_WORKERS=2` — never lower
- `--preload` — never disable
- `RAG_FP32_VERIFY=off` — top-3 verifier only, never blanket-on
- `GUNICORN_TIMEOUT=180+` — never lower
- Phase 1B semaphore + bounded queue + 503 backpressure — keep
- SSE heartbeat wrapper — keep
- Caddy 240s upstream timeouts — keep
- Schema-drift gate, kg_users allowlist gate — keep
- Teal-on-Kasten / amber-only-on-/knowledge-graph palette — keep
- All deploy.sh asserts (cgroup/stage2/rag-smoke) MUST stay fail-loud-no-rollback. Auto-rollback is FORBIDDEN.

## Remaining steps (DO IN ORDER)

### Step A — Watch deploy 7fcaaa0 (current in-flight push)

```bash
cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault
gh run list --workflow=deploy-droplet.yml --branch master --limit 1 --json databaseId,status,conclusion
```

If `id=N status=in_progress`:

```bash
gh run watch <N> --exit-status --interval 30
```

### Step B — Diagnose deploy outcome

**If [rag-smoke] passes (HTTP 200, primary_citation=gh-zk-org-zk):**

→ Caddy flips to new color. iter-03 is technically deployed. Proceed to Step D (Phase 12 eval).

**If [rag-smoke] still exits 89:**

ssh to droplet and pull the new [mem-trace] logs to identify the exact memory culprit:

```bash
# Git Bash
ssh -i ~/.ssh/zettelkasten_deploy -p 22 deploy@68.183.244.87 \
  'docker logs --since 5m zettelkasten-$(cat /opt/zettelkasten/ACTIVE_COLOR | tr blue green | tr green blue 2>/dev/null || echo green) 2>&1 | grep "\[mem-trace\]"'
```

Expected output (annotate per-stage deltas):

```
[mem-trace] stage2.enter rss_kb=N1 count=10
[mem-trace] stage2.encoded rss_kb=N2 count=10
[mem-trace] stage2.ran rss_kb=N3 count=10  ← biggest jump expected here
[mem-trace] stage2.scored rss_kb=N4 count=10
```

If `N3 - N2 > 400 MB`, the ONNX forward pass is still the spike culprit. Surgical options:

| Surgical fix | Where | Effect |
|---|---|---|
| Smaller batch processing | `_run_stage2_sync` in `website/features/rag_pipeline/rerank/cascade.py:503-513` — encode 5 at a time, run 2 batches | Halves peak forward-pass memory |
| Lower max_length 512→256 for stage-2 only | `CascadeReranker.__init__` `max_length=256` and `_encode_pairs_sync` truncation | Halves activation tensor sizes; may truncate long docs |
| Cap content slice in `_passage_text` | `website/features/rag_pipeline/rerank/cascade.py:570` — change `[:4000]` to `[:2000]` | Reduces token input, smaller tokenized seq |
| Drop attention/intermediate layer captures | requires onnx graph surgery; complex | Only if everything else fails |

### Step C — If memory still tight after surgical fix

Worth exploring (each requires explicit user approval per CLAUDE.md guardrails):

1. Move stage-2 to a separate worker process (true memory isolation, but new IPC complexity)
2. Use ONNX runtime's `enable_cpu_mem_arena=True` again (reverses iter-03 spec §2.3 — needs doc update)
3. Consider switching reranker to a smaller pre-built int8 model (BAAI/bge-reranker-v2-m3 is ~70 MB int8, but full re-calibration)

DO NOT propose droplet upgrade — explicitly forbidden.
DO NOT propose workers 2→1 — violates protected guardrail.

### Step D — Phase 12 Playwright eval (operator runs)

**Step D.1 — operator gets fresh Naruto JWT (Chrome DevTools console at https://zettelkasten.in/home/rag, logged in as Naruto):**

```javascript
copy(JSON.parse(localStorage.getItem('zk-auth-token')).access_token)
```

**Step D.2 — operator runs harness (PowerShell):**

```powershell
cd C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault
$env:ZK_BEARER_TOKEN = Get-Clipboard
python ops/scripts/eval_iter_03_playwright.py
```

Expected: ~10-15 min wall. Outputs `docs/rag_eval/common/knowledge-management/iter-03/verification_results.json`.

**Step D.3 — inspect against hard gates:**

```bash
cd /c/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault
python -c "import json; r=json.load(open('docs/rag_eval/common/knowledge-management/iter-03/verification_results.json')); s=r['qa_summary']; print(f\"gold@1={s['end_to_end_gold_at_1']} infra={s['infra_failures']} over_refusals={s['synthesizer_over_refusals']} p95={s['p95_latency_ms']}ms\")"
```

Hard gates (all must pass):

- `infra_failures == 0`
- `end_to_end_gold_at_1 >= 0.65`
- `synthesizer_over_refusals == 0`
- `p95_latency_ms <= 1.05 * iter-02 baseline`

If gold@1 dropped from iter-02 because of stage1_k 15→10: this is a known trade-off. Surface to user with comparison; decide whether to ship + iterate, OR rollback to stage1_k=15 + try a different surgical memory fix.

### Step E — Phase 12.2 scorecard

Create `docs/rag_eval/common/knowledge-management/iter-03/scores.md` mirroring iter-02's format. Include 3-way scorecard iter-01 vs iter-02 vs iter-03. Note the 80-chunk calibration source pool (vs plan-assumed 100+) and stage1_k=10 (vs iter-02 stage1_k=15) so comparisons are apples-to-apples.

### Step F — Phase 13.1 squash branch (NON-INTERACTIVE per CLAUDE.md)

The original plan called for ~14 logical commits. We have 14+ commits already plus the smoke/cgroup/sequential/uuid/profile fixes. Either:
1. Keep linear history (14+ commits, traceable per-fix)
2. Squash with `git reset --mixed master` + re-stage in groups (per plan Phase 13.1 — manual + non-interactive)

User preference TBD — ASK before squashing since fast-forward already landed everything to master, history can stay linear.

### Step G — Phase 13.2 24h obs window

For 7 days post-ship, daily:

```bash
gh workflow run read_recent_logs.yml -f tail_lines=2000 -f color=auto
```

Track `vm_rss_kb`, `cgroup_mem_current`, `cgroup_swap_current`. Decision point on day 7:

- IF p95(vm_rss) < 700 MB AND infra_failures = 0 → durably shipped, plan iter-04
- ELSE log data, leave config as-is, surface residual to follow-up spec

## Files to be aware of

- `models/bge-reranker-base-int8.onnx` — 267 MB LFS-tracked
- `models/bge_calibration_pairs.parquet` — 46 KB LFS-tracked
- `models/tokenizer.json` — 17 MB plain (XLMRoberta vocab=250002)
- `models/ms-marco-MiniLM-L-12-v2/` — FlashRank stage-1, ~33 MB plain
- `models/calibration_baseline.json` — drift detection metadata with sha256s
- `models/bge-reranker-base.onnx` — fp32 1.1 GB **gitignored** (regenerable via `ops/scripts/export_bge_onnx.py models/bge_export`)
- `models/bge_export/` — staging dir **gitignored**
- `new_envs.txt` — **gitignored**, contains `SUPABASE_ANON_KEY_LEGACY_JWT` for local JWT minting
- `docs/rag_eval/common/knowledge-management/iter-03-stale/` — failed first iter-03 attempt, archived as reference
- `docs/rag_eval/common/knowledge-management/iter-03/` — fresh attempt, NO Q-A scoring yet (only seed files)

## Local dev environment notes

- venv at `C:/Users/LENOVO/Documents/Claude_Code/Venv/rag-venv/` has heavy deps (optimum, transformers, torch) — used for re-running calibration/quantize when corpus drifts
- Default Python (`python` in PATH) is Windows Store install at `WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0` — works for tests but does NOT have onnx/transformers
- Long-path issue: pip install of optimum directly into Windows Store Python hits MAX_PATH; always use the venv for those packages

## Open questions for next agent

1. After Step B mem-trace data lands, do we need batch-splitting or max_length reduction? (Decide after seeing actual N1-N4 deltas)
2. Squash strategy for Step F (linear vs grouped)
3. If Phase 12 gold@1 drops below 0.65, do we accept the hit and ship, or revert stage1_k to 15 and try a different memory fix?
4. The `read_only: true` gunicorn control socket warning (issue D above) — fix in iter-03 or punt to iter-04?

## Operator commands the next agent will need

| Need | Shell | Command |
|---|---|---|
| Mint Naruto JWT for local probes | Git Bash | `bash <<'EOF'\nLEGACY_JWT=$(grep '^SUPABASE_ANON_KEY_LEGACY_JWT=' new_envs.txt | cut -d= -f2-)\nSUPA_URL=$(grep '^SUPABASE_URL=' .env | cut -d= -f2-)\ncurl -sS -X POST "${SUPA_URL}/auth/v1/token?grant_type=password" -H "apikey: ${LEGACY_JWT}" -H "Content-Type: application/json" -d '{"email":"naruto@zettelkasten.local","password":"Naruto2026!"}' \| python -c "import json,sys; print(json.load(sys.stdin)['access_token'])"\nEOF` |
| ssh droplet | Git Bash | `ssh -i ~/.ssh/zettelkasten_deploy -p 22 deploy@68.183.244.87 '<cmd>'` |
| Pull mem-trace logs | Git Bash | `ssh ... 'docker logs --since 5m zettelkasten-green 2>&1 \| grep "\[mem-trace\]"'` |
| Watch latest deploy | Git Bash | `gh run list --workflow=deploy-droplet.yml --branch master --limit 1 --json databaseId,status` then `gh run watch <id> --exit-status --interval 30` |

## Sudoers footnote

Deploy user `deploy` is uid 1000 with NOPASSWD on: `/usr/bin/tee /opt/zettelkasten/compose/.env`, `/usr/bin/chmod 600 ...`, `/usr/bin/chown deploy\\:deploy ...`, `/opt/zettelkasten/deploy/*.sh`, `/usr/bin/fallocate`, `/usr/sbin/mkswap`, `/usr/sbin/swapon`, `/usr/sbin/sysctl`, `/usr/bin/journalctl`, `/usr/bin/apt-get`, `/usr/bin/find`, `/usr/bin/rm`. NOT: arbitrary mkdir or chown. For directory creation in `/opt/zettelkasten/data/` deploy user can mkdir directly (they own that dir).
