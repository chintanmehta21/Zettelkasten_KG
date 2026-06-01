/* Mobile OAuth modal — Phase 3 (mobile-1a)
   Depends on: window.ZKAuth (auth.js), window.supabase (CDN)
   Safe to load on all mobile pages — early-exits if DOM nodes absent. */
(function () {
  'use strict';

  const modal     = document.getElementById('m-auth-modal');
  const avatar    = document.getElementById('m-avatar-btn');
  const closeBtn  = document.getElementById('m-auth-close');
  const moreBtn   = document.getElementById('m-auth-more');
  const moreOpts  = document.getElementById('m-auth-more-options');
  const providers = document.getElementById('m-auth-providers');

  // Auth.js DOM-safety guard — if either anchor node is absent, bail out.
  if (!modal || !avatar) return;

  let _client  = null;
  let _session = null;
  let _menu    = null; // active account-menu element

  // ── Modal helpers ──────────────────────────────────────────

  function openModal() {
    modal.showModal();
    document.body.style.overflow = 'hidden';
  }

  function closeModal() {
    if (!modal.open) return;
    modal.close();
    document.body.style.overflow = '';
    // Re-enable all provider buttons when modal closes (user may re-open after back).
    document.querySelectorAll('.m-auth-provider').forEach(function (b) { b.disabled = false; });
  }

  // ── Account menu ───────────────────────────────────────────

  function openAccountMenu() {
    if (_menu) { _menu.remove(); _menu = null; return; }

    const email = _session?.user?.email ?? '';
    const avatarUrl = _session?.user?.user_metadata?.avatar_url ?? '';
    const name      = _session?.user?.user_metadata?.full_name
                   || _session?.user?.user_metadata?.name
                   || email.split('@')[0]
                   || 'Account';

    const menu = document.createElement('div');
    menu.className = 'm-account-menu';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = `
      <div class="m-account-menu-email" title="${escHtml(email)}">${escHtml(name)}</div>
      <button class="m-account-menu-btn" id="m-signout-btn" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
          <polyline points="16 17 21 12 16 7"></polyline>
          <line x1="21" y1="12" x2="9" y2="12"></line>
        </svg>
        Sign out
      </button>
    `;

    menu.querySelector('#m-signout-btn').addEventListener('click', function () {
      menu.remove();
      _menu = null;
      if (typeof window.signOut === 'function') window.signOut();
    });

    // Close if user taps outside
    function onOutsideClick(e) {
      if (!menu.contains(e.target) && e.target !== avatar) {
        menu.remove();
        _menu = null;
        document.removeEventListener('click', onOutsideClick, true);
      }
    }
    // Defer listener so the current click doesn't immediately close it
    setTimeout(function () {
      document.addEventListener('click', onOutsideClick, true);
    }, 0);

    document.body.appendChild(menu);
    _menu = menu;
  }

  function escHtml(str) {
    return str.replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ── Avatar paint ───────────────────────────────────────────

  function paintAvatar(session) {
    _session = session;
    const imgEl = document.getElementById('m-avatar-image');

    if (session) {
      avatar.classList.add('is-authed');
      avatar.setAttribute('aria-label', 'Open account menu');
      if (imgEl) {
        imgEl.hidden = false;
        if (window.ZK && typeof window.ZK.renderAvatar === 'function') {
          // Shared renderer (avatar.js): curated /api/me avatar, random-assigned
          // + persisted when unset — identical to desktop. Replaces the old
          // user_metadata-or-initials path, which showed bare initials for the
          // common case where the avatar lives in the profile (not Supabase
          // user_metadata), e.g. email/password users — the "avatar not loading"
          // report.
          window.ZK.renderAvatar(imgEl, { size: 28 });
        } else {
          // Boot-race fallback: avatar.js not yet loaded → show initials.
          const initial = (
            session.user?.user_metadata?.full_name ||
            session.user?.user_metadata?.name ||
            session.user?.email || 'U'
          ).charAt(0).toUpperCase();
          imgEl.textContent = initial;
          imgEl.classList.add('initials');
        }
      }
    } else {
      avatar.classList.remove('is-authed');
      avatar.setAttribute('aria-label', 'Sign in or open account menu');
      if (imgEl) { imgEl.innerHTML = ''; imgEl.classList.remove('initials'); imgEl.hidden = true; }
    }
  }

  // ── Event wiring ───────────────────────────────────────────

  // Avatar tap — sign-in modal if anon, account menu if authed
  avatar.addEventListener('click', function () {
    if (_session) {
      openAccountMenu();
    } else {
      openModal();
    }
  });

  // Close button
  if (closeBtn) {
    closeBtn.addEventListener('click', closeModal);
  }

  // Backdrop tap — <dialog> fires 'cancel' on Escape; clicking backdrop fires 'click' on dialog itself
  modal.addEventListener('click', function (e) {
    if (e.target === modal) closeModal();
  });

  // Escape key (browsers fire 'cancel' on native <dialog>)
  modal.addEventListener('cancel', function (e) {
    e.preventDefault(); // prevent browser default close so we control body overflow
    closeModal();
  });

  // More-options expander
  if (moreBtn && moreOpts) {
    moreBtn.addEventListener('click', function () {
      const expanded = moreBtn.getAttribute('aria-expanded') === 'true';
      moreBtn.setAttribute('aria-expanded', String(!expanded));
      if (expanded) {
        moreOpts.setAttribute('hidden', '');
      } else {
        moreOpts.removeAttribute('hidden');
      }
    });
  }

  // Provider buttons → OAuth redirect
  if (providers) {
    providers.addEventListener('click', function (e) {
      const btn = e.target.closest('[data-provider]');
      if (!btn) return;
      const provider = btn.getAttribute('data-provider');
      btn.disabled = true;
      // Google native (on-domain) flow when GOOGLE_OAUTH_CLIENT_ID is set:
      // navigates to /api/auth/google/start (consent shows our brand/domain).
      // Returns false (flag off) ⇒ fall through to the legacy hosted redirect.
      if (provider === 'google' && window.ZKAuth &&
          typeof window.ZKAuth.signInWithGoogle === 'function' &&
          window.ZKAuth.signInWithGoogle('/home')) {
        return;
      }
      if (!_client) { btn.disabled = false; return; }
      _client.auth.signInWithOAuth({
        provider: provider,
        options: { redirectTo: window.location.origin + '/auth/callback' },
      }).catch(function () {
        btn.disabled = false;
      });
    });
  }

  // ── Boot: wait for ZKAuth, then hydrate session ────────────

  function boot(client) {
    _client = client;

    // Hydrate current session
    client.auth.getSession().then(function (result) {
      paintAvatar(result?.data?.session ?? null);
    });

    // Subscribe to future auth state changes
    client.auth.onAuthStateChange(function (event, session) {
      paintAvatar(session);
      if (event === 'SIGNED_IN') {
        closeModal();
      }
    });
  }

  // ── Bootstrap: wait for ZKAuth.ready, then bind to Supabase auth events ──
  var _bootAttempts = 0;
  var _BOOT_MAX = 50; // ~5s at 100ms intervals
  function waitForZKAuth() {
    if (window.ZKAuth && typeof window.ZKAuth.ready === 'object' && typeof window.ZKAuth.ready.then === 'function') {
      window.ZKAuth.ready.then(function () {
        boot(window.ZKAuth.getClient());
      });
      return;
    }
    _bootAttempts += 1;
    if (_bootAttempts >= _BOOT_MAX) {
      console.warn('Mobile auth: ZKAuth.ready unavailable after 5s; sign-in unavailable.');
      return;
    }
    setTimeout(waitForZKAuth, 100);
  }
  waitForZKAuth();

  // T11: Profile page broadcasts avatar changes; refresh the header avatar.
  document.addEventListener('zk:avatar-changed', function () {
    if (window.ZK && typeof window.ZK.renderAvatar === 'function') {
      const slot = document.getElementById('m-avatar-image');
      if (slot) {
        slot.hidden = false;
        window.ZK.renderAvatar(slot);
      }
    }
  });
})();
