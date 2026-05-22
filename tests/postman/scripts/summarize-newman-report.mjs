import fs from 'node:fs';
import path from 'node:path';

const input = process.argv[2] || 'tests/postman/reports/newman-summary.json';
const output = process.argv[3] || 'tests/postman/reports/timing-summary.md';

if (!fs.existsSync(input)) {
  console.error(`Newman JSON report not found: ${input}`);
  process.exit(1);
}

const report = JSON.parse(fs.readFileSync(input, 'utf8'));
const executions = report.run?.executions || [];
const rows = executions.map((execution) => {
  const itemName = execution.item?.name || 'unknown';
  const code = execution.response?.code || 0;
  const responseTime = execution.response?.responseTime || 0;
  const assertions = execution.assertions || [];
  const failures = assertions.filter((assertion) => assertion.error).length;
  return { itemName, code, responseTime, failures };
});

const slow = rows.filter((row) => row.responseTime >= 3000);
const lines = [
  '# Postman Timing Summary',
  '',
  `Generated: ${new Date().toISOString()}`,
  '',
  '| Request | HTTP | Time ms | Failed assertions |',
  '| --- | ---: | ---: | ---: |',
  ...rows.map((row) => `| ${row.itemName.replaceAll('|', '\\|')} | ${row.code} | ${row.responseTime} | ${row.failures} |`),
  '',
  '## Slow Paths',
  '',
  slow.length
    ? slow.map((row) => `- ${row.itemName}: ${row.responseTime}ms`).join('\n')
    : '- None at or above 3000ms in this run.',
  ''
];

fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, lines.join('\n'), 'utf8');
console.log(`Wrote ${output}`);
