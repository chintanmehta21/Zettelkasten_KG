/**
 * Zettelkasten — Feedback button controller.
 *
 * Auto-injects the megaphone button into .footer (desktop) and .m-footer
 * (mobile). Opens a modal or bottom-sheet on click. Posts FormData to
 * /api/feedback/submit. No framework. No template engine. Just DOM.
 */
(function () {
  'use strict';

  const STATIC_BASE = '/feedback-ui';

  const SVG_MEGAPHONE_SOLID =
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
    + '<path d="M3 11v2a2 2 0 0 0 2 2h1l2 5h3l-2-5h2l8 4V4l-8 4H5a2 2 0 0 0-2 2v1Z"/></svg>';
  const SVG_MEGAPHONE_OUTLINE =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" '
    + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    + 'stroke-linejoin="round"><path d="M3 11v2a2 2 0 0 0 2 2h1l2 5h3l-2-5h2l8 4V4l-8 4H5a2 2 0 0 0-2 2v1Z"/></svg>';

  let cssLoaded = false;
  let modalTemplate = null;
  let sheetTemplate = null;
  let currentSurface = null;  // 'modal' | 'sheet'

  function loadCSS() {
    if (cssLoaded) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = STATIC_BASE + '/feedback.css';
    document.head.appendChild(link);
    cssLoaded = true;
  }

  async function fetchTemplate(name) {
    const res = await fetch(STATIC_BASE + '/templates/' + name);
    if (!res.ok) throw new Error('Failed to load ' + name);
    return await res.text();
  }

  function buildDesktopButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'footer-icon';
    btn.setAttribute('aria-label', 'Send feedback');
    btn.setAttribute('title', 'Send feedback');
    btn.setAttribute('data-feedback-open', 'desktop');
    btn.innerHTML = SVG_MEGAPHONE_SOLID;
    return btn;
  }

  function buildMobileButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'm-footer-icon';
    btn.setAttribute('aria-label', 'Send feedback');
    btn.setAttribute('data-feedback-open', 'mobile');
    btn.innerHTML = SVG_MEGAPHONE_OUTLINE;
    return btn;
  }

  async function openSurface(kind) {
    loadCSS();
    if (kind === 'modal' && !modalTemplate) modalTemplate = await fetchTemplate('modal.html');
    if (kind === 'sheet' && !sheetTemplate) sheetTemplate = await fetchTemplate('sheet.html');

    const overlay = document.createElement('div');
    overlay.className = (kind === 'modal')
      ? 'zk-feedback-overlay'
      : 'zk-feedback-sheet-overlay';
    overlay.innerHTML =
      '<div class="' + (kind === 'modal' ? 'zk-feedback-backdrop' : 'zk-feedback-sheet-backdrop')
      + '" data-feedback-close></div>'
      + '<div class="' + (kind === 'modal' ? 'zk-feedback-modal' : 'zk-feedback-sheet')
      + '" role="dialog" aria-modal="true">'
      + ((kind === 'sheet') ? '<div class="zk-feedback-sheet-handle" data-feedback-close></div>' : '')
      + '<button class="zk-feedback-close" data-feedback-close aria-label="Close">'
      + '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
      + 'stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/>'
      + '<line x1="6" y1="6" x2="18" y2="18"/></svg></button>'
      + (kind === 'modal' ? modalTemplate : sheetTemplate)
      + '</div>';
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    currentSurface = overlay;
    wireOverlay(overlay);
  }

  function closeSurface() {
    if (!currentSurface) return;
    currentSurface.remove();
    currentSurface = null;
    document.body.style.overflow = '';
  }

  function wireOverlay(root) {
    // Close handlers
    root.querySelectorAll('[data-feedback-close]').forEach(el =>
      el.addEventListener('click', closeSurface));
    document.addEventListener('keydown', escHandler);

    // Tab switching
    const intentInput = root.querySelector('#zk-feedback-intent');
    root.querySelectorAll('.zk-feedback-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        root.querySelectorAll('.zk-feedback-tab').forEach(t => {
          t.classList.remove('active');
          t.setAttribute('aria-selected', 'false');
        });
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        if (intentInput) intentInput.value = tab.dataset.intent;
      });
    });

    // Char counter
    const desc = root.querySelector('textarea[name="description"]');
    const counter = root.querySelector('#zk-feedback-counter');
    if (desc && counter) {
      desc.addEventListener('input', () => {
        counter.textContent = desc.value.length + ' / 4000';
      });
    }

    // Image picker
    const dropzone = root.querySelector('#zk-feedback-dropzone');
    const thumbs = root.querySelector('#zk-feedback-thumbs');
    const pickBtn = root.querySelector('.zk-feedback-pick');
    const files = [];
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/png,image/jpeg,image/webp';
    fileInput.multiple = true;
    pickBtn?.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', e =>
      Array.from(e.target.files || []).forEach(f => addFile(f, thumbs, files)));
    dropzone?.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag-over'); });
    dropzone?.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
    dropzone?.addEventListener('drop', e => {
      e.preventDefault(); dropzone.classList.remove('drag-over');
      Array.from(e.dataTransfer.files || []).forEach(f => addFile(f, thumbs, files));
    });
    document.addEventListener('paste', pasteHandler);

    function pasteHandler(e) {
      if (!currentSurface) return;
      Array.from(e.clipboardData?.items || []).forEach(it => {
        if (it.type.startsWith('image/')) {
          const blob = it.getAsFile();
          if (blob) addFile(blob, thumbs, files);
        }
      });
    }

    // Email-followup toggle reveals anon-email field
    const followup = root.querySelector('input[name="follow_up_email"]');
    const emailField = root.querySelector('.zk-feedback-field-anon-email');
    followup?.addEventListener('change', () => {
      if (!emailField) return;
      emailField.hidden = !followup.checked;
    });

    // Submit
    const form = root.querySelector('#zk-feedback-form');
    form?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Sending…';
      const fd = new FormData(form);
      // Re-attach files (FormData doesn't auto-include our custom-managed list)
      files.forEach(f => fd.append('images', f));
      try {
        const res = await fetch('/api/feedback/submit', {
          method: 'POST',
          body: fd,
          credentials: 'include',
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 202) {
          const id = data.feedback_id || 'FB-????';
          root.querySelector('#zk-feedback-form').hidden = true;
          root.querySelector('#zk-feedback-tabs').hidden = true;
          root.querySelector('#zk-feedback-header').hidden = true;
          const success = root.querySelector('#zk-feedback-success');
          success.hidden = false;
          success.querySelector('#zk-feedback-id').textContent = id;
          setTimeout(closeSurface, 2200);
        } else if (res.status === 429) {
          alert('Daily feedback limit reached. Please try again tomorrow.');
          submitBtn.disabled = false;
          submitBtn.textContent = 'Send feedback';
        } else if (res.status === 503) {
          alert('Feedback is temporarily unavailable. Please email the team directly.');
          submitBtn.disabled = false;
          submitBtn.textContent = 'Send feedback';
        } else {
          alert('Could not send: ' + (data.detail || res.statusText));
          submitBtn.disabled = false;
          submitBtn.textContent = 'Send feedback';
        }
      } catch (err) {
        alert('Network error: ' + err.message);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Send feedback';
      }
    });

    // Cleanup on close
    const origCloseSurface = closeSurface;
    // eslint-disable-next-line no-func-assign
    closeSurface = function () {
      document.removeEventListener('keydown', escHandler);
      document.removeEventListener('paste', pasteHandler);
      origCloseSurface();
      // restore
      closeSurface = origCloseSurface;
    };
  }

  function addFile(file, thumbsEl, files) {
    if (files.length >= 3) return;
    if (file.size > 5 * 1024 * 1024) {
      alert('Image too large (max 5 MB).');
      return;
    }
    files.push(file);
    const t = document.createElement('div');
    t.className = 'zk-feedback-thumb';
    t.textContent = file.name.slice(0, 14);
    const x = document.createElement('button');
    x.className = 'zk-feedback-thumb-remove';
    x.type = 'button';
    x.textContent = '×';
    x.setAttribute('aria-label', 'Remove');
    x.addEventListener('click', () => {
      const idx = files.indexOf(file);
      if (idx >= 0) files.splice(idx, 1);
      t.remove();
    });
    t.appendChild(x);
    thumbsEl.appendChild(t);
  }

  function escHandler(e) {
    if (e.key === 'Escape' && currentSurface) closeSurface();
  }

  // Auto-inject buttons + wire triggers
  function init() {
    const desktop = document.querySelector('footer.footer');
    if (desktop) desktop.appendChild(buildDesktopButton());
    const mobile = document.querySelector('footer.m-footer');
    if (mobile) mobile.appendChild(buildMobileButton());
    document.body.addEventListener('click', (e) => {
      const trigger = e.target.closest('[data-feedback-open]');
      if (!trigger) return;
      e.preventDefault();
      const useSheet = trigger.dataset.feedbackOpen === 'mobile'
        || window.matchMedia('(max-width: 768px)').matches;
      openSurface(useSheet ? 'sheet' : 'modal');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
