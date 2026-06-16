/**
 * Part B 1.6 — community empty-state decision (opt-out model). Only the global
 * view shows "No community zettels yet"; the Personal view keeps its Part A
 * empty handling. Pure helper, fence-extracted from app.js.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const appSrc = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8',
);
const fenced = appSrc.match(/\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//)[1];
// eslint-disable-next-line no-new-func
const { communityEmptyState } = new Function(fenced + '; return { communityEmptyState };')();

describe('communityEmptyState', () => {
  it('global view with zero nodes → show empty overlay', () => {
    expect(communityEmptyState('global', 0)).toEqual({ show: true, text: 'No community zettels yet' });
  });
  it('global view with nodes → no overlay', () => {
    expect(communityEmptyState('global', 5).show).toBe(false);
  });
  it('my view with zero nodes → not the community overlay (Part A empty handles it)', () => {
    expect(communityEmptyState('my', 0).show).toBe(false);
  });
  it('tolerates garbage node counts without throwing', () => {
    expect(communityEmptyState('global', undefined)).toEqual({ show: true, text: 'No community zettels yet' });
    expect(communityEmptyState('global', NaN).show).toBe(true);
  });
});

describe('loadGraphData wires the empty-community overlay', () => {
  it('applies communityEmptyState after the filter/init branch', () => {
    expect(appSrc).toMatch(/communityEmptyState\(currentView,/);
  });
});
