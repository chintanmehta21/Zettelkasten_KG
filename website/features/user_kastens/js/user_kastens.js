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
  var _userNodes = [];              // cached zettels from /api/graph?view=my
  var _userNodesLoaded = false;
  var _userNodesFetchedAt = 0;
  var _userNodesInflight = null;
  var _selectedNodeIds = new Set();
  var KASTEN_CHOOSER_TTL_MS = 5000;

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

    if (!overlay || !form) return;

    function openModal() {
      // UX-5: paint the modal SHELL synchronously before any data work.
      errEl.textContent = '';
      form.reset();
      _selectedNodeIds = new Set();
      sourcePanel.classList.add('hidden');
      specificPanel.classList.add('hidden');
      overlay.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
      var listEl = document.getElementById('kasten-zettel-list');
      if (listEl && (!_userNodesLoaded || _userNodes.length === 0)) {
        listEl.innerHTML = '<div class="create-kasten-zettel-loading"><span class="btn-inline-spinner" aria-hidden="true"></span>Loading zettels…</div>';
      }
      setTimeout(function () { nameInput && nameInput.focus(); }, 30);
      // Defer the network fetch to the next frame so the modal paints first.
      requestAnimationFrame(function () {
        var ageMs = Date.now() - _userNodesFetchedAt;
        if (!_userNodesLoaded || ageMs > KASTEN_CHOOSER_TTL_MS) {
          loadUserNodes({ silent: true }).then(function () {
            if (!specificPanel.classList.contains('hidden')) {
              renderZettelList(zettelSearch ? zettelSearch.value : '');
            }
          });
        }
      });
    }
    function closeModal() {
      overlay.classList.add('hidden');
      document.body.style.overflow = '';
    }

    // Bind Create Kasten via event delegation on document.body. The direct
    // getElementById listener went stale when the page re-rendered after
    // async auth lands and the original button node was replaced; delegation
    // survives that swap and still fires the click.
    document.body.addEventListener('click', function (e) {
      if (e.target.closest('[data-action="create-kasten"]')) openModal();
    });
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
        if (v === 'specific') {
          if (!_userNodesLoaded) {
            await loadUserNodes();
          }
          renderZettelList(zettelSearch ? zettelSearch.value : '');
        }
      });
    });

    if (zettelSearch) {
      zettelSearch.addEventListener('input', function () {
        renderZettelList(zettelSearch.value || '');
      });
    }

    // UX-3: explicit Refresh button in the chooser header.
    var refreshBtn = document.getElementById('kasten-chooser-refresh');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', async function () {
        refreshBtn.disabled = true;
        try {
          await loadUserNodes({ force: true });
          renderZettelList(zettelSearch ? zettelSearch.value : '');
        } finally {
          refreshBtn.disabled = false;
        }
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
      var pricingActionId = form.getAttribute('data-pricing-action-id') || ('kasten:' + Date.now() + ':' + Math.random().toString(36).slice(2));
      form.setAttribute('data-pricing-action-id', pricingActionId);

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

      // UX-6: prevent re-submit while busy + spinner glyph + data-busy.
      if (submit.disabled) return;
      submit.disabled = true;
      submit.setAttribute('aria-busy', 'true');
      submit.innerHTML = '<span class="btn-inline-spinner" aria-hidden="true"></span>Creating Kasten…';
      form.setAttribute('data-busy', 'true');
      try {
        var createResp = await fetch('/api/rag/sandboxes', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + _token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name, description: desc || null, default_quality: quality, client_action_id: pricingActionId })
        });
        if (!createResp.ok) {
          var raw = '';
          try { raw = await createResp.text(); } catch (_) {}
          console.error('[kastens] create failed', createResp.status, raw);
          var detail = '';
          try { var j = JSON.parse(raw); detail = (j && (j.detail || j.error)) || ''; } catch (_) {}
          if (detail && detail.code === 'quota_exhausted' && window.ZKPricing) {
            await window.ZKPricing.openPurchase({
              detail: detail,
              source: 'my-kastens:create-kasten',
              resumeAction: { type: 'create_kasten', name: name, description: desc, scope: scope, clientActionId: pricingActionId },
              onResume: function () {
                form.setAttribute('data-pricing-action-id', pricingActionId);
                form.requestSubmit();
              }
            });
            return;
          }
          if (createResp.status === 409) errEl.textContent = 'A kasten with that name already exists';
          else if (createResp.status === 401) errEl.textContent = 'Please sign in again';
          else errEl.textContent = (detail && detail.message) || detail || ('Create failed (' + createResp.status + ')');
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
        submit.removeAttribute('aria-busy');
        submit.textContent = 'Create';
        form.removeAttribute('data-busy');
        form.removeAttribute('data-pricing-action-id');
      }
    });
  }

  // ── Zettel picker ────────────────────────────────────────────────

  async function loadUserNodes(opts) {
    opts = opts || {};
    if (_userNodesInflight && !opts.force) return _userNodesInflight;
    _userNodesInflight = (async function () {
      try {
        // UX-3: source the chooser from /api/graph?view=my so newly-added
        // zettels show up; the file-based /api/rag/nodes was lagging.
        var resp = await fetch('/api/graph?view=my', {
          credentials: 'include',
          headers: { 'Authorization': 'Bearer ' + _token }
        });
        if (!resp.ok) {
          console.warn('[kastens] load graph failed', resp.status);
          _userNodes = [];
        } else {
          var data = await resp.json();
          var nodes = data.nodes || [];
          _userNodes = nodes.map(function (n) {
            return {
              id: n.id,
              name: n.name || n.title || n.id,
              source_type: n.group || n.source_type || 'web',
              summary: n.summary || n.description || ''
            };
          });
        }
      } catch (e) {
        console.warn('[kastens] load graph err', e);
        _userNodes = [];
      }
      _userNodesLoaded = true;
      _userNodesFetchedAt = Date.now();
    })();
    try {
      await _userNodesInflight;
    } finally {
      _userNodesInflight = null;
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
