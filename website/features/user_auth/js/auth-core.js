/**
 * Zettelkasten Auth — shared core slice.
 *
 * Owns ONLY the auth surface that the desktop landing, the /pricing page,
 * and the mobile shell all share:
 *   - Supabase client construction (single source of truth — no duplicate
 *     "Multiple GoTrueClient instances" warnings).
 *   - /api/auth/config fetch + client bootstrap.
 *   - Session state cache (localStorage 'zk-auth-token').
 *   - Browser-cache state (hasLoggedIn / allowCredentialStorage / landingPath)
 *     via window.browserCache, with safe fallbacks.
 *   - Redirect-loop guard for /  → /home auto-redirect of authenticated users.
 *   - signOut.
 *   - window.ZKAuth { ready, getClient, getSession, onAuthStateChange, signOut }.
 *   - Compat globals window.getAuthToken / window.signOut / window.signInWithGoogle.
 *
 * Does NOT touch any landing-specific DOM (#login-btn / #user-menu / #login-modal /
 * .provider-item / etc.) — those live in auth.js, which the desktop landing +
 * /pricing also load right after this script. Mobile pages load only this file
 * because mobile/js/auth-modal.js owns the mobile DOM.
 */

(function () {
  'use strict';

  var _supabaseClient = null;
  var _currentSession = null;
  var _subscribers = [];

  function getCacheState() {
    if (!window.browserCache || typeof window.browserCache.getState !== 'function') {
      return {
        allowCredentialStorage: false,
        hasLoggedIn: false,
        landingPath: '/home',
        theme: '',
        updatedAt: 0,
      };
    }
    return window.browserCache.getState();
  }

  function patchCacheState(partial) {
    if (!window.browserCache || typeof window.browserCache.patchState !== 'function') return;
    window.browserCache.patchState(partial);
  }

  function setReturnPath(path) {
    if (window.browserCache && typeof window.browserCache.setReturnPath === 'function') {
      window.browserCache.setReturnPath(path);
      return;
    }
    try {
      sessionStorage.setItem('auth_return_to', path);
    } catch (_err) {
      // sessionStorage may be unavailable (private mode + cookie block);
      // failing silently is fine — the callback handler defaults to /home.
    }
  }

  function isLandingPage() {
    return window.location.pathname === '/';
  }

  // Auto-redirect authenticated visitors from the public landing to /home,
  // unless a recent redirect (<5s) suggests /home just bounced us back —
  // which would indicate an auth-loop bug we should surface in the console
  // rather than silently hammer.
  function maybeRedirectAuthenticated(session) {
    if (!session || !session.user || !isLandingPage()) return;
    var lastRedirect = parseInt(sessionStorage.getItem('zk-auth-redirect') || '0', 10);
    if (Date.now() - lastRedirect < 5000) {
      console.warn('[auth-core] Redirect loop detected, staying on landing page');
      return;
    }
    sessionStorage.setItem('zk-auth-redirect', String(Date.now()));
    var state = getCacheState();
    if (!state.hasLoggedIn) {
      patchCacheState({
        hasLoggedIn: true,
        allowCredentialStorage: true,
        landingPath: '/home',
      });
    }
    window.location.replace('/home');
  }

  function createSupabaseClient(config) {
    // storageKey 'zk-auth-token' is the production key — DO NOT rename
    // without coordinating with user_profile.js, user_zettels.js and the
    // KG add-to-Kasten path, which all reach into localStorage by this
    // exact key (see "Y2 auth token scoped to current Supabase project ref"
    // commit cc1a9aca).
    return supabase.createClient(config.supabase_url, config.supabase_anon_key, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        storage: window.localStorage,
        storageKey: 'zk-auth-token',
      },
    });
  }

  // Fan-out: every subscriber registered via window.ZKAuth.onAuthStateChange
  // gets the same (event, session) tuple. Subscribers run in registration
  // order; an exception in one MUST NOT silence later subscribers (e.g.
  // mobile auth-modal must still hide on SIGNED_IN even if a desktop
  // updateUI throws on a page that lacks #login-btn).
  function emit(eventName, session) {
    for (var i = 0; i < _subscribers.length; i += 1) {
      try {
        _subscribers[i](eventName, session);
      } catch (err) {
        console.error('[auth-core] subscriber threw on', eventName, err);
      }
    }
  }

  // Single canonical session handler: keeps internal state in sync, updates
  // the browser-cache hints, runs the landing-page redirect, then fans the
  // event out to all subscribers (desktop UI, mobile UI, pricing.js, …).
  function handleCoreSession(eventName, session) {
    _currentSession = session;

    if (!session || !session.user) {
      if (eventName === 'SIGNED_OUT') {
        patchCacheState({ hasLoggedIn: false, allowCredentialStorage: false });
      }
      emit(eventName, session);
      return;
    }

    patchCacheState({
      hasLoggedIn: true,
      allowCredentialStorage: true,
      landingPath: '/home',
    });

    emit(eventName, session);

    if (eventName === 'SIGNED_IN' && isLandingPage()) {
      sessionStorage.setItem('zk-auth-redirect', String(Date.now()));
      sessionStorage.removeItem('zk-home-redirect');
      window.location.replace('/home');
      return;
    }
    if (eventName !== 'SIGNED_IN') {
      // RESTORE / TOKEN_REFRESHED / USER_UPDATED — landing page may also
      // need the bounce if the user is just visiting / while signed in.
      maybeRedirectAuthenticated(session);
    }
  }

  async function init() {
    try {
      var resp = await fetch('/api/auth/config');
      var config = await resp.json();
      if (!config.supabase_url || !config.supabase_anon_key) {
        // No config = no auth. Subscribers still get a synthetic SIGNED_OUT
        // so they can hide their sign-in chrome cleanly.
        emit('SIGNED_OUT', null);
        if (window.ZKAuth && typeof window.ZKAuth.__signalReady === 'function') {
          window.ZKAuth.__signalReady();
        }
        return;
      }

      _supabaseClient = createSupabaseClient(config);

      // Subscribe ourselves to Supabase first so RESTORE/TOKEN_REFRESHED
      // events fan out to consumers as soon as they happen.
      _supabaseClient.auth.onAuthStateChange(function (event, session) {
        handleCoreSession(event, session);
      });

      // Signal ready BEFORE awaiting getSession so peers (pricing.js,
      // mobile auth-modal) can grab the client during the network round-trip
      // — they'll receive the initial RESTORE event via the subscription.
      if (window.ZKAuth && typeof window.ZKAuth.__signalReady === 'function') {
        window.ZKAuth.__signalReady();
      }

      var result = await _supabaseClient.auth.getSession();
      handleCoreSession('RESTORE', result.data.session);
    } catch (err) {
      console.error('[auth-core] Init failed:', err);
    }
  }

  async function signOut() {
    if (!_supabaseClient) return;
    await _supabaseClient.auth.signOut();
    _currentSession = null;
    patchCacheState({ hasLoggedIn: false, allowCredentialStorage: false });
    emit('SIGNED_OUT', null);
  }

  // ---- Public API ----

  var _readyResolve;
  window.ZKAuth = window.ZKAuth || {};
  window.ZKAuth.ready = new Promise(function (resolve) { _readyResolve = resolve; });
  window.ZKAuth.getClient = function () { return _supabaseClient; };
  window.ZKAuth.getSession = function () { return _currentSession; };
  window.ZKAuth.signOut = signOut;
  window.ZKAuth.onAuthStateChange = function (cb) {
    if (typeof cb !== 'function') return function () {};
    _subscribers.push(cb);
    // Replay the current state so late subscribers don't miss the initial
    // RESTORE — important for scripts that defer-load after init() has
    // already fanned out the first event.
    if (_currentSession !== undefined) {
      try { cb('REPLAY', _currentSession); } catch (err) {
        console.error('[auth-core] subscriber threw on REPLAY', err);
      }
    }
    return function unsubscribe() {
      var idx = _subscribers.indexOf(cb);
      if (idx !== -1) _subscribers.splice(idx, 1);
    };
  };
  window.ZKAuth.__signalReady = function () {
    if (_readyResolve) { _readyResolve(_supabaseClient); _readyResolve = null; }
  };

  // Helpers that auth.js (DOM layer) and tests still need to share.
  window.ZKAuth._internal = {
    setReturnPath: setReturnPath,
    isLandingPage: isLandingPage,
    getCacheState: getCacheState,
    patchCacheState: patchCacheState,
  };

  // Backward-compat globals — used by mobile auth-modal.js and the legacy
  // header avatar dropdown handler. Keep them pointing at the core impls.
  window.getAuthToken = function () {
    return _currentSession ? _currentSession.access_token : null;
  };
  window.signOut = signOut;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
