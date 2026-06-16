/**
 * Vitest: view=global must NOT send Authorization; view=my must send it.
 * Exercises the pure headersForView() helper from the test-exports fence.
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
const ctx = new Function(fenced + '; return { headersForView, buildGraphApiUrl };')();
const { headersForView, buildGraphApiUrl } = ctx;

describe('headersForView (Part B Phase 1)', () => {
  const authHeaders = () => ({ Authorization: 'Bearer tok' });
  it('drops Authorization for global', () => {
    expect(headersForView('global', authHeaders)).toEqual({});
  });
  it('keeps Authorization for my', () => {
    expect(headersForView('my', authHeaders)).toEqual({ Authorization: 'Bearer tok' });
  });
  it('treats any non-my view as global (binary)', () => {
    expect(headersForView('whatever', authHeaders)).toEqual({});
  });
});

describe('buildGraphApiUrl (Part A unchanged)', () => {
  it('still emits explicit view', () => {
    expect(buildGraphApiUrl('global', 0.3)).toContain('view=global');
    expect(buildGraphApiUrl('my', 0.3)).toContain('view=my');
  });
});
