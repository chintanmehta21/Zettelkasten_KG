// kastens.js — mobile Kasten grid + Create FAB (T10).
//
// API: GET /api/sandboxes (Bearer auth) → { sandboxes: [...] }
// Each kasten: { id, name, description, icon, color, default_quality,
//                member_count, last_used_at, created_at, updated_at }
//
// Auth: 401 (or no token) → redirect to /m/profile (the spec's "all gated
// pages route to Profile when unauth"). Auth-core stores the session in
// localStorage; we wait for ZKAuth.ready before checking.

(function () {
  "use strict";

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function authToken() {
    try {
      if (typeof window.getAuthToken === 'function') {
        var t = window.getAuthToken();
        if (t) return t;
      }
      if (window.ZKAuth && typeof window.ZKAuth.getSession === 'function') {
        var s = await window.ZKAuth.getSession();
        if (s && s.access_token) return s.access_token;
      }
    } catch (e) { void e; }
    return '';
  }

  function gotoProfile() { location.assign('/m/profile'); }

  async function load() {
    var token = await authToken();
    if (!token) { gotoProfile(); return null; }
    try {
      var r = await fetch('/api/sandboxes', {
        credentials: 'include',
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (r.status === 401) { gotoProfile(); return null; }
      if (!r.ok) return [];
      var data = await r.json();
      return data.sandboxes || [];
    } catch {
      return [];
    }
  }

  function render(items) {
    var grid = document.getElementById('kastens-grid');
    var empty = document.getElementById('kastens-empty');
    grid.innerHTML = '';
    if (!items.length) { empty.hidden = false; return; }
    empty.hidden = true;
    items.forEach(function (k) {
      var quality = (k.default_quality || 'fast').toLowerCase();
      var badgeClass = quality === 'strong' ? 'm-kasten-card-badge--strong' : 'm-kasten-card-badge--fast';
      var id = k.id || '';
      var href = '/home/kastens?desktop=1';  // no per-kasten mobile URL; lands on list
      var card = document.createElement('a');
      card.className = 'm-kasten-card';
      card.href = href;
      card.setAttribute('role', 'listitem');
      card.dataset.id = id;
      card.innerHTML =
        '<div class="m-kasten-card-name">' + escHtml(k.name || 'Untitled') + '</div>' +
        '<div class="m-kasten-card-meta">' +
          '<span class="m-kasten-card-badge ' + badgeClass + '">' + escHtml(quality) + '</span>' +
          '<span class="m-kasten-card-count">' + Number(k.member_count || 0) + ' zettels</span>' +
        '</div>';
      grid.appendChild(card);
    });
  }

  async function init() {
    var items = await load();
    if (items === null) return;  // redirect already issued
    render(items);
  }

  function bootWhenAuthReady() {
    if (window.ZKAuth && window.ZKAuth.ready && typeof window.ZKAuth.ready.then === 'function') {
      window.ZKAuth.ready.then(init);
    } else {
      init();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootWhenAuthReady);
  } else {
    bootWhenAuthReady();
  }
})();
