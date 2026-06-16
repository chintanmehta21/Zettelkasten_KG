/**
 * Vitest for the pure signup/first-use public-content notice helper.
 * Fence-extracted from home.js (new test-exports markers added in Task 1.8).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const homeSrc = readFileSync(
  resolve(__dirname, '../../../website/features/user_home/js/home.js'),
  'utf8'
);
const fenced = homeSrc.match(/\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//)[1];
// eslint-disable-next-line no-new-func
const ctx = new Function(fenced + '; return { shouldShowPublicNotice, publicNoticeText };')();
const { shouldShowPublicNotice, publicNoticeText } = ctx;

describe('shouldShowPublicNotice', () => {
  it('shows when never dismissed', () => {
    expect(shouldShowPublicNotice(null)).toBe(true);
    expect(shouldShowPublicNotice('')).toBe(true);
  });
  it('hidden once dismissed', () => {
    expect(shouldShowPublicNotice('1')).toBe(false);
  });
});

describe('publicNoticeText', () => {
  it('states zettels are public + attributed + how to hide', () => {
    const t = publicNoticeText();
    expect(t).toContain('public');
    expect(t.toLowerCase()).toContain('display name');
    expect(t.toLowerCase()).toContain('private');
  });
});
