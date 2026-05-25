// install-prompt.js — PWA install banner + header icon + iOS instructional sheet (T12).
// Android path: capture beforeinstallprompt; show banner; on click call prompt().
// iOS path:     no beforeinstallprompt; UA-detect + show instructional sheet on click.
// Dismissal persisted 30 days via localStorage.

(function () {
  "use strict";

  const DISMISS_KEY  = 'pwa_install_dismissed_at';
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
      if (!Number.isFinite(at)) return false;
      return (Date.now() - at) < DISMISS_DAYS * DAY_MS;
    } catch { return false; }
  }

  function rememberDismissal() {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch {}
  }

  function showBanner() {
    const banner = document.getElementById('install-banner');
    if (!banner) return;
    if (isIOS) {
      const sub = document.getElementById('install-banner-sub');
      if (sub) sub.textContent = 'Tap Install for setup steps.';
    }
    banner.hidden = false;
  }
  function hideBanner() {
    const banner = document.getElementById('install-banner');
    if (banner) banner.hidden = true;
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

  async function triggerInstall() {
    if (isIOS) { showIOSSheet(); return; }
    if (deferredPrompt) {
      try {
        deferredPrompt.prompt();
        const result = await deferredPrompt.userChoice;
        console.log('[pwa] userChoice:', result && result.outcome);
        if (result && result.outcome === 'dismissed') rememberDismissal();
      } catch (err) {
        console.error('[pwa] prompt failed', err);
      }
      deferredPrompt = null;
      hideBanner();
      hideHeaderIcon();
    }
  }

  function init() {
    isInstalled = detectInstalled();
    isIOS = detectIOS();

    if (isInstalled) { hideBanner(); hideHeaderIcon(); return; }

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      if (!recentlyDismissed()) showBanner(); else showHeaderIcon();
    });

    window.addEventListener('appinstalled', () => {
      isInstalled = true;
      hideBanner();
      hideHeaderIcon();
    });

    // iOS path — no beforeinstallprompt; show banner unless dismissed.
    if (isIOS && !recentlyDismissed()) showBanner();
    if (isIOS && recentlyDismissed()) showHeaderIcon();

    const cta      = document.getElementById('install-banner-cta');
    const close    = document.getElementById('install-banner-close');
    const head     = document.getElementById('m-install-btn');
    const iosClose = document.getElementById('ios-install-close');
    if (cta)   cta.addEventListener('click', triggerInstall);
    if (close) close.addEventListener('click', () => { rememberDismissal(); hideBanner(); showHeaderIcon(); });
    if (head)  head.addEventListener('click', triggerInstall);
    if (iosClose) iosClose.addEventListener('click', hideIOSSheet);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
