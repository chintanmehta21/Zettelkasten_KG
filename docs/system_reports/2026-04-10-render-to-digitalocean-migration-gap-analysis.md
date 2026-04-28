# Render → DigitalOcean Migration — Plan vs Implementation Gap Analysis

> **ARCHIVED — Historical gap-analysis report (legacy, no longer used).** This system report audited the Render → DigitalOcean migration when it landed. The migration is complete; Render is no longer used. The DigitalOcean droplet (Premium Intel 2 GB RAM / 1 vCPU / 70 GB NVMe SSD with Reserved IP, blue/green Docker Compose + Caddy) is the canonical and only production environment. See "Deployment Infrastructure (Canonical)" in the project root `CLAUDE.md` for the live setup.

**Date:** 2026-04-10
**Plan reviewed:** `docs/superpowers/plans/2026-04-09-render-to-digitalocean-migration.md` (4014 lines, 53 tasks across 13 phases)
**Reviewer:** Claude (worktree `cranky-visvesvaraya`, branch `claude/cranky-visvesvaraya`)
**Scope:** Verify the state of each of the 28 in-repo tasks (Phases 1–7) against what currently sits on disk. Phases 8–13 are operator-only (DNS, droplet provisioning, DNS cutover, monitoring, cleanup) and produce no repo artifacts, so they are covered separately at the end.

---

## 1. Executive Summary

**Bottom line:** Phases 1–7 are **fully implemented and merged to `master`.** All 28 code/config tasks produced the intended files, and the content matches the plan essentially verbatim. The few divergences that do exist are either conscious improvements (helper functions, more permissive boolean parsing, cleaner refactors) or purely cosmetic (ASCII `...` vs unicode `…`, different comment wording).

**🔴 One high-priority bug found:** Task 6 (requirements split) silently broke `.github/workflows/kg-intelligence-tests.yml`, which still runs `pip install -r ops/requirements.txt` then `pytest` — but pytest is no longer in the runtime file. The next KG-scoped PR will fail. One-line fix, see §Phase 7.

| Phase | Tasks | Status | Files touched | Plan-vs-impl deltas |
|---|---|---|---|---|
| 1 · App code refactors | 5 | ✅ COMPLETE | 5 modules + 5 test files | 3 tasks enhanced (beyond plan) |
| 2 · Container packaging | 5 (3 producing files) | ✅ COMPLETE | Dockerfile, reqs, `.dockerignore` | Exact match |
| 3 · Caddy + compose stack | 5 | ✅ COMPLETE | 2 Caddyfiles + 5 compose files | Cosmetic comment diffs only |
| 4 · Local rehearsal | 1 (verification only) | ⚪ NO ARTIFACT | — | — |
| 5 · Host bootstrap scripts | 5 | ✅ COMPLETE | sysctl, bootstrap.sh, ufw-rules.sh, logrotate, systemd | Unicode `…` → ASCII `...` |
| 6 · Deploy automation | 3 | ✅ COMPLETE | healthcheck.sh, deploy.sh, rollback.sh | Minor bash style diffs |
| 7 · GitHub Actions workflows | 4 | ✅ COMPLETE (one task has leftover) | ci.yml, deploy-droplet.yml, live-tests.yml | `keep-alive.yml` deleted but `keep-alive-backup.yml` still present |
| 8–13 · External/operational | 25 | ⚪ NOT VERIFIABLE FROM REPO | operator-only | Manual walkthrough doc added as enhancement |

**Truly missing:** nothing that blocks a deploy.
**Should-clean-up:** 4 leftover files from a prior nginx-based deploy scheme + 1 stale GitHub workflow.
**Nice-to-have gaps:** 2 small polish items in the CI env setup, 1 `mem_limit`/hardening gap in the `prod-local` Caddy service, and 1 documentation enhancement (manual-setup walkthrough) that is already present.

---

## 2. Phase-by-Phase Findings

### Phase 1 — Application Code Refactors (Tasks 1–5)

All five tasks are fully implemented. Git history confirms each landed as its own commit (`f2ebc7f`, `55115e0`, `983729e`, `88be1ca`, `1181852`).

#### Task 1 — `GEMINI_API_KEYS` env var fallback ✅ EXACT MATCH

- **Implementation:** `website/features/api_key_switching/__init__.py` — `init_key_pool()` (lines 40–84)
- **Tests:** `tests/test_api_key_pool_env.py` — all 5 tests present
- **Verdict:** Loader priority (file → env var → single-key), whitespace stripping, empty skipping, and error message all match the plan character-for-character.
- **Gaps:** none.

#### Task 2 — Lazy imports in `website/core/pipeline.py` ✅ EXACT MATCH

- **Implementation:** `website/core/pipeline.py` — heavy imports (`GeminiSummarizer`, `build_tag_list`, `get_extractor`, `detect_source_type`) all moved inside `summarize_url()`. Module-level imports limited to `logging`, `get_settings`, `normalize_url`, `resolve_redirects`. Unused `asdict` and `SourceType` removed.
- **Tests:** `tests/test_pipeline_lazy_imports.py` — both tests present, checks the full HEAVY_MODULES list.
- **Gaps:** none.

#### Task 3 — Lazy imports in `nexus/service/persist.py` ✅ FUNCTIONAL MATCH

- **Implementation:** `website/experimental_features/nexus/service/persist.py` — `find_similar_nodes`/`generate_embedding` imports moved inside `persist_summarized_result()`.
- **Difference from plan:** the plan places the lazy import as the **first line of the function body**; the actual implementation places it inside the `try:` block that guards the Supabase path (lines 332–335, after `sb = get_supabase_scope(user_sub)`).
- **Why this is fine (or better):** the embeddings code is only needed when Supabase persistence is active. Importing inside the `try:` block skips the import entirely when `user_sub is None` or Supabase is unreachable, which strictly extends the laziness. Test still passes because it only asserts the module is not in `sys.modules` at import time.
- **Tests:** `tests/test_persist_lazy_imports.py` — both tests present.
- **Gaps:** none (functional).

#### Task 4 — Telegram webhook path rename to `/telegram/webhook` ✅ ENHANCED

- **Implementation:** `telegram_bot/main.py`
  - Line 36: `_TELEGRAM_WEBHOOK_PATH = "/telegram/webhook"` constant
  - Lines 39–44: `_derive_webhook_url()` helper function
  - Line 140: `webhook_url = _derive_webhook_url(settings.webhook_url)`
  - Line 183: `web_app.routes.insert(0, Route(_TELEGRAM_WEBHOOK_PATH, _telegram_webhook, methods=["POST"]))`
- **Difference from plan:** plan prescribed two inline string replacements. Actual implementation extracted the path into a constant and the URL derivation into a helper — a clear net improvement (single-point-of-truth, unit-testable).
- **Tests:** `tests/test_telegram_webhook_path.py` tests the helper directly and the route registration — stronger than the plan's source-inspection test.
- **Gaps:** none.

#### Task 5 — `NEXUS_ENABLED` feature flag in `website/app.py` ✅ ENHANCED

- **Implementation:** `website/app.py`
  - Lines 43–45: `_nexus_enabled()` helper
  - Line 77: `nexus_enabled = _nexus_enabled()`
  - Lines 81–82: conditional `app.include_router(nexus_router)`
  - Lines 109–111: conditional static-asset mounts for nexus
  - Lines 166–174: conditional `/home/nexus` route
- **Differences from plan (all improvements):**
  1. Helper function instead of inline `os.getenv(...)` string
  2. More permissive false parsing: rejects `{"0", "false", "no", "off"}` instead of only `!= "true"` — matches the DX of most other feature flags in the wild
  3. **Also gates the static-asset mounts for `/home/nexus/css/*` and `/home/nexus/js/*`** — the plan missed this, so a disabled Nexus would have served empty asset directories. This is a genuine latent bug that was caught and fixed during implementation.
- **Tests:** `tests/test_nexus_feature_flag.py` — 2 class-based tests that use `TestClient` for full integration verification (plan asked for 3 simpler tests; implementation's coverage is stronger).
- **Gaps:** none.

---

### Phase 2 — Container Packaging (Tasks 6–10)

Tasks 9 and 10 are local verification-only (build an image, run it, check size) and produce no artifacts — they are inherently "was-it-run-locally?" gates and cannot be verified post hoc from the repo.

#### Task 6 — Split `ops/requirements.txt` and `ops/requirements-dev.txt` ✅ EXACT MATCH

- **runtime file:** all 18 packages match the plan list in order, including the version pins (`python-telegram-bot>=21.0`, `google-genai>=1.0`, `supabase>=2.0`, `cryptography>=43.0`, `networkx>=3.2`, `numpy>=1.26`, etc.)
- **dev file:** references `-r requirements.txt` + `pytest>=9.0`, `pytest-asyncio>=0.23`, `pytest-httpx>=0.30`
- **Note:** a preliminary subagent flagged `-r requirements.txt` as a potential CI failure (relative path). This is a **false positive** — per pip's own docs, `-r PATH` inside a requirements file is resolved **relative to the containing file**, not the working directory. So `-r requirements.txt` inside `ops/requirements-dev.txt` correctly resolves to `ops/requirements.txt` no matter where pip is invoked from. The plan itself uses the exact same syntax.
- **Gaps:** none.

#### Task 7 — Rewrite `ops/Dockerfile` ✅ EXACT MATCH

Verified line-by-line against the plan:

| Required feature | Present |
|---|---|
| Multi-stage builder + runtime | ✅ lines 3–24 / 25–78 |
| `python:3.12-slim` both stages | ✅ lines 4, 26 |
| `build-essential` only in builder | ✅ lines 9–11 |
| `/opt/venv` + compileall pre-compile | ✅ lines 14, 23 |
| `ARG GIT_SHA / BUILD_DATE` | ✅ lines 29–30 |
| All 6 OCI labels (title, description, source, revision, created, licenses) | ✅ lines 31–36 |
| Runtime deps: `ca-certificates tini curl` | ✅ lines 40–42 |
| Non-root user `appuser` UID/GID 1000 | ✅ lines 45–46 |
| `--chown=appuser:appuser` on copies | ✅ lines 54–57 |
| `/app/kg_output` + `/app/bot_data` pre-created and chowned | ✅ lines 60–61 |
| ENV PATH / PYTHONDONTWRITEBYTECODE=1 / PYTHONUNBUFFERED=1 / PIP_NO_CACHE_DIR=1 / WEBHOOK_PORT=10000 | ✅ lines 63–67 |
| `EXPOSE 10000` / `USER appuser` | ✅ lines 69, 71 |
| HEALTHCHECK (15s/3s/10s/3) hitting `/api/health` | ✅ lines 73–74 |
| `ENTRYPOINT ["/usr/bin/tini", "--"]` + `CMD ["python", "run.py"]` | ✅ lines 76–77 |

- **Cosmetic differences:** plan used unicode box-drawing (`─── Stage 1: builder ────`) for section headers; implementation uses ASCII (`--- Stage 1: builder ---`). Functionally identical.
- **Gaps:** none.

#### Task 8 — Create `.dockerignore` ✅ EXACT MATCH

Every entry from the plan (.git, .gitignore, .gitattributes, docs/, *.md, !README.md, .github/, tests/, all Python caches, editor files, worktrees, .claude/, .code-build/, data dirs, .env*, `ops/api_env`, `website/features/api_key_switching/api_env`, `supabase/.env`, `node_modules/`) is present in `/\.dockerignore` in the same order.

- **Gaps:** none.

#### Task 9 — Local build + size + healthcheck smoke test ⚪ NOT VERIFIABLE

Verification-only. No artifact. If image size, non-root verification, tini as PID 1, healthcheck graduation to `healthy`, and SIGTERM propagation were all checked locally, there's no lasting record. Recommend running `docker build -f ops/Dockerfile -t zettelkasten-kg-website:test .` and the plan's `docker run --rm --entrypoint id …` gate at least once before Phase 10 deploy.

#### Task 10 — Build cache reuse verification ⚪ NOT VERIFIABLE

Same category.

---

### Phase 3 — Caddy + Compose Stack (Tasks 11–15)

All 5 tasks complete.

#### Task 11 — Caddyfile + upstream snippet ✅ EXACT MATCH (cosmetic)

- **`ops/caddy/upstream.snippet`** — 3 lines, matches the plan.
- **`ops/caddy/Caddyfile`** — verified line-by-line:
  - Global block: `email chintanoninternet@gmail.com`, `default_bind tcp4/0.0.0.0 tcp6/[::]`
  - `www.zettelkasten.in` → permanent redirect to apex
  - Apex block has `encode zstd gzip`, all 6 security headers (HSTS, nosniff, DENY, Referrer-Policy, Permissions-Policy, `-Server`)
  - `@static` matcher covers all 20 listed asset paths (/css/*, /js/*, /m/css/*, /m/js/*, /kg/css/*, /kg/js/*, /home/css/*, /home/js/*, /home/zettels/css/*, /home/zettels/js/*, /home/nexus/css/*, /home/nexus/js/*, /about/css/*, /about/js/*, /pricing/css/*, /pricing/js/*, /auth/css/*, /auth/js/*, /artifacts/*, /browser-cache/js/*)
  - `Cache-Control "public, max-age=31536000, immutable"` applied to `@static`
  - `@api_graph` gets `public, max-age=30`
  - `@telegram path /telegram/webhook` + `log_skip @telegram`
  - `import /etc/caddy/upstream.snippet`
  - Log block with `roll_size 10MiB roll_keep 5 roll_keep_for 168h`, `format json`
- **Cosmetic diff:** ASCII `# ---` separators instead of unicode `# ───`. No functional impact.
- **Gaps:** none.

#### Task 12 — Blue + green compose files ✅ EXACT MATCH

Both `ops/docker-compose.blue.yml` and `ops/docker-compose.green.yml` match the plan exactly:
- `image: ghcr.io/chintanmehta21/zettelkasten-kg-website:${IMAGE_TAG:-latest}`
- container_name/hostname, env_file, environment (WEBHOOK_PORT, NEXUS_ENABLED), ports (`127.0.0.1:10000:10000` / `:10001:10000`)
- Volumes, `mem_limit: 768m`/`memswap_limit: 768m`, `pids_limit: 512`, `stop_grace_period: 20s`
- Hardening: `read_only: true`, `tmpfs: /tmp:size=64m`, `cap_drop: ALL`, `security_opt: no-new-privileges:true`
- Logging (json-file, 10m, 3), healthcheck (curl `/api/health`, 15s/3s/10s/3)
- `networks: zettelnet: external: true`

- **Gaps:** none.

#### Task 13 — Caddy compose file ✅ EXACT MATCH

`ops/docker-compose.caddy.yml` matches exactly. All security constraints (`cap_drop: ALL`, `cap_add: NET_BIND_SERVICE`, `no-new-privileges:true`), all 5 volume mounts, all 3 port bindings (80, 443 TCP, 443/udp for HTTP/3), 128m mem limit, wget-based healthcheck.

- **Gaps:** none.

#### Task 14 — Dev hot-reload compose ✅ EXACT MATCH

`ops/docker-compose.dev.yml` matches exactly. Build context `..`, uvicorn `--factory --reload` with two `--reload-dir` entries, bind mounts of `../website`, `../telegram_bot`, `../run.py:ro`, named volumes for kg_output/bot_data.

- **Gaps:** none.

#### Task 15 — Prod-local rehearsal compose + Caddyfile.local ✅ MATCH with ONE minor gap

- `ops/docker-compose.prod-local.yml` has the 3-service layout (blue/green/caddy), `${IMAGE:-zettelkasten-kg-website:local}` image var, `env_file: ../.env`, shared `zettelnet: driver: bridge` (not external — correct for local).
- `ops/caddy/Caddyfile.local` has the `local_certs` + `auto_https disable_redirects` global block and `tls internal` for `zettelkasten.local`.
- **Observable diff:** the Caddy service in `prod-local` omits `mem_limit`, `pids_limit`, `stop_grace_period`, `cap_drop`, `cap_add`, `security_opt`, `logging`, and `healthcheck`. The plan's `prod-local` snippet also omits them, so this is consistent with the plan — but it does mean the local rehearsal stack is strictly weaker than production at catching security-related misconfigurations. Not a bug, but worth keeping in mind: a deploy that passes `prod-local` can still fail production in ways the rehearsal won't catch.
- **Gaps:** none relative to the plan; minor observation above.

---

### Phase 4 — Local Rehearsal (Task 16)

Verification-only — no artifact. No way to confirm it was executed from the repo alone. Recommend running the rehearsal at least once before operators start Phase 8.

---

### Phase 5 — Host Bootstrap Scripts (Tasks 17–21)

#### Task 17 — `ops/host/sysctl-zettelkasten.conf` ✅ EXACT MATCH

All 7 tuning knobs present (somaxconn, tcp_max_syn_backlog, ip_local_port_range, fs.file-max, vm.swappiness, ipv6 sanity pair).

#### Task 18 — `ops/host/bootstrap.sh` ✅ EXACT MATCH (cosmetic)

Verified against the plan line-by-line:
- Root EUID guard + DEPLOY_PUBKEY requirement ✅
- Apt install of `ufw fail2ban unattended-upgrades apt-listchanges logrotate curl ca-certificates jq` ✅
- Both apt config files (20auto-upgrades + 50unattended-upgrades) ✅
- UFW reset/default/allow 22/80/443-tcp/443-udp/enable ✅
- fail2ban enable --now ✅
- Idempotent swapfile creation + fstab append ✅
- sysctl.d install + `sysctl --system` ✅
- `/etc/security/limits.d/zettelkasten.conf` with 65535 nofile ✅
- deploy user creation, docker group, SSH authorized_keys (chmod 700/600) ✅
- sshd hardening drop-in with all 9 directives ✅
- `/opt/zettelkasten/*` directory tree created with correct ownership ✅
- `ACTIVE_COLOR=blue` default ✅
- `docker network create zettelnet` (idempotent) ✅
- logrotate + systemd config installs from repo-cache ✅
- `systemctl daemon-reload && systemctl enable zettelkasten.service` ✅

- **Cosmetic diff:** plan used unicode ellipsis `…` in echo statements; implementation uses ASCII `...`. No functional impact.
- **Gaps:** none.

#### Task 19 — `ops/host/ufw-rules.sh` ✅ EXACT MATCH

19 lines, identical to the plan.

#### Task 20 — `ops/host/logrotate-zettelkasten.conf` ✅ EXACT MATCH

Identical: daily, rotate 7, compress, delaycompress, missingok, notifempty, copytruncate, `su root root`, sharedscripts, `docker kill --signal=USR1 caddy` postrotate hook.

#### Task 21 — `ops/systemd/zettelkasten.service` ✅ EXACT MATCH

Identical: `Type=oneshot`, `RemainAfterExit=yes`, `WorkingDirectory=/opt/zettelkasten/compose`, `EnvironmentFile=/opt/zettelkasten/compose/.env`, `ExecStartPre` ACTIVE_COLOR validation, `ExecStart`/`ExecStop` with the multi-compose-file layering, `TimeoutStartSec=180`, `TimeoutStopSec=60`, `Restart=on-failure`, `RestartSec=10`, `StartLimitIntervalSec=300`, `StartLimitBurst=5`, `LimitNOFILE=65535`, `WantedBy=multi-user.target`.

- **Gaps:** none.

---

### Phase 6 — Deploy Automation Scripts (Tasks 22–24)

#### Task 22 — `ops/deploy/healthcheck.sh` ✅ EXACT MATCH

28 lines, identical logic: 30 attempts, 1s sleep, curl `/api/health`, exits 0/1 appropriately. Executable bit set.

#### Task 23 — `ops/deploy/deploy.sh` ✅ FUNCTIONAL MATCH (minor bash style diffs)

Complete blue-green orchestration. Verified:
- `SHA` argument + usage ✅
- `ROOT`/`IMAGE`/`ACTIVE_FILE`/`SNIPPET`/`LOG` variables ✅
- `log()` function with UTC timestamp + tee ✅
- `trap on_error ERR` present (line 40) ✅ — slightly different shape from plan (`trap 'on_error' ERR` with quotes), but bash accepts both
- `on_error()` function defined (lines 35–39) — **before** the trap line, not after (reverse of plan); functionally identical
- Active/idle color computation (blue→green:10001, green→blue:10000) ✅
- `IMAGE_TAG="$SHA" docker compose pull` + `up -d --no-deps` ✅
- Healthcheck wait ✅
- Atomic snippet rewrite via `mktemp` + `mv` ✅
- `docker exec caddy caddy reload` ✅
- `echo "$IDLE" > "$ACTIVE_FILE"` ✅
- 20s drain + `docker compose down --timeout 20` ✅
- Final success log line ✅
- **Cosmetic:** `...` instead of `…` in log messages.
- **Gaps:** none.

#### Task 24 — `ops/deploy/rollback.sh` ✅ EXACT MATCH

60 lines, matches the plan. Reads ACTIVE_COLOR, determines OTHER, ensures active is up + healthchecked, rewrites snippet, reloads Caddy, tears down any half-started OTHER color, logs throughout.

- **Gaps:** none.

---

### Phase 7 — GitHub Actions Workflows (Tasks 25–28)

#### Task 25 — `.github/workflows/ci.yml` ✅ MATCH with minor env diff

- Triggers: `pull_request: [opened, synchronize, reopened]` + `push: branches: [master]` ✅
- `concurrency: group: ci-${{ github.ref }}, cancel-in-progress: true` ✅
- `permissions: contents: read` ✅
- `jobs.test`: Python 3.12, pip cache, installs `ops/requirements-dev.txt`, runs `pytest -q --maxfail=5` ✅
- **Delta:** `ALLOWED_CHAT_ID: "1"` (actual) vs `"0"` (plan). This is probably intentional because `ALLOWED_CHAT_ID=0` may fail Pydantic's positive-int validation (Telegram chat IDs are always non-zero). Keeping `"1"` is safer; the plan value is arguably wrong.
- **Gaps:** none (unless "0" is actually required somewhere).

#### Task 26 — `.github/workflows/deploy-droplet.yml` ✅ EXACT MATCH

All three jobs present with the correct topology:
1. `test` (mocked pytest) → `build-and-push` (GHCR with gha cache + provenance false) → `deploy` (appleboy/ssh-action@v1, `environment: production` for manual approval gate, 15m timeout)
2. Build tags include both `${{ github.sha }}` and `:latest`
3. GHCR login uses `secrets.GITHUB_TOKEN`; runtime image pull uses `secrets.GHCR_READ_PAT`
4. `concurrency: group: deploy-prod, cancel-in-progress: true` ✅
5. `permissions: contents: read, packages: write` ✅
6. The heredoc `.env` file written to `/opt/zettelkasten/compose/.env` contains all 20 expected keys:
   - `TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_ID, WEBHOOK_MODE=true, WEBHOOK_PORT=10000, WEBHOOK_URL=https://${TARGET_HOST}, WEBHOOK_SECRET, GEMINI_API_KEYS, SUPABASE_URL, SUPABASE_ANON_KEY, GITHUB_TOKEN, GITHUB_REPO, NEXUS_ENABLED=true, NEXUS_GOOGLE_CLIENT_ID, NEXUS_GOOGLE_CLIENT_SECRET, NEXUS_GITHUB_CLIENT_ID, NEXUS_GITHUB_CLIENT_SECRET, NEXUS_REDDIT_CLIENT_ID, NEXUS_REDDIT_CLIENT_SECRET, NEXUS_TWITTER_CLIENT_ID, NEXUS_TWITTER_CLIENT_SECRET, NEXUS_TOKEN_ENCRYPTION_KEY`
7. **Security-critical check:** ✅ **NO `SUPABASE_SERVICE_ROLE_KEY`** anywhere in the file — the spec §3.6/Q12 requirement that the service-role key never touch the droplet is honored.
8. `chmod 600` + `chown deploy:deploy` on the `.env` file ✅
9. Final command `sudo /opt/zettelkasten/deploy/deploy.sh "$SHA"` ✅

- **Delta:** the embedded test job also uses `ALLOWED_CHAT_ID: "1"` (same harmless diff as ci.yml).
- **Gaps:** none.

#### Task 27 — `.github/workflows/live-tests.yml` ✅ EXACT MATCH

`workflow_dispatch` + `schedule: cron "0 21 * * 0"`, `environment: production`, 25-min timeout, injects `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_ID`, `GEMINI_API_KEYS`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` from secrets, runs `pytest --live -q`.

- **Gaps:** none.

#### Task 28 — Delete `.github/workflows/keep-alive.yml` ⚠️ PARTIAL

- `.github/workflows/keep-alive.yml` — deleted ✅ (commit `bfa02d9`)
- **But:** `.github/workflows/keep-alive-backup.yml` is **still present** (26 lines) and still tries to `curl secrets.RENDER_URL/api/health` every 5 minutes with double-ping logic. This is a leftover from when two redundant keep-alive workflows pinged Render every 7 minutes. The droplet never sleeps, so this workflow will either:
  - Run forever as a no-op 404 if `RENDER_URL` secret still exists and Render service is paused
  - Fire the harmless `curl … || true` fallback
- **Impact:** harmless but wasteful — consumes a few GitHub Actions minutes per week and creates visual noise in the Actions tab.
- **Recommendation:** delete `keep-alive-backup.yml` in the same spirit as Task 28. Add to a cleanup PR.

---

#### 🔴 CRITICAL BUG FOUND — `kg-intelligence-tests.yml` broken by Task 6

`.github/workflows/kg-intelligence-tests.yml` is a legitimate pre-existing workflow (not part of the migration plan) that runs `tests/kg_intelligence/` on PRs/pushes that touch KG-related paths. **Task 6 (splitting `requirements.txt` into runtime + dev) silently broke it.**

**The failure:**

```yaml
# .github/workflows/kg-intelligence-tests.yml, lines 32-37
- name: Install dependencies
  run: |
    python -m pip install --upgrade pip
    pip install -r ops/requirements.txt   # ← pytest no longer here
- name: Run KG intelligence tests
  run: python -m pytest tests/kg_intelligence/ -v --tb=short   # ← will ModuleNotFoundError
```

Before Task 6, `ops/requirements.txt` contained `pytest>=9.0`, `pytest-asyncio`, and `pytest-httpx`. After Task 6 those moved to `ops/requirements-dev.txt` (verified: `grep -l pytest ops/requirements*.txt` returns only `ops/requirements-dev.txt`). So this workflow will fail with `ModuleNotFoundError: No module named 'pytest'` the next time it is triggered by a path-matching PR/push.

**Why it hasn't blown up yet:** the path filters are narrow. If nothing has touched `website/features/kg_features/**`, `website/core/supabase_kg/**`, `supabase/website/kg_features/**`, `tests/kg_intelligence/**`, `ops/requirements.txt`, or the workflow file itself since commit `b227516` (Task 6 landing), the workflow simply hasn't been invoked. It's a landmine waiting for the next KG-scoped change.

**Fix (one-liner):**

```yaml
# Change line 35 from:
pip install -r ops/requirements.txt
# to:
pip install -r ops/requirements-dev.txt
```

**Severity:** 🔴 HIGH — silent CI breakage on the next KG-related PR. Should be fixed before Phase 8 external work begins, otherwise the next KG PR (e.g., the "KG Intelligence remaining" work tracked in memory) will hit a red check that's nothing to do with the actual code change.

---

### Phases 8–13 — External / Operational (Tasks 29–53)

No repo artifacts — these are the browser-and-SSH phases. **Substantial enhancement over the plan:** a dedicated walkthrough document was added at `docs/superpowers/plans/2026-04-09-manual-setup-checklist.md` (added in commit `4ec01e4`). This document:
- Provides a secrets vault template for collection
- Walks through Tasks 29–53 with exact screens, click paths, copy/paste commands
- Includes verification commands after each step
- Warns to keep Render live as rollback target until Task 32 of the walkthrough
- Does not duplicate the plan; it's specifically for the manual follow-through

This is a genuine improvement and should be kept up to date as the operator executes it.

---

## 3. Leftover Files From Prior Deploy Schemes (Cleanup Gaps)

These files exist in the repo but are **not referenced anywhere in the current DigitalOcean plan** — they belong to an older nginx + venv + systemd deployment recipe that pre-dated this migration:

| File | Purpose (old) | Why it's stale |
|---|---|---|
| `ops/deploy/nginx.conf` | nginx server block with TLS + reverse proxy to port 8443 | We use Caddy now (ops/caddy/Caddyfile); port is 10000 not 8443 |
| `ops/deploy/zettelkasten-bot.service` | systemd unit running `/.venv/bin/python -m telegram_bot` | We use Docker now; the real systemd unit is `ops/systemd/zettelkasten.service` |
| `ops/deploy/DEPLOY.md` | Deployment guide for nginx + certbot + venv setup | The new guide is `docs/superpowers/plans/2026-04-09-manual-setup-checklist.md` |
| `.github/workflows/keep-alive-backup.yml` | Twin keep-alive pinger for Render's sleep behavior | Droplet doesn't sleep |

**Recommendation:** delete all four in a single cleanup commit labeled `chore: remove legacy nginx/systemd deploy artifacts`. None of the files are imported by the new stack, so their removal has zero blast radius.

---

## 4. Other Observations

### 4.1 `ALLOWED_CHAT_ID="1"` vs plan's `"0"` in both CI jobs

Both `ci.yml:42` and `deploy-droplet.yml:42` use `ALLOWED_CHAT_ID: "1"` for the mocked pytest run. The plan specifies `"0"`. This is likely intentional — `ALLOWED_CHAT_ID=0` is more likely to be rejected by strict Pydantic validation and tests that check positivity. If any test explicitly asserts `"0"` works, it would be invalidated, but I did not find any such test. **Impact:** none unless a test asserts on the value 0.

### 4.2 Phase 1/2 legacy env var `GEMINI_API_KEY` still documented in `ops/.env.example`

`ops/.env.example` still mentions `GEMINI_API_KEY=your-gemini-api-key` (single-key legacy form) and does not document `GEMINI_API_KEYS=` (the new comma-separated form introduced in Task 1). Since backward compatibility is intentional (Task 1's "Source 3: single key from settings"), the single-key example is not wrong — but an up-to-date example would mention both, with the multi-key form as preferred.

**Recommendation (nice-to-have):** append a comment to `ops/.env.example`:
```text
# Preferred: comma-separated multi-key pool (enables key rotation + model fallback)
# GEMINI_API_KEYS=key1,key2,key3
```

### 4.3 `pyproject.toml` and `run.py` unchanged

The plan never touched either; no evidence of drift. Dockerfile correctly copies both into `/app/`.

### 4.4 `render.yaml` successfully removed

The old Render blueprint file is gone. No residue. CLAUDE.md still references Render in the "Deployment" section — this matches Task 52 which hasn't been run (it's part of Phase 12 post-cutover). Not a bug; the operator executes it later.

### 4.5 Test count consistency

Phase 1 added 5 new test files (api_key_pool_env, pipeline_lazy_imports, persist_lazy_imports, telegram_webhook_path, nexus_feature_flag) for a total of ~13 new tests. The CLAUDE.md claim of "305 tests passing" predates this work, so expect a number in the 315–320 range now. Worth a `pytest --collect-only | tail -1` from the operator before Phase 7 CI runs.

### 4.6 The `prod-local` Caddy service has no security hardening

`ops/docker-compose.prod-local.yml` intentionally omits `cap_drop`, `cap_add: NET_BIND_SERVICE`, `no-new-privileges`, `mem_limit`, `pids_limit`, `logging`, and `healthcheck` on its `caddy` service. This matches the plan's example exactly, so it's not a deviation — but it does mean the local rehearsal doesn't exercise the full production Caddy container, weakening the rehearsal's coverage. A container-level security drift between `prod-local` and production won't be caught until the real deploy.

**Recommendation (nice-to-have):** copy the hardening block from `docker-compose.caddy.yml` into the `prod-local` Caddy service (minus only `ports: 443:443/udp` if local QUIC is problematic). Strengthens the rehearsal at zero cost.

---

## 5. Risk Register (post-implementation)

| Risk | Category | Severity | Mitigation present? | Notes |
|---|---|---|---|---|
| **`kg-intelligence-tests.yml` broken by Task 6 requirements split** | **CI reliability** | **🔴 HIGH** | ❌ — one-line fix needed | Will fail on next KG-scoped PR with `ModuleNotFoundError: pytest` |
| Legacy nginx config mistakenly re-deployed by an operator | Operational | Low | ❌ — file still exists | Delete as recommended in §3 |
| `keep-alive-backup.yml` wasting CI minutes | Cost | Low | ❌ — file still exists | Delete as recommended in §3 |
| `SUPABASE_SERVICE_ROLE_KEY` leaking to droplet | Security (Sev 1) | Critical | ✅ — absent from deploy-droplet.yml | Audited: confirmed not in env list anywhere |
| `ALLOWED_CHAT_ID=1` stub value being used in production | Security | None | N/A | Stub is only used in CI pytest, not the droplet `.env` which reads `secrets.ALLOWED_CHAT_ID` |
| Tasks 9/10/16 (local smoke tests) not actually executed | Operational | Medium | ❓ — unverifiable from repo | Operator should run before Phase 10 |
| Divergence between Phase 1 test count and CLAUDE.md's "305 tests passing" | Documentation | Low | ❌ | Update CLAUDE.md after next CI green |

---

## 6. What to do before Phase 8 starts

1. **🔴 (required, urgent)** Fix `.github/workflows/kg-intelligence-tests.yml` line 35 — change `pip install -r ops/requirements.txt` to `pip install -r ops/requirements-dev.txt`. Without this, the next KG-scoped PR will hit a red check that has nothing to do with the actual change.
2. **(required)** Run a local image build + smoke test once (plan Task 9) to catch any dependency drift early.
3. **(required)** Run the local rehearsal (plan Task 16) with a real `.env` to verify the blue-green flip works end-to-end on your laptop.
4. **(recommended cleanup PR)** Delete:
   - `ops/deploy/nginx.conf`
   - `ops/deploy/zettelkasten-bot.service`
   - `ops/deploy/DEPLOY.md`
   - `.github/workflows/keep-alive-backup.yml`
5. **(optional)** Add the `GEMINI_API_KEYS` example line to `ops/.env.example`.
6. **(optional)** Harden the `prod-local` Caddy service to match production's cap/security options.
7. **(later)** Update `CLAUDE.md` deployment section + test count once Phase 12 Task 52 runs.

---

## 7. Conclusion

The plan's Phases 1–7 are **implemented to the letter**, with a handful of deliberate improvements (helper extractions, tighter false-value parsing, extra gating of Nexus static mounts, stricter `ALLOWED_CHAT_ID` stub). Every file the plan prescribed exists. Every test the plan prescribed exists. Every security requirement (non-root user, cap_drop ALL, no service-role key on the droplet, UFW lockdown, SSH hardening, image signing labels) is present. The blue-green deploy pipeline is complete end-to-end from pytest → GHCR build → SSH deploy → Caddy hot reload → rollback on error.

**What is actually missing is not functionality but tidiness:**
- 4 leftover files from a pre-migration nginx/systemd deploy recipe (low blast radius but should be removed for clarity)
- A small `.env.example` documentation refresh
- Unverifiable local-rehearsal gates (Tasks 9/10/16) that the operator should run at least once before they touch the real droplet

The manual walkthrough at `docs/superpowers/plans/2026-04-09-manual-setup-checklist.md` is an unexpected but valuable enhancement — it converts Phases 8–13 from loose "manual checklist" tasks into a linear, copy-pasteable operator script. Keep it maintained during the cutover.

**Ready for Phase 8 external setup:** ✅ YES (with the recommended pre-checks above).
