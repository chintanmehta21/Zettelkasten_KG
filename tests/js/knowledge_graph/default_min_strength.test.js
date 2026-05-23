/**
 * LD-1: DEFAULT_MIN_STRENGTH must equal SLIDER_MIN (0.30) so the first paint
 * is maximally permissive and matches the slider's leftmost position.
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
const ctx = new Function(fenced + '; return { DEFAULT_MIN_STRENGTH, SLIDER_MIN, bucketForStrength };')();

describe('DEFAULT_MIN_STRENGTH (LD-1)', () => {
  it('equals 0.30 (slider minimum, maximally permissive)', () => {
    expect(ctx.DEFAULT_MIN_STRENGTH).toBe(0.30);
  });
  it('equals SLIDER_MIN', () => {
    expect(ctx.DEFAULT_MIN_STRENGTH).toBe(ctx.SLIDER_MIN);
  });
  it('bucket for default = "weak"', () => {
    expect(ctx.bucketForStrength(ctx.DEFAULT_MIN_STRENGTH)).toBe('weak');
  });
});
