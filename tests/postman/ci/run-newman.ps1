param(
  [string]$Collection = "tests/postman/collections/zettelkasten-summarization.postman_collection.json",
  [string]$Environment = "tests/postman/environments/zettelkasten.local.template.postman_environment.json",
  [string]$ReportDir = "tests/postman/reports",
  [string]$Folder = "",
  [switch]$Bail
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$argsList = @(
  "newman", "run", $Collection,
  "--environment", $Environment,
  "--reporters", "cli,json",
  "--reporter-json-export", (Join-Path $ReportDir "newman-summary.json"),
  "--timeout-request", "600000",
  "--timeout-script", "600000"
)

if ($Folder) {
  $argsList += @("--folder", $Folder)
}
if ($Bail) {
  $argsList += "--bail"
}

npx @argsList
node tests/postman/scripts/summarize-newman-report.mjs (Join-Path $ReportDir "newman-summary.json") (Join-Path $ReportDir "timing-summary.md")
