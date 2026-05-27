/* website/static/js/zk_stats_cache.js
 *
 * Per-browser persistent cache for the User Stats payload.
 * Single global key (zk_stats_v1::current) — Zettelkasten is one
 * workspace-per-profile today. On read, validates meta.profile_id
 * matches the current session JWT subject (if available) and clears
 * on mismatch.
 *
 * Promise-returning API even though localStorage is sync, so we can
 * swap to IndexedDB later without touching callers.
 */
(function () {
  'use strict';
  if (window.ZKStatsCache) return;

  var KEY = 'zk_stats_v1::current';

  function currentProfileSub() {
    // Try common bootstrap globals; fall back to null (no validation).
    try {
      if (window.ZK_PROFILE && window.ZK_PROFILE.id) return String(window.ZK_PROFILE.id);
      if (window.ZK_PROFILE && window.ZK_PROFILE.profile_id) return String(window.ZK_PROFILE.profile_id);
    } catch (_) {}
    return null;
  }

  function read() {
    return new Promise(function (resolve) {
      var raw;
      try { raw = localStorage.getItem(KEY); } catch (_) { return resolve(null); }
      if (!raw) return resolve(null);
      try {
        var parsed = JSON.parse(raw);
        if (!parsed || !parsed.payload) return resolve(null);
        // Profile-id validation: only enforce if we can read the session id.
        var currentSub = currentProfileSub();
        var storedSub = parsed.payload && parsed.payload.meta && parsed.payload.meta.profile_id;
        if (currentSub && storedSub && String(storedSub) !== String(currentSub)) {
          try { localStorage.removeItem(KEY); } catch (_) {}
          return resolve(null);
        }
        resolve({ etag: parsed.etag || '', payload: parsed.payload, stored_at: parsed.stored_at || 0 });
      } catch (_) {
        resolve(null);
      }
    });
  }

  function write(etag, payload) {
    return new Promise(function (resolve) {
      var entry = { etag: etag, payload: payload, stored_at: Date.now() };
      var serialized;
      try { serialized = JSON.stringify(entry); } catch (_) { return resolve(); }
      try {
        localStorage.setItem(KEY, serialized);
      } catch (_) {
        // Quota or other error — drop and retry once.
        try { localStorage.removeItem(KEY); } catch (_) {}
        try { localStorage.setItem(KEY, serialized); } catch (_) {}
      }
      resolve();
    });
  }

  function clear() {
    return new Promise(function (resolve) {
      try { localStorage.removeItem(KEY); } catch (_) {}
      resolve();
    });
  }

  window.ZKStatsCache = { read: read, write: write, clear: clear };
})();
