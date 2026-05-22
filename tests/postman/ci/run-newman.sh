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

npx "${args[@]}"
node tests/postman/scripts/sanitize-newman-report.mjs "$RAW_REPORT" "$SANITIZED_REPORT"
node tests/postman/scripts/summarize-newman-report.mjs "$SANITIZED_REPORT" "$REPORT_DIR/timing-summary.md"
