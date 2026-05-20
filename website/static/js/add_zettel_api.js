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

  // PR #39 / Wave-1 C1 (2026-05-20): 300s budget aligns with the 7-min
  // stuck-running reaper threshold (migration 59) + headroom so polling
  // can resolve before the reaper marks a long-running op as failed.
  // Exponential backoff (1s, 2s, 4s, capped at 8s) reduces poll storm on
  // the operations endpoint without sacrificing perceived snappiness for
  // fast jobs. Server `Retry-After` always wins when present.
  var POLL_BUDGET_MS = 300000;
  var POLL_BACKOFF_SCHEDULE_MS = [1000, 2000, 4000, 8000];
  var POLL_BACKOFF_CAP_MS = 8000;

  async function pollAccepted(body, headers, hooks) {
    if (!body || body.status !== 'accepted' || !body.status_url) return body;
    var onStatus = hooks && typeof hooks.onStatus === 'function' ? hooks.onStatus : null;
    var elapsed = 0;
    var attempt = 0;
    // Emit an initial 'queued' tick so the typewriter starts at t=0 instead
    // of waiting for the first poll round-trip.
    if (onStatus) {
      try { onStatus({ phase: body.phase || 'queued', elapsedMs: 0, attempt: 0 }); } catch (e) { void e; }
    }
    while (elapsed < POLL_BUDGET_MS) {
      var wait = attempt < POLL_BACKOFF_SCHEDULE_MS.length
        ? POLL_BACKOFF_SCHEDULE_MS[attempt]
        : POLL_BACKOFF_CAP_MS;
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
        if (onStatus) {
          try { onStatus({ phase: 'succeeded', elapsedMs: elapsed, attempt: attempt }); } catch (e) { void e; }
        }
        return next;
      }
      // PR #39 / Wave-2: surface the server-side `phase` (queued|running)
      // so the typewriter can swap to in-progress vocabulary the moment
      // the worker picks the job up. Falls back to elapsed-time staging
      // on older server builds that don't emit phase.
      if (onStatus) {
        var phase = (next && next.phase) || (elapsed >= 5000 ? 'running' : 'queued');
        try { onStatus({ phase: phase, elapsedMs: elapsed, attempt: attempt }); } catch (e) { void e; }
      }
    }
    var error = new Error('Still summarizing. Your Zettel will appear in My Zettels once it lands.');
    error.status = 202;
    error.code = 'poll_exhausted';
    error.detail = body;
    error.problem = body;
    error.operationId = body.operation_id || null;
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
        surface: opts.surface || 'landing'
        // PR #39 / Wave-1 A2: `mode` field retired (route is always-async).
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
    return pollAccepted(body, headers, { onStatus: opts.onStatus });
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
    return pollAccepted(body, headers, { onStatus: opts.onStatus });
  }

  window.ZKAddZettel = {
    add: add,
    uploadDocument: uploadDocument,
    makeActionId: makeActionId,
    _parseResponse: parseResponse
  };
})();
