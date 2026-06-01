/**
 * Zettelkasten Auth — desktop landing DOM layer.
 *
 * Loaded by pages with the desktop landing-style sign-in chrome (/  + /pricing).
 * Depends on auth-core.js, which MUST be loaded first (same <script> ordering)
 * because this file consumes window.ZKAuth for the client + session events.
 *
 * Owns:
 *   - resolveDOM (login button, avatar, modal, OAuth grid, logout)
 *   - updateUI (paints avatar + name + visibility based on session)
 *   - openModal / closeModal for the inline sign-in modal
 *   - signInWithProvider (OAuth) + signInWithEmail (password)
 *   - bindEvents for all the above
 *   - Subscribes to ZKAuth.onAuthStateChange so DOM stays in sync with auth.
 *
 * Does NOT own:
 *   - Supabase client creation, config fetch, session lifecycle, redirects,
 *     or the ZKAuth API — that all lives in auth-core.js.
 */

(function () {
  'use strict';

  var DEFAULT_AVATAR = '/artifacts/avatars/avatar_00.svg';

  var loginBtn, loginArrow, providerGrid, userMenu, userAvatar, userName;
  var loginModal, modalOverlay, modalClose, loginForm, loginEmail, loginPassword;
  var loginError, oauthGoogle, modalProviders;
  var AUTH_PROVIDERS = ['google', 'github', 'apple', 'twitter', 'facebook', 'twitch'];

  function resolveDOM() {
    loginBtn = document.getElementById('login-btn');
    loginArrow = document.getElementById('login-arrow');
    providerGrid = document.getElementById('provider-grid');
    userMenu = document.getElementById('user-menu');
    userAvatar = document.getElementById('user-avatar');
    userName = document.getElementById('user-name');
    loginModal = document.getElementById('login-modal');
    modalOverlay = document.getElementById('modal-overlay');
    modalClose = document.getElementById('modal-close');
    loginForm = document.getElementById('login-form');
    loginEmail = document.getElementById('login-email');
    loginPassword = document.getElementById('login-password');
    loginError = document.getElementById('login-error');
    oauthGoogle = document.getElementById('oauth-google');
    modalProviders = document.querySelectorAll('.modal-provider-btn');
  }

  function isKnownProvider(value) {
    return AUTH_PROVIDERS.indexOf(value) !== -1;
  }

  function patchCacheState(partial) {
    if (window.ZKAuth && window.ZKAuth._internal &&
        typeof window.ZKAuth._internal.patchCacheState === 'function') {
      window.ZKAuth._internal.patchCacheState(partial);
    }
  }

  function setReturnPath(path) {
    if (window.ZKAuth && window.ZKAuth._internal &&
        typeof window.ZKAuth._internal.setReturnPath === 'function') {
      window.ZKAuth._internal.setReturnPath(path);
    }
  }

  function isLandingPage() {
    return window.location.pathname === '/';
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function buildFallbackAvatar(label) {
    var text = (label || 'User').trim().charAt(0).toUpperCase() || 'U';
    var bg = '#102a31';
    var fg = '#d7f7f2';
    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" role="img" aria-label="' +
      escapeHtml(text) +
      '">' +
      '<rect width="96" height="96" rx="48" fill="' + bg + '"/>' +
      '<circle cx="48" cy="38" r="18" fill="' + fg + '" fill-opacity="0.92"/>' +
      '<path d="M20 84c4.5-17 16.7-25 28-25s23.5 8 28 25" fill="' + fg + '" fill-opacity="0.92"/>' +
      '<text x="48" y="56" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="32" font-weight="700" fill="' +
      bg +
      '">' +
      escapeHtml(text) +
      '</text>' +
      '</svg>';
    return 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg);
  }

  function normalizeAvatarUrl(avatar) {
    if (!avatar || typeof avatar !== 'string') return DEFAULT_AVATAR;
    var trimmed = avatar.trim();
    if (!trimmed) return DEFAULT_AVATAR;
    if (trimmed.indexOf('data:image/') === 0 || trimmed.indexOf('blob:') === 0) {
      return trimmed;
    }
    try {
      var resolved = new URL(trimmed, window.location.origin);
      if (resolved.protocol === 'https:' || resolved.protocol === 'http:') {
        return resolved.href;
      }
    } catch (_err) {
      // fall through to default avatar
    }
    return DEFAULT_AVATAR;
  }

  function applyAvatar(avatar, altText) {
    if (!userAvatar) return;
    var resolved = normalizeAvatarUrl(avatar);
    var fallback = buildFallbackAvatar(altText);
    var fellBack = false;

    userAvatar.alt = altText || 'User';
    userAvatar.decoding = 'async';
    userAvatar.loading = 'eager';
    userAvatar.referrerPolicy = 'no-referrer';

    userAvatar.onerror = function () {
      if (fellBack) return;
      fellBack = true;
      userAvatar.onerror = null;
      userAvatar.src = fallback;
    };

    userAvatar.onload = function () {
      if (fellBack) return;
      userAvatar.onerror = null;
    };

    userAvatar.src = resolved;
  }

  async function fetchProfile(session) {
    if (!session || !session.access_token) return null;
    try {
      var resp = await fetch('/api/me', {
        headers: { Authorization: 'Bearer ' + session.access_token },
      });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (_err) {
      return null;
    }
  }

  function buildUserName(session, profile) {
    if (profile && profile.name) return profile.name;
    var meta = session && session.user ? (session.user.user_metadata || {}) : {};
    return meta.full_name || (profile && profile.email) || (session && session.user && session.user.email) || 'User';
  }

  function buildAvatar(session, profile) {
    // R6 (2026-05-30): curated-only. The previous fallback to
    // session.user_metadata.avatar_url let an external (Google/Gravatar) or
    // user-supplied URL paint the landing avatar. Route through ZKAvatar when
    // present so only /artifacts/avatars/avatar_NN.svg is ever accepted; a
    // non-curated value resolves to the cached pick or the curated default.
    var profileId = (profile && profile.id) || (session && session.user && session.user.id) || null;
    var candidate = profile && profile.avatar_url;
    if (window.ZKAvatar) return window.ZKAvatar.resolve(profileId, candidate);
    // Fallback when ZKAvatar isn't loaded: anchored curated check (0-119),
    // matching app.py::_CURATED_AVATAR_RE — a prefix check would accept
    // traversal/attacker-suffixed strings.
    var CURATED = /^\/artifacts\/avatars\/avatar_(0\d|[1-9]\d|1[01]\d)\.svg$/;
    return (typeof candidate === 'string' && CURATED.test(candidate)) ? candidate : DEFAULT_AVATAR;
  }

  var _avatarSubBound = false;
  function bindAvatarSubscription(altText) {
    if (_avatarSubBound || !window.ZKAvatar) return;
    _avatarSubBound = true;
    // immediate:false — updateUI already painted the current value.
    window.ZKAvatar.subscribe(function (detail) {
      if (detail && detail.url) applyAvatar(detail.url, altText);
    }, { immediate: false });
  }

  function updateUI(session, profile) {
    if (!loginBtn || !userMenu) return;

    if (session && session.user) {
      loginBtn.style.display = 'none';
      if (loginArrow) loginArrow.style.display = 'none';
      userMenu.style.display = 'flex';

      var displayName = buildUserName(session, profile);
      if (userName) {
        userName.textContent = displayName;
      }
      var avatarUrl = buildAvatar(session, profile);
      applyAvatar(avatarUrl, displayName);
      // R6: seed the shared SoT (silent — we just painted) + subscribe once so
      // the landing avatar refreshes when the picker saves on another surface.
      if (window.ZKAvatar) {
        var pid = (profile && profile.id) || (session.user && session.user.id) || null;
        window.ZKAvatar.set(pid, avatarUrl, { silent: true });
        bindAvatarSubscription(displayName);
      }
      return;
    }

    loginBtn.style.display = 'flex';
    if (loginArrow) loginArrow.style.display = 'flex';
    userMenu.style.display = 'none';
  }

  async function onAuthChange(eventName, session) {
    // Paint synchronously off the session first so the avatar slot fills
    // even before /api/me returns; then upgrade with the richer profile.
    updateUI(session, null);
    if (eventName === 'SIGNED_IN' && loginModal) {
      closeModal();
    }
    if (!session || !session.user) return;
    var profile = await fetchProfile(session);
    updateUI(session, profile);
  }

  function openModal() {
    if (!loginModal) return;
    loginModal.classList.add('open');
    document.body.style.overflow = 'hidden';
    if (loginEmail) loginEmail.focus();
  }

  function closeModal() {
    if (!loginModal) return;
    loginModal.classList.remove('open');
    document.body.style.overflow = '';
    if (loginError) {
      loginError.textContent = '';
      loginError.style.display = 'none';
    }
  }

  async function signInWithProvider(provider) {
    var client = window.ZKAuth && typeof window.ZKAuth.getClient === 'function'
      ? window.ZKAuth.getClient() : null;
    if (!client) return;

    setReturnPath('/home');
    closeModal();

    // Google native (on-domain) flow when GOOGLE_OAUTH_CLIENT_ID is set:
    // ZKAuth.signInWithGoogle navigates to /api/auth/google/start so the
    // consent screen shows our brand/domain. Returns false (flag off) ⇒ fall
    // through to the legacy hosted redirect. Other providers always use legacy.
    if (provider === 'google' && window.ZKAuth &&
        typeof window.ZKAuth.signInWithGoogle === 'function' &&
        window.ZKAuth.signInWithGoogle('/home')) {
      return;
    }

    var result = await client.auth.signInWithOAuth({
      provider: provider,
      options: {
        redirectTo: window.location.origin + '/auth/callback',
      },
    });

    if (result.error) {
      showError('OAuth sign-in failed: ' + result.error.message);
    }
  }

  async function signInWithEmail() {
    var client = window.ZKAuth && typeof window.ZKAuth.getClient === 'function'
      ? window.ZKAuth.getClient() : null;
    if (!client || !loginEmail || !loginPassword) return;

    var email = loginEmail.value.trim();
    var password = loginPassword.value;

    if (!email || !password) {
      showError('Please enter both email and password.');
      return;
    }

    var result = await client.auth.signInWithPassword({ email: email, password: password });

    if (!result.error) {
      patchCacheState({ hasLoggedIn: true, allowCredentialStorage: true, landingPath: '/home' });
      if (isLandingPage()) window.location.replace('/home');
      return;
    }

    if (result.error.message.toLowerCase().indexOf('invalid login') !== -1) {
      var signup = await client.auth.signUp({ email: email, password: password });
      if (signup.error) {
        showError(signup.error.message);
      } else if (signup.data.user && !signup.data.session) {
        showError('Check your email to confirm your account.');
      }
      return;
    }

    showError(result.error.message);
  }

  function showError(msg) {
    if (!loginError) return;
    loginError.textContent = msg;
    loginError.style.display = 'block';
  }

  function bindEvents() {
    if (loginBtn) {
      loginBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        openModal();
      });
    }

    if (loginArrow) {
      loginArrow.addEventListener('click', function (e) {
        e.stopPropagation();
        if (providerGrid) providerGrid.classList.toggle('open');
      });
    }

    document.addEventListener('click', function (e) {
      if (providerGrid && !providerGrid.contains(e.target) && e.target !== loginArrow) {
        providerGrid.classList.remove('open');
      }
    });

    var gridItems = document.querySelectorAll('.provider-item');
    gridItems.forEach(function (item) {
      item.addEventListener('click', function () {
        var provider = item.getAttribute('data-provider');
        if (!isKnownProvider(provider)) return;
        providerGrid.classList.remove('open');
        signInWithProvider(provider);
      });
    });

    if (modalClose) modalClose.addEventListener('click', closeModal);
    if (modalOverlay) modalOverlay.addEventListener('click', closeModal);

    if (loginForm) {
      loginForm.addEventListener('submit', function (e) {
        e.preventDefault();
        signInWithEmail();
      });
    }

    if (oauthGoogle) {
      oauthGoogle.addEventListener('click', function () {
        signInWithProvider('google');
      });
    }

    if (modalProviders) {
      modalProviders.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var provider = btn.getAttribute('data-provider');
          if (!isKnownProvider(provider)) return;
          signInWithProvider(provider);
        });
      });
    }

    var logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', function () {
        if (window.ZKAuth && typeof window.ZKAuth.signOut === 'function') {
          window.ZKAuth.signOut();
        }
      });
    }
  }

  // Compat: pages still using window.signInWithGoogle expect it to exist.
  window.signInWithGoogle = function () { signInWithProvider('google'); };

  function boot() {
    resolveDOM();
    bindEvents();

    if (!window.ZKAuth || typeof window.ZKAuth.onAuthStateChange !== 'function') {
      // auth-core hasn't loaded — render the signed-out chrome so the page
      // is still usable (login button visible) and bail out cleanly.
      updateUI(null, null);
      console.warn('[auth] auth-core.js not present; sign-in disabled.');
      return;
    }

    // Replay-aware subscription: auth-core fires 'REPLAY' synchronously with
    // the current session if it already has one, so the avatar paints on the
    // first frame even if auth-core's init() completed before this script.
    window.ZKAuth.onAuthStateChange(onAuthChange);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
