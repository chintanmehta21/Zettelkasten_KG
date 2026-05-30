/**
 * R6 (2026-05-30): ZKAvatar is the single source of truth for the current
 * user's avatar. It must (1) accept ONLY curated /artifacts/avatars/avatar_NN.svg
 * URLs (closing the non-curated user_metadata leak), (2) write-through a
 * per-profile localStorage cache, and (3) notify subscribers on change.
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
const CURATED = '/artifacts/avatars/avatar_25.svg';
const EXTERNAL = 'https://lh3.googleusercontent.com/evil.jpg';

describe('R6 ZKAvatar — curated-only source of truth', () => {
  beforeEach(() => {
    try { localStorage.clear(); } catch (_) { /* noop */ }
  });

  it('accepts only curated avatar URLs', () => {
    const ZK = loadZKAvatar();
    expect(ZK.isCurated(CURATED)).toBe(true);
    expect(ZK.isCurated(EXTERNAL)).toBe(false);
    expect(ZK.isCurated('/artifacts/avatars/avatar_60.svg')).toBe(false); // out of range
    expect(ZK.isCurated('javascript:alert(1)')).toBe(false);
    expect(ZK.isCurated(null)).toBe(false);
  });

  it('set() coerces a non-curated URL to the resolved default', () => {
    const ZK = loadZKAvatar();
    const accepted = ZK.set(PID, EXTERNAL);
    expect(accepted).toBe(ZK.DEFAULT_AVATAR);
    expect(ZK.current()).toBe(ZK.DEFAULT_AVATAR);
  });

  it('set() persists a curated URL to the per-profile cache', () => {
    const ZK = loadZKAvatar();
    ZK.set(PID, CURATED);
    expect(localStorage.getItem('zk-avatar-url-' + PID)).toBe(CURATED);
    // Non-curated must never be cached.
    expect(localStorage.getItem('zk-avatar-url-anon')).toBeNull();
  });

  it('resolve() prefers curated input > cache > default without mutating state', () => {
    const ZK = loadZKAvatar();
    localStorage.setItem('zk-avatar-url-' + PID, '/artifacts/avatars/avatar_09.svg');
    expect(ZK.resolve(PID, CURATED)).toBe(CURATED);                       // curated input wins
    expect(ZK.resolve(PID, EXTERNAL)).toBe('/artifacts/avatars/avatar_09.svg'); // cache
    expect(ZK.resolve('other', EXTERNAL)).toBe(ZK.DEFAULT_AVATAR);        // default
    expect(ZK.current()).toBe(ZK.DEFAULT_AVATAR);                         // resolve() didn't mutate
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
    ZK.set(PID, CURATED);  // same value
    expect(cb).not.toHaveBeenCalled();
  });

  it('silent:true seeds without notifying (header boot path)', () => {
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

describe('R3 ZKAvatar — cross-tab sync (storage-event fallback)', () => {
  beforeEach(() => {
    try { localStorage.clear(); } catch (_) { /* noop */ }
  });

  it('falls back to the storage ping when BroadcastChannel is unavailable', () => {
    // Force the iOS-Safari-<15.4 / private-window path by removing BroadcastChannel
    // BEFORE the module captures it at load time.
    vi.stubGlobal('BroadcastChannel', undefined);
    const ZK = loadZKAvatar();
    ZK.set(PID, CURATED);
    const ping = localStorage.getItem('zk-avatar-bcast');
    expect(ping).toBeTruthy();
    expect(JSON.parse(ping).detail.url).toBe(CURATED);
    vi.unstubAllGlobals();
  });

  it('a silent seed does NOT broadcast to other tabs', () => {
    vi.stubGlobal('BroadcastChannel', undefined);
    const ZK = loadZKAvatar();
    ZK.set(PID, CURATED, { silent: true });
    expect(localStorage.getItem('zk-avatar-bcast')).toBeNull();
    vi.unstubAllGlobals();
  });

  it('an incoming storage ping applies remotely and notifies subscribers', () => {
    const ZK = loadZKAvatar();
    const cb = vi.fn();
    ZK.subscribe(cb, { immediate: false });

    const remote = '/artifacts/avatars/avatar_31.svg';
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'zk-avatar-bcast',
      newValue: JSON.stringify({ detail: { profileId: PID, url: remote }, n: 1 }),
    }));

    expect(ZK.current()).toBe(remote);
    expect(cb).toHaveBeenCalledWith({ profileId: PID, url: remote });
  });

  it('ignores a non-curated remote ping (no XSS via another tab)', () => {
    const ZK = loadZKAvatar();
    ZK.set(PID, CURATED, { silent: true });
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'zk-avatar-bcast',
      newValue: JSON.stringify({ detail: { profileId: PID, url: EXTERNAL }, n: 2 }),
    }));
    expect(ZK.current()).toBe(CURATED);  // unchanged
  });
});
