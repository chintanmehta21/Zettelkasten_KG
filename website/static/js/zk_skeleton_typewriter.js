/*
 * zk_skeleton_typewriter.js — shared quirky-message typewriter for the
 * Add Zettel skeleton card.
 *
 * PR #39 / Wave-2 D5 (2026-05-20). Coheres with the existing
 * .skeleton-line shimmer aesthetic: a single mono-styled line sits
 * inside the skeleton card and types a stage-appropriate phrase, deletes,
 * and types the next. The cycle is driven by `onStatus({phase, elapsedMs})`
 * ticks emitted by ZKAddZettel.add's pollAccepted (see add_zettel_api.js).
 *
 * Public API:
 *   var typer = ZKSkeletonTyper.attach(skeletonEl, options?);
 *   typer.update({phase: 'queued'|'running'|'long'|'succeeded'|'failed', elapsedMs?});
 *   typer.detach();   // safe at any time; cancels pending timers
 *
 * The module injects its own scoped <style> once per document load so
 * each surface CSS file doesn't need to know about it. The accent uses
 * teal (the canonical Kasten/zettel hue, per project UI rule); never
 * purple, never amber outside /knowledge-graph.
 *
 * Stage vocabulary is intentionally quirky/out-of-the-box: avoid
 * generic "loading" copy. Each stage has a small pool that cycles in
 * random order without repeats until the pool is exhausted, then
 * reshuffles. This keeps the line feeling alive on long jobs without
 * being repetitive.
 */
(function () {
  'use strict';

  if (window.ZKSkeletonTyper) return;

  var STYLE_ID = 'zk-skeleton-typewriter-style';
  // Coheres with the existing .skeleton-line shimmer rhythm: the caret
  // blinks at 1Hz, type/erase cadence is ~50ms/char with a 1.6s settle.
  var STYLE_CSS = [
    '.skeleton-typewriter {',
    '  font-family: var(--font-mono, ui-monospace, "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace);',
    '  font-size: 0.82rem;',
    '  line-height: 1.4;',
    '  letter-spacing: 0.005em;',
    /* Brighter teal-tinted muted color so the line stays visible against
     * the skeleton-line shimmer bands. Was rgba(160,160,168,0.78) which
     * faded into the card background under any inherited opacity. */
    '  color: hsla(172, 30%, 78%, 0.96);',
    '  margin-top: 0.65rem;',
    '  min-height: 1.1em;',
    '  white-space: nowrap;',
    '  overflow: hidden;',
    '  text-overflow: clip;',
    '  display: block;',  /* sit on its own row beneath the meta lines */
    '  opacity: 1;',  /* defensive: never inherit a faded opacity */
    '  position: relative;',
    '  z-index: 2;',  /* above any pseudo-element on the skeleton lines */
    '  pointer-events: none;',
    '  user-select: none;',
    '}',
    '.skeleton-typewriter::after {',
    '  content: "▍";',  /* left half block — feels intentional, not jittery */
    '  display: inline-block;',
    '  margin-left: 1px;',
    '  color: var(--accent-teal, #2EB8A6);',
    '  animation: zkSkeletonCaretBlink 1s steps(2, end) infinite;',
    '}',
    '@keyframes zkSkeletonCaretBlink { 50% { opacity: 0; } }',
    /* Subtle fade when the typewriter is detached (e.g., on success). */
    '.skeleton-typewriter.is-detaching {',
    '  transition: opacity 0.35s ease;',
    '  opacity: 0;',
    '}'
  ].join('\n');

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var el = document.createElement('style');
    el.id = STYLE_ID;
    el.textContent = STYLE_CSS;
    document.head.appendChild(el);
  }

  // Stage vocabularies. Tone: dry/playful, brief, never patronizing.
  // Keep each phrase ≤ ~42 chars so it fits a single skeleton row without
  // wrapping on narrow cards.
  var PHRASES = {
    queued: [
      'Warming up the librarian…',
      'Stretching the neural cortex…',
      'Lighting the candles for your Zettel…',
      'Loading the inkwell…',
      'Untangling the URL spaghetti…'
    ],
    running: [
      'Skimming the source for the juicy bits…',
      'Distilling the signal from the noise…',
      'Cross-referencing your Kasten…',
      'Hunting for the load-bearing sentences…',
      'Compressing thoughts into Zettel-sized truth…',
      'Polishing the prose; minor existential edits…',
      'Tagging the constellations…',
      'Pinning the load-bearing claims…',
      'Triangulating the thesis…'
    ],
    long: [
      'This one\'s a marathon — sit tight…',
      'Long-form magic in progress; brewing coffee…',
      'Big think, big patience; almost there…',
      'Reading every footnote so you don\'t have to…',
      'Worth the wait, promise.'
    ]
  };

  function shuffled(arr) {
    var a = arr.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = a[i]; a[i] = a[j]; a[j] = tmp;
    }
    return a;
  }

  function attach(skeletonEl, options) {
    if (!skeletonEl) return null;
    ensureStyle();

    var opts = options || {};
    var node = document.createElement('span');
    node.className = 'skeleton-typewriter';
    node.setAttribute('aria-live', 'polite');
    node.setAttribute('aria-label', 'Summarization in progress');

    // Mount: put the typewriter into the skeleton card, after the last
    // line. If the skeleton has a body line we slot AFTER it.
    skeletonEl.appendChild(node);

    var state = {
      detached: false,
      phase: 'queued',
      elapsedMs: 0,
      queue: shuffled(PHRASES.queued),
      typeTimer: null,
      idleTimer: null,
      cursor: 0,
      currentPhrase: ''
    };

    function clearTimers() {
      if (state.typeTimer) { clearTimeout(state.typeTimer); state.typeTimer = null; }
      if (state.idleTimer) { clearTimeout(state.idleTimer); state.idleTimer = null; }
    }

    function pickPool() {
      if (state.phase === 'succeeded' || state.phase === 'failed') return [];
      // After 90s of total polling, escalate to the "long" vocabulary even
      // if the server still says running — gives the user reassurance.
      if (state.elapsedMs >= 90000) return PHRASES.long;
      if (state.phase === 'running') return PHRASES.running;
      return PHRASES.queued;
    }

    function nextPhrase() {
      if (state.detached) return;
      var pool = pickPool();
      if (!pool.length) return;
      if (!state.queue.length || state.queue._poolKey !== state.phase + state.elapsedMs >= 90000) {
        state.queue = shuffled(pool);
        state.queue._poolKey = state.phase + (state.elapsedMs >= 90000 ? '-long' : '');
      }
      state.currentPhrase = state.queue.shift();
      state.cursor = 0;
      node.textContent = '';
      typeOne();
    }

    function typeOne() {
      if (state.detached) return;
      if (state.cursor >= state.currentPhrase.length) {
        // Settle for 1.6s, then erase + advance.
        state.idleTimer = setTimeout(eraseOne, 1600);
        return;
      }
      node.textContent = state.currentPhrase.slice(0, ++state.cursor);
      state.typeTimer = setTimeout(typeOne, 38 + Math.random() * 24);
    }

    function eraseOne() {
      if (state.detached) return;
      if (!node.textContent.length) { nextPhrase(); return; }
      node.textContent = node.textContent.slice(0, -1);
      state.typeTimer = setTimeout(eraseOne, 18 + Math.random() * 10);
    }

    function update(tick) {
      if (state.detached || !tick) return;
      var prevPhase = state.phase;
      state.phase = tick.phase || prevPhase;
      state.elapsedMs = typeof tick.elapsedMs === 'number' ? tick.elapsedMs : state.elapsedMs;
      if (state.phase === 'succeeded' || state.phase === 'failed') {
        detach();
        return;
      }
      // Phase changed → restart from the new pool; otherwise let the
      // current phrase finish naturally to avoid jitter.
      if (prevPhase !== state.phase) {
        clearTimers();
        state.queue = shuffled(pickPool());
        state.queue._poolKey = state.phase + (state.elapsedMs >= 90000 ? '-long' : '');
        nextPhrase();
      }
    }

    function detach() {
      if (state.detached) return;
      state.detached = true;
      clearTimers();
      if (node.parentNode) {
        node.classList.add('is-detaching');
        // Animate-out then remove. setTimeout matches the CSS .35s.
        setTimeout(function () {
          if (node.parentNode) node.parentNode.removeChild(node);
        }, 380);
      }
    }

    nextPhrase();

    return {
      update: update,
      detach: detach,
      _node: node  // exposed for tests only
    };
  }

  window.ZKSkeletonTyper = {
    attach: attach,
    _PHRASES: PHRASES  // exposed for tests
  };
})();
