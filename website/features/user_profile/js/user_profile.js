/* user_profile.js — Trash recovery surface on /profile.
 *
 * Lists soft-deleted workspace_zettels in the 30-day grace window
 * (migration 67) via GET /api/zettels/trash. Each row exposes:
 *   • Restore  → POST /api/zettels/{id}/restore  → flips deleted_at back to NULL.
 *   • Delete forever → DELETE /api/zettels/{id}/forever  → hard-deletes the row;
 *     two-click confirm pattern (same as live-card remove for muscle-memory).
 *
 * Both action endpoints are BOLA-gated server-side by compound (id +
 * workspace_id) match — no client-side workspace plumbing needed.
 *
 * No optimistic-undo on this page: clicks commit immediately. Users who
 * mis-click Restore can just click Remove on the live card to re-soft-delete;
 * users who mis-click Delete forever lose the grace window — the two-click
 * confirm is the only friction guarding that.
 */
(function () {
  'use strict';

  const SUPABASE_URL = window.__SUPABASE_URL || '';
  const SUPABASE_ANON_KEY = window.__SUPABASE_ANON_KEY || '';

  let _client = null;
  let _token = '';

  let listEl;
  let emptyEl;
  let loadingEl;
  let toastEl;
  let toastTextEl;
  let toastTimer = null;
  let _confirmId = null;
  let _confirmTimer = null;

  function $(id) { return document.getElementById(id); }

  async function initSupabase() {
    // Mirror user_zettels.js — share the zk-auth-token storage scope so
    // the persisted Supabase session is found instead of bouncing to /.
    try {
      const resp = await fetch('/api/auth/config');
      const config = await resp.json();
      if (!config.supabase_url || !config.supabase_anon_key) return null;
      return window.supabase.createClient(config.supabase_url, config.supabase_anon_key, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          storage: window.localStorage,
          storageKey: 'zk-auth-token',
        },
      });
    } catch (err) {
      console.error('[user_profile] Supabase init failed:', err);
      return null;
    }
  }

  async function fetchProfile(token) {
    try {
      const resp = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + token } });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (_) { return null; }
  }

  async function loadTrash() {
    showLoading(true);
    try {
      const resp = await fetch('/api/zettels/trash', {
        headers: { Authorization: 'Bearer ' + _token }
      });
      if (!resp.ok) throw new Error('trash fetch failed: ' + resp.status);
      const data = await resp.json();
      const rows = Array.isArray(data.zettels) ? data.zettels : [];
      renderTrash(rows);
    } catch (err) {
      console.error('[user_profile] loadTrash failed:', err);
      renderTrash([]);
    } finally {
      showLoading(false);
    }
  }

  function showLoading(on) {
    if (loadingEl) loadingEl.hidden = !on;
  }

  function renderTrash(rows) {
    // Clear existing cards, keep the empty-state + loading placeholders.
    Array.from(listEl.querySelectorAll('.profile-trash-card')).forEach(n => n.remove());

    if (!rows.length) {
      if (emptyEl) emptyEl.hidden = false;
      return;
    }
    if (emptyEl) emptyEl.hidden = true;

    rows.forEach(row => listEl.appendChild(buildCard(row)));
  }

  function buildCard(row) {
    const card = document.createElement('article');
    card.className = 'profile-trash-card';
    card.dataset.id = row.id;

    const title = (row.title || '').trim() || 'Untitled';
    const sourceType = (row.source_type || 'web').toLowerCase();
    const removedAt = formatRemovedAgo(row.deleted_at);
    const sourceUrl = row.source_url || '';

    card.innerHTML =
      '<div class="profile-trash-main">' +
        '<h3 class="profile-trash-card-title">' + escapeHtml(title) + '</h3>' +
        '<div class="profile-trash-card-meta">' +
          '<span class="pill">' + escapeHtml(sourceType) + '</span>' +
          (removedAt ? '<span>removed ' + escapeHtml(removedAt) + '</span>' : '') +
          (sourceUrl ? '<a href="' + escapeAttr(sourceUrl) + '" target="_blank" rel="noopener noreferrer">source</a>' : '') +
        '</div>' +
      '</div>' +
      '<div class="profile-trash-actions">' +
        '<button class="profile-trash-btn restore" type="button" aria-label="Restore zettel">' +
          '<svg class="profile-trash-btn-icon" viewBox="0 0 24 24" aria-hidden="true">' +
            '<path d="M3 12a9 9 0 1 0 3.05-6.74L3 8"></path>' +
            '<polyline points="3 3 3 8 8 8"></polyline>' +
          '</svg>' +
          'Restore' +
        '</button>' +
        '<button class="profile-trash-btn forever" type="button" aria-label="Delete permanently">' +
          '<svg class="profile-trash-btn-icon" viewBox="0 0 24 24" aria-hidden="true">' +
            '<polyline points="3 6 5 6 21 6"></polyline>' +
            '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>' +
            '<path d="M10 11v6"></path>' +
            '<path d="M14 11v6"></path>' +
          '</svg>' +
          'Delete forever' +
        '</button>' +
      '</div>';

    const restoreBtn = card.querySelector('.profile-trash-btn.restore');
    const foreverBtn = card.querySelector('.profile-trash-btn.forever');

    restoreBtn.addEventListener('click', (e) => {
      e.preventDefault();
      // Restore commits immediately — low blast radius, easy to mis-click
      // recover from (just click Remove on the live card to soft-delete again).
      handleRestore(row.id, card);
    });

    foreverBtn.addEventListener('click', (e) => {
      e.preventDefault();
      // Two-click confirm — same friction model as live-card Remove.
      if (_confirmId !== row.id) {
        clearConfirmState();
        _confirmId = row.id;
        foreverBtn.classList.add('confirm');
        foreverBtn.textContent = '';
        foreverBtn.append(makeIconNode('forever'), document.createTextNode('Confirm'));
        _confirmTimer = window.setTimeout(clearConfirmState, 2800);
        return;
      }
      clearConfirmState();
      handleForever(row.id, card);
    });

    return card;
  }

  function makeIconNode(kind) {
    const wrap = document.createElement('span');
    wrap.innerHTML = kind === 'forever'
      ? '<svg class="profile-trash-btn-icon" viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path></svg>'
      : '';
    return wrap.firstChild || document.createTextNode('');
  }

  function clearConfirmState() {
    if (_confirmTimer) { window.clearTimeout(_confirmTimer); _confirmTimer = null; }
    _confirmId = null;
    Array.from(listEl.querySelectorAll('.profile-trash-btn.forever.confirm')).forEach(btn => {
      btn.classList.remove('confirm');
      // Re-render the button label cleanly.
      btn.textContent = '';
      btn.append(makeIconNode('forever'), document.createTextNode('Delete forever'));
    });
  }

  async function handleRestore(id, cardEl) {
    try {
      const resp = await fetch('/api/zettels/' + encodeURIComponent(id) + '/restore', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + _token }
      });
      if (!resp.ok) throw new Error('restore failed: ' + resp.status);
      animateRemove(cardEl);
      showToast('Restored to your workspace.');
      maybeShowEmpty();
    } catch (err) {
      console.error('[user_profile] restore failed:', err);
      showToast('Restore failed. Try again.');
    }
  }

  async function handleForever(id, cardEl) {
    try {
      const resp = await fetch('/api/zettels/' + encodeURIComponent(id) + '/forever', {
        method: 'DELETE',
        headers: { Authorization: 'Bearer ' + _token }
      });
      if (!resp.ok) throw new Error('forever failed: ' + resp.status);
      animateRemove(cardEl);
      showToast('Deleted forever.');
      maybeShowEmpty();
    } catch (err) {
      console.error('[user_profile] hard-delete failed:', err);
      showToast('Delete failed. Try again.');
    }
  }

  function animateRemove(cardEl) {
    cardEl.classList.add('is-removing');
    window.setTimeout(() => cardEl.classList.add('is-collapsed'), 320);
    window.setTimeout(() => cardEl.remove(), 700);
  }

  function maybeShowEmpty() {
    window.setTimeout(() => {
      if (!listEl.querySelector('.profile-trash-card') && emptyEl) {
        emptyEl.hidden = false;
      }
    }, 720);
  }

  function showToast(message) {
    if (!toastEl || !toastTextEl) return;
    toastTextEl.textContent = message;
    toastEl.classList.remove('hidden');
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toastEl.classList.add('hidden'), 2400);
  }

  function formatRemovedAgo(iso) {
    if (!iso) return '';
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '';
    const sec = Math.max(0, (Date.now() - t) / 1000);
    if (sec < 60) return 'just now';
    if (sec < 3600) return Math.round(sec / 60) + ' min ago';
    if (sec < 86400) return Math.round(sec / 3600) + ' h ago';
    return Math.round(sec / 86400) + ' d ago';
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function escapeAttr(s) { return escapeHtml(s); }

  async function init() {
    listEl     = $('trash-list');
    emptyEl    = $('trash-empty');
    loadingEl  = $('trash-loading');
    toastEl    = $('profile-toast');
    toastTextEl = $('profile-toast-text');

    _client = await initSupabase();
    if (!_client) { window.location.href = '/'; return; }

    const sessionResult = await _client.auth.getSession();
    _token = sessionResult.data.session ? sessionResult.data.session.access_token : '';
    if (!_token) { window.location.href = '/'; return; }

    const profile = await fetchProfile(_token);
    if (!profile) { window.location.href = '/'; return; }

    if (window.ZKHeader && typeof window.ZKHeader.boot === 'function') {
      await window.ZKHeader.boot(_token, { profile });
    }
    await loadTrash();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
