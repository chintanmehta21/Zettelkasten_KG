param(
  [string]$Collection = "tests/postman/collections/zettelkasten-summarization.postman_collection.json",
  [string]$Environment = "tests/postman/environments/zettelkasten.local.template.postman_environment.json",
  [string]$ReportDir = "tests/postman/reports",
  [string]$Folder = "",
  [switch]$Bail
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$rawRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $ReportDir }
$runId = if ($env:GITHUB_RUN_ID) { $env:GITHUB_RUN_ID } else { "local" }
$rawReport = Join-Path $rawRoot ("newman-raw-{0}-{1}.json" -f $runId, $PID)
$sanitizedReport = Join-Path $ReportDir "newman-summary.redacted.json"

$argsList = @(
  "newman", "run", $Collection,
  "--environment", $Environment,
  "--reporters", "cli,json",
  "--reporter-json-export", $rawReport,
  "--timeout-request", "600000",
  "--timeout-script", "600000"
)

if ($Folder) {
  $argsList += @("--folder", $Folder)
}
if ($Bail) {
  $argsList += "--bail"
}

# Capture Newman's exit code. On a failed run the sanitize + summarize
# steps below MUST still run so the failure artifacts are produced; the
# script then exits with Newman's code so the caller still sees failure.
npx @argsList
$newmanExit = $LASTEXITCODE

if (Test-Path $rawReport) {
  node tests/postman/scripts/sanitize-newman-report.mjs $rawReport $sanitizedReport
  node tests/postman/scripts/summarize-newman-report.mjs $sanitizedReport (Join-Path $ReportDir "timing-summary.md")
} else {
  Write-Warning "Newman produced no JSON report at $rawReport - skipping sanitize/summarize"
}

exit $newmanExit
