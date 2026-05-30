import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(
  resolve(__dirname, '../../../website/features/functional_gates/js/quota_gate.js'),
  'utf8',
);

function load() {
  delete window.ZKQuotaGate;
  // eslint-disable-next-line no-new-func
  new Function('window', SRC).call(window, window);
  return window.ZKQuotaGate;
}

describe('ZKQuotaGate.extractQuotaDetail', () => {
  let g;
  beforeEach(() => { g = load(); });

  it('matches the sync/normalized detail dict', () => {
    const d = g.extractQuotaDetail({ detail: { code: 'quota_exhausted', meter: 'zettel' } });
    expect(d).toEqual({ code: 'quota_exhausted', meter: 'zettel' });
  });

  it('matches a direct quota dict', () => {
    const d = g.extractQuotaDetail({ code: 'quota_exhausted', meter: 'kasten' });
    expect(d.meter).toBe('kasten');
  });

  it('matches a raw failed-op body via error.detail', () => {
    const d = g.extractQuotaDetail({ status: 'failed', error: {
      code: 'quota-exhausted', detail: { code: 'quota_exhausted', meter: 'zettel' } } });
    expect(d.code).toBe('quota_exhausted');
    expect(d.meter).toBe('zettel');
  });

  it('normalizes the hyphen-slug form to the underscore canonical', () => {
    const d = g.extractQuotaDetail({ code: 'quota-exhausted', detail: { meter: 'rag_question' } });
    expect(d.code).toBe('quota_exhausted');
    expect(d.meter).toBe('rag_question');
  });

  it('returns null for near-misses (no false positives)', () => {
    expect(g.extractQuotaDetail({ detail: { code: 'quota_warning', meter: 'zettel' } })).toBeNull();
    expect(g.extractQuotaDetail({ detail: { code: 'insufficient-content' }, title: 'quota? no' })).toBeNull();
    expect(g.extractQuotaDetail({ code: 'quota-exhausted' })).toBeNull(); // slug w/o meter
    expect(g.extractQuotaDetail(null)).toBeNull();
    expect(g.extractQuotaDetail('quota_exhausted')).toBeNull();
  });
});
