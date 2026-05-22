#!/usr/bin/env bash
set -euo pipefail

COLLECTION="${COLLECTION:-tests/postman/collections/zettelkasten-summarization.postman_collection.json}"
ENVIRONMENT="${ENVIRONMENT:-tests/postman/environments/zettelkasten.local.template.postman_environment.json}"
REPORT_DIR="${REPORT_DIR:-tests/postman/reports}"
FOLDER="${FOLDER:-}"

mkdir -p "$REPORT_DIR"
RAW_REPORT_DIR="${RUNNER_TEMP:-$REPORT_DIR}"
RAW_REPORT="$RAW_REPORT_DIR/newman-raw-${GITHUB_RUN_ID:-local}-$$.json"
SANITIZED_REPORT="$REPORT_DIR/newman-summary.redacted.json"

args=(
  newman run "$COLLECTION"
  --environment "$ENVIRONMENT"
  --reporters cli,json
  --reporter-json-export "$RAW_REPORT"
  --timeout-request 600000
  --timeout-script 600000
)

if [[ -n "$FOLDER" ]]; then
  args+=(--folder "$FOLDER")
fi

# Capture Newman's exit code instead of letting `set -e` abort here: on a
# failed live run Newman exits non-zero, but the sanitize + summarize steps
# below MUST still run so the failure artifacts (redacted report + timing
# summary) are produced and uploaded. Without this, a failed run uploads
# only the manifest + environment.
set +e
npx "${args[@]}"
NEWMAN_EXIT=$?
set -e

if [[ -f "$RAW_REPORT" ]]; then
  node tests/postman/scripts/sanitize-newman-report.mjs "$RAW_REPORT" "$SANITIZED_REPORT"
  node tests/postman/scripts/summarize-newman-report.mjs "$SANITIZED_REPORT" "$REPORT_DIR/timing-summary.md"
else
  echo "Newman produced no JSON report at $RAW_REPORT — skipping sanitize/summarize" >&2
fi

exit "$NEWMAN_EXIT"
