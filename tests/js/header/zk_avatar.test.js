/**
 * R6/R3 (2026-05-30): ZKAvatar is the single source of truth for the current
 * user's avatar. It accepts ONLY curated /artifacts/avatars/avatar_NN.svg URLs
 * (0-119, matching app.py::_CURATED_AVATAR_RE), write-throughs a per-profile
 * localStorage cache, notifies subscribers, syncs cross-tab, and bridges to the
 * existing zk:avatar-changed event so it unifies with the mobile surfaces.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(
  resolve(__dirname, '../../../website/features/header/js/zk_avatar.js'),
  'utf8',
);

function loadZKAvatar() {
  delete window.ZKAvatar;
  // eslint-disable-next-line no-new-func
  new Function(SRC)();
  return window.ZKAvatar;
}

const PID = '550e8400-e29b-41d4-a716-446655440000';
const CURATED = '/artifacts/avatars/avatar_99.svg';   // 99 in [0,119]
const EXTERNAL = 'https://lh3.googleusercontent.com/evil.jpg';

describe('R6 ZKAvatar — curated-only source of truth (0-119)', () => {
  beforeEach(() => { try { localStorage.clear(); } catch (_) { /* noop */ } });

  it('accepts curated 0-119 URLs, rejects everything else', () => {
    const ZK = loadZKAvatar();
    expect(ZK.isCurated('/artifacts/avatars/avatar_00.svg')).toBe(true);
    expect(ZK.isCurated('/artifacts/avatars/avatar_59.svg')).toBe(true);
    expect(ZK.isCurated('/artifacts/avatars/avatar_119.svg')).toBe(true);
    expect(ZK.isCurated('/artifacts/avatars/avatar_120.svg')).toBe(false); // out of range
    expect(ZK.isCurated('/artifacts/avatars/avatar_0.svg')).toBe(false);   // 1-digit
    expect(ZK.isCurated(EXTERNAL)).toBe(false);
    expect(ZK.isCurated('javascript:alert(1)')).toBe(false);
    expect(ZK.isCurated(null)).toBe(false);
  });

  it('set() coerces a non-curated URL to the resolved default', () => {
    const ZK = loadZKAvatar();
    expect(ZK.set(PID, EXTERNAL)).toBe(ZK.DEFAULT_AVATAR);
    expect(ZK.current()).toBe(ZK.DEFAULT_AVATAR);
  });

  it('set() persists a curated URL to the per-profile cache', () => {
    const ZK = loadZKAvatar();
    ZK.set(PID, CURATED);
    expect(localStorage.getItem('zk-avatar-url-' + PID)).toBe(CURATED);
    expect(localStorage.getItem('zk-avatar-url-anon')).toBeNull();
  });

  it('resolve() prefers curated input > cache > default without mutating state', () => {
    const ZK = loadZKAvatar();
    localStorage.setItem('zk-avatar-url-' + PID, '/artifacts/avatars/avatar_09.svg');
    expect(ZK.resolve(PID, CURATED)).toBe(CURATED);
    expect(ZK.resolve(PID, EXTERNAL)).toBe('/artifacts/avatars/avatar_09.svg');
    expect(ZK.resolve('other', EXTERNAL)).toBe(ZK.DEFAULT_AVATAR);
    expect(ZK.current()).toBe(ZK.DEFAULT_AVATAR);
  });

  it('notifies subscribers on change with the accepted url', () => {
    const ZK = loadZKAvatar();
    const cb = vi.fn();
    ZK.subscribe(cb, { immediate: false });
    ZK.set(PID, CURATED);
    expect(cb).toHaveBeenCalledWith({ profileId: PID, url: CURATED });
  });

  it('does NOT re-notify when the value is unchanged', () => {
    const ZK = loadZKAvatar();
    ZK.set(PID, CURATED);
    const cb = vi.fn();
    ZK.subscribe(cb, { immediate: false });
    ZK.set(PID, CURATED);
    expect(cb).not.toHaveBeenCalled();
  });

  it('silent:true seeds without notifying', () => {
    const ZK = loadZKAvatar();
    const cb = vi.fn();
    ZK.subscribe(cb, { immediate: false });
    ZK.set(PID, CURATED, { silent: true });
    expect(cb).not.toHaveBeenCalled();
    expect(ZK.current()).toBe(CURATED);
  });

  it('subscribe() returns a working unsubscribe', () => {
    const ZK = loadZKAvatar();
    const cb = vi.fn();
    const off = ZK.subscribe(cb, { immediate: false });
    off();
    ZK.set(PID, CURATED);
    expect(cb).not.toHaveBeenCalled();
  });
});

describe('R6 ZKAvatar — bridge to existing zk:avatar-changed', () => {
  beforeEach(() => { try { localStorage.clear(); } catch (_) { /* noop */ } });

  it('set() dispatches zk:avatar-changed for mobile-style listeners', () => {
    const ZK = loadZKAvatar();
    const seen = [];
    document.addEventListener('zk:avatar-changed', (e) => seen.push(e.detail && e.detail.url));
    ZK.set(PID, CURATED);
    expect(seen).toContain(CURATED);
  });

  it('an incoming zk:avatar-changed updates ZKAvatar + subscribers', () => {
    const ZK = loadZKAvatar();
    const cb = vi.fn();
    ZK.subscribe(cb, { immediate: false });
    const remote = '/artifacts/avatars/avatar_31.svg';
    document.dispatchEvent(new CustomEvent('zk:avatar-changed', { detail: { profileId: PID, url: remote } }));
    expect(ZK.current()).toBe(remote);
    expect(cb).toHaveBeenCalledWith({ profileId: PID, url: remote });
  });

  it('ignores a non-curated zk:avatar-changed (no XSS via the bridge)', () => {
    const ZK = loadZKAvatar();
    ZK.set(PID, CURATED, { silent: true });
    document.dispatchEvent(new CustomEvent('zk:avatar-changed', { detail: { profileId: PID, url: EXTERNAL } }));
    expect(ZK.current()).toBe(CURATED);
  });
});

describe('R3 ZKAvatar — cross-tab storage fallback', () => {
  beforeEach(() => { try { localStorage.clear(); } catch (_) { /* noop */ } });

  it('falls back to the storage ping when BroadcastChannel is unavailable', () => {
    vi.stubGlobal('BroadcastChannel', undefined);
    const ZK = loadZKAvatar();
    ZK.set(PID, CURATED);
    const ping = localStorage.getItem('zk-avatar-bcast');
    expect(ping).toBeTruthy();
    expect(JSON.parse(ping).detail.url).toBe(CURATED);
    vi.unstubAllGlobals();
  });

  it('an incoming storage ping applies remotely + notifies', () => {
    const ZK = loadZKAvatar();
    const cb = vi.fn();
    ZK.subscribe(cb, { immediate: false });
    const remote = '/artifacts/avatars/avatar_77.svg';
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'zk-avatar-bcast',
      newValue: JSON.stringify({ detail: { profileId: PID, url: remote }, n: 1 }),
    }));
    expect(ZK.current()).toBe(remote);
    expect(cb).toHaveBeenCalledWith({ profileId: PID, url: remote });
  });
});
