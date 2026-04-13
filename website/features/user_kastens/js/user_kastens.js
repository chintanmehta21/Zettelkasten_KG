(function () {
  'use strict';

  var state = {
    token: '',
    sandboxes: [],
    selectedSandboxId: '',
    nodes: [],
    focusNodeId: '',
    focusNodeTitle: '',
    latestSearchRequestId: 0,
    latestSelectionRequestId: 0,
  };

  var els = {};

  function q(id) {
    return document.getElementById(id);
  }

  async function init() {
    resolveDom();
    var params = new URLSearchParams(window.location.search);
    state.focusNodeId = params.get('focus_node') || '';
    state.focusNodeTitle = params.get('focus_title') || '';
    try {
      var token = await getAuthToken();
      if (!token) {
        window.location.href = '/';
        return;
      }
      state.token = token;
      bindEvents();
      await refreshSandboxes();
      if (state.focusNodeTitle) {
        els.searchInput.value = state.focusNodeTitle;
        setFeedback('Focused note ready to add: ' + state.focusNodeTitle + '.', false);
      }
      await searchNodes(state.focusNodeTitle || '');
    } catch (err) {
      setFeedback(toErrorMessage(err, 'Unable to load your kastens right now.'), true);
    }
  }

  function resolveDom() {
    els.kastensList = q('kastens-list');
    els.kastensEmpty = q('kastens-empty');
    els.kastenCount = q('kasten-count');
    els.memberCount = q('member-count');
    els.defaultQuality = q('default-quality');
    els.detailTitle = q('detail-title');
    els.detailSubtitle = q('detail-subtitle');
    els.form = q('kasten-form');
    els.name = q('kasten-name');
    els.description = q('kasten-description');
    els.icon = q('kasten-icon');
    els.color = q('kasten-color');
    els.quality = q('kasten-quality');
    els.feedback = q('kasten-feedback');
    els.newDraft = q('new-kasten-btn');
    els.deleteBtn = q('delete-kasten-btn');
    els.openChat = q('open-chat-btn');
    els.createBtn = q('create-kasten-btn');
    els.searchInput = q('node-search');
    els.searchResults = q('node-search-results');
    els.memberList = q('member-list');
  }

  async function getAuthToken() {
    try {
      var configResp = await fetch('/api/auth/config');
      var config = await configResp.json();
      if (!config.supabase_url || !config.supabase_anon_key) return '';
      var client = supabase.createClient(config.supabase_url, config.supabase_anon_key, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          storage: window.localStorage,
          storageKey: 'zk-auth-token',
        },
      });
      var sessionResult = await client.auth.getSession();
      return sessionResult && sessionResult.data && sessionResult.data.session
        ? sessionResult.data.session.access_token
        : '';
    } catch (err) {
      console.error('[user_kastens] auth init failed', err);
      return '';
    }
  }

  function bindEvents() {
    els.form.addEventListener('submit', onSaveSandbox);
    els.newDraft.addEventListener('click', resetDraft);
    els.createBtn.addEventListener('click', resetDraft);
    els.deleteBtn.addEventListener('click', onDeleteSandbox);
    els.searchInput.addEventListener('input', debounce(function () {
      searchNodes(els.searchInput.value.trim());
    }, 220));
  }

  async function refreshSandboxes(selectId) {
    var payload = await api('/api/rag/sandboxes');
    state.sandboxes = payload.sandboxes || [];
    renderSandboxCards();
    updateStats();

    var targetId = selectId || state.selectedSandboxId || (state.sandboxes[0] && state.sandboxes[0].id) || '';
    if (targetId) {
      await selectSandbox(targetId);
    } else {
      resetDraft();
    }
  }

  function updateStats() {
    var totalMembers = state.sandboxes.reduce(function (sum, sandbox) {
      return sum + Number(sandbox.member_count || 0);
    }, 0);
    els.kastenCount.textContent = String(state.sandboxes.length);
    els.memberCount.textContent = String(totalMembers);
    els.defaultQuality.textContent = state.sandboxes[0] ? state.sandboxes[0].default_quality : 'fast';
  }

  function renderSandboxCards() {
    els.kastensList.innerHTML = '';
    if (!state.sandboxes.length) {
      els.kastensEmpty.classList.remove('hidden');
      return;
    }
    els.kastensEmpty.classList.add('hidden');

    state.sandboxes.forEach(function (sandbox) {
      var card = document.createElement('article');
      card.className = 'kastens-card' + (sandbox.id === state.selectedSandboxId ? ' active' : '');
      card.dataset.sandboxId = sandbox.id;
      card.tabIndex = 0;
      card.setAttribute('role', 'button');
      card.setAttribute('aria-pressed', sandbox.id === state.selectedSandboxId ? 'true' : 'false');
      card.innerHTML = [
        '<div class="kastens-card-head">',
        '  <span class="kastens-icon-pill" style="box-shadow: inset 0 0 0 1px ' + sanitizeColorToken(sandbox.color) + '33;">' + escapeHtml((sandbox.icon || 'stack').slice(0, 12)) + '</span>',
        '  <span class="kastens-count-pill">' + escapeHtml(String(sandbox.member_count || 0)) + ' members</span>',
        '</div>',
        '<div>',
        '  <h3>' + escapeHtml(sandbox.name) + '</h3>',
        '  <p>' + escapeHtml(sandbox.description || 'No description yet.') + '</p>',
        '</div>',
        '<div class="kastens-card-foot">',
        '  <span class="kastens-source-pill">' + escapeHtml((sandbox.default_quality || 'fast').toUpperCase()) + '</span>',
        '  <button class="kastens-mini-btn" type="button" data-open-chat="' + escapeHtml(sandbox.id) + '">Chat</button>',
        '</div>'
      ].join('');

      card.addEventListener('click', function (event) {
        var chatTrigger = event.target.closest('[data-open-chat]');
        if (chatTrigger) {
          event.stopPropagation();
          window.location.href = '/home/rag?sandbox_id=' + encodeURIComponent(sandbox.id);
          return;
        }
        selectSandbox(sandbox.id);
      });
      card.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          selectSandbox(sandbox.id);
        }
      });
      els.kastensList.appendChild(card);
    });
  }

  async function selectSandbox(sandboxId) {
    var requestId = ++state.latestSelectionRequestId;
    state.selectedSandboxId = sandboxId;
    renderSandboxCards();
    try {
      var payload = await api('/api/rag/sandboxes/' + encodeURIComponent(sandboxId));
      if (requestId !== state.latestSelectionRequestId || sandboxId !== state.selectedSandboxId) {
        return;
      }
      populateForm(payload.sandbox);
      renderMembers(payload.members || []);
    } catch (err) {
      if (requestId === state.latestSelectionRequestId) {
        setFeedback(toErrorMessage(err, 'Unable to load this kasten.'), true);
      }
    }
  }

  function populateForm(sandbox) {
    els.detailTitle.textContent = sandbox.name;
    els.detailSubtitle.textContent = sandbox.description || 'Keep refining this workspace before you open the chat surface.';
    els.name.value = sandbox.name || '';
    els.description.value = sandbox.description || '';
    els.icon.value = sandbox.icon || 'stack';
    els.color.value = sanitizeColorToken(sandbox.color);
    els.quality.value = sandbox.default_quality || 'fast';
    els.deleteBtn.classList.remove('hidden');
    els.newDraft.classList.remove('hidden');
    els.openChat.classList.remove('hidden');
    els.openChat.href = '/home/rag?sandbox_id=' + encodeURIComponent(sandbox.id);
    setFeedback('Selected ' + sandbox.name + '.', false);
  }

  function renderMembers(members) {
    els.memberList.innerHTML = '';
    if (!members.length) {
      els.memberList.innerHTML = '<div class="kastens-empty"><h3>No members yet</h3><p>Search your zettels above and add the ones you want this kasten to own.</p></div>';
      return;
    }

    members.forEach(function (member) {
      var node = member.node || {};
      var row = document.createElement('div');
      row.className = 'kastens-member-row';
      row.innerHTML = [
        '<div>',
        '  <h3>' + escapeHtml(node.name || member.node_id) + '</h3>',
        '  <p>' + escapeHtml((node.summary || 'No summary available.').slice(0, 140)) + '</p>',
        '</div>',
        '<div class="kastens-member-actions">',
        '  <span class="kastens-source-pill">' + escapeHtml(String(node.source_type || 'web')) + '</span>',
        '  <button class="kastens-mini-btn danger" type="button">Remove</button>',
        '</div>'
      ].join('');
      row.querySelector('button').addEventListener('click', function () {
        removeMember(member.node_id);
      });
      els.memberList.appendChild(row);
    });
  }

  async function searchNodes(query) {
    var requestId = ++state.latestSearchRequestId;
    var url = '/api/rag/nodes?limit=12';
    if (query) {
      url += '&query=' + encodeURIComponent(query);
    }
    try {
      var payload = await api(url);
      if (requestId !== state.latestSearchRequestId) {
        return;
      }
      state.nodes = payload.nodes || [];
      renderSearchResults();
    } catch (err) {
      if (requestId === state.latestSearchRequestId) {
        state.nodes = [];
        renderSearchResults();
        setFeedback(toErrorMessage(err, 'Unable to search your zettels right now.'), true);
      }
    }
  }

  function renderSearchResults() {
    els.searchResults.innerHTML = '';
    if (!state.nodes.length) {
      els.searchResults.innerHTML = '<div class="kastens-empty"><h3>No zettels found</h3><p>Try a different query or add more notes first.</p></div>';
      return;
    }

    var nodes = state.nodes.slice().sort(function (left, right) {
      if (left.id === state.focusNodeId) return -1;
      if (right.id === state.focusNodeId) return 1;
      return 0;
    });

    nodes.forEach(function (node) {
      var row = document.createElement('div');
      row.className = 'kastens-node-row';
      row.innerHTML = [
        '<div>',
        '  <h3>' + escapeHtml(node.name || node.id) + '</h3>',
        '  <p>' + escapeHtml((node.summary || 'No summary available.').slice(0, 150)) + '</p>',
        '</div>',
        '<div class="kastens-node-actions">',
        (node.id === state.focusNodeId ? '  <span class="kastens-source-pill">Focused</span>' : ''),
        '  <span class="kastens-source-pill">' + escapeHtml(String(node.source_type || 'web')) + '</span>',
        '  <button class="kastens-mini-btn" type="button">Add</button>',
        '</div>'
      ].join('');
      row.querySelector('button').addEventListener('click', function () {
        addNodeToSandbox(node.id);
      });
      els.searchResults.appendChild(row);
    });
  }

  async function addNodeToSandbox(nodeId) {
    if (!state.selectedSandboxId) {
      setFeedback('Create or select a kasten first.', true);
      return;
    }
    try {
      await api('/api/rag/sandboxes/' + encodeURIComponent(state.selectedSandboxId) + '/members', {
        method: 'POST',
        body: JSON.stringify({ node_ids: [nodeId], added_via: 'manual' })
      });
      await selectSandbox(state.selectedSandboxId);
      setFeedback('Node added to the kasten.', false);
    } catch (err) {
      setFeedback(toErrorMessage(err, 'Unable to add that zettel right now.'), true);
    }
  }

  async function removeMember(nodeId) {
    try {
      await api('/api/rag/sandboxes/' + encodeURIComponent(state.selectedSandboxId) + '/members/' + encodeURIComponent(nodeId), {
        method: 'DELETE'
      });
      await selectSandbox(state.selectedSandboxId);
      setFeedback('Node removed from the kasten.', false);
    } catch (err) {
      setFeedback(toErrorMessage(err, 'Unable to remove that zettel right now.'), true);
    }
  }

  async function onSaveSandbox(event) {
    event.preventDefault();
    var body = {
      name: els.name.value.trim(),
      description: els.description.value.trim(),
      icon: els.icon.value.trim() || 'stack',
      color: els.color.value.trim() || '#14b8a6',
      default_quality: els.quality.value
    };
    if (!body.name) {
      setFeedback('Please name the kasten before saving.', true);
      return;
    }
    body.color = sanitizeColorToken(body.color);

    try {
      if (state.selectedSandboxId) {
        await api('/api/rag/sandboxes/' + encodeURIComponent(state.selectedSandboxId), {
          method: 'PATCH',
          body: JSON.stringify(body)
        });
        setFeedback('Kasten updated.', false);
        await refreshSandboxes(state.selectedSandboxId);
        return;
      }

      var payload = await api('/api/rag/sandboxes', {
        method: 'POST',
        body: JSON.stringify(body)
      });
      setFeedback('Kasten created.', false);
      await refreshSandboxes(payload.sandbox.id);
    } catch (err) {
      setFeedback(toErrorMessage(err, 'Unable to save this kasten right now.'), true);
    }
  }

  async function onDeleteSandbox() {
    if (!state.selectedSandboxId) return;
    if (!window.confirm('Delete this kasten and its session links?')) return;
    try {
      await api('/api/rag/sandboxes/' + encodeURIComponent(state.selectedSandboxId), { method: 'DELETE' });
      state.selectedSandboxId = '';
      setFeedback('Kasten deleted.', false);
      await refreshSandboxes();
    } catch (err) {
      setFeedback(toErrorMessage(err, 'Unable to delete this kasten right now.'), true);
    }
  }

  function resetDraft() {
    state.selectedSandboxId = '';
    renderSandboxCards();
    els.detailTitle.textContent = 'Create or select a kasten';
    els.detailSubtitle.textContent = 'Set a name, describe the focus, then keep adding the zettels you want the chat to reason over.';
    els.form.reset();
    els.icon.value = 'stack';
    els.color.value = '#14b8a6';
    els.quality.value = 'fast';
    els.deleteBtn.classList.add('hidden');
    els.newDraft.classList.add('hidden');
    els.openChat.classList.add('hidden');
    els.memberList.innerHTML = '<div class="kastens-empty"><h3>No active kasten</h3><p>Select a card from the left or create a new one to start curating members.</p></div>';
    setFeedback('Draft reset.', false);
  }

  function setFeedback(message, isError) {
    els.feedback.textContent = message || '';
    els.feedback.style.color = isError ? 'var(--error)' : 'var(--text-secondary)';
  }

  async function api(url, options) {
    var response = await fetch(url, Object.assign({
      headers: {
        'Authorization': 'Bearer ' + state.token,
        'Content-Type': 'application/json'
      }
    }, options || {}));
    if (!response.ok) {
      var payload = await safeJson(response);
      var detail = payload && payload.detail ? payload.detail : 'Request failed';
      throw new Error(detail);
    }
    return safeJson(response);
  }

  async function safeJson(response) {
    try {
      return await response.json();
    } catch (err) {
      return {};
    }
  }

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = String(value || '');
    return div.innerHTML;
  }

  function debounce(fn, wait) {
    var timer = 0;
    return function () {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(null, args);
      }, wait);
    };
  }

  function sanitizeColorToken(value) {
    var candidate = String(value || '').trim();
    if (!candidate) return '#14b8a6';
    if (/^#[0-9a-fA-F]{3,8}$/.test(candidate)) return candidate;
    if (/^(rgb|rgba|hsl|hsla)\([\d\s.,%+-]+\)$/.test(candidate)) return candidate;
    return '#14b8a6';
  }

  function toErrorMessage(err, fallback) {
    return err && err.message ? err.message : fallback;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
