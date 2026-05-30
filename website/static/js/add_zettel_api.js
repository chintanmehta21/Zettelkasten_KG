(function () {
  'use strict';

  var zkFetch = window.zkFetch || window.fetch;  // signup-failure-fixes-1a: fall back if wrapper not loaded

  function makeActionId(surface) {
    return 'zettel:' + (surface || 'unknown') + ':' + Date.now() + ':' + Math.random().toString(36).slice(2);
  }

  function cleanProblemDetail(body, fallback) {
    if (!body || typeof body !== 'object') return fallback;
    if (body.detail && typeof body.detail === 'object') return body.detail.message || body.detail.detail || fallback;
    return body.detail || body.title || body.message || fallback;
  }

  // Normalize a terminal failed-op envelope ({status:'failed', error:<RFC9457
  // problem>, ...}) into the SAME shape a sync 4xx rejection produces, so one
  // consumer catch works for both paths. Inner object `detail` (quota) is
  // surfaced directly; a string `detail` keeps the problem object (no false
  // quota match). Title becomes the user-facing message.
  function _normalizeFailure(next) {
    var problem = (next && typeof next.error === 'object' && next.error) ? next.error : next;
    var inner = (problem && typeof problem.detail === 'object' && problem.detail) ? problem.detail : null;
    return {
      message: (problem && problem.title) || cleanProblemDetail(problem, 'Summary failed.'),
      detail: inner || problem || next,
      problem: problem,
    };
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
    var response = await zkFetch(statusUrl, { headers: headers });
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
    var response = await zkFetch(statusUrl, { headers: headers });
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

  // ADR-1 (summary-api-async-fixes): budget raised 300s → 420s so long
  // YouTube/PDF pipelines finish inside the client's polling window. The
  // reaper threshold moved 7m → 10m (migration 65) so it stays strictly
  // above this budget — a slow-but-progressing op is never reaped mid-poll.
  // Request volume is kept sane by SERVER-GUIDED backoff: GET
  // /api/operations/{id} returns a `Retry-After` that grows with the
  // operation's age (2s while young → 20s once long-running), so a 7-min
  // job is ~40 polls, not ~200. The client schedule below is only the
  // fallback when no `Retry-After` header is present.
  var POLL_BUDGET_MS = 420000;
  var POLL_BACKOFF_SCHEDULE_MS = [2000, 4000, 8000, 16000];
  var POLL_BACKOFF_CAP_MS = 20000;

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
          var n = _normalizeFailure(next);
          var failErr = new Error(n.message);
          failErr.status = 200;
          failErr.detail = n.detail;
          failErr.problem = n.problem;
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
    var actionId = opts.clientActionId || makeActionId(opts.surface);
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;
    // PR #39 / Wave-4 A3 (2026-05-20): send the same key as both the body's
    // legacy `client_action_id` AND the IETF-draft `Idempotency-Key` header.
    // The route prefers the header (zettels_routes.py:543) so two parallel
    // clicks sharing the same form-mounted action id resolve to the same
    // canonical operation server-side, even if the browser race-condition
    // would normally yield separate body ids. Stable per logical Add Zettel
    // submission; regenerated on each fresh form mount.
    headers['Idempotency-Key'] = actionId;

    var response = await zkFetch('/api/zettels/add', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({
        url: opts.url,
        client_action_id: actionId,
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
    var actionId = opts.clientActionId || makeActionId(opts.surface || 'landing-document');
    var headers = {};
    if (token) headers.Authorization = 'Bearer ' + token;
    // PR #39 / Wave-4 A3: parity with the URL add path — send the
    // Idempotency-Key header so a duplicate document submission resolves
    // to the same canonical operation server-side.
    headers['Idempotency-Key'] = actionId;

    var form = new FormData();
    form.append('file', opts.file);
    form.append('client_action_id', actionId);
    form.append('persist', opts.persist === false ? 'false' : 'true');
    form.append('surface', opts.surface || 'landing');

    var response = await zkFetch('/api/zettels/add/document', {
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

  // ADR-1: background continuation. After pollAccepted gives up at
  // POLL_BUDGET_MS the operation is still running server-side (the reaper
  // window is wider). continueInBackground keeps polling the status URL at a
  // slow cadence until the operation reaches a terminal state or the reaper
  // window elapses, then invokes onDone(envelope) — envelope is the succeeded
  // body, or null on failure/reap/timeout so the caller can clear its
  // placeholder card.
  async function continueInBackground(operationId, token, onDone) {
    function done(env) { try { if (onDone) onDone(env); } catch (e) { void e; } }
    if (!operationId) { done(null); return; }
    var headers = {};
    if (token) headers.Authorization = 'Bearer ' + token;
    var statusUrl = '/api/operations/' + encodeURIComponent(operationId);
    // ~6 min more — stays inside the 10-min reaper window (migration 65).
    var deadline = Date.now() + 360000;
    while (Date.now() < deadline) {
      await sleep(30000);
      try {
        var resp = await fetchStatusRaw(statusUrl, headers);
        var b = resp.body;
        if (b && b.status && b.status !== 'accepted') {
          done(b.status === 'succeeded' ? b : null);
          return;
        }
      } catch (e) { void e; }
    }
    done(null);
  }

  window.ZKAddZettel = {
    add: add,
    uploadDocument: uploadDocument,
    makeActionId: makeActionId,
    continueInBackground: continueInBackground,
    _parseResponse: parseResponse,
    _normalizeFailure: _normalizeFailure
  };
})();
