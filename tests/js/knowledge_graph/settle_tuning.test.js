/**
 * KG settle tuning (audit 2026-06-04): pre-settle warmup is tiered by node
 * count (floor 60, cap 250) so the first painted frame is near-final without
 * delaying first paint on big graphs; the visible drift is shortened from
 * 2500ms to GRAPH_COOLDOWN_MS. "Alive but fast."
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const APP_SRC = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8',
);

// Extract the pure-helper fence and eval it (same harness as sibling tests).
const FENCE = APP_SRC.match(
  /\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//,
)[1];
const exported = new Function(
  FENCE + '\nreturn { warmupTicksForNodeCount, GRAPH_COOLDOWN_MS };',
)();

describe('settle tuning helpers', () => {
  it('floors warmup at 60 for tiny graphs', () => {
    expect(exported.warmupTicksForNodeCount(0)).toBe(60);
    expect(exported.warmupTicksForNodeCount(10)).toBe(60);
  });
  it('scales warmup with node count in the middle band', () => {
    expect(exported.warmupTicksForNodeCount(200)).toBe(120);
    expect(exported.warmupTicksForNodeCount(300)).toBe(180);
  });
  it('caps warmup at 250 for large graphs (bounds first-paint delay)', () => {
    expect(exported.warmupTicksForNodeCount(800)).toBe(250);
    expect(exported.warmupTicksForNodeCount(5000)).toBe(250);
  });
  it('tolerates non-numeric input', () => {
    expect(exported.warmupTicksForNodeCount(undefined)).toBe(60);
    expect(exported.warmupTicksForNodeCount('x')).toBe(60);
  });
  it('shortens the visible cooldown from the old 2500ms', () => {
    expect(exported.GRAPH_COOLDOWN_MS).toBeLessThanOrEqual(1200);
    expect(exported.GRAPH_COOLDOWN_MS).toBeGreaterThanOrEqual(800);
  });
});

describe('settle tuning is wired into initGraph', () => {
  it('initGraph uses the tiered warmup, not the old flat .warmupTicks(100)', () => {
    expect(APP_SRC).toMatch(/\.warmupTicks\(\s*warmupTicksForNodeCount\(/);
    expect(APP_SRC).not.toMatch(/\.warmupTicks\(\s*100\s*\)/);
  });
  it('initGraph uses GRAPH_COOLDOWN_MS, not the old flat .cooldownTime(2500)', () => {
    expect(APP_SRC).toMatch(/\.cooldownTime\(\s*GRAPH_COOLDOWN_MS\s*\)/);
    expect(APP_SRC).not.toMatch(/\.cooldownTime\(\s*2500\s*\)/);
  });
});
