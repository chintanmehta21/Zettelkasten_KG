#!/usr/bin/env bash
set -euo pipefail

COLLECTION="${COLLECTION:-tests/postman/collections/zettelkasten-summarization.postman_collection.json}"
ENVIRONMENT="${ENVIRONMENT:-tests/postman/environments/zettelkasten.local.template.postman_environment.json}"
REPORT_DIR="${REPORT_DIR:-tests/postman/reports}"
FOLDER="${FOLDER:-}"

mkdir -p "$REPORT_DIR"

args=(
  newman run "$COLLECTION"
  --environment "$ENVIRONMENT"
  --reporters cli,json
  --reporter-json-export "$REPORT_DIR/newman-summary.json"
  --timeout-request 600000
  --timeout-script 600000
)

if [[ -n "$FOLDER" ]]; then
  args+=(--folder "$FOLDER")
fi

npx "${args[@]}"
node tests/postman/scripts/summarize-newman-report.mjs "$REPORT_DIR/newman-summary.json" "$REPORT_DIR/timing-summary.md"
