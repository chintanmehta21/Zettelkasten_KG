// install-prompt.js — PWA install via a header icon revealed after the user's
// FIRST successful capture (a value moment), per 2026 install-UX research
// (Twitter Lite / Flipkart Lite pattern): no upfront banner — the affordance
// appears only once the user has something worth keeping, which converts far
// better than an on-load interruption and stays out of the way on bad networks.
//
//   Android: capture beforeinstallprompt, defer it; icon click → native prompt().
//   iOS:     no beforeinstallprompt exists; icon click → instructional sheet.
//   Installed users never see the icon (display-mode / navigator.standalone).
//   Dismissal persists 30 days.
//
// The header button (#m-install-btn) and the iOS sheet (#ios-install-sheet)
// live in the mobile shell, so this runs on every /m/* page.

(function () {
  "use strict";

  const DISMISS_KEY  = 'pwa_install_dismissed_at';
  const CAPTURED_KEY = 'zk_pwa_captured';
  const DISMISS_DAYS = 30;
  const DAY_MS = 86400000;

  let deferredPrompt = null;
  let isIOS = false;
  let isInstalled = false;

  function detectInstalled() {
    const mm = window.matchMedia && window.matchMedia('(display-mode: standalone)');
    if (mm && mm.matches) return true;
    if ('standalone' in window.navigator && window.navigator.standalone === true) return true;
    return false;
  }

  function detectIOS() {
    const ua = navigator.userAgent || '';
    return /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  }

  function recentlyDismissed() {
    try {
      const v = localStorage.getItem(DISMISS_KEY);
      if (!v) return false;
      const at = Number(v);
      return Number.isFinite(at) && (Date.now() - at) < DISMISS_DAYS * DAY_MS;
    } catch { return false; }
  }

  function rememberDismissal() {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (e) { void e; }
  }

  function hasCaptured() {
    try { return localStorage.getItem(CAPTURED_KEY) === '1'; } catch { return false; }
  }

  // The post-capture landing is /m/zettels?just_captured=… — record that the
  // user has reached their first value moment so the install icon can appear.
  function markCapturedIfLanding() {
    try {
      if (location.pathname === '/m/zettels' &&
          new URLSearchParams(location.search).has('just_captured')) {
        localStorage.setItem(CAPTURED_KEY, '1');
      }
    } catch (e) { void e; }
  }

  function showHeaderIcon() {
    const btn = document.getElementById('m-install-btn');
    if (btn) btn.hidden = false;
  }
  function hideHeaderIcon() {
    const btn = document.getElementById('m-install-btn');
    if (btn) btn.hidden = true;
  }
  function showIOSSheet() {
    const sheet = document.getElementById('ios-install-sheet');
    if (sheet) sheet.hidden = false;
  }
  function hideIOSSheet() {
    const sheet = document.getElementById('ios-install-sheet');
    if (sheet) sheet.hidden = true;
  }

  // Reveal the icon only after a value moment AND only when it is actionable:
  // iOS is always actionable (instructional sheet); Android needs a deferred
  // beforeinstallprompt in hand, or prompt() would do nothing.
  function refreshIcon() {
    if (isInstalled || recentlyDismissed() || !hasCaptured()) { hideHeaderIcon(); return; }
    if (isIOS || deferredPrompt) showHeaderIcon(); else hideHeaderIcon();
  }

  async function triggerInstall() {
    if (isIOS) { showIOSSheet(); return; }
    if (deferredPrompt) {
      try {
        deferredPrompt.prompt();
        const result = await deferredPrompt.userChoice;
        if (result && result.outcome === 'dismissed') rememberDismissal();
      } catch (err) {
        console.error('[pwa] prompt failed', err);
      }
      deferredPrompt = null;   // beforeinstallprompt is single-use
      hideHeaderIcon();
    }
  }

  function init() {
    isInstalled = detectInstalled();
    isIOS = detectIOS();
    markCapturedIfLanding();

    if (isInstalled) { hideHeaderIcon(); return; }

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      refreshIcon();
    });

    window.addEventListener('appinstalled', () => {
      isInstalled = true;
      hideHeaderIcon();
    });

    const head     = document.getElementById('m-install-btn');
    const iosClose = document.getElementById('ios-install-close');
    if (head) head.addEventListener('click', triggerInstall);
    if (iosClose) iosClose.addEventListener('click', hideIOSSheet);

    refreshIcon();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
