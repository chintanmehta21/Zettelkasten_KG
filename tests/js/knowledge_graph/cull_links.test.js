/**
 * Vitest test for cullLinksByStrength null-handling (LD-2).
 * Extracts the test-exports block from app.js (see fence markers).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const appSrc = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8'
);
const fenced = appSrc.match(/\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//)[1];
// eslint-disable-next-line no-new-func
const ctx = new Function(fenced + '; return { cullLinksByStrength };')();
const { cullLinksByStrength } = ctx;

describe('cullLinksByStrength (LD-2)', () => {
  it('null connection_strength passes at any threshold', () => {
    const links = [{ connection_strength: null }, { connection_strength: undefined }, {}];
    expect(cullLinksByStrength(links, 0.7)).toHaveLength(3);
  });
  it('scored link below threshold is dropped', () => {
    expect(cullLinksByStrength([{ connection_strength: 0.49 }], 0.5)).toHaveLength(0);
  });
  it('scored link at threshold passes', () => {
    expect(cullLinksByStrength([{ connection_strength: 0.5 }], 0.5)).toHaveLength(1);
  });
  it('mixed null + scored: null always passes, scored gated', () => {
    const out = cullLinksByStrength(
      [{ connection_strength: null }, { connection_strength: 0.4 }, { connection_strength: 0.8 }],
      0.5
    );
    expect(out).toHaveLength(2); // null + 0.8
  });
  it('non-array input returns []', () => {
    expect(cullLinksByStrength(null, 0.5)).toEqual([]);
  });
  it('NaN or non-finite strength is dropped', () => {
    expect(cullLinksByStrength([{ connection_strength: 'foo' }], 0.5)).toHaveLength(0);
  });
});
