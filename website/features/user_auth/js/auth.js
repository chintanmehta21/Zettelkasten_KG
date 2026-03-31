/**
 * Zettelkasten Auth Module
 *
 * Handles Supabase Auth lifecycle: init, login, logout, session state.
 * Features:
 *   - Simple "Login" button with dropdown arrow for provider grid
 *   - Login modal with email/password + OAuth providers
 *   - Provider grid: Google, GitHub, Apple, Twitter, Facebook, Twitch
 */

(function () {
  'use strict';

  var _supabaseClient = null;
  var _currentSession = null;

  // ── DOM refs (resolved on DOMContentLoaded) ───────────────────────
  var loginBtn, loginArrow, providerGrid, userMenu, userAvatar, userName;
  var loginModal, modalOverlay, modalClose, loginForm, loginEmail, loginPassword;
  var loginError, oauthGoogle, modalProviders;

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

  // ── Init ──────────────────────────────────────────────────────────
  async function init() {
    try {
      var resp = await fetch('/api/auth/config');
      var config = await resp.json();

      if (!config.supabase_url || !config.supabase_anon_key) {
        console.log('[auth] Supabase not configured, auth disabled');
        if (loginBtn) loginBtn.style.display = 'none';
        return;
      }

      _supabaseClient = supabase.createClient(config.supabase_url, config.supabase_anon_key);

      _supabaseClient.auth.onAuthStateChange(function (event, session) {
        _currentSession = session;
        updateUI(session);
        if (event === 'SIGNED_IN' && loginModal) {
          closeModal();
        }
      });

      var result = await _supabaseClient.auth.getSession();
      _currentSession = result.data.session;
      updateUI(_currentSession);

      bindEvents();
    } catch (err) {
      console.error('[auth] Init failed:', err);
    }
  }

  // ── UI Updates ────────────────────────────────────────────────────
  function updateUI(session) {
    if (!loginBtn || !userMenu) return;

    if (session && session.user) {
      var meta = session.user.user_metadata || {};
      loginBtn.style.display = 'none';
      if (loginArrow) loginArrow.style.display = 'none';
      userMenu.style.display = 'flex';
      if (userAvatar) {
        userAvatar.src = meta.avatar_url || meta.picture || '';
        userAvatar.alt = meta.full_name || 'User';
      }
      if (userName) {
        userName.textContent = meta.full_name || session.user.email || 'User';
      }
    } else {
      loginBtn.style.display = 'flex';
      if (loginArrow) loginArrow.style.display = 'flex';
      userMenu.style.display = 'none';
    }
  }

  // ── Event Binding ─────────────────────────────────────────────────
  function bindEvents() {
    // Login button → open modal
    if (loginBtn) {
      loginBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        openModal();
      });
    }

    // Dropdown arrow → toggle provider grid
    if (loginArrow) {
      loginArrow.addEventListener('click', function (e) {
        e.stopPropagation();
        if (providerGrid) {
          providerGrid.classList.toggle('open');
        }
      });
    }

    // Close provider grid on outside click
    document.addEventListener('click', function (e) {
      if (providerGrid && !providerGrid.contains(e.target) && e.target !== loginArrow) {
        providerGrid.classList.remove('open');
      }
    });

    // Provider grid items → sign in with that provider
    var gridItems = document.querySelectorAll('.provider-item');
    gridItems.forEach(function (item) {
      item.addEventListener('click', function () {
        var provider = item.getAttribute('data-provider');
        providerGrid.classList.remove('open');
        signInWithProvider(provider);
      });
    });

    // Modal close
    if (modalClose) modalClose.addEventListener('click', closeModal);
    if (modalOverlay) modalOverlay.addEventListener('click', closeModal);

    // Modal email/password login
    if (loginForm) {
      loginForm.addEventListener('submit', function (e) {
        e.preventDefault();
        signInWithEmail();
      });
    }

    // Modal OAuth button
    if (oauthGoogle) {
      oauthGoogle.addEventListener('click', function () {
        signInWithProvider('google');
      });
    }

    // Modal provider buttons
    if (modalProviders) {
      modalProviders.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var provider = btn.getAttribute('data-provider');
          signInWithProvider(provider);
        });
      });
    }

    // Logout
    var logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', function () {
        signOut();
      });
    }
  }

  // ── Modal ─────────────────────────────────────────────────────────
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

  // ── Auth Actions ──────────────────────────────────────────────────
  async function signInWithProvider(provider) {
    if (!_supabaseClient) {
      console.error('[auth] Supabase client not initialized');
      return;
    }
    sessionStorage.setItem('auth_return_to', window.location.pathname);
    closeModal();

    var result = await _supabaseClient.auth.signInWithOAuth({
      provider: provider,
      options: {
        redirectTo: window.location.origin + '/auth/callback',
      },
    });
    if (result.error) {
      console.error('[auth] OAuth error:', result.error.message);
      showError('OAuth sign-in failed: ' + result.error.message);
    }
  }

  async function signInWithEmail() {
    if (!_supabaseClient || !loginEmail || !loginPassword) return;
    var email = loginEmail.value.trim();
    var password = loginPassword.value;

    if (!email || !password) {
      showError('Please enter both email and password.');
      return;
    }

    // Try sign in first, then sign up if user doesn't exist
    var result = await _supabaseClient.auth.signInWithPassword({
      email: email,
      password: password,
    });

    if (result.error) {
      if (result.error.message.toLowerCase().includes('invalid login')) {
        // Try sign up
        var signup = await _supabaseClient.auth.signUp({
          email: email,
          password: password,
        });
        if (signup.error) {
          showError(signup.error.message);
        } else if (signup.data.user && !signup.data.session) {
          showError('Check your email to confirm your account.');
        }
      } else {
        showError(result.error.message);
      }
    }
  }

  function showError(msg) {
    if (!loginError) return;
    loginError.textContent = msg;
    loginError.style.display = 'block';
  }

  async function signOut() {
    if (!_supabaseClient) return;
    await _supabaseClient.auth.signOut();
    _currentSession = null;
    updateUI(null);
  }

  // ── Globals for app.js ────────────────────────────────────────────
  window.getAuthToken = function () {
    return _currentSession ? _currentSession.access_token : null;
  };

  // Keep legacy global for backwards compat
  window.signInWithGoogle = function () { signInWithProvider('google'); };
  window.signOut = signOut;

  // ── Start ─────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { resolveDOM(); init(); });
  } else {
    resolveDOM();
    init();
  }
})();
