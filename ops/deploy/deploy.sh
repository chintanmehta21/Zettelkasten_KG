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
#   - Reloads Caddy gracefully, with restart fallback if docker exec flakes
#   - Drains and stops the previously-active color
#   - Updates /opt/zettelkasten/ACTIVE_COLOR
#
# On failure: performs an in-script rollback and exits non-zero.

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

healthcheck_port() {
    local port="$1"
    local attempts=30

    for attempt in $(seq 1 "$attempts"); do
        if curl --silent --fail --max-time 2 "http://127.0.0.1:${port}/api/health" >/dev/null; then
            log "[healthcheck] Port ${port} healthy after ${attempt} attempt(s)"
            return 0
        fi
        sleep 1
    done

    log "[healthcheck] Port ${port} did NOT become healthy after ${attempts} attempts"
    return 1
}

wait_for_caddy() {
    local attempts="${1:-20}"
    local delay="${2:-2}"
    local status=""

    for _ in $(seq 1 "$attempts"); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' caddy 2>/dev/null || true)"
        if [[ "$status" == "healthy" || "$status" == "running" ]]; then
            return 0
        fi
        sleep "$delay"
    done

    log "Caddy did not become ready (last status: ${status:-missing})"
    return 1
}

reload_caddy() {
    local prefix="${1:-}"
    local attempts=5
    local delay=2

    for attempt in $(seq 1 "$attempts"); do
        if docker exec caddy caddy reload --config /etc/caddy/Caddyfile; then
            return 0
        fi
        log "${prefix}Caddy reload attempt ${attempt}/${attempts} failed; retrying..."
        sleep "$delay"
    done

    log "${prefix}Falling back to docker restart caddy..."
    docker restart caddy >/dev/null
    wait_for_caddy
}

rollback_deploy() {
    log "[ROLLBACK] Restoring known-good color: $ACTIVE"

    log "[ROLLBACK] Ensuring $ACTIVE is running..."
    docker compose \
        -f "$ROOT/compose/docker-compose.${ACTIVE}.yml" \
        up -d --no-deps || true

    if ! healthcheck_port "$ACTIVE_PORT"; then
        log "[ROLLBACK] FATAL: $ACTIVE is not healthy on rollback. Manual intervention required."
        return 1
    fi

    log "[ROLLBACK] Rewriting upstream snippet -> $ACTIVE..."
    cat > "$SNIPPET" <<EOF
# Updated by deploy.sh rollback at $(date -u +%Y-%m-%dT%H:%M:%SZ)
reverse_proxy zettelkasten-${ACTIVE}:10000
EOF
    chown deploy:deploy "$SNIPPET"
    chmod 644 "$SNIPPET"

    log "[ROLLBACK] Reloading Caddy..."
    if ! reload_caddy "[ROLLBACK] "; then
        log "[ROLLBACK] WARNING: Caddy reload failed even after restart fallback."
    fi

    if docker ps --format '{{.Names}}' | grep -q "^zettelkasten-${IDLE}$"; then
        log "[ROLLBACK] Tearing down failed $IDLE container..."
        docker compose \
            -f "$ROOT/compose/docker-compose.${IDLE}.yml" \
            down --timeout 20 || true
    fi

    echo "$ACTIVE" > "$ACTIVE_FILE"
    log "[ROLLBACK] ROLLBACK COMPLETE. Active color: $ACTIVE"
}

on_error() {
    log "DEPLOY FAILED at line $LINENO. Invoking rollback..."
    rollback_deploy || true
    exit 1
}
trap on_error ERR

ACTIVE=$(cat "$ACTIVE_FILE")
if [[ "$ACTIVE" == "blue" ]]; then
    IDLE="green"
    ACTIVE_PORT=10000
    IDLE_PORT=10001
else
    IDLE="blue"
    ACTIVE_PORT=10001
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
healthcheck_port "$IDLE_PORT"

log "Running reranker preflight inside $IDLE stack..."
IMAGE_TAG="$SHA" docker compose \
    -f "$ROOT/compose/docker-compose.${IDLE}.yml" \
    exec -T reranker wget -qO- http://localhost:8080/health >/dev/null

log "Flipping Caddy upstream to $IDLE..."
# IMPORTANT: must write in-place (truncate + rewrite) rather than via
# `mv TMP SNIPPET`. Docker bind mounts of a single file track the inode
# at mount time; atomic-replace via `mv` creates a new inode, leaving the
# container stuck viewing the pre-deploy snippet. Rewriting keeps inode.
cat > "$SNIPPET" <<EOF
# Updated by deploy.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ) - SHA=$SHA
reverse_proxy zettelkasten-${IDLE}:10000
EOF
chown deploy:deploy "$SNIPPET"
chmod 644 "$SNIPPET"

log "Reloading Caddy..."
reload_caddy

echo "$IDLE" > "$ACTIVE_FILE"

log "Draining $ACTIVE for 20 seconds..."
sleep 20

log "Stopping $ACTIVE container..."
docker compose \
    -f "$ROOT/compose/docker-compose.${ACTIVE}.yml" \
    down --timeout 20 || log "Warning: failed to stop $ACTIVE cleanly"

log "DEPLOY SUCCEEDED. New active color: $IDLE, image: $IMAGE"
