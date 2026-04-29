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

verify_caddy_upstream_matches() {
    # Confirm the running Caddy config actually points at the expected color.
    # The autosave.json holds the live runtime config; if it diverges from
    # upstream.snippet, reload silently failed and traffic is going to a dead
    # upstream. Compare the upstream host token in both places.
    local expected actual
    expected="$(grep -oE 'zettelkasten-(blue|green):10000' \
        "$ROOT/caddy/upstream.snippet" | head -n1 || true)"
    actual="$(grep -oE 'zettelkasten-(blue|green):10000' \
        "$ROOT/caddy/config/caddy/autosave.json" 2>/dev/null | head -n1 || true)"
    if [[ -z "$expected" || -z "$actual" ]]; then
        return 1
    fi
    [[ "$expected" == "$actual" ]]
}

main() {
    # iter-03 §B (2026-04-29): the in-container `caddy reload` path appeared
    # to succeed (exit 0) but Caddy's running config did not actually re-bind
    # to the new upstream; autosave.json kept the prior color and every
    # public request returned 502 until an operator manually restarted the
    # container. The deploy smoke probe hits 127.0.0.1:10000 directly,
    # bypassing Caddy, so the broken reload never failed the deploy gate.
    # New behavior: try reload, then VERIFY the running config picked up
    # the new upstream. If it didn't, fall through to a full restart.
    if docker exec caddy caddy reload --config /etc/caddy/Caddyfile; then
        # Caddy writes autosave.json synchronously inside reload; a 1s grace
        # absorbs any filesystem flush lag.
        sleep 1
        if verify_caddy_upstream_matches; then
            log "${LOG_PREFIX:-}" "Caddy reloaded successfully via exec"
            return 0
        fi
        log "${LOG_PREFIX:-}" "Caddy reload returned 0 but running config still points to old upstream; will restart..."
    else
        log "${LOG_PREFIX:-}" "Caddy reload exec failed; will restart..."
    fi

    log "${LOG_PREFIX:-}" "Falling back to docker restart caddy..."
    docker restart caddy >/dev/null
    wait_for_caddy 40 2
    if ! verify_caddy_upstream_matches; then
        log "${LOG_PREFIX:-}" "FATAL: Caddy still does not point at expected upstream after restart."
        return 1
    fi
}

main "$@"
