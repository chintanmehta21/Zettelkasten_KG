import fs from 'node:fs';

// Allowlist of Postman JSON files (collections + environment template +
// smoke data sets). Update this list when adding a new collection so the
// CI validate-collection step doesn't silently skip it. Locked here as the
// single source of truth (Codex / new_apis_1a 2026-05-23 reconciliation).
const files = [
  'tests/postman/collections/zettelkasten-summarization.postman_collection.json',
  'tests/postman/collections/zettelkasten-kastens.postman_collection.json',
  'tests/postman/collections/zettelkasten-ask-kasten.postman_collection.json',
  'tests/postman/collections/zettelkasten-graph.postman_collection.json',
  'tests/postman/environments/zettelkasten.local.template.postman_environment.json',
  'tests/postman/data/summarization-smoke.postman_data.json'
];

for (const file of files) {
  try {
    JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    console.error(`${file}: ${error.message}`);
    process.exitCode = 1;
  }
}

if (process.exitCode) {
  process.exit(process.exitCode);
}

console.log(`Validated ${files.length} Postman JSON files.`);
