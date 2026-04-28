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
# of the .env (TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, SUPABASE_*, etc.) stays
# scoped to the docker --env-file path and never leaks into deploy.sh's
# shell. Missing values fall through to the existing ${VAR:-default} guards
# below — manual operator deploys from a droplet shell still work.
ENV_FILE="${ENV_FILE:-/opt/zettelkasten/compose/.env}"
if [[ -r "$ENV_FILE" ]]; then
    while IFS='=' read -r _key _val; do
        case "$_key" in
            DEPLOY_GIT_SHA|DEPLOY_ID|DEPLOY_ACTOR)
                export "$_key=$_val"
                ;;
        esac
    done < <(grep -E '^DEPLOY_(GIT_SHA|ID|ACTOR)=' "$ENV_FILE" || true)
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

ACTIVE=$(cat "$ACTIVE_FILE")
if [[ "$ACTIVE" == "blue" ]]; then
    IDLE="green"
    IDLE_PORT=10001
else
    IDLE="blue"
    IDLE_PORT=10000
fi

log "Starting deploy: SHA=$SHA, ACTIVE=$ACTIVE, IDLE=$IDLE"

log "Pulling $IMAGE..."
IMAGE_TAG="$SHA" docker compose \
    -f "$ROOT/compose/docker-compose.${IDLE}.yml" \
    pull

# ── D-1 (KAS-11): apply pending Supabase migrations BEFORE traffic flips. ──
# Runs the new image as a short-lived helper container so the migration set
# matches the code about to be deployed. Failure is FATAL — we abort before
# touching the IDLE container so prod stays on the previous (working) color.

# iter-03 §1C.1 preflight: confirm SUPABASE_DB_URL is in the env-file before
# we even spin the migration container. Without it apply_migrations exits
# with rc=2 (config error) — surface that as a clear deploy abort.
if ! grep -q '^SUPABASE_DB_URL=' /opt/zettelkasten/compose/.env; then
    log "[deploy] FATAL: SUPABASE_DB_URL missing from /opt/zettelkasten/compose/.env"
    exit 2
fi

log "[migration] Applying pending Supabase migrations against prod..."
set +e
# iter-03 §1C.4: pass deploy provenance so apply_migrations can stamp each
# audit row with git SHA / deploy id / actor. Defaults guarantee non-null
# values even when this script is run outside CI (manual operator deploy).
# iter-03 §1C.5: mount a host dir so the bootstrapped/verified manifest
# survives the container exit. Operator commits this back to Git after the
# first deploy, after which the in-image copy at /app/supabase/.../
# expected_schema.json is the canonical source.
MANIFEST_HOST_DIR="$ROOT/data/schema"
mkdir -p "$MANIFEST_HOST_DIR"
chown -R deploy:deploy "$MANIFEST_HOST_DIR" 2>/dev/null || true

docker run --rm --network host \
    --env-file /opt/zettelkasten/compose/.env \
    -v "$MANIFEST_HOST_DIR":/manifest-out \
    -e DEPLOY_GIT_SHA="${DEPLOY_GIT_SHA:-$SHA}" \
    -e DEPLOY_ID="${DEPLOY_ID:-manual-$(date -u +%Y%m%dT%H%M%SZ)}" \
    -e DEPLOY_ACTOR="${DEPLOY_ACTOR:-$(whoami)}" \
    -e MIGRATION_MANIFEST_REQUIRED="${MIGRATION_MANIFEST_REQUIRED:-1}" \
    -e MIGRATION_MANIFEST_AUTOBOOTSTRAP="${MIGRATION_MANIFEST_AUTOBOOTSTRAP:-1}" \
    "$IMAGE" \
    python ops/scripts/apply_migrations.py \
        --manifest-path /manifest-out/expected_schema.json \
        2>&1 | tee -a "$LOG"
MIG_RC=${PIPESTATUS[0]}
set -e
if [ "$MIG_RC" -ne 0 ]; then
    log "[migration] FAILED rc=$MIG_RC — ABORTING DEPLOY (no traffic flip, IDLE container not started)"
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

log "Starting $IDLE container with new image..."
IMAGE_TAG="$SHA" docker compose \
    -f "$ROOT/compose/docker-compose.${IDLE}.yml" \
    up -d --no-deps

log "Waiting for $IDLE healthcheck on port $IDLE_PORT..."
"$ROOT/deploy/healthcheck.sh" "$IDLE_PORT"

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

log "Flipping Caddy upstream to $IDLE..."
# IMPORTANT: must write in-place (truncate + rewrite) rather than via
# `mv TMP SNIPPET`. Docker bind mounts of a single file track the inode
# at mount time; atomic-replace via `mv` creates a new inode, leaving the
# container stuck viewing the pre-deploy snippet. Rewriting keeps inode.
cat > "$SNIPPET" <<EOF
# Updated by deploy.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ) — SHA=$SHA
reverse_proxy zettelkasten-${IDLE}:10000
EOF
chown deploy:deploy "$SNIPPET"
chmod 644 "$SNIPPET"

log "Reloading Caddy..."
"$ROOT/deploy/reload_caddy.sh"

ACTIVE_CONTAINER_NAME="zettelkasten-${ACTIVE}"
ACTIVE_CONTAINER_ID="$(docker inspect --format '{{.Id}}' "$ACTIVE_CONTAINER_NAME" 2>/dev/null || true)"

echo "$IDLE" > "$ACTIVE_FILE"

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

log "Handing off $ACTIVE retirement to background drain (${DRAIN_SECONDS}s)..."
nohup "$ROOT/deploy/retire_color.sh" "$ACTIVE" "$DRAIN_SECONDS" "$ACTIVE_CONTAINER_ID" >/dev/null 2>&1 &
RETIRE_PID=$!

log "DEPLOY SUCCEEDED. New active color: $IDLE, image: $IMAGE, retire_pid=$RETIRE_PID"
