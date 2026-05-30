import { describe, it, expect, beforeEach, vi } from 'vitest';
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

describe('ZKQuotaGate.precheck', () => {
  let g, shown;
  beforeEach(() => {
    g = load();
    shown = [];
    g.show = (opts) => { shown.push(opts); return Promise.resolve('dismiss'); };
  });

  function mockFetch(impl) { window.fetch = vi.fn(impl); }

  it('blocks and shows the modal when effective_available <= 0', async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ feature: 'zettel', effective_available: 0 }) }));
    const ok = await g.precheck({ feature: 'zettel', token: 't', source: 'home' });
    expect(ok).toBe(false);
    expect(shown).toHaveLength(1);
    expect(shown[0].detail).toEqual({ code: 'quota_exhausted', meter: 'zettel' });
  });

  it('proceeds when balance is sufficient (no modal)', async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ effective_available: 3 }) }));
    const ok = await g.precheck({ feature: 'zettel', token: 't' });
    expect(ok).toBe(true);
    expect(shown).toHaveLength(0);
  });

  it('fail-open proceeds on null (unknown) balance', async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ effective_available: null }) }));
    expect(await g.precheck({ feature: 'zettel', token: 't' })).toBe(true);
    expect(shown).toHaveLength(0);
  });

  it('fail-open proceeds on a non-2xx response', async () => {
    mockFetch(async () => ({ ok: false, status: 500, json: async () => ({}) }));
    expect(await g.precheck({ feature: 'zettel', token: 't' })).toBe(true);
    expect(shown).toHaveLength(0);
  });

  it('fail-open proceeds on a transport error', async () => {
    mockFetch(async () => { throw new Error('network down'); });
    expect(await g.precheck({ feature: 'zettel', token: 't' })).toBe(true);
    expect(shown).toHaveLength(0);
  });

  it('a well-formed 0 NEVER fails open (modal shown, blocked)', async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ effective_available: 0 }) }));
    expect(await g.precheck({ feature: 'zettel', token: 't' })).toBe(false);
  });

  it('collapses concurrent double-submits into one fetch', async () => {
    let calls = 0;
    mockFetch(async () => { calls += 1; return { ok: true, json: async () => ({ effective_available: 5 }) }; });
    const [a, b] = await Promise.all([
      g.precheck({ feature: 'zettel', token: 't' }),
      g.precheck({ feature: 'zettel', token: 't' }),
    ]);
    expect(a).toBe(true); expect(b).toBe(true);
    expect(calls).toBe(1);
  });
});
