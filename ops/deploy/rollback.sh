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

log "Rewriting upstream snippet -> $ACTIVE (color swap only)..."
# 2026-08-01: this used to overwrite the snippet with a bare one-line
# reverse_proxy, silently discarding the iter-03/04 transport block
# (read_timeout 300s, max_conns_per_host 20, 502/504 -> 503 + Retry-After).
# Those are protected knobs (CLAUDE.md) and a rollback must never revert
# them. Swap only the color token, and write in place: a bind-mounted
# single file tracks its inode, so truncate+rewrite (not mv) is required
# for the caddy container to see the change.
if grep -q 'transport http' "$SNIPPET"; then
    SNIPPET_SWAPPED="$(sed -E "s/zettelkasten-(blue|green):10000/zettelkasten-${ACTIVE}:10000/g" "$SNIPPET")"
    printf '%s\n' "$SNIPPET_SWAPPED" > "$SNIPPET"
else
    # Degraded path: the block is already missing, so there is nothing to
    # preserve. Restore service, but say so loudly — the next deploy
    # rewrites the canonical snippet from deploy.sh's heredoc.
    log "WARNING: upstream.snippet has no transport block (protected timeouts absent)."
    log "WARNING: writing minimal snippet to restore service; redeploy to restore timeouts."
    cat > "$SNIPPET" <<EOF
# Updated by rollback.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ)
reverse_proxy zettelkasten-${ACTIVE}:10000
EOF
fi
chown deploy:deploy "$SNIPPET"
chmod 644 "$SNIPPET"

log "Reloading Caddy..."
LOG_PREFIX="[ROLLBACK] " "$ROOT/deploy/reload_caddy.sh" | tee -a "$LOG" || {
    log "WARNING: Caddy reload failed. Run: $ROOT/deploy/reload_caddy.sh"
}

# Clear the graceful-503 maintenance gate now that the known-good color is
# healthy and Caddy points at it — otherwise users keep seeing 503 over a
# healthy backend during the failed-color teardown below. deploy.sh's EXIT trap
# also clears it (idempotent); this just ends the window promptly on the
# rollback path. Graceful 503 is preserved through the (cold-boot) restore above.
rm -f "$ROOT/caddy/data/maintenance.flag" 2>/dev/null || true

if docker ps --format '{{.Names}}' | grep -q "^zettelkasten-${OTHER}\$"; then
    log "Tearing down failed $OTHER container..."
    docker compose \
        -f "$ROOT/compose/docker-compose.${OTHER}.yml" \
        down --timeout 20 || true
fi

log "ROLLBACK COMPLETE. Active color: $ACTIVE"
