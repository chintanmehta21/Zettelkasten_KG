// kastens.js — mobile Kasten grid + Create FAB (T10).
// API: GET /api/sandboxes → { sandboxes: [...] }
// Each kasten: { id, name, description, icon, color, default_quality,
//                member_count, last_used_at, created_at, updated_at }
// Tap-card opens desktop view in same tab (per design D7).

(function () {
  "use strict";

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function load() {
    try {
      const r = await fetch('/api/sandboxes', { credentials: 'include' });
      if (!r.ok) return [];
      const data = await r.json();
      return data.sandboxes || [];
    } catch {
      return [];
    }
  }

  function render(items) {
    const grid = document.getElementById('kastens-grid');
    const empty = document.getElementById('kastens-empty');
    grid.innerHTML = '';
    if (!items.length) { empty.hidden = false; return; }
    empty.hidden = true;
    items.forEach(k => {
      const quality = (k.default_quality || 'fast').toLowerCase();
      const badgeClass = quality === 'strong' ? 'm-kasten-card-badge--strong' : 'm-kasten-card-badge--fast';
      const id = k.id || '';
      const href = '/home/kastens?desktop=1';  // no per-kasten mobile URL; lands on list
      const card = document.createElement('a');
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
    const items = await load();
    render(items);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
