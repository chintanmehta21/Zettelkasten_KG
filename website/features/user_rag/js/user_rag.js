(function () {
  'use strict';

  var SOURCE_OPTIONS = ['youtube', 'github', 'reddit', 'substack', 'medium', 'web'];
  var state = {
    token: '',
    sandboxes: [],
    sessions: [],
    sessionId: '',
    sandboxId: '',
    focusNodeId: '',
    focusNodeTitle: '',
    sources: [],
    currentAssistantCitations: []
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
    state.sandboxId = params.get('sandbox_id') || '';
    state.sessionId = params.get('session_id') || '';
    state.focusNodeId = params.get('focus_node') || '';
    state.focusNodeTitle = params.get('focus_title') || '';
    if (state.focusNodeTitle && !els.input.value) {
      els.input.placeholder = 'Ask about ' + state.focusNodeTitle + '...';
    }

    await Promise.all([
      loadSandboxes(),
      loadExampleQueries()
    ]);
    await refreshSessions();
    if (state.sessionId) {
      await loadSession(state.sessionId);
    } else if (state.focusNodeTitle) {
      setStatus('Scoped to ' + state.focusNodeTitle + '.');
    }
  }

  function resolveDom() {
    els.sandboxSelect = q('sandbox-select');
    els.qualitySelect = q('quality-select');
    els.tagsInput = q('tags-input');
    els.sourceGrid = q('source-grid');
    els.sessionList = q('session-list');
    els.exampleList = q('example-list');
    els.transcript = q('transcript');
    els.emptyState = q('empty-state');
    els.form = q('composer-form');
    els.input = q('composer-input');
    els.status = q('rag-status');
    els.chatTitle = q('chat-title');
    els.newSessionBtn = q('new-session-btn');
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
    els.newSessionBtn.addEventListener('click', startNewSession);
    els.sandboxSelect.addEventListener('change', function () {
      state.sandboxId = els.sandboxSelect.value;
      state.sessionId = '';
      updateChatTitle();
      setQueryParams();
      refreshSessions();
      resetTranscript();
    });
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
    var payload = await api('/api/rag/sandboxes');
    state.sandboxes = payload.sandboxes || [];
    els.sandboxSelect.innerHTML = '<option value="">All zettels</option>';
    state.sandboxes.forEach(function (sandbox) {
      var option = document.createElement('option');
      option.value = sandbox.id;
      option.textContent = sandbox.name + ' (' + (sandbox.member_count || 0) + ')';
      if (sandbox.id === state.sandboxId) option.selected = true;
      els.sandboxSelect.appendChild(option);
    });
    updateChatTitle();
  }

  async function loadExampleQueries() {
    var payload = await api('/api/rag/example-queries');
    els.exampleList.innerHTML = '';
    (payload.queries || []).forEach(function (query) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'rag-chip';
      button.textContent = query;
      button.addEventListener('click', function () {
        els.input.value = query;
        els.input.focus();
      });
      els.exampleList.appendChild(button);
    });
  }

  async function refreshSessions() {
    var url = '/api/rag/sessions?limit=20';
    if (state.sandboxId) {
      url += '&sandbox_id=' + encodeURIComponent(state.sandboxId);
    }
    var payload = await api(url);
    state.sessions = payload.sessions || [];
    renderSessions();
  }

  function renderSessions() {
    els.sessionList.innerHTML = '';
    if (!state.sessions.length) {
      els.sessionList.innerHTML = '<div class="rag-session-card"><h3>No sessions yet</h3><p>Ask a first question to create one.</p></div>';
      return;
    }

    state.sessions.forEach(function (session) {
      var card = document.createElement('button');
      card.type = 'button';
      card.className = 'rag-session-card' + (session.id === state.sessionId ? ' active' : '');
      card.setAttribute('aria-pressed', session.id === state.sessionId ? 'true' : 'false');
      card.innerHTML = [
        '<h3>' + escapeHtml(session.title || 'New conversation') + '</h3>',
        '<p>' + escapeHtml((session.quality_mode || 'fast').toUpperCase()) + ' mode</p>',
        '<p class="rag-message-meta">' + escapeHtml(String(session.message_count || 0)) + ' messages</p>'
      ].join('');
      card.addEventListener('click', function () {
        loadSession(session.id);
      });
      els.sessionList.appendChild(card);
    });
  }

  async function loadSession(sessionId) {
    state.sessionId = sessionId;
    setQueryParams();
    renderSessions();
    var sessionPayload = await api('/api/rag/sessions/' + encodeURIComponent(sessionId));
    var session = sessionPayload.session;
    if (session.sandbox_id) {
      state.sandboxId = session.sandbox_id;
      els.sandboxSelect.value = session.sandbox_id;
    }
    els.qualitySelect.value = session.quality_mode || 'fast';
    updateChatTitle();

    var payload = await api('/api/rag/sessions/' + encodeURIComponent(sessionId) + '/messages');
    renderMessages(payload.messages || []);
  }

  function renderMessages(messages) {
    els.transcript.innerHTML = '';
    if (!messages.length) {
      resetTranscript();
      return;
    }
    els.emptyState.classList.add('hidden');
    messages.forEach(function (message) {
      els.transcript.appendChild(createMessageNode(message.role, message.content, message.citations || [], message));
    });
    scrollTranscript();
  }

  function resetTranscript() {
    els.transcript.innerHTML = '';
    els.emptyState.classList.remove('hidden');
  }

  function createMessageNode(role, content, citations, meta) {
    var article = document.createElement('article');
    article.className = 'rag-message ' + role;
    var citationMarkup = (citations || []).map(function (citation) {
      return '<span class="rag-citation-chip">' + escapeHtml(citation.title || citation.node_id || citation.id) + '</span>';
    }).join('');
    article.innerHTML = [
      '<div class="rag-message-head">',
      '  <span class="rag-message-role">' + escapeHtml(role) + '</span>',
      '  <span class="rag-message-meta">' + escapeHtml(meta && meta.llm_model ? meta.llm_model : '') + '</span>',
      '</div>',
      '<div class="rag-message-body"></div>',
      citationMarkup ? ('<div class="rag-citations">' + citationMarkup + '</div>') : ''
    ].join('');
    article.querySelector('.rag-message-body').textContent = content || '';
    return article;
  }

  async function onAsk(event) {
    event.preventDefault();
    var content = els.input.value.trim();
    if (!content) return;

    setStatus('Creating grounded answer...');
    els.emptyState.classList.add('hidden');
    setComposerBusy(true);

    var userNode = createMessageNode('user', content, [], {});
    var assistantNode = createMessageNode('assistant', '', [], {});
    try {
      if (!state.sessionId) {
        await createSession();
      }

      els.transcript.appendChild(userNode);
      els.transcript.appendChild(assistantNode);
      state.currentAssistantCitations = [];
      scrollTranscript();
      els.input.value = '';

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
        throw new Error((payload && payload.detail) || 'The chat request failed.');
      }

      await consumeSSE(response.body.getReader(), assistantNode);
      await refreshSessions();
    } catch (err) {
      rollbackPendingAssistant(assistantNode, userNode, err);
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
      renderCitations(assistantNode, state.currentAssistantCitations);
      return;
    }
    if (payload.type === 'replace') {
      body.textContent = payload.content || '';
      return;
    }
    if (payload.type === 'error') {
      body.textContent = payload.message || 'The request failed.';
      setStatus(payload.message || 'The request failed.');
      return;
    }
    if (payload.type === 'done') {
      var turn = payload.turn || {};
      body.textContent = turn.content || body.textContent;
      renderCitations(assistantNode, turn.citations || state.currentAssistantCitations || []);
      assistantNode.querySelector('.rag-message-meta').textContent = turn.llm_model || '';
      setStatus('Answer complete.');
      return;
    }
  }

  function renderCitations(assistantNode, citations) {
    var existing = assistantNode.querySelector('.rag-citations');
    if (existing) existing.remove();
    if (!citations || !citations.length) return;
    var wrapper = document.createElement('div');
    wrapper.className = 'rag-citations';
    citations.forEach(function (citation) {
      var chip = document.createElement('span');
      chip.className = 'rag-citation-chip';
      chip.textContent = citation.title || citation.node_id || citation.id;
      wrapper.appendChild(chip);
    });
    assistantNode.appendChild(wrapper);
  }

  function buildScopeFilter() {
    var tagValue = els.tagsInput.value.trim();
    return {
      node_ids: state.focusNodeId ? [state.focusNodeId] : [],
      tags: tagValue ? tagValue.split(',').map(function (item) { return item.trim(); }).filter(Boolean) : [],
      tag_mode: 'any',
      source_types: state.sources.slice()
    };
  }

  function updateChatTitle() {
    var sandbox = state.sandboxes.find(function (item) { return item.id === state.sandboxId; });
    if (sandbox) {
      els.chatTitle.textContent = state.focusNodeTitle
        ? 'Ask inside ' + sandbox.name + ' with ' + state.focusNodeTitle + ' pinned.'
        : 'Ask inside ' + sandbox.name + '.';
      return;
    }
    els.chatTitle.textContent = state.focusNodeTitle
      ? 'Ask with ' + state.focusNodeTitle + ' pinned.'
      : 'Ask the graph something precise.';
  }

  function startNewSession() {
    state.sessionId = '';
    setQueryParams();
    resetTranscript();
    renderSessions();
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

  function rollbackPendingAssistant(assistantNode, userNode, err) {
    if (!assistantNode.isConnected && userNode.isConnected) {
      userNode.remove();
    }
    if (!assistantNode.isConnected) {
      setStatus(toErrorMessage(err, 'The chat request failed.'));
      if (!els.transcript.children.length) {
        els.emptyState.classList.remove('hidden');
      }
      return;
    }
    assistantNode.querySelector('.rag-message-body').textContent = toErrorMessage(err, 'The chat request failed.');
    renderCitations(assistantNode, []);
    setStatus(toErrorMessage(err, 'The chat request failed.'));
  }

  function setComposerBusy(isBusy) {
    els.input.disabled = isBusy;
    els.newSessionBtn.disabled = isBusy;
    els.sandboxSelect.disabled = isBusy;
    els.qualitySelect.disabled = isBusy;
    els.tagsInput.disabled = isBusy;
    q('send-btn').disabled = isBusy;
    Array.prototype.forEach.call(
      els.sourceGrid.querySelectorAll('.rag-source-chip'),
      function (chip) {
        chip.disabled = isBusy;
      }
    );
  }

  function toErrorMessage(err, fallback) {
    return err && err.message ? err.message : fallback;
  }

  function setQueryParams() {
    var params = new URLSearchParams(window.location.search);
    if (state.sandboxId) params.set('sandbox_id', state.sandboxId); else params.delete('sandbox_id');
    if (state.sessionId) params.set('session_id', state.sessionId); else params.delete('session_id');
    if (state.focusNodeId) params.set('focus_node', state.focusNodeId); else params.delete('focus_node');
    if (state.focusNodeTitle) params.set('focus_title', state.focusNodeTitle); else params.delete('focus_title');
    var next = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
    window.history.replaceState({}, '', next);
  }

  function setStatus(text) {
    els.status.textContent = text;
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
      throw new Error((payload && payload.detail) || 'Request failed');
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
