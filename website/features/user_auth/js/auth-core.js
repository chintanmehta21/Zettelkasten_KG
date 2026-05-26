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

  // Client-side idle + absolute session timeout — closes the "forever session"
  // gap that Supabase Auth has when running on the free tier (idle/inactivity
  // timeouts are Pro-only). 7d idle aligns with Notion / Figma defaults; 30d
  // absolute matches Linear's documented session policy. Pure client-side: no
  // server calls, no DB writes — just a localStorage timestamp + a forced
  // signOut() when exceeded. See research synthesis 2026-05-26 R1.
  var IDLE_MS = 7 * 24 * 60 * 60 * 1000;
  var ABSOLUTE_MS = 30 * 24 * 60 * 60 * 1000;
  var ACTIVITY_THROTTLE_MS = 60 * 1000;
  var ACTIVITY_KEY = 'zk-auth-last-activity';
  var _lastActivityWrite = 0;

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
    // flowType: 'pkce' MUST be explicit. @supabase/auth-js default is
    // 'implicit' (verified in DEFAULT_OPTIONS, GoTrueClient.ts) — without
    // this override, signInWithOAuth never writes the code_verifier to
    // localStorage, and the /auth/callback page (which IS pkce) fails the
    // exchange with the generic "No session established" toast. The
    // server-side user row is still created (Google OAuth handoff is
    // independent of PKCE), masking the bug as a UI-only failure. See
    // test_auth_core_flow_type.py and the Vedant incident on 2026-05-26.
    return supabase.createClient(config.supabase_url, config.supabase_anon_key, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        flowType: 'pkce',
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
    // On RESTORE / INITIAL_SESSION, validate the restored session against
    // idle + absolute timeouts BEFORE propagating to subscribers. If the
    // session exceeded our policy, sign out cleanly so subscribers see
    // SIGNED_OUT (the existing zk_fetch.js banner takes over).
    if ((eventName === 'RESTORE' || eventName === 'INITIAL_SESSION') && session) {
      var timeoutReason = checkSessionTimeout(session);
      if (timeoutReason) {
        console.warn('[auth-core] Restored session timed out (' + timeoutReason + '), forcing sign-out');
        _currentSession = null;
        signOut();
        return;
      }
    }
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
        // so they can hide their sign-in chrome cleanly. Both ready signals
        // resolve immediately so callers awaiting either don't hang.
        emit('SIGNED_OUT', null);
        if (window.ZKAuth) {
          if (typeof window.ZKAuth.__signalReady === 'function') window.ZKAuth.__signalReady();
          if (typeof window.ZKAuth.__signalSessionReady === 'function') window.ZKAuth.__signalSessionReady();
        }
        return;
      }

      _supabaseClient = createSupabaseClient(config);

      // Subscribe ourselves to Supabase first so RESTORE/TOKEN_REFRESHED
      // events fan out to consumers as soon as they happen.
      _supabaseClient.auth.onAuthStateChange(function (event, session) {
        handleCoreSession(event, session);
      });

      // Signal `ready` BEFORE awaiting getSession so peers (pricing.js,
      // mobile auth-modal) can grab the SDK during the network round-trip
      // — they'll receive the initial RESTORE event via the subscription.
      // `sessionReady` is the LATE signal — resolved after the RESTORE has
      // populated _currentSession (so window.getAuthToken() returns the
      // real token, not the brief null window).
      if (window.ZKAuth && typeof window.ZKAuth.__signalReady === 'function') {
        window.ZKAuth.__signalReady();
      }

      var result = await _supabaseClient.auth.getSession();
      handleCoreSession('RESTORE', result.data.session);

      // sessionReady resolves AFTER _currentSession is populated so
      // downstream callers (zk_fetch.js) can await it before reading
      // window.getAuthToken(). Kills the page-load → form-submit race that
      // produced the Prajeet stranding 2026-05-26 03:41 UTC (Race 1/2/4).
      if (window.ZKAuth && typeof window.ZKAuth.__signalSessionReady === 'function') {
        window.ZKAuth.__signalSessionReady();
      }

      // Gap-3 reconciliation: browserCache says "previously signed in" but
      // no Supabase session restored — most likely cause is localStorage
      // 'zk-auth-token' cleared (profile sync, Safari ITP, manual clear)
      // while hasLoggedIn survived. Emit a structured event so observability
      // and future UI listeners can react. Phase-1 = event-only, no banner.
      try {
        var cache = getCacheState();
        if (cache && cache.hasLoggedIn && !_currentSession) {
          console.warn('[auth-core] auth-cache mismatch: hasLoggedIn=true but no Supabase session restored');
          window.dispatchEvent(new CustomEvent('zk:auth-cache-mismatch', {
            detail: { hasLoggedIn: true, hasSession: false, at: Date.now() }
          }));
        }
      } catch (mismatch_err) {
        // CustomEvent ctor unavailable on very old browsers; non-fatal.
        console.debug('[auth-core] cache-mismatch dispatch failed:', mismatch_err);
      }
    } catch (err) {
      console.error('[auth-core] Init failed:', err);
      // Even on init failure, resolve sessionReady (to anon) so awaiters
      // proceed rather than hang forever. The 5s timeout in the Public API
      // section below is the secondary safety net.
      if (window.ZKAuth && typeof window.ZKAuth.__signalSessionReady === 'function') {
        window.ZKAuth.__signalSessionReady();
      }
    }
  }

  async function signOut() {
    if (!_supabaseClient) return;
    await _supabaseClient.auth.signOut();
    _currentSession = null;
    patchCacheState({ hasLoggedIn: false, allowCredentialStorage: false });
    try { localStorage.removeItem(ACTIVITY_KEY); } catch (_) {}
    emit('SIGNED_OUT', null);
  }

  // Record activity timestamp in localStorage so multi-tab activity counts
  // (a click in tab A keeps tab B alive). Throttled to one write/minute so
  // mass click/keydown events don't hammer storage.
  function recordActivity() {
    var now = Date.now();
    if (now - _lastActivityWrite < ACTIVITY_THROTTLE_MS) return;
    _lastActivityWrite = now;
    try { localStorage.setItem(ACTIVITY_KEY, String(now)); } catch (_) {}
  }

  // Returns null OR a reason string ('idle' | 'absolute') if the session
  // should be force-signed-out. First-run users (no baseline) get the
  // baseline set NOW so they aren't instantly logged out by the new gate.
  function checkSessionTimeout(session) {
    if (!session || !session.user) return null;
    var now = Date.now();
    var lastActivityRaw;
    try { lastActivityRaw = localStorage.getItem(ACTIVITY_KEY); } catch (_) { return null; }
    if (!lastActivityRaw) {
      try { localStorage.setItem(ACTIVITY_KEY, String(now)); } catch (_) {}
      return null;
    }
    var lastActivity = parseInt(lastActivityRaw, 10);
    if (lastActivity && now - lastActivity > IDLE_MS) return 'idle';
    var signedInAtRaw = session.user.last_sign_in_at;
    if (signedInAtRaw) {
      var signedInAt = new Date(signedInAtRaw).getTime();
      if (signedInAt && now - signedInAt > ABSOLUTE_MS) return 'absolute';
    }
    return null;
  }

  function maybeTimeout() {
    var reason = checkSessionTimeout(_currentSession);
    if (reason) {
      console.warn('[auth-core] Session timed out (' + reason + '), signing out');
      signOut();
    }
  }

  // ---- Public API ----

  var _readyResolve;
  var _sessionReadyResolve;
  window.ZKAuth = window.ZKAuth || {};
  // `ready` (existing API): resolves after createSupabaseClient — peer
  // scripts (pricing.js, mobile auth-modal.js, auth.js dropdown wiring)
  // grab the supabase SDK synchronously here without waiting for the
  // getSession() RTT. DO NOT add late-resolution semantics — that's what
  // sessionReady is for.
  window.ZKAuth.ready = new Promise(function (resolve) { _readyResolve = resolve; });
  // `sessionReady` (post-Prajeet 2026-05-26): resolves AFTER the initial
  // RESTORE event populates _currentSession. Form-submission paths that
  // read window.getAuthToken() MUST await this; otherwise a click in the
  // 100–800ms restoration window yields null and the request silently
  // drops to anonymous (the Prajeet 03:41 UTC stranding). 5s timeout below
  // is the safety net for /api/auth/config / supabase CDN outage so
  // submissions degrade to anon rather than hang the user.
  window.ZKAuth.sessionReady = new Promise(function (resolve) {
    _sessionReadyResolve = resolve;
    setTimeout(function () {
      if (_sessionReadyResolve) {
        console.warn('[auth-core] sessionReady timed out after 5s; falling through to anonymous');
        var r = _sessionReadyResolve; _sessionReadyResolve = null;
        r(null);
      }
    }, 5000);
  });
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
  window.ZKAuth.__signalSessionReady = function () {
    if (_sessionReadyResolve) {
      var r = _sessionReadyResolve; _sessionReadyResolve = null;
      r(_currentSession);
    }
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

  // Activity listeners feed the idle-timeout baseline. Passive to avoid
  // scroll-jank; throttled inside recordActivity() to one localStorage write
  // per minute. visibilitychange + focus also run a timeout check so a tab
  // returning from background instantly detects expired sessions.
  ['click', 'keydown', 'pointerdown'].forEach(function (evt) {
    document.addEventListener(evt, recordActivity, { passive: true, capture: true });
  });
  window.addEventListener('focus', function () { recordActivity(); maybeTimeout(); });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) { recordActivity(); maybeTimeout(); }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
