/* zk_avatar.js — single source of truth for the current user's avatar URL.
 *
 * R6 (2026-05-30): before this module there were FOUR independent avatar paint
 * paths (header.js, user_profile hero, user_auth/auth.js landing, mobile
 * auth-modal pill), each with its own URL normalization and its own (or no)
 * refresh. Picking a new avatar on /profile updated only 2 of the 4 surfaces.
 *
 * ZKAvatar centralizes:
 *   - the curated-URL validator (closes the non-curated user_metadata leak the
 *     mobile pill had — only /artifacts/avatars/avatar_NN.svg is ever accepted)
 *   - the current value + a per-profile localStorage write-through cache
 *   - a tiny EventTarget pub-sub so every surface re-renders on change
 *
 * Cross-tab sync (BroadcastChannel) layers on top of this in R3; this module
 * stays transport-agnostic and only emits the local 'change' event.
 *
 * Load order: this file must load BEFORE header.js / auth.js / page scripts.
 * It is dependency-free and safe to load on every page (anon included).
 */
(function () {
  'use strict';

  var CURATED_RE = /^\/artifacts\/avatars\/avatar_(0[0-9]|[1-5][0-9])\.svg$/;
  var DEFAULT_AVATAR = '/artifacts/avatars/avatar_00.svg';
  var CACHE_KEY_PREFIX = 'zk-avatar-url-';

  var bus = new EventTarget();
  var _state = { profileId: null, url: null };

  // R3 (2026-05-30): cross-tab sync. BroadcastChannel is the modern primitive
  // (Baseline since 2022); the localStorage `storage`-event ping is the
  // fallback for iOS Safari < 15.4 / private windows. A received message
  // applies LOCALLY only (never re-broadcast) so two tabs can't ping-pong.
  var BC_NAME = 'zk-user';
  var STORAGE_PING_KEY = 'zk-avatar-bcast';
  var _channel = null;
  try {
    if (typeof BroadcastChannel !== 'undefined') _channel = new BroadcastChannel(BC_NAME);
  } catch (_) { _channel = null; }

  /** Only curated preset URLs are ever accepted — anything else (external
   *  Google/Gravatar URLs, data: URIs, attacker-supplied metadata) is rejected
   *  and the caller gets null so it can fall back to the curated default. */
  function isCurated(url) {
    return typeof url === 'string' && CURATED_RE.test(url);
  }

  function cacheKey(profileId) {
    return CACHE_KEY_PREFIX + (profileId || 'anon');
  }

  function readCached(profileId) {
    try {
      var v = localStorage.getItem(cacheKey(profileId));
      return isCurated(v) ? v : null;
    } catch (_) { return null; }
  }

  function writeCached(profileId, url) {
    try { localStorage.setItem(cacheKey(profileId), url); } catch (_) {}
  }

  /** Resolve the best-known URL for a profile WITHOUT mutating state:
   *  curated input > cache > curated default. Used for first paint. */
  function resolve(profileId, candidateUrl) {
    if (isCurated(candidateUrl)) return candidateUrl;
    var cached = readCached(profileId);
    if (cached) return cached;
    return DEFAULT_AVATAR;
  }

  /** Push a change to other tabs. BroadcastChannel first; storage-ping fallback. */
  function broadcast(detail) {
    if (_channel) {
      try { _channel.postMessage({ type: 'avatar', detail: detail }); return; } catch (_) {}
    }
    // Fallback: a versioned write fires the `storage` event in OTHER tabs only
    // (never the writer), which is exactly the cross-tab signal we want.
    try {
      localStorage.setItem(STORAGE_PING_KEY, JSON.stringify({
        detail: detail, n: (broadcast._n = (broadcast._n || 0) + 1)
      }));
    } catch (_) {}
  }

  /** Apply a change received from another tab — LOCAL state + subscribers only,
   *  never re-broadcast (prevents an infinite tab-to-tab ping-pong). */
  function applyRemote(detail) {
    if (!detail || !isCurated(detail.url)) return;
    if (detail.url === _state.url && (detail.profileId || null) === _state.profileId) return;
    _state.profileId = detail.profileId || null;
    _state.url = detail.url;
    if (_state.profileId) writeCached(_state.profileId, _state.url);
    bus.dispatchEvent(new CustomEvent('change', {
      detail: { profileId: _state.profileId, url: _state.url }
    }));
  }

  if (_channel) {
    _channel.onmessage = function (e) {
      if (e && e.data && e.data.type === 'avatar') applyRemote(e.data.detail);
    };
  }
  try {
    window.addEventListener('storage', function (e) {
      if (e.key !== STORAGE_PING_KEY || !e.newValue) return;
      try { applyRemote(JSON.parse(e.newValue).detail); } catch (_) {}
    });
  } catch (_) {}

  window.ZKAvatar = {
    CURATED_RE: CURATED_RE,
    DEFAULT_AVATAR: DEFAULT_AVATAR,
    isCurated: isCurated,
    resolve: resolve,

    /** Current resolved URL (curated default if nothing set yet). */
    current: function () {
      return _state.url || DEFAULT_AVATAR;
    },

    currentProfileId: function () { return _state.profileId; },

    /** Seed/replace the source of truth and notify subscribers.
     *  @param {string|null} profileId
     *  @param {string} url - curated; non-curated is coerced to default
     *  @param {{silent?: boolean}} [opts] - silent skips the change event
     *  @returns {string} the accepted (curated) url
     */
    set: function (profileId, url, opts) {
      opts = opts || {};
      var accepted = isCurated(url) ? url : resolve(profileId, url);
      var changed = accepted !== _state.url || profileId !== _state.profileId;
      _state.profileId = profileId || null;
      _state.url = accepted;
      if (profileId && isCurated(accepted)) writeCached(profileId, accepted);
      if (changed && !opts.silent) {
        var detail = { profileId: _state.profileId, url: accepted };
        bus.dispatchEvent(new CustomEvent('change', { detail: detail }));
        // R3: tell other tabs (unless this set IS a remote-apply, which uses
        // applyRemote directly and never reaches here).
        broadcast(detail);
      }
      return accepted;
    },

    /** Subscribe to avatar changes. Returns an unsubscribe function.
     *  Fires immediately with the current value unless {immediate:false}. */
    subscribe: function (handler, opts) {
      opts = opts || {};
      if (typeof handler !== 'function') return function () {};
      var wrapped = function (e) { handler(e.detail); };
      bus.addEventListener('change', wrapped);
      if (opts.immediate !== false && _state.url) {
        try { handler({ profileId: _state.profileId, url: _state.url }); } catch (_) {}
      }
      return function () { bus.removeEventListener('change', wrapped); };
    }
  };
})();
