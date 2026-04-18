/*
 * /home/kastens — View All page
 * Loads the user's sandboxes, renders a 3-up grid of kasten cards with stats,
 * and wires up the Create Kasten modal (name + quality + scope + members).
 */
(function () {
  'use strict';

  var _supabaseClient = null;
  var _session = null;
  var _token = '';
  var _userNodes = [];              // cached zettels from /api/rag/nodes
  var _userNodesLoaded = false;
  var _selectedNodeIds = new Set();

  var ALL_SOURCES = ['youtube', 'github', 'reddit', 'substack', 'medium', 'twitter', 'web', 'generic'];

  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  async function init() {
    try {
      var cfgResp = await fetch('/api/auth/config');
      var cfg = await cfgResp.json();
      if (cfg.supabase_url && cfg.supabase_anon_key) {
        _supabaseClient = supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key, {
          auth: {
            persistSession: true,
            autoRefreshToken: true,
            storage: window.localStorage,
            storageKey: 'zk-auth-token',
          },
        });
        var s = await _supabaseClient.auth.getSession();
        _session = s.data.session;
      }
    } catch (e) {
      console.error('[kastens] Supabase init failed:', e);
    }

    _token = _session ? _session.access_token : '';
    if (!_token) {
      var last = parseInt(sessionStorage.getItem('zk-kastens-redirect') || '0', 10);
      if (Date.now() - last < 5000) {
        console.warn('[kastens] Redirect loop suppressed');
        return;
      }
      sessionStorage.setItem('zk-kastens-redirect', String(Date.now()));
      window.location.href = '/';
      return;
    }
    sessionStorage.removeItem('zk-kastens-redirect');

    // Shared header (avatar + sign-out) via ZKHeader module.
    if (window.ZKHeader && typeof window.ZKHeader.boot === 'function') {
      try {
        var meResp = await fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + _token } });
        var profile = null;
        if (meResp.ok) profile = await meResp.json();
        if (!profile) {
          var u = _session.user || {};
          var meta = u.user_metadata || {};
          profile = { name: meta.full_name || u.email || 'User', email: u.email || '', avatar_url: meta.avatar_url || meta.picture || '' };
        }
        await window.ZKHeader.boot(_token, { profile: profile });
      } catch (e) {
        console.error('[kastens] Header boot failed:', e);
      }
    }

    await loadSandboxes();
    setupCreateKastenModal();
  }

  // ── Sandboxes ─────────────────────────────────────────────────────

  async function loadSandboxes() {
    var grid = document.getElementById('kastens-grid');
    var emptyEl = document.getElementById('kastens-empty');
    try {
      var resp = await fetch('/api/rag/sandboxes', {
        headers: { 'Authorization': 'Bearer ' + _token }
      });
      if (!resp.ok) {
        console.error('[kastens] GET /sandboxes failed', resp.status);
        renderStats(0, 0, '—');
        grid.innerHTML = '';
        emptyEl.classList.remove('hidden');
        emptyEl.querySelector('h2').textContent = resp.status === 503 ? 'Kastens backend unavailable' : 'Could not load kastens';
        emptyEl.querySelector('p').textContent = 'Please try again shortly.';
        return;
      }
      var data = await resp.json();
      var sandboxes = data.sandboxes || [];
      var totalMembers = sandboxes.reduce(function (a, s) { return a + (s.member_count || 0); }, 0);
      // Sort by last_used_at || updated_at || created_at desc
      sandboxes.sort(function (a, b) {
        var ak = a.last_used_at || a.updated_at || a.created_at || '';
        var bk = b.last_used_at || b.updated_at || b.created_at || '';
        return bk.localeCompare(ak);
      });
      var latestName = sandboxes.length ? sandboxes[0].name : '—';
      renderStats(sandboxes.length, totalMembers, latestName);
      renderGrid(sandboxes);
    } catch (e) {
      console.warn('[kastens] load failed', e);
      renderStats(0, 0, '—');
      grid.innerHTML = '';
      emptyEl.classList.remove('hidden');
    }
  }

  function renderStats(kCount, memberCount, latestName) {
    var s1 = document.getElementById('stat-kastens');
    var s2 = document.getElementById('stat-members');
    var s3 = document.getElementById('stat-latest');
    if (s1) s1.textContent = kCount;
    if (s2) s2.textContent = memberCount;
    if (s3) s3.textContent = latestName || '—';
  }

  function renderGrid(sandboxes) {
    var grid = document.getElementById('kastens-grid');
    var emptyEl = document.getElementById('kastens-empty');
    grid.innerHTML = '';
    if (!sandboxes.length) {
      emptyEl.classList.remove('hidden');
      return;
    }
    emptyEl.classList.add('hidden');

    sandboxes.forEach(function (k) {
      var card = document.createElement('a');
      card.className = 'kastens-card';
      card.href = '/home/rag?sandbox=' + encodeURIComponent(k.id);
      var members = k.member_count || 0;
      var q = (k.default_quality || 'fast').toLowerCase();
      var qLabel = q === 'high' ? 'Strong' : 'Fast';
      var desc = (k.description || '').trim();
      card.innerHTML =
        '<h2 class="kastens-card-title">' + escapeHtml(k.name || 'Untitled') + '</h2>' +
        (desc ? '<p class="kastens-card-desc">' + escapeHtml(desc) + '</p>' : '<p class="kastens-card-desc" style="opacity:0.5">No description</p>') +
        '<div class="kastens-card-meta">' +
          '<span class="kastens-card-members">' + members + ' zettel' + (members === 1 ? '' : 's') + '</span>' +
          '<span class="kastens-card-quality">' + escapeHtml(qLabel) + '</span>' +
        '</div>';
      grid.appendChild(card);
    });
  }

  // ── Create Kasten modal ──────────────────────────────────────────

  function setupCreateKastenModal() {
    var btn = document.getElementById('create-kasten-btn');
    var overlay = document.getElementById('create-kasten-overlay');
    var form = document.getElementById('create-kasten-form');
    var nameInput = document.getElementById('kasten-name');
    var descInput = document.getElementById('kasten-desc');
    var errEl = document.getElementById('create-kasten-error');
    var submit = document.getElementById('create-kasten-submit');
    var sourcePanel = document.getElementById('kasten-scope-source-panel');
    var specificPanel = document.getElementById('kasten-scope-specific-panel');
    var zettelList = document.getElementById('kasten-zettel-list');
    var zettelSearch = document.getElementById('kasten-zettel-search');

    if (!btn || !overlay || !form) return;

    function openModal() {
      errEl.textContent = '';
      form.reset();
      _selectedNodeIds = new Set();
      sourcePanel.classList.add('hidden');
      specificPanel.classList.add('hidden');
      overlay.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
      setTimeout(function () { nameInput && nameInput.focus(); }, 30);
    }
    function closeModal() {
      overlay.classList.add('hidden');
      document.body.style.overflow = '';
    }

    btn.addEventListener('click', openModal);
    overlay.addEventListener('click', function (e) {
      if (e.target && e.target.hasAttribute('data-close-kasten')) closeModal();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !overlay.classList.contains('hidden')) closeModal();
    });

    // Scope radio toggle
    form.querySelectorAll('input[name="kasten-scope"]').forEach(function (r) {
      r.addEventListener('change', async function () {
        var v = r.value;
        sourcePanel.classList.toggle('hidden', v !== 'source');
        specificPanel.classList.toggle('hidden', v !== 'specific');
        if (v === 'specific' && !_userNodesLoaded) {
          await loadUserNodes();
          renderZettelList('');
        }
      });
    });

    if (zettelSearch) {
      zettelSearch.addEventListener('input', function () {
        renderZettelList(zettelSearch.value || '');
      });
    }

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      errEl.textContent = '';

      var name = (nameInput.value || '').trim();
      if (!name) { errEl.textContent = 'Name is required'; return; }
      if (name.length > 80) { errEl.textContent = 'Name must be 80 characters or fewer'; return; }

      var qualityEl = form.querySelector('input[name="kasten-quality"]:checked');
      var quality = qualityEl ? qualityEl.value : 'fast';
      var desc = (descInput.value || '').trim();
      var scope = (form.querySelector('input[name="kasten-scope"]:checked') || {}).value || 'all';

      // Validate scope selection early
      var pickedSources = [];
      if (scope === 'source') {
        form.querySelectorAll('input[name="kasten-source"]:checked').forEach(function (c) { pickedSources.push(c.value); });
        if (!pickedSources.length) { errEl.textContent = 'Select at least one source type'; return; }
      }
      var pickedNodeIds = [];
      if (scope === 'specific') {
        pickedNodeIds = Array.from(_selectedNodeIds);
        if (!pickedNodeIds.length) { errEl.textContent = 'Select at least one zettel'; return; }
      }

      submit.disabled = true;
      submit.textContent = 'Creating…';
      try {
        var createResp = await fetch('/api/rag/sandboxes', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + _token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name, description: desc || null, default_quality: quality })
        });
        if (!createResp.ok) {
          var raw = '';
          try { raw = await createResp.text(); } catch (_) {}
          console.error('[kastens] create failed', createResp.status, raw);
          var detail = '';
          try { var j = JSON.parse(raw); detail = (j && (j.detail || j.error)) || ''; } catch (_) {}
          if (createResp.status === 409) errEl.textContent = 'A kasten with that name already exists';
          else if (createResp.status === 401) errEl.textContent = 'Please sign in again';
          else errEl.textContent = detail || ('Create failed (' + createResp.status + ')');
          return;
        }
        var created = await createResp.json();
        var sandboxId = created && created.sandbox && created.sandbox.id;

        if (sandboxId) {
          // Populate members according to scope
          var memberBody = null;
          if (scope === 'all') {
            memberBody = { source_types: ALL_SOURCES, added_via: 'bulk_source' };
          } else if (scope === 'source') {
            memberBody = { source_types: pickedSources, added_via: 'bulk_source' };
          } else if (scope === 'specific') {
            memberBody = { node_ids: pickedNodeIds, added_via: 'manual' };
          }
          if (memberBody) {
            try {
              var addResp = await fetch('/api/rag/sandboxes/' + encodeURIComponent(sandboxId) + '/members', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + _token, 'Content-Type': 'application/json' },
                body: JSON.stringify(memberBody)
              });
              if (!addResp.ok) {
                var addRaw = '';
                try { addRaw = await addResp.text(); } catch (_) {}
                console.warn('[kastens] add members failed', addResp.status, addRaw);
              }
            } catch (addErr) {
              console.warn('[kastens] add members network error', addErr);
            }
          }
        }

        closeModal();
        await loadSandboxes();
      } catch (err) {
        console.error('[kastens] create network err', err);
        errEl.textContent = 'Network error. Please try again.';
      } finally {
        submit.disabled = false;
        submit.textContent = 'Create';
      }
    });
  }

  // ── Zettel picker ────────────────────────────────────────────────

  async function loadUserNodes() {
    try {
      var resp = await fetch('/api/rag/nodes?limit=500', {
        headers: { 'Authorization': 'Bearer ' + _token }
      });
      if (!resp.ok) {
        console.warn('[kastens] load nodes failed', resp.status);
        _userNodes = [];
        _userNodesLoaded = true;
        return;
      }
      var data = await resp.json();
      _userNodes = data.nodes || [];
      _userNodesLoaded = true;
    } catch (e) {
      console.warn('[kastens] load nodes err', e);
      _userNodes = [];
      _userNodesLoaded = true;
    }
  }

  function renderZettelList(query) {
    var list = document.getElementById('kasten-zettel-list');
    if (!list) return;
    var q = (query || '').trim().toLowerCase();
    var filtered = _userNodes.filter(function (n) {
      if (!q) return true;
      var hay = ((n.name || '') + ' ' + (n.summary || '') + ' ' + (n.source_type || '')).toLowerCase();
      return hay.indexOf(q) !== -1;
    }).slice(0, 200);

    if (!filtered.length) {
      list.innerHTML = '<div class="create-kasten-zettel-empty">No zettels match.</div>';
      return;
    }
    list.innerHTML = '';
    filtered.forEach(function (n) {
      var row = document.createElement('label');
      row.className = 'create-kasten-zettel-item';
      var checked = _selectedNodeIds.has(n.id) ? 'checked' : '';
      row.innerHTML =
        '<input type="checkbox" data-node-id="' + escapeHtml(n.id) + '" ' + checked + ' />' +
        '<div class="create-kasten-zettel-body">' +
          '<div class="create-kasten-zettel-title">' + escapeHtml(n.name || n.id) + '</div>' +
          '<div class="create-kasten-zettel-meta">' + escapeHtml(n.source_type || 'web') + '</div>' +
        '</div>';
      var cb = row.querySelector('input');
      cb.addEventListener('change', function () {
        if (cb.checked) _selectedNodeIds.add(n.id);
        else _selectedNodeIds.delete(n.id);
      });
      list.appendChild(row);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
