// summarizer.js — capture-form handler (iter-2a).
// - URL submit  → window.ZKAddZettel.add(...)        → redirect to /m/zettels
// - File upload → window.ZKAddZettel.uploadDocument(...) → redirect to /m/zettels
// - Source picker: bottom sheet via window.ZK.openSheet (hamburger button)
// - No inline result rendering (removed in iter-2a; results live on /m/zettels)
//
// normalizeSummaryMarkdown is kept (even though /m/ no longer renders summaries
// inline) to preserve the cross-surface regression contract enforced by
// tests/unit/frontend/test_add_zettel_shared_helper.py — mobile should still
// expose the same Markdown normalisation as desktop in case any future surface
// wants to inline-render again.

(function () {
  "use strict";

  const SOURCES = [
    { value: 'auto',       label: 'Auto-detect',   selected: true  },
    { value: 'youtube',    label: 'YouTube'                       },
    { value: 'github',     label: 'GitHub'                        },
    { value: 'reddit',     label: 'Reddit'                        },
    { value: 'newsletter', label: 'Newsletter'                    },
    { value: 'web',        label: 'Web'                           },
  ];

  // Shared cross-surface Markdown post-processor. Mobile no longer renders
  // summaries inline (iter-2a), but the helper stays so any future renderer
  // pulling from window remains consistent with desktop output.
  function normalizeSummaryMarkdown(md) {
    if (typeof md !== 'string') return '';
    // Hardened split: inline ATX heading onto its own block.
    var split = md.replace(/(\S)[ \t]+(#{2,6})[ \t]+(?=\S)/g, '$1\n\n$2 ');
    // Strip a trailing ``#`` run the model appended to a heading line.
    return split.replace(/^(#{2,6} .+?)[ \t]+#+[ \t]*$/gm, '$1');
  }

  async function getAuthToken() {
    try {
      // Canonical: window.getAuthToken (synchronous) from auth-core.js.
      if (typeof window.getAuthToken === 'function') {
        var t = window.getAuthToken();
        if (t) return t;
      }
      if (window.ZKAuth && typeof window.ZKAuth.getSession === 'function') {
        var s = await window.ZKAuth.getSession();
        if (s && s.access_token) return s.access_token;
      }
    } catch (e) { void e; }
    return '';
  }

  function redirectAfterSuccess(data) {
    var d = data || {};
    var s = d.summary || {};
    // AddZettel response carries the id as workspace_zettel_id (Supabase) or
    // node_id (file store) — NOT id/zettel_id. Without one, /m/zettels has no
    // ?just_captured param and an anon user gets bounced to /m/profile.
    var id = d.workspace_zettel_id || d.node_id || d.id || d.zettel_id || d.canonical_zettel_id || '';
    // Flatten into the shape /m/zettels' normalizeZettel reads (title/summary/
    // source live under data.summary), so the just-captured card renders from
    // this cache — anon has no token to re-fetch it from the API.
    var stash = {
      id: id,
      title: s.title || '',
      title_ready: !!s.title,
      brief_summary: s.brief_summary || s.one_line_summary || '',
      detailed_summary: s.detailed_summary || s.summary || '',
      tags: Array.isArray(s.tags) ? s.tags : [],
      source_type: s.source_type || '',
      source_url: s.source_url || '',
      added_at: new Date().toISOString(),
    };
    try { sessionStorage.setItem('zk_just_captured', JSON.stringify(stash)); } catch (e) { void e; }
    var url = '/m/zettels' + (id ? '?just_captured=' + encodeURIComponent(id) : '');
    window.location.assign(url);
  }

  function showError(submitBtn, originalLabel, err) {
    console.error(err);
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = originalLabel;
    }
    var msg = (err && err.message) ? err.message : 'Could not summarize. Please try again.';
    window.alert(msg);
  }

  // Show the quota modal for a quota error, else fall back to showError.
  function handleAddError(submitBtn, originalLabel, err, retry) {
    var qd = (window.ZKQuotaGate && window.ZKQuotaGate.extractQuotaDetail)
      ? window.ZKQuotaGate.extractQuotaDetail(err) : null;
    if (qd && window.ZKQuotaGate) {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = originalLabel; }
      window.ZKQuotaGate.show({ detail: qd, source: 'mobile:add', onResume: retry });
      return;
    }
    showError(submitBtn, originalLabel, err);
  }

  // Returns true if the caller should proceed (sufficient/unknown/fail-open),
  // false if blocked (modal shown). Re-enables the button on block.
  async function quotaProceed(submitBtn, originalLabel) {
    if (!(window.ZKQuotaGate && typeof window.ZKQuotaGate.precheck === 'function')) return true;
    var token = await getAuthToken();
    var ok = await window.ZKQuotaGate.precheck({ feature: 'zettel', token: token, source: 'mobile:add' });
    if (!ok && submitBtn) { submitBtn.disabled = false; submitBtn.textContent = originalLabel; }
    return ok;
  }

  function attach() {
    var form = document.getElementById('summarize-form');
    var picker = document.getElementById('source-picker-btn');
    var fileInput = document.getElementById('document-input');
    var docBtn = document.getElementById('document-upload-btn');
    if (!form || !picker) return;

    // Source-override hamburger sheet (replaces the removed <select>).
    picker.addEventListener('click', function () {
      var current = form.dataset.source || 'auto';
      if (!window.ZK || !window.ZK.openSheet) {
        console.warn('[summarizer] hamburger-sheet primitive not loaded');
        return;
      }
      window.ZK.openSheet({
        title: 'Source',
        options: SOURCES.map(function (s) {
          return { value: s.value, label: s.label, selected: s.value === current };
        }),
        onSelect: function (v) { form.dataset.source = v; },
      });
    });

    // Document upload: paperclip → file input → ZKAddZettel.uploadDocument
    if (docBtn && fileInput) {
      docBtn.addEventListener('click', function () { fileInput.click(); });
      fileInput.addEventListener('change', async function () {
        var file = fileInput.files && fileInput.files[0];
        if (!file) return;
        var submitBtn = document.getElementById('submit-btn');
        var originalLabel = submitBtn ? submitBtn.textContent : 'Summarize';
        if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Summarizing…'; }
        try {
          if (!window.ZKAddZettel || typeof window.ZKAddZettel.uploadDocument !== 'function') {
            throw new Error('ZKAddZettel helper not loaded');
          }
          if (!(await quotaProceed(submitBtn, originalLabel))) { fileInput.value = ''; return; }
          var token = await getAuthToken();
          var data = await window.ZKAddZettel.uploadDocument({
            file: file,
            token: token,
            clientActionId: 'mobile-document',
            persist: true,
            surface: 'mobile',
          });
          redirectAfterSuccess(data);
        } catch (err) {
          handleAddError(submitBtn, originalLabel, err, function () { fileInput.dispatchEvent(new Event('change')); });
          fileInput.value = '';
        }
      });
    }

    // URL submit: form submit → ZKAddZettel.add
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      var urlInput = document.getElementById('url-input');
      var url = (urlInput && urlInput.value || '').trim();
      if (!url) return;
      var submitBtn = document.getElementById('submit-btn');
      var originalLabel = submitBtn ? submitBtn.textContent : 'Summarize';
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Summarizing…'; }

      try {
        if (!window.ZKAddZettel || typeof window.ZKAddZettel.add !== 'function') {
          throw new Error('ZKAddZettel helper not loaded');
        }
        if (!(await quotaProceed(submitBtn, originalLabel))) return;
        var token = await getAuthToken();
        var data = await window.ZKAddZettel.add({
          url: url,
          token: token,
          clientActionId: 'mobile-url',
          persist: true,
          surface: 'mobile',
        });
        redirectAfterSuccess(data);
      } catch (err) {
        handleAddError(submitBtn, originalLabel, err, function () { form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true })); });
      }
    });
  }

  // Export the normaliser so any future inline renderer can pull it off window.
  window.ZKMobileSummary = window.ZKMobileSummary || {};
  window.ZKMobileSummary.normalizeSummaryMarkdown = normalizeSummaryMarkdown;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }
})();
