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
  var _bodyLockCount = 0;

  // ── DOM refs ──────────────────────────────────────────────────────

  var avatarBtn, avatarImg, avatarFallback, avatarDropdown, avatarWrap;
  var cardGrid, emptyState, zettelCount, userDisplayName;
  var addZettelBtn, addZettelDropdown, addZettelForm, addUrlInput;
  var addSubmitBtn, addError, addLoading;
  var avatarModal, avatarModalOverlay, avatarModalClose, avatarGrid;
  var menuProfile, menuNexus, menuSignout;

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
    addSubmitBtn = document.getElementById('add-submit-btn');
    addError = document.getElementById('add-error');
    addLoading = document.getElementById('add-loading');
    avatarModal = document.getElementById('avatar-modal');
    avatarModalOverlay = document.getElementById('avatar-modal-overlay');
    avatarModalClose = document.getElementById('avatar-modal-close');
    avatarGrid = document.getElementById('avatar-grid');
    menuProfile = document.getElementById('menu-profile');
    menuNexus = document.getElementById('menu-nexus');
    menuSignout = document.getElementById('menu-signout');
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

  // ── Init ──────────────────────────────────────────────────────────

  async function init() {
    resolveDOM();

    try {
      // Init Supabase client
      var resp = await fetch('/api/auth/config');
      var config = await resp.json();
      if (config.supabase_url && config.supabase_anon_key) {
        _supabaseClient = supabase.createClient(config.supabase_url, config.supabase_anon_key, {
          auth: {
            persistSession: true,
            autoRefreshToken: true,
            storage: window.localStorage,
            storageKey: 'zk-auth-token',
          },
        });
        var sessionResult = await _supabaseClient.auth.getSession();
        _currentSession = sessionResult.data.session;
      }
    } catch (e) {
      console.error('[home] Supabase init failed:', e);
    }

    // Auth guard — redirect if not logged in (with loop protection)
    var token = _currentSession ? _currentSession.access_token : null;
    if (!token) {
      var lastRedirect = parseInt(sessionStorage.getItem('zk-home-redirect') || '0', 10);
      if (Date.now() - lastRedirect < 5000) {
        console.warn('[home] Redirect loop detected, staying on page');
        return;
      }
      sessionStorage.setItem('zk-home-redirect', String(Date.now()));
      window.location.href = '/';
      return;
    }
    sessionStorage.removeItem('zk-home-redirect');

    // Load user profile — stay on page even if fetch fails
    var profile = await fetchProfile(token);
    if (!profile) {
      var user = _currentSession.user || {};
      var meta = user.user_metadata || {};
      profile = {
        name: meta.full_name || user.email || 'User',
        email: user.email || '',
        avatar_url: meta.avatar_url || meta.picture || ''
      };
      console.warn('[home] Profile fetch failed, using session data');
    }

    // Set display name
    var displayName = profile.name || profile.email || 'User';
    if (userDisplayName) {
      userDisplayName.textContent = displayName.split(' ')[0];
    }

    // Set avatar — delegates to shared ZKHeader (preload + retry + fallback owned there)
    if (window.ZKHeader && typeof window.ZKHeader.boot === 'function') {
      await window.ZKHeader.boot(token, { profile: profile });
      // Track current id for the picker grid's "selected" highlight
      var _idMatch = profile && profile.avatar_url && profile.avatar_url.match(/avatar_(\d+)\.svg/);
      if (_idMatch) _currentAvatarId = parseInt(_idMatch[1], 10);
    } else {
      console.error('[home] ZKHeader missing — avatar will use CSS fallback only');
    }

    // Load zettels
    await loadZettels(token);
    loadKastens(token);

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
  // All avatar load/fallback/preload logic now lives in the shared ZKHeader module
  // (website/features/header/js/header.js). These wrappers keep the local picker-grid
  // callsite working without duplicating lifecycle code.

  async function updateAvatar(avatarId, token) {
    _currentAvatarId = avatarId;
    if (window.ZKHeader && typeof window.ZKHeader.setAvatarById === 'function') {
      await window.ZKHeader.setAvatarById(avatarId, token, null);
    }
  }

  // ── Zettels ───────────────────────────────────────────────────────

  async function loadKastens(token) {
    try {
      var resp = await fetch('/api/rag/sandboxes', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      if (!resp.ok) return;
      var data = await resp.json();
      var sandboxes = data.sandboxes || [];
      var totalMembers = sandboxes.reduce(function (acc, s) {
        return acc + (s.member_count || 0);
      }, 0);
      var elCount = document.getElementById('kastens-count');
      var elTotal = document.getElementById('kastens-total');
      var elMembers = document.getElementById('kastens-members');
      if (elCount) elCount.textContent = sandboxes.length;
      if (elTotal) elTotal.textContent = sandboxes.length;
      if (elMembers) elMembers.textContent = totalMembers;

      // Sort by last_used_at desc (fallback updated_at, then created_at)
      sandboxes.sort(function (a, b) {
        var ak = a.last_used_at || a.updated_at || a.created_at || '';
        var bk = b.last_used_at || b.updated_at || b.created_at || '';
        return bk.localeCompare(ak);
      });
      renderKastenCards(sandboxes.slice(0, 3), sandboxes.length);
    } catch (e) {
      console.warn('[home] Kastens load failed:', e);
      renderKastenCards([], 0);
    }
  }

  function renderKastenCards(previewKastens, totalCount) {
    var grid = document.getElementById('kasten-grid');
    var emptyEl = document.getElementById('kasten-empty-state');
    var preview = document.getElementById('kasten-preview');
    if (!grid || !emptyEl || !preview) return;

    var fade = preview.querySelector('.home-card-fade');

    if (totalCount === 0) {
      grid.innerHTML = '';
      emptyEl.classList.remove('hidden');
      if (fade) fade.style.display = 'none';
      return;
    }

    emptyEl.classList.add('hidden');
    grid.innerHTML = '';
    if (fade) fade.style.display = previewKastens.length > 0 ? '' : 'none';

    previewKastens.forEach(function (k, i) {
      var card = document.createElement('a');
      card.className = 'home-card home-kasten-card';
      card.href = '/home/rag?sandbox=' + encodeURIComponent(k.id);
      card.style.animationDelay = (i * 0.08) + 's';

      var members = k.member_count || 0;
      var quality = (k.default_quality || 'fast').toLowerCase();
      var qualityLabel = quality === 'high' ? 'Strong' : 'Fast';
      var desc = (k.description || '').trim();

      card.innerHTML =
        '<h3 class="home-card-title">' + escapeHtml(k.name || 'Untitled') + '</h3>' +
        (desc
          ? '<p class="home-kasten-desc">' + escapeHtml(desc) + '</p>'
          : '') +
        '<div class="home-card-meta">' +
          '<span class="home-card-date">' + members + ' zettel' + (members === 1 ? '' : 's') + '</span>' +
          '<span class="home-card-source">' + escapeHtml(qualityLabel) + '</span>' +
        '</div>';

      grid.appendChild(card);
    });
  }

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
      var safeUrl = toSafeHttpUrl(node.url);
      card.href = safeUrl || '#';
      card.target = safeUrl ? '_blank' : '';
      card.rel = safeUrl ? 'noopener noreferrer' : '';
      card.style.animationDelay = (i * 0.08) + 's';

      var sourceClass = (node.group || 'web').toLowerCase();

      card.innerHTML =
        '<h3 class="home-card-title">' + escapeHtml(node.name || 'Untitled') + '</h3>' +
        '<div class="home-card-meta">' +
          (node.date ? '<span class="home-card-date">' + escapeHtml(node.date) + '</span>' : '') +
          '<span class="home-card-source ' + sourceClass + '">' + escapeHtml(node.group || 'web') + '</span>' +
          '<button class="home-card-summary-btn" data-node-idx="' + i + '" type="button" title="Summary" aria-label="View summary">' +
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

  function extractSummaryParts(rawSummary) {
    var rawText = normalizeSummaryText(rawSummary || '');
    var parsed = tryParseSummaryObject(rawText);

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
    var cleaned = normalizeSummaryText(rawText || '');
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
    var pattern = new RegExp('"' + fieldName + '"\\s*:\\s*"([\\s\\S]*?)"\\s*(?:,|})', 'i');
    var match = text.match(pattern);
    if (!match || !match[1]) return '';
    return normalizeSummaryText(match[1]);
  }

  function normalizeSummaryText(value) {
    return String(value || '')
      .replace(/\r\n/g, '\n')
      .replace(/\\n/g, '\n')
      .replace(/\\r/g, '\r')
      .replace(/\\t/g, '\t')
      .replace(/\\"/g, '"')
      .trim();
  }

  // ── Add Zettel ────────────────────────────────────────────────────

  // ── Glass Shatter Animation ─────────────────────────────────────

  function shatterElement(sourceEl, targetRect, revealEl) {
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

      // Phase 2: Assemble into card shape (600ms) — shards snap into a tight grid
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
        // Start revealing skeleton underneath as shards settle
        if (revealEl) {
          setTimeout(function () {
            revealEl.style.opacity = '1';
          }, 300);
        }
      }, 600);

      // Phase 3: Dissolve shards — skeleton is already visible beneath (1150ms)
      setTimeout(function () {
        shards.forEach(function (s) {
          s.el.style.transition = 'all 0.35s ease-out';
          s.el.style.opacity = '0';
          s.el.style.transform = 'scale(0.95)';
        });
      }, 1200);

      // Phase 4: Cleanup (1600ms total)
      setTimeout(function () {
        container.remove();
        resolve();
      }, 1550);
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
    spacer.style.cssText = 'height:0;overflow:hidden;transition:height 0.65s cubic-bezier(0.22, 0.61, 0.36, 1);border:none;background:none;padding:0;margin:0;';

    if (cardGrid) {
      cardGrid.insertBefore(spacer, cardGrid.firstChild);
      while (cardGrid.children.length > 4) {
        cardGrid.removeChild(cardGrid.lastChild);
      }
      // Expand to exact skeleton card height
      requestAnimationFrame(function () {
        spacer.style.height = Math.round(cardH * 0.85) + 'px';
      });
    }

    // Start shatter after cards begin sliding down
    await new Promise(function (r) { setTimeout(r, 300); });

    var targetRect = spacer.getBoundingClientRect();

    // Start API call immediately (runs in parallel with animation)
    var apiPromise = fetch('/api/summarize', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ url: url })
    });

    // Create skeleton now — it'll be revealed seamlessly during shatter
    var skeleton = document.createElement('div');
    skeleton.className = 'home-card home-card-skeleton';
    skeleton.style.opacity = '0';
    skeleton.style.transition = 'opacity 0.4s ease';
    skeleton.innerHTML =
      '<div class="skeleton-line skeleton-title"></div>' +
      '<div class="home-card-meta">' +
        '<div class="skeleton-line skeleton-date"></div>' +
        '<div class="skeleton-line skeleton-source"></div>' +
      '</div>';

    // Replace spacer with hidden skeleton before shatter starts
    if (cardGrid && spacer.parentNode) {
      cardGrid.replaceChild(skeleton, spacer);
      while (cardGrid.children.length > 3) {
        cardGrid.removeChild(cardGrid.lastChild);
      }
    }

    // Run shatter — shards assemble on top of the skeleton, then skeleton fades in
    if (dropdownRect && addZettelDropdown) {
      await shatterElement(addZettelDropdown, skeleton.getBoundingClientRect(), skeleton);
    } else {
      if (addZettelDropdown) addZettelDropdown.classList.remove('open');
      skeleton.style.opacity = '1';
    }

    // Clear form
    if (addUrlInput) addUrlInput.value = '';

    try {
      var resp = await apiPromise;

      if (!resp.ok) {
        var errMsg = 'Failed to process URL (HTTP ' + resp.status + ')';
        try {
          var err = await resp.json();
          errMsg = err.detail || errMsg;
        } catch (_parseErr) {
          var rawText = '';
          try { rawText = await resp.text(); } catch (_) {}
          if (rawText) errMsg = rawText.slice(0, 200);
        }
        throw new Error(errMsg);
      }

      var result = await resp.json();

      // Morph skeleton into real card
      var today = new Date().toISOString().slice(0, 10);
      var sourceType = (result.source_type || 'web').toLowerCase();
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
      var safeNewUrl = toSafeHttpUrl(newNode.url);
      realCard.href = safeNewUrl || '#';
      realCard.target = safeNewUrl ? '_blank' : '';
      realCard.rel = safeNewUrl ? 'noopener noreferrer' : '';

      realCard.innerHTML =
        '<h3 class="home-card-title">' + escapeHtml(newNode.name) + '</h3>' +
        '<div class="home-card-meta">' +
          '<span class="home-card-date">' + escapeHtml(newNode.date) + '</span>' +
          '<span class="home-card-source ' + sourceType + '">' + escapeHtml(newNode.group) + '</span>' +
          '<button class="home-card-summary-btn" type="button" title="Summary" aria-label="View summary">' +
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

    var sourceClass = (node.group || 'web').toLowerCase();
    meta.innerHTML =
      (node.date ? '<span class="home-card-date">' + escapeHtml(node.date) + '</span>' : '') +
      '<span class="home-card-source ' + sourceClass + '">' + escapeHtml(node.group || 'web') + '</span>';

    var summaryParts = extractSummaryParts(node.summary || node.description || '');
    text.textContent = summaryParts.detailed || summaryParts.brief || 'No summary available for this zettel.';

    tags.innerHTML = '';
    var nodeTags = node.tags || [];
    nodeTags.forEach(function (tag) {
      var el = document.createElement('span');
      el.className = 'home-summary-tag';
      el.textContent = '#' + tag;
      tags.appendChild(el);
    });

    // Show loader animation first
    setBodyScrollLocked(true);
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
    setBodyScrollLocked(false);
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
    setBodyScrollLocked(true);
  }

  function closeAvatarPicker() {
    if (!avatarModal) return;
    avatarModal.classList.remove('open');
    setBodyScrollLocked(false);
  }

  // ── Events ────────────────────────────────────────────────────────

  function bindEvents(token) {
    // Avatar dropdown toggle
    if (avatarBtn) {
      avatarBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        avatarDropdown.classList.toggle('open');
        avatarBtn.setAttribute('aria-expanded', avatarDropdown.classList.contains('open') ? 'true' : 'false');
      });
    }

    // Close dropdown on outside click
    document.addEventListener('click', function (e) {
      if (avatarDropdown && avatarWrap && !avatarWrap.contains(e.target)) {
        avatarDropdown.classList.remove('open');
        if (avatarBtn) avatarBtn.setAttribute('aria-expanded', 'false');
      }
      var addWrap = document.getElementById('add-zettel-wrap');
      if (addZettelDropdown && addWrap && !addWrap.contains(e.target)) {
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

    if (menuNexus) {
      menuNexus.addEventListener('click', function () {
        if (avatarDropdown) avatarDropdown.classList.remove('open');
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
