/* eslint-disable */
// Self-contained Add-to-Kasten modal. Exposed as window.kgKastenModal.
(function () {
  'use strict';

  const modal       = document.getElementById('kasten-modal');
  if (!modal) return; // KG page not present.
  const backdrop    = document.getElementById('kasten-modal-backdrop');
  const closeBtn    = document.getElementById('kasten-modal-close');
  const subtitle    = document.getElementById('kasten-modal-note-name');
  const listEl      = document.getElementById('kasten-modal-list');
  const errorEl     = document.getElementById('kasten-modal-error');
  const cancelBtn   = document.getElementById('kasten-modal-cancel');
  const addBtn      = document.getElementById('kasten-modal-add');

  let state = { node: null, kastens: [], selectedId: null, headersFn: null, refresh: null };

  function escapeHtml(s) {
    const el = document.createElement('span'); el.textContent = String(s == null ? '' : s); return el.innerHTML;
  }

  function showError(msg) {
    if (!errorEl) return;
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
  }
  function clearError() { if (errorEl) { errorEl.textContent = ''; errorEl.classList.add('hidden'); } }

  function showToast(text) {
    let t = document.querySelector('.kg-toast');
    if (!t) { t = document.createElement('div'); t.className = 'kg-toast'; document.body.appendChild(t); }
    t.textContent = text;
    requestAnimationFrame(() => t.classList.add('visible'));
    setTimeout(() => t.classList.remove('visible'), 2200);
    setTimeout(() => t.remove(), 2700);
  }

  function render() {
    if (!listEl) return;
    listEl.innerHTML = '';
    // Create-new row.
    const createRow = document.createElement('li');
    createRow.className = 'kg-kasten-modal-item kg-kasten-modal-item-create';
    createRow.textContent = '+ Create new Kasten';
    createRow.addEventListener('click', () => renderCreateForm(createRow));
    listEl.appendChild(createRow);
    // Existing kastens.
    state.kastens.forEach(k => {
      const li = document.createElement('li');
      li.className = 'kg-kasten-modal-item' + (state.selectedId === k.id ? ' selected' : '');
      li.dataset.id = k.id;
      li.innerHTML =
        '<span class="kg-filter-dot" style="background:' + escapeHtml(k.color || '#14b8a6') + '"></span>' +
        '<span>' + escapeHtml(k.name) + '</span>';
      li.addEventListener('click', () => {
        state.selectedId = k.id;
        render();
        if (addBtn) addBtn.disabled = false;
      });
      listEl.appendChild(li);
    });
  }

  function renderCreateForm(replaceRow) {
    const form = document.createElement('div');
    form.className = 'kg-kasten-modal-create-form';
    form.innerHTML =
      '<input type="text" class="kg-kasten-modal-create-input" placeholder="Kasten name" maxlength="80" />' +
      '<button type="button" class="kg-kasten-modal-create-go">Create</button>';
    replaceRow.replaceWith(form);
    const input = form.querySelector('input');
    const go = form.querySelector('button');
    input.focus();
    const submit = async () => {
      const name = (input.value || '').trim();
      if (!name) { input.focus(); return; }
      const pricingActionId = form.dataset.pricingActionId || ('kasten:' + Date.now() + ':' + Math.random().toString(36).slice(2));
      form.dataset.pricingActionId = pricingActionId;
      go.disabled = true;
      clearError();
      try {
        const resp = await fetch('/api/rag/sandboxes', {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, state.headersFn()),
          body: JSON.stringify({ name, client_action_id: pricingActionId })
        });
        if (!resp.ok) {
          let payload = null;
          try { payload = await resp.json(); } catch (_) {}
          const detail = payload && payload.detail;
          if (detail && detail.code === 'quota_exhausted' && window.ZKPricing) {
            await window.ZKPricing.openPurchase({
              detail: detail,
              source: 'knowledge-graph:create-kasten',
              resumeAction: { type: 'create_kasten', name: name, nodeId: state.node && state.node.id, clientActionId: pricingActionId },
              onResume: submit
            });
            return;
          }
          throw new Error((detail && detail.message) || 'Could not create Kasten (' + resp.status + ')');
        }
        const data = await resp.json();
        const created = data.sandbox || data;
        state.kastens.unshift({ id: created.id, name: created.name, color: created.color });
        state.selectedId = created.id;
        render();
        if (addBtn) addBtn.disabled = false;
        if (state.refresh) state.refresh();
      } catch (e) {
        showError(e.message || 'Could not create Kasten');
        go.disabled = false;
      }
    };
    go.addEventListener('click', submit);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  }

  async function performAdd() {
    if (!state.node || !state.selectedId) return;
    addBtn.disabled = true;
    clearError();
    try {
      const resp = await fetch('/api/rag/sandboxes/' + encodeURIComponent(state.selectedId) + '/members', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, state.headersFn()),
        body: JSON.stringify({ node_ids: [state.node.id] })
      });
      if (!resp.ok) throw new Error('Could not add to Kasten (' + resp.status + ')');
      const target = state.kastens.find(k => k.id === state.selectedId);
      showToast('Added to ' + (target?.name || 'Kasten'));
      close();
    } catch (e) {
      showError(e.message || 'Could not add to Kasten');
      addBtn.disabled = false;
    }
  }

  function open(node, kastens, headersFn, refresh) {
    state.node = node;
    state.kastens = (kastens || []).slice();
    state.selectedId = null;
    state.headersFn = headersFn || (() => ({}));
    state.refresh = refresh || null;
    if (subtitle) subtitle.textContent = 'Note: "' + (node.name || node.id) + '"';
    if (addBtn) addBtn.disabled = true;
    clearError();
    render();
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function close() {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
  }

  if (closeBtn)  closeBtn.addEventListener('click', close);
  if (cancelBtn) cancelBtn.addEventListener('click', close);
  if (backdrop)  backdrop.addEventListener('click', close);
  if (addBtn)    addBtn.addEventListener('click', performAdd);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) close();
  });

  window.kgKastenModal = { open, close };
})();
