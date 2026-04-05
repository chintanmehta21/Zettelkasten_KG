(function () {
  'use strict';

  var _supabaseClient = null;
  var _session = null;
  var _allNodes = [];

  var avatarBtn;
  var avatarWrap;
  var avatarDropdown;
  var avatarImg;
  var avatarFallback;
  var menuSignout;

  var statTotal;
  var statSources;
  var statLatest;

  var searchInput;
  var sourceFilter;
  var sortFilter;
  var listEl;
  var emptyEl;

  var summaryOverlay;
  var summaryBackdrop;
  var summaryClose;
  var summarySource;
  var summaryDate;
  var summaryTitle;
  var summaryText;
  var summaryTags;

  function resolveDom() {
    avatarBtn = document.getElementById('avatar-btn');
    avatarWrap = document.getElementById('avatar-wrap');
    avatarDropdown = document.getElementById('avatar-dropdown');
    avatarImg = document.getElementById('avatar-img');
    avatarFallback = document.getElementById('avatar-fallback');
    menuSignout = document.getElementById('menu-signout');

    statTotal = document.getElementById('stat-total');
    statSources = document.getElementById('stat-sources');
    statLatest = document.getElementById('stat-latest');

    searchInput = document.getElementById('zettels-search');
    sourceFilter = document.getElementById('source-filter');
    sortFilter = document.getElementById('sort-filter');
    listEl = document.getElementById('zettels-list');
    emptyEl = document.getElementById('zettels-empty');

    summaryOverlay = document.getElementById('summary-overlay');
    summaryBackdrop = document.getElementById('summary-backdrop');
    summaryClose = document.getElementById('summary-close');
    summarySource = document.getElementById('summary-source');
    summaryDate = document.getElementById('summary-date');
    summaryTitle = document.getElementById('summary-title');
    summaryText = document.getElementById('summary-text');
    summaryTags = document.getElementById('summary-tags');
  }

  async function initSupabase() {
    try {
      var resp = await fetch('/api/auth/config');
      var config = await resp.json();
      if (!config.supabase_url || !config.supabase_anon_key) return null;
      return supabase.createClient(config.supabase_url, config.supabase_anon_key);
    } catch (err) {
      console.error('[user_zettels] Supabase init failed:', err);
      return null;
    }
  }

  async function init() {
    resolveDom();
    _supabaseClient = await initSupabase();
    if (!_supabaseClient) {
      window.location.href = '/';
      return;
    }

    var sessionResult = await _supabaseClient.auth.getSession();
    _session = sessionResult.data.session;

    var token = _session ? _session.access_token : '';
    if (!token) {
      window.location.href = '/';
      return;
    }

    var profile = await fetchProfile(token);
    if (!profile) {
      window.location.href = '/';
      return;
    }

    setupAvatar(profile);
    bindEvents();
    await loadZettels(token);
  }

  async function fetchProfile(token) {
    try {
      var resp = await fetch('/api/me', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (err) {
      console.error('[user_zettels] Profile fetch failed:', err);
      return null;
    }
  }

  function setupAvatar(profile) {
    var avatarUrl = profile.avatar_url || '';
    if (avatarUrl && avatarImg) {
      avatarImg.src = avatarUrl;
      avatarImg.onerror = function () {
        avatarImg.classList.add('hidden');
        showAvatarFallback(profile);
      };
      return;
    }
    if (avatarImg) avatarImg.classList.add('hidden');
    showAvatarFallback(profile);
  }

  function showAvatarFallback(profile) {
    if (!avatarFallback) return;
    var display = profile.name || profile.email || 'User';
    avatarFallback.textContent = display.charAt(0).toUpperCase();
    avatarFallback.classList.add('visible');
  }

  async function loadZettels(token) {
    try {
      var resp = await fetch('/api/graph?view=my', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      var graph = await resp.json();
      var nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
      _allNodes = nodes.map(normalizeNode);

      populateSourceFilter(_allNodes);
      updateStats(_allNodes);
      applyFilters();
    } catch (err) {
      console.error('[user_zettels] Failed to load zettels:', err);
      _allNodes = [];
      populateSourceFilter([]);
      updateStats([]);
      applyFilters();
    }
  }

  function normalizeNode(node) {
    var source = normalizeSource(node.group || node.source_type || 'web');
    return {
      id: node.id || '',
      title: node.name || 'Untitled',
      summary: (node.summary || node.description || 'No summary available for this zettel.').trim(),
      tags: Array.isArray(node.tags) ? node.tags : [],
      url: node.url || '',
      date: node.date || '',
      source: source,
      sourceLabel: source === 'substack' ? 'newsletter' : source
    };
  }

  function normalizeSource(value) {
    var raw = (value || 'web').toString().trim().toLowerCase();
    if (raw === 'generic') return 'web';
    if (raw === 'news' || raw === 'newsletter') return 'newsletter';
    if (raw === 'hackernews') return 'web';
    return raw;
  }

  function populateSourceFilter(nodes) {
    if (!sourceFilter) return;

    var selected = sourceFilter.value || 'all';
    var unique = {};
    nodes.forEach(function (node) { unique[node.source] = true; });
    var keys = Object.keys(unique).sort();

    sourceFilter.innerHTML = '<option value="all">All Sources</option>';
    keys.forEach(function (key) {
      var option = document.createElement('option');
      option.value = key;
      option.textContent = titleCase(key);
      sourceFilter.appendChild(option);
    });

    if ([].slice.call(sourceFilter.options).some(function (opt) { return opt.value === selected; })) {
      sourceFilter.value = selected;
    }
  }

  function updateStats(nodes) {
    var total = nodes.length;
    var sources = {};
    var latest = '';

    nodes.forEach(function (node) {
      sources[node.source] = true;
      if ((node.date || '') > latest) latest = node.date;
    });

    if (statTotal) statTotal.textContent = String(total);
    if (statSources) statSources.textContent = String(Object.keys(sources).length);
    if (statLatest) statLatest.textContent = latest ? formatDate(latest) : '-';
  }

  function applyFilters() {
    var q = (searchInput && searchInput.value ? searchInput.value : '').trim().toLowerCase();
    var source = sourceFilter ? sourceFilter.value : 'all';
    var sort = sortFilter ? sortFilter.value : 'newest';

    var filtered = _allNodes.filter(function (node) {
      var sourceMatch = source === 'all' || node.source === source;
      if (!sourceMatch) return false;
      if (!q) return true;

      var haystack = [
        node.title,
        node.summary,
        node.source,
        (node.tags || []).join(' ')
      ].join(' ').toLowerCase();

      return haystack.indexOf(q) !== -1;
    });

    filtered.sort(function (a, b) {
      if (sort === 'oldest') return (a.date || '').localeCompare(b.date || '');
      if (sort === 'title') return a.title.localeCompare(b.title);
      return (b.date || '').localeCompare(a.date || '');
    });

    renderList(filtered);
  }

  function renderList(nodes) {
    if (!listEl || !emptyEl) return;
    listEl.innerHTML = '';

    if (!nodes.length) {
      emptyEl.classList.remove('hidden');
      return;
    }
    emptyEl.classList.add('hidden');

    nodes.forEach(function (node, idx) {
      var card = document.createElement('a');
      card.className = 'zettels-card';
      card.style.animationDelay = String(idx * 0.03) + 's';
      card.href = node.url || '#';
      if (node.url) {
        card.target = '_blank';
        card.rel = 'noopener';
      }

      var safeTitle = escapeHtml(node.title);
      var safeTitleAttr = escapeAttr(node.title);
      var safeSummary = escapeHtml(truncate(node.summary, 220));
      var safeSource = escapeHtml(node.sourceLabel);
      var safeDate = node.date ? '<span class="home-card-date">' + escapeHtml(formatDate(node.date)) + '</span>' : '';

      card.innerHTML =
        '<h2 class="zettels-card-title">' + safeTitle + '</h2>' +
        '<p class="zettels-card-summary">' + safeSummary + '</p>' +
        '<div class="zettels-card-meta">' +
          safeDate +
          '<span class="home-card-source ' + node.source + '">' + safeSource + '</span>' +
          '<button class="home-card-summary-btn" type="button" aria-label="View summary for ' + safeTitleAttr + '">' +
            '<img src="/artifacts/icon-summary.svg" alt="" aria-hidden="true" />' +
            '<span class="tooltip">Summary</span>' +
          '</button>' +
        '</div>';

      card.addEventListener('click', function (e) {
        var summaryBtn = e.target.closest('.home-card-summary-btn');
        if (summaryBtn) {
          e.preventDefault();
          e.stopPropagation();
          openSummary(node);
        }
      });

      listEl.appendChild(card);
    });
  }

  function openSummary(node) {
    if (!summaryOverlay) return;

    summarySource.className = 'zettels-source-badge ' + node.source;
    summarySource.textContent = node.sourceLabel;
    summaryDate.textContent = node.date ? formatDate(node.date) : 'No capture date';
    summaryTitle.textContent = node.title;
    summaryText.textContent = node.summary || 'No summary available for this zettel.';

    summaryTags.innerHTML = '';
    (node.tags || []).forEach(function (tag) {
      var el = document.createElement('span');
      el.className = 'zettels-tag';
      el.textContent = '#' + tag;
      summaryTags.appendChild(el);
    });

    summaryOverlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeSummary() {
    if (!summaryOverlay) return;
    summaryOverlay.classList.add('hidden');
    document.body.style.overflow = '';
  }

  function bindEvents() {
    if (avatarBtn && avatarDropdown) {
      avatarBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        avatarDropdown.classList.toggle('open');
      });
    }

    document.addEventListener('click', function (e) {
      if (avatarDropdown && avatarWrap && !avatarWrap.contains(e.target)) {
        avatarDropdown.classList.remove('open');
      }
    });

    if (searchInput) searchInput.addEventListener('input', applyFilters);
    if (sourceFilter) sourceFilter.addEventListener('change', applyFilters);
    if (sortFilter) sortFilter.addEventListener('change', applyFilters);

    if (menuSignout) {
      menuSignout.addEventListener('click', async function () {
        try {
          if (_supabaseClient) await _supabaseClient.auth.signOut();
        } finally {
          window.location.href = '/';
        }
      });
    }

    if (summaryClose) summaryClose.addEventListener('click', closeSummary);
    if (summaryBackdrop) summaryBackdrop.addEventListener('click', closeSummary);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeSummary();
        if (avatarDropdown) avatarDropdown.classList.remove('open');
      }
    });
  }

  function truncate(value, limit) {
    if (!value || value.length <= limit) return value;
    return value.slice(0, limit - 1).trim() + '…';
  }

  function formatDate(value) {
    var parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: 'short',
      day: '2-digit'
    }).format(parsed);
  }

  function titleCase(value) {
    return value.replace(/[_-]/g, ' ').replace(/\b\w/g, function (ch) { return ch.toUpperCase(); });
  }

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
  }

  function escapeAttr(value) {
    return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
