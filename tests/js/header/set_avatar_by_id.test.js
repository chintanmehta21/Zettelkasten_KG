/**
 * R2 (2026-05-30): ZKHeader.setAvatarById must AWAIT the PUT and propagate
 * failures so the profile picker can roll back + surface an error.
 *
 * Before R2 the PUT was fire-and-forget with `.catch(()=>{})`, so a 401/404/500
 * was invisible and the picker toasted success while nothing persisted. These
 * tests load the real header.js IIFE into jsdom and exercise the contract:
 *
 *   1. On 2xx → resolves with the {avatar_url} body.
 *   2. On non-2xx → REJECTS with err.status set (no silent swallow).
 *   3. The AbortSignal is threaded into the fetch options (rapid re-pick).
 *   4. The localStorage cache is written under the real profileId, not 'anon'.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const HEADER_JS = readFileSync(
  resolve(__dirname, '../../../website/features/header/js/header.js'),
  'utf8',
);

function loadHeader(fetchImpl) {
  // Minimal header DOM so resolveRefs() finds the avatar img.
  document.body.innerHTML = `
    <div id="avatar-wrap">
      <button id="avatar-btn" aria-expanded="false"></button>
      <img id="avatar-img" hidden />
      <span id="avatar-fallback"></span>
      <div id="avatar-dropdown"></div>
    </div>`;
  // Stub Image so preload() resolves immediately (jsdom Image never loads).
  class FakeImage {
    set src(v) { this._src = v; if (this.onload) setTimeout(() => this.onload(), 0); }
    get src() { return this._src; }
  }
  vi.stubGlobal('Image', FakeImage);
  // header.js captures `var zkFetch = window.zkFetch || window.fetch` at IIFE
  // eval time, so the fetch stub MUST be installed before we evaluate it.
  if (fetchImpl) vi.stubGlobal('fetch', fetchImpl);
  // Evaluate the IIFE in this realm.
  // eslint-disable-next-line no-new-func
  new Function(HEADER_JS)();
  // header binds initBasics on DOMContentLoaded OR immediately if not loading.
  return window.ZKHeader;
}

const PROFILE_ID = '550e8400-e29b-41d4-a716-446655440000';

describe('R2 ZKHeader.setAvatarById — awaited PUT, propagated failures', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    try { localStorage.clear(); } catch (_) { /* noop */ }
  });

  it('resolves with {avatar_url} on a 2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ avatar_url: '/artifacts/avatars/avatar_07.svg' }),
    });
    const ZK = loadHeader(fetchMock);

    const out = await ZK.setAvatarById(7, 'tok', PROFILE_ID);
    expect(out.avatar_url).toBe('/artifacts/avatars/avatar_07.svg');
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/me/avatar');
    expect(opts.method).toBe('PUT');
    expect(JSON.parse(opts.body)).toEqual({ avatar_id: 7 });
  });

  it('REJECTS with err.status on a non-2xx response (no silent swallow)', async () => {
    const ZK = loadHeader(vi.fn().mockResolvedValue({ ok: false, status: 404 }));

    await expect(ZK.setAvatarById(7, 'tok', PROFILE_ID)).rejects.toMatchObject({ status: 404 });
  });

  it('REJECTS when the network throws', async () => {
    const ZK = loadHeader(vi.fn().mockRejectedValue(new Error('network down')));

    await expect(ZK.setAvatarById(7, 'tok', PROFILE_ID)).rejects.toThrow();
  });

  it('threads the AbortSignal into the fetch options', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: () => Promise.resolve({ avatar_url: '/artifacts/avatars/avatar_03.svg' }),
    });
    const ZK = loadHeader(fetchMock);
    const ctrl = new AbortController();

    await ZK.setAvatarById(3, 'tok', PROFILE_ID, { signal: ctrl.signal });
    expect(fetchMock.mock.calls[0][1].signal).toBe(ctrl.signal);
  });

  it('writes the localStorage cache under the real profileId, not anon', async () => {
    const ZK = loadHeader(vi.fn().mockResolvedValue({
      ok: true, json: () => Promise.resolve({ avatar_url: '/artifacts/avatars/avatar_09.svg' }),
    }));

    await ZK.setAvatarById(9, 'tok', PROFILE_ID);
    expect(localStorage.getItem('zk-avatar-url-' + PROFILE_ID))
      .toBe('/artifacts/avatars/avatar_09.svg');
    expect(localStorage.getItem('zk-avatar-url-anon')).toBeNull();
  });

  it('returns visual-only (no fetch) when no token is supplied', async () => {
    const fetchMock = vi.fn();
    const ZK = loadHeader(fetchMock);

    const out = await ZK.setAvatarById(5, '', PROFILE_ID);
    expect(out.avatar_url).toBe('/artifacts/avatars/avatar_05.svg');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
