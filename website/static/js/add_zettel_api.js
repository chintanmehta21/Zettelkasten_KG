(function () {
  'use strict';

  function makeActionId(surface) {
    return 'zettel:' + (surface || 'unknown') + ':' + Date.now() + ':' + Math.random().toString(36).slice(2);
  }

  function cleanProblemDetail(body, fallback) {
    if (!body || typeof body !== 'object') return fallback;
    if (body.detail && typeof body.detail === 'object') return body.detail.message || body.detail.detail || fallback;
    return body.detail || body.title || body.message || fallback;
  }

  async function parseResponse(response) {
    var contentType = (response.headers.get('content-type') || '').toLowerCase();
    if (contentType.indexOf('application/json') !== -1 || contentType.indexOf('application/problem+json') !== -1) {
      return response.json();
    }
    var text = await response.text();
    var message = text ? text.slice(0, 220) : 'Server returned an empty non-JSON response.';
    throw new Error('Server returned non-JSON response (HTTP ' + response.status + '): ' + message);
  }

  function sleep(ms) {
    return new Promise(function (resolve) { window.setTimeout(resolve, ms); });
  }

  async function fetchStatus(statusUrl, headers) {
    var response = await fetch(statusUrl, { headers: headers });
    var body = await parseResponse(response);
    if (!response.ok) {
      var error = new Error(cleanProblemDetail(body, 'Status check failed with status ' + response.status));
      error.status = response.status;
      error.detail = body && (body.detail || body.error || body);
      error.problem = body;
      throw error;
    }
    return body;
  }

  async function fetchStatusRaw(statusUrl, headers) {
    var response = await fetch(statusUrl, { headers: headers });
    var body = await parseResponse(response);
    if (!response.ok && response.status !== 202) {
      var error = new Error(cleanProblemDetail(body, 'Status check failed with status ' + response.status));
      error.status = response.status;
      error.detail = body && (body.detail || body.error || body);
      error.problem = body;
      throw error;
    }
    return { body: body, retryAfter: response.headers.get('Retry-After') };
  }

  // ~180s total budget (matches GUNICORN_TIMEOUT) so slow YouTube/long-form
  // synth completes via polling instead of a Cloudflare 524. Fast polls first
  // to catch quick jobs, then steady 4s; server Retry-After (seconds) wins.
  var POLL_BUDGET_MS = 180000;

  async function pollAccepted(body, headers) {
    if (!body || body.status !== 'accepted' || !body.status_url) return body;
    var elapsed = 0;
    var attempt = 0;
    while (elapsed < POLL_BUDGET_MS) {
      var wait = attempt < 3 ? 1500 : 4000;
      if (body && body.retry_after) {
        var ra = parseInt(body.retry_after, 10);
        if (!isNaN(ra) && ra > 0) wait = ra * 1000;
      }
      await sleep(wait);
      elapsed += wait;
      attempt += 1;
      var resp = await fetchStatusRaw(body.status_url, headers);
      var next = resp.body;
      if (resp.retryAfter) { body.retry_after = resp.retryAfter; }
      if (next && next.status && next.status !== 'accepted') {
        // A terminal async FAILURE must reject (same contract as a non-202
        // add failure) so each consumer's existing catch surfaces it instead
        // of building an "Untitled" card from a failed envelope.summary.
        if (next.status === 'failed') {
          var failErr = new Error(cleanProblemDetail(next, 'Summary failed.'));
          failErr.status = 200;
          failErr.detail = next.detail || next.error || next;
          failErr.problem = next;
          throw failErr;
        }
        return next;
      }
    }
    var error = new Error('Summary is still processing. It will appear in My Zettels shortly.');
    error.status = 202;
    error.detail = body;
    error.problem = body;
    throw error;
  }

  async function add(options) {
    var opts = options || {};
    var token = opts.token || '';
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;

    var response = await fetch('/api/zettels/add', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({
        url: opts.url,
        client_action_id: opts.clientActionId || makeActionId(opts.surface),
        persist: opts.persist !== false,
        surface: opts.surface || 'landing',
        mode: opts.mode || 'sync'
      })
    });

    var body = await parseResponse(response);
    if (!response.ok) {
      var error = new Error(cleanProblemDetail(body, 'Request failed with status ' + response.status));
      error.status = response.status;
      error.detail = body && (body.detail || body.error || body);
      error.problem = body;
      throw error;
    }
    return pollAccepted(body, headers);
  }

  async function uploadDocument(options) {
    var opts = options || {};
    var token = opts.token || '';
    var headers = {};
    if (token) headers.Authorization = 'Bearer ' + token;

    var form = new FormData();
    form.append('file', opts.file);
    form.append('client_action_id', opts.clientActionId || makeActionId(opts.surface || 'landing-document'));
    form.append('persist', opts.persist === false ? 'false' : 'true');
    form.append('surface', opts.surface || 'landing');

    var response = await fetch('/api/zettels/add/document', {
      method: 'POST',
      headers: headers,
      body: form
    });

    var body = await parseResponse(response);
    if (!response.ok) {
      var error = new Error(cleanProblemDetail(body, 'Document upload failed with status ' + response.status));
      error.status = response.status;
      error.detail = body && (body.detail || body.error || body);
      error.problem = body;
      throw error;
    }
    return pollAccepted(body, headers);
  }

  window.ZKAddZettel = {
    add: add,
    uploadDocument: uploadDocument,
    makeActionId: makeActionId,
    _parseResponse: parseResponse
  };
})();
