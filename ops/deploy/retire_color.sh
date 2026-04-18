#!/usr/bin/env bash
# ops/deploy/retire_color.sh <color> [drain_seconds] [expected_container_id]
#
# Detaches old-color retirement from the SSH session after cutover.
# Keeps the full drain window, then stops the previous color and prunes
# stale Docker artifacts in the background.

set -euo pipefail

COLOR="${1:-}"
DRAIN_SECONDS="${2:-20}"
EXPECTED_CONTAINER_ID="${3:-}"

if [[ "$COLOR" != "blue" && "$COLOR" != "green" ]]; then
    echo "usage: $0 <blue|green> [drain_seconds]" >&2
    exit 2
fi

ROOT=/opt/zettelkasten
LOG="$ROOT/logs/deploy.log"
COMPOSE_FILE="$ROOT/compose/docker-compose.${COLOR}.yml"
CONTAINER_NAME="zettelkasten-${COLOR}"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [retire] $*" >> "$LOG"
}

log "Draining $COLOR for ${DRAIN_SECONDS} seconds before shutdown..."
sleep "$DRAIN_SECONDS"

CURRENT_CONTAINER_ID="$(docker inspect --format '{{.Id}}' "$CONTAINER_NAME" 2>/dev/null || true)"
if [[ -z "$CURRENT_CONTAINER_ID" ]]; then
    log "$CONTAINER_NAME is already gone; nothing to retire."
    exit 0
fi

if [[ -n "$EXPECTED_CONTAINER_ID" && "$CURRENT_CONTAINER_ID" != "$EXPECTED_CONTAINER_ID" ]]; then
    log "$CONTAINER_NAME was recycled by a newer deploy; skipping background retire."
    exit 0
fi

log "Stopping $COLOR container..."
docker compose \
    -f "$COMPOSE_FILE" \
    down --timeout 20 || log "Warning: failed to stop $COLOR cleanly"

log "[cleanup] Pruning unused Docker resources..."
docker system prune -af --filter "until=72h" >/dev/null 2>&1 || true
docker image prune -af >/dev/null 2>&1 || true

log "[cleanup] Disk usage after prune:"
docker system df >> "$LOG" 2>&1 || true
