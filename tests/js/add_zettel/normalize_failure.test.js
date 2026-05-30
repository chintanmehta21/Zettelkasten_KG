import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(
  resolve(__dirname, '../../../website/static/js/add_zettel_api.js'),
  'utf8',
);

function load() {
  delete window.ZKAddZettel;
  // eslint-disable-next-line no-new-func
  new Function('window', SRC).call(window, window);
  return window.ZKAddZettel;
}

describe('ZKAddZettel._normalizeFailure', () => {
  let api;
  beforeEach(() => { api = load(); });

  it('extracts the inner quota detail from an async failed-op envelope', () => {
    const next = {
      status: 'failed',
      operation_id: 'op1',
      error: {
        type: '.../quota-exhausted',
        title: 'You have used your included zettels.',
        status: 402,
        detail: { code: 'quota_exhausted', meter: 'zettel', recommended_products: ['zettel_10'] },
        code: 'quota-exhausted',
      },
    };
    const n = api._normalizeFailure(next);
    expect(n.detail.code).toBe('quota_exhausted');
    expect(n.detail.meter).toBe('zettel');
    expect(n.message).toBe('You have used your included zettels.');
  });

  it('uses the problem title for non-quota failures (string detail)', () => {
    const next = {
      status: 'failed',
      error: { title: 'Insufficient content', status: 422,
               detail: 'Could not extract enough content.', code: 'insufficient-content' },
    };
    const n = api._normalizeFailure(next);
    expect(n.message).toBe('Insufficient content');
    expect(n.detail.code).toBe('insufficient-content');
  });

  it('falls back to a generic message when no title is present', () => {
    const n = api._normalizeFailure({ status: 'failed' });
    expect(n.message).toBe('Summary failed.');
  });
});
