/* ═════════════════════════════════════════════════════════════
   Mobile shell — bottom-tab active state, avatar pill click.
   Loaded on every /m/* page.
   ═════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── Active tab from current path ──
  var path = window.location.pathname;
  var tabFor = function () {
    if (path === '/m/' || path === '/m') return 'capture';
    if (path === '/m/zettels') return 'zettels';
    if (path === '/m/kastens') return 'kastens';
    if (path === '/m/knowledge-graph') return 'graph';
    if (path === '/m/profile') return 'profile';
    return null;
  };
  var active = tabFor();
  if (active) {
    var el = document.querySelector('.m-tab[data-tab="' + active + '"]');
    if (el) el.classList.add('is-active');
  }

  // ── Avatar pill: hand off to auth-modal.js (Phase 3 wires the listener). ──
  // Anonymous => open sign-in modal. Authed => open account menu.
  // shell.js only paints the icon; auth-modal.js manages session state.

})();
