/**
 * UA-04: OAuth state CSRF mismatch regression lock.
 *
 * The codebase delegates OAuth state/PKCE validation to the Supabase JS SDK.
 * As of commit 924d9415 ("drop redundant PKCE exchange on callback page") the
 * callback does NOT call exchangeCodeForSession — a second explicit exchange
 * would burn the single-use PKCE code_verifier. Instead the SDK auto-exchanges
 * the `?code=` inside `initialize()` (driven by `detectSessionInUrl: true` +
 * `flowType: 'pkce'`); the PKCE code_verifier is the anti-CSRF binding,
 * validated inside the SDK. Our regression invariants:
 *
 *   1. callback.html MUST drive the SDK's state-validated exchange
 *      (`detectSessionInUrl: true` + `flowType: 'pkce'` + `sb.auth.initialize()`),
 *      and MUST NOT hand-roll a hash parser (or re-add exchangeCodeForSession).
 *   2. callback.html MUST surface SDK exchange errors to the user — throw on
 *      `initResult.error`, show the error block, stop the spinner, and avoid
 *      redirecting on failure.
 *   3. auth-core.js MUST configure `detectSessionInUrl: true` so the SDK
 *      enforces state on session restore.
 *
 * If any of these invariants flips, this test fails and forces a manual
 * review before a CSRF-bypass regression ships.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const CALLBACK_HTML = readFileSync(
  resolve(__dirname, '../../../website/features/user_auth/callback.html'),
  'utf8',
);
const AUTH_CORE_JS = readFileSync(
  resolve(__dirname, '../../../website/features/user_auth/js/auth-core.js'),
  'utf8',
);

describe('UA-04 OAuth state CSRF — SDK delegation invariants', () => {
  it('callback.html drives the SDK state-validated exchange (detectSessionInUrl + pkce + initialize)', () => {
    // exchangeCodeForSession was intentionally removed (commit 924d9415): a
    // second explicit exchange burns the single-use PKCE verifier. The SDK
    // auto-exchanges via initialize() under detectSessionInUrl + pkce; the PKCE
    // code_verifier is the anti-CSRF binding, validated inside the SDK.
    expect(CALLBACK_HTML).toMatch(/detectSessionInUrl\s*:\s*true/);
    expect(CALLBACK_HTML).toMatch(/flowType\s*:\s*['"]pkce['"]/);
    expect(CALLBACK_HTML).toMatch(/sb\.auth\.initialize\s*\(/);
    // Must NOT re-introduce the redundant explicit exchange call.
    expect(CALLBACK_HTML).not.toMatch(/exchangeCodeForSession\s*\(/);
  });

  it('callback.html does NOT hand-roll a hash parser around access_token', () => {
    // A hand-rolled `location.hash.split('access_token=')` style parser
    // would bypass Supabase's state-CSRF check. Forbid that pattern.
    expect(CALLBACK_HTML).not.toMatch(/location\.hash\s*\.\s*split\s*\(\s*['"]access_token/);
    expect(CALLBACK_HTML).not.toMatch(/hash\.match\s*\(\s*\/access_token/);
  });

  it('callback.html surfaces SDK errors to user (no silent redirect)', () => {
    // The error block must hide the spinner and reveal the error element
    // before throwing, so an attacker forging a state cannot land on /home.
    expect(CALLBACK_HTML).toMatch(/spinnerEl\.style\.display\s*=\s*['"]none/);
    expect(CALLBACK_HTML).toMatch(/errorEl\.style\.display\s*=\s*['"]block/);
    // The SDK exchange error (from initialize()) must be thrown, not swallowed,
    // so the catch surfaces it instead of silently redirecting to /home.
    expect(CALLBACK_HTML).toMatch(/if\s*\(\s*initResult\s*&&\s*initResult\.error\s*\)/);
    expect(CALLBACK_HTML).toMatch(/throw new Error\('OAuth exchange failed/);
  });

  it('auth-core.js enables detectSessionInUrl so SDK enforces state on restore', () => {
    expect(AUTH_CORE_JS).toMatch(/detectSessionInUrl\s*:\s*true/);
  });

  it('callback.html re-applies isSafePath after consumeReturnPath (defence in depth)', () => {
    // Even if returnTo came from a trusted store, validate the shape before
    // window.location.replace — protects against state corruption.
    expect(CALLBACK_HTML).toMatch(/isSafePath\s*\(\s*returnTo\s*\)/);
  });
});
