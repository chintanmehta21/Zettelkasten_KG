/* zk_fetch.js — single source of truth for authenticated fetch behavior.
 *
 * Wraps window.fetch to:
 *   1. React to X-Auth-Status: jwt-dropped-to-anon (set by website/app.py
 *      middleware on JWT silent-drop) by surfacing a non-blocking banner
 *      that prompts re-auth — instead of silently mapping the user to Zoro.
 *   2. On 401 from /api/*, attempt a single-flight supabase.auth.refreshSession()
 *      and replay the request once; if refresh also fails, show the banner
 *      with a "Sign in again" CTA. Never auto-redirects mid-flow (per the
 *      "Please Stop Redirecting on 401" UX consensus, dev.to/aragossa).
 *   3. Distinguish Cloudflare-issued errors (cf-error-type / cf-error-code
 *      headers — per developers.cloudflare.com/support/troubleshooting/
 *      http-status-codes/cloudflare-error-headers/) from origin 401s.
 *      Cloudflare 401s are NOT auth issues; don't try to refresh on them.
 *   4. Broadcast cross-tab via BroadcastChannel('zk-auth') so all open tabs
 *      see the downgrade simultaneously.
 *
 * Industry precedent (researched 2026-05-25):
 *   - RFC 6750 WWW-Authenticate Bearer error="invalid_token" companion header
 *     is emitted by the backend alongside X-Auth-Status.
 *   - Single-flight refresh + queue + replay pattern is the canonical token-
 *     refresh-rotation idiom (axios interceptor world).
 *   - Banner-over-modal per NN/G + DWP design system + PatternFly guidance.
 *
 * Loaded from website/features/header/header.html so every page that uses
 * the shared shell gets the wrapper installed before its first fetch.
 * No-op on pages without a Supabase client (banner still surfaces on
 * X-Auth-Status; only the 401-refresh path is skipped).
 */
(function () {
  'use strict';

  if (window.zkFetch) return; // idempotent — survives accidental double-load

  var BANNER_ID = 'zk-reauth-banner';
  var BANNER_STYLE_ID = 'zk-reauth-banner-style';
  var BC_NAME = 'zk-auth';
  // storage-event fallback key for legacy iOS Safari (<15.4) that lacks
  // BroadcastChannel. Pattern: setItem + immediate removeItem fires the
  // event in OTHER tabs without polluting storage.
  var STORAGE_BROADCAST_KEY = 'zk-auth-broadcast';

  var origFetch = window.fetch.bind(window);
  var refreshInFlight = null;
  var channel = null;
  try { channel = new BroadcastChannel(BC_NAME); } catch (_) { channel = null; }

  // ── Banner ──────────────────────────────────────────────────────────────
  function injectBannerStyle() {
    if (document.getElementById(BANNER_STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = BANNER_STYLE_ID;
    // Teal palette (per CLAUDE.md — no purple, teal for non-KG surfaces).
    style.textContent =
      '#' + BANNER_ID + '{position:fixed;top:0;left:0;right:0;z-index:99999;' +
      'background:hsl(172,66%,28%);color:hsl(210,20%,98%);padding:10px 16px;' +
      'font-family:Inter,system-ui,sans-serif;font-size:14px;line-height:1.4;' +
      'box-shadow:0 2px 8px rgba(0,0,0,.25);display:flex;align-items:center;' +
      'justify-content:center;gap:12px}' +
      '#' + BANNER_ID + ' a{color:hsl(172,66%,82%);text-decoration:underline;' +
      'cursor:pointer;font-weight:500}' +
      '#' + BANNER_ID + ' button.zk-reauth-close{background:transparent;border:0;' +
      'color:inherit;font-size:18px;line-height:1;cursor:pointer;padding:0 4px;' +
      'opacity:.7}' +
      '#' + BANNER_ID + ' button.zk-reauth-close:hover{opacity:1}' +
      '#' + BANNER_ID + '[hidden]{display:none!important}';
    document.head.appendChild(style);
  }

  function showBanner(reason) {
    if (!document.body) {
      // DOM not ready yet — retry on DOMContentLoaded.
      document.addEventListener('DOMContentLoaded', function () { showBanner(reason); }, { once: true });
      return;
    }
    injectBannerStyle();
    var el = document.getElementById(BANNER_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = BANNER_ID;
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      var msg = reason === 'expired'
        ? 'Your session has expired. '
        : 'Your sign-in needs to be refreshed. ';
      el.innerHTML =
        '<span>' + msg + '<a href="/?reauth=expired" data-zk-reauth-cta>Sign in again</a></span>' +
        '<button type="button" class="zk-reauth-close" aria-label="Dismiss">×</button>';
      var closeBtn = el.querySelector('button.zk-reauth-close');
      if (closeBtn) {
        closeBtn.addEventListener('click', function () { el.setAttribute('hidden', ''); });
      }
      document.body.insertBefore(el, document.body.firstChild);
    } else {
      el.removeAttribute('hidden');
    }
  }

  // ── Cross-tab fan-out ──────────────────────────────────────────────────
  function applyBroadcast(data) {
    if (!data || typeof data !== 'object') return;
    if (data.type !== 'downgraded' && data.type !== 'expired') return;
    showBanner(data.type);
    window.dispatchEvent(new CustomEvent(
      data.type === 'expired' ? 'zk:auth-expired' : 'zk:auth-downgraded',
      { detail: data }
    ));
  }

  if (channel) {
    channel.addEventListener('message', function (e) { applyBroadcast(e.data); });
  }

  // Storage-event fallback for iOS Safari <15.4 (no BroadcastChannel). The
  // 'storage' event only fires in OTHER tabs, so a write+remove of the same
  // key in the originating tab is invisible there but propagates everywhere
  // else. Belt + braces alongside BroadcastChannel on modern browsers.
  window.addEventListener('storage', function (e) {
    if (e.key !== STORAGE_BROADCAST_KEY || !e.newValue) return;
    try { applyBroadcast(JSON.parse(e.newValue)); } catch (_) {}
  });

  function broadcastAndShow(type) {
    showBanner(type);
    var detail = { type: type, at: Date.now() };
    window.dispatchEvent(new CustomEvent(
      type === 'expired' ? 'zk:auth-expired' : 'zk:auth-downgraded',
      { detail: detail }
    ));
    if (channel) {
      try { channel.postMessage(detail); } catch (_) {}
    }
    // Storage-event fan-out for tabs without BroadcastChannel support.
    // Race-tolerant: only remove if our payload is still the current value,
    // so a parallel broadcast from another tab isn't silently overwritten.
    try {
      var payload = JSON.stringify(detail);
      localStorage.setItem(STORAGE_BROADCAST_KEY, payload);
      if (localStorage.getItem(STORAGE_BROADCAST_KEY) === payload) {
        localStorage.removeItem(STORAGE_BROADCAST_KEY);
      }
    } catch (_) {}
  }

  // ── Helpers ────────────────────────────────────────────────────────────
  function isCloudflareIssued(resp) {
    return Boolean(
      resp.headers.get('cf-error-type') ||
      resp.headers.get('cf-error-code')
    );
  }

  function isApiPath(input) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    // Only handle 401s on our own API surface; let third-party requests
    // (e.g., Supabase direct calls from supabase-js) handle their own errors.
    return url.indexOf('/api/') === 0 || url.indexOf('/api/') > 0;
  }

  function getSupabaseClient() {
    // Pages that call ZKAuth.getClient() (auth-core.js) expose the client this way.
    try {
      if (window.ZKAuth && typeof window.ZKAuth.getClient === 'function') {
        return window.ZKAuth.getClient();
      }
    } catch (_) {}
    return null;
  }

  // ── Wrapper ────────────────────────────────────────────────────────────
  async function zkFetch(input, init) {
    var res = await origFetch(input, init);

    if (res.headers.get('X-Auth-Status') === 'jwt-dropped-to-anon') {
      broadcastAndShow('downgraded');
    }

    if (res.status !== 401 || isCloudflareIssued(res) || !isApiPath(input)) {
      return res;
    }

    var client = getSupabaseClient();
    if (!client || !client.auth || typeof client.auth.refreshSession !== 'function') {
      broadcastAndShow('expired');
      return res;
    }

    if (!refreshInFlight) {
      refreshInFlight = client.auth.refreshSession()
        .catch(function (err) { return { error: err }; })
        .finally(function () { refreshInFlight = null; });
    }
    var refreshOutcome = await refreshInFlight;
    if (refreshOutcome && refreshOutcome.error) {
      broadcastAndShow('expired');
      return res;
    }

    // Replay once with fresh token. Build the new init by re-reading the
    // updated session so the Authorization header carries the new access_token.
    var newSession = null;
    try {
      var s = await client.auth.getSession();
      newSession = s && s.data && s.data.session;
    } catch (_) { newSession = null; }

    var nextInit = init ? Object.assign({}, init) : {};
    if (newSession && newSession.access_token) {
      var headers = new Headers((init && init.headers) || {});
      // Only swap if the caller had set an Authorization header — otherwise
      // leave it alone (some callers are intentionally anonymous).
      if (headers.has('Authorization')) {
        headers.set('Authorization', 'Bearer ' + newSession.access_token);
        nextInit.headers = headers;
      }
    }
    return await origFetch(input, nextInit);
  }

  window.zkFetch = zkFetch;

  // Make the banner reachable from tests + the cross-tab listener without
  // forcing a fetch round-trip first.
  window.ZKAuthUI = {
    showReauthBanner: showBanner,
    _broadcast: broadcastAndShow,
  };
})();
