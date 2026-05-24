/* ═════════════════════════════════════════════════════════════
   Mobile KG filter sheet — mode switch, slider readout, chip
   search, multi-select, reset/apply. Exposes a small API for
   graph.js to consume via window.ZKMobileKGFilters.
   ═════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── DOM ──
  var sheet = document.getElementById('sheet');
  if (!sheet) return;

  var tabs = sheet.querySelectorAll('.kg-m-sheet-tab');
  var detailPanel = document.getElementById('sheet-detail');
  var filtersPanel = document.getElementById('sheet-filters');

  var slider = document.getElementById('kg-strength-slider');
  var readout = document.getElementById('kg-strength-readout');
  var sourceChips = document.getElementById('kg-source-chips');

  var segView = filtersPanel ? filtersPanel.querySelectorAll('.kg-m-segment') : [];
  var tagSearch = document.getElementById('kg-tag-search');
  var tagSelected = document.getElementById('kg-tag-chips-selected');
  var tagSuggestions = document.getElementById('kg-tag-suggestions');
  var kastenSearch = document.getElementById('kg-kasten-search');
  var kastenSelected = document.getElementById('kg-kasten-chips-selected');
  var kastenSuggestions = document.getElementById('kg-kasten-suggestions');

  var resetBtn = document.getElementById('kg-filter-reset');
  var applyBtn = document.getElementById('kg-filter-apply');
  var filterCountPill = document.getElementById('kg-filter-count-pill');
  var filterCountBadge = document.getElementById('filter-count');
  var filterToggleBtn = document.getElementById('filter-toggle');
  var recenterBtn = document.getElementById('recenter-btn');

  // ── State (mutable, exposed via getState) ──
  var state = {
    view: 'global',     // 'global' | 'my'
    strength: 0.30,
    sources: new Set(['youtube', 'reddit', 'github', 'substack', 'medium', 'web']),
    tags: new Set(),
    kastens: new Set(),
  };
  var availableTags = [];
  var availableKastens = [];

  // ── Listeners registry — graph.js subscribes ──
  var listeners = { change: [], recenter: [], view: [] };
  function emit(event) { listeners[event].forEach(function (fn) { try { fn(state); } catch (_) {} }); }

  // ── Sheet mode switch ──
  function setMode(mode) {
    tabs.forEach(function (t) {
      var on = t.dataset.mode === mode;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', String(on));
    });
    if (detailPanel) detailPanel.hidden = mode !== 'detail';
    if (filtersPanel) filtersPanel.hidden = mode !== 'filters';
  }
  tabs.forEach(function (t) { t.addEventListener('click', function () { setMode(t.dataset.mode); }); });

  // ── Sheet open/close ──
  function openSheet(mode) {
    sheet.classList.add('open');
    document.body.classList.add('kg-sheet-open');
    setMode(mode || 'detail');
  }
  function closeSheet() {
    sheet.classList.remove('open');
    document.body.classList.remove('kg-sheet-open');
  }
  filterToggleBtn && filterToggleBtn.addEventListener('click', function () {
    if (sheet.classList.contains('open') && !filtersPanel.hidden) {
      closeSheet();
    } else {
      openSheet('filters');
    }
  });

  // ── Slider ──
  slider && slider.addEventListener('input', function () {
    var v = parseFloat(slider.value).toFixed(2);
    state.strength = parseFloat(v);
    if (readout) readout.textContent = v;
  });

  // ── Source chips (toggle) ──
  sourceChips && sourceChips.addEventListener('click', function (e) {
    var chip = e.target.closest('.kg-m-chip');
    if (!chip) return;
    var src = chip.dataset.source;
    chip.classList.toggle('is-active');
    if (chip.classList.contains('is-active')) state.sources.add(src);
    else state.sources.delete(src);
  });

  // ── Segmented view toggle ──
  Array.prototype.forEach.call(segView, function (seg) {
    seg.addEventListener('click', function () {
      if (seg.getAttribute('aria-disabled') === 'true') return;
      Array.prototype.forEach.call(segView, function (s) {
        s.classList.remove('is-active');
        s.setAttribute('aria-checked', 'false');
      });
      seg.classList.add('is-active');
      seg.setAttribute('aria-checked', 'true');
      state.view = seg.dataset.view;
      emit('view');
    });
  });

  // ── Multi-select chip search (tags + kastens, same logic) ──
  function bindChipSearch(searchInput, suggestionsEl, selectedEl, available, stateSet) {
    if (!searchInput) return;
    function renderSelected() {
      selectedEl.innerHTML = '';
      Array.from(stateSet).forEach(function (v) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'kg-m-chip is-active';
        chip.textContent = v + ' ×';
        chip.addEventListener('click', function () {
          stateSet.delete(v);
          renderSelected();
        });
        selectedEl.appendChild(chip);
      });
    }
    function renderSuggestions(q) {
      suggestionsEl.innerHTML = '';
      if (!q) return;
      var matches = available
        .filter(function (v) { return v.toLowerCase().indexOf(q.toLowerCase()) > -1 && !stateSet.has(v); })
        .slice(0, 7);
      matches.forEach(function (v) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'kg-m-chip';
        chip.textContent = v;
        chip.addEventListener('click', function () {
          stateSet.add(v);
          renderSelected();
          searchInput.value = '';
          suggestionsEl.innerHTML = '';
        });
        suggestionsEl.appendChild(chip);
      });
    }
    searchInput.addEventListener('input', function () { renderSuggestions(searchInput.value.trim()); });
    renderSelected();
    return { renderSelected: renderSelected, renderSuggestions: renderSuggestions };
  }
  var tagApi = bindChipSearch(tagSearch, tagSuggestions, tagSelected, availableTags, state.tags);
  var kastenApi = bindChipSearch(kastenSearch, kastenSuggestions, kastenSelected, availableKastens, state.kastens);

  // ── Reset + Apply ──
  resetBtn && resetBtn.addEventListener('click', function () {
    var prevView = state.view;
    state.strength = 0.30;
    state.sources = new Set(['youtube', 'reddit', 'github', 'substack', 'medium', 'web']);
    state.tags = new Set();
    state.kastens = new Set();
    state.view = 'global';
    // Repaint UI
    if (slider) { slider.value = '0.30'; }
    if (readout) readout.textContent = '0.30';
    sourceChips && sourceChips.querySelectorAll('.kg-m-chip').forEach(function (c) { c.classList.add('is-active'); });
    tagApi && tagApi.renderSelected();
    kastenApi && kastenApi.renderSelected();
    Array.prototype.forEach.call(segView, function (s) {
      s.classList.toggle('is-active', s.dataset.view === 'global');
      s.setAttribute('aria-checked', String(s.dataset.view === 'global'));
    });
    updateBadges();
    emit('change');
    if (prevView !== 'global') emit('view');
  });
  applyBtn && applyBtn.addEventListener('click', function () {
    updateBadges();
    emit('change');
    closeSheet();
  });

  // ── Recenter ──
  recenterBtn && recenterBtn.addEventListener('click', function () { emit('recenter'); });

  function activeCount() {
    var n = 0;
    if (state.strength > 0.30) n += 1;
    if (state.sources.size < 6) n += (6 - state.sources.size);
    n += state.tags.size;
    n += state.kastens.size;
    if (state.view !== 'global') n += 1;
    return n;
  }
  function updateBadges() {
    var n = activeCount();
    if (filterCountPill) filterCountPill.textContent = String(n);
    if (filterCountBadge) {
      filterCountBadge.hidden = n === 0;
      filterCountBadge.textContent = String(n);
    }
  }
  updateBadges();

  // ── Public API for graph.js ──
  window.ZKMobileKGFilters = {
    getState: function () { return state; },
    on: function (event, fn) { if (listeners[event]) listeners[event].push(fn); },
    setAvailable: function (tags, kastens) {
      availableTags.length = 0; Array.prototype.push.apply(availableTags, tags || []);
      availableKastens.length = 0; Array.prototype.push.apply(availableKastens, kastens || []);
    },
    enablePersonalView: function (enabled) {
      Array.prototype.forEach.call(segView, function (s) {
        if (s.dataset.view !== 'my') return;
        if (enabled) s.removeAttribute('aria-disabled');
        else s.setAttribute('aria-disabled', 'true');
      });
    },
    openDetail: function () { openSheet('detail'); },
    closeSheet: closeSheet,
  };
})();
