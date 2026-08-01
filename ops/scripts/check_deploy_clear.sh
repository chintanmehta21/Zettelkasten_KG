#!/usr/bin/env bash
# ops/scripts/check_deploy_clear.sh
#
# Exit 0 only when it is SAFE to push to master.
#
# Why this exists: deploy-droplet.yml declares
#   concurrency: {group: deploy-prod, cancel-in-progress: true}
# so a push while a deploy is mid-cutover cancels it INSTANTLY. deploy.sh has
# already stopped and `docker rm`'d the serving container by then, and an
# external SIGHUP bypasses every in-script gate — including
# restore_previous_color. The EXIT trap also clears the maintenance flag, so
# users get raw 502s instead of the graceful 503. That produced a real outage
# on 2026-08-01.
#
# It also exists because the obvious one-liner is a trap. This:
#
#   gh run list ... --jq '.[] | select(.status!="completed") | "IN FLIGHT"'; echo "(safe)"
#
# prints "IN FLIGHT" AND THEN "(safe)" unconditionally, and exits 0 either way.
# A guard whose failure looks like its success is worse than no guard — the
# same "cannot run != passed" defect this repo has been fixing all day.
#
# Usage:
#   ops/scripts/check_deploy_clear.sh && git push origin master

set -euo pipefail

REPO="${DEPLOY_REPO:-chintanmehta21/Zettelkasten_KG}"
WORKFLOW="${DEPLOY_WORKFLOW:-deploy-droplet.yml}"

state="$(gh run list --repo "$REPO" --workflow "$WORKFLOW" --limit 1 \
          --json status,databaseId,headSha \
          --jq '.[0] | "\(.status) \(.databaseId) \(.headSha[0:8])"' 2>/dev/null || true)"

if [ -z "$state" ]; then
    echo "WARN: could not read deploy status — refusing to certify the push as safe." >&2
    exit 2   # UNKNOWN, not OK (Nagios convention)
fi

status="${state%% *}"
rest="${state#* }"

case "$status" in
    completed)
        echo "safe: latest deploy is completed ($rest)"
        exit 0
        ;;
    *)
        echo "BLOCKED: a deploy is $status ($rest)." >&2
        echo "Pushing now would cancel it mid-cutover and can take the site down." >&2
        echo "Wait for it to finish, then re-run this check." >&2
        exit 1
        ;;
esac
