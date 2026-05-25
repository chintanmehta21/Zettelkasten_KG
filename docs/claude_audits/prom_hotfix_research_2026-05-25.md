# Prom-hotfix research — industry-standard sweep + recommendations for approval

**Date:** 2026-05-25
**Trigger:** live URL repro (Naruto, `youtube.com/watch?v=ZvO5kikFVOk&t=5s`) crashed in 11.78 s with `FileNotFoundError: '/tmp/prom_multiproc/counter_15.db'` from `Counter.labels(...).inc()` — see `live_url_repro_2026-05-25.md` for the full trace. Slack `#app-errors` confirmed the alert fired with severity `critical`.
**Scope:** decide what to ship in a new PR (separate from #89) to make summarisation fully-functioning again. 4 items + 1 optional probe.
**Method:** 4 parallel research subagents, each tasked with a single decision; web search + web fetch only; recency-weighted (< 5 yr); no code modified during research.

---

## TL;DR — what to ship (1 PR, 4 changes + 1 probe)

1. **Wrap every `.inc()` in a *single* safe-metrics helper module**, not inline `try/except` at the call-site. Catch `(OSError, ValueError, RuntimeError)`, log with `exc_info=True` through a rate-limited handler (1 per 60 s per `(metric_name, errno)` key), AND bump a meta-counter `app_metric_emit_failures_total{metric, errno}` so failures stay visible. Matches OpenTelemetry's "MUST NOT throw" rule and how `prometheus-fastapi-instrumentator` ships it.
2. **Move `PROMETHEUS_MULTIPROC_DIR` off `/tmp`** to `/app/var/prom` (in-image, app-namespaced, disk-backed). `python:3.12-slim` itself has no `/tmp` cleaner, but the droplet host's `systemd-tmpfiles` or a stray compose `tmpfs:` re-mount can clobber `/tmp` mid-process — and the Django-Prometheus docs are the closest thing the ecosystem has to a vendor blessing for the new location ("not `/tmp`"). Recreate the dir + wipe stale files in the FastAPI `lifespan` startup belt-and-suspenders style.
3. **Add a *default-else* branch in `_async_failure_error_payload`** that emits the canonical RFC 9457 fallback: `type=about:blank`, `code=internal_error`, `detail="An unexpected error occurred…"`, no `str(exc)` ever in `detail`. Add a `X-Operation-Id` response header on every problem body. Server-side, `maybe_fire_app_error` already captures `repr(exc)` + stage to Slack, which is the only place the class name should live.
4. **Tests follow the parametrized + caplog + `mock.patch` + `TestClient(raise_server_exceptions=False)` pattern.** Snapshot tests are explicitly *not* recommended for problem-detail bodies — those are specifications, not regressions.
5. **(Probe, not code)** Run `docker exec zettelkasten-blue ls -la /tmp/prom_multiproc /app/var/prom` right after the fix lands to confirm the new dir survives and the old one is no longer load-bearing.

The four items chain: (1) is the safety net so a future re-wipe never breaks a request again; (2) is the actual root-cause fix; (3) closes the entire `code=null` cohort (4 of 8 24h failures yesterday); (4) keeps the safety net honest.

---

## Item 1 — Defensive metrics emission in `budget.py`

### Decision

Today's posture: every `Counter.labels(...).inc()` in `budget.py:174-188` can raise `FileNotFoundError` straight through into the request handler. Two questions:

- **(a) How to wrap the swallow?** Inline `try/except` at every emit site, decorator, Counter subclass, or a single helper module?
- **(b) Silent-swallow vs swallow-with-alert?** And if alert, how do mature shops avoid storming when the metric backend is wedged?

### What industry actually does

| Question | Industry signal | Recency |
|---|---|---|
| Telemetry must never throw | **OpenTelemetry hard MUST**: "OpenTelemetry implementations MUST NOT throw unhandled exceptions at runtime." SDK must let operators override the default handler. Followed by Honeycomb, Datadog, Dynatrace. | Current spec |
| `prometheus_client` is famously *not* OTel-compliant | Multiple multi-year issues (`#127`, `#275`, `#425`, `#599`, `#939`) show `mmap_dict`/`MultiProcessCollector` raise straight through. The community workaround is a safety harness *outside* `prometheus_client`. | Issues open 2018-2025 |
| Reference safety-harness shape | `prometheus-fastapi-instrumentator` wraps its middleware in `try/except` so a broken metric never escapes the request — this is the closest thing the ecosystem has to a "canonical wrapper". | Active 2024-2025 |
| Where mature platform teams put the swallow | A thin internal "safe-metrics" facade. Product code never touches raw counters. Stripe's published observability philosophy ("design defensive systems with failures in mind") explicitly calls this out as a discipline. | 2023+ |
| Alert storms | Pattern: emit a *dedicated* `app_metric_emit_failures_total` counter (lazily-constructed, swallows its own init errors), alert on `rate( ... > 0)[5m]`, AND add an **absence alert** on the real signal (`absent_over_time(gen_ai_client_calls_total[15m])`). Grafana Labs uses geographically-distributed meta-Prometheus servers cross-monitoring each other for this exact failure mode. | 2024-2026 |
| Log-bill explosion | When `/tmp/prom_multiproc` is wiped, *every* request hits the swallow → naive `logger.warning` floods stdout. Industry uses `ratelimitingfilter` / `log-rate-limit` or hand-rolled "log once per 60 s per signature" dedup. | 2023+ |

### Recommendation for our stack

- **Preferred:** new module `website/features/observability/safe_metrics.py` exposing `safe_inc(counter, labels, amount=1)` and `safe_observe(counter, labels, value)`. Each call wrapped in `try/except (OSError, ValueError, RuntimeError)`. On exception:
  1. Increment a module-local `_metric_emit_failures` counter (constructed once via its own `try/except`; if even that fails, log only).
  2. Log via a rate-limited logger (1 per 60 s per `(metric_name, errno_or_excclass)` signature) with `exc_info=True` so the stack survives.
- Re-route the four `_emit_*` helpers in `budget.py:174-188` through `safe_inc`. Net diff: ~25-30 lines including the new module.
- **Do NOT** add a global `try/except` middleware around the whole request — too broad, hides real bugs. Catch must stay narrow.

### Risks

1. **Silent drift** — if you ship the swallow *without* the emit-failure counter + absence alert, a `/tmp` wipe will produce zero metrics and zero alerts — worse than today's loud crash. Ship together.
2. **Cause-chain loss** — wrong indentation (try/except around surrounding business logic, not just `.inc()`) re-creates the bug. Tight scope only.
3. **`KeyboardInterrupt` / `SystemExit`** — never `except Exception:` without thinking. Restrict to `(OSError, ValueError, RuntimeError)` so `BaseException` subclasses propagate.

---

## Item 2 — `PROMETHEUS_MULTIPROC_DIR` location + recreate-at-boot

### Decision

Today: `PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc`, `mkdir -p` at Dockerfile build time, nothing recreates it at runtime. The dir disappeared ~78 min after container start (cause unproven — see below). Two questions:

- **(a)** Is `/tmp` the wrong home for this state — and if so, where?
- **(b)** Should we recreate at app boot (lifespan), or is a stable path enough?

### What industry actually does

| Question | Industry signal | Recency |
|---|---|---|
| Canonical path | **Django-Prometheus docs (closest to vendor-blessed in the ecosystem)**: "since these files will be written often, you should consider mounting this directory as a tmpfs or using a subdir of an existing one such as `/run/` or `/var/run/`." | Current |
| Path in real production | GitLab: `/prom_cache`. Nautobot: `/prom_cache`. Most tutorials: `/tmp/prom_multiproc` (least-defensible). | 2023-2025 |
| `python:3.12-slim` itself | Debian Bookworm slim — **ships NO `systemd-tmpfiles`, NO `cron`, NO `tmpwatch`**. The base image alone cannot wipe `/tmp`. | Current |
| Mechanisms that *did* wipe `/tmp` in real incidents | (1) Host-side `systemd-tmpfiles-clean.timer` reaching into container storage overlapping `/tmp` (Podman `#7852`). (2) Compose-level `tmpfs:` re-mount on a sidecar starting. (3) Operator deploy script doing `rm -rf /tmp/*`. (4) OOM-killed worker leaving per-PID files orphaned (not the dir). | 2022-2025 |
| Big-vendor (Anthropic, Stripe, Cloudflare, OpenAI, …) | None publish `PROMETHEUS_MULTIPROC_DIR` placement. **They sidestep the problem** — they use OpenTelemetry pipelines OR single-process-per-container with replica-count scaling. Our 2-worker-per-droplet model is exactly the small-scale design that *needs* this dir. | 2023-2025 |
| Recreate-at-boot vs stable-path-by-construction | **Both, together.** Stable path is primary defense; lifespan-start `os.makedirs(dir, exist_ok=True) + optional wipe` is belt-and-suspenders. Library has *no built-in recreation* — first `.inc()` after a missing-dir event raises. | 2023+ |
| Volume vs no-volume | **No named volume.** Upstream explicit: "directory must be wiped between Gunicorn runs." Persisting across restarts re-introduces PID-reuse + stale-file accumulation (Nautobot #4234: months of accumulation → inode exhaustion). Wipe-on-restart is *desirable*. | 2024-2025 |

### Recommendation for our stack

- **Preferred:** move to `/app/var/prom` (in-image, app-namespaced, disk-backed). 32 small `.db` files = well under 10 MB; I/O is negligible on the 70 GB NVMe. Immune to *any* `/tmp` cleaner.
- **Alternative:** keep `/tmp/prom_multiproc` but mount it as an explicit `tmpfs` in `ops/docker-compose.{blue,green}.yml`, size-capped at 64 MB. Trades ~3 % of the 2 GB RAM (acceptable but not free given the iter-03 int8 quantization budget).
- **Regardless of path:** add FastAPI `lifespan` startup that does:
  ```python
  d = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "/app/var/prom")
  os.makedirs(d, exist_ok=True)
  # optional: wipe stale per-PID files from prior process generations
  for f in glob.glob(os.path.join(d, "*.db")):
      try: os.unlink(f)
      except OSError: pass
  ```
- **Do NOT** add a Docker named volume. Wipe-on-restart is the desired posture.

### Risks

1. **`mark_process_dead` only cleans `live*` gauge files.** Counter/histogram/summary files accumulate across worker restarts. If you ever enable `gunicorn --max-requests` (worker recycling), files grow unbounded between container restarts. Mitigation: keep workers long-lived, OR add periodic cleanup, OR accept restart-as-cleanup (current state).
2. **`gunicorn --preload` interaction.** Metrics defined at import-time are shared via copy-on-write; each child still writes its own per-PID file. Works correctly only if `PROMETHEUS_MULTIPROC_DIR` is set via shell *before* `prometheus_client` import in the parent. Already shell-set in Dockerfile — fine.
3. **High-cardinality labels** (future `user_id` label) would explode per-PID file size very quickly because every combination is appended to the mmap'd file. Out of scope for this PR; flag for the team.

---

## Item 3 — RFC 9457 catch-all (default-else for uncaught exceptions)

### Decision

Today: `_async_failure_error_payload(exc)` maps 6 specific typed exceptions to RFC 9457 problem bodies. For anything outside that list, it returns `None`, which lands `error JSONB = NULL` in `core.operations`. The `code=null` cohort yesterday was 4 of 8 24 h failures. Three questions:

- **(a)** What's the canonical RFC 9457 fallback shape?
- **(b)** What goes in `detail` — generic string, redacted class name, or `str(exc)`?
- **(c)** Where does the correlation id (we already have `operation_id`) live — body, header, or both?

### What industry actually does

| Question | Industry signal | Recency |
|---|---|---|
| RFC 9457's own guidance | §3.1.4: detail "ought to focus on helping the client correct the problem, rather than giving debugging information." §5: generators "are encouraged to avoid making implementation details such as a stack dump available." §4.2.1: `about:blank` is the explicit default `type`. | RFC 9457, Jul 2023 |
| `detail` text | **Three camps.** (1) Static generic string (Stripe: "Something went wrong on Stripe's end."). (2) Sanitized class hint (OpenAI: "The server had an error processing your request."). (3) Verbatim `str(exc)` — flagged as a vulnerability by OWASP API8:2023. **Industry consensus for 500 catch-all = static generic.** | 2023-2026 |
| `type_slug` | `about:blank` (Spring Boot 3.x default, Quarkus default) for the catch-all. Project-namespaced URIs (e.g. `https://zettelkasten.in/problems/internal-error`) only for *typed* errors with docs pages. | 2023-2025 |
| Correlation id | **Both header + body.** Header is what curl/fetch debugging tools surface and the only thing readable if the body is malformed. Body is what support copies out of Slack screenshots. Anthropic: `request-id` header + `request_id` body. GitHub: `X-GitHub-Request-Id`. AWS: `x-amzn-requestid`. Stripe: `Request-Id` header. | 2024-2026 |
| Major API providers' 5xx shape | None of Anthropic / Stripe / OpenAI / Google Cloud use RFC 9457 wire format — all proprietary envelopes. **All four converge on `{static generic message + machine-readable type/code + request id}`** which is exactly what we already do via the `code` extension. | 2024-2026 |
| OWASP API8:2023 redaction list | Strip before the wire: `str(exc)`, `repr(exc)`, `type(exc).__name__`, traceback, absolute file paths (`/opt/`, `C:\`, `/etc/`), IPs, hostnames, DSNs, JWT prefixes (`eyJ`), Stripe key prefixes (`sk_`, `pk_`), email addresses, internal IDs, DB column names from constraint violations. | 2023 |

### Recommendation for our stack

The fallback returns this (server-side; never `None`):

```json
{
  "type": "about:blank",
  "title": "Internal Server Error",
  "status": 500,
  "detail": "An unexpected error occurred. Please contact support with the operation ID below if this persists.",
  "instance": "/api/zettels/add/<op_id>",
  "code": "internal_error",
  "operation_id": "<existing op id>"
}
```

Plus: `X-Operation-Id: <op_id>` response header on every problem response (sync + async-finalized paths).

**Single iron-clad redaction rule for our codebase:** the fallback NEVER reads `exc`. Server-side, `maybe_fire_app_error` already captures `repr(exc)` + stage + user_hash to Slack — that is the only place class name and message can appear. The wire response is exception-content-agnostic, by construction. No regex-based redactor needed because the unsafe inputs never enter the response builder.

### Risks

1. **Support debuggability regression** — engineers will ask "what was the actual exception?" Mitigated: Slack alert already fires with `operation_id + user_hash + stage`. Document that triage pivots from `operation_id` → Slack, not from the response body.
2. **Regression on existing typed handlers** — the default-else must be the *last* branch. If placed first, every `ExtractionConfidenceError` collapses to `internal_error`. Mandatory regression test: each existing typed exception still maps to its specific `type_slug` and `code`.
3. **Alert fatigue** — once every unmapped exception emits a structured 500, previously-silent paths might surface new Slack noise. `maybe_fire_app_error` already fires today, so net new noise should be near zero — but watch the post-deploy window. Add a per-`(stage, exc_class_name)` server-side dedup on the *Slack* side, NOT the response builder.

---

## Item 4 — Test patterns for items 1-3

### Decision

How do we test:
- **(a)** that the swallow in `safe_inc` actually swallows + logs + bumps the meta-counter?
- **(b)** that the RFC 9457 default-else returns the right shape for any uncaught exception?

### What industry actually does

| Question | Industry signal | Recency |
|---|---|---|
| Where to patch the mock | **"Patch where it's used, not where it's defined"** — patch the bound symbol inside the module under test, not `prometheus_client.Counter.labels`. `mock.patch` with `side_effect=FileNotFoundError(...)`. `monkeypatch` can't drive `.side_effect` semantics ergonomically. | 2024 |
| Reproduce missing-dir organically? | **No.** Don't `rm -rf` the dir in a fixture — depends on multiproc init order, brittle, tests the environment not the swallow. | 2024 |
| Unit vs integration | **Both.** Unit-test `_emit_call_counter` directly (stub counter raises, assert no re-raise + caplog WARNING). One integration test: `TestClient.post('/api/zettels/add', ...)` with `raise_server_exceptions=False`, force the metric to raise via `mock.patch`, assert response is 200/202. | 2024-2025 |
| Snapshot vs explicit-key | **Explicit keys for problem-detail bodies.** Snapshots are for stable large payloads where regression-detection beats specification; error responses are *specifications*, not regressions. Kreya / Syrupy literature explicit on this. Existing `test_problem_shape.py` parametrize style is already correct. | 2024 |
| Parametrize the exception class | **Yes.** `pytest.param(FileNotFoundError, id="missing-multiproc-dir"), (PermissionError, id="perm-denied"), (OSError, id="generic"), (BrokenPipeError, id="broken-pipe")`. Proves the `except` family catches all of them; matches existing typed-exception parametrize style. | 2024 |
| Caplog vs side-effect | **Both — they assert different things.** `caplog.at_level(WARNING, logger=...)` proves observability. `counter.labels.return_value.inc.assert_called_once_with(...)` proves attempt. Side-effect-only is necessary-but-insufficient. Use `record.exc_info` to verify the `exc_info=True` survived. | 2024 |
| FastAPI `@app.exception_handler(Exception)` gotcha | Catch-all `Exception` handler runs through Starlette's `ServerErrorMiddleware`, not the normal `ExceptionMiddleware`. Tests **must** use `TestClient(app, raise_server_exceptions=False)` or they fail with the raw exception. | 2024 |
| Ruff BLE001 | Auto-suppresses when the `except Exception:` body calls `logger.warning(..., exc_info=True)` (configure `lint.logger-objects` if needed). No `# noqa` required. | 2024 |

### Recommendation

```python
# scope: unit, then one integration smoke
@pytest.mark.parametrize("exc", [
    pytest.param(FileNotFoundError("no multiproc dir"), id="missing-multiproc-dir"),
    pytest.param(PermissionError("denied"), id="perm-denied"),
    pytest.param(OSError("generic"), id="generic-oserror"),
])
def test_safe_inc_swallows_OSError_family(monkeypatch, caplog, exc):
    counter = mock.MagicMock()
    counter.labels.return_value.inc.side_effect = exc
    with caplog.at_level(logging.WARNING, logger="website.features.observability.safe_metrics"):
        result = safe_inc(counter, ("gemini", "youtube", "dense_verify"))   # must not raise
    assert result is None
    assert counter.labels.return_value.inc.called
    assert any(
        r.levelname == "WARNING" and r.exc_info is not None
        for r in caplog.records
    )
```

Plus one integration test using `TestClient(app, raise_server_exceptions=False)` that monkeypatches the same symbol to raise, posts to `/api/zettels/add`, and asserts response 202 + eventual terminal with proper RFC 9457 fallback (NOT `error: null`).

### Risks

1. **Testing the mock, not the behavior** — the contract is "request returns successful envelope even when metric backend is broken." Always assert on the response, not just on the mock call.
2. **Patching the wrong namespace** — patches at `prometheus_client.Counter.labels` are cross-test-polluting and brittle. Patch the bound symbol in `safe_metrics` instead.

---

## Updated PR plan vs. my earlier proposal

| Item | Earlier proposal (pre-research) | Post-research |
|---|---|---|
| Defensive emit | inline `try/except OSError` at 4 sites in `budget.py` | **single `safe_metrics` helper module** + 4 sites route through it; ALSO ship the emit-failure counter + rate-limited logging. ~25-30 lines new vs ~12. |
| Multiproc dir | `os.makedirs(...)` in lifespan-start | **move dir off `/tmp` to `/app/var/prom`** + lifespan-start `os.makedirs(exist_ok=True)` + optional stale-file wipe. Dockerfile change too. |
| Catch-all | "default-else branch with redacted detail" | **canonical RFC 9457 fallback** (`about:blank` + `internal_error` + static generic detail + `X-Operation-Id` header), and the redaction is by-construction (the fallback never reads `exc`). |
| Tests | "unit test for budget.py emit-swallowing + regression test" | **parametrize over OSError family**, unit + 1 integration, `TestClient(raise_server_exceptions=False)`, caplog + side-effect both. |
| Probe | "docker exec ls /tmp/prom_multiproc" | unchanged — but expand to also check `/app/var/prom` after the dir move. |

Net: same shape, but every item gains a research-grounded refinement that closes a class of failure I would otherwise have shipped past.

---

## Decision matrix — what needs your explicit approval

| # | Sub-decision | Default if you say "yes" | Risk if you say "no" |
|---|---|---|---|
| 1a | Single `safe_metrics` helper module (not inline `try/except`) | new file `website/features/observability/safe_metrics.py`; refactor `budget.py:174-188` | inline pattern works but harder to evolve; OTel migration later would be 4× the diff |
| 1b | Emit-failure counter + absence alerts | `app_metric_emit_failures_total{metric, errno}` + Grafana alert rule | swallow ships *without* visibility → silent drift; metric values look correct but are missing data |
| 1c | Rate-limited swallow logger (1 per 60 s per signature) | use `ratelimitingfilter` or hand-rolled dedup in the helper | uncapped logs flood stdout when `/tmp` is wiped — log-bill spike + droplet disk pressure |
| 2a | Move dir to `/app/var/prom` (vs. `tmpfs`-mount `/tmp/prom_multiproc`) | new Dockerfile path + env update | tmpfs is fine too but trades ~3 % RAM on a 2 GB droplet |
| 2b | Lifespan-start `os.makedirs(exist_ok=True)` | in `website/main.py` startup | the move alone is enough if the new path never gets wiped; insurance recommended |
| 2c | Wipe stale `*.db` files at lifespan-start | `glob` + `os.unlink` swallowing `OSError` | Nautobot-style accumulation if you ever enable `gunicorn --max-requests`; otherwise no observable effect |
| 3a | Default-else returns the static RFC 9457 fallback | `_async_failure_error_payload` never returns `None`; `core.operations.error` is never `NULL` | the `code=null` cohort (4/8 in 24 h) continues; ops triage stays painful |
| 3b | `X-Operation-Id` response header on every problem body | small middleware change in `_problem` JSONResponse builder | curl/fetch debugging stays harder; not a regression — additive only |
| 4 | Test pattern: parametrize OSError family + caplog + integration `TestClient(raise_server_exceptions=False)` | matches existing `test_problem_shape.py` style | other patterns also work but diverge from the repo's current style |
| 5 (probe) | `docker exec zettelkasten-blue ls -la /tmp/prom_multiproc /app/var/prom` post-deploy | one-line operator command, no code | you won't know whether the wipe is intermittent vs persistent on the *new* path |

The most-load-bearing approvals are **1a + 1b + 2a + 3a**. Everything else is refinement.

---

## Citations (deduplicated across all four sub-reports, recent first)

**Spec / canon:**
- RFC 9457 — Problem Details for HTTP APIs, Jul 2023 — `https://www.rfc-editor.org/rfc/rfc9457.html`
- OpenTelemetry — Error Handling spec — `https://opentelemetry.io/docs/specs/otel/error-handling/`
- OWASP API Security Top 10 — 2023 edition, API8 misconfiguration — `https://owasp.org/API-Security/editions/2023/en/0xa8-security-misconfiguration/`
- W3C Trace Context, X-Request-Id draft, AIP-193 Google error model

**`prometheus_client` directly:**
- Official multiprocess docs — `https://prometheus.github.io/client_python/multiprocess/`
- Source: `client_python/multiprocess.py`
- Issues: `#127`, `#275`, `#425`, `#599`, `#939` — multiproc fragility, `mark_process_dead` semantics, FileNotFoundError races

**Reference impls:**
- `prometheus-fastapi-instrumentator` — `https://github.com/trallnag/prometheus-fastapi-instrumentator` (and its #108 — swallow-done-wrong cautionary tale)
- `django-prometheus` — exports docs (vendor-blessed path guidance)
- `nautobot/nautobot#4234` — `/prom_cache` accumulation → inode exhaustion → wipe-before-startup fix
- `jonashaag/prometheus-multiprocessing-example` — minimal working pattern most tutorials copy

**Grown-up shops:**
- Stripe API errors — `https://docs.stripe.com/api/errors`; observability blog on AWS — `https://aws.amazon.com/blogs/mt/how-stripe-architected-massive-scale-observability-solution-on-aws/`
- Anthropic API errors — `https://platform.claude.com/docs/en/api/errors`
- OpenAI server-error shape — community thread + docs
- GitHub `X-GitHub-Request-Id`, AWS `x-amzn-requestid`
- Grafana Labs meta-monitoring playbook — `https://grafana.com/blog/...meta-monitoring-prometheus-servers-to-monitor-all-other-prometheus-servers...`

**Testing:**
- FastAPI Discussion #6248 — testing custom error handlers
- Ruff `BLE001` rule docs — `https://docs.astral.sh/ruff/rules/blind-except/`
- pytest caplog + monkeypatch docs
- Honeycomb `beeline-python` test_trace.py — canonical "instrumentation must absorb errors" pattern
- Starlette #1175 — `ServerErrorMiddleware` routing of `Exception` handler

**Industry context for path placement:**
- systemd.io — Temporary Directories spec
- containers/podman#7852 — host `systemd-tmpfiles` reaching into container storage
- Ploetzli 2025 — read-only container best practices
- GitLab forum thread on its production deployment

**Practitioner:** `shiriev.ru` FastAPI + Gunicorn + Prometheus multiprocess walkthrough
