/* user_profile.js — /profile redesign (2026-05-26, exec/build-profile-page-1a).
 *
 * Renders the dark-theme profile page:
 *   • Identity hero (avatar + name + email + joined + UUID copy)
 *   • 26-week zettel-creation heatmap (client-side aggregation of /api/zettels)
 *   • 4 stat cards (Zettels / Kastens / Knowledge graph / Plan)
 *   • Avatar picker (60-icon SVG radio grid, persisted via ZKHeader.setAvatarById)
 *   • Trash recovery (Restore + Delete forever, 2-click confirm muscle-memory match)
 *   • Danger zone (Sign out; Delete account stays disabled until backend wires up)
 *
 * Data sources (all already exposed, no new endpoints):
 *   GET /api/me                     -> { id, email, name, avatar_url, profile_source }
 *   GET /api/zettels                -> { zettels: [{ id, title, source_type, added_at, ... }] }
 *   GET /api/rag/sandboxes          -> { sandboxes: [{ ..., member_count }] }
 *   GET /api/graph                  -> { nodes: [...], links: [...] }
 *   GET /api/pricing/billing-profile-> { profile: { plan_name|plan_id } }
 *   GET /api/zettels/trash          -> { zettels: [...] }
 *   POST /api/zettels/{id}/restore  -> 200 on success
 *   DELETE /api/zettels/{id}/forever-> 200 on success
 *
 * Action endpoints (restore/forever) are BOLA-gated server-side by compound
 * (id + workspace_id) match -- no client-side workspace plumbing needed.
 */
(function () {
  'use strict';

  var zkFetch = window.zkFetch || window.fetch;

  const AVATAR_COUNT = 60;
  const HEATMAP_WEEKS = 26;

  // Localhost preview bypass: when running on localhost without a Supabase
  // session, render the page with stub data instead of redirecting to "/".
  // Production hostname (zettelkasten.in) keeps the strict redirect path.
  const LOCALHOST_HOSTNAMES = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);
  function isLocalhost() {
    return LOCALHOST_HOSTNAMES.has(window.location.hostname);
  }
  const LOCAL_STUB_PROFILE = {
    id: '00000000-0000-0000-0000-0000000d3f17',
    email: 'localhost@dev',
    name: 'Local Preview',
    avatar_url: '/artifacts/avatars/avatar_07.svg',
    profile_source: 'localhost-stub',
  };
  const LOCAL_STUB_SESSION = { user: { created_at: new Date().toISOString() } };

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
  let avatarOverlayEl;
  let avatarGridRendered = false;
  let _lastFocusBeforeModal = null;
  let heatmapEl;
  let heatmapEmptyEl;
  let activityMetaEl;
  let trashMetaEl;

  function $(id) { return document.getElementById(id); }

  /* ─── Supabase / auth bootstrap ─────────────────────────────────────── */

  async function initSupabase() {
    try {
      const resp = await zkFetch('/api/auth/config');
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
      const resp = await zkFetch('/api/me', { headers: { Authorization: 'Bearer ' + token } });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (_) { return null; }
  }

  async function fetchJSON(url, token) {
    try {
      const resp = await zkFetch(url, { headers: { Authorization: 'Bearer ' + token } });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (_) {
      return null;
    }
  }

  /* ─── Identity hero ─────────────────────────────────────────────────── */

  function renderHero(profile, session) {
    const nameEl = $('hero-name');
    const emailEl = $('hero-email');
    const joinedEl = $('hero-joined');
    const heroImg = $('hero-avatar-img');
    const heroFallback = $('hero-avatar-fallback');

    if (nameEl) nameEl.textContent = profile.name || profile.email || 'Friend';
    if (emailEl) emailEl.textContent = profile.email || '—';
    const created = session && session.user ? session.user.created_at : null;
    if (joinedEl) joinedEl.textContent = formatJoinedDate(created);

    if (heroImg && profile.avatar_url) {
      heroImg.addEventListener('load', () => {
        heroImg.hidden = false;
        if (heroFallback) heroFallback.style.display = 'none';
      }, { once: true });
      heroImg.src = profile.avatar_url;
    }

    bindAvatarModalOpeners();
    renderUuidPill(profile.id);
  }

  /* ─── Avatar modal — open / close / focus management ───────────────── */

  function bindAvatarModalOpeners() {
    // Hero avatar is the only opener — the dedicated "Change avatar" CTA
    // was removed because the pencil badge already telegraphs clickability.
    const heroBtn = $('hero-avatar-btn');
    if (heroBtn && !heroBtn.dataset.zkBound) {
      heroBtn.dataset.zkBound = '1';
      heroBtn.addEventListener('click', openAvatarModal);
    }

    if (avatarOverlayEl && !avatarOverlayEl.dataset.zkBound) {
      avatarOverlayEl.dataset.zkBound = '1';
      // Close: any element marked with data-close-avatar (backdrop + X button).
      avatarOverlayEl.querySelectorAll('[data-close-avatar]').forEach((el) => {
        el.addEventListener('click', closeAvatarModal);
      });
      // Close: Escape while open.
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !avatarOverlayEl.classList.contains('hidden')) {
          closeAvatarModal();
        }
      });
    }
  }

  function openAvatarModal() {
    if (!avatarOverlayEl) return;
    if (!avatarGridRendered) {
      renderAvatarGrid();
      avatarGridRendered = true;
    }
    _lastFocusBeforeModal = document.activeElement;
    avatarOverlayEl.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    // Move focus inside the dialog for keyboard users.
    const firstFocusable = avatarOverlayEl.querySelector('.profile-avatar-option.selected, .profile-avatar-option, .profile-avatar-dialog-close');
    if (firstFocusable) firstFocusable.focus();
  }

  function closeAvatarModal() {
    if (!avatarOverlayEl) return;
    avatarOverlayEl.classList.add('hidden');
    document.body.style.overflow = '';
    if (_lastFocusBeforeModal && typeof _lastFocusBeforeModal.focus === 'function') {
      _lastFocusBeforeModal.focus();
    }
  }

  function renderUuidPill(uuid) {
    if (!uuid || !isUuid(uuid)) return;  // only render if id is a proper UUID
    const pill = $('hero-uuid-btn');
    const sep = $('hero-uuid-sep');
    const code = $('hero-uuid-code');
    if (!pill || !code) return;
    code.textContent = uuid.slice(0, 8);  // short prefix, full UUID copies on click
    pill.hidden = false;
    if (sep) sep.hidden = false;
    if (pill.dataset.zkBound) return;
    pill.dataset.zkBound = '1';
    pill.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(uuid);
        pill.classList.add('copied');
        showToast('Account ID copied');
        window.setTimeout(() => pill.classList.remove('copied'), 1200);
      } catch (err) {
        console.error('[user_profile] uuid copy failed:', err);
        showToast('Copy failed');
      }
    });
  }

  function isUuid(value) {
    return typeof value === 'string'
      && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
  }

  /* ─── Trash ─────────────────────────────────────────────────────────── */

  async function loadTrash() {
    showLoading(true);
    try {
      const resp = await zkFetch('/api/zettels/trash', {
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
    Array.from(listEl.querySelectorAll('.profile-trash-card')).forEach(n => n.remove());

    if (trashMetaEl) {
      trashMetaEl.textContent = rows.length
        ? rows.length + (rows.length === 1 ? ' item' : ' items')
        : '';
    }

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
      handleRestore(row.id, card);
    });

    foreverBtn.addEventListener('click', (e) => {
      e.preventDefault();
      // Two-click confirm — first click arms, second commits within 2.8s.
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
      btn.textContent = '';
      btn.append(makeIconNode('forever'), document.createTextNode('Delete forever'));
    });
  }

  async function handleRestore(id, cardEl) {
    try {
      const resp = await zkFetch('/api/zettels/' + encodeURIComponent(id) + '/restore', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + _token }
      });
      if (!resp.ok) throw new Error('restore failed: ' + resp.status);
      animateRemove(cardEl);
      decTrashCount();
      showToast('Restored to your workspace.');
      maybeShowEmpty();
    } catch (err) {
      console.error('[user_profile] restore failed:', err);
      showToast('Restore failed. Try again.');
    }
  }

  async function handleForever(id, cardEl) {
    try {
      const resp = await zkFetch('/api/zettels/' + encodeURIComponent(id) + '/forever', {
        method: 'DELETE',
        headers: { Authorization: 'Bearer ' + _token }
      });
      if (!resp.ok) throw new Error('forever failed: ' + resp.status);
      animateRemove(cardEl);
      decTrashCount();
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

  function decTrashCount() {
    if (!trashMetaEl) return;
    const remaining = listEl.querySelectorAll('.profile-trash-card:not(.is-removing)').length - 1;
    if (remaining <= 0) {
      trashMetaEl.textContent = '';
    } else {
      trashMetaEl.textContent = remaining + (remaining === 1 ? ' item' : ' items');
    }
  }

  function maybeShowEmpty() {
    window.setTimeout(() => {
      if (!listEl.querySelector('.profile-trash-card') && emptyEl) {
        emptyEl.hidden = false;
      }
    }, 720);
  }

  /* ─── Toast ─────────────────────────────────────────────────────────── */

  function showToast(message) {
    if (!toastEl || !toastTextEl) return;
    toastTextEl.textContent = message;
    toastEl.classList.remove('hidden');
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toastEl.classList.add('hidden'), 2400);
  }

  /* ─── Dates ─────────────────────────────────────────────────────────── */

  function formatJoinedDate(iso) {
    if (!iso) return '—';
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '—';
    return new Date(t).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
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

  /* ─── Escape helpers ────────────────────────────────────────────────── */

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function escapeAttr(s) { return escapeHtml(s); }

  /* ─── Stats (each card resolves independently) ──────────────────────── */

  function clearSkeleton(el, text) {
    if (!el) return;
    el.classList.remove('skeleton');
    el.removeAttribute('aria-busy');
    if (text !== undefined) el.textContent = text;
  }

  function renderStats(token) {
    // Zettels — also seeds the heatmap (single fetch, two consumers)
    fetchJSON('/api/zettels', token).then((data) => {
      const rows = data && Array.isArray(data.zettels) ? data.zettels : [];
      const totalEl = $('stat-zettels-total');
      const breakdownEl = $('stat-zettels-breakdown');
      clearSkeleton(totalEl, String(rows.length));
      if (breakdownEl) {
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
      }
      renderHeatmap(rows);
    });

    // Kastens
    fetchJSON('/api/rag/sandboxes', token).then((data) => {
      const sandboxes = data && Array.isArray(data.sandboxes) ? data.sandboxes : [];
      const totalEl = $('stat-kastens-total');
      const subEl = $('stat-kastens-members');
      clearSkeleton(totalEl, String(sandboxes.length));
      const members = sandboxes.reduce((acc, s) => acc + (s.member_count || 0), 0);
      if (subEl) subEl.textContent = members + ' zettel' + (members === 1 ? '' : 's') + ' grouped';
    });

    // Knowledge graph
    fetchJSON('/api/graph', token).then((data) => {
      const nodes = data && Array.isArray(data.nodes) ? data.nodes.length : 0;
      const links = data && Array.isArray(data.links) ? data.links.length : 0;
      const nodesEl = $('stat-kg-nodes');
      const linksEl = $('stat-kg-links');
      clearSkeleton(nodesEl, String(nodes));
      if (linksEl) linksEl.textContent = links + ' connection' + (links === 1 ? '' : 's');
    });

    // Plan — tier only; usage detail lives on /pricing
    fetchJSON('/api/pricing/billing-profile', token).then((data) => {
      const bp = (data && data.profile) || {};
      const tier = bp.plan_name || bp.plan_id || 'Free';
      const tierEl = $('stat-plan-tier');
      const usageEl = $('stat-plan-usage');
      clearSkeleton(tierEl, tier);
      if (usageEl) usageEl.textContent = 'Period limits & usage on /pricing';
    });
  }

  /* ─── Activity heatmap (26 weeks, client-side aggregation) ──────────── */

  function renderHeatmap(rows) {
    if (!heatmapEl) return;
    heatmapEl.innerHTML = '';

    if (!rows || !rows.length) {
      if (heatmapEmptyEl) heatmapEmptyEl.hidden = false;
      if (activityMetaEl) activityMetaEl.textContent = '0 zettels';
      return;
    }
    if (heatmapEmptyEl) heatmapEmptyEl.hidden = true;

    // Bucket rows by YYYY-MM-DD using local-time. ``added_at`` is the
    // workspace_zettels.created_at ISO string emitted by /api/zettels.
    const counts = new Map();
    let inWindowTotal = 0;
    const startMs = startOfDay(Date.now() - (HEATMAP_WEEKS * 7 - 1) * 86400000);
    rows.forEach((z) => {
      const ts = Date.parse(z.added_at);
      if (Number.isNaN(ts)) return;
      if (ts < startMs) return;
      const key = isoDay(ts);
      counts.set(key, (counts.get(key) || 0) + 1);
      inWindowTotal += 1;
    });

    // Build the grid column-by-column (7 rows = days-of-week, Sun..Sat).
    // The leftmost column starts on the Sunday of the earliest visible week.
    const today = startOfDay(Date.now());
    const todayDow = new Date(today).getDay();          // 0=Sun
    const firstColStart = today - (HEATMAP_WEEKS - 1) * 7 * 86400000 - todayDow * 86400000;

    let maxCount = 1;
    counts.forEach((v) => { if (v > maxCount) maxCount = v; });

    for (let col = 0; col < HEATMAP_WEEKS; col++) {
      for (let row = 0; row < 7; row++) {
        const dayMs = firstColStart + (col * 7 + row) * 86400000;
        const cell = document.createElement('span');
        cell.className = 'profile-heatmap-cell';
        cell.style.gridColumn = String(col + 1);
        cell.style.gridRow = String(row + 1);
        cell.style.animationDelay = (col * 18) + 'ms';
        if (dayMs > today) {
          cell.style.visibility = 'hidden';            // future, leave the slot but don't show
        } else if (dayMs < startMs) {
          // before window — shouldn't happen with current math, defensive
          cell.style.visibility = 'hidden';
        } else {
          const key = isoDay(dayMs);
          const c = counts.get(key) || 0;
          if (c > 0) cell.classList.add(bucketClass(c, maxCount));
          const label = formatHeatmapTooltip(dayMs, c);
          cell.title = label;
          cell.setAttribute('aria-label', label);
        }
        heatmapEl.appendChild(cell);
      }
    }

    if (activityMetaEl) {
      activityMetaEl.textContent = inWindowTotal + (inWindowTotal === 1 ? ' zettel' : ' zettels') + ' in 26 weeks';
    }
  }

  function bucketClass(count, max) {
    // 4 visible levels above zero. Use a log-ish split so a single dominant
    // day doesn't wash everything else into l1.
    if (count <= 0) return '';
    const ratio = count / Math.max(max, 1);
    if (count === 1 && max <= 2) return 'l2';          // small dataset: surface single days
    if (ratio > 0.66) return 'l4';
    if (ratio > 0.33) return 'l3';
    if (ratio > 0.10) return 'l2';
    return 'l1';
  }

  function startOfDay(ms) {
    const d = new Date(ms);
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }
  function isoDay(ms) {
    const d = new Date(ms);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }
  function formatHeatmapTooltip(ms, count) {
    const d = new Date(ms);
    const date = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    return count > 0
      ? count + (count === 1 ? ' zettel on ' : ' zettels on ') + date
      : 'No zettels on ' + date;
  }

  /* ─── Avatar picker ─────────────────────────────────────────────────── */

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
    if (!_token) return;
    if (id === _currentAvatarId) {
      closeAvatarModal();
      return;
    }
    _currentAvatarId = id;
    avatarGridEl.querySelectorAll('.profile-avatar-option').forEach((el) => {
      el.classList.remove('selected');
      el.setAttribute('aria-checked', 'false');
    });
    btnEl.classList.add('selected');
    btnEl.setAttribute('aria-checked', 'true');

    // Update the hero avatar preview optimistically.
    const heroImg = $('hero-avatar-img');
    const heroFallback = $('hero-avatar-fallback');
    if (heroImg) {
      heroImg.src = '/artifacts/avatars/avatar_' + String(id).padStart(2, '0') + '.svg';
      heroImg.hidden = false;
      if (heroFallback) heroFallback.style.display = 'none';
    }

    // Close the modal first so the toast lands over the dimmed page, not
    // behind the backdrop. The PUT /api/me/avatar request continues in flight.
    closeAvatarModal();

    try {
      if (window.ZKHeader && typeof window.ZKHeader.setAvatarById === 'function') {
        // Persists to core.profiles.avatar_url via PUT /api/me/avatar; the
        // shared header also re-renders its small avatar from the same call.
        await window.ZKHeader.setAvatarById(id, _token, null);
        showToast('Avatar updated.');
      }
    } catch (err) {
      console.error('[user_profile] avatar update failed:', err);
      showToast('Avatar update failed.');
    }
  }

  /* ─── Danger zone ───────────────────────────────────────────────────── */

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

  /* ─── Bootstrap ─────────────────────────────────────────────────────── */

  async function init() {
    listEl        = $('trash-list');
    emptyEl       = $('trash-empty');
    loadingEl     = $('trash-loading');
    toastEl       = $('profile-toast');
    toastTextEl   = $('profile-toast-text');
    avatarGridEl  = $('profile-avatar-grid');
    avatarOverlayEl = $('avatar-overlay');
    heatmapEl     = $('activity-heatmap');
    heatmapEmptyEl = $('activity-empty');
    activityMetaEl = $('activity-meta');
    trashMetaEl   = $('trash-meta');

    _client = await initSupabase();
    let session = null;
    let profile = null;

    if (_client) {
      const sessionResult = await _client.auth.getSession();
      session = sessionResult.data.session;
      _token = session ? session.access_token : '';
      if (_token) {
        profile = await fetchProfile(_token);
      }
    }

    if (!profile) {
      if (isLocalhost()) {
        // Dev preview path: render the page with stub data so designers can
        // inspect the layout without a working Supabase session.
        renderLocalPreviewBanner();
        profile = LOCAL_STUB_PROFILE;
        session = LOCAL_STUB_SESSION;
        _token = '';
      } else {
        window.location.href = '/';
        return;
      }
    }

    if (_token && window.ZKHeader && typeof window.ZKHeader.boot === 'function') {
      await window.ZKHeader.boot(_token, { profile });
    }

    const idMatch = profile.avatar_url && profile.avatar_url.match(/avatar_(\d+)\.svg/);
    if (idMatch) _currentAvatarId = parseInt(idMatch[1], 10);

    renderHero(profile, session);
    // Avatar grid is rendered lazily on first modal open; no init cost.
    if (_token) {
      renderStats(_token);          // also seeds heatmap from the same /api/zettels response
      bindDangerZone();
      await loadTrash();
    } else {
      // Localhost stub state — clear the skeletons, show an empty heatmap +
      // empty trash so the layout is fully visible without real data.
      renderLocalStubData();
      bindDangerZone();
    }
  }

  function renderLocalPreviewBanner() {
    if (document.querySelector('.profile-local-banner')) return;
    const banner = document.createElement('div');
    banner.className = 'profile-local-banner';
    banner.setAttribute('role', 'status');
    banner.innerHTML =
      '<span class="profile-local-banner-dot" aria-hidden="true"></span>' +
      '<span><strong>Local preview</strong> &mdash; no Supabase session, showing stub data. Sign in to see your real data.</span>';
    const container = document.querySelector('.profile-container');
    const main = document.querySelector('.profile-main');
    if (container && main) container.insertBefore(banner, main);
  }

  function renderLocalStubData() {
    // Stats: clear skeletons and show "—"
    ['stat-zettels-total', 'stat-kastens-total', 'stat-kg-nodes', 'stat-plan-tier'].forEach((id) => {
      const el = $(id);
      if (el) clearSkeleton(el, id === 'stat-plan-tier' ? 'Free' : '0');
    });
    const breakdown = $('stat-zettels-breakdown');
    if (breakdown) breakdown.textContent = 'stub data — no zettels';
    const members = $('stat-kastens-members');
    if (members) members.textContent = '0 zettels grouped';
    const kgLinks = $('stat-kg-links');
    if (kgLinks) kgLinks.textContent = '0 connections';
    const planUsage = $('stat-plan-usage');
    if (planUsage) planUsage.textContent = 'Period limits & usage on /pricing';
    // Heatmap: render the empty state
    renderHeatmap([]);
    // Trash: empty state
    showLoading(false);
    renderTrash([]);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
