#!/usr/bin/env bash
# ops/deploy/deploy.sh <image_sha>
#
# Blue-green deploy of a new image SHA.
#
# Side effects:
#   - Pulls ghcr.io/chintanmehta21/zettelkasten-kg-website:<sha>
#   - Brings up the idle color with the new image
#   - Waits for /api/health on the idle color
#   - Rewrites /opt/zettelkasten/caddy/upstream.snippet to point at idle color
#   - Reloads Caddy gracefully
#   - Hands off the previously-active color to background retirement
#   - Updates /opt/zettelkasten/ACTIVE_COLOR
#
# On failure: invokes rollback.sh and exits non-zero.

set -euo pipefail

# Use the deploy user's Docker credentials even when this script is invoked
# via `sudo` (HOME becomes /root otherwise, which has no GHCR auth).
export DOCKER_CONFIG="${DOCKER_CONFIG:-/home/deploy/.docker}"

SHA="${1:-}"
if [[ -z "$SHA" ]]; then
    echo "usage: $0 <image_sha>" >&2
    exit 2
fi

ROOT=/opt/zettelkasten
IMAGE="ghcr.io/chintanmehta21/zettelkasten-kg-website:${SHA}"
DRAIN_SECONDS="${DEPLOY_DRAIN_SECONDS:-45}"

# iter-03 §1C.4: extract ONLY the DEPLOY_* audit metadata from the container
# .env file (which the GH Actions workflow writes via the already-NOPASSWD-
# allowed sudo /usr/bin/tee path). Avoids full-sourcing the file so the rest
# of the .env (GEMINI_API_KEY, SUPABASE_*, etc.) stays
# scoped to the docker --env-file path and never leaks into deploy.sh's
# shell. Missing values fall through to the existing ${VAR:-default} guards
# below — manual operator deploys from a droplet shell still work.
ENV_FILE="${ENV_FILE:-/opt/zettelkasten/compose/.env}"
if [[ -r "$ENV_FILE" ]]; then
    while IFS='=' read -r _key _val; do
        case "$_key" in
            DEPLOY_GIT_SHA|DEPLOY_ID|DEPLOY_ACTOR|RAG_SMOKE_KASTEN_ID|RAG_SMOKE_EXPECT_TITLE|NARUTO_SMOKE_PASSWORD|SUPABASE_ANON_KEY_LEGACY_JWT|SUPABASE_URL)
                export "$_key=$_val"
                ;;
        esac
    done < <(grep -E '^(DEPLOY_(GIT_SHA|ID|ACTOR)|RAG_SMOKE_KASTEN_ID|RAG_SMOKE_EXPECT_TITLE|NARUTO_SMOKE_PASSWORD|SUPABASE_ANON_KEY_LEGACY_JWT|SUPABASE_URL)=' "$ENV_FILE" || true)
    unset _key _val
fi

MODEL_DIR="$ROOT/data/models"
if [[ ! -d "$MODEL_DIR" ]]; then
    mkdir -p "$MODEL_DIR"
    chown deploy:deploy "$MODEL_DIR"
fi

ACTIVE_FILE="$ROOT/ACTIVE_COLOR"
SNIPPET="$ROOT/caddy/upstream.snippet"
LOG="$ROOT/logs/deploy.log"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"
}

on_error() {
    log "DEPLOY FAILED at line $LINENO. Invoking rollback..."
    "$ROOT/deploy/rollback.sh" || true
    exit 1
}
trap on_error ERR

# C (2026-06 cutover): serve a graceful 503 "maintenance" page (the Caddyfile
# @maintenance matcher reads /data/maintenance.flag) during the sequential-deploy
# window instead of raw 502s. /api/health bypasses the matcher, so health probes
# and reload_caddy.sh's e2e cutover gate still work. The flag lives on the
# host-mounted caddy volume (host $ROOT/caddy/data == caddy container /data) and
# is toggled HOST-side here (not via docker exec) so cleanup can't fail even if
# the caddy container is down at exit. Best-effort: if the toggle can't run, the
# deploy proceeds unchanged. The EXIT trap removes the flag on EVERY exit path
# (success, FATAL exit, or rollback) so the site can never get stuck behind it.
MAINT_FLAG="$ROOT/caddy/data/maintenance.flag"
maint_window() {
    if [[ "${1:-}" == "open" ]]; then
        if touch "$MAINT_FLAG" 2>/dev/null; then
            chmod 644 "$MAINT_FLAG" 2>/dev/null || true
            log "[maint] graceful 503 window OPEN"
        else
            log "[maint] WARN: could not open maintenance window (proceeding; raw 502s during cutover)"
        fi
    else
        rm -f "$MAINT_FLAG" 2>/dev/null || true
    fi
}
trap 'maint_window close' EXIT
# Also fire cleanup on termination signals — the CI deploy step has an 8m
# command_timeout and the rag-smoke can retry up to ~12m, so an external SIGTERM
# is realistic; without this it would skip the EXIT trap and strand the flag
# (SIGKILL stays uncoverable; the next deploy or a manual rm clears it).
trap 'exit 143' TERM HUP INT

ACTIVE=$(cat "$ACTIVE_FILE")
if [[ "$ACTIVE" == "blue" ]]; then
    IDLE="green"
    IDLE_PORT=10001
else
    IDLE="blue"
    IDLE_PORT=10000
fi

log "Starting deploy: SHA=$SHA, ACTIVE=$ACTIVE, IDLE=$IDLE"

# ── PREFLIGHT (2026-08-01) ──────────────────────────────────────────────────
# Assert everything the LATER gates need, HERE — before anything is stopped.
#
# The 2026-07-31 outage had two halves. The famous one was a rotted fixture.
# The quieter one: the smoke gate had been SKIPPING for weeks because its
# credentials were absent, and a gate that cannot run had been treated as a
# gate that passed. That is the failure mode Kubernetes admission webhooks
# default against (`failurePolicy: Fail`) and that Nagios encodes as a distinct
# UNKNOWN exit state — "could not check" is not "checked and fine".
#
# Running these checks at the top is the whole point: a missing credential now
# costs a failed deploy with the old colour still serving, instead of an abort
# after the point of no return with nothing serving at all.
preflight_fail() {
    log "[preflight] FATAL: $1"
    log "[preflight] Nothing has been stopped; ${ACTIVE} is still serving."
    exit 3   # Nagios convention: 3 = UNKNOWN (could not run), never 0
}

if [[ "${RAG_SMOKE_REQUIRED:-1}" == "1" ]]; then
    [[ -n "${SUPABASE_URL:-}" ]] \
        || preflight_fail "SUPABASE_URL unset — the rag-smoke gate could not run."
    [[ -n "${SUPABASE_ANON_KEY_LEGACY_JWT:-}" ]] \
        || preflight_fail "SUPABASE_ANON_KEY_LEGACY_JWT unset — the rag-smoke gate could not run."
    [[ -n "${NARUTO_SMOKE_PASSWORD:-}" ]] \
        || preflight_fail "NARUTO_SMOKE_PASSWORD unset — the rag-smoke gate could not run."
fi
for _bin in curl docker python3; do
    command -v "$_bin" >/dev/null 2>&1 \
        || preflight_fail "required binary '${_bin}' not on PATH."
done
unset _bin
[[ -x "$ROOT/deploy/rollback.sh" ]] \
    || preflight_fail "rollback.sh missing or not executable — the fail-safe path is unavailable."
[[ -x "$ROOT/deploy/healthcheck.sh" ]] \
    || preflight_fail "healthcheck.sh missing or not executable."
log "[preflight] OK — creds, binaries and recovery scripts all present."

log "Pulling $IMAGE..."
IMAGE_TAG="$SHA" docker compose \
    -f "$ROOT/compose/docker-compose.${IDLE}.yml" \
    pull

# ── D-1 (KAS-11): apply pending Supabase migrations BEFORE traffic flips. ──
# Runs the new image as a short-lived helper container so the migration set
# matches the code about to be deployed. Failure is FATAL — we abort before
# touching the IDLE container so prod stays on the previous (working) color.
#
# Phase 8.5 v2-purge (2026-05-11): switched to --v2 so the deploy targets
# supabase/website/_v2/*.sql against SUPABASE_V2_DATABASE_URL. The legacy
# v1 migration tree (supabase/website/kg_public/migrations/) is unrunnable
# post-Phase-6 — every file there references public.kg_* tables that were
# dropped in 15_drop_legacy_tables.sql / 31_drop_legacy_pricing.sql. The
# canonical v2 manifest lives in-image at supabase/website/_v2/
# expected_schema.json (versioned with code), so we no longer mount an
# external manifest-out volume — operator updates the manifest by running
# `apply_migrations.py --v2 --update-manifest` against staging and
# committing the diff.

# Preflight: confirm a Supabase DB URL is in the env-file before we even
# spin the migration container. Post-Phase-6/8 there is a single Supabase
# project hosting only v2 schemas — SUPABASE_DB_URL and SUPABASE_V2_DATABASE_URL
# point at the same DSN. We accept either, and inject SUPABASE_V2_DATABASE_URL
# into the container env from SUPABASE_DB_URL when the v2-named var is absent
# (covers the case where the operator has only registered SUPABASE_DB_URL as
# a GH Actions secret). Without one of them apply_migrations --v2 exits with
# rc=2 (config error) — surface that as a clear deploy abort.
V2_URL_FROM_ENV=$(grep -E '^SUPABASE_V2_DATABASE_URL=' /opt/zettelkasten/compose/.env | head -n1 | cut -d= -f2- || true)
if [ -z "$V2_URL_FROM_ENV" ]; then
    V2_URL_FROM_ENV=$(grep -E '^SUPABASE_DB_URL=' /opt/zettelkasten/compose/.env | head -n1 | cut -d= -f2- || true)
fi
if [ -z "$V2_URL_FROM_ENV" ]; then
    log "[deploy] FATAL: neither SUPABASE_V2_DATABASE_URL nor SUPABASE_DB_URL in /opt/zettelkasten/compose/.env"
    exit 2
fi

log "[migration] Applying pending v2 Supabase migrations against prod..."
set +e
# iter-03 §1C.4: pass deploy provenance so apply_migrations can stamp each
# audit row with git SHA / deploy id / actor. Defaults guarantee non-null
# values even when this script is run outside CI (manual operator deploy).
docker run --rm --network host \
    --env-file /opt/zettelkasten/compose/.env \
    -e SUPABASE_V2_DATABASE_URL="$V2_URL_FROM_ENV" \
    -e DEPLOY_GIT_SHA="${DEPLOY_GIT_SHA:-$SHA}" \
    -e DEPLOY_ID="${DEPLOY_ID:-manual-$(date -u +%Y%m%dT%H%M%SZ)}" \
    -e DEPLOY_ACTOR="${DEPLOY_ACTOR:-$(whoami)}" \
    -e MIGRATION_MANIFEST_REQUIRED="${MIGRATION_MANIFEST_REQUIRED:-1}" \
    -e MIGRATION_MANIFEST_AUTOBOOTSTRAP="${MIGRATION_MANIFEST_AUTOBOOTSTRAP:-1}" \
    "$IMAGE" \
    python ops/scripts/apply_migrations.py --v2 \
        2>&1 | tee -a "$LOG"
MIG_RC=${PIPESTATUS[0]}
set -e
if [ "$MIG_RC" -ne 0 ]; then
    case "$MIG_RC" in
        2)
            log "[migration] CONFIG ERROR (rc=2) — ABORTING DEPLOY (no traffic flip, IDLE container not started)"
            log "[migration] Likely cause: missing/invalid SUPABASE_V2_DATABASE_URL or related env in /opt/zettelkasten/compose/.env"
            ;;
        3)
            log "[migration] DRIFT DETECTED (rc=3) — ABORTING DEPLOY (no traffic flip, IDLE container not started)"
            log "[migration] An applied migration's checksum no longer matches the file on disk."
            log "[migration] Runbook: ops/runbooks/migration-drift.md"
            log "[migration] Resolution paths (pick one, then re-deploy):"
            log "[migration]   (a) Revert if unintended:"
            log "[migration]       git checkout HEAD -- supabase/website/_v2/<file>.sql"
            log "[migration]   (b) Move to repeatable if intentional+idempotent code object (fn/view/RLS):"
            log "[migration]       mv supabase/website/_v2/<file>.sql supabase/website/_v2/repeatable/R__<name>.sql"
            log "[migration]   (c) Add a new versioned migration for structural changes (table/column)."
            ;;
        *)
            log "[migration] FAILED rc=$MIG_RC — ABORTING DEPLOY (no traffic flip, IDLE container not started)"
            ;;
    esac
    exit "$MIG_RC"
fi
log "[migration] OK — proceeding with blue/green flip."

# iter-03 §3.9 / Plan 2D.2: single-tenant kg_users allowlist gate.
# Skipped by default per operator decision — re-enable with
# DEPLOY_ALLOWLIST_GATE=1 once the live kg_users table has been reconciled
# (run ops/scripts/reconcile_kg_users.py --audit first).
if [ "${DEPLOY_ALLOWLIST_GATE:-0}" = "1" ]; then
    log "[deploy] Running kg_users allowlist gate..."
    set +e
    docker run --rm --network host \
        --env-file /opt/zettelkasten/compose/.env \
        "$IMAGE" \
        python -c "
import json, os, sys, psycopg
allowed = set(json.load(open('/app/ops/deploy/expected_users.json'))['allowed_auth_ids'])
with psycopg.connect(os.environ['SUPABASE_DB_URL']) as c, c.cursor() as cur:
    cur.execute('SELECT id::text FROM kg_users')
    live = {r[0] for r in cur.fetchall()}
unknown = live - allowed
if unknown:
    print(f'[deploy] FATAL: kg_users has unknown auth_ids: {unknown}', file=sys.stderr)
    sys.exit(1)
print('[deploy] kg_users allowlist OK')
" 2>&1 | tee -a "$LOG"
    GATE_RC=${PIPESTATUS[0]}
    set -e
    if [ "$GATE_RC" -ne 0 ]; then
        log "[deploy] FATAL: allowlist gate failed rc=$GATE_RC — ABORTING DEPLOY"
        exit "$GATE_RC"
    fi
else
    log "[deploy] kg_users allowlist gate SKIPPED (DEPLOY_ALLOWLIST_GATE!=1)"
fi

# iter-03 (2026-04-28): SEQUENTIAL blue/green - stop ACTIVE before starting
# IDLE. The 2 GB droplet cannot fit two simultaneous containers each holding
# the int8 BGE (267 MB resident) + 2 gunicorn workers + temp tensors during
# stage-2 rerank (peak +684 MB). Running both blue and green at once causes
# system-level OOM during the smoke probe q1 query. Trade-off: ~30-60s of
# 502s while Caddy points at the now-stopped ACTIVE color until the post-
# assert flip below. Acceptable for a single-droplet 2 GB target; iter-04
# can revisit (larger droplet, smaller stage1_k, or batched encoding).
# 2026-07-31 fail-safe, widened 2026-08-01. Everything between the ACTIVE
# stop below and the Caddy flip runs with NOTHING serving. Any gate that
# aborts in that window leaves Caddy pointed at a container that no longer
# exists -> raw 502s until an operator intervenes (this is exactly how the
# 2026-07-31 outage lasted ~10h). Every fatal exit in that window must call
# this first. Defined here, above the point of no return, so it is in scope
# for the cgroup/stage2 asserts as well as the smoke gate.
#
# This is NOT auto-rollback-on-failure-masking: callers still exit non-zero
# and still log FATAL, so the deploy fails loudly. It only restores serving.
restore_previous_color() {
    log "[fail-safe] ${1:-gate} aborted post-stop -- restoring previous color via rollback.sh"
    # 2026-08-01: capture the failed container's logs BEFORE docker rm. The
    # first version of this function removed the container immediately, which
    # destroyed the only record of why the gate failed — the 04:08Z smoke
    # failure could not be root-caused because its logs went with it.
    FAILED_LOG="$ROOT/logs/failed-${IDLE}-$(date -u +%Y%m%dT%H%M%SZ).log"
    mkdir -p "$ROOT/logs"
    if docker logs --tail 5000 "zettelkasten-${IDLE}" > "$FAILED_LOG" 2>&1; then
        chown deploy:deploy "$FAILED_LOG" 2>/dev/null || true
        log "[fail-safe] failed-container logs saved: $FAILED_LOG"
    else
        log "[fail-safe] WARN: could not capture logs for zettelkasten-${IDLE}"
    fi
    docker stop --time 20 "zettelkasten-${IDLE}" 2>/dev/null || true
    docker rm "zettelkasten-${IDLE}" 2>/dev/null || true
    "$ROOT/deploy/rollback.sh" || log "[fail-safe] WARN: rollback.sh failed -- site may need manual restore"
}

maint_window open
log "[seq-deploy] Stopping ACTIVE color ${ACTIVE} to free memory for ${IDLE}..."
ACTIVE_CONTAINER_NAME_PRE="zettelkasten-${ACTIVE}"
ACTIVE_CONTAINER_ID_PRE="$(docker inspect --format '{{.Id}}' "$ACTIVE_CONTAINER_NAME_PRE" 2>/dev/null || true)"
docker stop --time 20 "$ACTIVE_CONTAINER_NAME_PRE" 2>/dev/null || log "[seq-deploy] WARN: stop ${ACTIVE} returned non-zero (likely already stopped)"
docker rm "$ACTIVE_CONTAINER_NAME_PRE" 2>/dev/null || true
log "[seq-deploy] ${ACTIVE} stopped. Caddy will 502 until cutover (~30-60s)."

log "Starting $IDLE container with new image..."
IMAGE_TAG="$SHA" docker compose \
    -f "$ROOT/compose/docker-compose.${IDLE}.yml" \
    up -d --no-deps

log "Waiting for $IDLE healthcheck on port $IDLE_PORT..."
"$ROOT/deploy/healthcheck.sh" "$IDLE_PORT"

# iter-03 mem-bounded §2.10 (post-mortem): assert the cgroup limits the
# container actually ended up with match what the compose file declared.
# This guards against the silent-no-op failure mode where compose ceiling
# changes never reach the droplet (compose files stale / not synced) — a
# class of bug that bit iter-03 mid-rollout. Mismatch fails the deploy.
EXPECTED_MEM_MAX=1677721600        # 1600m == 1.5625 GiB (bumped from 1300m on 2026-04-28 - q1 OOM)
EXPECTED_SWAP_MAX=1048576000       # 1000m == 1.0 GiB swap budget per cgroup
ACTUAL_MEM_MAX=$(docker exec "zettelkasten-${IDLE}" cat /sys/fs/cgroup/memory.max 2>/dev/null || echo "missing")
ACTUAL_SWAP_MAX=$(docker exec "zettelkasten-${IDLE}" cat /sys/fs/cgroup/memory.swap.max 2>/dev/null || echo "missing")
log "[cgroup-assert] ${IDLE} memory.max=${ACTUAL_MEM_MAX} (expect ${EXPECTED_MEM_MAX})"
log "[cgroup-assert] ${IDLE} memory.swap.max=${ACTUAL_SWAP_MAX} (expect ${EXPECTED_SWAP_MAX})"
if [[ "$ACTUAL_MEM_MAX" != "$EXPECTED_MEM_MAX" ]] || [[ "$ACTUAL_SWAP_MAX" != "$EXPECTED_SWAP_MAX" ]]; then
    log "[cgroup-assert] FATAL: cgroup limits don't match compose."
    log "[cgroup-assert] Compose ceiling edits likely did not reach the droplet."
    # 2026-08-01: previously exited bare here, which was fail-DARK — the two
    # comments this replaces were both false after the sequential-deploy
    # rewrite: the previous color's container was already `docker rm`d ~25
    # lines above (so Caddy resolves a dead name and 502s), and the next
    # deploy uses `up -d --no-deps` with no --force-recreate.
    restore_previous_color "cgroup-assert"
    exit 87
fi
log "[cgroup-assert] ${IDLE} cgroup limits OK"

# iter-03 §8: assert that _STAGE2_SESSION (the int8 BGE reranker) actually
# loaded inside the running container. The lazy fp32 fallback is gone
# (cascade.py refactor); if the int8 file is missing or failed to import,
# the worker would 500 the first /api/rag/adhoc call. Catch it here pre-flip.
# Fail-loud, no auto-rollback (same pattern as cgroup-assert post-de-fang).
ACTUAL_STAGE2=$(docker exec "zettelkasten-${IDLE}" python -c "from website.features.rag_pipeline.rerank import cascade; print(cascade._STAGE2_SESSION is not None)" 2>/dev/null || echo "false")
log "[stage2-assert] ${IDLE} _STAGE2_SESSION_loaded=${ACTUAL_STAGE2} (expect True)"
if [[ "$ACTUAL_STAGE2" != "True" ]]; then
    log "[stage2-assert] FATAL: int8 BGE session not loaded in ${IDLE}."
    log "[stage2-assert] Likely causes: HF fetch failed in CI; image missing models/bge-reranker-base-int8.onnx; import error."
    # 2026-08-01: was fail-DARK (see cgroup-assert note above).
    restore_previous_color "stage2-assert"
    exit 88
fi
log "[stage2-assert] ${IDLE} stage2 session OK"

# iter-03 §8: pre-flip canonical RAG smoke probe. Fires the iter-03 q1 zk-org/zk
# two-fact lookup against the new color; asserts HTTP 200 + primary citation
# title == RAG_SMOKE_EXPECT_TITLE. Fail-loud, restores previous color on abort.
#
# JWT minted inline every deploy via Supabase password grant (NARUTO_SMOKE_PASSWORD
# + SUPABASE_ANON_KEY_LEGACY_JWT). Replaces the previous static RAG_SMOKE_TOKEN
# secret which expired after 1 hour and silently blocked all subsequent deploys.
# 2026-07-31: retargeted from the zk-org/zk fixture (kasten 227e0fb2 + canonical
# zettel were deleted by QA cleanup + 30-day canonical shred → FK 23503 → 500).
# New target: Naruto's curated "Economics & Markets" kasten, big-mac-data zettel.
RAG_SMOKE_KASTEN_ID="${RAG_SMOKE_KASTEN_ID:-087184be-3a87-4eb0-9b74-8313077b85ea}"
RAG_SMOKE_QUERY="Which GitHub repository contains the data and code for The Economist's Big Mac index, and in what language is the data generator written?"
# v2 citations carry canonical_chunk_id UUIDs in node_id (brittle across
# re-chunking), so the gate asserts on the stable citation TITLE instead.
RAG_SMOKE_EXPECT_TITLE="${RAG_SMOKE_EXPECT_TITLE:-TheEconomist/big-mac-data}"


# 2026-06-17: fail-CLOSED by default (was warn-and-skip, which caused a 38-day
# silent outage — see docs/claude_audits/rag_smoke_gate_disabled_2026-06-17.md).
# Set RAG_SMOKE_REQUIRED=0 only for an emergency credless manual deploy.
SMOKE_REQUIRED="${RAG_SMOKE_REQUIRED:-1}"

if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_ANON_KEY_LEGACY_JWT:-}" || -z "${NARUTO_SMOKE_PASSWORD:-}" ]]; then
    if [[ "$SMOKE_REQUIRED" == "1" ]]; then
        log "[rag-smoke] FATAL: smoke creds not all set in a CI deploy -- ABORTING (set NARUTO_SMOKE_PASSWORD / SUPABASE_ANON_KEY_LEGACY_JWT / SUPABASE_URL as GH secrets)."
        restore_previous_color
        exit 91
    fi
    log "[rag-smoke] WARN: smoke creds not all set -- skipping (manual deploy, degraded confidence)"
else
    log "[rag-smoke] minting fresh Naruto JWT via Supabase password grant..."
    AUTH_TMP=$(mktemp)
    AUTH_HTTP=$(curl -sS --max-time 15 -o "$AUTH_TMP" -w "%{http_code}" -X POST "${SUPABASE_URL}/auth/v1/token?grant_type=password" \
        -H "apikey: ${SUPABASE_ANON_KEY_LEGACY_JWT}" \
        -H "Content-Type: application/json" \
        -d "$(printf '{"email":"naruto@zettelkasten.local","password":%s}' "$(printf '%s' "$NARUTO_SMOKE_PASSWORD" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")" \
        2>/dev/null || echo "000")
    AUTH_RESP=$(cat "$AUTH_TMP"); rm -f "$AUTH_TMP"
    SMOKE_TOKEN=$(echo "$AUTH_RESP" | python3 -c "import json,sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get('access_token') or '')
except Exception:
    print('')" 2>/dev/null)
    if [[ -z "$SMOKE_TOKEN" ]]; then
        # 2026-06-17: surface the auth HTTP status + GoTrue error_code (never the
        # token/password) — the old path discarded it, making the 38-day outage
        # undiagnosable from deploy logs. error_code/msg carry no secret.
        AUTH_REASON=$(echo "$AUTH_RESP" | python3 -c "import json,sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get('error_code') or d.get('error') or d.get('msg') or d.get('error_description') or 'unknown')
except Exception:
    print('unparseable')" 2>/dev/null)
        log "[rag-smoke] JWT mint failed: HTTP=${AUTH_HTTP} reason=${AUTH_REASON}"
        if [[ "$SMOKE_REQUIRED" == "1" ]]; then
            log "[rag-smoke] FATAL: smoke creds present but mint REJECTED -- ABORTING DEPLOY (no traffic flip)."
            log "[rag-smoke] Likely: NARUTO_SMOKE_PASSWORD stale vs Supabase, anon key revoked, or naruto account drift."
            restore_previous_color
            exit 91
        fi
        log "[rag-smoke] WARN: skipping smoke probe (manual deploy, degraded confidence)"
    else
        log "[rag-smoke] JWT minted (len ${#SMOKE_TOKEN}); pre-warming and probing..."
        SMOKE_BODY=$(printf '{"sandbox_id":"%s","content":%s,"quality":"fast","stream":false,"scope_filter":{}}' \
            "$RAG_SMOKE_KASTEN_ID" "$(printf '%s' "$RAG_SMOKE_QUERY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")

        # iter-03 §B (2026-04-29): pre-warm hot paths before the smoke probe.
        # First call after gunicorn fork can have cold Supabase RPC pools, cold
        # pgvector index pages, and cold Gemini key-pool selectors. Without
        # warming, retrieval can return 0 candidates → empty citations → smoke
        # mis-classifies a healthy worker as broken. Best-effort, non-fatal.
        #
        # 2026-08-01: fire it repeatedly, not once. GUNICORN_WORKERS=2 and
        # gunicorn round-robins accept across workers, so a single request warms
        # exactly ONE worker and the smoke probe may then land on the cold one.
        # (Separately: /api/health/warm only warms the stage-2 ONNX session — it
        # does NOT touch embeddings, the Supabase pool, PostgREST, or the Gemini
        # key pool, despite what the comment above implies. Widening it is
        # tracked as item 2.5 in docs/claude_audits/hardening_plan_2026-08-01.md.)
        for _warm in 1 2 3 4 5 6; do
            curl -fsS --max-time 30 "http://127.0.0.1:${IDLE_PORT}/api/health/warm" >/dev/null 2>&1 || true
        done
        unset _warm

        # iter-03 §B (2026-04-29): retry the smoke probe up to 3 times with
        # 15s backoff. Cold-start retrieval and intra-request memory ceiling
        # (503 backpressure) can both transiently fail the first probe.
        # Three windows of 240s upper-bound = up to 12 min of grace, but
        # typical cold-start is recovered by attempt 2 in ~30s.
        SMOKE_PRIMARY=""
        SMOKE_HTTP=""
        SMOKE_RESPONSE=""
        for smoke_attempt in 1 2 3; do
            SMOKE_TMP=$(mktemp)
            SMOKE_HTTP=$(curl -sS --max-time 240 -o "$SMOKE_TMP" -w "%{http_code}" \
                -H "Authorization: Bearer $SMOKE_TOKEN" -H "Content-Type: application/json" \
                -d "$SMOKE_BODY" "http://127.0.0.1:${IDLE_PORT}/api/rag/adhoc" 2>/dev/null || echo "000")
            SMOKE_RESPONSE=$(cat "$SMOKE_TMP")
            rm -f "$SMOKE_TMP"
            SMOKE_PRIMARY=$(echo "$SMOKE_RESPONSE" | python3 -c "import json,sys
try:
    d = json.loads(sys.stdin.read())
    if 'turn' not in d:
        # 503 backpressure body has 'error', not 'turn'.
        print('NO_TURN:'+str(d.get('error','unknown')))
    else:
        cits = d.get('turn',{}).get('citations',[])
        # v2 node_id is a chunk UUID; TITLE is the stable assert key.
        print(cits[0].get('title') if cits else 'NO_CITATIONS')
except Exception as e:
    print('PARSE_FAIL:'+str(e))" 2>/dev/null || echo "PARSE_FAIL")
            log "[rag-smoke] attempt ${smoke_attempt}/3 ${IDLE} HTTP=${SMOKE_HTTP} primary_title=${SMOKE_PRIMARY} (expect ${RAG_SMOKE_EXPECT_TITLE})"
            if [[ "$SMOKE_HTTP" == "200" && "$SMOKE_PRIMARY" == "$RAG_SMOKE_EXPECT_TITLE" ]]; then
                log "[rag-smoke] ${IDLE} smoke probe OK on attempt ${smoke_attempt}"
                break
            fi
            if (( smoke_attempt < 3 )); then
                log "[rag-smoke] cold-start or backpressure -- waiting 15s before retry..."
                sleep 15
            fi
        done

        if [[ "$SMOKE_HTTP" != "200" || "$SMOKE_PRIMARY" != "$RAG_SMOKE_EXPECT_TITLE" ]]; then
            log "[rag-smoke] FATAL: smoke probe failed after 3 attempts. Final HTTP=${SMOKE_HTTP} primary_title=${SMOKE_PRIMARY}"
            log "[rag-smoke] response body (first 600 chars):"
            log "$(printf '%s' "$SMOKE_RESPONSE" | head -c 600)"

            # 2026-08-01 diagnostic triage. The 04:08Z failure returned
            # HTTP 200 with ZERO citations and could not be root-caused,
            # because the container was removed before its logs were read.
            # These two fields discriminate the leading hypotheses directly
            # from the response we already have in hand:
            #   critic_notes non-null  -> the answer critic FAILED (it catches
            #       every exception and returns "unsupported", which becomes
            #       unsupported_no_retry and makes _SUPPRESS_CITATIONS_ON_REFUSAL
            #       strip the citations). Retrieval was fine; a transient Gemini
            #       error on the last of ~6 generative calls stripped the evidence.
            #   critic_notes null + 0 citations -> genuine retrieval failure
            #       (scope resolved empty, embedding failed, RPC error).
            SMOKE_DIAG=$(printf '%s' "$SMOKE_RESPONSE" | python3 -c "
import json,sys
try:
    t = (json.loads(sys.stdin.read()) or {}).get('turn') or {}
    print('critic_verdict=%r critic_notes=%r citations=%d answer_chars=%d' % (
        t.get('critic_verdict'), (t.get('critic_notes') or '')[:200],
        len(t.get('citations') or []), len(t.get('content') or '')))
except Exception as e:
    print('diag_parse_failed: %s' % e)
" 2>/dev/null || echo "diag unavailable")
            log "[rag-smoke] diag: ${SMOKE_DIAG}"
            log "[rag-smoke] -> critic_notes set = critic outage stripped citations (retrieval likely OK)"
            log "[rag-smoke] -> critic_notes empty + 0 citations = genuine retrieval failure"
            log "[rag-smoke] Possible causes: smoke fixture deleted from DB (check rag.kastens); critic/Gemini transient failure; worker OOM-killed mid-pipeline; persistent backpressure (503); corpus drift."
            log "[rag-smoke] Container logs are captured below before teardown."
            restore_previous_color "rag-smoke"
            exit 89
        fi
    fi
    unset SMOKE_TOKEN AUTH_RESP
fi

# Pre-warm the new color so the first user request after cutover doesn't pay
# the BGE int8 ONNX cold-start tax (~1-3s on a 1 vCPU droplet). Best-effort:
# the loop tolerates the endpoint being briefly unavailable while gunicorn
# workers come up after --preload.
log "Pre-warming $IDLE on port $IDLE_PORT..."
PREWARM_OK=0
for i in {1..30}; do
    if curl -fsS "http://127.0.0.1:${IDLE_PORT}/api/health/warm" > /dev/null 2>&1; then
        log "Pre-warm complete after ${i}s"
        PREWARM_OK=1
        break
    fi
    sleep 1
done
if [[ "$PREWARM_OK" -ne 1 ]]; then
    log "WARN: pre-warm did not respond within 30s -- proceeding with cutover"
fi

# Multi-route SSR-HTML warm-up. The /api/health/warm probe above warms backend
# hot paths (Supabase pool, Gemini keys, pgvector) but does NOT exercise the
# FastAPI _render_with_shell SSR path that re-reads header.html + footer.html
# on every request. Stress audit 2026-05-24 showed first-hit on each user-
# facing shell route eats 400-500 ms of file-read + Jinja + brotli on a cold
# worker. Hit each route 6x on a forced-fresh TCP socket so the kernel
# round-robins between the 2 gunicorn workers (~98% binomial coverage
# = 1 - 2 * (1/2)^6). Best-effort; logged but never aborts the deploy
# (Caddy reload + caddy-smoke probe below are the actual gates).
log "Warming SSR HTML routes on $IDLE port $IDLE_PORT..."
SSR_ROUTES=(/ /home /home/zettels /home/kastens /home/nexus /home/rag /profile /knowledge-graph /about /pricing)
SSR_HITS=6
SSR_OK=0
SSR_TOTAL=0
for route in "${SSR_ROUTES[@]}"; do
    for i in $(seq 1 $SSR_HITS); do
        SSR_TOTAL=$((SSR_TOTAL + 1))
        code=$(curl -sS -o /dev/null --max-time 8 \
            --http1.1 -H "Connection: close" \
            -H "Host: zettelkasten.in" \
            -H "X-Zk-Warmup: 1" \
            -w "%{http_code}" \
            "http://127.0.0.1:${IDLE_PORT}${route}" 2>/dev/null || echo "000")
        if [[ "$code" == "200" || "$code" == "302" ]]; then
            SSR_OK=$((SSR_OK + 1))
        fi
    done
done
log "SSR warm-up: ${SSR_OK}/${SSR_TOTAL} requests returned 200/302 (best-effort)"

log "Flipping Caddy upstream to $IDLE..."
# IMPORTANT: must write in-place (truncate + rewrite) rather than via
# `mv TMP SNIPPET`. Docker bind mounts of a single file track the inode
# at mount time; atomic-replace via `mv` creates a new inode, leaving the
# container stuck viewing the pre-deploy snippet. Rewriting keeps inode.
cat > "$SNIPPET" <<EOF
# Updated by deploy.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ) — SHA=$SHA
#
# iter-03: explicit transport timeouts so Strong-mode / multi-hop synthesis
# (Gemini Pro answers can take 60-120s) doesn't trip the upstream deadline.
# Must be >= GUNICORN_TIMEOUT (180s) for sane semantics.
#
# iter-04: bound upstream concurrency at the proxy layer with
# max_conns_per_host 20 (= 2 workers x (2 sem + 8 queue)). Pair with
# gunicorn --backlog 64 in run.py:46 to make the OS accept-queue overflow
# fail fast rather than queueing into a 240s death-trail. Convert
# upstream 502 / 504 to 503 with a Retry-After:10 header so the burst
# client sees structured backpressure (the eval expects >=1 503; pre-iter-04
# all 12 saw raw 502 because the app-layer 503 path was unreachable).
reverse_proxy zettelkasten-${IDLE}:10000 {
    transport http {
        dial_timeout 5s
        read_timeout 300s
        write_timeout 300s
        response_header_timeout 300s
        max_conns_per_host 20
    }
    flush_interval -1
    lb_try_duration 0s
    @upstream_down status 502 504
    handle_response @upstream_down {
        header Retry-After 10
        respond "queue_full" 503
    }
}
EOF
chown deploy:deploy "$SNIPPET"
chmod 644 "$SNIPPET"

log "Reloading Caddy..."
"$ROOT/deploy/reload_caddy.sh"

# iter-03 §B (2026-04-29): public-facing smoke gate. Catches the failure
# mode where Caddy reload silently no-ops (autosave.json keeps the prior
# upstream color, every public request returns 502 even though the
# 127.0.0.1:10000 upstream probe was happy). We hit the apex hostname so
# the request actually traverses Caddy's reverse_proxy with the new config.
# Two attempts, 5s apart, to absorb cert/HSTS warm-up after a restart.
PUBLIC_SMOKE_OK=0
for attempt in 1 2; do
    PUBLIC_HTTP="$(curl -sS -o /dev/null -w '%{http_code}' \
        --max-time 10 \
        --resolve "zettelkasten.in:443:127.0.0.1" \
        https://zettelkasten.in/api/health || echo "000")"
    if [[ "$PUBLIC_HTTP" == "200" ]]; then
        PUBLIC_SMOKE_OK=1
        break
    fi
    log "[caddy-smoke] attempt ${attempt}/2 returned HTTP=${PUBLIC_HTTP}; sleeping 5s..."
    sleep 5
done
if (( PUBLIC_SMOKE_OK == 0 )); then
    log "[caddy-smoke] FATAL: public probe via Caddy did not return 200 after flip."
    log "[caddy-smoke] Likely causes: caddy reload no-op (check autosave.json upstream), TLS cert issue, dns drift, container stopped."
    # 2026-08-01: deliberately does NOT call restore_previous_color, unlike the
    # gates above. By this point ${IDLE} has passed health, cgroup, stage2 and
    # the RAG smoke, and Caddy has already been flipped to it — so the backend
    # is good and the fault is in Caddy itself. reload_caddy.sh has already
    # tried a graceful reload AND a full restart. Tearing down a healthy
    # container to boot the old one would remove the only working backend and
    # make recovery harder, not easier.
    log "[caddy-smoke] ${IDLE} is healthy; fault is Caddy-side. Recover with:"
    log "[caddy-smoke]   gh workflow run ops-recover-serve.yml"
    exit 90
fi
log "[caddy-smoke] public probe via Caddy OK (HTTP 200)"
maint_window close

ACTIVE_CONTAINER_NAME="zettelkasten-${ACTIVE}"
ACTIVE_CONTAINER_ID="$(docker inspect --format '{{.Id}}' "$ACTIVE_CONTAINER_NAME" 2>/dev/null || true)"

echo "$IDLE" > "$ACTIVE_FILE"

# 2026-08-01: record the SHA that just passed every gate, so rollback.sh can
# restore THIS image rather than resolving ${IMAGE_TAG:-latest}. CI pushes both
# :<sha> and :latest on every build, and deploy.sh `docker rm`s the previous
# container before the flip — so a rollback could not no-op, it had to create a
# fresh container, pulling :latest = the NEW, suspect image. The operator would
# see "ROLLBACK COMPLETE" while running exactly the build they meant to escape.
# Written only on the success path, after caddy-smoke, so it always names a
# genuinely-good build.
echo "$SHA" > "$ROOT/LAST_GOOD_SHA"
chown deploy:deploy "$ROOT/LAST_GOOD_SHA" 2>/dev/null || true
log "[last-good] recorded $SHA for rollback"

log "Running metadata backfill against $IDLE (idempotent, non-fatal)..."
# T13: enrich pre-existing chunks that lack metadata_enriched_at. The
# script's IS NULL filter makes repeated runs no-ops. Failure here MUST
# NOT block the deploy — backfill is enrichment, not correctness-critical.
# Run in background so it doesn't extend deploy wall-time; logs go to deploy.log.
BACKFILL_SCRIPT="ops/scripts/backfill_metadata.py"
if docker exec "zettelkasten-${IDLE}" test -f "$BACKFILL_SCRIPT" 2>/dev/null; then
    nohup bash -c "docker exec zettelkasten-${IDLE} python $BACKFILL_SCRIPT --batch-size 200 >> '$LOG' 2>&1 || echo '[backfill] WARN: metadata backfill exited non-zero (deploy unaffected)' >> '$LOG'" >/dev/null 2>&1 &
    log "Metadata backfill dispatched (pid=$!) — see $LOG for progress."
else
    log "WARN: $BACKFILL_SCRIPT not found in $IDLE container — skipping backfill."
fi

# iter-03 sequential blue/green: ACTIVE was stopped pre-flight (line ~167)
# to free RAM for IDLE on this 2 GB droplet. There's no live container to
# drain - skip the background retire step. Kept the variable name above for
# audit-log compatibility.
log "[seq-deploy] ACTIVE color ${ACTIVE} already stopped pre-flight; no retire needed."

log "DEPLOY SUCCEEDED. New active color: $IDLE, image: $IMAGE"
