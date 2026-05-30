/**
 * R2 (2026-05-30): lock the profile picker's save contract so a future edit
 * can't regress back to "optimistic + silent-fail + success-toast-always".
 *
 * These are source invariants (the IIFE has no exports and heavy DOM deps, so
 * the behavioral half lives in tests/js/header/set_avatar_by_id.test.js which
 * exercises the real PUT path). Here we pin that the picker:
 *   - awaits setAvatarById
 *   - passes the real profileId (not null) so the cache key is correct
 *   - threads an AbortController signal
 *   - rolls back + shows an inline error on failure
 *   - only closes the modal AFTER a successful save
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(
  resolve(__dirname, '../../../website/features/user_profile/js/user_profile.js'),
  'utf8',
);
const HTML = readFileSync(
  resolve(__dirname, '../../../website/features/user_profile/index.html'),
  'utf8',
);

describe('R2 profile avatar picker — await / rollback / abort invariants', () => {
  it('awaits ZKHeader.setAvatarById (not fire-and-forget)', () => {
    expect(SRC).toMatch(/await\s+window\.ZKHeader\.setAvatarById\s*\(/);
  });

  it('passes the real _profileId as the cache-key owner (not null)', () => {
    expect(SRC).toMatch(/setAvatarById\s*\(\s*id\s*,\s*_token\s*,\s*_profileId\s*,/);
    // And _profileId is seeded from the loaded profile.
    expect(SRC).toMatch(/_profileId\s*=\s*\(profile && profile\.id\)/);
  });

  it('threads an AbortController signal into the save', () => {
    expect(SRC).toMatch(/new AbortController\(\)/);
    expect(SRC).toMatch(/\{\s*signal:\s*myAbort\.signal\s*\}/);
  });

  it('rolls back the optimistic preview + selection on failure', () => {
    expect(SRC).toMatch(/selectAvatarOption\(prevBtn\)/);
    expect(SRC).toMatch(/paintHero\(prevId\)/);
  });

  it('surfaces a save error in the aria-live region', () => {
    expect(SRC).toMatch(/setAvatarError\(/);
    // The error element exists with role=alert in the modal.
    expect(HTML).toMatch(/id="avatar-error"[^>]*role="alert"/);
  });

  it('closes the modal only AFTER the awaited save resolves (success path)', () => {
    // closeAvatarModal must appear after the await in the try block, before the catch.
    const handler = SRC.slice(SRC.indexOf('async function handleAvatarPick'));
    const tryIdx = handler.indexOf('await window.ZKHeader.setAvatarById');
    const closeIdx = handler.indexOf('closeAvatarModal();', tryIdx);
    const catchIdx = handler.indexOf('} catch (err) {');
    expect(tryIdx).toBeGreaterThan(-1);
    expect(closeIdx).toBeGreaterThan(tryIdx);
    expect(closeIdx).toBeLessThan(catchIdx);
  });

  it('does NOT silently swallow the PUT with an empty .catch on the picker path', () => {
    // The old anti-pattern: setAvatarById(...).catch(function () {}) with no await.
    expect(SRC).not.toMatch(/setAvatarById\([^)]*\)\.catch\(function\s*\(\)\s*\{\s*\}\)/);
  });
});
