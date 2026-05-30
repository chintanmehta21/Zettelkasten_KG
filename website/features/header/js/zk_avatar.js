/* zk_avatar.js — single source of truth for the current user's avatar URL.
 *
 * R6/R3 (2026-05-30): before this, desktop surfaces (small header avatar, profile
 * hero, landing #user-avatar) each painted the avatar independently, so picking a
 * new one updated only some of them. ZKAvatar centralizes:
 *   - the curated-URL validator (only /artifacts/avatars/avatar_NN.svg, 0-119 —
 *     mirrors website/app.py::_CURATED_AVATAR_RE; non-curated values are rejected)
 *   - the current value + a per-profile localStorage write-through cache
 *   - a tiny EventTarget pub-sub so every desktop surface re-renders on change
 *   - cross-tab sync via BroadcastChannel('zk-user') (+ storage-event fallback)
 *   - a BRIDGE to the existing `zk:avatar-changed` CustomEvent so it unifies with
 *     the mobile surfaces (mobile/js/avatar.js + auth-modal.js) instead of
 *     competing with them.
 *
 * Dependency-free; must load BEFORE header.js / auth.js / page scripts.
 */
(function () {
  'use strict';

  // 0-119, matching website/app.py::_CURATED_AVATAR_RE and mobile/js/avatar.js.
  var CURATED_RE = /^\/artifacts\/avatars\/avatar_(0\d|[1-9]\d|1[01]\d)\.svg$/;
  var DEFAULT_AVATAR = '/artifacts/avatars/avatar_00.svg';
  var CACHE_KEY_PREFIX = 'zk-avatar-url-';
  var BRIDGE_EVENT = 'zk:avatar-changed';

  var bus = new EventTarget();
  var _state = { profileId: null, url: null };

  var BC_NAME = 'zk-user';
  var STORAGE_PING_KEY = 'zk-avatar-bcast';
  var _channel = null;
  try {
    if (typeof BroadcastChannel !== 'undefined') _channel = new BroadcastChannel(BC_NAME);
  } catch (_) { _channel = null; }

  function isCurated(url) {
    return typeof url === 'string' && CURATED_RE.test(url);
  }

  function cacheKey(profileId) { return CACHE_KEY_PREFIX + (profileId || 'anon'); }

  function readCached(profileId) {
    try {
      var v = localStorage.getItem(cacheKey(profileId));
      return isCurated(v) ? v : null;
    } catch (_) { return null; }
  }
  function writeCached(profileId, url) {
    try { localStorage.setItem(cacheKey(profileId), url); } catch (_) {}
  }

  /** Resolve the best-known curated URL WITHOUT mutating state:
   *  curated input > cache > curated default. */
  function resolve(profileId, candidateUrl) {
    if (isCurated(candidateUrl)) return candidateUrl;
    var cached = readCached(profileId);
    return cached || DEFAULT_AVATAR;
  }

  function broadcast(detail) {
    if (_channel) {
      try { _channel.postMessage({ type: 'avatar', detail: detail }); return; } catch (_) {}
    }
    try {
      localStorage.setItem(STORAGE_PING_KEY, JSON.stringify({
        detail: detail, n: (broadcast._n = (broadcast._n || 0) + 1)
      }));
    } catch (_) {}
  }

  /** Apply a change received from ANOTHER tab/surface — local state + local
   *  subscribers only. Never re-broadcasts / re-dispatches (prevents loops). */
  function applyRemote(detail) {
    if (!detail || !isCurated(detail.url)) return;
    if (detail.url === _state.url && (detail.profileId || null) === _state.profileId) return;
    _state.profileId = detail.profileId || null;
    _state.url = detail.url;
    if (_state.profileId) writeCached(_state.profileId, _state.url);
    bus.dispatchEvent(new CustomEvent('change', { detail: { profileId: _state.profileId, url: _state.url } }));
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
    // Bridge: a mobile-surface (or any) zk:avatar-changed updates ZKAvatar too.
    document.addEventListener(BRIDGE_EVENT, function (e) {
      var d = e && e.detail;
      if (d && isCurated(d.url)) applyRemote(d);
    });
  } catch (_) {}

  window.ZKAvatar = {
    CURATED_RE: CURATED_RE,
    DEFAULT_AVATAR: DEFAULT_AVATAR,
    isCurated: isCurated,
    resolve: resolve,
    current: function () { return _state.url || DEFAULT_AVATAR; },
    currentProfileId: function () { return _state.profileId; },

    /** Seed/replace the SoT and notify subscribers + other tabs/surfaces.
     *  @returns {string} the accepted (curated) url */
    set: function (profileId, url, opts) {
      opts = opts || {};
      var accepted = isCurated(url) ? url : resolve(profileId, url);
      var changed = accepted !== _state.url || (profileId || null) !== _state.profileId;
      _state.profileId = profileId || null;
      _state.url = accepted;
      if (profileId && isCurated(accepted)) writeCached(profileId, accepted);
      if (changed && !opts.silent) {
        var detail = { profileId: _state.profileId, url: accepted };
        bus.dispatchEvent(new CustomEvent('change', { detail: detail }));
        broadcast(detail);
        // Bridge out to mobile-style listeners on this page.
        try { document.dispatchEvent(new CustomEvent(BRIDGE_EVENT, { detail: detail })); } catch (_) {}
      }
      return accepted;
    },

    /** Subscribe to avatar changes. Returns an unsubscribe fn. Fires immediately
     *  with the current value unless {immediate:false}. */
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
