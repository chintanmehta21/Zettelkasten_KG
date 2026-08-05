/**
 * Vitest for pure privacy-toggle helpers (Part B Phase 1, opt-out model).
 * Fence-extracted from app.js (see test-exports markers).
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
const ctx = new Function(
  fenced + '; return { privacyToggleLabel, privacyBadge, undoToastText };'
)();
const { privacyToggleLabel, privacyBadge, undoToastText } = ctx;

describe('privacyToggleLabel', () => {
  it('public zettel → offers "Make private"', () => {
    expect(privacyToggleLabel(false)).toBe('Make private');
  });
  it('private zettel → offers "Make public"', () => {
    expect(privacyToggleLabel(true)).toBe('Make public');
  });
});

describe('privacyBadge (teal, never amber/purple)', () => {
  it('returns a teal Private badge spec when private', () => {
    const b = privacyBadge(true);
    expect(b.visible).toBe(true);
    expect(b.text).toBe('Private');
    expect(b.className).toContain('kg-private-badge');
  });
  it('hidden when public', () => {
    expect(privacyBadge(false)).toEqual({ visible: false, text: '', className: '' });
  });
});

describe('undoToastText', () => {
  it('made-private toast offers undo', () => {
    expect(undoToastText(true)).toBe('Marked private. Undo?');
  });
  it('made-public toast offers undo', () => {
    expect(undoToastText(false)).toBe('Made public. Undo?');
  });
});
