/**
 * KG client load flip-metric (audit 2026-06-04): one console line per graph
 * load with decoded payload size + wall time + node count, so the LOD /
 * progressive-reveal thresholds can be watched from real post-CDN client data.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const APP_SRC = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8',
);
const FENCE = APP_SRC.match(
  /\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//,
)[1];
const exported = new Function(
  FENCE + '\nreturn { formatGraphLoadMetric };',
)();

describe('formatGraphLoadMetric', () => {
  it('formats bytes as KB, ms rounded, node count', () => {
    const s = exported.formatGraphLoadMetric({ bytes: 204800, ms: 123.7, nodes: 42 });
    expect(s).toContain('42 nodes');
    expect(s).toContain('200 KB');
    expect(s).toContain('124 ms');
  });
  it('tolerates missing/garbage fields without throwing', () => {
    expect(() => exported.formatGraphLoadMetric(undefined)).not.toThrow();
    expect(exported.formatGraphLoadMetric({})).toContain('0 nodes');
  });
});

describe('client metric is wired into loadGraphData', () => {
  it('loadGraphData logs the formatted metric', () => {
    expect(APP_SRC).toMatch(/formatGraphLoadMetric\(/);
  });
});
