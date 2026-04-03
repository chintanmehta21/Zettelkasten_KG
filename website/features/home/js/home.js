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

      // Intercept card clicks — if summary button was clicked, show popup instead of navigating
      card.addEventListener('click', function (e) {
        var btn = e.target.closest('.home-card-summary-btn');
        if (btn) {
          e.preventDefault();
          e.stopPropagation();
          openSummaryPopup(node);
        }
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

  // ── Glass Shatter Animation ─────────────────────────────────────

  function shatterElement(sourceEl, targetRect) {
    return new Promise(function (resolve) {
      var rect = sourceEl.getBoundingClientRect();
      var container = document.createElement('div');
      container.style.cssText = 'position:fixed;inset:0;z-index:600;pointer-events:none;overflow:hidden;';
      document.body.appendChild(container);

      var cols = 10, rows = 4;
      var shardW = rect.width / cols;
      var shardH = rect.height / rows;
      var shards = [];
      var colors = [
        'hsla(172, 66%, 50%, 0.7)',
        'hsla(172, 50%, 40%, 0.6)',
        'hsla(172, 40%, 35%, 0.5)',
        'hsla(190, 50%, 30%, 0.5)',
        'hsla(210, 30%, 25%, 0.5)',
        'hsla(172, 66%, 50%, 0.4)',
      ];

      // Target card grid dimensions
      var tCols = 10, tRows = 4;
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

          // Calculate where this shard should land in the target card grid
          var idx = r * cols + c;
          var tR = Math.floor(idx / tCols) % tRows;
          var tC = idx % tCols;

          shards.push({
            el: shard,
            startX: startX,
            startY: startY,
            explodeX: startX + (Math.random() - 0.5) * 280,
            explodeY: startY + (Math.random() - 0.5) * 180 - 60,
            explodeRot: (Math.random() - 0.5) * 300,
            // Exact grid position on the target card
            targetX: targetRect.left + tC * tShardW,
            targetY: targetRect.top + tR * tShardH,
            targetW: tShardW,
            targetH: tShardH,
          });
        }
      }

      // Hide dropdown
      sourceEl.classList.remove('open');

      // Phase 1: Explode outward
      requestAnimationFrame(function () {
        shards.forEach(function (s) {
          s.el.style.left = s.explodeX + 'px';
          s.el.style.top = s.explodeY + 'px';
          s.el.style.transform = 'rotate(' + s.explodeRot + 'deg) scale(' + (0.6 + Math.random() * 0.6) + ')';
          s.el.style.opacity = '0.85';
        });
      });

      // Phase 2: Assemble into card shape (650ms) — shards snap into a tight grid
      setTimeout(function () {
        shards.forEach(function (s, i) {
          var delay = (i % 5) * 0.02;
          s.el.style.transition = 'all 0.55s cubic-bezier(0.34, 1.56, 0.64, 1) ' + delay + 's';
          s.el.style.left = s.targetX + 'px';
          s.el.style.top = s.targetY + 'px';
          s.el.style.width = s.targetW + 'px';
          s.el.style.height = s.targetH + 'px';
          s.el.style.transform = 'rotate(0deg) scale(1)';
          s.el.style.opacity = '0.7';
          s.el.style.borderRadius = '1px';
        });
      }, 600);

      // Phase 3: Flash glow then fade — card shape is visible, then dissolves (1200ms)
      setTimeout(function () {
        shards.forEach(function (s) {
          s.el.style.transition = 'all 0.3s ease-out';
          s.el.style.opacity = '0';
          s.el.style.boxShadow = '0 0 12px hsla(172, 66%, 50%, 0.4)';
        });
      }, 1250);

      // Phase 4: Cleanup (1600ms total)
      setTimeout(function () {
        container.remove();
        resolve();
      }, 1600);
    });
  }

  async function addZettel(url, token) {
    if (addError) addError.textContent = '';
    if (addSubmitBtn) addSubmitBtn.disabled = true;

    // Capture dropdown rect before hiding
    var dropdownRect = addZettelDropdown ? addZettelDropdown.getBoundingClientRect() : null;

    // Step 0: Insert an invisible spacer at top and animate cards sliding down
    if (emptyState) emptyState.classList.add('hidden');
    var fade = document.querySelector('.home-card-fade');
    if (fade) fade.style.display = '';

    // Measure exact skeleton height by briefly inserting a hidden one
    var measureSkeleton = document.createElement('div');
    measureSkeleton.className = 'home-card home-card-skeleton';
    measureSkeleton.style.cssText = 'visibility:hidden;position:absolute;';
    measureSkeleton.innerHTML =
      '<div class="skeleton-line skeleton-title"></div>' +
      '<div class="home-card-meta"><div class="skeleton-line skeleton-date"></div><div class="skeleton-line skeleton-source"></div></div>';
    if (cardGrid) {
      cardGrid.appendChild(measureSkeleton);
      var cardH = measureSkeleton.offsetHeight;
      cardGrid.removeChild(measureSkeleton);
    } else {
      var cardH = 72;
    }

    var spacer = document.createElement('div');
    spacer.className = 'home-card-spacer';
    spacer.style.cssText = 'height:0;overflow:hidden;transition:height 1.4s cubic-bezier(0.25, 0.1, 0.25, 1);border:none;background:none;padding:0;margin:0;';

    if (cardGrid) {
      cardGrid.insertBefore(spacer, cardGrid.firstChild);
      while (cardGrid.children.length > 4) {
        cardGrid.removeChild(cardGrid.lastChild);
      }
      // Expand to exact skeleton card height
      requestAnimationFrame(function () {
        spacer.style.height = cardH + 'px';
      });
    }

    // Start shatter early while cards are still sliding down
    await new Promise(function (r) { setTimeout(r, 500); });

    var targetRect = spacer.getBoundingClientRect();

    // Start API call immediately (runs in parallel with animation)
    var apiPromise = fetch('/api/summarize', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ url: url, source_type: addSourceType ? addSourceType.value : '' })
    });

    // Run shatter animation on the dropdown
    if (dropdownRect && addZettelDropdown) {
      await shatterElement(addZettelDropdown, targetRect);
    } else {
      if (addZettelDropdown) addZettelDropdown.classList.remove('open');
    }

    // Clear form
    if (addUrlInput) addUrlInput.value = '';

    // Replace spacer with skeleton card
    var skeleton = document.createElement('div');
    skeleton.className = 'home-card home-card-skeleton';
    skeleton.innerHTML =
      '<div class="skeleton-line skeleton-title"></div>' +
      '<div class="home-card-meta">' +
        '<div class="skeleton-line skeleton-date"></div>' +
        '<div class="skeleton-line skeleton-source"></div>' +
      '</div>';

    if (cardGrid && spacer.parentNode) {
      cardGrid.replaceChild(skeleton, spacer);
      while (cardGrid.children.length > 3) {
        cardGrid.removeChild(cardGrid.lastChild);
      }
    }

    try {
      var resp = await apiPromise;

      if (!resp.ok) {
        var err = await resp.json();
        throw new Error(err.detail || 'Failed to process URL');
      }

      var result = await resp.json();

      // Morph skeleton into real card
      var today = new Date().toISOString().slice(0, 10);
      var sourceType = (result.source_type || 'generic').toLowerCase();
      var newNode = {
        name: result.title || 'Untitled',
        date: today,
        group: sourceType,
        url: result.source_url || url,
        summary: result.brief_summary || result.summary || '',
        tags: result.tags || []
      };

      var realCard = document.createElement('a');
      realCard.className = 'home-card home-card-new';
      realCard.href = newNode.url;
      realCard.target = '_blank';
      realCard.rel = 'noopener';

      realCard.innerHTML =
        '<h3 class="home-card-title">' + escapeHtml(newNode.name) + '</h3>' +
        '<div class="home-card-meta">' +
          '<span class="home-card-date">' + escapeHtml(newNode.date) + '</span>' +
          '<span class="home-card-source ' + sourceType + '">' + escapeHtml(newNode.group) + '</span>' +
          '<button class="home-card-summary-btn" title="Summary">' +
            '<img src="/artifacts/icon-summary.svg" alt="Summary" />' +
            '<span class="tooltip">Summary</span>' +
          '</button>' +
        '</div>';

      realCard.addEventListener('click', function (e) {
        var btn = e.target.closest('.home-card-summary-btn');
        if (btn) {
          e.preventDefault();
          e.stopPropagation();
          openSummaryPopup(newNode);
        }
      });

      if (cardGrid && skeleton.parentNode) {
        cardGrid.replaceChild(realCard, skeleton);
      }

      var count = parseInt(zettelCount.textContent || '0', 10) + 1;
      zettelCount.textContent = count;
    } catch (e) {
      if (skeleton.parentNode) skeleton.parentNode.removeChild(skeleton);
      if (addError) addError.textContent = e.message;
      if (addZettelDropdown) addZettelDropdown.classList.add('open');
    } finally {
      if (addSubmitBtn) addSubmitBtn.disabled = false;
    }
  }

  // ── Summary Popup ────────────────────────────────────────────────

  function openSummaryPopup(node) {
    var loader = document.getElementById('summary-loader');
    var overlay = document.getElementById('summary-overlay');
    var title = document.getElementById('summary-title');
    var meta = document.getElementById('summary-meta');
    var text = document.getElementById('summary-text');
    var tags = document.getElementById('summary-tags');
    if (!overlay) return;

    // Prepare popup content while loader plays
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

    // Show loader animation first
    document.body.style.overflow = 'hidden';
    if (loader) {
      loader.classList.add('active');
      setTimeout(function () {
        loader.classList.remove('active');
        overlay.classList.add('open');
      }, 1500);
    } else {
      overlay.classList.add('open');
    }
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
