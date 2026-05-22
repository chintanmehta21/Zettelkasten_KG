import fs from 'node:fs';

const files = [
  'tests/postman/collections/zettelkasten-summarization.postman_collection.json',
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
