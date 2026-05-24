/* ═════════════════════════════════════════════════════════════
   Mobile shell — bottom-tab active state, disabled-tab toast,
   avatar pill click. Loaded on every /m/* page.
   ═════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── Active tab from current path ──
  var path = window.location.pathname;
  var tabFor = function () {
    if (path === '/m/' || path === '/m') return 'capture';
    if (path === '/m/knowledge-graph') return 'graph';
    return null;
  };
  var active = tabFor();
  if (active) {
    var el = document.querySelector('.m-tab[data-tab="' + active + '"]');
    if (el) el.classList.add('is-active');
  }

  // ── Disabled-tab toast ──
  var toastEl = null;
  var toastTimer = null;
  function showToast(message) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'm-toast';
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = message;
    toastEl.classList.add('is-visible');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      if (toastEl) toastEl.classList.remove('is-visible');
    }, 1800);
  }

  var disabledLabels = {
    notes: 'Notes — coming soon',
    chat: 'Chat — coming soon',
    profile: 'Profile — coming soon'
  };

  document.addEventListener('click', function (e) {
    var t = e.target.closest('.m-tab-disabled');
    if (!t) return;
    e.preventDefault();
    var name = t.dataset.tab;
    showToast(disabledLabels[name] || 'Coming soon');
  });

  // ── Avatar pill: hand off to auth-modal.js (Phase 3 wires the listener). ──
  // Anonymous => open sign-in modal. Authed => open account menu.
  // shell.js only paints the icon; auth-modal.js manages session state.

})();
