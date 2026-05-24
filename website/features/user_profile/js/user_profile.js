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
  const AVATAR_COUNT = 60;

  let _client = null;
  let _token = '';
  let _currentAvatarId = null;

  let listEl;
  let emptyEl;
  let loadingEl;
  let toastEl;
  let toastTextEl;
  let toastTimer = null;
  let _confirmId = null;
  let _confirmTimer = null;
  let avatarGridEl;

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

  function formatJoinedDate(iso) {
    if (!iso) return '—';
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '—';
    return new Date(t).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
  }

  function renderAccount(profile, session) {
    const nameEl = $('account-name');
    const emailEl = $('account-email');
    const joinedEl = $('account-joined');
    if (nameEl) nameEl.textContent = profile.name || profile.email || '—';
    if (emailEl) emailEl.textContent = profile.email || '—';
    const created = session && session.user ? session.user.created_at : null;
    if (joinedEl) joinedEl.textContent = formatJoinedDate(created);
  }

  async function fetchJSON(url, token) {
    try {
      const resp = await fetch(url, { headers: { Authorization: 'Bearer ' + token } });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (_) {
      return null;
    }
  }

  async function renderStats(token) {
    // Zettels — total + breakdown by source_type
    // /api/zettels/list was wrong (returned 405); home.js loadZettels uses /api/zettels
    fetchJSON('/api/zettels', token).then((data) => {
      const rows = data && Array.isArray(data.zettels) ? data.zettels : [];
      const totalEl = $('stat-zettels-total');
      const breakdownEl = $('stat-zettels-breakdown');
      if (totalEl) totalEl.textContent = String(rows.length);
      if (!breakdownEl) return;
      const bySource = {};
      rows.forEach((z) => {
        const s = (z.source_type || 'web').toLowerCase();
        bySource[s] = (bySource[s] || 0) + 1;
      });
      breakdownEl.textContent = Object.entries(bySource)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
        .map(([s, c]) => s + ' ' + c)
        .join(' · ');
    });

    // Kastens — total + zettels assigned across them
    fetchJSON('/api/rag/sandboxes', token).then((data) => {
      const sandboxes = data && Array.isArray(data.sandboxes) ? data.sandboxes : [];
      const totalEl = $('stat-kastens-total');
      const subEl = $('stat-kastens-members');
      if (totalEl) totalEl.textContent = String(sandboxes.length);
      const members = sandboxes.reduce((acc, s) => acc + (s.member_count || 0), 0);
      if (subEl) subEl.textContent = members + ' zettel' + (members === 1 ? '' : 's') + ' grouped';
    });

    // Knowledge graph — node + connection counts
    fetchJSON('/api/graph', token).then((data) => {
      const nodes = data && Array.isArray(data.nodes) ? data.nodes.length : 0;
      const links = data && Array.isArray(data.links) ? data.links.length : 0;
      const nodesEl = $('stat-kg-nodes');
      const linksEl = $('stat-kg-links');
      if (nodesEl) nodesEl.textContent = String(nodes);
      if (linksEl) linksEl.textContent = links + ' connection' + (links === 1 ? '' : 's');
    });

    // Plan — tier from billing-profile; usage detail lives on /pricing
    fetchJSON('/api/pricing/billing-profile', token).then((data) => {
      const bp = (data && data.profile) || {};
      const tier = bp.plan_name || bp.plan_id || 'Free';
      const tierEl = $('stat-plan-tier');
      const usageEl = $('stat-plan-usage');
      if (tierEl) tierEl.textContent = tier;
      if (usageEl) usageEl.textContent = 'Period limits & usage on /pricing';
    });
  }

  function bindDangerZone() {
    const signOutBtn = $('profile-sign-out');
    if (signOutBtn && !signOutBtn.dataset.zkBound) {
      signOutBtn.dataset.zkBound = '1';
      signOutBtn.addEventListener('click', async () => {
        signOutBtn.disabled = true;
        try {
          if (_client) await _client.auth.signOut();
        } catch (err) {
          console.error('[user_profile] signOut failed:', err);
        } finally {
          window.location.href = '/';
        }
      });
    }
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

  function renderAvatarGrid() {
    if (!avatarGridEl) return;
    avatarGridEl.innerHTML = '';
    for (let i = 0; i < AVATAR_COUNT; i++) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'profile-avatar-option' + (i === _currentAvatarId ? ' selected' : '');
      btn.setAttribute('role', 'radio');
      btn.setAttribute('aria-checked', i === _currentAvatarId ? 'true' : 'false');
      btn.setAttribute('aria-label', 'Avatar ' + i);
      btn.dataset.avatarId = String(i);
      btn.innerHTML = '<img src="/artifacts/avatars/avatar_' + String(i).padStart(2, '0') + '.svg" alt="" />';
      btn.addEventListener('click', () => handleAvatarPick(i, btn));
      avatarGridEl.appendChild(btn);
    }
  }

  async function handleAvatarPick(id, btnEl) {
    if (!_token || id === _currentAvatarId) return;
    _currentAvatarId = id;
    avatarGridEl.querySelectorAll('.profile-avatar-option').forEach((el) => {
      el.classList.remove('selected');
      el.setAttribute('aria-checked', 'false');
    });
    btnEl.classList.add('selected');
    btnEl.setAttribute('aria-checked', 'true');
    try {
      if (window.ZKHeader && typeof window.ZKHeader.setAvatarById === 'function') {
        await window.ZKHeader.setAvatarById(id, _token, null);
        showToast('Avatar updated.');
      }
    } catch (err) {
      console.error('[user_profile] avatar update failed:', err);
      showToast('Avatar update failed.');
    }
  }

  async function init() {
    listEl     = $('trash-list');
    emptyEl    = $('trash-empty');
    loadingEl  = $('trash-loading');
    toastEl    = $('profile-toast');
    toastTextEl = $('profile-toast-text');
    avatarGridEl = $('profile-avatar-grid');

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

    const idMatch = profile.avatar_url && profile.avatar_url.match(/avatar_(\d+)\.svg/);
    if (idMatch) _currentAvatarId = parseInt(idMatch[1], 10);
    renderAvatarGrid();

    renderAccount(profile, sessionResult.data.session);
    renderStats(_token);
    bindDangerZone();

    await loadTrash();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
