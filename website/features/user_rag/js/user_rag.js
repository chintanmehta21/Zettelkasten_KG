(function () {
  'use strict';

  var SOURCE_OPTIONS = ['youtube', 'github', 'reddit', 'substack', 'medium', 'web'];
  var HINT_KEY = 'zk-rag-hint-seen';
  var FEEDBACK_EMAIL = 'vedantbarbhaya21@gmail.com';

  var state = {
    token: '',
    sandboxes: [],
    sessionId: '',
    sandboxId: '',
    focusNodeId: '',
    focusNodeTitle: '',
    sources: [],
    currentAssistantCitations: [],
    lastUserContent: '',
    userNodes: [],
    sandboxMemberIds: new Set(),
    addModalSelected: new Set()
  };
  var els = {};

  function q(id) { return document.getElementById(id); }

  async function init() {
    resolveDom();
    renderSourceChips();
    bindEvents();
    state.token = await getAuthToken();
    if (!state.token) {
      window.location.href = '/';
      return;
    }

    var params = new URLSearchParams(window.location.search);
    // KAS-19: canonicalize to ?sandbox= and ?session= (accept legacy ?sandbox_id=/?session_id=).
    state.sandboxId = params.get('sandbox') || params.get('sandbox_id') || '';
    state.sessionId = params.get('session') || params.get('session_id') || '';
    state.focusNodeId = params.get('focus_node') || '';
    state.focusNodeTitle = params.get('focus_title') || '';
    if (state.focusNodeTitle) {
      els.input.placeholder = 'Ask about ' + state.focusNodeTitle + '...';
    }

    // KAS-7: hide persistent streaming hint after first session.
    try {
      if (window.localStorage && window.localStorage.getItem(HINT_KEY)) {
        els.hint.classList.add('hidden');
      }
    } catch (_) { /* localStorage may be blocked */ }

    await loadSandboxes();
    if (state.sessionId) {
      await loadSession(state.sessionId);
    }
    updateChatTitle();
    updateDocTitle();
  }

  function resolveDom() {
    els.qualitySelect = q('quality-select');
    els.tagsInput = q('tags-input');
    els.sourceGrid = q('source-grid');
    els.transcript = q('transcript');
    els.emptyState = q('empty-state');
    els.form = q('composer-form');
    els.input = q('composer-input');
    els.status = q('rag-status');
    els.chatTitle = q('chat-title');
    els.hint = q('rag-chat-hint');
    els.sendBtn = q('send-btn');
    // Header menu
    els.menuBtn = q('rag-menu-btn');
    els.menu = q('rag-menu');
    els.menuAdd = q('rag-menu-add');
    els.menuNewChat = q('rag-menu-new-chat');
    els.menuDelete = q('rag-menu-delete');
    // Add modal
    els.addModal = q('rag-add-modal');
    els.addList = q('rag-add-list');
    els.addSearch = q('rag-add-search');
    els.addHint = q('rag-add-modal-hint');
    els.addError = q('rag-add-modal-error');
    els.addSubmit = q('rag-add-submit');
    // Delete modal
    els.delModal = q('rag-delete-modal');
    els.delConfirm = q('rag-delete-confirm-check');
    els.delSubmit = q('rag-delete-submit');
    els.delError = q('rag-delete-modal-error');
    els.delText = q('rag-delete-modal-text');
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
      console.error('[user_rag] auth init failed', err);
      return '';
    }
  }

  function bindEvents() {
    els.form.addEventListener('submit', onAsk);

    // KAS-21/22: auto-grow textarea + Cmd/Ctrl+Enter to send.
    els.input.addEventListener('input', autoGrow);
    els.input.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        if (!els.sendBtn.disabled) els.form.requestSubmit();
      }
    });

    // 3-dot menu (KAS-12)
    els.menuBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      toggleMenu();
    });
    document.addEventListener('click', function (e) {
      if (!els.menu.contains(e.target) && e.target !== els.menuBtn) {
        closeMenu();
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeMenu();
        closeAddModal();
        closeDeleteModal();
      }
    });

    els.menuAdd.addEventListener('click', function () {
      closeMenu();
      openAddModal();
    });
    els.menuNewChat.addEventListener('click', function () {
      closeMenu();
      startNewSession();
    });
    els.menuDelete.addEventListener('click', function () {
      closeMenu();
      openDeleteModal();
    });

    // Modal close handlers
    Array.prototype.forEach.call(document.querySelectorAll('[data-close-add-modal]'), function (b) {
      b.addEventListener('click', closeAddModal);
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-close-delete-modal]'), function (b) {
      b.addEventListener('click', closeDeleteModal);
    });
    els.addModal.addEventListener('click', function (e) {
      if (e.target === els.addModal) closeAddModal();
    });
    els.delModal.addEventListener('click', function (e) {
      if (e.target === els.delModal) closeDeleteModal();
    });

    els.addSearch.addEventListener('input', renderAddList);
    els.addSubmit.addEventListener('click', submitAddZettels);
    els.delConfirm.addEventListener('change', function () {
      els.delSubmit.disabled = !els.delConfirm.checked;
    });
    els.delSubmit.addEventListener('click', submitDeleteKasten);
  }

  function autoGrow() {
    els.input.style.height = 'auto';
    var max = 184; // ~6 rows
    var target = Math.min(els.input.scrollHeight, max);
    els.input.style.height = target + 'px';
  }

  function toggleMenu() {
    var open = !els.menu.classList.contains('hidden');
    if (open) closeMenu(); else openMenu();
  }
  function openMenu() {
    els.menu.classList.remove('hidden');
    els.menuBtn.setAttribute('aria-expanded', 'true');
    // Hide Delete entry when no Kasten is selected.
    els.menuDelete.style.display = state.sandboxId ? '' : 'none';
  }
  function closeMenu() {
    els.menu.classList.add('hidden');
    els.menuBtn.setAttribute('aria-expanded', 'false');
  }

  function renderSourceChips() {
    els.sourceGrid.innerHTML = '';
    SOURCE_OPTIONS.forEach(function (source) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'rag-source-chip';
      chip.textContent = source;
      chip.dataset.source = source;
      chip.setAttribute('aria-pressed', 'false');
      chip.addEventListener('click', function () {
        var idx = state.sources.indexOf(source);
        if (idx >= 0) {
          state.sources.splice(idx, 1);
          chip.classList.remove('active');
          chip.setAttribute('aria-pressed', 'false');
        } else {
          state.sources.push(source);
          chip.classList.add('active');
          chip.setAttribute('aria-pressed', 'true');
        }
      });
      els.sourceGrid.appendChild(chip);
    });
  }

  async function loadSandboxes() {
    try {
      var payload = await api('/api/rag/sandboxes');
      state.sandboxes = payload.sandboxes || [];
    } catch (err) {
      console.warn('[user_rag] loadSandboxes failed', err);
      state.sandboxes = [];
    }
    // KAS-3: default Quality to current Kasten's default_quality if known.
    var current = currentSandbox();
    if (current && current.default_quality) {
      els.qualitySelect.value = current.default_quality;
    }
  }

  function currentSandbox() {
    if (!state.sandboxId) return null;
    return state.sandboxes.find(function (s) { return s.id === state.sandboxId; }) || null;
  }

  async function loadSession(sessionId) {
    try {
      state.sessionId = sessionId;
      setQueryParams();
      var sessionPayload = await api('/api/rag/sessions/' + encodeURIComponent(sessionId));
      var session = sessionPayload.session;
      if (session && session.sandbox_id) {
        state.sandboxId = session.sandbox_id;
      }
      if (session) {
        els.qualitySelect.value = session.quality_mode || els.qualitySelect.value || 'fast';
      }
      updateChatTitle();
      updateDocTitle();

      var payload = await api('/api/rag/sessions/' + encodeURIComponent(sessionId) + '/messages');
      renderMessages(payload.messages || []);
    } catch (err) {
      console.warn('[user_rag] loadSession failed', err);
      setStatus('Could not load this conversation.', true);
    }
  }

  function renderMessages(messages) {
    els.transcript.innerHTML = '';
    if (!messages.length) {
      resetTranscript();
      return;
    }
    els.emptyState.classList.add('hidden');
    var lastUserContent = '';
    messages.forEach(function (message) {
      if (message.role === 'user') lastUserContent = message.content || '';
      els.transcript.appendChild(createMessageNode(message.role, message.content, message.citations || [], message));
    });
    state.lastUserContent = lastUserContent;
    scrollTranscript();
  }

  function resetTranscript() {
    els.transcript.innerHTML = '';
    els.emptyState.classList.remove('hidden');
  }

  function verdictBadge(verdict) {
    if (!verdict) return '';
    var label = String(verdict).toLowerCase();
    var map = {
      grounded: { cls: 'grounded', text: '✅ Grounded' },
      partial: { cls: 'partial', text: '⚠ Partial' },
      unsupported: { cls: 'unsupported', text: '❌ Unsupported' }
    };
    var entry = map[label];
    if (!entry) return '';
    return '<span class="rag-verdict ' + entry.cls + '">' + entry.text + '</span>';
  }

  function createMessageNode(role, content, citations, meta) {
    var article = document.createElement('article');
    article.className = 'rag-message ' + role;

    var head = document.createElement('div');
    head.className = 'rag-message-head';
    var roleSpan = document.createElement('span');
    roleSpan.className = 'rag-message-role';
    roleSpan.textContent = role;
    var metaSpan = document.createElement('span');
    metaSpan.className = 'rag-message-meta';
    head.appendChild(roleSpan);
    head.appendChild(metaSpan);
    article.appendChild(head);

    var body = document.createElement('div');
    body.className = 'rag-message-body';
    body.textContent = content || '';
    article.appendChild(body);

    if (citations && citations.length) {
      article.appendChild(buildCitations(citations));
    }

    if (role === 'assistant' && meta && (meta.id || meta.content)) {
      // KAS-23: critic verdict.
      if (meta.critic_verdict) {
        var v = document.createElement('div');
        v.innerHTML = verdictBadge(meta.critic_verdict);
        if (v.firstChild) article.appendChild(v.firstChild);
      }
      // KAS-25: copy / regenerate / feedback row.
      if (content) {
        article.appendChild(buildActionsRow(meta, body));
      }
    }
    return article;
  }

  function buildCitations(citations) {
    var wrapper = document.createElement('div');
    wrapper.className = 'rag-citations';
    citations.forEach(function (citation) {
      var chip = document.createElement('span');
      chip.className = 'rag-citation-chip';
      chip.textContent = citation.title || citation.node_id || citation.id;
      wrapper.appendChild(chip);
    });
    return wrapper;
  }

  function buildActionsRow(meta, bodyEl) {
    var row = document.createElement('div');
    row.className = 'rag-msg-actions';

    var copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.title = 'Copy answer as Markdown';
    copyBtn.innerHTML = '<span aria-hidden="true">📋</span><span>Copy</span>';
    copyBtn.addEventListener('click', function () {
      var text = bodyEl.textContent || '';
      try {
        navigator.clipboard.writeText(text).then(function () {
          copyBtn.querySelector('span:last-child').textContent = 'Copied';
          setTimeout(function () { copyBtn.querySelector('span:last-child').textContent = 'Copy'; }, 1400);
        });
      } catch (_) {
        // Fallback: do nothing visible.
      }
    });
    row.appendChild(copyBtn);

    var regenBtn = document.createElement('button');
    regenBtn.type = 'button';
    regenBtn.title = 'Regenerate answer';
    regenBtn.innerHTML = '<span aria-hidden="true">↻</span><span>Regenerate</span>';
    regenBtn.addEventListener('click', function () {
      var prompt = state.lastUserContent || '';
      if (!prompt) return;
      els.input.value = prompt;
      autoGrow();
      els.form.requestSubmit();
    });
    row.appendChild(regenBtn);

    var upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.title = 'Helpful';
    upBtn.innerHTML = '<span aria-hidden="true">👍</span>';
    upBtn.addEventListener('click', function () { sendFeedback(meta, 'up', upBtn, downBtn); });
    row.appendChild(upBtn);

    var downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.title = 'Not helpful';
    downBtn.innerHTML = '<span aria-hidden="true">👎</span>';
    downBtn.addEventListener('click', function () { sendFeedback(meta, 'down', upBtn, downBtn); });
    row.appendChild(downBtn);

    return row;
  }

  function sendFeedback(meta, vote, upBtn, downBtn) {
    // No /api/rag/feedback endpoint exists yet — fall back to a mailto link
    // so users still have a path to flag answers. When the endpoint ships,
    // swap this for a POST.
    var subject = encodeURIComponent('[RAG feedback] ' + (vote === 'up' ? '👍 helpful' : '👎 not helpful'));
    var bodyText = 'Message id: ' + (meta && meta.id ? meta.id : 'n/a') + '\n'
      + 'Session id: ' + state.sessionId + '\n'
      + 'Sandbox id: ' + state.sandboxId + '\n'
      + 'Vote: ' + vote + '\n\n'
      + 'Notes:\n';
    var href = 'mailto:' + FEEDBACK_EMAIL + '?subject=' + subject + '&body=' + encodeURIComponent(bodyText);
    upBtn.classList.toggle('active', vote === 'up');
    downBtn.classList.toggle('active', vote === 'down');
    try { window.open(href, '_blank'); } catch (_) { /* noop */ }
  }

  async function onAsk(event) {
    event.preventDefault();
    var content = els.input.value.trim();
    if (!content) return;

    // KAS-7: mark hint seen after first ask.
    try { if (window.localStorage) window.localStorage.setItem(HINT_KEY, '1'); } catch (_) {}
    els.hint.classList.add('hidden');

    setStatus('Creating grounded answer...');
    els.emptyState.classList.add('hidden');
    setComposerBusy(true);

    var userNode = createMessageNode('user', content, [], {});
    var assistantNode = createMessageNode('assistant', '', [], {});
    state.lastUserContent = content;

    try {
      if (!state.sessionId) {
        await createSession();
      }

      els.transcript.appendChild(userNode);
      els.transcript.appendChild(assistantNode);
      state.currentAssistantCitations = [];
      scrollTranscript();
      els.input.value = '';
      autoGrow();

      var response = await fetch('/api/rag/sessions/' + encodeURIComponent(state.sessionId) + '/messages', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + state.token,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          content: content,
          quality: els.qualitySelect.value,
          scope_filter: buildScopeFilter(),
          stream: true
        })
      });

      if (!response.ok || !response.body) {
        var payload = await safeJson(response);
        var msg = (payload && (payload.detail && (payload.detail.message || payload.detail))) || 'The chat request failed.';
        throw new Error(typeof msg === 'string' ? msg : 'The chat request failed.');
      }

      await consumeSSE(response.body.getReader(), assistantNode);
    } catch (err) {
      rollbackPendingAssistant(assistantNode, userNode, err, content);
    } finally {
      setComposerBusy(false);
    }
  }

  async function createSession() {
    var payload = await api('/api/rag/sessions', {
      method: 'POST',
      body: JSON.stringify({
        sandbox_id: state.sandboxId || null,
        title: 'New conversation',
        quality: els.qualitySelect.value,
        scope_filter: buildScopeFilter()
      })
    });
    state.sessionId = payload.session.id;
    setQueryParams();
  }

  async function consumeSSE(reader, assistantNode) {
    var decoder = new TextDecoder();
    var buffer = '';
    while (true) {
      var result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });
      var parts = buffer.split('\n\n');
      buffer = parts.pop();
      parts.forEach(function (chunk) {
        handleSSEChunk(chunk, assistantNode);
      });
    }
    if (buffer.trim()) {
      handleSSEChunk(buffer, assistantNode);
    }
  }

  function handleSSEChunk(chunk, assistantNode) {
    if (!chunk.trim()) return;
    var payload = parseSSEPayload(chunk);
    if (!payload) return;
    var body = assistantNode.querySelector('.rag-message-body');

    if (payload.type === 'token') {
      body.textContent += payload.content || '';
      scrollTranscript();
      return;
    }
    if (payload.type === 'citations') {
      state.currentAssistantCitations = payload.citations || [];
      replaceCitations(assistantNode, state.currentAssistantCitations);
      return;
    }
    if (payload.type === 'replace') {
      body.textContent = payload.content || '';
      return;
    }
    if (payload.type === 'error') {
      renderInlineError(assistantNode, payload.message || 'The request failed.', state.lastUserContent);
      setStatus(payload.message || 'The request failed.', true);
      return;
    }
    if (payload.type === 'done') {
      var turn = payload.turn || {};
      body.textContent = turn.content || body.textContent;
      replaceCitations(assistantNode, turn.citations || state.currentAssistantCitations || []);
      assistantNode.querySelector('.rag-message-meta').textContent = turn.llm_model || '';
      // Clear any stale verdict / actions from a re-stream.
      Array.prototype.forEach.call(
        assistantNode.querySelectorAll('.rag-verdict, .rag-msg-actions'),
        function (n) { n.remove(); }
      );
      if (turn.critic_verdict) {
        var v = document.createElement('div');
        v.innerHTML = verdictBadge(turn.critic_verdict);
        if (v.firstChild) assistantNode.appendChild(v.firstChild);
      }
      if (body.textContent) {
        assistantNode.appendChild(buildActionsRow(turn, body));
      }
      setStatus('Answer complete.');
      return;
    }
  }

  function replaceCitations(assistantNode, citations) {
    var existing = assistantNode.querySelector('.rag-citations');
    if (existing) existing.remove();
    if (!citations || !citations.length) return;
    assistantNode.appendChild(buildCitations(citations));
  }

  function renderInlineError(assistantNode, message, retryContent) {
    var body = assistantNode.querySelector('.rag-message-body');
    body.classList.add('error');
    body.textContent = message;
    replaceCitations(assistantNode, []);
    Array.prototype.forEach.call(
      assistantNode.querySelectorAll('.rag-retry-btn, .rag-msg-actions, .rag-verdict'),
      function (n) { n.remove(); }
    );
    if (retryContent) {
      var retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'rag-retry-btn';
      retry.textContent = '↻ Retry';
      retry.addEventListener('click', function () {
        els.input.value = retryContent;
        autoGrow();
        els.form.requestSubmit();
      });
      body.appendChild(retry);
    }
  }

  function buildScopeFilter() {
    var tagValue = (els.tagsInput.value || '').trim();
    return {
      node_ids: state.focusNodeId ? [state.focusNodeId] : [],
      tags: tagValue ? tagValue.split(',').map(function (item) { return item.trim(); }).filter(Boolean) : [],
      tag_mode: 'any',
      source_types: state.sources.slice()
    };
  }

  function updateChatTitle() {
    var sandbox = currentSandbox();
    if (sandbox) {
      els.chatTitle.textContent = state.focusNodeTitle
        ? 'Ask ' + sandbox.name + ' about ' + state.focusNodeTitle + '.'
        : 'Ask ' + sandbox.name + ' something precise.';
    } else {
      els.chatTitle.textContent = state.focusNodeTitle
        ? 'Ask your knowledge graph about ' + state.focusNodeTitle + '.'
        : 'Ask your knowledge graph something precise.';
    }
  }

  function updateDocTitle() {
    var sandbox = currentSandbox();
    var name = sandbox ? sandbox.name : 'All zettels';
    document.title = 'Chat — ' + name + ' — Zettelkasten';
  }

  function startNewSession() {
    state.sessionId = '';
    setQueryParams();
    resetTranscript();
    setStatus('Ready.');
    els.input.focus();
  }

  function parseSSEPayload(chunk) {
    var lines = chunk.split('\n');
    var payloadLines = [];
    lines.forEach(function (line) {
      if (line.indexOf('data:') === 0) {
        payloadLines.push(line.replace(/^data:\s?/, ''));
      }
    });
    if (!payloadLines.length) return null;
    try {
      return JSON.parse(payloadLines.join('\n'));
    } catch (err) {
      console.warn('[user_rag] Ignoring malformed SSE payload', err);
      return null;
    }
  }

  function rollbackPendingAssistant(assistantNode, userNode, err, retryContent) {
    var msg = toErrorMessage(err, 'The chat request failed.');
    if (!assistantNode.isConnected && userNode.isConnected) {
      // Surface the error inline by appending a fresh assistant node.
      var failNode = createMessageNode('assistant', '', [], {});
      els.transcript.appendChild(failNode);
      renderInlineError(failNode, msg, retryContent);
    } else if (assistantNode.isConnected) {
      renderInlineError(assistantNode, msg, retryContent);
    }
    setStatus(msg, true);
    if (!els.transcript.children.length) {
      els.emptyState.classList.remove('hidden');
    }
  }

  function setComposerBusy(isBusy) {
    els.input.disabled = isBusy;
    els.qualitySelect.disabled = isBusy;
    els.tagsInput.disabled = isBusy;
    els.sendBtn.disabled = isBusy;
    Array.prototype.forEach.call(
      els.sourceGrid.querySelectorAll('.rag-source-chip'),
      function (chip) { chip.disabled = isBusy; }
    );
  }

  function toErrorMessage(err, fallback) {
    if (!err) return fallback;
    if (typeof err === 'string') return err;
    if (err.message) return err.message;
    return fallback;
  }

  function setQueryParams() {
    // KAS-19: emit only canonical names, drop legacy duplicates.
    var params = new URLSearchParams(window.location.search);
    params.delete('sandbox');
    params.delete('sandbox_id');
    params.delete('session');
    params.delete('session_id');
    if (state.sandboxId) params.set('sandbox', state.sandboxId);
    if (state.sessionId) params.set('session', state.sessionId);
    if (state.focusNodeId) params.set('focus_node', state.focusNodeId); else params.delete('focus_node');
    if (state.focusNodeTitle) params.set('focus_title', state.focusNodeTitle); else params.delete('focus_title');
    var next = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
    window.history.replaceState({}, '', next);
  }

  function setStatus(text, isError) {
    els.status.textContent = text;
    els.status.classList.toggle('error', !!isError);
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
      var detail = payload && (payload.detail || payload.error);
      var msg = typeof detail === 'string' ? detail
        : (detail && detail.message) ? detail.message
        : ('Request failed (' + response.status + ')');
      throw new Error(msg);
    }
    return safeJson(response);
  }

  async function safeJson(response) {
    try { return await response.json(); } catch (err) { return {}; }
  }

  function scrollTranscript() {
    els.transcript.scrollTop = els.transcript.scrollHeight;
  }

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = String(value || '');
    return div.innerHTML;
  }

  // ── Add-zettels modal ───────────────────────────────────────────

  async function openAddModal() {
    if (!state.sandboxId) {
      alert('Open a Kasten first to add zettels to it.');
      return;
    }
    state.addModalSelected = new Set();
    els.addError.classList.add('hidden');
    els.addError.textContent = '';
    els.addSearch.value = '';
    els.addHint.textContent = 'Loading your zettels…';
    els.addList.innerHTML = '';
    els.addSubmit.disabled = true;
    els.addSubmit.textContent = 'Add 0 zettels';
    els.addModal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';

    try {
      // Existing members so we can disable already-added rows.
      var membersResp = await api('/api/rag/sandboxes/' + encodeURIComponent(state.sandboxId) + '/members?limit=1000');
      state.sandboxMemberIds = new Set((membersResp.members || []).map(function (m) { return m.node_id; }));
    } catch (err) {
      console.warn('[user_rag] member load failed', err);
      state.sandboxMemberIds = new Set();
    }

    try {
      var graphResp = await fetch('/api/graph?view=my', {
        credentials: 'include',
        headers: { 'Authorization': 'Bearer ' + state.token }
      });
      if (!graphResp.ok) throw new Error('Could not load your zettels (' + graphResp.status + ').');
      var data = await graphResp.json();
      var nodes = (data.nodes || []).map(function (n) {
        return {
          id: n.id,
          name: n.name || n.title || n.id,
          source_type: n.group || n.source_type || 'web'
        };
      }).sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); });
      state.userNodes = nodes;
      els.addHint.textContent = nodes.length + ' zettels available. Already-added zettels are dimmed.';
      renderAddList();
    } catch (err) {
      els.addHint.textContent = '';
      els.addError.textContent = err.message || 'Failed to load zettels.';
      els.addError.classList.remove('hidden');
    }
  }

  function closeAddModal() {
    els.addModal.classList.add('hidden');
    document.body.style.overflow = '';
  }

  function renderAddList() {
    var query = (els.addSearch.value || '').trim().toLowerCase();
    els.addList.innerHTML = '';
    var visible = state.userNodes.filter(function (n) {
      return !query || (n.name || '').toLowerCase().indexOf(query) >= 0;
    });
    if (!visible.length) {
      var empty = document.createElement('li');
      empty.className = 'member';
      empty.textContent = 'No zettels match.';
      els.addList.appendChild(empty);
      return;
    }
    visible.forEach(function (node) {
      var li = document.createElement('li');
      var alreadyMember = state.sandboxMemberIds.has(node.id);
      if (alreadyMember) li.classList.add('member');
      var checked = state.addModalSelected.has(node.id);
      li.innerHTML =
        '<input type="checkbox" ' + (checked ? 'checked' : '') + (alreadyMember ? ' disabled' : '') + '>' +
        '<span class="rag-add-name">' + escapeHtml(node.name) + '</span>' +
        '<span class="rag-add-source">' + escapeHtml(node.source_type) + (alreadyMember ? ' · added' : '') + '</span>';
      var checkbox = li.querySelector('input');
      var toggle = function () {
        if (alreadyMember) return;
        if (state.addModalSelected.has(node.id)) {
          state.addModalSelected.delete(node.id);
          checkbox.checked = false;
        } else {
          state.addModalSelected.add(node.id);
          checkbox.checked = true;
        }
        updateAddSubmit();
      };
      li.addEventListener('click', function (e) {
        if (e.target !== checkbox) toggle();
        else updateAddSubmit();
      });
      els.addList.appendChild(li);
    });
    updateAddSubmit();
  }

  function updateAddSubmit() {
    var n = state.addModalSelected.size;
    els.addSubmit.disabled = n === 0;
    els.addSubmit.textContent = 'Add ' + n + ' zettel' + (n === 1 ? '' : 's');
  }

  async function submitAddZettels() {
    var ids = Array.from(state.addModalSelected);
    if (!ids.length) return;
    els.addSubmit.disabled = true;
    els.addError.classList.add('hidden');
    try {
      var resp = await fetch('/api/rag/sandboxes/' + encodeURIComponent(state.sandboxId) + '/members', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + state.token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_ids: ids, added_via: 'manual' })
      });
      if (!resp.ok) {
        var payload = await safeJson(resp);
        var detail = payload && (payload.detail || payload.error);
        throw new Error(typeof detail === 'string' ? detail : 'Add failed (' + resp.status + ')');
      }
      closeAddModal();
      setStatus('Added ' + ids.length + ' zettel' + (ids.length === 1 ? '' : 's') + ' to this Kasten.');
      // Refresh sandbox member counts so quality / metadata stays in sync.
      await loadSandboxes();
    } catch (err) {
      els.addError.textContent = err.message || 'Failed to add zettels.';
      els.addError.classList.remove('hidden');
      els.addSubmit.disabled = false;
    }
  }

  // ── Delete-Kasten modal ─────────────────────────────────────────

  function openDeleteModal() {
    if (!state.sandboxId) return;
    var sandbox = currentSandbox();
    var name = sandbox ? sandbox.name : 'this Kasten';
    els.delText.textContent =
      'This permanently deletes “' + name + '” and all of its chat sessions. ' +
      'Your zettels stay intact. This cannot be undone.';
    els.delConfirm.checked = false;
    els.delSubmit.disabled = true;
    els.delError.classList.add('hidden');
    els.delError.textContent = '';
    els.delModal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeDeleteModal() {
    els.delModal.classList.add('hidden');
    document.body.style.overflow = '';
  }

  async function submitDeleteKasten() {
    if (!state.sandboxId || !els.delConfirm.checked) return;
    // Second confirmation per production-discipline reminder.
    var sandbox = currentSandbox();
    var name = sandbox ? sandbox.name : 'this Kasten';
    if (!window.confirm('Final confirmation: delete “' + name + '”? This cannot be undone.')) {
      return;
    }
    els.delSubmit.disabled = true;
    els.delError.classList.add('hidden');
    try {
      var resp = await fetch('/api/rag/sandboxes/' + encodeURIComponent(state.sandboxId), {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + state.token }
      });
      if (!resp.ok) {
        var payload = await safeJson(resp);
        var detail = payload && (payload.detail || payload.error);
        throw new Error(typeof detail === 'string' ? detail : 'Delete failed (' + resp.status + ')');
      }
      // Done — ship the user back to the Kastens index.
      window.location.href = '/home/kastens';
    } catch (err) {
      els.delError.textContent = err.message || 'Failed to delete Kasten.';
      els.delError.classList.remove('hidden');
      els.delSubmit.disabled = false;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
