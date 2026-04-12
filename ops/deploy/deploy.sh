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
#   - Drains and stops the previously-active color
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

log "Starting $IDLE container with new image..."
IMAGE_TAG="$SHA" docker compose \
    -f "$ROOT/compose/docker-compose.${IDLE}.yml" \
    up -d --no-deps

log "Waiting for $IDLE healthcheck on port $IDLE_PORT..."
"$ROOT/deploy/healthcheck.sh" "$IDLE_PORT"

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

echo "$IDLE" > "$ACTIVE_FILE"

log "Draining $ACTIVE for 20 seconds..."
sleep 20

log "Stopping $ACTIVE container..."
docker compose \
    -f "$ROOT/compose/docker-compose.${ACTIVE}.yml" \
    down --timeout 20 || log "Warning: failed to stop $ACTIVE cleanly"

log "DEPLOY SUCCEEDED. New active color: $IDLE, image: $IMAGE"
