/**
 * A4 (2026-06-15): keep the Personal toggle + isLoggedIn honest with live
 * auth state, and never leave Personal showing a stale empty graph after
 * sign-out. authChangeDecision is the PURE decision; the subscriber that
 * uses it must be synchronous (no await inside onAuthStateChange — Navigator
 * Locks deadlock, supabase-js #2013).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const APP_SRC = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8',
);
const FENCE = APP_SRC.match(
  /\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//,
)[1];
const { authChangeDecision } = new Function(
  FENCE + '\nreturn { authChangeDecision };',
)();

describe('authChangeDecision', () => {
  it('enables Personal when a session is present', () => {
    const d = authChangeDecision('TOKEN_REFRESHED', true, 'global');
    expect(d).toEqual({ isLoggedIn: true, personalEnabled: true, switchToGlobal: false });
  });
  it('on SIGNED_OUT while in Personal: disable + switch to global', () => {
    const d = authChangeDecision('SIGNED_OUT', false, 'my');
    expect(d).toEqual({ isLoggedIn: false, personalEnabled: false, switchToGlobal: true });
  });
  it('on SIGNED_OUT while in Global: disable but do not switch', () => {
    const d = authChangeDecision('SIGNED_OUT', false, 'global');
    expect(d).toEqual({ isLoggedIn: false, personalEnabled: false, switchToGlobal: false });
  });
  it('no-ops on a session-less REPLAY/RESTORE at boot', () => {
    expect(authChangeDecision('REPLAY', false, 'global')).toBeNull();
    expect(authChangeDecision('RESTORE', false, 'global')).toBeNull();
  });
});

describe('subscriber is wired and synchronous', () => {
  it('subscribes via ZKAuth.onAuthStateChange', () => {
    expect(APP_SRC).toMatch(/ZKAuth\.onAuthStateChange\(/);
  });
  it('the onAuthStateChange callback contains no await (deadlock-safe)', () => {
    // The closing `\n    });` (4-space indent) is load-bearing for this regex;
    // if the subscriber is reindented, update the terminator here too.
    const m = APP_SRC.match(
      /onAuthStateChange\(function \(event, session\) \{([\s\S]*?)\n {4}\}\);/,
    );
    expect(m, 'subscriber callback not matched — check the closing }); indentation').not.toBeNull();
    expect(m[1]).not.toMatch(/\bawait\b/);
  });
});
