#!/usr/bin/env bash
# ops/deploy/reload_caddy.sh
#
# Reload Caddy with retries, falling back to a container restart if
# `docker exec` transiently fails on the droplet runtime.

set -euo pipefail

ROOT=/opt/zettelkasten

log() {
    local prefix="${1:-}"
    local message="${2:-}"
    if [[ -n "$prefix" ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ${prefix}${message}"
    else
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ${message}"
    fi
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

    log "${LOG_PREFIX:-}" "Caddy did not become ready (last status: ${status:-missing})"
    return 1
}

reload_with_exec() {
    local attempts="${1:-5}"
    local delay="${2:-2}"

    for attempt in $(seq 1 "$attempts"); do
        if docker exec caddy caddy reload --config /etc/caddy/Caddyfile; then
            return 0
        fi
        log "${LOG_PREFIX:-}" "Caddy reload attempt ${attempt}/${attempts} failed; retrying..."
        sleep "$delay"
    done

    return 1
}

main() {
    # Single-file Docker bind mounts track the inode at mount time.
    # deploy.sh rewrites upstream.snippet via `cat >`, which may create a
    # new inode despite the intent to truncate-and-rewrite.  When that
    # happens, the container still sees the OLD content, so `caddy reload`
    # (which re-reads the file from inside the container) loads stale
    # config.  A full container restart re-mounts the file and always
    # picks up the current host content.
    log "${LOG_PREFIX:-}" "Restarting caddy container (bind-mount refresh)..."
    docker restart caddy >/dev/null
    wait_for_caddy
}

main "$@"
