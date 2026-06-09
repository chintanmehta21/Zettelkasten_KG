// Lints only the CSS LINES added/changed in this PR (vs the merge base) so
// pre-existing literals in legacy files never block a PR, but any NEW raw
// border-radius does. Exit 1 on a violation on a changed line.
import { execSync } from "node:child_process";
import stylelint from "stylelint";

const base = process.env.GITHUB_BASE_REF
  ? `origin/${process.env.GITHUB_BASE_REF}`
  : "origin/master";

const diff = execSync(`git diff --unified=0 ${base}...HEAD -- "*.css"`, { encoding: "utf8" });

// Build { file -> Set(changedLineNumbers) } from the unified diff hunks.
const changed = {};
let file = null;
for (const line of diff.split("\n")) {
  const f = line.match(/^\+\+\+ b\/(.+)$/);
  if (f) { file = f[1]; changed[file] ??= new Set(); continue; }
  const h = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/);
  if (h && file) {
    const start = +h[1], count = h[2] === undefined ? 1 : +h[2];
    for (let i = 0; i < count; i++) changed[file].add(start + i);
  }
}

const files = Object.keys(changed);
if (files.length === 0) { console.log("No changed CSS files."); process.exit(0); }

// NB: must be run from the repo root (CI checkout + `npm run` both satisfy this).
const cwdNorm = process.cwd().replace(/\\/g, "/");
const { results } = await stylelint.lint({ files, configFile: ".stylelintrc.json" });
let failed = 0;
for (const r of results) {
  const srcNorm = r.source.replace(/\\/g, "/");
  const rel = srcNorm.startsWith(cwdNorm + "/") ? srcNorm.slice(cwdNorm.length + 1) : srcNorm;
  const lines = changed[rel];
  if (!lines) continue;
  for (const w of r.warnings) {
    if (lines.has(w.line)) { failed++; console.error(`✖ ${rel}:${w.line} ${w.text}`); }
  }
}
if (failed) { console.error(`\n${failed} stylelint violation(s) on changed lines.`); process.exit(1); }
console.log("✓ No stylelint violations on changed CSS lines.");
