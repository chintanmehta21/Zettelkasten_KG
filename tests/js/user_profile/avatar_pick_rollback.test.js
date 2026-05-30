/**
 * R2 (2026-05-30): lock the profile picker's save contract so a future edit
 * can't regress to "optimistic + silent-fail + success-toast-always".
 *
 * Source invariants (the IIFE has no exports + heavy DOM deps; the behavioral
 * half lives in tests/js/header/set_avatar_by_id.test.js). Here we pin that the
 * picker awaits, passes the real profileId, threads an AbortController, rolls
 * back + shows an inline error on failure, and closes the modal only on success.
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

  it('reverts the hero to the fallback glyph when there is no previous avatar', () => {
    // prevId === null (user had no curated avatar): the optimistic paintHero(id)
    // must not be left on the unsaved avatar — restore the fallback instead.
    expect(SRC).toMatch(/else\s+restoreHeroFallback\(\)/);
    expect(SRC).toMatch(/function restoreHeroFallback\(\)/);
  });

  it('surfaces a save error in the aria-live region', () => {
    expect(SRC).toMatch(/setAvatarError\(/);
    expect(HTML).toMatch(/id="avatar-error"[^>]*role="alert"/);
  });

  it('loads header.js so window.ZKHeader exists on the profile page', () => {
    // The primary "avatars not updating" bug: profile page omitted header.js,
    // so setAvatarById was skipped. Pin that the script is present.
    expect(HTML).toMatch(/<script[^>]+\/header\/js\/header\.js/);
  });

  it('closes the modal only AFTER the awaited save resolves (success path)', () => {
    const handler = SRC.slice(SRC.indexOf('async function handleAvatarPick'));
    const tryIdx = handler.indexOf('await window.ZKHeader.setAvatarById');
    const closeIdx = handler.indexOf('closeAvatarModal();', tryIdx);
    const catchIdx = handler.indexOf('} catch (err) {');
    expect(tryIdx).toBeGreaterThan(-1);
    expect(closeIdx).toBeGreaterThan(tryIdx);
    expect(closeIdx).toBeLessThan(catchIdx);
  });

  it('does NOT silently swallow the PUT with an empty .catch on the picker path', () => {
    expect(SRC).not.toMatch(/setAvatarById\([^)]*\)\.catch\(function\s*\(\)\s*\{\s*\}\)/);
  });
});
