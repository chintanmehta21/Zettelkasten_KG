/* ═══════════════════════════════════════════════════════════
   Mobile Summarizer — Touch-optimized, minimal JS
   ═══════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const form     = document.getElementById('summarize-form');
  const urlInput = document.getElementById('url-input');
  const documentInput = document.getElementById('document-input');
  const documentUploadBtn = document.getElementById('document-upload-btn');
  const srcSel   = document.getElementById('source-select');
  const submitBtn= document.getElementById('submit-btn');
  const loading  = document.getElementById('loading');
  const loadTxt  = document.getElementById('loading-text');
  const errorEl  = document.getElementById('error');
  const result   = document.getElementById('result');
  const copyBtn  = document.getElementById('copy-btn');

  // PR #39 / Wave-2 D5: quirky phase-aware messages, matching the
  // desktop typewriter vocabulary. Mobile keeps its lighter rotation
  // model (no skeleton card to mount a typewriter inside).
  const MESSAGES_QUEUED = [
    'Warming up the librarian…',
    'Loading the inkwell…',
    'Stretching the neural cortex…'
  ];
  const MESSAGES_RUNNING = [
    'Skimming the source for the juicy bits…',
    'Distilling the signal from the noise…',
    'Compressing thoughts into Zettel-sized truth…',
    'Polishing the prose; minor existential edits…',
    'Tagging the constellations…'
  ];
  const MESSAGES_LONG = [
    'This one\'s a marathon — sit tight…',
    'Long-form magic in progress…',
    'Worth the wait, promise.'
  ];

  let msgIndex = 0;
  let msgTimer = null;
  let currentPool = MESSAGES_QUEUED;
  let rawSummary = '';

  function showLoading() {
    msgIndex = 0;
    currentPool = MESSAGES_QUEUED;
    loadTxt.textContent = currentPool[0];
    loading.classList.add('active');
    result.classList.remove('active');
    errorEl.classList.remove('active');
    submitBtn.disabled = true;
    msgTimer = setInterval(() => {
      msgIndex = (msgIndex + 1) % currentPool.length;
      loadTxt.textContent = currentPool[msgIndex];
    }, 3000);
  }

  function hideLoading() {
    loading.classList.remove('active');
    submitBtn.disabled = false;
    if (msgTimer) { clearInterval(msgTimer); msgTimer = null; }
  }

  function handleStatusTick(tick) {
    if (!tick) return;
    const elapsed = tick.elapsedMs || 0;
    let nextPool;
    if (elapsed >= 90000) nextPool = MESSAGES_LONG;
    else if (tick.phase === 'running') nextPool = MESSAGES_RUNNING;
    else nextPool = MESSAGES_QUEUED;
    if (nextPool !== currentPool) {
      currentPool = nextPool;
      msgIndex = 0;
      if (loadTxt) loadTxt.textContent = currentPool[0];
    }
  }

  function showError(msg) {
    hideLoading();
    errorEl.textContent = msg;
    errorEl.classList.add('active');
  }

  function validateDocument(file) {
    if (!file) return null;
    const allowed = /\.(pdf|txt|md|markdown|docx)$/i;
    if (!allowed.test(file.name || '')) return 'Upload PDF, TXT, Markdown, or DOCX.';
    if (file.size > 10 * 1024 * 1024) return 'Document is too large (max 10 MB).';
    if (file.size <= 0) return 'Document is empty.';
    return null;
  }

  function clearSelectedDocument() {
    if (documentInput) documentInput.value = '';
    if (documentUploadBtn) documentUploadBtn.classList.remove('has-file');
    if (urlInput) urlInput.placeholder = 'Paste a URL...';
  }

  function getSelectedDocument() {
    return documentInput && documentInput.files ? documentInput.files[0] : null;
  }

  function markdownToHTML(md) {
    if (!md) return '';
    // Escape HTML first: summaries derive from arbitrary ingested pages, so
    // raw innerHTML without escaping is a stored-XSS vector.
    let html = normalizeSummaryMarkdown(md)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
    // Lists
    html = html.replace(/^[\s]*[-•*]\s+(.+)$/gm, '<li>$1</li>');
    html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');
    // Paragraphs
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p>\s*<(h[23]|ul|pre)/g, '<$1');
    html = html.replace(/<\/(h[23]|ul|pre)>\s*<\/p>/g, '</$1>');
    return html;
  }

  function normalizeSummaryMarkdown(text) {
    // Parity with the desktop renderers: split an inline ATX heading the model
    // glued mid-line onto its own block, then drop any trailing ``#``.
    return String(text || '')
      .replace(/(\S)[ \t]+(#{2,6})[ \t]+(?=\S)/g, '$1\n\n$2 ')
      .replace(/^(#{2,6} .+?)[ \t]+#+[ \t]*$/gm, '$1');
  }

  function showResult(data) {
    hideLoading();

    // Badge
    const badge = document.getElementById('result-badge');
    const src = (data.source_type === 'generic' ? 'web' : data.source_type) || 'web';
    badge.textContent = src;
    badge.className = 'm-result-badge ' + src.toLowerCase();

    // Title
    document.getElementById('result-title').textContent = data.title || 'Summary';

    // Brief
    document.getElementById('result-brief').textContent = data.brief_summary || data.one_line_summary || '';

    // Tags
    const tagsEl = document.getElementById('result-tags');
    tagsEl.innerHTML = '';
    if (data.tags && data.tags.length) {
      data.tags.forEach(function (t) {
        const tag = document.createElement('span');
        tag.className = 'm-tag';
        tag.textContent = t;
        tagsEl.appendChild(tag);
      });
    }

    // Detailed summary
    rawSummary = data.summary || '';
    document.getElementById('result-detail').innerHTML = markdownToHTML(rawSummary);

    // Source link
    const srcLink = document.getElementById('source-link');
    srcLink.href = data.source_url || '#';
    if (data.source_type === 'document') {
      srcLink.removeAttribute('href');
      srcLink.setAttribute('aria-disabled', 'true');
    } else {
      srcLink.setAttribute('href', data.source_url || '#');
      srcLink.removeAttribute('aria-disabled');
    }

    result.classList.add('active');
    result.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // Copy handler
  copyBtn.addEventListener('click', function () {
    if (!rawSummary) return;
    navigator.clipboard.writeText(rawSummary).then(function () {
      copyBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
      setTimeout(function () {
        copyBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy';
      }, 2000);
    });
  });

  if (documentUploadBtn && documentInput) {
    documentUploadBtn.addEventListener('click', function () {
      documentInput.click();
    });
    documentInput.addEventListener('change', function () {
      const file = getSelectedDocument();
      errorEl.classList.remove('active');
      documentUploadBtn.classList.toggle('has-file', Boolean(file));
      if (file) {
        urlInput.value = '';
        urlInput.placeholder = file.name || 'Document selected';
      }
    });
  }

  if (urlInput) {
    urlInput.addEventListener('input', function () {
      if (urlInput.value.trim()) clearSelectedDocument();
    });
  }

  // Form submit
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var url = urlInput.value.trim();
    var file = getSelectedDocument();
    if (!url && !file) return showError('Please enter a URL or choose a document.');

    // Basic URL validation
    if (!file && !/^https?:\/\/.+/i.test(url)) {
      if (/^[\w]/.test(url)) url = 'https://' + url;
      else return showError('Please enter a valid URL.');
    }
    if (!file && url.length > 2048) return showError('URL is too long (max 2048 characters).');
    const documentError = file ? validateDocument(file) : null;
    if (documentError) return showError(documentError);

    showLoading();

    if (!window.ZKAddZettel || typeof window.ZKAddZettel.add !== 'function' || typeof window.ZKAddZettel.uploadDocument !== 'function') {
      return showError('Add Zettel API helper failed to load. Please refresh and try again.');
    }

    const request = file
      ? window.ZKAddZettel.uploadDocument({
        file: file,
        clientActionId: window.ZKAddZettel.makeActionId('mobile-document'),
        persist: true,
        surface: 'mobile',
        onStatus: handleStatusTick
      })
      : window.ZKAddZettel.add({
        url: url,
        clientActionId: window.ZKAddZettel.makeActionId('mobile'),
        persist: true,
        surface: 'mobile',
        onStatus: handleStatusTick
      });

    request
    .then(function (data) {
      clearSelectedDocument();
      urlInput.value = '';
      showResult(data.summary || {});
    })
    .catch(function (err) {
      // PR #39 / Wave-2 C2: graceful exhaust — keep the user informed
      // rather than blasting a generic failure for a still-running pipeline.
      if (err && err.code === 'poll_exhausted') {
        hideLoading();
        errorEl.textContent = 'Still summarizing in the background — refresh in a moment to view.';
        errorEl.classList.add('active');
        return;
      }
      showError(err.message || 'Something went wrong. Please try again.');
    });
  });
})();
