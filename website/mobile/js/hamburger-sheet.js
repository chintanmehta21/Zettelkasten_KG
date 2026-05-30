// hamburger-sheet.js — bottom-sheet primitive (single-instance at a time).
// Usage:
//   ZK.openSheet({
//     title: 'Pick source',
//     options: [{ value: 'auto', label: 'Auto-detect', selected: true }, ...],
//     onSelect: (value) => { ... },
//   });

(function () {
  "use strict";

  let activeRoot = null;

  function ensureRoot() {
    if (activeRoot) return activeRoot;
    const root = document.createElement('div');
    root.className = 'zk-sheet-root';
    root.innerHTML =
      '<div class="zk-sheet-backdrop" data-close="1"></div>' +
      '<div class="zk-sheet" role="dialog" aria-modal="true">' +
        '<div class="zk-sheet-handle"></div>' +
        '<div class="zk-sheet-title"></div>' +
        '<div class="zk-sheet-list"></div>' +
      '</div>';
    document.body.appendChild(root);
    root.addEventListener('click', (e) => {
      if (e.target instanceof HTMLElement && e.target.dataset.close === '1') closeSheet();
    });
    activeRoot = root;
    return root;
  }

  function openSheet(spec) {
    const root = ensureRoot();
    root.querySelector('.zk-sheet-title').textContent = spec.title || '';
    const list = root.querySelector('.zk-sheet-list');
    list.innerHTML = '';
    spec.options.forEach((opt) => {
      const cell = document.createElement('button');
      cell.type = 'button';
      // Per-value modifier (sanitised) lets callers theme cells via CSS — e.g.
      // source-type accent colours on the capture sheet (see hamburger-sheet.css).
      const valueMod = String(opt.value || '').replace(/[^a-z0-9_-]/gi, '');
      cell.className = 'zk-sheet-cell' + (opt.selected ? ' is-selected' : '') +
        (valueMod ? ' zk-sheet-cell--' + valueMod : '');
      cell.dataset.value = opt.value;
      cell.innerHTML = (opt.icon || '') + '<span class="zk-sheet-cell-label">' + opt.label + '</span>';
      cell.addEventListener('click', () => {
        spec.onSelect && spec.onSelect(opt.value);
        closeSheet();
      });
      list.appendChild(cell);
    });
    requestAnimationFrame(() => root.classList.add('is-open'));
  }

  function closeSheet() {
    if (!activeRoot) return;
    activeRoot.classList.remove('is-open');
    setTimeout(() => {
      if (activeRoot) { activeRoot.remove(); activeRoot = null; }
    }, 250);
  }

  window.ZK = window.ZK || {};
  window.ZK.openSheet = openSheet;
  window.ZK.closeSheet = closeSheet;
})();
