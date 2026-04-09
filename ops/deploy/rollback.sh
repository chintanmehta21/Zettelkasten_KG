#!/usr/bin/env bash
# ops/deploy/rollback.sh
#
# Roll back to the last known good color.
# Reads /opt/zettelkasten/ACTIVE_COLOR as the canonical source of truth.

set -euo pipefail

ROOT=/opt/zettelkasten
ACTIVE_FILE="$ROOT/ACTIVE_COLOR"
SNIPPET="$ROOT/caddy/upstream.snippet"
LOG="$ROOT/logs/deploy.log"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [ROLLBACK] $*" | tee -a "$LOG"
}

ACTIVE=$(cat "$ACTIVE_FILE")
if [[ "$ACTIVE" == "blue" ]]; then
    OTHER="green"
    ACTIVE_PORT=10000
else
    OTHER="blue"
    ACTIVE_PORT=10001
fi

log "Restoring known-good color: $ACTIVE"

log "Ensuring $ACTIVE is running..."
docker compose \
    -f "$ROOT/compose/docker-compose.${ACTIVE}.yml" \
    up -d --no-deps || true

"$ROOT/deploy/healthcheck.sh" "$ACTIVE_PORT" || {
    log "FATAL: $ACTIVE is not healthy on rollback. Manual intervention required."
    exit 1
}

log "Rewriting upstream snippet -> $ACTIVE..."
TMP=$(mktemp)
cat > "$TMP" <<EOF
# Updated by rollback.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ)
reverse_proxy zettelkasten-${ACTIVE}:10000
EOF
mv "$TMP" "$SNIPPET"

log "Reloading Caddy..."
docker exec caddy caddy reload --config /etc/caddy/Caddyfile || {
    log "WARNING: Caddy reload failed. Run: docker exec caddy caddy reload --config /etc/caddy/Caddyfile"
}

if docker ps --format '{{.Names}}' | grep -q "^zettelkasten-${OTHER}\$"; then
    log "Tearing down failed $OTHER container..."
    docker compose \
        -f "$ROOT/compose/docker-compose.${OTHER}.yml" \
        down --timeout 20 || true
fi

log "ROLLBACK COMPLETE. Active color: $ACTIVE"
