import fs from 'node:fs';
import path from 'node:path';

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  console.error('Usage: node sanitize-newman-report.mjs <input> <output>');
  process.exit(1);
}

const report = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const secretHeaderNames = new Set(['authorization', 'apikey', 'x-api-key', 'cookie', 'set-cookie']);

delete report.collection;
delete report.environment;
delete report.globals;

for (const execution of report.run?.executions || []) {
  if (execution.request?.header) {
    execution.request.header = execution.request.header.map((header) => {
      const key = String(header.key || '').toLowerCase();
      return secretHeaderNames.has(key) ? { ...header, value: '<redacted>' } : header;
    });
  }
  if (execution.response?.header) {
    execution.response.header = execution.response.header.map((header) => {
      const key = String(header.key || '').toLowerCase();
      return secretHeaderNames.has(key) ? { ...header, value: '<redacted>' } : header;
    });
  }
  if (execution.request?.body?.raw) {
    execution.request.body.raw = '<redacted body>';
  }
  if (execution.response?.stream) {
    execution.response.stream = '<redacted stream>';
  }
}

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + '\n', 'utf8');
console.log(`Wrote sanitized Newman report to ${outputPath}`);
