# Iter-03 Prod Memory-Bounded Design

**Status:** spec, awaiting plan
**Goal:** hold peak RSS per blue/green container ≤ 1.3 GB on the existing 2 GB / 1 vCPU DigitalOcean droplet, support multi-user concurrent access, no user-perceived latency regression, ≤3% drop on `end_to_end_gold@1` (with a soft 2-3% bump per-stage as the upside target).
**Hard constraints (CLAUDE.md "Critical Infra Decision Guardrails"):**
- Droplet stays 2 GB / 1 vCPU. No upgrade.
- `GUNICORN_WORKERS=2` stays. Quantization is the entire reason 2 workers fit.
- `--preload` stays.
- Int8 cascade stays. fp32 verifier MUST stay code-available, only `RAG_FP32_VERIFY=off` at runtime.
- Existing Phase 1B rerank semaphore + bounded queue + 503 backpressure stays.
- Phase 1B.4 SSE heartbeat stays.
- Caddy 240s upstream timeouts stay.
- Schema-drift gate stays.

## 1 — Diagnosis (evidence, not hypothesis)

Three verified findings drive the design.

### 1.1 Container is hard-capped at 1 GB total memory with **zero swap access**

`ops/docker-compose.blue.yml` and `ops/docker-compose.green.yml` both set:

```yaml
mem_limit: 1024m
memswap_limit: 1024m
```

`memswap_limit == mem_limit` means cgroup swap allowance is **0 MiB**. The Phase 0.3 host swapfile (1 GB at `vm.swappiness=10`) is invisible to the container's cgroup. Kernel memcg-OOM fires on the cgroup before any swap is touched.

Ref: [Docker resource constraints](https://docs.docker.com/config/containers/resource_constraints/), [Linux cgroup memory docs](https://docs.kernel.org/admin-guide/cgroup-v1/memory.html).

### 1.2 ONNX `enable_cpu_mem_arena=True` is the dominant in-call spike

`website/features/rag_pipeline/rerank/cascade.py:_build_ort_session` runs with the default arena setting. [microsoft/onnxruntime#11627](https://github.com/microsoft/onnxruntime/issues/11627) documents a single inference growing RSS from 206 MiB → 5,792 MiB with arena on; the same call with `enable_cpu_mem_arena=False` grew 206 → 217 MiB. Arena pre-allocates large slabs and never returns memory to the OS for the session lifetime. On dynamic-shape inputs (variable token lengths, padding=512), the pattern caching is invalidated each call, so arena gives essentially no perf win.

### 1.3 Resident model footprint is heavier than necessary by default

| Component | When | Size | Notes |
|---|---|---|---|
| BGE int8 ONNX session | eager at module import, `--preload` shared via COW | ~110 MB | Phase 1A.4 — keep |
| BGE fp32 verify session | eager at module import, COW shared (`RAG_FP32_VERIFY=on` default) | ~440 MB | only used to re-score top-3 on `quality=high`; sits resident at all times |
| FlashRank stage-1 `Ranker` | **lazy per worker on first request** | ~80 MB **per worker** | not COW shared because instantiated post-fork |
| `ChunkEmbedder._query_cache` | grows on every unique query | ~6 KB / entry, unbounded | slow linear leak; ~3 MB after ~500 unique queries |

Master baseline ~700-800 MB. Two workers' private FlashRank ~160 MB. Plus ONNX arena spikes during inference. Total in 1 GB cgroup is over budget.

Logs evidence:
```
[2026-04-28 08:06:09 +0000] [7] [ERROR]
    Worker (pid:14) was sent SIGKILL! Perhaps out of memory?
```

## 2 — Architecture changes

Nine changes, all independently revertable. None touches a protected iter-03 knob.

### 2.1 Container ceiling — 1300m / 2300m (compose)

`ops/docker-compose.blue.yml` and `ops/docker-compose.green.yml`:

```yaml
mem_limit: 1300m
memswap_limit: 2300m   # 1 GB swap accessible to cgroup
```

Conservative margin: leaves ~530 MB on host for Caddy (128 m), migration container (transient), system overhead, headroom. With FP32 disabled and arena off, expected steady-state container RSS ~750-900 MB; spikes absorbed via swap before cgroup-OOM.

### 2.2 Bigger host swapfile — verify and ensure ≥ 2 GB (manual SSH op + runbook)

The existing `docs/runbooks/droplet_swapfile.md` already documents a **2 GB** swapfile. Verify the live droplet matches before changing anything:

```bash
swapon --show          # expect /swapfile  file  2G  …
free -h                # expect Swap: 2.0Gi …
```

**If already 2 GB (matches runbook):** no action; proceed to §2.2.b.
**If smaller (e.g., live at 1 GB from an earlier provisioning):** recreate (idempotent — preserves `/etc/fstab` and `vm.swappiness=10` already set by the runbook):

```bash
sudo swapoff /swapfile
sudo rm /swapfile
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
free -h                                # expect Swap: 2.0Gi 0B 2.0Gi
swapon --show
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sysctl vm.swappiness                   # expect 10
```

**§2.2.b — verify cgroup v2 honors the new swap budget from inside the container:**

```bash
docker exec zettelkasten-blue cat /sys/fs/cgroup/memory.max       # expect 1363148800 (~1.3 GB)
docker exec zettelkasten-blue cat /sys/fs/cgroup/memory.swap.max  # expect 1048576000 (~1.0 GB swap budget)
```

The kernel computes `memory.swap.max = memswap_limit - mem_limit = 2300m - 1300m = 1000 MiB`. The container only consumes ~1 GB of the 2 GB host swap; the host keeps 1 GB headroom for the green container during blue/green cutover (both colors hold mem at the same time for ~30s drain).

**§2.2.c — verify no extra DigitalOcean cost** (user requirement):

```bash
doctl compute droplet get <DROPLET_ID> --format Name,Size,Memory,VCPUs,Disk,PriceMonthly
# expect: same plan as before (s-1vcpu-2gb or premium-intel-2gb), same $monthly
df -h /                # confirm enough free space on the 70 GB SSD for 2 GB swap
```

Swap is local SSD storage — billed inside the existing droplet plan. Provisioning more swap does not change the droplet size or the monthly bill.

`vm.swappiness=10` stays (already set). Container cgroup v2 inherits parent swappiness; no separate cgroup tuning needed.

### 2.3 ONNX arena off (cascade.py)

`website/features/rag_pipeline/rerank/cascade.py:_build_ort_session`:

```python
opts = ort.SessionOptions()
opts.intra_op_num_threads = 1
opts.inter_op_num_threads = 1
opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
opts.enable_cpu_mem_arena = False     # NEW — caps arena at working-set
opts.enable_mem_pattern = False       # NEW — no benefit on dynamic shapes
```

Apply to **both** int8 and fp32 sessions in `_build_ort_session`. The fp32 session is gated by `RAG_FP32_VERIFY=on` (off by default — §2.4), but the arena flags must be set in the helper for both code paths so future fp32 re-enable does not regress.

Latency cost: per [issue #11627](https://github.com/microsoft/onnxruntime/issues/11627) thread, +10-30ms per BGE call. We do 1-3 BGE rerank calls per `/api/rag/adhoc`. Current p50 end-to-end is ~20s (Gemini-bound), so this is +0.05-0.15% relative — invisible.

Quality cost: 0. Arena is a memory allocator; identical numerical output.

### 2.4 RAG_FP32_VERIFY=off (env default)

Insert one line in `.github/workflows/deploy-droplet.yml` STATIC_BODY between the existing `REDDIT_OPTIONAL=1` and the existing `DEPLOY_GIT_SHA=…` lines:

```yaml
          STATIC_BODY=$(printf '%s\n' \
            "WEBHOOK_MODE=true" \
            "WEBHOOK_PORT=10000" \
            "WEBHOOK_URL=https://${TARGET_HOST}" \
            "NEXUS_ENABLED=true" \
            "REDDIT_OPTIONAL=1" \
            "RAG_FP32_VERIFY=off" \                    # NEW
            "DEPLOY_GIT_SHA=${DEPLOY_GIT_SHA}" \
            "DEPLOY_ID=${DEPLOY_ID}" \
            "DEPLOY_ACTOR=${DEPLOY_ACTOR}" \
            "GUNICORN_WORKERS=2" \
            "GUNICORN_TIMEOUT=240" \
            "GUNICORN_GRACEFUL_TIMEOUT=90")
```

Reclaims ~440 MB resident from master COW base. Quality cost is bounded by the int8-vs-fp32 outlier rate on top-3 only; will be measured by the post-deploy eval. **Re-enable trigger** documented in §3 — operational, not automatic, last-resort only.

### 2.5 FlashRank preload at module level (cascade.py)

Hoist `Ranker` instantiation from `_get_stage1_ranker` (lazy per worker) to a module-level singleton beside `_STAGE2_SESSION` and `_FP32_VERIFY_SESSION`. With `--preload`, both workers inherit the FlashRank model via COW instead of paying the ~80 MB private cost twice.

Concrete change in `website/features/rag_pipeline/rerank/cascade.py`:

```python
# After the int8 / fp32 session preloads, before the CascadeReranker class.
_DEFAULT_FLASHRANK_DIR = _REPO_ROOT / "models"
_FLASHRANK_MODEL_NAME = "ms-marco-MiniLM-L-12-v2"  # current FlashRank default — verify in flashrank source if changed


def _build_flashrank_ranker(model_dir: Path) -> Ranker | None:
    """Eagerly build the FlashRank stage-1 ranker for module-level COW share.

    Runs in master pre-fork under gunicorn --preload, so each worker inherits
    the resident model via copy-on-write. Filesystem side effects (model
    download via flashrank's ModelManager on first run) MUST be done before
    fork, so the cache directory is populated and workers do not race.
    """
    try:
        ModelManager(str(model_dir)).ensure_flashrank_model(_FLASHRANK_MODEL_NAME)
        return Ranker(model_name=_FLASHRANK_MODEL_NAME, cache_dir=str(model_dir))
    except Exception as exc:  # pragma: no cover — bootstrap fault is logged
        _logger.warning("failed to preload FlashRank ranker: %s", exc)
        return None


_STAGE1_RANKER: Ranker | None = _build_flashrank_ranker(_DEFAULT_FLASHRANK_DIR)
```

`CascadeReranker._get_stage1_ranker` is rewritten to:

```python
def _get_stage1_ranker(self) -> Ranker:
    if _STAGE1_RANKER is not None:
        return _STAGE1_RANKER
    # Test / smoke fallback: per-instance lazy build retains the legacy path
    # so tests that patch model_dir keep working.
    with self._stage1_lock:
        if self._stage1 is None:
            self._stage1 = Ranker(
                model_name=_FLASHRANK_MODEL_NAME,
                cache_dir=str(self._model_manager.model_dir),
            )
        return self._stage1
```

The existing `_get_stage2_session` lazy path stays as a fallback for tests; in prod, `_STAGE2_SESSION` (already module-level) wins. Same pattern for `_get_stage2_tokenizer`. Document this explicitly with a comment in cascade.py: "production path uses module-level singletons; lazy paths exist for tests where the model file is absent."

Side benefit: gunicorn `--max-requests` recycle (§2.7) becomes essentially free — fork inherits FlashRank from master, no cold-load on first post-recycle request.

### 2.6 Bounded LRU embedder query cache (embedder.py)

`website/features/rag_pipeline/ingest/embedder.py` top-of-file imports:

```python
from cachetools import LRUCache
```

`cachetools>=5.3` is already pinned in `ops/requirements.txt` — no new dependency.

In `ChunkEmbedder.__init__`, replace:

```python
self._query_cache: dict[str, list[float]] = {}
```

with:

```python
self._query_cache: LRUCache[str, list[float]] = LRUCache(
    maxsize=int(os.environ.get("RAG_QUERY_CACHE_MAX", "256")),
)
```

256 entries × ~6 KB = ~1.5 MB cap. The env var lets ops change the size without redeploying code. Hot queries within a session still hit the cache; the slow linear leak from unbounded growth stops.

`cachetools.LRUCache` is not thread-safe across threads, but uvicorn workers run a single asyncio loop — the cache is only read/written inside coroutines without crossing await points except the embed call itself. Worst case is two coroutines miss for the same key, both fire embed, both write — duplicate work, no corruption. Acceptable.

### 2.7 Gunicorn worker recycling (run.py)

`run.py`:

```python
cmd = [
    "gunicorn",
    "-k", "uvicorn.workers.UvicornWorker",
    "-w", os.environ.get("GUNICORN_WORKERS", "2"),
    "--preload",
    "--bind", ...,
    "--timeout", os.environ.get("GUNICORN_TIMEOUT", "240"),
    "--graceful-timeout", os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "90"),
    "--keep-alive", os.environ.get("GUNICORN_KEEPALIVE", "5"),
    "--max-requests", os.environ.get("GUNICORN_MAX_REQUESTS", "100"),         # NEW
    "--max-requests-jitter", os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "20"),  # NEW
    "website.main:app",
]
```

With FlashRank now COW-shared (§2.5), worker recycle is ~10-50ms kernel fork only. Bounds drift from any leaky dep (psycopg pool, google-genai HTTP buffers, etc.) without user-visible latency.

### 2.8 RSS + CPU + load instrumentation

Two surfaces, both new:

**(a) On-demand JSON endpoint at `/api/admin/_proc_stats`** (auth-gated):

New file `website/api/admin_routes.py`:

```python
"""Ops-only diagnostic endpoints. Mounted at /api/admin/*. Naruto + Zoro only.

Allowlist source: ops/deploy/expected_users.json (the single-tenant gate from
Phase 2D). Any auth_id outside that file gets 404 (not 403, to avoid leaking
the existence of admin endpoints to randoms).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from website.api.auth import get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin"], include_in_schema=False)

_ALLOWLIST_PATH = Path(__file__).resolve().parents[2] / "ops" / "deploy" / "expected_users.json"


def _load_admin_allowlist() -> set[str]:
    try:
        return set(json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))["allowed_auth_ids"])
    except Exception:
        return set()


def _require_admin(user: dict) -> None:
    allowed = _load_admin_allowlist()
    if not allowed or user.get("sub") not in allowed:
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/_proc_stats")
async def proc_stats(user: Annotated[dict, Depends(get_current_user)]):
    _require_admin(user)
    # Read /proc/self/status, /proc/loadavg, /sys/fs/cgroup/memory.{max,current,swap.current}
    # Return JSON: vm_rss_kb, vm_size_kb, vm_swap_kb, cgroup_mem_used, cgroup_mem_max,
    #   cgroup_swap_used, load_1m, load_5m, num_threads, num_fds.
    return _read_proc_stats()
```

`website/main.py` mounts the router alongside `chat_router` and `sandbox_router`.

**(b) Periodic background task (every 60s) emitting a single log line**:

Implemented as a `lifespan`-registered asyncio task in `website/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    interval = int(os.environ.get("PROC_STATS_LOG_INTERVAL_SECONDS", "60"))
    task = asyncio.create_task(_proc_stats_logger_loop(interval))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
```

The task logs once per interval at `INFO` level, single line:

```
[proc_stats] vm_rss_kb=512340 vm_swap_kb=18240 cpu_percent=42.5 load_1m=0.18 cgroup_mem_used=523648 cgroup_mem_max=1363148800 cgroup_swap_used=18432 cgroup_swap_max=1048576000
```

The interval is env-overridable via `PROC_STATS_LOG_INTERVAL_SECONDS` (default 60). Lifecycle is guaranteed: cancelled on shutdown via the lifespan context manager.

This is the data we need to decide later if `RAG_FP32_VERIFY=on` is safe to re-enable. The endpoint also feeds the post-deploy verification harness so the Playwright eval records VmRSS pre/post each phase.

### 2.9 Soft RSS-guard middleware

New `website/api/_memory_guard.py`. FastAPI middleware that, before dispatching to a handler, reads `/proc/self/status` for `VmRSS` and compares against a soft threshold (default 90% of cgroup `memory.max`). If over the threshold:

```python
return JSONResponse(
    {"error": "server_under_memory_pressure", "retry_after_seconds": 5},
    status_code=503,
    headers={"Retry-After": "5"},
)
```

**Threshold detection** (cgroup v2 → cgroup v1 → fallback):

```python
def _detect_mem_max() -> int:
    # cgroup v2 (Ubuntu 22.04+, our droplet base)
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = Path(p).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if raw == "max":
            continue   # cgroup unbounded — fall through
        try:
            return int(raw)
        except ValueError:
            continue
    # Fallback: read total host RAM (used in dev/local where no cgroup limit is set)
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0  # 0 → guard disables itself
```

**Configurable threshold** (env-override): `RAG_MEMORY_GUARD_THRESHOLD_PERCENT` (default `90`). Setting to `0` disables the guard entirely (useful for tests, dev).

**Path exemptions** — the guard MUST skip these paths to avoid breaking probes and ops:

```python
_EXEMPT_PREFIXES = (
    "/api/health",      # Caddy / Cloudflare upstream healthchecks
    "/api/admin/",      # ops triage during pressure must always work
    "/telegram/webhook",# Telegram retries on 503 — but this is webhook, not user
    "/favicon.ico",
    "/favicon.svg",
)
```

Hot-path cost: one `/proc/self/status` read per non-exempt request = ~20 µs (cached file handle if reused). The existing Phase 1B semaphore + queue caps concurrency; this guard catches the case where peak RSS spikes faster than the queue can shed.

## 3 — Failure modes, observability, rollback

### Failure modes
- **Cgroup-OOM still possible** when a single hot path's allocation blows past 1.3 GB before the guard reads. Soft RSS guard catches the steady-state case; outliers still produce 502. Mitigation if observed: drop stage-1 candidate count from 15 → 12 (Phase 1A constant), reducing per-call working set.
- **Quality regression** from §2.4 fp32-off is the highest-likelihood culprit, but the **revert order does NOT lead with re-enabling fp32** (per user constraint — fp32 is too resource-heavy to re-enable without exhausting alternatives).

### Quality-regression triage order (do NOT flip fp32 first)
1. Verify the regression is real and persistent (re-run eval, compare against same query set, rule out flake).
2. Inspect critic_verdict distribution: if "unsupported_or_partial" rate jumped, check if synthesizer (not retrieval) is the cause.
3. Inspect `retrieval_recall_at_10`: if recall is fine but reranker top-1 changed, the regression is in the int8 top-3 path.
4. **Try non-fp32 fixes first**:
   - Restore `enable_cpu_mem_arena=True` only on the int8 session — the rerank path may need warmup arena to converge on stable scoring under the same seed.
   - Bump stage-1 candidate count from 15 → 20, giving int8 more candidates to choose from before stage-2.
   - Re-tune per-class margin thresholds in `_int8_thresholds.json` (Phase 1A.5) — likely **lower** the threshold for `lookup` and `vague` classes by 0.02-0.05 if the post-arena-off scoring distribution shifted; re-measure on the iter-03 query set.
   - Re-tune the score-calibration regression in `_int8_score_cal.json` against the iter-03 query set with arena off.
5. If 1-4 don't recover end_to_end_gold@1 to within 3% of pre-iter-03-mem baseline, **only then** evaluate flipping `RAG_FP32_VERIFY=on` — and if that's needed, also evaluate dropping container `mem_limit` headroom by another 100m to make room (since fp32 adds ~440 MB).

### Latency / CPU regression triage order
1. Check `/api/admin/_proc_stats` cpu_percent under load. If sustained > 70%:
   - Compare to baseline (pre-arena-off).
   - If arena-off is the cause (more `malloc` cycles), re-enable arena on the int8 session **only** (fp32 stays off).
   - If thread-pool growth, set `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1` in env.

### Rollback unit
Each change is one config knob:
- compose mem_limit / memswap_limit → revert with one yml edit.
- swapfile size → swapoff + recreate.
- arena flag → one-line cascade.py revert.
- **`RAG_FP32_VERIFY` → LAST RESORT only — see triage order above. NEVER first revert.**
- FlashRank preload → restore lazy `_get_stage1_ranker`.
- LRU cache → restore unbounded dict.
- max-requests → drop the gunicorn flag.
- proc_stats endpoint + memory guard → unmount the router.

## 4 — Validation & roll-out plan

1. **Pre-merge unit + stress tests** (every new test must fail before the change and pass after):
   - `tests/unit/rag/test_query_cache_lru.py` — LRU eviction at 256, env-var override (`RAG_QUERY_CACHE_MAX`) honored, hot-key round-trip.
   - `tests/unit/api/test_memory_guard.py` — VmRSS over threshold returns 503 with `Retry-After`; cgroup v2 + v1 + fallback path detection covered; `RAG_MEMORY_GUARD_THRESHOLD_PERCENT=0` disables the guard entirely.
   - `tests/unit/api/test_memory_guard_exempts_health.py` — `/api/health`, `/api/admin/_proc_stats`, `/favicon.ico`, `/favicon.svg`, `/telegram/webhook` MUST return 200 even when the guard would otherwise trip 503.
   - `tests/unit/api/test_proc_stats.py` — endpoint returns the documented JSON shape; non-allowlisted user gets 404 (not 403, to avoid leaking the existence of admin endpoints).
   - `tests/unit/quantization/test_arena_off.py` — `_build_ort_session` returns a session with `enable_cpu_mem_arena=False` AND `enable_mem_pattern=False`.
   - `tests/unit/rerank/test_flashrank_preload.py` — module-level `_STAGE1_RANKER` resolves on import; `_get_stage1_ranker` returns the singleton when present and falls back to per-instance build only when `_STAGE1_RANKER is None`.
   - `tests/unit/website/test_static_body_has_fp32_off.py` — assert the literal `RAG_FP32_VERIFY=off` line is present in `.github/workflows/deploy-droplet.yml` STATIC_BODY between `REDDIT_OPTIONAL=1` and `DEPLOY_GIT_SHA=`.
   - `tests/unit/website/test_run_py_emits_max_requests.py` — assert `--max-requests` and `--max-requests-jitter` appear in the gunicorn argv built by `run.py.main()`.
   - `tests/unit/api/test_lifespan_proc_stats_task.py` — lifespan startup creates the periodic logger task; shutdown cancels it cleanly within 1s.
   - Existing 1376-test suite must stay green.
   - Existing `tests/stress/test_burst_capacity.py` re-run; add a new test in the same file that imports `website.api._memory_guard._detect_mem_max` and asserts a sane integer (>0) when called within the harness.

2. **Local Docker smoke** (operator runs):
   ```bash
   docker run --rm \
     -m 1300m --memory-swap 2300m \
     --env-file .env.local \
     ghcr.io/chintanmehta21/zettelkasten-kg-website:<sha>
   ```
   Smoke fixture query: `q1` from `docs/rag_eval/common/knowledge-management/iter-03/queries.json` (`"Which programming language is the zk-org/zk command-line tool written in, and what file format does it use for notes?"`). Expect HTTP 200, `turn.citations[0].node_id == "gh-zk-org-zk"`, latency < 30s. Verify `VmRSS / cgroup_mem_max < 0.9` via `GET /api/admin/_proc_stats` before AND after the query.

3. **Deploy** via existing GH Actions pipeline.

4. **One-shot droplet swap bump** (manual SSH op via runbook §2.2).

5. **Post-deploy verification** — `python ops/scripts/eval_iter_03_playwright.py` (full 13+2 Q-A chain + diversification + UI/UX + per-stage metrics). Acceptance gate compares against the pre-change baseline captured at `docs/rag_eval/common/knowledge-management/iter-03/baseline.json` (already committed; iter-02 derived numbers). Each metric below has its source field in that file:
   - `infra_failures = 0` on the 13 sequential queries (zero 502s, zero 503s). The burst phase MAY legitimately produce a 503 from §2.9 — that's the test, NOT counted as `infra_failures`.
   - `end_to_end_gold_at_1` (hard gate) must be ≥ `baseline.json:ci_gates.end_to_end_gold_at_1_min` (= 0.65) AND must NOT drop more than 3% absolute below the pre-change post-iter-03 baseline measured by the harness immediately before this rollout. Soft target: improvement.
   - per-stage signals (soft, must not drop more than 3% absolute):
     - `retrieval_recall_at_10` vs `baseline.json:per_stage.retrieval_recall_at_10` (= 1.0 from iter-02 orchestrator-only)
     - `reranker_top1_top2_margin_p50` vs `baseline.json:per_stage.reranker_top1_top2_margin_p50` (= null in iter-02; this is the first iter to record a real value, so floor is "non-null" rather than a delta)
     - `synthesizer_grounding_pct` vs `baseline.json:per_stage.synthesizer_grounding_pct` (= 0.60)
   - `over_refusals = 0`.
   - p95 latency ≤ pre-change p95 + 5% (pre-change p95 captured by running the harness against the current deployed sha BEFORE applying any of this iter's changes).

6. **24h observation window**:
   - Pull `/api/admin/_proc_stats` periodic logs once daily.
   - If VmRSS p95 < 70% of 1300m AND CPU p95 < 60% AND zero infra_failures: candidate to attempt `RAG_FP32_VERIFY=on` again as a separate, isolated rollout (run 1-4 of §3 quality-regression triage in reverse).

## 5 — Out of scope

- Changing the droplet (hard constraint).
- Changing `GUNICORN_WORKERS` away from 2 (hard constraint).
- Switching to `gthread` workers (FastAPI is ASGI; not viable).
- Re-quantizing BGE to a smaller variant (would need a new int8 calibration run + new score-calibration regression — separate iter).
- Adding a second droplet behind a load balancer (out of cost budget).
