// summarizer.js — capture-form handler (iter-2a).
// - Source picker: bottom sheet (via window.ZK.openSheet)
// - On submit: POST /api/zettels/add → redirect to /m/zettels?just_captured=<id>
// - No inline result rendering (removed in iter-2a; results live on /m/zettels)

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

  function attach() {
    const form = document.getElementById('summarize-form');
    const picker = document.getElementById('source-picker-btn');
    if (!form || !picker) return;

    picker.addEventListener('click', () => {
      const current = form.dataset.source || 'auto';
      if (!window.ZK || !window.ZK.openSheet) {
        console.warn('[summarizer] hamburger-sheet primitive not loaded');
        return;
      }
      window.ZK.openSheet({
        title: 'Source',
        options: SOURCES.map(s => ({ value: s.value, label: s.label, selected: s.value === current })),
        onSelect: (v) => { form.dataset.source = v; },
      });
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const urlInput = document.getElementById('url-input');
      const url = (urlInput && urlInput.value || '').trim();
      if (!url) return;
      const submitBtn = document.getElementById('submit-btn');
      const originalLabel = submitBtn ? submitBtn.textContent : 'Summarize';
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Summarizing…';
      }

      try {
        const source = form.dataset.source && form.dataset.source !== 'auto'
          ? form.dataset.source
          : undefined;
        const body = { url, surface: 'mobile' };
        if (source) body.source_override = source;

        const r = await fetch('/api/zettels/add', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!r.ok) {
          let detail = '';
          try { detail = (await r.json()).detail || ''; } catch {}
          throw new Error('summarize failed: ' + r.status + (detail ? ' — ' + detail : ''));
        }
        const data = await r.json();
        const id = data.id || data.zettel_id || data.canonical_zettel_id || '';
        try { sessionStorage.setItem('zk_just_captured', JSON.stringify(data)); } catch {}
        window.location.assign('/m/zettels' + (id ? '?just_captured=' + encodeURIComponent(id) : ''));
      } catch (err) {
        console.error(err);
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalLabel;
        }
        alert('Could not summarize. Please try again.');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }
})();
