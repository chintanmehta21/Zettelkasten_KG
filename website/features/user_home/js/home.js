/**
 * Home Page — Post-Login Dashboard
 *
 * Loads user profile, displays zettel vault, handles avatar menu,
 * and provides "Add Zettel" functionality.
 */

(function () {
  'use strict';

  var AVATAR_COUNT = 60;

  // Conservative smart-dollar guard: only treat $...$ as math when the
  // content looks like LaTeX (no bare prices like $5 / $ 100). Display
  // ($$, \[ \]) and \( \) are unambiguous and always allowed.
  function _mathRenderArxiv(rootEl, sourceType) {
    if (!rootEl) return;
    rootEl.setAttribute('data-math-source', String(sourceType || ''));
    // DYNAMIC GATE: today only 'arxiv'; widen this set later if accuracy holds.
    var MATH_SOURCES = { arxiv: true };
    if (!MATH_SOURCES[String(sourceType || '').toLowerCase()]) return;
    if (typeof window.renderMathInElement !== 'function') return;
    try {
      window.renderMathInElement(rootEl, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '\\[', right: '\\]', display: true },
          { left: '\\(', right: '\\)', display: false },
          { left: '$', right: '$', display: false }
        ],
        // smart-dollar: a $ that opens math must be followed by a
        // non-space, non-digit; closing $ preceded by non-space. KaTeX
        // auto-render has no built-in guard, so pre-mask price-like $.
        preProcess: function (math) { return math; },
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
        ignoredClasses: ['no-math'],
        throwOnError: false,
        trust: false,
        maxExpand: 1000
      });
    } catch (e) {
      // Never let math rendering break the popup.
      if (window.console && console.warn) console.warn('[katex] skipped', e);
    }
  }

  // Pre-mask ONLY genuine currency $ so it can't be mis-paired as math, while
  // preserving real $...$ / $$...$$ KaTeX delimiter pairs (incl. numeric-leading
  // inline LaTeX like $1/N$, $2\pi$). Applied to text nodes only, pre-render.
  // Mirrors KaTeX auto-render delimiter rules: an opening $ may not be
  // immediately followed by whitespace and a closing $ may not be immediately
  // preceded by whitespace; \$ is an escaped literal (never a delimiter).
  function _maskPriceDollarsStr(s) {
    var SENT = '﹩'; // ﹩ small dollar sign sentinel
    var out = '';
    var i = 0;
    var n = s.length;
    while (i < n) {
      var ch = s[i];
      if (ch === '\\' && s[i + 1] === '$') { out += '\\$'; i += 2; continue; }
      if (ch !== '$') { out += ch; i += 1; continue; }
      // $$ display, then $ inline. Try to find a valid closing delimiter.
      var isDisplay = s[i + 1] === '$';
      var openLen = isDisplay ? 2 : 1;
      var contentStart = i + openLen;
      // KaTeX: opening delimiter not immediately followed by whitespace.
      var bad = contentStart >= n || /\s/.test(s[contentStart]);
      var close = -1;
      if (!bad) {
        for (var j = contentStart; j < n; j++) {
          if (s[j] === '\\') { j += 1; continue; }
          if (isDisplay) {
            if (s[j] === '$' && s[j + 1] === '$') {
              if (j > contentStart && !/\s/.test(s[j - 1])) { close = j; }
              break;
            }
          } else if (s[j] === '$') {
            // closing $ not immediately preceded by whitespace, non-empty span.
            if (j > contentStart && !/\s/.test(s[j - 1])) { close = j; }
            break;
          }
        }
      }
      if (close !== -1) {
        // Valid math span: emit verbatim so KaTeX still pairs/renders it.
        var end = close + openLen;
        out += s.slice(i, end);
        i = end;
        continue;
      }
      // Unpaired $: currency iff followed by digit/whitespace → mask it.
      if (contentStart < n && /[\s\d]/.test(s[i + 1])) {
        out += SENT;
      } else {
        out += '$';
      }
      i += 1;
    }
    return out;
  }

  function _maskPriceDollars(rootEl) {
    if (!rootEl) return;
    var walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, null);
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue.indexOf('$') !== -1) {
        node.nodeValue = _maskPriceDollarsStr(node.nodeValue);
      }
    }
  }

  function _unmaskPriceDollars(rootEl) {
    if (!rootEl) return;
    var walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, null);
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue.indexOf('﹩') !== -1) {
        node.nodeValue = node.nodeValue.replace(/﹩/g, '$');
      }
    }
  }

  var _supabaseClient = null;
  var _currentSession = null;
  var _currentAvatarId = null;
  var _bodyLockCount = 0;

  // ── DOM refs ──────────────────────────────────────────────────────

  var avatarBtn, avatarImg, avatarFallback, avatarDropdown, avatarWrap;
  var cardGrid, emptyState, zettelCount, userDisplayName;
  var addZettelDropdown, addZettelForm, addUrlInput, addDocumentInput, addDocumentBtn;
  var addSubmitBtn, addError, addLoading;
  var avatarModal, avatarModalOverlay, avatarModalClose, avatarGrid;
  var menuProfile, menuNexus, menuSignout;

  function resolveDOM() {
    // D-2 namespace: home owns its own duplicate avatar markup; header.html
    // ships #avatar-btn/#avatar-dropdown/#menu-signout — renamed here so a
    // future shell-injection of header on /home cannot silent-collide.
    avatarBtn = document.getElementById('home-avatar-btn');
    avatarImg = document.getElementById('home-avatar-img');
    avatarFallback = document.getElementById('home-avatar-fallback');
    avatarDropdown = document.getElementById('home-avatar-dropdown');
    avatarWrap = document.getElementById('home-avatar-wrap');
    cardGrid = document.getElementById('card-grid');
    emptyState = document.getElementById('empty-state');
    zettelCount = document.getElementById('zettel-count');
    userDisplayName = document.getElementById('user-display-name');
    addZettelDropdown = document.getElementById('add-zettel-dropdown');
    addZettelForm = document.getElementById('add-zettel-form');
    addUrlInput = document.getElementById('add-url-input');
    addDocumentInput = document.getElementById('add-document-input');
    addDocumentBtn = document.getElementById('add-document-btn');
    addSubmitBtn = document.getElementById('add-submit-btn');
    addError = document.getElementById('add-error');
    addLoading = document.getElementById('add-loading');
    avatarModal = document.getElementById('avatar-modal');
    avatarModalOverlay = document.getElementById('avatar-modal-overlay');
    avatarModalClose = document.getElementById('avatar-modal-close');
    avatarGrid = document.getElementById('avatar-grid');
    menuProfile = document.getElementById('menu-profile');
    menuNexus = document.getElementById('menu-nexus');
    menuSignout = document.getElementById('home-menu-signout');
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

  function validateDocument(file) {
    if (!file) return null;
    var allowed = /\.(pdf|txt|md|markdown|docx)$/i;
    if (!allowed.test(file.name || '')) return 'Upload PDF, TXT, Markdown, or DOCX';
    if (file.size > 10 * 1024 * 1024) return 'Document is too large (max 10 MB)';
    if (file.size <= 0) return 'Document is empty';
    return null;
  }

  function clearSelectedDocument() {
    if (addDocumentInput) addDocumentInput.value = '';
    if (addDocumentBtn) addDocumentBtn.classList.remove('has-file');
    if (addUrlInput) addUrlInput.placeholder = 'https://…';
  }

  function getSelectedDocument() {
    return addDocumentInput && addDocumentInput.files ? addDocumentInput.files[0] : null;
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

    // Bind events FIRST so UI stays interactive even if downstream calls fail
    bindEvents(token);

    // Set avatar — delegates to shared ZKHeader (non-fatal if it throws)
    try {
      if (window.ZKHeader && typeof window.ZKHeader.boot === 'function') {
        await window.ZKHeader.boot(token, { profile: profile });
        var _idMatch = profile && profile.avatar_url && profile.avatar_url.match(/avatar_(\d+)\.svg/);
        if (_idMatch) _currentAvatarId = parseInt(_idMatch[1], 10);
      } else {
        console.error('[home] ZKHeader missing — avatar will use CSS fallback only');
      }
    } catch (e) {
      console.error('[home] ZKHeader.boot failed:', e);
    }

    // Load zettels + kastens (non-fatal if they error)
    try {
      await loadZettels(token);
    } catch (e) {
      console.error('[home] loadZettels failed:', e);
    }
    try {
      loadKastens(token);
    } catch (e) {
      console.error('[home] loadKastens failed:', e);
    }
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

  // Single canonical title fallback — never render a bare "Untitled" for a
  // zettel whose summary has not produced a real title yet.
  var PENDING_TITLE = 'Summarizing…';

  function homeDisplayTitle(node) {
    return (node && node.titleReady && node.name) ? node.name : PENDING_TITLE;
  }

  async function loadZettels(token) {
    try {
      var resp = await fetch('/api/zettels', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      var data = await resp.json();
      var zettels = Array.isArray(data.zettels) ? data.zettels : [];
      var nodes = zettels.map(function (z) {
        var rawTitle = (z.title || '').trim();
        return {
          id: z.id,
          name: rawTitle,
          titleReady: z.title_ready !== false && Boolean(rawTitle),
          group: z.source_type || 'web',
          url: z.source_url || '',
          date: (z.added_at || '').slice(0, 10),
          summary: z.brief_summary || '',
          description: z.detailed_summary || z.brief_summary || '',
          tags: Array.isArray(z.tags) ? z.tags : []
        };
      });

      // Sort by capture date descending
      nodes.sort(function (a, b) {
        return (b.date || '').localeCompare(a.date || '');
      });

      // Update KG stats panel
      var kgNodeCount = document.getElementById('kg-node-count');
      if (kgNodeCount) kgNodeCount.textContent = nodes.length;

      // Show only latest 3 zettels in the preview
      renderCards(nodes.slice(0, 3), nodes.length);
    } catch (e) {
      console.error('[home] Zettels load failed:', e);
      renderCards([], 0);
    }
  }

  // "Open original source" link, rendered inside the card meta row. Card body
  // click opens the summary popup; this button is the only nav affordance.
  function homeGotoBtnHtml(url) {
    var safe = toSafeHttpUrl(url);
    if (!safe) return '';
    return '<a class="home-card-goto-btn" href="' + escapeHtml(safe) + '" ' +
        'target="_blank" rel="noopener noreferrer" ' +
        'title="Open original source" aria-label="Open original source">' +
        '<img src="/artifacts/icon-external-link.svg" alt="Open" />' +
        '<span class="tooltip">Open original source</span>' +
      '</a>';
  }

  function attachHomeCardInteraction(card, node) {
    card.addEventListener('click', function (e) {
      // Goto button is a native anchor — let it navigate, don't open popup.
      if (e.target.closest('.home-card-goto-btn')) {
        e.stopPropagation();
        return;
      }
      openSummaryPopup(node);
    });
    card.addEventListener('keydown', function (e) {
      if ((e.key === 'Enter' || e.key === ' ') && e.target === card) {
        e.preventDefault();
        openSummaryPopup(node);
      }
    });
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
      var card = document.createElement('div');
      card.className = 'home-card';
      card.setAttribute('role', 'link');
      card.tabIndex = 0;
      card.style.animationDelay = (i * 0.08) + 's';

      var sourceClass = (node.group || 'web').toLowerCase();
      if (!node.titleReady) card.className += ' home-card-pending';

      card.innerHTML =
        '<h3 class="home-card-title">' + escapeHtml(homeDisplayTitle(node)) + '</h3>' +
        '<div class="home-card-meta">' +
          (node.date ? '<span class="home-card-date">' + escapeHtml(node.date) + '</span>' : '') +
          '<span class="home-card-source ' + sourceClass + '">' + escapeHtml(node.group || 'web') + '</span>' +
          homeGotoBtnHtml(node.url) +
        '</div>';

      // Card body click opens the summary popup; goto button navigates.
      attachHomeCardInteraction(card, node);

      cardGrid.appendChild(card);
    });
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Summary popup rendering — mirror of user_zettels (source of truth).
  // Keep this block verbatim with website/features/user_zettels/js/user_zettels.js
  // so the popup is visually and behaviorally identical on both pages.
  // ─────────────────────────────────────────────────────────────────

  function renderDualSummary(container, parts) {
    container.innerHTML = '';
    var brief = (parts && parts.brief) ? String(parts.brief).trim() : '';
    var detailed = (parts && parts.detailed) ? String(parts.detailed).trim() : '';
    var structured = (parts && isStructuredDetailed(parts.detailedStructured))
      ? parts.detailedStructured
      : null;
    var hasBrief = brief && brief !== 'No summary available for this zettel.';
    var hasDetailed = structured
      ? true
      : (detailed && detailed !== brief && detailed !== 'No summary available for this zettel.');

    if (!hasBrief && !hasDetailed) {
      container.textContent = 'No summary available for this zettel.';
      return;
    }

    if (hasBrief) {
      var briefWrap = document.createElement('div');
      briefWrap.className = 'zettels-summary-section zettels-summary-brief';
      var briefHeading = document.createElement('h3');
      briefHeading.className = 'zettels-summary-section-heading';
      briefHeading.textContent = 'Brief';
      var briefBody = document.createElement('p');
      briefBody.className = 'zettels-summary-section-body';
      briefBody.textContent = brief;
      briefWrap.appendChild(briefHeading);
      briefWrap.appendChild(briefBody);
      container.appendChild(briefWrap);
    }

    if (hasDetailed) {
      if (hasBrief) {
        var divider = document.createElement('hr');
        divider.className = 'zettels-summary-divider';
        container.appendChild(divider);
      }
      var detailedWrap = document.createElement('div');
      detailedWrap.className = 'zettels-summary-section zettels-summary-detailed';
      var detailedHeading = document.createElement('h3');
      detailedHeading.className = 'zettels-summary-section-heading';
      detailedHeading.textContent = 'Detailed';
      detailedWrap.appendChild(detailedHeading);
      if (structured) {
        renderStructuredDetailed(detailedWrap, structured);
      } else {
        renderMarkdownLite(detailedWrap, detailed);
      }
      container.appendChild(detailedWrap);
    }
  }

  function isStructuredDetailed(value) {
    if (!Array.isArray(value) || value.length === 0) return false;
    for (var i = 0; i < value.length; i++) {
      var section = value[i];
      if (!section || typeof section !== 'object' || Array.isArray(section)) return false;
      if (!('heading' in section || 'bullets' in section || 'sub_sections' in section || 'subSections' in section)) {
        return false;
      }
    }
    return true;
  }

  function coerceStructuredDetailed(value) {
    if (value == null) return null;
    if (isStructuredDetailed(value)) return value;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      var wrapped = [value];
      if (isStructuredDetailed(wrapped)) return wrapped;
    }
    if (typeof value !== 'string') return null;
    var trimmed = value.trim();
    if (!trimmed) return null;
    if (trimmed.charAt(0) === '[' || trimmed.charAt(0) === '{') {
      var attempts = [trimmed];
      if (trimmed.indexOf("'") !== -1) attempts.push(trimmed.replace(/'/g, '"'));
      for (var i = 0; i < attempts.length; i++) {
        try {
          var parsed = JSON.parse(attempts[i]);
          if (isStructuredDetailed(parsed)) return parsed;
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            var wrappedParsed = [parsed];
            if (isStructuredDetailed(wrappedParsed)) return wrappedParsed;
          }
        } catch (err) { void err; }
      }
    }
    if (trimmed.indexOf('## ') !== -1 || trimmed.indexOf('### ') !== -1) {
      var sections = parseMarkdownToSections(trimmed);
      if (sections && sections.length) return sections;
    }
    return null;
  }

  function parseMarkdownToSections(markdown) {
    var lines = String(markdown || '').split(/\r?\n/);
    var sections = [];
    var current = null;
    var subHeading = null;
    function ensureCurrent() {
      if (!current) { current = { heading: 'Overview', bullets: [], sub_sections: {} }; sections.push(current); }
      return current;
    }
    function pushBullet(text) {
      var c = ensureCurrent();
      if (subHeading) {
        if (!c.sub_sections[subHeading]) c.sub_sections[subHeading] = [];
        c.sub_sections[subHeading].push(text);
      } else {
        c.bullets.push(text);
      }
    }
    for (var i = 0; i < lines.length; i++) {
      var raw = lines[i];
      var line = raw.replace(/\s+$/, '');
      if (!line.trim()) continue;
      var h2 = line.match(/^##\s+(.*)$/);
      var h3 = line.match(/^###\s+(.*)$/);
      var bullet = line.match(/^\s*[-*]\s+(.*)$/);
      if (h2) {
        current = { heading: h2[1].trim(), bullets: [], sub_sections: {} };
        sections.push(current);
        subHeading = null;
        continue;
      }
      if (h3) {
        subHeading = h3[1].trim();
        ensureCurrent();
        continue;
      }
      if (bullet) {
        pushBullet(bullet[1].trim());
        continue;
      }
      pushBullet(line.trim());
    }
    return sections.length ? sections : null;
  }

  var RAW_HEADING_MAP = {
    'thesis': 'Core argument',
    'core_argument': 'Core argument',
    'issue_thesis': 'Core argument',
    'chapters_or_segments': 'Chapter walkthrough',
    'chapter_walkthrough': 'Chapter walkthrough',
    'demonstrations': 'Demonstrations',
    'closing_takeaway': 'Closing remarks',
    'closing_remarks': 'Closing remarks',
    'publication_identity': 'Publication identity',
    'sections': 'Sections',
    'conclusions_or_recommendations': 'Conclusions & recommendations',
    'cta': 'Call to action',
    'stance': 'Stance',
    'overview': 'Overview',
    'format': 'Format',
    'format_and_speakers': 'Format and speakers'
  };

  function prettyHeading(raw) {
    if (!raw) return raw;
    var key = String(raw).trim().toLowerCase();
    if (RAW_HEADING_MAP.hasOwnProperty(key)) return RAW_HEADING_MAP[key];
    return String(raw)
      .replace(/_+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/^\w/, function (c) { return c.toUpperCase(); });
  }

  function stripTimestampPrefix(label) {
    if (!label) return label;
    return String(label)
      .replace(/^\s*\[?\d{1,2}(?::\d{2}){1,2}\]?\s*[—\-:]\s*/, '')
      .replace(/^\s*\[?\d{1,2}(?::\d{2}){1,2}\]?\s+/, '')
      .replace(/^\s*\d{4}\s*[—\-]\s*/, '')
      .trim();
  }

  function expandChapterJsonBullets(section) {
    var bullets = Array.isArray(section.bullets) ? section.bullets : [];
    if (!bullets.length) return section;
    var subs = {};
    var leftover = [];
    bullets.forEach(function (b) {
      if (typeof b !== 'string') { leftover.push(b); return; }
      var t = b.trim();
      if (t.charAt(0) !== '{') { leftover.push(b); return; }
      try {
        var parsed = JSON.parse(t);
        if (parsed && typeof parsed === 'object') {
          var title = stripTimestampPrefix(String(parsed.title || '').trim());
          if (!title) { leftover.push(b); return; }
          var sub = Array.isArray(parsed.bullets) ? parsed.bullets.filter(Boolean).map(String) : [];
          if (!sub.length && parsed.summary) sub = [String(parsed.summary)];
          var key = title;
          var idx = 2;
          while (Object.prototype.hasOwnProperty.call(subs, key)) { key = title + ' (' + idx + ')'; idx += 1; }
          subs[key] = sub;
          return;
        }
      } catch (e) { void e; }
      leftover.push(b);
    });
    if (!Object.keys(subs).length) return section;
    var merged = {};
    if (section.sub_sections && typeof section.sub_sections === 'object') {
      Object.keys(section.sub_sections).forEach(function (k) { merged[k] = section.sub_sections[k]; });
    }
    Object.keys(subs).forEach(function (k) { merged[k] = subs[k]; });
    return {
      heading: section.heading,
      bullets: leftover,
      sub_sections: merged
    };
  }

  function normalizeRawSchemaSections(sections) {
    if (!Array.isArray(sections)) return sections;
    var out = [];
    sections.forEach(function (section) {
      if (!section || typeof section !== 'object') return;
      var rawKey = String(section.heading || '').trim().toLowerCase();
      if (rawKey === 'format') return;
      var working = expandChapterJsonBullets(section);
      var prettySubs = {};
      var subs = working.sub_sections && typeof working.sub_sections === 'object' ? working.sub_sections : {};
      Object.keys(subs).forEach(function (sk) {
        var cleanSk = stripTimestampPrefix(prettyHeading(sk));
        prettySubs[cleanSk || sk] = subs[sk];
      });
      out.push({
        heading: prettyHeading(working.heading || ''),
        bullets: Array.isArray(working.bullets) ? working.bullets : [],
        sub_sections: prettySubs
      });
    });
    return out;
  }

  function buildChevronSpan() {
    var span = document.createElement('span');
    span.className = 'zettels-summary-h2-chevron';
    span.setAttribute('aria-hidden', 'true');
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none">' +
      '<path d="M6 9L12 15L18 9" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"></path></svg>';
    return span;
  }

  function setSectionExpanded(headingEl, panelEl, expanded) {
    headingEl.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    if (expanded) {
      panelEl.removeAttribute('data-collapsed');
      panelEl.style.maxHeight = '0px';
      requestAnimationFrame(function () {
        var target = panelEl.scrollHeight;
        panelEl.style.maxHeight = target + 'px';
      });
      var clearMax = function () {
        panelEl.style.maxHeight = '';
        panelEl.removeEventListener('transitionend', clearMax);
      };
      panelEl.addEventListener('transitionend', clearMax);
    } else {
      var current = panelEl.scrollHeight;
      panelEl.style.maxHeight = current + 'px';
      requestAnimationFrame(function () {
        panelEl.setAttribute('data-collapsed', 'true');
        panelEl.style.maxHeight = '0px';
      });
    }
  }

  function attachToggle(headingEl, panelEl) {
    headingEl.setAttribute('role', 'button');
    headingEl.setAttribute('tabindex', '0');
    headingEl.setAttribute('aria-expanded', 'true');
    var sectionId = 'zk-sec-' + Math.random().toString(36).slice(2, 9);
    panelEl.id = sectionId;
    headingEl.setAttribute('aria-controls', sectionId);

    var handler = function (event) {
      var expanded = headingEl.getAttribute('aria-expanded') === 'true';
      setSectionExpanded(headingEl, panelEl, !expanded);
      event.preventDefault();
    };
    headingEl.addEventListener('click', handler);
    headingEl.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
        handler(event);
      }
    });
  }

  function renderStructuredDetailed(container, sections) {
    sections = normalizeRawSchemaSections(sections) || sections;
    var firstSectionRendered = false;
    sections.forEach(function (section) {
      if (!section || typeof section !== 'object') return;
      var heading = section.heading == null ? '' : String(section.heading).trim();

      var bullets = Array.isArray(section.bullets) ? section.bullets : [];
      var subs = section.sub_sections || section.subSections;
      var hasSubs = subs && typeof subs === 'object' && !Array.isArray(subs)
        && Object.keys(subs).length > 0;

      if (!heading) {
        appendSectionBody(container, bullets, subs, hasSubs);
        return;
      }

      var h4 = document.createElement('h4');
      h4.className = 'zettels-summary-h2';
      var labelSpan = document.createElement('span');
      labelSpan.className = 'zettels-summary-h2-label';
      labelSpan.textContent = heading;
      h4.appendChild(labelSpan);
      h4.appendChild(buildChevronSpan());
      container.appendChild(h4);

      var panel = document.createElement('div');
      panel.className = 'zettels-summary-panel';
      appendSectionBody(panel, bullets, subs, hasSubs);
      container.appendChild(panel);

      attachToggle(h4, panel);
      if (firstSectionRendered) {
        h4.setAttribute('aria-expanded', 'false');
        panel.setAttribute('data-collapsed', 'true');
        panel.style.maxHeight = '0px';
      }
      firstSectionRendered = true;
    });
  }

  function appendSectionBody(parent, bullets, subs, hasSubs) {
    if (bullets && bullets.length) {
      var ul = document.createElement('ul');
      ul.className = 'zettels-summary-list';
      bullets.forEach(function (bullet) {
        var text = bullet == null ? '' : String(bullet).trim();
        if (!text) return;
        var li = document.createElement('li');
        li.className = 'zettels-summary-list-item';
        li.textContent = text;
        ul.appendChild(li);
      });
      if (ul.childNodes.length) parent.appendChild(ul);
    }
    if (hasSubs) {
      Object.keys(subs).forEach(function (subHeading) {
        var subBullets = subs[subHeading];
        if (!Array.isArray(subBullets) || !subBullets.length) return;
        var h5 = document.createElement('h5');
        h5.className = 'zettels-summary-h3';
        h5.textContent = String(subHeading || '').trim();
        parent.appendChild(h5);

        var subUl = document.createElement('ul');
        subUl.className = 'zettels-summary-list';
        subBullets.forEach(function (bullet) {
          var text = bullet == null ? '' : String(bullet).trim();
          if (!text) return;
          var li = document.createElement('li');
          li.className = 'zettels-summary-list-item';
          li.textContent = text;
          subUl.appendChild(li);
        });
        if (subUl.childNodes.length) parent.appendChild(subUl);
      });
    }
  }

  function renderMarkdownLite(container, markdown) {
    markdown = normalizeSummaryMarkdown(markdown);
    var lines = String(markdown || '').split(/\r?\n/);
    var paraBuf = [];
    var listStack = null;
    var currentTarget = container;
    var firstH2Seen = false;

    function flushPara() {
      if (!paraBuf.length) return;
      var joined = paraBuf.join(' ').trim();
      if (joined) {
        var p = document.createElement('p');
        p.className = 'zettels-summary-para';
        p.textContent = joined;
        currentTarget.appendChild(p);
      }
      paraBuf = [];
    }
    function closeList() { listStack = null; }

    for (var i = 0; i < lines.length; i++) {
      var trimmed = lines[i].replace(/\s+$/, '');
      if (!trimmed.trim()) { flushPara(); closeList(); continue; }
      var h3 = trimmed.match(/^###\s+(.*)$/);
      var h2 = trimmed.match(/^##\s+(.*)$/);
      var bullet = trimmed.match(/^\s*[-*]\s+(.*)$/);
      if (h2) {
        flushPara(); closeList();
        var h4 = document.createElement('h4');
        h4.className = 'zettels-summary-h2';
        var lbl = document.createElement('span');
        lbl.className = 'zettels-summary-h2-label';
        lbl.textContent = h2[1].trim();
        h4.appendChild(lbl);
        h4.appendChild(buildChevronSpan());
        container.appendChild(h4);
        var panel = document.createElement('div');
        panel.className = 'zettels-summary-panel';
        container.appendChild(panel);
        attachToggle(h4, panel);
        if (firstH2Seen) {
          h4.setAttribute('aria-expanded', 'false');
          panel.setAttribute('data-collapsed', 'true');
          panel.style.maxHeight = '0px';
        }
        firstH2Seen = true;
        currentTarget = panel;
        continue;
      }
      if (h3) {
        flushPara(); closeList();
        var h5 = document.createElement('h5');
        h5.className = 'zettels-summary-h3';
        h5.textContent = h3[1].trim();
        currentTarget.appendChild(h5);
        continue;
      }
      if (bullet) {
        flushPara();
        if (!listStack) {
          listStack = { el: document.createElement('ul') };
          listStack.el.className = 'zettels-summary-list';
          currentTarget.appendChild(listStack.el);
        }
        var li = document.createElement('li');
        li.className = 'zettels-summary-list-item';
        li.textContent = bullet[1].trim();
        listStack.el.appendChild(li);
        continue;
      }
      closeList();
      paraBuf.push(trimmed.trim());
    }
    flushPara();
    closeList();
  }

  function normalizeSummaryMarkdown(markdown) {
    return String(markdown || '')
      .replace(/(\S)[ \t]+(#{2,6})[ \t]+(?=\S)/g, '$1\n\n$2 ')
      .replace(/^(#{2,6} .+?)[ \t]+#+[ \t]*$/gm, '$1');
  }

  function extractSummaryParts(rawSummary) {
    var isPlainObject = rawSummary && typeof rawSummary === 'object' && !Array.isArray(rawSummary);
    var rawInput = rawSummary == null ? '' : (typeof rawSummary === 'string' ? rawSummary : '');
    var rawText = normalizeSummaryText(rawInput);
    var parsed = isPlainObject ? rawSummary : tryParseSummaryObject(rawInput);

    if (parsed) {
      var rawDetailed = parsed.detailed_summary != null ? parsed.detailed_summary : parsed.detailedSummary;
      var structuredDetailed = coerceStructuredDetailed(rawDetailed);

      var briefFromParsed = normalizeSummaryText(
        parsed.brief_summary || parsed.briefSummary || parsed.one_line_summary || parsed.summary || ''
      );
      var detailedFromParsed = structuredDetailed
        ? ''
        : normalizeSummaryText(rawDetailed || parsed.summary || '');

      var resolvedBrief = briefFromParsed || detailedFromParsed;
      var resolvedDetailed = detailedFromParsed || briefFromParsed;
      if (resolvedBrief || resolvedDetailed || structuredDetailed) {
        return {
          brief: resolvedBrief || 'No summary available for this zettel.',
          detailed: resolvedDetailed || resolvedBrief || 'No summary available for this zettel.',
          detailedStructured: structuredDetailed
        };
      }
    }

    var fallback = rawText || 'No summary available for this zettel.';
    return { brief: fallback, detailed: fallback, detailedStructured: null };
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
    if (value != null && typeof value === 'object') return '';
    var text = String(value || '')
      .replace(/\r\n/g, '\n')
      .replace(/\\n/g, '\n')
      .replace(/\\r/g, '\r')
      .replace(/\\t/g, '\t')
      .trim();
    if (!opts.preserveEscapedQuotes) {
      text = text.replace(/\\"/g, '"');
    }
    if (/^(\[object Object\](,\s*)?)+$/.test(text)) return '';
    return text;
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

  // ── My Zettels badge (UX-8) ──────────────────────────────────────
  // The header badge was set once at render time and drifted from the
  // authoritative count returned by /api/zettels as the user added
  // zettels. We now refetch on add success and on stale interaction.

  var _badgeUpdatedAt = 0;
  var BADGE_TTL_MS = 60 * 1000;
  var _badgeRefreshing = false;
  var _badgeListenersBound = false;

  async function refreshMyZettelsBadge(token) {
    if (_badgeRefreshing) return;
    _badgeRefreshing = true;
    try {
      var resp = await fetch('/api/zettels', {
        credentials: 'include',
        headers: { 'Authorization': 'Bearer ' + token }
      });
      if (!resp.ok) return;
      var data = await resp.json();
      var count = Array.isArray(data.zettels) ? data.zettels.length : 0;
      var badge = document.getElementById('zettel-count');
      if (badge) badge.textContent = count;
      var kgN = document.getElementById('kg-node-count');
      if (kgN) kgN.textContent = count;
      _badgeUpdatedAt = Date.now();
    } catch (e) {
      console.warn('[home] badge refresh failed', e);
    } finally {
      _badgeRefreshing = false;
    }
  }

  function bindBadgeFreshness(token) {
    if (_badgeListenersBound) return;
    _badgeListenersBound = true;
    _badgeUpdatedAt = Date.now();
    function maybeRefresh() {
      if (Date.now() - _badgeUpdatedAt > BADGE_TTL_MS) {
        refreshMyZettelsBadge(token);
      }
    }
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') maybeRefresh();
    });
    var vault = document.getElementById('home-vault');
    if (vault) vault.addEventListener('click', maybeRefresh);
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

  async function addZettel(url, token, existingPricingActionId, file) {
    var isDocument = Boolean(file);
    var pricingActionId = existingPricingActionId || (isDocument && window.ZKAddZettel && typeof window.ZKAddZettel.makeActionId === 'function'
      ? window.ZKAddZettel.makeActionId('home-document')
      : 'zettel:' + Date.now() + ':' + Math.random().toString(36).slice(2));
    if (addError) addError.textContent = '';
    // UX-2: immediate progress feedback — disable + spinner label + busy attr.
    var addWrapEl = document.getElementById('add-zettel-wrap');
    var _origSubmitLabel = null;
    if (addSubmitBtn) {
      addSubmitBtn.disabled = true;
      _origSubmitLabel = addSubmitBtn.textContent;
      addSubmitBtn.innerHTML = '<span class="btn-inline-spinner" aria-hidden="true"></span>Summarizing…';
      addSubmitBtn.setAttribute('aria-busy', 'true');
    }
    if (addWrapEl) addWrapEl.setAttribute('data-busy', 'true');
    // UX-2 bonus: clarifying message after 30s if still in flight.
    var _slowMsgTimer = setTimeout(function () {
      if (addError && addWrapEl && addWrapEl.getAttribute('data-busy') === 'true') {
        addError.textContent = 'Still working… large pages can take up to 60 s.';
      }
    }, 30000);
    function _restoreAddButton() {
      clearTimeout(_slowMsgTimer);
      if (addSubmitBtn) {
        addSubmitBtn.disabled = false;
        addSubmitBtn.textContent = _origSubmitLabel || 'Add';
        addSubmitBtn.removeAttribute('aria-busy');
      }
      if (addWrapEl) addWrapEl.removeAttribute('data-busy');
    }

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

    // PR #39 / Wave-2 D5: typewriter is attached once the skeleton lands
    // in the DOM (below). A late-binding closure preserves API-call
    // parallelism: the first onStatus tick fires after the network
    // round-trip (>80ms), by which point the skeleton is already mounted.
    var typer = null;
    var onStatus = function (tick) {
      if (typer) { try { typer.update(tick); } catch (e) { void e; } }
    };

    // Start API call immediately (runs in parallel with animation)
    var apiPromise = isDocument
      ? window.ZKAddZettel.uploadDocument({
        file: file,
        token: token,
        clientActionId: pricingActionId,
        persist: true,
        surface: 'home',
        onStatus: onStatus
      })
      : window.ZKAddZettel.add({
        url: url,
        token: token,
        clientActionId: pricingActionId,
        persist: true,
        surface: 'home',
        onStatus: onStatus
      });

    // PR #40 L2' (2026-05-21): optimistic UI — derive source-type from
    // the submitted URL (or "document" if file upload) and render the
    // meta row with REAL chips at t=0. Title remains a skeleton line
    // because the LLM-generated title is the actual unknown. Linear/
    // GitHub pattern: user sees "their card" the moment they hit add,
    // not 2 minutes later.
    var _h_url = String(url || '').trim().toLowerCase();
    var _h_isDoc = Boolean(file);
    var _h_source = (function () {
      if (_h_isDoc) return 'document';
      if (!_h_url) return 'web';
      if (/(^|\/\/)(www\.)?(youtube\.com|youtu\.be|m\.youtube\.com)\b/.test(_h_url)) return 'youtube';
      if (/(^|\/\/)(www\.)?github\.com\b/.test(_h_url)) return 'github';
      if (/(^|\/\/)(www\.)?(reddit\.com|old\.reddit\.com|redd\.it)\b/.test(_h_url)) return 'reddit';
      if (/(^|\/\/)([^./]+\.)?substack\.com\b/.test(_h_url)) return 'substack';
      if (/(^|\/\/)(www\.)?medium\.com\b/.test(_h_url)) return 'medium';
      return 'web';
    })();
    var _h_sourceLabel = (_h_source === 'web')
      ? 'Web'
      : _h_source.charAt(0).toUpperCase() + _h_source.slice(1);
    var _h_date = new Date().toISOString().slice(0, 10);

    // Create skeleton now — it'll be revealed seamlessly during shatter
    var skeleton = document.createElement('div');
    skeleton.className = 'home-card home-card-skeleton';
    skeleton.style.opacity = '0';
    skeleton.style.transition = 'opacity 0.4s ease';
    skeleton.innerHTML =
      '<div class="skeleton-line skeleton-title"></div>' +
      '<div class="home-card-meta">' +
        '<span class="home-card-date">' + escapeHtml(_h_date) + '</span>' +
        '<span class="home-card-source ' + _h_source + '">' +
          escapeHtml(_h_sourceLabel) +
        '</span>' +
      '</div>';

    // Replace spacer with hidden skeleton before shatter starts
    if (cardGrid && spacer.parentNode) {
      cardGrid.replaceChild(skeleton, spacer);
      while (cardGrid.children.length > 3) {
        cardGrid.removeChild(cardGrid.lastChild);
      }
    }
    if (window.ZKSkeletonTyper) {
      typer = window.ZKSkeletonTyper.attach(skeleton);
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
    clearSelectedDocument();

    try {
      var envelope = await apiPromise;
      var result = envelope.summary || {};
      result.node_id = envelope.node_id;
      result.workspace_zettel_id = envelope.workspace_zettel_id;
      result.persistence = envelope.persistence;

      // Morph skeleton into real card
      var today = new Date().toISOString().slice(0, 10);
      var sourceType = (result.source_type || 'web').toLowerCase();
      var rawTitle = (result.title || '').trim();
      var newNode = {
        name: rawTitle,
        // Degraded/metadata-only extractions can finalize with an empty
        // title — render the neutral pending state, never "Untitled".
        titleReady: Boolean(rawTitle),
        date: today,
        group: sourceType,
        url: result.source_url || url || '',
        summary: JSON.stringify({
          brief_summary: result.brief_summary || '',
          detailed_summary: result.summary || result.brief_summary || ''
        }),
        tags: result.tags || []
      };

      var realCard = document.createElement('div');
      realCard.className = 'home-card home-card-new'
        + (newNode.titleReady ? '' : ' home-card-pending');
      realCard.setAttribute('role', 'link');
      realCard.tabIndex = 0;

      realCard.innerHTML =
        '<h3 class="home-card-title">' + escapeHtml(homeDisplayTitle(newNode)) + '</h3>' +
        '<div class="home-card-meta">' +
          '<span class="home-card-date">' + escapeHtml(newNode.date) + '</span>' +
          '<span class="home-card-source ' + sourceType + '">' + escapeHtml(newNode.group) + '</span>' +
          homeGotoBtnHtml(newNode.url) +
        '</div>';

      attachHomeCardInteraction(realCard, newNode);

      // PR #40 (2026-05-21): smooth skeleton -> real card crossfade. Detach
      // the typewriter first so its caret doesn't blink during the fade,
      // then fade the skeleton out (250ms) and replace with the realCard
      // carrying the .is-fading-in animation (280ms). Background tasks
      // (lazy enrichment chunk_embed, KG population) keep running in the
      // worker independently — the user sees the polished card immediately
      // while RAG/KG fill in.
      if (typer) { try { typer.detach(); } catch (te) { void te; } }
      realCard.classList.add('is-fading-in');
      if (cardGrid && skeleton.parentNode) {
        skeleton.classList.add('is-fading-out');
        var _hSkel = skeleton, _hReal = realCard;
        window.setTimeout(function () {
          if (_hSkel && _hSkel.parentNode) {
            _hSkel.parentNode.replaceChild(_hReal, _hSkel);
            window.setTimeout(function () {
              _hReal.classList.remove('is-fading-in');
            }, 320);
          }
        }, 250);
      }

      var count = parseInt(zettelCount.textContent || '0', 10) + 1;
      zettelCount.textContent = count;
      // UX-2: clear any slow-message that may have appeared in-flight.
      if (addError) addError.textContent = '';
      // UX-8: refresh the My Zettels badge authoritatively from /api/zettels.
      refreshMyZettelsBadge(token);
      // Authoritative reconcile: re-pull the preview grid so the optimistic
      // card is replaced by the persisted /api/zettels row — picks up the
      // real title if this add finalized with a pending/empty one.
      // loadZettels catches its own errors.
      window.setTimeout(function () { loadZettels(token); }, 6000);
    } catch (e) {
      // The optimistic add did not land — tear the skeleton down immediately on
      // ANY error (incl. quota_exhausted) so it never orphans if the user
      // dismisses the quota gate without paying/watching ads. A resume re-runs
      // addZettel() which creates a fresh skeleton.
      if (typer) { try { typer.detach(); } catch (te) { void te; } }
      if (skeleton.parentNode) skeleton.parentNode.removeChild(skeleton);
      var quotaDetail = e && e.detail && e.detail.code === 'quota_exhausted' ? e.detail : null;
      if (quotaDetail && window.ZKQuotaGate) {
        await window.ZKQuotaGate.show({
          detail: quotaDetail,
          source: 'home:add-zettel',
          resumeAction: { type: 'add_zettel', url: url, clientActionId: pricingActionId },
          onResume: function () { return addZettel(url, token, pricingActionId, file); }
        });
        return;
      }
      // ADR-1: graceful poll-exhaust. Backend is still running (reaper window
      // is wider than the poll budget). Show a visible pending placeholder
      // card and reconcile the preview grid in the background.
      if (e && e.code === 'poll_exhausted') {
        if (addError) {
          addError.textContent = 'Still summarizing in the background — it\'ll appear in My Zettels automatically.';
        }
        var pendingCard = document.createElement('a');
        pendingCard.className = 'home-card home-card-pending';
        pendingCard.href = '#';
        pendingCard.innerHTML =
          '<h3 class="home-card-title">' + escapeHtml(PENDING_TITLE) + '</h3>' +
          '<div class="home-card-meta">' +
            '<span class="home-card-date">' + escapeHtml(new Date().toISOString().slice(0, 10)) + '</span>' +
          '</div>';
        if (cardGrid) {
          cardGrid.insertBefore(pendingCard, cardGrid.firstChild);
          if (emptyState) emptyState.classList.add('hidden');
        }
        var clearPending = function () {
          if (pendingCard && pendingCard.parentNode) {
            pendingCard.parentNode.removeChild(pendingCard);
          }
        };
        if (window.ZKAddZettel && typeof window.ZKAddZettel.continueInBackground === 'function') {
          window.ZKAddZettel.continueInBackground(e.operationId, token, function (envelope) {
            clearPending();
            if (envelope) { try { loadZettels(token); } catch (le) { void le; } }
          });
        } else {
          window.setTimeout(function () {
            clearPending();
            try { loadZettels(token); } catch (le) { void le; }
          }, 30000);
        }
        refreshMyZettelsBadge(token);
      } else {
        if (addError) addError.textContent = e.message;
        if (addZettelDropdown) addZettelDropdown.classList.add('open');
      }
    } finally {
      _restoreAddButton();
    }
  }

  // ── Summary Popup ────────────────────────────────────────────────

  function openSummaryPopup(node) {
    var loader = document.getElementById('summary-loader');
    var overlay = document.getElementById('summary-overlay');
    var sourceEl = document.getElementById('summary-source');
    var dateEl = document.getElementById('summary-date');
    var title = document.getElementById('summary-title');
    var text = document.getElementById('summary-text');
    var tags = document.getElementById('summary-tags');
    if (!overlay) return;

    // Mirror user_zettels openSummary: date pill (mono) THEN source pill, both
    // in the meta-row above the title. Source class drives the badge color.
    var sourceClass = (node.group || node.source || 'web').toLowerCase();
    var sourceLabel = node.group || node.source || 'web';
    if (sourceEl) {
      sourceEl.className = 'home-card-source ' + sourceClass;
      sourceEl.textContent = sourceLabel;
    }
    if (dateEl) {
      dateEl.className = 'home-card-date';
      if (node.date) {
        dateEl.textContent = formatDate(node.date);
        dateEl.style.display = '';
      } else {
        dateEl.textContent = '';
        dateEl.style.display = 'none';
      }
    }
    title.textContent = homeDisplayTitle(node);

    // Pass the raw summary blob through the same extractor user_zettels uses
    // (now structured-aware). One extraction yields brief + detailed +
    // detailedStructured — no need to call it twice on different fields.
    var primary = node.summary || node.description || '';
    var parts = extractSummaryParts(primary);
    if (!parts.detailedStructured && node.description && node.description !== primary) {
      var alt = extractSummaryParts(node.description);
      if (alt && (alt.detailedStructured || (alt.detailed && alt.detailed !== parts.detailed))) {
        parts.detailed = alt.detailed || parts.detailed;
        parts.detailedStructured = alt.detailedStructured || parts.detailedStructured;
      }
    }
    renderDualSummary(text, {
      brief: parts.brief,
      detailed: parts.detailed,
      detailedStructured: parts.detailedStructured
    });

    var _mathSrc = (node.group || node.source || '').toLowerCase();
    _maskPriceDollars(text);
    _mathRenderArxiv(text, _mathSrc);
    _unmaskPriceDollars(text);

    tags.innerHTML = '';
    var nodeTags = node.tags || [];
    nodeTags.forEach(function (tag) {
      var el = document.createElement('span');
      el.className = 'zettels-tag';
      el.textContent = '#' + tag;
      tags.appendChild(el);
    });

    if (window.ZkRefreshButton && typeof window.ZkRefreshButton.setCurrentNode === 'function') {
      window.ZkRefreshButton.setCurrentNode(node);
    }

    // Show loader animation first
    setBodyScrollLocked(true);
    if (loader) {
      loader.classList.add('active');
      setTimeout(function () {
        loader.classList.remove('active');
        overlay.classList.remove('hidden');
      }, 1500);
    } else {
      overlay.classList.remove('hidden');
    }
  }

  function closeSummaryPopup() {
    var overlay = document.getElementById('summary-overlay');
    if (overlay) overlay.classList.add('hidden');
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
    // Re-entry guard: init() can be re-invoked (DOMContentLoaded vs immediate
    // call vs auth-state change) and each call would otherwise stack a fresh
    // document/body/menu listener — clicking Sign out would then fire signOut
    // N times. Per-element dataset.zkBound guards below still gate the
    // element-bound listeners, but the document/body delegated ones don't
    // have that, so guard the whole function.
    if (window.__homeBindEventsRan) return;
    window.__homeBindEventsRan = true;
    // Avatar dropdown toggle — IDs are home-namespaced (D-2) so header.js binds
    // only header's #avatar-btn; the dataset.zkBound guard remains for re-init safety.
    if (avatarBtn && !avatarBtn.dataset.zkBound) {
      avatarBtn.dataset.zkBound = '1';
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

    // Profile menu item → navigate to /profile (href takes over; close dropdown
    // so the transition feels clean). Avatar picker has moved to /profile.
    if (menuProfile) {
      menuProfile.addEventListener('click', function () {
        avatarDropdown.classList.remove('open');
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

    // Add Zettel toggle — bound via event delegation on document.body so the
    // handler survives async re-renders (e.g. avatar/auth state landing after
    // initial paint replaces the toolbar DOM and would orphan a direct
    // getElementById listener). Filter by data-action so the listener only
    // ever fires on the real Add button.
    document.body.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-action="add-zettel"]');
      if (!btn) return;
      e.stopPropagation();
      var dropdown = document.getElementById('add-zettel-dropdown');
      if (!dropdown) return;
      dropdown.classList.toggle('open');
      var urlInput = document.getElementById('add-url-input');
      if (dropdown.classList.contains('open') && urlInput) {
        urlInput.focus();
      }
    });

    if (addDocumentBtn && addDocumentInput) {
      addDocumentBtn.addEventListener('click', function () {
        addDocumentInput.click();
      });
      addDocumentInput.addEventListener('change', function () {
        var file = getSelectedDocument();
        if (addError) addError.textContent = '';
        addDocumentBtn.classList.toggle('has-file', Boolean(file));
        if (addUrlInput && file) {
          addUrlInput.value = '';
          addUrlInput.placeholder = file.name || 'Document selected';
        }
      });
    }

    if (addUrlInput) {
      addUrlInput.addEventListener('input', function () {
        if (addUrlInput.value.trim()) clearSelectedDocument();
      });
    }

    // Add Zettel form submit
    if (addZettelForm) {
      addZettelForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var url = addUrlInput ? addUrlInput.value.trim() : '';
        var file = getSelectedDocument();
        var err = file ? validateDocument(file) : (!url ? 'Please enter a URL or choose a document' : null);
        if (err) {
          if (addError) addError.textContent = err;
          return;
        }
        if (!window.ZKAddZettel || typeof window.ZKAddZettel.add !== 'function' || typeof window.ZKAddZettel.uploadDocument !== 'function') {
          if (addError) addError.textContent = 'Add Zettel API helper failed to load. Please refresh and try again.';
          return;
        }
        addZettel(url, token, null, file);
      });
    }

    // Summary popup close
    var summaryClose = document.getElementById('summary-close');
    var summaryBackdrop = document.getElementById('summary-backdrop');
    if (summaryClose) summaryClose.addEventListener('click', closeSummaryPopup);
    if (summaryBackdrop) summaryBackdrop.addEventListener('click', closeSummaryPopup);

    // Refresh + Download buttons (handlers live in refresh_button feature).
    if (window.ZkRefreshButton && typeof window.ZkRefreshButton.bind === 'function') {
      window.ZkRefreshButton.bind({
        onRefreshed: function (payload) {
          if (!payload) return;
          var title = document.getElementById('summary-title');
          var text = document.getElementById('summary-text');
          var tags = document.getElementById('summary-tags');
          if (title && payload.title) title.textContent = payload.title;
          if (text) {
            var parts = extractSummaryParts({
              brief_summary: payload.brief_summary || '',
              detailed_summary: payload.detailed_summary || payload.summary || ''
            });
            renderDualSummary(text, parts);
            var src = (payload.source_type || '').toLowerCase();
            _maskPriceDollars(text);
            _mathRenderArxiv(text, src);
            _unmaskPriceDollars(text);
          }
          if (tags && Array.isArray(payload.tags)) {
            tags.innerHTML = '';
            payload.tags.forEach(function (tag) {
              var el = document.createElement('span');
              el.className = 'zettels-tag';
              el.textContent = '#' + tag;
              tags.appendChild(el);
            });
          }
        }
      });
    }

    // Avatar modal close
    if (avatarModalClose) avatarModalClose.addEventListener('click', closeAvatarPicker);
    if (avatarModalOverlay) avatarModalOverlay.addEventListener('click', closeAvatarPicker);

    // Escape key closes modals
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeSummaryPopup();
        closeAvatarPicker();
        if (avatarDropdown) avatarDropdown.classList.remove('open');
        // m-8: keep aria-expanded in sync with the visible state so AT users
        // hear the dropdown collapse when Escape closes it.
        if (avatarBtn) avatarBtn.setAttribute('aria-expanded', 'false');
        if (addZettelDropdown) {
          addZettelDropdown.classList.remove('open');
        }
      }
    });

    // Create Kasten modal
    setupCreateKastenModal(token);

    // UX-8: refresh badge on stale interaction (60 s TTL).
    bindBadgeFreshness(token);
  }

  // ── Create Kasten Modal ───────────────────────────────────────────

  var _createKastenNodes = [];
  var _createKastenNodesLoaded = false;
  var _createKastenNodesFetchedAt = 0;
  var _createKastenSelectedIds = new Set();
  var _createKastenInflight = null;
  var ALL_KASTEN_SOURCES = ['youtube', 'github', 'reddit', 'substack', 'medium', 'twitter', 'web', 'generic'];
  var KASTEN_CHOOSER_TTL_MS = 5000;

  function setupCreateKastenModal(token) {
    var overlay = document.getElementById('create-kasten-overlay');
    var form = document.getElementById('create-kasten-form');
    var nameInput = document.getElementById('kasten-name');
    var descInput = document.getElementById('kasten-desc');
    var errEl = document.getElementById('create-kasten-error');
    var submit = document.getElementById('create-kasten-submit');
    var sourcePanel = document.getElementById('kasten-scope-source-panel');
    var specificPanel = document.getElementById('kasten-scope-specific-panel');
    var zettelSearch = document.getElementById('kasten-zettel-search');
    if (!overlay || !form) return;

    function openModal() {
      // UX-5: paint the modal SHELL synchronously before doing any data work.
      // Prior code's chooser-build / graph-fetch happened on the same tick
      // and pushed first-paint to ~12 s; now everything async runs after rAF.
      errEl.textContent = '';
      form.reset();
      _createKastenSelectedIds = new Set();
      if (sourcePanel) sourcePanel.classList.add('hidden');
      if (specificPanel) specificPanel.classList.add('hidden');
      overlay.classList.remove('hidden');
      setBodyScrollLocked(true);
      // Show a placeholder in the (still-hidden) chooser so when the user
      // toggles the Specific radio there's visible feedback immediately.
      var listEl = document.getElementById('kasten-zettel-list');
      if (listEl && (!_createKastenNodesLoaded || _createKastenNodes.length === 0)) {
        listEl.innerHTML = '<div class="create-kasten-zettel-loading"><span class="btn-inline-spinner" aria-hidden="true"></span>Loading zettels…</div>';
      }
      setTimeout(function () { nameInput && nameInput.focus(); }, 30);
      // Defer the network fetch to the next frame so the modal paints first.
      requestAnimationFrame(function () {
        var ageMs = Date.now() - _createKastenNodesFetchedAt;
        if (!_createKastenNodesLoaded || ageMs > KASTEN_CHOOSER_TTL_MS) {
          loadCreateKastenNodes(token).then(function () {
            if (specificPanel && !specificPanel.classList.contains('hidden')) {
              renderCreateKastenZettelList(zettelSearch ? zettelSearch.value : '');
            }
          });
        }
      });
    }
    function closeModal() {
      overlay.classList.add('hidden');
      setBodyScrollLocked(false);
    }

    // Bind Create Kasten via event delegation so the click survives any
    // async toolbar re-render (the direct getElementById listener went stale
    // when auth resolved after initial paint and replaced the button node).
    document.body.addEventListener('click', function (e) {
      if (e.target.closest('[data-action="create-kasten"]')) openModal();
    });
    overlay.addEventListener('click', function (e) {
      if (e.target.hasAttribute('data-close-kasten')) closeModal();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !overlay.classList.contains('hidden')) closeModal();
    });

    // Scope radio toggle
    form.querySelectorAll('input[name="kasten-scope"]').forEach(function (r) {
      r.addEventListener('change', async function () {
        var v = r.value;
        if (sourcePanel) sourcePanel.classList.toggle('hidden', v !== 'source');
        if (specificPanel) specificPanel.classList.toggle('hidden', v !== 'specific');
        if (v === 'specific') {
          if (!_createKastenNodesLoaded) {
            await loadCreateKastenNodes(token);
          }
          renderCreateKastenZettelList(zettelSearch ? zettelSearch.value : '');
        }
      });
    });

    if (zettelSearch) {
      zettelSearch.addEventListener('input', function () {
        renderCreateKastenZettelList(zettelSearch.value || '');
      });
    }

    // UX-3: explicit Refresh button in the chooser header.
    var refreshBtn = document.getElementById('kasten-chooser-refresh');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', async function () {
        refreshBtn.disabled = true;
        try {
          await loadCreateKastenNodes(token, { force: true });
          renderCreateKastenZettelList(zettelSearch ? zettelSearch.value : '');
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
      var quality = (form.querySelector('input[name="kasten-quality"]:checked') || {}).value || 'fast';
      var desc = (descInput.value || '').trim();
      var scope = (form.querySelector('input[name="kasten-scope"]:checked') || {}).value || 'all';
      var pricingActionId = form.getAttribute('data-pricing-action-id') || ('kasten:' + Date.now() + ':' + Math.random().toString(36).slice(2));
      form.setAttribute('data-pricing-action-id', pricingActionId);

      var pickedSources = [];
      if (scope === 'source') {
        form.querySelectorAll('input[name="kasten-source"]:checked').forEach(function (c) { pickedSources.push(c.value); });
        if (!pickedSources.length) { errEl.textContent = 'Select at least one source type'; return; }
      }
      var pickedNodeIds = [];
      if (scope === 'specific') {
        pickedNodeIds = Array.from(_createKastenSelectedIds);
        if (!pickedNodeIds.length) { errEl.textContent = 'Select at least one zettel'; return; }
      }

      // UX-6: prevent re-submit while busy + spinner glyph + data-busy.
      if (submit.disabled) return;
      submit.disabled = true;
      submit.setAttribute('aria-busy', 'true');
      submit.innerHTML = '<span class="btn-inline-spinner" aria-hidden="true"></span>Creating Kasten…';
      form.setAttribute('data-busy', 'true');
      try {
        var resp = await fetch('/api/rag/sandboxes', {
          method: 'POST',
          headers: {
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ name: name, description: desc || null, default_quality: quality, client_action_id: pricingActionId })
        });
        if (!resp.ok) {
          var detail = '';
          var raw = '';
          try { raw = await resp.text(); } catch(_) {}
          try { var j = JSON.parse(raw); detail = (j && (j.detail || j.error)) || ''; } catch (_) {}
          console.error('[create-kasten] failed', resp.status, raw);
          if (detail && detail.code === 'quota_exhausted' && window.ZKQuotaGate) {
            await window.ZKQuotaGate.show({
              detail: detail,
              source: 'home:create-kasten',
              resumeAction: { type: 'create_kasten', name: name, description: desc, scope: scope, clientActionId: pricingActionId },
              onResume: function () {
                form.setAttribute('data-pricing-action-id', pricingActionId);
                form.requestSubmit();
              }
            });
            return;
          }
          if (resp.status === 409) errEl.textContent = 'A kasten with that name already exists';
          else if (resp.status === 401) errEl.textContent = 'Please sign in again';
          else errEl.textContent = (detail && detail.message) || detail || ('Create failed (' + resp.status + ')');
          return;
        }
        var created = await resp.json();
        var sandboxId = created && created.sandbox && created.sandbox.id;

        if (sandboxId) {
          var memberBody = null;
          if (scope === 'all') memberBody = { source_types: ALL_KASTEN_SOURCES, added_via: 'bulk_source' };
          else if (scope === 'source') memberBody = { source_types: pickedSources, added_via: 'bulk_source' };
          else if (scope === 'specific') memberBody = { node_ids: pickedNodeIds, added_via: 'manual' };
          if (memberBody) {
            try {
              var addResp = await fetch('/api/rag/sandboxes/' + encodeURIComponent(sandboxId) + '/members', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
                body: JSON.stringify(memberBody)
              });
              if (!addResp.ok) {
                var addRaw = '';
                try { addRaw = await addResp.text(); } catch(_) {}
                console.warn('[create-kasten] add members failed', addResp.status, addRaw);
              }
            } catch (addErr) {
              console.warn('[create-kasten] add members network error', addErr);
            }
          }
        }

        closeModal();
        await loadKastens(token);
      } catch (err) {
        console.error('[home] Create kasten failed:', err);
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

  async function loadCreateKastenNodes(token, opts) {
    opts = opts || {};
    // Reuse an in-flight request so concurrent callers (open + radio toggle)
    // don't double-fetch.
    if (_createKastenInflight && !opts.force) return _createKastenInflight;
    _createKastenInflight = (async function () {
      try {
        // UX-3: source the chooser from /api/zettels so newly-added
        // zettels are always present (the dedicated per-user list).
        var resp = await fetch('/api/zettels', {
          credentials: 'include',
          headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!resp.ok) {
          console.warn('[create-kasten] load zettels failed', resp.status);
          _createKastenNodes = [];
        } else {
          var data = await resp.json();
          var zettels = Array.isArray(data.zettels) ? data.zettels : [];
          // Normalize to the shape renderCreateKastenZettelList expects:
          // {id, name, source_type, summary}.
          _createKastenNodes = zettels.map(function (z) {
            return {
              id: z.id,
              name: z.title || z.id,
              source_type: z.source_type || 'web',
              summary: z.brief_summary || ''
            };
          });
        }
      } catch (e) {
        console.warn('[create-kasten] load graph err', e);
        _createKastenNodes = [];
      }
      _createKastenNodesLoaded = true;
      _createKastenNodesFetchedAt = Date.now();
    })();
    try {
      await _createKastenInflight;
    } finally {
      _createKastenInflight = null;
    }
  }

  function renderCreateKastenZettelList(query) {
    var list = document.getElementById('kasten-zettel-list');
    if (!list) return;
    var q = (query || '').trim().toLowerCase();
    var filtered = _createKastenNodes.filter(function (n) {
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
      var checked = _createKastenSelectedIds.has(n.id) ? 'checked' : '';
      row.innerHTML =
        '<input type="checkbox" data-node-id="' + escapeHtml(n.id) + '" ' + checked + ' />' +
        '<div class="create-kasten-zettel-body">' +
          '<div class="create-kasten-zettel-title">' + escapeHtml(n.name || n.id) + '</div>' +
          '<div class="create-kasten-zettel-meta">' + escapeHtml(n.source_type || 'web') + '</div>' +
        '</div>';
      var cb = row.querySelector('input');
      cb.addEventListener('change', function () {
        if (cb.checked) _createKastenSelectedIds.add(n.id);
        else _createKastenSelectedIds.delete(n.id);
      });
      list.appendChild(row);
    });
  }

  // ── Start ─────────────────────────────────────────────────────────

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
