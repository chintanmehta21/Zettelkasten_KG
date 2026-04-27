/* Kasten-card-shuffle loader primitive (Phase 3D).
 *
 * Three states for three distinct waiting moments on the Kasten surface:
 *
 *   showLongPipelineLoader(container)         → 3-card lively shuffle +
 *                                                cycling stage captions
 *   showHeartbeatLoader(container, onRetry)   → calmer shuffle + Retry now
 *   showQueuedLoader(container, seconds)      → single breathing card +
 *                                                live countdown
 *
 * Each function returns a stop() teardown that clears its interval and
 * removes the rendered DOM. Callers must call stop() before swapping
 * states (or before appending real content to the container) so timers
 * never leak.
 *
 * Style decisions are TEAL-only — see ../css/loader.css.
 *
 * Exposed as window.ZkLoader to match the non-bundled global pattern of
 * the rest of user_rag.js.
 */
(function () {
  'use strict';

  var STAGE_CAPTIONS = [
    'Searching your Zettels…',
    'Reading the right cards…',
    'Connecting the dots…',
    'Drafting your answer…'
  ];
  var STAGE_INTERVAL_MS = 3000;

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = String(value == null ? '' : value);
    return div.innerHTML;
  }

  function clearContainer(container) {
    if (container) container.innerHTML = '';
  }

  function makeShell(container, stateClass, opts) {
    clearContainer(container);
    var cardCount = (opts && opts.cardCount) || 3;
    var cards = '';
    for (var i = 0; i < cardCount; i++) {
      cards += '<span class="kasten-card" aria-hidden="true"></span>';
    }
    var captionHtml = (opts && opts.captionHtml) || '';
    var trailing = (opts && opts.trailingHtml) || '';
    container.innerHTML =
      '<div class="kasten-shuffle ' + stateClass + '" role="status" aria-live="polite">' +
        '<span class="kasten-cards">' + cards + '</span>' +
        '<span class="kasten-caption">' + captionHtml + '</span>' +
        trailing +
      '</div>';
    return container.querySelector('.kasten-shuffle');
  }

  function showLongPipelineLoader(container) {
    if (!container) return function () {};
    var idx = 0;
    var shell = makeShell(container, 'long-pipeline', {
      cardCount: 3,
      captionHtml: escapeHtml(STAGE_CAPTIONS[0])
    });
    var caption = shell.querySelector('.kasten-caption');
    var tick = setInterval(function () {
      idx = (idx + 1) % STAGE_CAPTIONS.length;
      if (caption) caption.textContent = STAGE_CAPTIONS[idx];
    }, STAGE_INTERVAL_MS);
    return function stop() {
      clearInterval(tick);
      if (container.contains(shell)) clearContainer(container);
    };
  }

  function showHeartbeatLoader(container, onRetry) {
    if (!container) return function () {};
    var shell = makeShell(container, 'heartbeat', {
      cardCount: 3,
      captionHtml: 'Reconnecting your Kasten…',
      trailingHtml: '<button type="button" class="kasten-retry">↻ Retry now</button>'
    });
    var btn = shell.querySelector('.kasten-retry');
    var handler = function () {
      if (typeof onRetry === 'function') onRetry();
    };
    if (btn) btn.addEventListener('click', handler);
    return function stop() {
      if (btn) btn.removeEventListener('click', handler);
      if (container.contains(shell)) clearContainer(container);
    };
  }

  function showQueuedLoader(container, seconds) {
    if (!container) return function () {};
    var s = Math.max(1, parseInt(seconds, 10) || 1);
    var shell = makeShell(container, 'queued', {
      cardCount: 1,
      captionHtml:
        'Lots of questions right now — retrying in ' +
        '<span class="kasten-countdown">' + s + '</span>s…'
    });
    var cd = shell.querySelector('.kasten-countdown');
    var tick = setInterval(function () {
      s -= 1;
      if (s <= 0) {
        clearInterval(tick);
        if (container.contains(shell)) clearContainer(container);
      } else if (cd) {
        cd.textContent = String(s);
      }
    }, 1000);
    return function stop() {
      clearInterval(tick);
      if (container.contains(shell)) clearContainer(container);
    };
  }

  window.ZkLoader = {
    showLongPipelineLoader: showLongPipelineLoader,
    showHeartbeatLoader: showHeartbeatLoader,
    showQueuedLoader: showQueuedLoader
  };
})();
