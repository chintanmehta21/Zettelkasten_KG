(function () {
  'use strict';

  var _supabaseClient = null;
  var _session = null;
  var _token = '';
  var _allNodes = [];
  var _activeSource = 'all';
  var _activeTags = new Set();
  var _activeSort = 'newest';

  var _deleteConfirmId = null;
  var _deleteConfirmTimer = null;
  var _pendingDelete = null;
  var _bodyLockCount = 0;

  var avatarBtn;
  var avatarWrap;
  var avatarDropdown;
  var avatarImg;
  var avatarFallback;
  var menuSignout;
  var menuNexus;

  var statTotal;
  var statSources;
  var statLatest;

  var searchInput;
  var listEl;
  var emptyEl;

  var filtersWrap;
  var filtersBtn;
  var filtersBtnText;
  var filtersMenu;
  var filterParentSource;
  var filterParentTags;
  var submenuSource;
  var submenuTags;
  var filtersClear;
  var sortWrap;
  var sortBtn;
  var sortBtnText;
  var sortMenu;

  var addWrap;
  var addBtn;
  var addDropdown;
  var addForm;
  var addUrlInput;
  var addSubmitBtn;
  var addError;

  var summaryOverlay;
  var summaryBackdrop;
  var summaryClose;
  var summarySource;
  var summaryDate;
  var summaryTitle;
  var summaryText;
  var summaryTags;

  var undoToast;
  var undoText;
  var undoBtn;
  var undoTime;

  function resolveDom() {
    avatarBtn = document.getElementById('avatar-btn');
    avatarWrap = document.getElementById('avatar-wrap');
    avatarDropdown = document.getElementById('avatar-dropdown');
    avatarImg = document.getElementById('avatar-img');
    avatarFallback = document.getElementById('avatar-fallback');
    menuSignout = document.getElementById('menu-signout');
    menuNexus = document.getElementById('menu-nexus');

    statTotal = document.getElementById('stat-total');
    statSources = document.getElementById('stat-sources');
    statLatest = document.getElementById('stat-latest');

    searchInput = document.getElementById('zettels-search');
    listEl = document.getElementById('zettels-list');
    emptyEl = document.getElementById('zettels-empty');

    filtersWrap = document.getElementById('filters-wrap');
    filtersBtn = document.getElementById('filters-btn');
    filtersBtnText = document.getElementById('filters-btn-text');
    filtersMenu = document.getElementById('filters-menu');
    filterParentSource = document.getElementById('filter-parent-source');
    filterParentTags = document.getElementById('filter-parent-tags');
    submenuSource = document.getElementById('submenu-source');
    submenuTags = document.getElementById('submenu-tags');
    filtersClear = document.getElementById('filters-clear');
    sortWrap = document.getElementById('sort-wrap');
    sortBtn = document.getElementById('sort-btn');
    sortBtnText = document.getElementById('sort-btn-text');
    sortMenu = document.getElementById('sort-menu');

    addWrap = document.getElementById('add-zettel-wrap');
    addBtn = document.getElementById('add-zettel-btn');
    addDropdown = document.getElementById('add-zettel-dropdown');
    addForm = document.getElementById('add-zettel-form');
    addUrlInput = document.getElementById('add-url-input');
    addSubmitBtn = document.getElementById('add-submit-btn');
    addError = document.getElementById('add-error');

    summaryOverlay = document.getElementById('summary-overlay');
    summaryBackdrop = document.getElementById('summary-backdrop');
    summaryClose = document.getElementById('summary-close');
    summarySource = document.getElementById('summary-source');
    summaryDate = document.getElementById('summary-date');
    summaryTitle = document.getElementById('summary-title');
    summaryText = document.getElementById('summary-text');
    summaryTags = document.getElementById('summary-tags');

    undoToast = document.getElementById('undo-toast');
    undoText = document.getElementById('undo-text');
    undoBtn = document.getElementById('undo-btn');
    undoTime = document.getElementById('undo-time');
  }

  function setBodyScrollLocked(locked) {
    if (locked) {
      _bodyLockCount += 1;
    } else {
      _bodyLockCount = Math.max(0, _bodyLockCount - 1);
    }
    document.body.style.overflow = _bodyLockCount > 0 ? 'hidden' : '';
  }

  function toSafeHttpUrl(rawUrl) {
    var value = String(rawUrl || '').trim();
    if (!value) return '';
    try {
      var parsed = new URL(value, window.location.origin);
      var protocol = parsed.protocol.toLowerCase();
      if (protocol !== 'http:' && protocol !== 'https:') return '';
      return parsed.href;
    } catch (err) {
      void err;
      return '';
    }
  }

  async function initSupabase() {
    try {
      var resp = await fetch('/api/auth/config');
      var config = await resp.json();
      if (!config.supabase_url || !config.supabase_anon_key) return null;
      return supabase.createClient(config.supabase_url, config.supabase_anon_key, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          storage: window.localStorage,
          storageKey: 'zk-auth-token',
        },
      });
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
    _token = _session ? _session.access_token : '';

    if (!_token) {
      window.location.href = '/';
      return;
    }

    var profile = await fetchProfile(_token);
    if (!profile) {
      window.location.href = '/';
      return;
    }

    setupAvatar(profile);
    bindEvents();
    await loadZettels();
  }

  async function fetchProfile(token) {
    try {
      var resp = await fetch('/api/me', {
        headers: { Authorization: 'Bearer ' + token }
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
    var cacheKey = 'zk-avatar-url';

    // If server has a valid avatar, use it and cache locally
    if (avatarUrl && avatarUrl.includes('/artifacts/avatars/')) {
      try { localStorage.setItem(cacheKey, avatarUrl); } catch (_) {}
    } else {
      // Fall back to cached avatar from localStorage
      try { avatarUrl = localStorage.getItem(cacheKey) || ''; } catch (_) {}
    }

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

  async function loadZettels() {
    try {
      var resp = await fetch('/api/graph?view=my', {
        headers: { Authorization: 'Bearer ' + _token }
      });
      var graph = await resp.json();
      var nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
      _allNodes = nodes.map(normalizeNode);
    } catch (err) {
      console.error('[user_zettels] Failed to load zettels:', err);
      _allNodes = [];
    }

    rebuildFilterMenus();
    updateStats(_allNodes);
    applyFilters();
  }

  function normalizeNode(node) {
    var source = normalizeSource(node.group || node.source_type || 'web');
    var summaryParts = extractSummaryParts(node.summary || '');
    if (node.description) {
      var descriptionParts = extractSummaryParts(node.description || '');
      if (!summaryParts.brief || summaryParts.brief === summaryParts.detailed) {
        summaryParts.brief = descriptionParts.brief || summaryParts.brief;
      }
      if (!summaryParts.detailed || summaryParts.detailed === summaryParts.brief) {
        summaryParts.detailed = descriptionParts.detailed || summaryParts.detailed;
      }
    }
    var cleanTags = (Array.isArray(node.tags) ? node.tags : [])
      .map(normalizeTag)
      .filter(Boolean);

    return {
      id: node.id || createLocalNodeId(node.name || node.title || 'zettel'),
      title: (node.name || node.title || 'Untitled').trim(),
      summary: summaryParts.brief,
      briefSummary: summaryParts.brief,
      detailedSummary: summaryParts.detailed,
      tags: uniqueStrings(cleanTags),
      normalizedTags: uniqueStrings(cleanTags.map(function (tag) { return tag.toLowerCase(); })),
      url: (node.url || '').trim(),
      date: normalizeCaptureDate(node.date || node.node_date || node.captured_at || node.created_at || ''),
      source: source,
      sourceLabel: sourceLabel(source),
      summaryLength: summaryParts.detailed.length || summaryParts.brief.length
    };
  }

  function normalizeSource(value) {
    var raw = (value || 'web').toString().trim().toLowerCase();
    if (raw === 'generic' || raw === 'hackernews') return 'web';
    if (raw === 'news' || raw === 'newsletter') return 'newsletter';
    if (raw === 'yt') return 'youtube';
    if (raw === 'gh') return 'github';
    if (raw === 'rd') return 'reddit';
    if (raw === 'ss') return 'substack';
    if (raw === 'md') return 'medium';
    return raw || 'web';
  }

  function sourceLabel(source) {
    if (source === 'substack') return 'Newsletter';
    if (source === 'web') return 'Web';
    return titleCase(source);
  }

  function normalizeTag(tag) {
    var clean = (tag || '').toString().trim();
    if (!clean) return '';
    var slashIndex = clean.indexOf('/');
    if (slashIndex >= 0) clean = clean.slice(slashIndex + 1);
    return clean.trim();
  }

  function rebuildFilterMenus() {
    renderSourceFilterMenu();
    renderTagFilterMenu();
    updateFiltersButtonText();
    syncSortMenuOptions();
  }

  function renderSourceFilterMenu() {
    if (!submenuSource) return;

    submenuSource.innerHTML = '';
    submenuSource.appendChild(createSourceOption('all', 'All Sources'));

    uniqueSources(_allNodes).forEach(function (src) {
      submenuSource.appendChild(createSourceOption(src, sourceLabel(src)));
    });
  }

  function renderTagFilterMenu() {
    if (!submenuTags) return;
    submenuTags.innerHTML = '';

    var tags = uniqueTags(_allNodes);
    if (!tags.length) {
      var empty = document.createElement('div');
      empty.className = 'zettels-filter-sub-option';
      empty.textContent = 'No tags yet';
      empty.style.cursor = 'default';
      empty.style.opacity = '0.65';
      submenuTags.appendChild(empty);
      return;
    }

    tags.forEach(function (tag) {
      submenuTags.appendChild(createTagOption(tag));
    });
  }

  function createSourceOption(value, label) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'zettels-filter-sub-option' + (_activeSource === value ? ' selected' : '');
    btn.textContent = label;
    btn.setAttribute('role', 'menuitemradio');
    btn.setAttribute('aria-checked', _activeSource === value ? 'true' : 'false');
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      _activeSource = value;
      clearDeleteConfirmState();
      renderSourceFilterMenu();
      updateFiltersButtonText();
      applyFilters();
    });
    return btn;
  }

  function createTagOption(tag) {
    var normalized = tag.toLowerCase();
    var isSelected = _activeTags.has(normalized);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'zettels-tag-option' + (isSelected ? ' selected' : '');
    btn.setAttribute('role', 'menuitemcheckbox');
    btn.setAttribute('aria-checked', isSelected ? 'true' : 'false');
    btn.innerHTML =
      '<span class="zettels-tag-check" aria-hidden="true"></span>' +
      '<span>#' + escapeHtml(tag) + '</span>';

    btn.addEventListener('click', function (e) {
      e.preventDefault();
      if (_activeTags.has(normalized)) _activeTags.delete(normalized);
      else _activeTags.add(normalized);
      clearDeleteConfirmState();
      renderTagFilterMenu();
      updateFiltersButtonText();
      applyFilters();
    });

    return btn;
  }

  function uniqueSources(nodes) {
    var seen = {};
    var list = [];
    nodes.forEach(function (node) {
      if (node.source && !seen[node.source]) {
        seen[node.source] = true;
        list.push(node.source);
      }
    });
    list.sort(function (a, b) { return sourceLabel(a).localeCompare(sourceLabel(b)); });
    return list;
  }

  function uniqueTags(nodes) {
    var seen = {};
    var list = [];
    nodes.forEach(function (node) {
      (node.tags || []).forEach(function (tag) {
        var normalized = tag.toLowerCase();
        if (normalized && !seen[normalized]) {
          seen[normalized] = true;
          list.push(tag);
        }
      });
    });
    list.sort(function (a, b) { return a.localeCompare(b); });
    return list;
  }

  function updateFiltersButtonText() {
    if (!filtersBtnText) return;
    var parts = [];
    if (_activeSource !== 'all') {
      parts.push('Source: ' + sourceLabel(_activeSource));
    }
    if (_activeTags.size > 0) {
      parts.push('Tags: ' + String(_activeTags.size));
    }
    filtersBtnText.textContent = parts.length ? parts.join(' | ') : 'All Filters';
  }

  function updateSortButtonText() {
    if (!sortBtnText || !sortMenu) return;
    var option = sortMenu.querySelector('.sort-option[data-sort="' + _activeSort + '"]');
    sortBtnText.textContent = option ? option.textContent : 'Newest First';
  }

  function syncSortMenuOptions() {
    if (!sortMenu) return;
    var options = sortMenu.querySelectorAll('.sort-option');
    options.forEach(function (opt) {
      var selected = opt.getAttribute('data-sort') === _activeSort;
      opt.classList.toggle('selected', selected);
      opt.setAttribute('aria-checked', selected ? 'true' : 'false');
    });
    updateSortButtonText();
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

  function applyFilters(options) {
    var opts = options || {};
    var restoreId = opts.restoreId || '';
    var query = ((searchInput && searchInput.value) || '').trim().toLowerCase();
    var sortMode = _activeSort || 'newest';

    var filtered = _allNodes.filter(function (node) {
      if (_activeSource !== 'all' && node.source !== _activeSource) return false;

      if (_activeTags.size) {
        var matchesAllTags = true;
        _activeTags.forEach(function (selectedTag) {
          if (node.normalizedTags.indexOf(selectedTag) === -1) matchesAllTags = false;
        });
        if (!matchesAllTags) return false;
      }

      if (!query) return true;
      var haystack = [
        node.title,
        node.briefSummary,
        node.detailedSummary,
        node.source,
        node.sourceLabel,
        (node.tags || []).join(' ')
      ].join(' ').toLowerCase();
      return haystack.indexOf(query) !== -1;
    });

    filtered.sort(function (a, b) {
      if (sortMode === 'oldest') return (a.date || '').localeCompare(b.date || '');
      if (sortMode === 'title') return a.title.localeCompare(b.title);
      if (sortMode === 'summary_long') return b.summaryLength - a.summaryLength;
      if (sortMode === 'summary_short') return a.summaryLength - b.summaryLength;
      return (b.date || '').localeCompare(a.date || '');
    });

    renderList(filtered, { restoreId: restoreId });
  }

  function renderList(nodes, options) {
    if (!listEl || !emptyEl) return;

    var opts = options || {};
    listEl.innerHTML = '';

    if (!nodes.length) {
      emptyEl.classList.remove('hidden');
      return;
    }

    emptyEl.classList.add('hidden');

    nodes.forEach(function (node, idx) {
      var card = createCard(node, idx, opts.restoreId === node.id);
      listEl.appendChild(card);
    });
  }

  function createCard(node, idx, shouldRestoreAnimate) {
    var card = document.createElement('article');
    card.className = 'zettels-card' + (shouldRestoreAnimate ? ' is-restoring' : '');
    card.style.animationDelay = String(idx * 0.03) + 's';
    card.tabIndex = 0;
    card.setAttribute('role', 'link');
    var safeUrl = toSafeHttpUrl(node.url);
    card.setAttribute('aria-label', safeUrl ? 'Open ' + node.title : node.title);
    card.dataset.nodeId = node.id;

    var dateBadge = node.date
      ? '<span class="home-card-date">' + escapeHtml(formatDate(node.date)) + '</span>'
      : '';

    card.innerHTML =
      '<h2 class="zettels-card-title">' + escapeHtml(node.title) + '</h2>' +
      '<p class="zettels-card-summary">' + escapeHtml(truncate(node.briefSummary, 240)) + '</p>' +
      '<div class="zettels-card-meta">' +
        dateBadge +
        '<span class="home-card-source ' + node.source + '">' + escapeHtml(node.sourceLabel) + '</span>' +
        '<div class="zettels-card-actions">' +
          '<button class="home-card-summary-btn" type="button" aria-label="View summary">' +
            '<img src="/artifacts/icon-summary.svg" alt="" aria-hidden="true" />' +
            '<span class="tooltip">Summary</span>' +
          '</button>' +
          '<button class="zettels-delete-btn" type="button" aria-label="Delete zettel">' +
            '<img class="icon-trash icon-trash-img" src="/artifacts/icon-trash-bootstrap.svg" alt="" aria-hidden="true" />' +
            '<svg class="icon-check" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
              '<path d="M5 12.5L9.2 16.7L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>' +
            '</svg>' +
            '<span class="tooltip">Delete</span>' +
          '</button>' +
          '<span class="zettels-delete-cloud">Are you sure?</span>' +
        '</div>' +
      '</div>';

    card.addEventListener('click', function (e) {
      var summaryBtn = e.target.closest('.home-card-summary-btn');
      if (summaryBtn) {
        e.preventDefault();
        e.stopPropagation();
        openSummary(node);
        return;
      }

      var deleteBtn = e.target.closest('.zettels-delete-btn');
      if (deleteBtn) {
        e.preventDefault();
        e.stopPropagation();
        handleDeleteClick(node, card, deleteBtn);
        return;
      }

      if (safeUrl) {
        window.open(safeUrl, '_blank', 'noopener');
      }
    });

    card.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      if (!safeUrl) return;
      e.preventDefault();
      window.open(safeUrl, '_blank', 'noopener');
    });

    return card;
  }

  function handleDeleteClick(node, cardEl, buttonEl) {
    if (_pendingDelete && _pendingDelete.node.id !== node.id) return;

    if (_deleteConfirmId !== node.id) {
      clearDeleteConfirmState();
      _deleteConfirmId = node.id;
      cardEl.classList.add('delete-confirm');
      if (buttonEl) buttonEl.classList.add('confirm');
      _deleteConfirmTimer = window.setTimeout(clearDeleteConfirmState, 2600);
      return;
    }

    clearDeleteConfirmState();
    startDeleteFlow(node, cardEl);
  }

  function clearDeleteConfirmState() {
    _deleteConfirmId = null;
    if (_deleteConfirmTimer) {
      window.clearTimeout(_deleteConfirmTimer);
      _deleteConfirmTimer = null;
    }

    var current = listEl ? listEl.querySelector('.zettels-card.delete-confirm') : null;
    if (current) current.classList.remove('delete-confirm');
    if (listEl) {
      var btn = listEl.querySelector('.zettels-delete-btn.confirm');
      if (btn) btn.classList.remove('confirm');
    }
  }

  function startDeleteFlow(node, cardEl) {
    if (_pendingDelete) return;

    var sourceIndex = findNodeIndexById(node.id);
    if (sourceIndex < 0) return;

    _allNodes.splice(sourceIndex, 1);
    rebuildFilterMenus();
    updateStats(_allNodes);

    cardEl.classList.add('is-removing');
    window.setTimeout(function () {
      cardEl.classList.add('is-collapsed');
    }, 680);

    window.setTimeout(function () {
      applyFilters();
    }, 820);

    _pendingDelete = {
      node: node,
      sourceIndex: sourceIndex,
      expiresAt: Date.now() + 5000,
      timeoutId: null,
      intervalId: null
    };

    showUndoToast('Zettel deleted.');

    _pendingDelete.intervalId = window.setInterval(function () {
      if (!_pendingDelete) return;
      var secondsLeft = Math.max(0, Math.ceil((_pendingDelete.expiresAt - Date.now()) / 1000));
      if (undoTime) undoTime.textContent = secondsLeft + 's';
    }, 200);

    _pendingDelete.timeoutId = window.setTimeout(function () {
      finalizePendingDelete();
    }, 5000);
  }

  function showUndoToast(message) {
    if (!undoToast) return;
    if (undoText) undoText.textContent = message;
    if (undoBtn) undoBtn.classList.remove('hidden');
    if (undoTime) undoTime.classList.remove('hidden');
    if (undoTime) undoTime.textContent = '5s';
    undoToast.classList.remove('hidden');
  }

  function hideUndoToast() {
    if (!undoToast) return;
    undoToast.classList.add('hidden');
  }

  function handleUndoDelete() {
    if (!_pendingDelete) return;
    var pending = _pendingDelete;
    clearPendingDeleteTimers();
    _pendingDelete = null;
    hideUndoToast();

    restoreDeletedNode(pending.node, pending.sourceIndex);
  }

  async function finalizePendingDelete() {
    if (!_pendingDelete) return;
    var pending = _pendingDelete;
    clearPendingDeleteTimers();
    _pendingDelete = null;
    hideUndoToast();

    try {
      var resp = await fetch('/api/zettels/' + encodeURIComponent(pending.node.id), {
        method: 'DELETE',
        headers: {
          Authorization: 'Bearer ' + _token
        }
      });

      if (!resp.ok) {
        var detail = 'Delete failed';
        try {
          var body = await resp.json();
          detail = body.detail || detail;
        } catch (parseErr) {
          void parseErr;
        }
        throw new Error(detail);
      }
    } catch (err) {
      console.error('[user_zettels] Delete failed:', err);
      restoreDeletedNode(pending.node, pending.sourceIndex);
      showTransientToast('Delete failed. Restored.');
    }
  }

  function restoreDeletedNode(node, sourceIndex) {
    var insertAt = Math.max(0, Math.min(sourceIndex, _allNodes.length));
    _allNodes.splice(insertAt, 0, node);
    rebuildFilterMenus();
    updateStats(_allNodes);
    applyFilters({ restoreId: node.id });
  }

  function clearPendingDeleteTimers() {
    if (!_pendingDelete) return;
    if (_pendingDelete.timeoutId) window.clearTimeout(_pendingDelete.timeoutId);
    if (_pendingDelete.intervalId) window.clearInterval(_pendingDelete.intervalId);
  }

  function showTransientToast(message) {
    if (!undoToast) return;
    if (undoText) undoText.textContent = message;
    if (undoBtn) undoBtn.classList.add('hidden');
    if (undoTime) undoTime.classList.add('hidden');
    undoToast.classList.remove('hidden');
    window.setTimeout(function () {
      undoToast.classList.add('hidden');
      if (undoBtn) undoBtn.classList.remove('hidden');
      if (undoTime) undoTime.classList.remove('hidden');
    }, 2200);
  }

  async function addZettel(url) {
    if (addError) addError.textContent = '';
    if (addSubmitBtn) addSubmitBtn.disabled = true;
    clearDeleteConfirmState();

    var dropdownRect = addDropdown ? addDropdown.getBoundingClientRect() : null;
    var targetSlot = createInsertionSlot();
    var spacer = targetSlot.spacer;
    var skeleton = null;

    await sleep(500);

    skeleton = createSkeletonCard();
    if (spacer && spacer.parentNode) {
      spacer.parentNode.replaceChild(skeleton, spacer);
    } else if (listEl) {
      listEl.insertBefore(skeleton, listEl.firstChild);
    }

    var apiPromise = fetch('/api/summarize', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + _token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ url: url })
    });

    if (addUrlInput) addUrlInput.value = '';

    if (dropdownRect && addDropdown && skeleton) {
      await shatterElement(addDropdown, skeleton.getBoundingClientRect(), skeleton);
    } else if (addDropdown) {
      addDropdown.classList.remove('open');
    }

    try {
      var resp = await apiPromise;
      if (!resp.ok) {
        var errBody = await resp.json();
        throw new Error(errBody.detail || 'Failed to process URL');
      }

      var result = await resp.json();
      var newNode = normalizeNode({
        id: result.node_id || buildNodeId(result.title || 'untitled', result.source_type || 'web'),
        name: result.title || 'Untitled',
        summary: result.summary || result.brief_summary || '',
        description: result.brief_summary || '',
        tags: Array.isArray(result.tags) ? result.tags : [],
        url: result.source_url || url,
        group: result.source_type || 'web',
        date: result.captured_at || new Date().toISOString().slice(0, 10)
      });

      upsertNodeAtTop(newNode);
      rebuildFilterMenus();
      updateStats(_allNodes);

      var canInsertAtTop = shouldRenderNewNodeAtTop(newNode);
      if (canInsertAtTop && skeleton && skeleton.parentNode) {
        var newCard = createCard(newNode, 0, false);
        newCard.classList.add('is-new');
        skeleton.parentNode.replaceChild(newCard, skeleton);
        emptyEl.classList.add('hidden');
        window.setTimeout(function () {
          newCard.classList.remove('is-new');
        }, 450);
      } else {
        if (skeleton && skeleton.parentNode) skeleton.parentNode.removeChild(skeleton);
        if (spacer && spacer.parentNode) spacer.parentNode.removeChild(spacer);
        applyFilters();
      }
    } catch (err) {
      console.error('[user_zettels] Add failed:', err);
      if (skeleton && skeleton.parentNode) skeleton.parentNode.removeChild(skeleton);
      if (spacer && spacer.parentNode) spacer.parentNode.removeChild(spacer);
      applyFilters();

      if (addError) addError.textContent = err.message || 'Failed to add zettel';
      if (addDropdown) addDropdown.classList.add('open');
      if (addUrlInput) addUrlInput.focus();
    } finally {
      if (addSubmitBtn) addSubmitBtn.disabled = false;
    }
  }

  function createInsertionSlot() {
    if (emptyEl) emptyEl.classList.add('hidden');
    if (!listEl) return { spacer: null };

    var cardHeight = measureCardHeight();

    var spacer = document.createElement('div');
    spacer.className = 'zettels-card-spacer';
    spacer.style.height = '0';
    spacer.style.overflow = 'hidden';
    spacer.style.transition = 'height 1.2s cubic-bezier(0.25, 0.1, 0.25, 1)';
    spacer.style.border = 'none';
    spacer.style.background = 'transparent';
    spacer.style.padding = '0';
    spacer.style.margin = '0';

    listEl.insertBefore(spacer, listEl.firstChild);
    requestAnimationFrame(function () {
      spacer.style.height = Math.round(cardHeight * 0.9) + 'px';
    });

    return { spacer: spacer };
  }

  function measureCardHeight() {
    if (!listEl) return 104;
    var firstCard = listEl.querySelector('.zettels-card');
    if (firstCard) return firstCard.getBoundingClientRect().height || 104;

    var measure = createSkeletonCard();
    measure.style.visibility = 'hidden';
    measure.style.position = 'absolute';
    listEl.appendChild(measure);
    var height = measure.getBoundingClientRect().height || 104;
    listEl.removeChild(measure);
    return height;
  }

  function createSkeletonCard() {
    var skeleton = document.createElement('article');
    skeleton.className = 'zettels-card zettels-card-skeleton';
    skeleton.style.opacity = '0';
    skeleton.style.transition = 'opacity 0.4s ease';
    skeleton.innerHTML =
      '<div class="skeleton-line skeleton-title"></div>' +
      '<div class="skeleton-line skeleton-body"></div>' +
      '<div class="zettels-card-meta">' +
        '<div class="skeleton-line skeleton-date"></div>' +
        '<div class="skeleton-line skeleton-source"></div>' +
      '</div>';
    return skeleton;
  }

  function shouldRenderNewNodeAtTop(node) {
    var query = ((searchInput && searchInput.value) || '').trim().toLowerCase();
    var sortMode = _activeSort || 'newest';
    if (sortMode !== 'newest') return false;
    if (_activeSource !== 'all' && node.source !== _activeSource) return false;

    if (_activeTags.size) {
      var matches = true;
      _activeTags.forEach(function (tag) {
        if (node.normalizedTags.indexOf(tag) === -1) matches = false;
      });
      if (!matches) return false;
    }

    if (!query) return true;
    var haystack = [
      node.title,
      node.briefSummary,
      node.detailedSummary,
      node.source,
      node.sourceLabel,
      (node.tags || []).join(' ')
    ].join(' ').toLowerCase();
    return haystack.indexOf(query) !== -1;
  }

  function upsertNodeAtTop(node) {
    var idx = findNodeIndexById(node.id);
    if (idx >= 0) _allNodes.splice(idx, 1);
    _allNodes.unshift(node);
  }

  function buildNodeId(title, sourceType) {
    var source = normalizeSource(sourceType);
    var prefixMap = {
      youtube: 'yt',
      reddit: 'rd',
      github: 'gh',
      substack: 'ss',
      newsletter: 'ss',
      medium: 'md',
      web: 'web'
    };
    var prefix = prefixMap[source] || 'web';
    var slug = slugify(title || 'untitled', 24);
    return prefix + '-' + slug;
  }

  function slugify(text, maxLen) {
    var slug = (text || '')
      .toString()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
    return (slug || 'untitled').slice(0, maxLen || 24).replace(/-+$/g, '');
  }

  function shatterElement(sourceEl, targetRect, revealEl) {
    return new Promise(function (resolve) {
      var rect = sourceEl.getBoundingClientRect();
      var container = document.createElement('div');
      container.style.cssText = 'position:fixed;inset:0;z-index:600;pointer-events:none;overflow:hidden;';
      document.body.appendChild(container);

      var cols = 10;
      var rows = 4;
      var shardW = rect.width / cols;
      var shardH = rect.height / rows;
      var shards = [];
      var colors = [
        'hsla(172, 66%, 50%, 0.7)',
        'hsla(172, 50%, 40%, 0.6)',
        'hsla(172, 40%, 35%, 0.5)',
        'hsla(190, 50%, 30%, 0.5)',
        'hsla(210, 30%, 25%, 0.5)',
        'hsla(172, 66%, 50%, 0.4)'
      ];

      var tCols = 10;
      var tRows = 4;
      var tShardW = targetRect.width / tCols;
      var tShardH = targetRect.height / tRows;

      for (var r = 0; r < rows; r++) {
        for (var c = 0; c < cols; c++) {
          var shard = document.createElement('div');
          var startX = rect.left + c * shardW;
          var startY = rect.top + r * shardH;

          shard.style.cssText =
            'position:fixed;' +
            'left:' + startX + 'px;top:' + startY + 'px;' +
            'width:' + shardW + 'px;height:' + shardH + 'px;' +
            'background:' + colors[Math.floor(Math.random() * colors.length)] + ';' +
            'border:0.5px solid hsla(172, 66%, 50%, 0.12);' +
            'border-radius:' + (Math.random() * 2) + 'px;' +
            'transition:all 0.55s cubic-bezier(0.25, 0.46, 0.45, 0.94);' +
            'box-shadow:0 0 3px hsla(172, 66%, 50%, 0.15);' +
            'opacity:1;';

          container.appendChild(shard);

          var idx = r * cols + c;
          var tR = Math.floor(idx / tCols) % tRows;
          var tC = idx % tCols;

          shards.push({
            el: shard,
            explodeX: startX + (Math.random() - 0.5) * 280,
            explodeY: startY + (Math.random() - 0.5) * 180 - 60,
            explodeRot: (Math.random() - 0.5) * 300,
            targetX: targetRect.left + tC * tShardW,
            targetY: targetRect.top + tR * tShardH,
            targetW: tShardW,
            targetH: tShardH
          });
        }
      }

      sourceEl.classList.remove('open');

      requestAnimationFrame(function () {
        shards.forEach(function (shardState) {
          shardState.el.style.left = shardState.explodeX + 'px';
          shardState.el.style.top = shardState.explodeY + 'px';
          shardState.el.style.transform = 'rotate(' + shardState.explodeRot + 'deg) scale(' + (0.6 + Math.random() * 0.6) + ')';
          shardState.el.style.opacity = '0.85';
        });
      });

      setTimeout(function () {
        shards.forEach(function (shardState, idx) {
          var delay = (idx % 5) * 0.02;
          shardState.el.style.transition = 'all 0.55s cubic-bezier(0.34, 1.56, 0.64, 1) ' + delay + 's';
          shardState.el.style.left = shardState.targetX + 'px';
          shardState.el.style.top = shardState.targetY + 'px';
          shardState.el.style.width = shardState.targetW + 'px';
          shardState.el.style.height = shardState.targetH + 'px';
          shardState.el.style.transform = 'rotate(0deg) scale(1)';
          shardState.el.style.opacity = '0.7';
          shardState.el.style.borderRadius = '1px';
        });
        if (revealEl) {
          setTimeout(function () {
            revealEl.style.opacity = '1';
          }, 300);
        }
      }, 600);

      setTimeout(function () {
        shards.forEach(function (shardState) {
          shardState.el.style.transition = 'all 0.35s ease-out';
          shardState.el.style.opacity = '0';
          shardState.el.style.transform = 'scale(0.95)';
        });
      }, 1200);

      setTimeout(function () {
        container.remove();
        resolve();
      }, 1550);
    });
  }

  function openSummary(node) {
    if (!summaryOverlay || !summarySource || !summaryDate || !summaryTitle || !summaryText || !summaryTags) return;

    summarySource.className = 'zettels-source-badge ' + node.source;
    summarySource.textContent = node.sourceLabel;
    summaryDate.textContent = node.date ? formatDate(node.date) : 'No capture date';
    summaryTitle.textContent = node.title;
    summaryText.textContent = node.detailedSummary || node.briefSummary || 'No summary available for this zettel.';

    summaryTags.innerHTML = '';
    (node.tags || []).forEach(function (tag) {
      var el = document.createElement('span');
      el.className = 'zettels-tag';
      el.textContent = '#' + tag;
      summaryTags.appendChild(el);
    });

    summaryOverlay.classList.remove('hidden');
    setBodyScrollLocked(true);
  }

  function closeSummary() {
    if (!summaryOverlay) return;
    summaryOverlay.classList.add('hidden');
    setBodyScrollLocked(false);
  }

  function openFiltersMenu() {
    if (!filtersWrap || !filtersBtn) return;
    closeSortMenu();
    filtersWrap.classList.add('open');
    filtersBtn.setAttribute('aria-expanded', 'true');
    openSubmenu('source');
  }

  function closeFiltersMenu() {
    if (!filtersWrap || !filtersBtn) return;
    filtersWrap.classList.remove('open');
    filtersBtn.setAttribute('aria-expanded', 'false');
    closeSubmenus();
  }

  function toggleFiltersMenu() {
    if (!filtersWrap) return;
    if (filtersWrap.classList.contains('open')) closeFiltersMenu();
    else openFiltersMenu();
  }

  function openSortMenu() {
    if (!sortWrap || !sortBtn) return;
    closeFiltersMenu();
    sortWrap.classList.add('open');
    sortBtn.setAttribute('aria-expanded', 'true');
  }

  function closeSortMenu() {
    if (!sortWrap || !sortBtn) return;
    sortWrap.classList.remove('open');
    sortBtn.setAttribute('aria-expanded', 'false');
  }

  function toggleSortMenu() {
    if (!sortWrap) return;
    if (sortWrap.classList.contains('open')) closeSortMenu();
    else openSortMenu();
  }

  function openSubmenu(name) {
    closeSubmenus();

    if (name === 'source' && submenuSource) {
      submenuSource.classList.add('open');
      if (filterParentSource) filterParentSource.classList.add('active');
    }

    if (name === 'tags' && submenuTags) {
      submenuTags.classList.add('open');
      if (filterParentTags) filterParentTags.classList.add('active');
    }
  }

  function closeSubmenus() {
    if (submenuSource) submenuSource.classList.remove('open');
    if (submenuTags) submenuTags.classList.remove('open');
    if (filterParentSource) filterParentSource.classList.remove('active');
    if (filterParentTags) filterParentTags.classList.remove('active');
  }

  function bindEvents() {
    if (avatarBtn && avatarDropdown) {
      avatarBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        avatarDropdown.classList.toggle('open');
      });
    }

    if (filtersBtn) {
      filtersBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        toggleFiltersMenu();
      });
    }

    if (sortBtn) {
      sortBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        toggleSortMenu();
      });
    }

    if (filterParentSource) {
      filterParentSource.addEventListener('mouseenter', function () { openSubmenu('source'); });
      filterParentSource.addEventListener('focus', function () { openSubmenu('source'); });
      filterParentSource.addEventListener('click', function (e) {
        e.preventDefault();
        openSubmenu('source');
      });
    }

    if (filterParentTags) {
      filterParentTags.addEventListener('mouseenter', function () { openSubmenu('tags'); });
      filterParentTags.addEventListener('focus', function () { openSubmenu('tags'); });
      filterParentTags.addEventListener('click', function (e) {
        e.preventDefault();
        openSubmenu('tags');
      });
    }

    if (filtersClear) {
      filtersClear.addEventListener('click', function () {
        _activeSource = 'all';
        _activeTags.clear();
        clearDeleteConfirmState();
        rebuildFilterMenus();
        applyFilters();
      });
    }

    if (sortMenu) {
      sortMenu.addEventListener('click', function (e) {
        var option = e.target.closest('.sort-option');
        if (!option) return;
        e.preventDefault();
        var nextSort = option.getAttribute('data-sort') || 'newest';
        if (_activeSort === nextSort) {
          closeSortMenu();
          return;
        }
        _activeSort = nextSort;
        syncSortMenuOptions();
        clearDeleteConfirmState();
        applyFilters();
        closeSortMenu();
      });
    }

    if (addBtn) {
      addBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        if (!addDropdown) return;
        addDropdown.classList.toggle('open');
        if (addDropdown.classList.contains('open') && addUrlInput) addUrlInput.focus();
      });
    }

    if (addForm) {
      addForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var url = addUrlInput ? addUrlInput.value.trim() : '';
        if (!url) return;
        addZettel(url);
      });
    }

    if (searchInput) searchInput.addEventListener('input', applyFilters);

    if (menuSignout) {
      menuSignout.addEventListener('click', async function () {
        try {
          if (_supabaseClient) await _supabaseClient.auth.signOut();
        } finally {
          window.location.href = '/';
        }
      });
    }

    if (menuNexus) {
      menuNexus.addEventListener('click', function () {
        if (avatarDropdown) avatarDropdown.classList.remove('open');
      });
    }

    if (undoBtn) undoBtn.addEventListener('click', handleUndoDelete);
    if (summaryClose) summaryClose.addEventListener('click', closeSummary);
    if (summaryBackdrop) summaryBackdrop.addEventListener('click', closeSummary);

    document.addEventListener('click', function (e) {
      if (avatarDropdown && avatarWrap && !avatarWrap.contains(e.target)) {
        avatarDropdown.classList.remove('open');
      }
      if (filtersWrap && !filtersWrap.contains(e.target)) {
        closeFiltersMenu();
      }
      if (sortWrap && !sortWrap.contains(e.target)) {
        closeSortMenu();
      }
      if (addDropdown && addWrap && !addWrap.contains(e.target)) {
        addDropdown.classList.remove('open');
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      closeSummary();
      clearDeleteConfirmState();
      if (avatarDropdown) avatarDropdown.classList.remove('open');
      closeFiltersMenu();
      closeSortMenu();
      if (addDropdown) addDropdown.classList.remove('open');
    });
  }

  function findNodeIndexById(nodeId) {
    for (var i = 0; i < _allNodes.length; i++) {
      if (_allNodes[i].id === nodeId) return i;
    }
    return -1;
  }

  function uniqueStrings(values) {
    var seen = {};
    var out = [];
    values.forEach(function (value) {
      if (!value) return;
      if (!seen[value]) {
        seen[value] = true;
        out.push(value);
      }
    });
    return out;
  }

  function createLocalNodeId(seed) {
    return 'local-' + slugify(seed || 'zettel', 20) + '-' + String(Date.now()).slice(-6);
  }

  function extractSummaryParts(rawSummary) {
    var rawInput = rawSummary == null ? '' : String(rawSummary);
    var rawText = normalizeSummaryText(rawInput);
    var parsed = tryParseSummaryObject(rawInput);

    if (parsed) {
      var briefFromParsed = normalizeSummaryText(
        parsed.brief_summary || parsed.briefSummary || parsed.one_line_summary || parsed.summary || ''
      );
      var detailedFromParsed = normalizeSummaryText(
        parsed.detailed_summary || parsed.detailedSummary || parsed.summary || ''
      );

      var resolvedBrief = briefFromParsed || detailedFromParsed;
      var resolvedDetailed = detailedFromParsed || briefFromParsed;
      if (resolvedBrief || resolvedDetailed) {
        return {
          brief: resolvedBrief || 'No summary available for this zettel.',
          detailed: resolvedDetailed || resolvedBrief || 'No summary available for this zettel.'
        };
      }
    }

    var fallback = rawText || 'No summary available for this zettel.';
    return { brief: fallback, detailed: fallback };
  }

  function tryParseSummaryObject(rawText) {
    var cleaned = String(rawText || '')
      .replace(/\r\n/g, '\n')
      .trim();
    if (!cleaned) return null;

    cleaned = cleaned
      .replace(/^```(?:json)?/i, '')
      .replace(/```$/i, '')
      .replace(/^json\s*/i, '')
      .trim();

    var candidates = [cleaned];
    var start = cleaned.indexOf('{');
    var end = cleaned.lastIndexOf('}');
    if (start !== -1 && end > start) {
      candidates.push(cleaned.slice(start, end + 1));
    }

    for (var i = 0; i < candidates.length; i++) {
      var candidate = candidates[i].trim();
      if (!candidate) continue;
      try {
        var parsed = JSON.parse(candidate);
        if (parsed && typeof parsed === 'object') return parsed;
        if (typeof parsed === 'string') {
          var nested = JSON.parse(parsed);
          if (nested && typeof nested === 'object') return nested;
        }
      } catch (err) {
        void err;
      }
    }

    var regexBrief = extractSummaryFieldByRegex(cleaned, 'brief_summary');
    var regexDetailed = extractSummaryFieldByRegex(cleaned, 'detailed_summary');
    if (regexBrief || regexDetailed) {
      return {
        brief_summary: regexBrief,
        detailed_summary: regexDetailed
      };
    }

    return null;
  }

  function extractSummaryFieldByRegex(text, fieldName) {
    var pattern = new RegExp('"' + fieldName + '"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"', 'i');
    var match = text.match(pattern);
    if (!match || !match[1]) return '';
    return normalizeSummaryText(match[1]);
  }

  function normalizeSummaryText(value, options) {
    var opts = options || {};
    var text = String(value || '')
      .replace(/\r\n/g, '\n')
      .replace(/\\n/g, '\n')
      .replace(/\\r/g, '\r')
      .replace(/\\t/g, '\t')
      .trim();
    if (!opts.preserveEscapedQuotes) {
      text = text.replace(/\\"/g, '"');
    }
    return text;
  }

  function truncate(value, limit) {
    if (!value || value.length <= limit) return value;
    return value.slice(0, limit - 3).trim() + '...';
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

  function normalizeCaptureDate(value) {
    var raw = String(value || '').trim();
    if (!raw) return '';
    var parsed = new Date(raw);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString().slice(0, 10);
    }
    var match = raw.match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : '';
  }

  function titleCase(value) {
    return (value || '')
      .replace(/[_-]/g, ' ')
      .replace(/\b\w/g, function (ch) { return ch.toUpperCase(); });
  }

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      window.setTimeout(resolve, ms);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

