(function () {
  'use strict';

  var DEFAULT_PROVIDERS = [
    { key: 'youtube', name: 'YouTube', accent: '#ff7a7a' },
    { key: 'github', name: 'GitHub', accent: '#7fb4c8' },
    { key: 'reddit', name: 'Reddit', accent: '#e29c66' },
    { key: 'twitter', name: 'Twitter / X', accent: '#90a4b8' }
  ];

  var PROVIDER_DETAILS = {
    youtube: {
      description: 'Import channels, playlists, and videos as note-ready source captures.',
      icon: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="3.75" y="6.75" width="16.5" height="10.5" rx="3" stroke="currentColor" stroke-width="1.8"></rect><path d="M11 9.2 15.3 12 11 14.8V9.2Z" fill="currentColor"></path></svg>'
    },
    github: {
      description: 'Connect repositories, issues, and discussions for engineering context.',
      icon: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 4.2c-4.3 0-7.8 3.5-7.8 7.8 0 3.4 2.2 6.2 5.2 7.3.4.1.5-.2.5-.4v-1.4c-2.1.5-2.6-.9-2.6-.9-.4-.9-.9-1.2-.9-1.2-.8-.5.1-.5.1-.5.9.1 1.4.9 1.4.9.8 1.5 2.1 1.1 2.6.9.1-.6.3-1 .6-1.2-1.7-.2-3.5-.9-3.5-3.9 0-.9.3-1.7.9-2.3-.1-.2-.4-1 .1-2 0 0 .7-.2 2.2.9.6-.2 1.2-.3 1.9-.3.7 0 1.3.1 1.9.3 1.5-1 2.2-.9 2.2-.9.5 1 .2 1.8.1 2 .6.6.9 1.4.9 2.3 0 3-1.8 3.7-3.5 3.9.3.2.5.7.5 1.4v2.1c0 .2.1.5.5.4 3-1.1 5.2-3.9 5.2-7.3 0-4.3-3.5-7.8-7.8-7.8Z" fill="currentColor"></path></svg>'
    },
    reddit: {
      description: 'Capture threads and community signals before they disappear into the feed.',
      icon: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M17.7 9.7c.8 0 1.4.6 1.4 1.4s-.6 1.4-1.4 1.4c-.1 0-.3 0-.4-.1-.5 2.5-3 4.3-6.2 4.3s-5.7-1.8-6.2-4.3c-.1 0-.3.1-.4.1-.8 0-1.4-.6-1.4-1.4s.6-1.4 1.4-1.4c.5 0 1 .3 1.2.7 1-.7 2.3-1.2 3.7-1.3l.7-3.1 2.1.5c.2-.6.7-1 1.4-1 1 0 1.7.8 1.7 1.7 0 .8-.6 1.5-1.4 1.7l-.5 1.3c1.4.1 2.7.6 3.7 1.3.2-.4.7-.7 1.2-.7Z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"></path><circle cx="9" cy="12.1" r=".9" fill="currentColor"></circle><circle cx="15" cy="12.1" r=".9" fill="currentColor"></circle><path d="M9.4 15.1c.8.6 1.7.9 2.6.9.9 0 1.8-.3 2.6-.9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"></path></svg>'
    },
    twitter: {
      description: 'Bring tweets and threads into the vault while the signal is still fresh.',
      icon: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M19.9 7.5c-.6.3-1.2.5-1.9.6.7-.4 1.1-1.1 1.4-1.8-.6.4-1.3.6-2 .8a3.3 3.3 0 0 0-5.7 2.2c0 .3 0 .5.1.7-2.8-.1-5.3-1.5-7-3.5-.3.5-.4 1.1-.4 1.8 0 1.2.6 2.2 1.4 2.8-.5 0-1-.2-1.4-.4 0 1.7 1.2 3.1 2.8 3.4-.3.1-.6.1-.9.1-.2 0-.4 0-.7-.1.5 1.4 1.8 2.3 3.4 2.3A6.6 6.6 0 0 1 4 17.1c1.6 1 3.4 1.6 5.4 1.6 6.4 0 9.9-5.3 9.9-9.9v-.5c.7-.4 1.3-1 1.8-1.6-.6.3-1.3.6-2 .8.7-.4 1.1-1 1.5-1.6Z" fill="currentColor"></path></svg>'
    }
  };

  var state = {
    supabaseClient: null,
    token: '',
    providers: [],
    runs: []
  };

  var els = {};

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function resolveDom() {
    els.providerGrid = document.getElementById('provider-grid');
    els.runsList = document.getElementById('runs-list');
    els.runsEmpty = document.getElementById('runs-empty');
    els.providerCount = document.getElementById('provider-count');
    els.connectedCount = document.getElementById('connected-count');
    els.runCount = document.getElementById('run-count');
    els.toast = document.getElementById('toast');
    els.importAllBtn = document.getElementById('import-all-btn');
    els.refreshAllBtn = document.getElementById('refresh-all-btn');
    els.reloadProvidersBtn = document.getElementById('reload-providers-btn');
    els.reloadRunsBtn = document.getElementById('reload-runs-btn');
    els.rememberConnectionToggle = document.getElementById('remember-connection-toggle');
  }

  function authHeaders(token) {
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;
    return headers;
  }

  async function requestJson(path, options) {
    options = options || {};
    var response = await fetch(path, {
      method: options.method || 'GET',
      headers: authHeaders(options.token || state.token),
      body: options.body ? JSON.stringify(options.body) : undefined
    });

    var payload = null;
    try { payload = await response.json(); } catch (err) { payload = null; }
    if (!response.ok) {
      throw new Error((payload && (payload.detail || payload.message)) || ('Request failed: ' + response.status));
    }
    return payload;
  }

  function showToast(message, isError) {
    if (!els.toast) return;
    els.toast.textContent = message;
    els.toast.classList.toggle('is-error', !!isError);
    els.toast.classList.add('visible');
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(function () {
      if (els.toast) els.toast.classList.remove('visible');
    }, 2600);
  }

  function fmtTime(value) {
    if (!value) return 'Just now';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }

  function normalizeKey(value) {
    var key = String(value || '').toLowerCase().replace(/\s+/g, '');
    if (key.indexOf('twitter') === 0 || key === 'x') return 'twitter';
    return key;
  }

  function providerAccent(key) {
    var found = DEFAULT_PROVIDERS.find(function (item) { return item.key === key; });
    return found ? found.accent : '#20c3a5';
  }

  function shouldRememberConnection() {
    if (!els.rememberConnectionToggle) return true;
    return !!els.rememberConnectionToggle.checked;
  }

  function normalizeProviders(payload) {
    var raw = payload && (payload.providers || payload.data || payload.items || payload);
    if (!raw) return DEFAULT_PROVIDERS.slice();

    var list = Array.isArray(raw)
      ? raw
      : DEFAULT_PROVIDERS.map(function (item) {
          return Object.assign({}, item, raw[item.key] || raw[item.name] || {});
        });

    return list.map(function (item) {
      var key = normalizeKey(item.key || item.provider || item.id || item.name);
      var meta = PROVIDER_DETAILS[key] || {};
      return {
        key: key || String(item.key || item.provider || 'provider'),
        name: item.name || item.label || (key === 'twitter' ? 'Twitter / X' : String(item.key || item.provider || 'Provider')),
        connected: !!(item.connected || item.is_connected || item.enabled || item.active),
        account: item.account || item.account_username || item.handle || item.username || item.email || item.owner || 'Not connected',
        lastImportedAt: item.last_imported_at || item.last_imported || item.lastRunAt || item.updated_at || null,
        lastResult: item.last_result || item.lastResult || item.result || '',
        totalImports: item.total_imports || item.import_count || item.run_count || item.count || 0,
        description: item.description || meta.description || '',
        accent: item.accent || item.color || providerAccent(key)
      };
    });
  }

  function normalizeRuns(payload) {
    var raw = payload && (payload.runs || payload.data || payload.items || payload);
    if (!raw || !Array.isArray(raw)) return [];

    return raw.map(function (item) {
      var provider = normalizeKey(item.provider || item.source || item.platform);
      return {
        provider: provider,
        title: item.title || item.name || (provider ? provider.toUpperCase() + ' import' : 'Import run'),
        status: item.status || item.state || 'unknown',
        startedAt: item.started_at || item.created_at || item.timestamp || item.time || null,
        finishedAt: item.finished_at || item.completed_at || null,
        message: item.message || item.detail || item.error || item.summary || '',
        importedCount: item.imported_count || item.count || item.nodes_created || 0
      };
    });
  }

  function renderStats() {
    var connected = state.providers.filter(function (provider) { return provider.connected; }).length;
    if (els.connectedCount) els.connectedCount.textContent = String(connected);
    if (els.providerCount) els.providerCount.textContent = String(Math.max(state.providers.length, DEFAULT_PROVIDERS.length));
    if (els.runCount) els.runCount.textContent = String(state.runs.length);
  }

  function providerCard(provider) {
    var details = PROVIDER_DETAILS[provider.key] || {};
    var connectLabel = provider.connected ? 'Reconnect' : 'Connect';
    var disconnectDisabled = provider.connected ? '' : 'disabled';
    var importDisabled = provider.connected ? '' : 'disabled';

    return '' +
      '<article class="nexus-provider-card ' + (provider.connected ? 'is-connected' : '') + '" data-provider="' + provider.key + '">' +
        '<div class="nexus-provider-top">' +
          '<div class="nexus-provider-brand">' +
            '<div class="nexus-provider-icon" style="color:' + provider.accent + '">' + (details.icon || '') + '</div>' +
            '<div>' +
              '<h3 class="nexus-provider-name">' + escapeHtml(provider.name) + '</h3>' +
              '<p class="nexus-provider-description">' + escapeHtml(provider.description) + '</p>' +
            '</div>' +
          '</div>' +
          '<div class="nexus-status-pill ' + (provider.connected ? 'is-connected' : '') + '">' + (provider.connected ? 'Connected' : 'Disconnected') + '</div>' +
        '</div>' +
        '<div class="nexus-provider-meta">' +
          '<div class="nexus-meta-item"><span class="nexus-meta-label">Connected account</span><span class="nexus-meta-value">' + escapeHtml(provider.account) + '</span></div>' +
          '<div class="nexus-meta-item"><span class="nexus-meta-label">Last import</span><span class="nexus-meta-value">' + (provider.lastImportedAt ? fmtTime(provider.lastImportedAt) : 'No imports yet') + '</span></div>' +
          '<div class="nexus-meta-item"><span class="nexus-meta-label">Import count</span><span class="nexus-meta-value">' + String(provider.totalImports || 0) + '</span></div>' +
          '<div class="nexus-meta-item"><span class="nexus-meta-label">Sync state</span><span class="nexus-meta-value">' + escapeHtml(provider.lastResult || 'Ready') + '</span></div>' +
        '</div>' +
        '<div class="nexus-provider-actions">' +
          '<button class="nexus-button nexus-button-primary js-provider-connect" type="button" data-provider="' + provider.key + '">' + connectLabel + '</button>' +
          '<button class="nexus-button nexus-button-danger js-provider-disconnect" type="button" data-provider="' + provider.key + '" ' + disconnectDisabled + '>Disconnect</button>' +
          '<button class="nexus-button nexus-button-secondary js-provider-import" type="button" data-provider="' + provider.key + '" ' + importDisabled + '>Import</button>' +
        '</div>' +
      '</article>';
  }

  function renderProviders() {
    if (!els.providerGrid) return;

    var providers = state.providers.length ? state.providers : DEFAULT_PROVIDERS.map(function (provider) {
      return {
        key: provider.key,
        name: provider.name,
        connected: false,
        account: 'Not connected',
        lastImportedAt: null,
        lastResult: 'Ready',
        totalImports: 0,
        description: PROVIDER_DETAILS[provider.key].description,
        accent: provider.accent
      };
    });

    els.providerGrid.innerHTML = providers.map(providerCard).join('');

    els.providerGrid.querySelectorAll('.js-provider-connect').forEach(function (button) {
      button.addEventListener('click', function () {
        connectProvider(this.getAttribute('data-provider'));
      });
    });
    els.providerGrid.querySelectorAll('.js-provider-import').forEach(function (button) {
      button.addEventListener('click', function () {
        importProvider(this.getAttribute('data-provider'));
      });
    });
    els.providerGrid.querySelectorAll('.js-provider-disconnect').forEach(function (button) {
      button.addEventListener('click', function () {
        disconnectProvider(this.getAttribute('data-provider'));
      });
    });

    renderStats();
  }

  function renderRuns() {
    if (!els.runsList || !els.runsEmpty) return;
    if (!state.runs.length) {
      els.runsList.innerHTML = '';
      els.runsEmpty.classList.remove('hidden');
      renderStats();
      return;
    }

    els.runsEmpty.classList.add('hidden');
    els.runsList.innerHTML = state.runs.map(function (run) {
      var providerLabel = run.provider ? run.provider.toUpperCase() : 'Nexus';
      var message = run.message || 'No extra details returned by the API.';
      return '' +
        '<article class="nexus-run-item">' +
          '<div>' +
            '<h3 class="nexus-run-title">' + escapeHtml(run.title) + '</h3>' +
            '<div class="nexus-run-meta">' +
              '<span>' + escapeHtml(providerLabel) + '</span>' +
              '<span>&middot;</span>' +
              '<span>' + escapeHtml(String(run.status || 'unknown')) + '</span>' +
              (run.importedCount ? '<span>&middot;</span><span>' + String(run.importedCount) + ' imported</span>' : '') +
            '</div>' +
            '<p class="nexus-run-message">' + escapeHtml(message) + '</p>' +
          '</div>' +
          '<div class="nexus-run-timestamp">' + fmtTime(run.finishedAt || run.startedAt) + '</div>' +
        '</article>';
    }).join('');

    renderStats();
  }

  async function loadAuth() {
    var config = await requestJson('/api/auth/config', { token: '' });
    if (config && config.supabase_url && config.supabase_anon_key) {
      state.supabaseClient = supabase.createClient(config.supabase_url, config.supabase_anon_key, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          storage: window.localStorage,
          storageKey: 'zk-auth-token',
        },
      });
      var sessionResult = await state.supabaseClient.auth.getSession();
      state.token = sessionResult && sessionResult.data && sessionResult.data.session ? sessionResult.data.session.access_token : '';
    }

    if (!state.token) {
      window.location.href = '/';
      throw new Error('Missing session');
    }
  }

  async function loadProviders() {
    state.providers = normalizeProviders(await requestJson('/api/nexus/providers'));
    renderProviders();
  }

  async function loadRuns() {
    state.runs = normalizeRuns(await requestJson('/api/nexus/runs'));
    renderRuns();
  }

  async function refreshAll() {
    await Promise.allSettled([loadProviders(), loadRuns()]);
    showToast('Nexus refreshed');
  }

  async function connectProvider(providerKey) {
    if (!providerKey) return;
    try {
      showToast('Starting ' + providerKey + ' connection...');
      var rememberConnection = shouldRememberConnection();
      var payload = await requestJson('/api/nexus/connect/' + encodeURIComponent(providerKey), {
        method: 'POST',
        body: { remember_connection: rememberConnection }
      });
      var redirectUrl = payload && (
        payload.authorization_url ||
        payload.authorizationUrl ||
        payload.redirect_url ||
        payload.redirectUrl ||
        payload.auth_url ||
        payload.authUrl ||
        payload.url
      );
      if (redirectUrl) {
        window.location.href = redirectUrl;
        return;
      }
      await refreshAll();
      if (rememberConnection) {
        showToast(providerKey + ' connection ready');
      } else {
        showToast(providerKey + ' connected in session mode (credentials will be forgotten after import).');
      }
    } catch (err) {
      showToast(err.message || 'Connection failed', true);
    }
  }

  async function importProvider(providerKey) {
    if (!providerKey) return;
    try {
      showToast('Importing ' + providerKey + '...');
      var rememberConnection = shouldRememberConnection();
      await requestJson('/api/nexus/import/' + encodeURIComponent(providerKey), {
        method: 'POST',
        body: { remember_connection: rememberConnection }
      });
      await Promise.allSettled([loadProviders(), loadRuns()]);
      if (rememberConnection) {
        showToast(providerKey + ' import started');
      } else {
        showToast(providerKey + ' import complete. Credentials forgotten for test mode.');
      }
    } catch (err) {
      showToast(err.message || 'Import failed', true);
    }
  }

  async function importAll() {
    try {
      showToast('Importing all providers...');
      var rememberConnection = shouldRememberConnection();
      await requestJson('/api/nexus/import/all', {
        method: 'POST',
        body: { remember_connection: rememberConnection }
      });
      await Promise.allSettled([loadProviders(), loadRuns()]);
      if (rememberConnection) {
        showToast('Full import started');
      } else {
        showToast('Full import complete. Credentials forgotten for test mode.');
      }
    } catch (err) {
      showToast(err.message || 'Import all failed', true);
    }
  }

  async function disconnectProvider(providerKey) {
    if (!providerKey) return;
    try {
      showToast('Disconnecting ' + providerKey + '...');
      var payload = await requestJson('/api/nexus/disconnect/' + encodeURIComponent(providerKey), { method: 'POST' });
      await Promise.allSettled([loadProviders(), loadRuns()]);
      if (payload && payload.disconnected === false) {
        showToast(providerKey + ' was already disconnected');
        return;
      }
      showToast(providerKey + ' disconnected');
    } catch (err) {
      showToast(err.message || 'Disconnect failed', true);
    }
  }

  function bindEvents() {
    if (els.importAllBtn) els.importAllBtn.addEventListener('click', importAll);
    if (els.refreshAllBtn) els.refreshAllBtn.addEventListener('click', refreshAll);
    if (els.reloadProvidersBtn) els.reloadProvidersBtn.addEventListener('click', loadProviders);
    if (els.reloadRunsBtn) els.reloadRunsBtn.addEventListener('click', loadRuns);
  }

  async function init() {
    resolveDom();
    bindEvents();
    try {
      await loadAuth();
      await Promise.allSettled([loadProviders(), loadRuns()]);
    } catch (err) {
      if (err && err.message !== 'Missing session') {
        showToast(err.message || 'Failed to load Nexus', true);
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
