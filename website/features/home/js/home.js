/**
 * Home Page — Post-Login Dashboard
 *
 * Loads user profile, displays zettel vault, handles avatar menu,
 * and provides "Add Zettel" functionality.
 */

(function () {
  'use strict';

  var AVATAR_COUNT = 60;
  var _supabaseClient = null;
  var _currentSession = null;
  var _currentAvatarId = null;

  // ── DOM refs ──────────────────────────────────────────────────────

  var avatarBtn, avatarImg, avatarFallback, avatarDropdown, avatarWrap;
  var cardGrid, emptyState, zettelCount, userDisplayName;
  var addZettelBtn, addZettelDropdown, addZettelForm, addUrlInput;
  var addSourceType, addSubmitBtn, addError, addLoading;
  var avatarModal, avatarModalOverlay, avatarModalClose, avatarGrid;
  var menuProfile, menuSignout;

  function resolveDOM() {
    avatarBtn = document.getElementById('avatar-btn');
    avatarImg = document.getElementById('avatar-img');
    avatarFallback = document.getElementById('avatar-fallback');
    avatarDropdown = document.getElementById('avatar-dropdown');
    avatarWrap = document.getElementById('avatar-wrap');
    cardGrid = document.getElementById('card-grid');
    emptyState = document.getElementById('empty-state');
    zettelCount = document.getElementById('zettel-count');
    userDisplayName = document.getElementById('user-display-name');
    addZettelBtn = document.getElementById('add-zettel-btn');
    addZettelDropdown = document.getElementById('add-zettel-dropdown');
    addZettelForm = document.getElementById('add-zettel-form');
    addUrlInput = document.getElementById('add-url-input');
    addSourceType = document.getElementById('add-source-type');
    addSubmitBtn = document.getElementById('add-submit-btn');
    addError = document.getElementById('add-error');
    addLoading = document.getElementById('add-loading');
    avatarModal = document.getElementById('avatar-modal');
    avatarModalOverlay = document.getElementById('avatar-modal-overlay');
    avatarModalClose = document.getElementById('avatar-modal-close');
    avatarGrid = document.getElementById('avatar-grid');
    menuProfile = document.getElementById('menu-profile');
    menuSignout = document.getElementById('menu-signout');
  }

  // ── Init ──────────────────────────────────────────────────────────

  async function init() {
    resolveDOM();

    try {
      // Init Supabase client
      var resp = await fetch('/api/auth/config');
      var config = await resp.json();
      if (config.supabase_url && config.supabase_anon_key) {
        _supabaseClient = supabase.createClient(config.supabase_url, config.supabase_anon_key);
        var sessionResult = await _supabaseClient.auth.getSession();
        _currentSession = sessionResult.data.session;
      }
    } catch (e) {
      console.error('[home] Supabase init failed:', e);
    }

    // Auth guard — redirect if not logged in
    var token = _currentSession ? _currentSession.access_token : null;
    if (!token) {
      window.location.href = '/';
      return;
    }

    // Load user profile
    var profile = await fetchProfile(token);
    if (!profile) {
      window.location.href = '/';
      return;
    }

    // Set display name
    var displayName = profile.name || profile.email || 'User';
    if (userDisplayName) {
      userDisplayName.textContent = displayName.split(' ')[0];
    }

    // Set avatar
    await setupAvatar(profile, token);

    // Load zettels
    await loadZettels(token);

    // Bind events
    bindEvents(token);
  }

  // ── Profile ───────────────────────────────────────────────────────

  async function fetchProfile(token) {
    try {
      var resp = await fetch('/api/me', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      if (resp.status === 401) return null;
      return await resp.json();
    } catch (e) {
      console.error('[home] Profile fetch failed:', e);
      return null;
    }
  }

  // ── Avatar ────────────────────────────────────────────────────────

  async function setupAvatar(profile, token) {
    var avatarUrl = profile.avatar_url;

    // If no avatar set, assign a random one
    if (!avatarUrl || !avatarUrl.includes('/artifacts/avatars/')) {
      var randomId = Math.floor(Math.random() * AVATAR_COUNT);
      avatarUrl = '/artifacts/avatars/avatar_' + String(randomId).padStart(2, '0') + '.svg';
      _currentAvatarId = randomId;

      // Persist to server
      try {
        await fetch('/api/me/avatar', {
          method: 'PUT',
          headers: {
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ avatar_id: randomId })
        });
      } catch (e) {
        console.warn('[home] Avatar persist failed:', e);
      }
    } else {
      // Extract avatar_id from URL
      var match = avatarUrl.match(/avatar_(\d+)\.svg/);
      _currentAvatarId = match ? parseInt(match[1], 10) : 0;
    }

    // Display avatar
    if (avatarImg) {
      avatarImg.src = avatarUrl;
      avatarImg.onerror = function () {
        avatarImg.classList.add('hidden');
        if (avatarFallback) {
          var initial = (profile.name || profile.email || 'U')[0].toUpperCase();
          avatarFallback.textContent = initial;
          avatarFallback.classList.add('visible');
        }
      };
    }
  }

  async function updateAvatar(avatarId, token) {
    var avatarUrl = '/artifacts/avatars/avatar_' + String(avatarId).padStart(2, '0') + '.svg';
    _currentAvatarId = avatarId;

    // Update display
    if (avatarImg) {
      avatarImg.src = avatarUrl;
      avatarImg.classList.remove('hidden');
    }
    if (avatarFallback) {
      avatarFallback.classList.remove('visible');
    }

    // Persist
    try {
      await fetch('/api/me/avatar', {
        method: 'PUT',
        headers: {
          'Authorization': 'Bearer ' + token,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ avatar_id: avatarId })
      });
    } catch (e) {
      console.warn('[home] Avatar update failed:', e);
    }
  }

  // ── Zettels ───────────────────────────────────────────────────────

  async function loadZettels(token) {
    try {
      var resp = await fetch('/api/graph?view=my', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      var data = await resp.json();
      var nodes = data.nodes || [];
      var links = data.links || [];

      // Sort by date descending
      nodes.sort(function (a, b) {
        return (b.date || '').localeCompare(a.date || '');
      });

      // Update KG stats panel
      var kgNodeCount = document.getElementById('kg-node-count');
      var kgLinkCount = document.getElementById('kg-link-count');
      if (kgNodeCount) kgNodeCount.textContent = nodes.length;
      if (kgLinkCount) kgLinkCount.textContent = links.length;

      // Show only latest 3 zettels in the preview
      renderCards(nodes.slice(0, 3), nodes.length);
    } catch (e) {
      console.error('[home] Zettels load failed:', e);
      renderCards([], 0);
    }
  }

  function renderCards(previewNodes, totalCount) {
    if (!cardGrid || !emptyState || !zettelCount) return;

    zettelCount.textContent = totalCount;

    if (totalCount === 0) {
      cardGrid.innerHTML = '';
      emptyState.classList.remove('hidden');
      // Hide fade when empty
      var fade = document.querySelector('.home-card-fade');
      if (fade) fade.style.display = 'none';
      return;
    }

    emptyState.classList.add('hidden');
    cardGrid.innerHTML = '';

    // Show fade only when there are cards
    var fade = document.querySelector('.home-card-fade');
    if (fade) fade.style.display = previewNodes.length > 0 ? '' : 'none';

    previewNodes.forEach(function (node, i) {
      var card = document.createElement('a');
      card.className = 'home-card';
      card.href = node.url || '#';
      card.target = '_blank';
      card.rel = 'noopener';
      card.style.animationDelay = (i * 0.08) + 's';

      var sourceClass = (node.group || 'generic').toLowerCase();

      card.innerHTML =
        '<h3 class="home-card-title">' + escapeHtml(node.name || 'Untitled') + '</h3>' +
        '<div class="home-card-meta">' +
          (node.date ? '<span class="home-card-date">' + escapeHtml(node.date) + '</span>' : '') +
          '<span class="home-card-source ' + sourceClass + '">' + escapeHtml(node.group || 'web') + '</span>' +
          '<button class="home-card-summary-btn" data-node-idx="' + i + '" title="Summary">' +
            '<img src="/artifacts/icon-summary.svg" alt="Summary" />' +
            '<span class="tooltip">Summary</span>' +
          '</button>' +
        '</div>';

      // Store node data for popup
      card.querySelector('.home-card-summary-btn').addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        openSummaryPopup(node);
      });

      cardGrid.appendChild(card);
    });
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Add Zettel ────────────────────────────────────────────────────

  async function addZettel(url, token) {
    if (addError) addError.textContent = '';
    if (addLoading) addLoading.classList.remove('hidden');
    if (addSubmitBtn) addSubmitBtn.disabled = true;

    try {
      var resp = await fetch('/api/summarize', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + token,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ url: url, source_type: addSourceType ? addSourceType.value : '' })
      });

      if (!resp.ok) {
        var err = await resp.json();
        throw new Error(err.detail || 'Failed to process URL');
      }

      // Clear form
      if (addUrlInput) addUrlInput.value = '';
      if (addZettelDropdown) addZettelDropdown.classList.remove('open');
      if (addZettelBtn) addZettelBtn.classList.remove('open');

      // Reload zettels
      await loadZettels(token);
    } catch (e) {
      if (addError) addError.textContent = e.message;
    } finally {
      if (addLoading) addLoading.classList.add('hidden');
      if (addSubmitBtn) addSubmitBtn.disabled = false;
    }
  }

  // ── Summary Popup ────────────────────────────────────────────────

  function openSummaryPopup(node) {
    var overlay = document.getElementById('summary-overlay');
    var title = document.getElementById('summary-title');
    var meta = document.getElementById('summary-meta');
    var text = document.getElementById('summary-text');
    var tags = document.getElementById('summary-tags');
    if (!overlay) return;

    title.textContent = node.name || 'Untitled';

    var sourceClass = (node.group || 'generic').toLowerCase();
    meta.innerHTML =
      (node.date ? '<span class="home-card-date">' + escapeHtml(node.date) + '</span>' : '') +
      '<span class="home-card-source ' + sourceClass + '">' + escapeHtml(node.group || 'web') + '</span>';

    text.textContent = node.summary || node.description || 'No summary available for this zettel.';

    tags.innerHTML = '';
    var nodeTags = node.tags || [];
    nodeTags.forEach(function (tag) {
      var el = document.createElement('span');
      el.className = 'home-summary-tag';
      el.textContent = '#' + tag;
      tags.appendChild(el);
    });

    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeSummaryPopup() {
    var overlay = document.getElementById('summary-overlay');
    if (overlay) overlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  // ── Avatar Picker Modal ──────────────────────────────────────────

  function openAvatarPicker(token) {
    if (!avatarModal || !avatarGrid) return;

    // Populate grid
    avatarGrid.innerHTML = '';
    for (var i = 0; i < AVATAR_COUNT; i++) {
      var btn = document.createElement('button');
      btn.className = 'home-avatar-option' + (i === _currentAvatarId ? ' selected' : '');
      btn.innerHTML = '<img src="/artifacts/avatars/avatar_' + String(i).padStart(2, '0') + '.svg" alt="Avatar ' + i + '" />';
      btn.setAttribute('data-avatar-id', i);

      btn.addEventListener('click', (function (id) {
        return function () {
          updateAvatar(id, token);
          // Update selection
          var all = avatarGrid.querySelectorAll('.home-avatar-option');
          all.forEach(function (el) { el.classList.remove('selected'); });
          this.classList.add('selected');
          // Close modal after short delay
          setTimeout(function () { closeAvatarPicker(); }, 300);
        };
      })(i));

      avatarGrid.appendChild(btn);
    }

    avatarModal.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeAvatarPicker() {
    if (!avatarModal) return;
    avatarModal.classList.remove('open');
    document.body.style.overflow = '';
  }

  // ── Events ────────────────────────────────────────────────────────

  function bindEvents(token) {
    // Avatar dropdown toggle
    if (avatarBtn) {
      avatarBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        avatarDropdown.classList.toggle('open');
      });
    }

    // Close dropdown on outside click
    document.addEventListener('click', function (e) {
      if (avatarDropdown && !avatarWrap.contains(e.target)) {
        avatarDropdown.classList.remove('open');
      }
      if (addZettelDropdown && !document.getElementById('add-zettel-wrap').contains(e.target)) {
        addZettelDropdown.classList.remove('open');
        if (addZettelBtn) addZettelBtn.classList.remove('open');
      }
    });

    // Profile menu item → open avatar picker
    if (menuProfile) {
      menuProfile.addEventListener('click', function (e) {
        e.preventDefault();
        avatarDropdown.classList.remove('open');
        openAvatarPicker(token);
      });
    }

    // Sign out
    if (menuSignout) {
      menuSignout.addEventListener('click', async function () {
        if (_supabaseClient) {
          await _supabaseClient.auth.signOut();
        }
        window.location.href = '/';
      });
    }

    // Add Zettel toggle
    if (addZettelBtn) {
      addZettelBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        addZettelDropdown.classList.toggle('open');
        addZettelBtn.classList.toggle('open');
        if (addZettelDropdown.classList.contains('open') && addUrlInput) {
          addUrlInput.focus();
        }
      });
    }

    // Add Zettel form submit
    if (addZettelForm) {
      addZettelForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var url = addUrlInput ? addUrlInput.value.trim() : '';
        if (url) addZettel(url, token);
      });
    }

    // Summary popup close
    var summaryClose = document.getElementById('summary-close');
    var summaryBackdrop = document.getElementById('summary-backdrop');
    if (summaryClose) summaryClose.addEventListener('click', closeSummaryPopup);
    if (summaryBackdrop) summaryBackdrop.addEventListener('click', closeSummaryPopup);

    // Avatar modal close
    if (avatarModalClose) avatarModalClose.addEventListener('click', closeAvatarPicker);
    if (avatarModalOverlay) avatarModalOverlay.addEventListener('click', closeAvatarPicker);

    // Escape key closes modals
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeSummaryPopup();
        closeAvatarPicker();
        if (avatarDropdown) avatarDropdown.classList.remove('open');
        if (addZettelDropdown) {
          addZettelDropdown.classList.remove('open');
          if (addZettelBtn) addZettelBtn.classList.remove('open');
        }
      }
    });
  }

  // ── Start ─────────────────────────────────────────────────────────

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
