#!/usr/bin/env bash
# ops/deploy/healthcheck.sh
#
# Polls http://127.0.0.1:<port>/api/health and exits 0 once it returns 200.
# Exits 1 after 30 attempts (~30s total).
#
# Usage: healthcheck.sh <port>

set -euo pipefail

PORT="${1:-}"
if [[ -z "$PORT" ]]; then
    echo "usage: $0 <port>" >&2
    exit 2
fi

MAX_ATTEMPTS=30
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    if curl --silent --fail --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
        echo "[healthcheck] Port ${PORT} healthy after ${attempt} attempt(s)"
        exit 0
    fi
    sleep 1
done

echo "[healthcheck] Port ${PORT} did NOT become healthy after ${MAX_ATTEMPTS} attempts" >&2
exit 1
