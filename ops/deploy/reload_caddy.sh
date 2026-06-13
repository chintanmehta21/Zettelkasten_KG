#!/usr/bin/env bash
# ops/deploy/reload_caddy.sh
#
# Reload Caddy and confirm — END TO END — that it is actually serving through
# the (new) upstream.
#
# 2026-06 cutover root-cause: the previous version proved the flip by reading
# config/caddy/autosave.json (`verify_caddy_upstream_matches`) and, on a
# mismatch, restarted caddy and waited on the Docker *health status*
# (`wait_for_caddy`). Two problems made this fail on EVERY deploy:
#   (1) the first `caddy reload` per deploy returned 0 but autosave.json did not
#       reflect the new upstream within the 1s grace -> false "reload failed";
#   (2) the caddy Docker healthcheck (admin :2019) never reports "healthy", so
#       the restart wait ALWAYS timed out (~82s) -> deploy.sh ERR trap ->
#       rollback -> retry. Result: a 3-minute rollback saga on every deploy.
#
# New behavior: readiness is a real HTTPS request THROUGH Caddy on loopback
# returning 200 — no autosave.json guesswork, no dependence on the Docker
# health status. Robust whether the reload silently no-ops (e2e fails -> restart
# fixes it) or actually applied (e2e passes -> no restart needed).

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

# End-to-end readiness: hit the public hostname THROUGH Caddy on loopback.
# A 200 means Caddy is proxying to a live backend. After a flip the only live
# backend is the new color (deploy.sh stops the old color pre-flight), so a 200
# here proves the new upstream is in effect. /api/health bypasses the
# @maintenance matcher, so this is unaffected by the graceful-window flag.
caddy_serving() {
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
        --resolve "zettelkasten.in:443:127.0.0.1" \
        https://zettelkasten.in/api/health 2>/dev/null || echo 000)"
    [[ "$code" == "200" ]]
}

wait_serving() {
    local attempts="${1:-20}"
    local delay="${2:-2}"
    for _ in $(seq 1 "$attempts"); do
        if caddy_serving; then
            return 0
        fi
        sleep "$delay"
    done
    return 1
}

main() {
    # 1) Graceful reload, then confirm end-to-end. A reload that exits 0 but
    #    isn't visibly in effect within a few seconds is treated the same as a
    #    failed reload (escalate to restart) — no autosave.json inspection.
    if docker exec caddy caddy reload --config /etc/caddy/Caddyfile; then
        if wait_serving 6 1; then
            log "${LOG_PREFIX:-}" "Caddy reloaded; serving 200 via new upstream (e2e)"
            return 0
        fi
        log "${LOG_PREFIX:-}" "Caddy reload exited 0 but e2e probe not 200 within 6s; restarting caddy..."
    else
        log "${LOG_PREFIX:-}" "Caddy reload exec failed; restarting caddy..."
    fi

    # 2) Fallback: restart caddy (boots fresh from Caddyfile + current snippet),
    #    then confirm end-to-end. Readiness is the e2e probe, NOT the Docker
    #    health status — the admin :2019 healthcheck is unreliable and a
    #    health-based wait would time out even while caddy serves correctly.
    log "${LOG_PREFIX:-}" "Restarting caddy..."
    docker restart caddy >/dev/null
    if wait_serving 30 2; then
        log "${LOG_PREFIX:-}" "Caddy restarted; serving 200 via new upstream (e2e)"
        return 0
    fi

    log "${LOG_PREFIX:-}" "FATAL: Caddy not serving 200 via new upstream after reload + restart."
    return 1
}

main "$@"
