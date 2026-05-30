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

  // Phase 1.5 Item 3: read the server-set zk-session-marker cookie. Survives
  // localStorage clears (Safari ITP 7-day cap, profile sync, manual "clear
  // site data"); when present + no Supabase session restored on boot → user
  // WAS signed in but their localStorage is gone → trigger the re-auth banner.
  // Non-secret value ("1") so JS-readable (.httponly=false on the server).
  function readMarkerCookie() {
    try {
      var parts = (document.cookie || '').split(';');
      for (var i = 0; i < parts.length; i += 1) {
        var kv = parts[i].split('=');
        if (kv[0].trim() === 'zk-session-marker') return true;
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  function clearMarkerCookie() {
    try {
      document.cookie = 'zk-session-marker=; Max-Age=0; Path=/; SameSite=Lax; Secure';
    } catch (_) {
      // document.cookie may throw in sandboxed iframes — non-fatal.
    }
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

    if (eventName === 'SIGNED_IN') {
      // Item 6: claim any anonymous (Zoro) zettels created in THIS browser
      // session into the just-signed-in user's workspace. Only on a real
      // SIGNED_IN (never RESTORE/INITIAL_SESSION/TOKEN_REFRESHED). Idempotent
      // server-side (first-claim-wins); fire-and-forget + keepalive so it
      // survives the landing redirect below.
      claimAnonSession(session);
    }

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

  // Item 6 — anon→user zettel claim. POSTs the claim endpoint once per tab on
  // sign-in; the HttpOnly zk_anon_sid cookie (sent via credentials:'include')
  // identifies the anon browser-session server-side. Best-effort; broadcasts to
  // sibling tabs so an open /m/zettels can refresh.
  function claimAnonSession(session) {
    try {
      if (sessionStorage.getItem('zk-anon-claimed') === '1') return;
      sessionStorage.setItem('zk-anon-claimed', '1');
    } catch (e) { void e; }
    var token = session && session.access_token;
    if (!token) return;
    try {
      fetch('/api/zettels/claim-anon-session', {
        method: 'POST',
        credentials: 'include',
        keepalive: true,
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: '{}',
      })
        .then(function (r) { return r && r.ok ? r.json() : null; })
        .then(function (data) {
          if (data && data.claimed > 0 && typeof BroadcastChannel === 'function') {
            try { new BroadcastChannel('zk-auth').postMessage({ type: 'anon-claimed', claimed: data.claimed }); } catch (e) { void e; }
          }
        })
        .catch(function () { /* best-effort */ });
    } catch (e) { void e; }
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

      // Reconciliation (Gap-3 + Phase 1.5 Item 3): the user WAS signed in
      // before — per browserCache.hasLoggedIn OR per the server-set
      // zk-session-marker cookie — but no Supabase session was restored
      // this load. Two layers because they fail differently:
      //   - browserCache: lives in the same localStorage that may have been
      //     wiped alongside zk-auth-token (profile sync, "clear site data")
      //   - marker cookie: server-issued, separate storage; survives most
      //     localStorage wipes including Safari ITP's 7-day script-storage
      //     cap (per WebKit Tracking Prevention policy, still active 2025).
      // If EITHER signal says "was signed in" → trigger re-auth banner so
      // the user doesn't silently submit anonymously.
      try {
        var cache = getCacheState();
        var hadCacheFlag = !!(cache && cache.hasLoggedIn);
        var hadMarker = readMarkerCookie();
        if ((hadCacheFlag || hadMarker) && !_currentSession) {
          console.warn(
            '[auth-core] auth-cache mismatch: previously signed in '
            + '(cache=' + hadCacheFlag + ', marker=' + hadMarker + ') '
            + 'but no Supabase session restored'
          );
          window.dispatchEvent(new CustomEvent('zk:auth-cache-mismatch', {
            detail: {
              hasLoggedIn: hadCacheFlag,
              markerCookie: hadMarker,
              hasSession: false,
              at: Date.now(),
            },
          }));
          // ZKAuthUI is exposed by zk_fetch.js — defensive check before
          // calling so a script-order edge case (auth-core loaded first)
          // degrades to event-only rather than throwing.
          if (window.ZKAuthUI && typeof window.ZKAuthUI.showReauthBanner === 'function') {
            window.ZKAuthUI.showReauthBanner('expired');
          }
        }
      } catch (mismatch_err) {
        // CustomEvent ctor unavailable on very old browsers; non-fatal.
        console.debug('[auth-core] cache-mismatch dispatch failed:', mismatch_err);
      }

      // Phase-1.5 Item 2 (post-Prajeet 2026-05-26): one-shot /api/me probe
      // at boot when we have an access_token in hand. Verifies the server
      // still recognizes the token (catches "JWT valid client-side but
      // expired/revoked server-side" silent failures). Uses zkFetch so the
      // existing X-Auth-Status response → banner pipeline handles 401 →
      // single-flight refresh → re-auth banner. Fire-and-forget; never
      // blocks page render. Falls back to plain fetch + manual banner
      // only when zk_fetch.js hasn't loaded yet (script-order edge case).
      //
      // Tab-scoped idempotency (post-2026-05-27): sessionStorage flag so a
      // landing → /home full-page redirect (window.location.replace) doesn't
      // double-fire — init() runs once per HTTP document, sessionStorage
      // persists across same-tab navigations. Private-mode / cookie-block →
      // sessionStorage throws → fall through to fire-anyway (no regression).
      try {
        var bootCache = getCacheState();
        var bootSession = _currentSession;
        if (bootCache && bootCache.hasLoggedIn && bootSession && bootSession.access_token) {
          var alreadyFired = false;
          try { alreadyFired = sessionStorage.getItem('zk:boot-probe-fired') === '1'; }
          catch (_storage_read_err) { /* private mode — fire anyway */ }
          if (!alreadyFired) {
            try { sessionStorage.setItem('zk:boot-probe-fired', '1'); }
            catch (_storage_write_err) { /* private mode — fire without idempotency */ }
            var bootProbeOpts = {
              headers: { 'Authorization': 'Bearer ' + bootSession.access_token },
            };
            if (typeof window.zkFetch === 'function') {
              window.zkFetch('/api/me', bootProbeOpts).catch(function () { /* best-effort */ });
            } else {
              // zk_fetch.js not yet loaded — degrade to plain fetch + direct
              // banner trigger so observability still works in this edge.
              window.fetch('/api/me', bootProbeOpts).then(function (res) {
                if (res && res.status === 401 && window.ZKAuthUI &&
                    typeof window.ZKAuthUI.showReauthBanner === 'function') {
                  window.ZKAuthUI.showReauthBanner('expired');
                }
              }).catch(function () { /* best-effort */ });
            }
          }
        }
      } catch (probe_err) {
        console.debug('[auth-core] /api/me boot-probe failed:', probe_err);
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
    // Phase 1.5 Item 3: clear the marker cookie so the next page load
    // doesn't show a phantom "re-auth needed" banner for a user who
    // explicitly signed out. The 30-day cookie would otherwise outlive
    // the localStorage wipe and trigger the reconciliation false-positive.
    clearMarkerCookie();
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
