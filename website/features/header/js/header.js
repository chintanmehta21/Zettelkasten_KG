/* Shared header behavior — single source of truth for back button, avatar dropdown,
 * AND avatar image loading. Pages include the rendered header markup via the
 * <!--ZK_HEADER--> server-side placeholder, then call ZKHeader.boot(getToken).
 *
 * Robustness guarantees (defense in depth):
 *   1. If this script never runs, CSS keeps the fallback (user glyph) visible — never a broken <img>.
 *   2. If /api/me fails, we fall back to localStorage, then to a random avatar, then to initial.
 *   3. Avatar URL is PRE-LOADED with new Image() before being committed to the visible <img>.
 *      A failed preload never touches the DOM — broken images can never render.
 *   4. On preload failure, we retry once with a cache-bust query string, then commit initial-letter fallback.
 *   5. All page-local avatar logic has been removed; home-picker uses ZKHeader.setAvatarById(id) to update.
 */
(function () {
  'use strict';

  var zkFetch = window.zkFetch || window.fetch;  // signup-failure-fixes-1a: fall back if wrapper not loaded

  var AVATAR_COUNT = 120;
  var AVATAR_PATH_RE = /\/artifacts\/avatars\/avatar_\d+\.svg/;
  var CACHE_KEY_PREFIX = 'zk-avatar-url-';

  // ── DOM refs (resolved in init) ───────────────────────────────────
  var refs = {};

  function resolveRefs() {
    // PR2: dropped the `home-*` ID fallbacks. /home now uses the shared
    // header markup (avatar-* IDs) like every other shared-header page.
    refs.backBtn      = document.querySelector('[data-zk-back]');
    refs.avatarBtn    = document.getElementById('avatar-btn');
    refs.avatarImg    = document.getElementById('avatar-img');
    refs.avatarFb     = document.getElementById('avatar-fallback');
    refs.avatarDrop   = document.getElementById('avatar-dropdown');
    refs.avatarWrap   = document.getElementById('avatar-wrap');
  }

  function avatarUrlFor(id) {
    var safeId = Math.max(0, Math.min(AVATAR_COUNT - 1, parseInt(id, 10) || 0));
    return '/artifacts/avatars/avatar_' + String(safeId).padStart(2, '0') + '.svg';
  }

  function idFromUrl(url) {
    if (!url) return null;
    var m = String(url).match(/avatar_(\d+)\.svg/);
    return m ? parseInt(m[1], 10) : null;
  }

  function cacheKey(profileId) {
    return CACHE_KEY_PREFIX + (profileId || 'anon');
  }

  function readCached(profileId) {
    try {
      var v = localStorage.getItem(cacheKey(profileId));
      return (v && AVATAR_PATH_RE.test(v)) ? v : null;
    } catch (_) { return null; }
  }

  function writeCached(profileId, url) {
    try { localStorage.setItem(cacheKey(profileId), url); } catch (_) {}
  }

  /** Preload a URL through new Image(); only resolve once the browser confirms it's valid. */
  function preload(url, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      var done = false;
      var timer = setTimeout(function () {
        if (done) return;
        done = true;
        reject(new Error('preload-timeout'));
      }, timeoutMs || 5000);
      img.onload = function () {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve(url);
      };
      img.onerror = function () {
        if (done) return;
        done = true;
        clearTimeout(timer);
        reject(new Error('preload-error'));
      };
      img.src = url;
    });
  }

  /** Render a proven-good URL into the <img>. */
  function commitImage(url) {
    if (!refs.avatarImg) return;
    refs.avatarImg.onload = null;
    refs.avatarImg.onerror = null;
    refs.avatarImg.removeAttribute('hidden');
    refs.avatarImg.src = url;
    refs.avatarImg.classList.add('loaded');
    refs.avatarImg.classList.remove('hidden');
    if (refs.avatarFb) refs.avatarFb.classList.add('hidden');
  }

  /** Seed the shared ZKAvatar SoT without re-broadcasting (the header already
   *  painted itself). Other surfaces read ZKAvatar.current() / subscribe. R6. */
  function seedZKAvatar(profileId, url) {
    if (window.ZKAvatar && window.ZKAvatar.isCurated(url)) {
      window.ZKAvatar.set(profileId || null, url, { silent: true });
    }
  }

  /** Terminal fallback: show user initial (or generic glyph if no name). */
  function commitInitial(profile) {
    if (!refs.avatarFb) return;
    var seed = (profile && (profile.name || profile.email || profile.display_name)) || '';
    var initial = seed ? seed.trim().charAt(0).toUpperCase() : '';
    if (initial) {
      refs.avatarFb.textContent = initial;
    }
    // Keep the generic glyph if we have no initial — do nothing, SVG stays.
    if (refs.avatarImg) {
      refs.avatarImg.classList.remove('loaded');
      refs.avatarImg.setAttribute('hidden', '');
    }
    refs.avatarFb.classList.remove('hidden');
  }

  /** Pick the URL we'll attempt: server > localStorage > random (display-only).
   *  R6 (2026-05-30): for AUTHED users we no longer client-side-assign a random
   *  avatar and PUT it back — /api/me (R5) always returns a curated avatar_url
   *  (the DB default-avatar trigger guarantees one), so that fire-and-forget
   *  self-write was dead and raced the user's real pick. Authed users with no
   *  server/cache URL fall to a random preset for DISPLAY only (no PUT); anon
   *  visitors keep the per-load random preset. */
  function resolveAvatarUrl(profile) {
    var profileId = (profile && profile.id) || null;
    var serverUrl = profile && profile.avatar_url;
    if (serverUrl && AVATAR_PATH_RE.test(serverUrl)) {
      if (profileId) writeCached(profileId, serverUrl);
      return { url: serverUrl, source: 'server' };
    }
    if (profileId) {
      var cached = readCached(profileId);
      if (cached) return { url: cached, source: 'cache' };
    }
    // Display-only random preset (no server write). Authed users effectively
    // never reach here post-R5 since /api/me always returns a curated URL.
    var randomId = Math.floor(Math.random() * AVATAR_COUNT);
    var url = avatarUrlFor(randomId);
    if (profileId) writeCached(profileId, url);
    return { url: url, source: 'random', id: randomId };
  }

  /** Main avatar lifecycle: try URL → preload → commit. On failure, retry cache-busted; else initial. */
  async function loadAvatar(profile, getToken) {
    if (!refs.avatarImg) return;
    try {
      var picked = resolveAvatarUrl(profile || {});
      var pid = (profile && profile.id) || null;
      try {
        await preload(picked.url);
        commitImage(picked.url);
        seedZKAvatar(pid, picked.url);
        return;
      } catch (err) {
        // Retry once with cache-bust (handles stale 304/CORS edge cases)
        try {
          var bustUrl = picked.url + '?v=' + Date.now();
          await preload(bustUrl);
          commitImage(picked.url); // commit the clean URL now that we've proven it's reachable
          seedZKAvatar(pid, picked.url);
          return;
        } catch (err2) {
          console.warn('[ZKHeader] avatar preload failed twice for', picked.url, err2 && err2.message);
          // If we were trying a cached/server URL, try one more time with a fresh random
          if (picked.source !== 'random') {
            try {
              var rid = Math.floor(Math.random() * AVATAR_COUNT);
              var rurl = avatarUrlFor(rid);
              await preload(rurl);
              writeCached(pid, rurl);
              commitImage(rurl);
              seedZKAvatar(pid, rurl);
              return;
            } catch (_) { /* fall through */ }
          }
        }
      }
    } catch (err) {
      console.warn('[ZKHeader] avatar resolution failed', err && err.message);
    }
    // Terminal fallback
    commitInitial(profile || {});
  }

  /** Fetch /api/me with a bearer token, tolerant of network / 401. */
  async function fetchProfile(token) {
    if (!token) return null;
    try {
      var resp = await zkFetch('/api/me', {
        headers: { 'Authorization': 'Bearer ' + token },
        cache: 'no-store'
      });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (_) { return null; }
  }

  function bindBackButton() {
    if (!refs.backBtn || refs.backBtn.dataset.zkBound) return;
    refs.backBtn.dataset.zkBound = '1';
    refs.backBtn.addEventListener('click', function () {
      if (window.history.length > 1) window.history.back();
      else window.location.href = '/home';
    });
  }

  /** PR2 anon flow: when /pricing is loaded by an anon visitor and
   * page-init calls boot({anonAction: 'open-login-modal'}), the avatar
   * click opens the existing #login-modal directly. The dropdown wrap
   * stays hidden via the zk-anon-no-dropdown-default class. */
  function _installAnonLoginModalClickSwap() {
    if (!refs.avatarBtn || refs.avatarBtn.dataset.zkAnonBound) return;
    refs.avatarBtn.dataset.zkAnonBound = '1';
    refs.avatarBtn.addEventListener('click', function (e) {
      // If the user signed in mid-session, ZKHeader.exitAnonMode() will have
      // removed the zk-anon-no-dropdown-default class — bail and let the
      // bubble-phase dropdown toggle handle the click.
      if (refs.avatarWrap && !refs.avatarWrap.classList.contains('zk-anon-no-dropdown-default')) {
        return;
      }
      e.stopPropagation();
      e.preventDefault();
      // Defensive: clear any stale .open on the (hidden) dropdown so a future
      // edit that drops zk-anon-no-dropdown-default doesn't flash open items.
      if (refs.avatarDrop) refs.avatarDrop.classList.remove('open');
      var modal = document.getElementById('login-modal');
      if (modal && typeof modal.classList === 'object') {
        modal.classList.add('open');
      } else {
        console.warn('[ZKHeader] anonAction=open-login-modal but #login-modal not found in DOM');
      }
    }, true);
  }

  function bindAvatarDropdown() {
    if (!refs.avatarBtn || !refs.avatarDrop || refs.avatarBtn.dataset.zkBound) return;
    refs.avatarBtn.dataset.zkBound = '1';

    // m-8: every close path MUST also reset aria-expanded — screen readers
    // otherwise announce the menu as still expanded after Escape / focus loss.
    function closeDropdown() {
      if (!refs.avatarDrop.classList.contains('open')) return;
      refs.avatarDrop.classList.remove('open');
      refs.avatarBtn.setAttribute('aria-expanded', 'false');
    }

    // WCAG 2.2 4.1.2 / WAI-ARIA 1.2 menubutton: aria-expanded mirrors .open state.
    refs.avatarBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var nowOpen = refs.avatarDrop.classList.toggle('open');
      refs.avatarBtn.setAttribute('aria-expanded', nowOpen ? 'true' : 'false');
    });
    document.addEventListener('click', function (e) {
      if (refs.avatarWrap && !refs.avatarWrap.contains(e.target)) {
        closeDropdown();
      }
    });
    // m-8: Escape key closes the dropdown from anywhere.
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeDropdown();
    });
    // m-8: focus leaving the avatar wrap closes the dropdown (focusout
    // bubbles, unlike blur). Schedule on microtask so the relatedTarget
    // check sees the post-focus state — without that delay, clicking a
    // dropdown menu item would close before the click handler fires.
    if (refs.avatarWrap) {
      refs.avatarWrap.addEventListener('focusout', function (e) {
        var next = e.relatedTarget;
        if (!next || !refs.avatarWrap.contains(next)) closeDropdown();
      });
    }
  }

  var _zkAvatarSubBound = false;
  function initBasics() {
    resolveRefs();
    bindBackButton();
    bindAvatarDropdown();
    // R6: re-render the small header avatar when ANY surface (or another tab
    // via R3 BroadcastChannel) changes the SoT. immediate:false — boot paint is
    // owned by loadAvatar; this handles later changes. commitImage is idempotent
    // and we never call set() here, so no loop.
    if (window.ZKAvatar && !_zkAvatarSubBound) {
      _zkAvatarSubBound = true;
      window.ZKAvatar.subscribe(function (detail) {
        if (detail && detail.url) commitImage(detail.url);
      }, { immediate: false });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBasics);
  } else {
    initBasics();
  }

  // ── Public API ──────────────────────────────────────────────────────
  window.ZKHeader = {
    /**
     * Boot avatar loading for the current page.
     * @param {Function|string} getToken - () => Promise<string>|string  or raw bearer string
     * @param {Object} [options]
     * @param {Object} [options.profile] - pre-fetched profile (skips /api/me call)
     * @param {'open-login-modal'|'none'} [options.anonAction] - PR2: for anon
     *   visitors with anonAction='open-login-modal', the avatar click opens
     *   #login-modal instead of toggling the dropdown.
     */
    boot: async function (getToken, options) {
      options = options || {};
      if (!refs.avatarImg) resolveRefs();
      var profile = options.profile || null;
      if (!profile && getToken) {
        try {
          var token = typeof getToken === 'function' ? await getToken() : getToken;
          profile = await fetchProfile(token);
        } catch (_) { profile = null; }
      }
      var isAnon = !profile || !profile.id;
      // PR2: anon click-swap. Wire BEFORE loadAvatar so the swap is in
      // place even if avatar load races a fast click.
      if (isAnon && options.anonAction === 'open-login-modal') {
        _installAnonLoginModalClickSwap();
      } else {
        // Authed (or no opt-in): reveal the dropdown wrap.
        if (refs.avatarWrap) refs.avatarWrap.classList.remove('zk-anon-no-dropdown-default');
      }
      await loadAvatar(profile, getToken);
      // iter-03 §UI: surface a stable signal harness/automation can read to
      // verify every authed page actually called boot() (the missing-boot bug
      // is invisible in the DOM otherwise — partial renders, img stays blank).
      try { window.ZKHeader.__booted = true; } catch (_) { /* no-op */ }
      return profile;
    },

    /**
     * Force-update the visible avatar to a specific ID (used by the profile picker).
     * Updates the small header img + localStorage cache + shared ZKAvatar SoT
     * optimistically, then AWAITS the PUT and REJECTS on failure so the caller
     * can roll back and surface an error. (R2, 2026-05-30: previously the PUT was
     * fire-and-forget with a silent `.catch(()=>{})`, so a 401/404/500 was
     * invisible — the picker toasted success while nothing persisted.)
     *
     * @param {number} avatarId
     * @param {Function|string} getToken
     * @param {string|null} profileId  - cache-key owner; null falls back to 'anon'
     * @param {{signal?: AbortSignal}} [options] - abort an in-flight PUT on rapid re-pick
     * @returns {Promise<{avatar_url: string}>} resolves on persisted save; rejects on failure
     */
    setAvatarById: async function (avatarId, getToken, profileId, options) {
      options = options || {};
      var url = avatarUrlFor(avatarId);
      // Preload first so we never commit a broken image.
      try { await preload(url); } catch (_) {
        console.warn('[ZKHeader] setAvatarById preload failed for id', avatarId);
      }
      // Commit the shared surfaces (small header img + cache + ZKAvatar SoT)
      // and return, with NO persistence, only in the token-less visual path
      // (localhost stub / anon). R2: the picker owns the optimistic hero
      // preview; the header + SoT must NOT show an unsaved avatar, so for the
      // authed path we commit ONLY after the PUT confirms (below).
      function commitShared() {
        writeCached(profileId || null, url);
        commitImage(url);
        if (window.ZKAvatar) window.ZKAvatar.set(profileId || null, url);
      }
      if (!getToken) { commitShared(); return { avatar_url: url }; }
      var token = typeof getToken === 'function' ? await getToken() : getToken;
      if (!token) { commitShared(); return { avatar_url: url }; }
      // Persist FIRST — errors propagate to the caller and NOTHING is committed,
      // so the header/SoT never display an unsaved pick on failure.
      var resp = await zkFetch('/api/me/avatar', {
        method: 'PUT',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ avatar_id: avatarId }),
        signal: options.signal
      });
      if (!resp.ok) {
        var err = new Error('avatar PUT failed: ' + resp.status);
        err.status = resp.status;
        throw err;
      }
      commitShared();
      return await resp.json().catch(function () { return { avatar_url: url }; });
    },

    /** PR2: called by a page when an anon visitor signs in mid-session
     * (e.g. /pricing after the login modal succeeds). Reveals the dropdown
     * so the avatar click flips from "open login modal" to "toggle menu".
     * The capture-phase anon click handler stays bound but no-ops when
     * the class is gone, so we don't need to remove the listener. */
    exitAnonMode: function () {
      if (refs.avatarWrap) {
        refs.avatarWrap.classList.remove('zk-anon-no-dropdown-default');
      }
    },

    /** Bind a sign-out handler. Keeps Supabase auth out of the shared header. */
    onSignOut: function (handler) {
      var btn = document.getElementById('menu-signout');
      if (!btn || typeof handler !== 'function' || btn.dataset.zkSignoutBound) return;
      btn.dataset.zkSignoutBound = '1';
      btn.addEventListener('click', function () {
        try { handler(); } catch (e) { console.error('[ZKHeader] signOut handler threw', e); }
      });
    },

    /** Expose lightweight helpers for pages that need them (e.g. home picker). */
    _internal: { avatarUrlFor: avatarUrlFor, idFromUrl: idFromUrl }
  };
})();
