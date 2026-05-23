/* Refresh + Download button handlers for the summary popup.
 *
 * Self-contained — both user_home and user_zettels load this file and call
 * ZkRefreshButton.bind({ onRefreshed }) once during their page init, plus
 * ZkRefreshButton.setCurrentNode(node) each time openSummaryPopup runs.
 *
 * Download = window.print() with a body-class flag that print.css picks up.
 * Refresh  = POST /api/zettels/refresh with the current node's URL, then
 *            hand the SummaryDTO payload back to the page via onRefreshed.
 */
(function () {
  'use strict';

  var _currentNode = null;
  var _onRefreshed = null;

  function bind(opts) {
    opts = opts || {};
    _onRefreshed = typeof opts.onRefreshed === 'function' ? opts.onRefreshed : null;

    var downloadBtn = document.getElementById('summary-download');
    var refreshBtn = document.getElementById('summary-refresh');

    if (downloadBtn && !downloadBtn._zkBound) {
      downloadBtn._zkBound = true;
      downloadBtn.addEventListener('click', _onDownloadClick);
    }
    if (refreshBtn && !refreshBtn._zkBound) {
      refreshBtn._zkBound = true;
      refreshBtn.addEventListener('click', _onRefreshClick);
    }
  }

  function setCurrentNode(node) {
    _currentNode = node || null;
    var note = document.getElementById('summary-refresh-note');
    if (note) note.classList.add('hidden');
  }

  function _onDownloadClick() {
    var body = document.body;
    if (!body) return;
    body.classList.add('zk-printing-summary');
    function cleanup() {
      body.classList.remove('zk-printing-summary');
      window.removeEventListener('afterprint', cleanup);
    }
    window.addEventListener('afterprint', cleanup);
    setTimeout(function () {
      try { window.print(); } catch (_) { cleanup(); }
    }, 30);
  }

  function _getAuthToken() {
    try {
      if (window.ZKAuth && typeof window.ZKAuth.getAccessToken === 'function') {
        return window.ZKAuth.getAccessToken();
      }
      if (window.zk_supabase && window.zk_supabase.auth) {
        var s = window.zk_supabase.auth.getSession ? window.zk_supabase.auth.getSession() : null;
        if (s && s.then) return null; // async, skip
      }
    } catch (_) { /* fall through */ }
    return null;
  }

  async function _onRefreshClick() {
    if (!_currentNode || !_currentNode.url) {
      _toast('No URL on this zettel to refresh.');
      return;
    }
    var btn = document.getElementById('summary-refresh');
    if (!btn) return;
    btn.disabled = true;
    btn.classList.add('is-spinning');

    var loader = document.getElementById('summary-loader');
    if (loader) loader.classList.add('active');

    try {
      var headers = { 'Content-Type': 'application/json' };
      var token = _getAuthToken();
      if (token) headers['Authorization'] = 'Bearer ' + token;

      var actionId = 'refresh:' + (_currentNode.id || _currentNode.url) + ':' + Date.now();
      var resp = await fetch('/api/zettels/refresh', {
        method: 'POST',
        credentials: 'include',
        headers: headers,
        body: JSON.stringify({ url: _currentNode.url, client_action_id: actionId })
      });

      if (!resp.ok) {
        if (resp.status === 402) {
          _toast('Quota exhausted. Refresh needs one zettel credit.');
        } else if (resp.status === 401) {
          _toast('Please sign in to refresh.');
        } else {
          _toast('Refresh failed (' + resp.status + ').');
        }
        return;
      }

      var payload = await resp.json();
      _renderRefreshNote(payload && payload.refreshed_at);
      if (_onRefreshed) {
        try { _onRefreshed(payload); }
        catch (e) { console.error('[refresh-button] onRefreshed handler threw', e); }
      }
    } catch (err) {
      console.error('[refresh-button] refresh failed', err);
      _toast('Refresh failed — network error.');
    } finally {
      btn.disabled = false;
      btn.classList.remove('is-spinning');
      if (loader) loader.classList.remove('active');
    }
  }

  function _renderRefreshNote(refreshedAtIso) {
    var note = document.getElementById('summary-refresh-note');
    if (!note) return;
    var when = 'just now';
    if (refreshedAtIso) {
      try {
        var d = new Date(refreshedAtIso);
        if (!isNaN(d.getTime())) {
          when = d.toLocaleString(undefined, {
            month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit'
          });
        }
      } catch (_) { /* keep 'just now' */ }
    }
    note.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<path d="M3 12a9 9 0 0 1 15.5-6.3L21 8M21 4v4h-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>' +
      '</svg><span>Refreshed ' + _escape(when) + '</span>';
    note.classList.remove('hidden');
  }

  function _toast(message) {
    if (window.ZkToast && typeof window.ZkToast.show === 'function') {
      window.ZkToast.show(message);
      return;
    }
    var el = document.createElement('div');
    el.textContent = message;
    el.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);' +
      'background:hsl(0,0%,12%);color:hsl(0,0%,95%);padding:10px 16px;border-radius:6px;' +
      'font-size:13px;z-index:9999;box-shadow:0 4px 14px rgba(0,0,0,0.4);';
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 3200);
  }

  function _escape(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  window.ZkRefreshButton = { bind: bind, setCurrentNode: setCurrentNode };
})();
