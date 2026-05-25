// zettels.js — mobile Zettels list + multi-section filter + detail modal (T9).
// API: GET /api/zettels → { zettels: [...], total, limit, offset }
// Each zettel: { id, title, title_ready, brief_summary, detailed_summary,
//                tags, source_type, source_url, added_at, published_at }
// Anonymous + ?just_captured: read the stashed payload from sessionStorage.

(function () {
  "use strict";

  const STATE = {
    items: [],
    filtered: [],
    search: '',
    source: 'all',
    tag: '',
    range: 'all',
    sort: 'newest',
    justCapturedId: null,
    isAnon: false,
  };

  function qs(sel) { return document.querySelector(sel); }
  function el(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }

  function hasSession() {
    return document.cookie.split(';').some(c => {
      const name = c.trim().split('=')[0];
      return name === 'sb-access-token' || (name.startsWith('sb-') && name.endsWith('-auth-token'));
    });
  }

  function readJustCapturedFromStorage() {
    try {
      const raw = sessionStorage.getItem('zk_just_captured');
      if (!raw) return null;
      sessionStorage.removeItem('zk_just_captured');
      return JSON.parse(raw);
    } catch { return null; }
  }

  async function loadZettels() {
    if (STATE.isAnon) {
      const stash = readJustCapturedFromStorage();
      STATE.items = stash ? [normalizeZettel(stash)] : [];
      applyFiltersAndRender();
      return;
    }
    try {
      const r = await fetch('/api/zettels?limit=200', { credentials: 'include' });
      if (!r.ok) { STATE.items = []; renderEmpty(); return; }
      const data = await r.json();
      STATE.items = (data.zettels || []).map(normalizeZettel);
      applyFiltersAndRender();
    } catch {
      STATE.items = []; renderEmpty();
    }
  }

  function normalizeZettel(z) {
    return {
      id: z.id || z.zettel_id || z.canonical_zettel_id || '',
      title: z.title || '',
      titleReady: z.title_ready !== false,
      brief: z.brief_summary || '',
      detail: z.detailed_summary || '',
      tags: Array.isArray(z.tags) ? z.tags : [],
      source: (z.source_type || '').toLowerCase(),
      url: z.source_url || z.url || '',
      added: z.added_at || z.created_at || z.published_at || '',
    };
  }

  function applyFiltersAndRender() {
    let out = STATE.items.slice();

    if (STATE.search) {
      const q = STATE.search.toLowerCase();
      out = out.filter(z =>
        (z.title || '').toLowerCase().includes(q) ||
        (z.brief || '').toLowerCase().includes(q)
      );
    }
    if (STATE.source !== 'all') {
      out = out.filter(z => z.source === STATE.source);
    }
    if (STATE.tag) {
      const t = STATE.tag.toLowerCase();
      out = out.filter(z => z.tags.some(tag => (tag || '').toLowerCase().includes(t)));
    }
    if (STATE.range !== 'all') {
      const days = { today: 1, '7d': 7, '30d': 30 }[STATE.range] || 0;
      if (days > 0) {
        const cutoff = Date.now() - days * 86400000;
        out = out.filter(z => z.added && new Date(z.added).getTime() >= cutoff);
      }
    }

    const sorters = {
      newest: (a, b) => new Date(b.added || 0) - new Date(a.added || 0),
      oldest: (a, b) => new Date(a.added || 0) - new Date(b.added || 0),
      'a-z':  (a, b) => (a.title || '').localeCompare(b.title || ''),
      source: (a, b) => (a.source || '').localeCompare(b.source || ''),
    };
    out.sort(sorters[STATE.sort] || sorters.newest);

    STATE.filtered = out;
    renderList();
  }

  function renderList() {
    const list = qs('#zettels-list');
    const empty = qs('#zettels-empty');
    list.innerHTML = '';
    if (STATE.filtered.length === 0) { empty.hidden = false; return; }
    empty.hidden = true;
    STATE.filtered.forEach(z => {
      const li = el(
        '<li class="m-zettel-card" data-id="' + escAttr(z.id) + '">' +
          '<div class="m-zettel-card-title">' + escHtml(z.titleReady ? (z.title || 'Untitled') : 'Summarizing…') + '</div>' +
          '<div class="m-zettel-card-meta">' +
            '<span class="m-zettel-card-source">' + escHtml(z.source || '—') + '</span>' +
            '<span class="m-zettel-card-time">' + escHtml(relativeTime(z.added)) + '</span>' +
          '</div>' +
        '</li>'
      );
      li.addEventListener('click', () => openDetail(z));
      list.appendChild(li);
    });
  }

  function renderEmpty() {
    qs('#zettels-list').innerHTML = '';
    qs('#zettels-empty').hidden = false;
  }

  function relativeTime(iso) {
    if (!iso) return '';
    const t = new Date(iso).getTime();
    if (!Number.isFinite(t)) return '';
    const diff = (Date.now() - t) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return new Date(iso).toLocaleDateString();
  }

  function openDetail(z) {
    const detail = qs('#zettels-detail');
    qs('#zettels-detail-content').innerHTML =
      '<h2>' + escHtml(z.titleReady ? (z.title || 'Untitled') : 'Summarizing…') + '</h2>' +
      (z.url ? '<a class="m-zettel-detail-link" href="' + escAttr(z.url) + '" target="_blank" rel="noopener noreferrer">Open source</a>' : '') +
      '<p class="m-zettel-detail-brief">' + escHtml(z.brief) + '</p>' +
      '<div class="m-zettel-detail-summary">' + linesToHtml(z.detail) + '</div>';
    detail.hidden = false;
    if (z.id) history.pushState({ detail: z.id }, '');
  }

  function closeDetail() {
    qs('#zettels-detail').hidden = true;
    if (history.state && history.state.detail) history.back();
  }

  function linesToHtml(s) {
    // Minimal markdown-ish: paragraphs separated by blank lines.
    return (s || '').split(/\n\n+/).map(p => '<p>' + escHtml(p) + '</p>').join('');
  }

  // ── Multi-section filter sheet (D8): source / tag / date / sort ──
  function openFilterSheet() {
    const root = document.createElement('div');
    root.className = 'zk-sheet-root zk-filter-sheet';
    root.innerHTML =
      '<div class="zk-sheet-backdrop" data-close="1"></div>' +
      '<div class="zk-sheet" role="dialog" aria-modal="true">' +
        '<div class="zk-sheet-handle"></div>' +
        '<div class="zk-sheet-title">Filter</div>' +

        '<div class="zk-filter-section"><div class="zk-filter-section-h">Source</div>' +
          '<div class="zk-filter-chips" data-group="source">' +
            chip('all', 'All', STATE.source === 'all') +
            chip('youtube', 'YouTube', STATE.source === 'youtube') +
            chip('github',  'GitHub',  STATE.source === 'github')  +
            chip('reddit',  'Reddit',  STATE.source === 'reddit')  +
            chip('newsletter', 'Newsletter', STATE.source === 'newsletter') +
            chip('web',     'Web',     STATE.source === 'web') +
          '</div>' +
        '</div>' +

        '<div class="zk-filter-section"><div class="zk-filter-section-h">Tag</div>' +
          '<input type="search" class="zk-filter-tag-input" placeholder="Filter by tag…" value="' + escAttr(STATE.tag || '') + '">' +
        '</div>' +

        '<div class="zk-filter-section"><div class="zk-filter-section-h">Date range</div>' +
          '<div class="zk-filter-chips" data-group="range">' +
            chip('all',   'All',     STATE.range === 'all')   +
            chip('today', 'Today',   STATE.range === 'today') +
            chip('7d',    'Last 7d', STATE.range === '7d')    +
            chip('30d',   'Last 30d',STATE.range === '30d')   +
          '</div>' +
        '</div>' +

        '<div class="zk-filter-section"><div class="zk-filter-section-h">Sort</div>' +
          '<div class="zk-filter-chips" data-group="sort">' +
            chip('newest', 'Newest', STATE.sort === 'newest') +
            chip('oldest', 'Oldest', STATE.sort === 'oldest') +
            chip('a-z',    'A → Z',  STATE.sort === 'a-z')    +
            chip('source', 'Source', STATE.sort === 'source') +
          '</div>' +
        '</div>' +

        '<button type="button" class="m-btn m-btn-primary zk-filter-apply">Apply</button>' +
      '</div>';

    document.body.appendChild(root);
    requestAnimationFrame(() => root.classList.add('is-open'));

    root.addEventListener('click', (e) => {
      const target = e.target;
      if (target instanceof HTMLElement && target.dataset.close === '1') {
        closeFilterSheet(root);
        return;
      }
      const chipEl = target && target.closest && target.closest('[data-value]');
      if (chipEl && chipEl.parentElement) {
        const group = chipEl.parentElement.dataset.group;
        chipEl.parentElement.querySelectorAll('[data-value]').forEach(el => el.classList.remove('is-selected'));
        chipEl.classList.add('is-selected');
        if (group === 'source') STATE.source = chipEl.dataset.value;
        if (group === 'range')  STATE.range  = chipEl.dataset.value;
        if (group === 'sort')   STATE.sort   = chipEl.dataset.value;
      }
      if (target.classList && target.classList.contains('zk-filter-apply')) {
        const tagInput = root.querySelector('.zk-filter-tag-input');
        STATE.tag = (tagInput && tagInput.value || '').trim();
        applyFiltersAndRender();
        closeFilterSheet(root);
      }
    });
  }

  function chip(value, label, selected) {
    return '<button type="button" class="zk-filter-chip' + (selected ? ' is-selected' : '') +
           '" data-value="' + escAttr(value) + '">' + escHtml(label) + '</button>';
  }
  function closeFilterSheet(root) {
    root.classList.remove('is-open');
    setTimeout(() => root.remove(), 240);
  }

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function escAttr(s) { return escHtml(s).replace(/`/g, '&#96;'); }

  function init() {
    const qp = new URLSearchParams(location.search);
    STATE.justCapturedId = qp.get('just_captured');
    STATE.isAnon = !hasSession();

    if (STATE.justCapturedId && STATE.isAnon) {
      qs('#zettels-anon-banner').hidden = false;
    }

    qs('#zettels-search').addEventListener('input', (e) => {
      STATE.search = e.target.value;
      applyFiltersAndRender();
    });
    qs('#zettels-filter-btn').addEventListener('click', openFilterSheet);
    qs('#zettels-detail-close').addEventListener('click', closeDetail);
    qs('#zettels-anon-signin').addEventListener('click', () => location.assign('/m/profile'));
    window.addEventListener('popstate', () => { qs('#zettels-detail').hidden = true; });

    loadZettels();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
