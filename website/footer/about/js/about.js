(function () {
  'use strict';

  var SECTION_SELECTOR = '.about-section, .about-hero';
  var sections = Array.prototype.slice.call(document.querySelectorAll(SECTION_SELECTOR));
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var dialog = document.getElementById('about-document-dialog');
  var titleEl = document.getElementById('about-document-title');
  var introEl = document.getElementById('about-document-intro');
  var eyebrowEl = document.getElementById('about-document-eyebrow');
  var metaEl = document.getElementById('about-document-meta');
  var highlightsEl = document.getElementById('about-document-highlights');
  var noteEl = document.getElementById('about-document-note');
  var sectionsEl = document.getElementById('about-document-sections');
  var footerActionsEl = document.querySelector('.about-doc-footer-actions');
  var closeBtn = document.querySelector('.about-doc-close');

  var lastTrigger = null;
  var activeDocKey = 'privacy';

  var DOCUMENTS = {
    privacy: {
      eyebrow: 'Privacy Policy',
      title: 'What We Keep, What We Never Keep',
      intro: 'The browser remembers only the smallest bits of state needed to keep sign-in smooth and the page flow calm.',
      meta: [
        { label: 'Storage', value: 'Tiny browser hints only' },
        { label: 'Retention', value: 'Return path auto-expires' },
        { label: 'Sensitive data', value: 'Never stored here' }
      ],
      highlights: [
        'Local storage holds a compact login hint, not your password.',
        'Session storage keeps a short-lived return path for the auth callback.',
        'The theme placeholder is blank for now and ready for future use.'
      ],
      note: 'Designed to reduce friction without turning the browser into a vault.',
      sections: [
        {
          title: 'What is stored',
          body: 'We store only compact browser hints: whether the browser has logged in before, whether credential persistence was allowed, the preferred landing path, and a blank theme placeholder for the future.'
        },
        {
          title: 'What is never stored',
          body: 'Passwords, access tokens, refresh tokens, cookies, and other secrets stay out of the custom cache. The browser cache exists for UX continuity, not for secret storage.'
        },
        {
          title: 'How it behaves',
          body: 'Redirect state is short-lived and is consumed once. If the state is stale or unsafe, it gets dropped automatically so the app falls back to /home instead of guessing.'
        }
      ],
      footer: 'Plain-language summary: keep the cache tiny, keep secrets out, and let the page recover gracefully.'
    },
    terms: {
      eyebrow: 'Terms of Service',
      title: 'The Rules In Plain English',
      intro: 'Use the app to capture links, organize ideas, and build your graph. The service works best when everyone plays fair.',
      meta: [
        { label: 'Allowed use', value: 'Personal capture & note-taking' },
        { label: 'Service scope', value: 'Web app and linked capture flow' },
        { label: 'Responsibility', value: 'You own the sources you capture' }
      ],
      highlights: [
        'You can use the service for your own capture and organization workflows.',
        'Do not abuse the app, overload the service, or use it in ways that break the experience for others.',
        'Content from external sources belongs to those sources and their owners.'
      ],
      note: 'A clean product works best with a clean set of expectations.',
      sections: [
        {
          title: 'What you can do',
          body: 'You can paste links, create summaries, browse your zettels, and explore the graph. The product is meant to help you keep track of what you have read and captured.'
        },
        {
          title: 'What we ask from you',
          body: 'Use the service responsibly, do not attempt to disrupt the app, and do not rely on it as a substitute for backup copies of important personal material.'
        },
        {
          title: 'What can change',
          body: 'Features may evolve as the product grows. When the experience changes, the goal stays the same: keep capture fast, useful, and easy to revisit.'
        }
      ],
      footer: 'Plain-language summary: capture with care, expect reasonable service behavior, and keep a backup of anything critical.'
    },
    security: {
      eyebrow: 'Data & Security',
      title: 'How Data Stays Small, Safe, and Useful',
      intro: 'The system is built to keep the useful parts available while keeping the sensitive parts narrow and controlled.',
      meta: [
        { label: 'Browser cache', value: 'Non-sensitive hints only' },
        { label: 'Login', value: 'Supabase session storage' },
        { label: 'Network friendliness', value: 'Lightweight pages & fallback paths' }
      ],
      highlights: [
        'The custom browser cache keeps only tiny, non-secret state.',
        'Auth stays in Supabase session storage so the browser can remember a session after the first login.',
        'Fallbacks protect the flow when source extraction or network conditions are rough.'
      ],
      note: 'Security here is about reducing attack surface and reducing surprises at the same time.',
      sections: [
        {
          title: 'Access model',
          body: 'Authenticated pages fetch profile and graph data with the current session, and the browser cache only stores hints that help the UI decide where to send you next.'
        },
        {
          title: 'Retention model',
          body: 'Return-path data expires after a short time and is consumed once. Anything that is no longer useful is pruned rather than left behind indefinitely.'
        },
        {
          title: 'Reliability model',
          body: 'The app prefers small payloads, graceful fallbacks, and low-friction flows so it remains usable on slow or unstable connections.'
        }
      ],
      footer: 'Plain-language summary: data stays small, sign-in remains persistent, and the browser keeps only what it needs.'
    }
  };

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderMeta(items) {
    if (!metaEl) return;
    metaEl.innerHTML = items.map(function (item) {
      return (
        '<div class="about-doc-meta-item">' +
          '<span class="about-doc-meta-label">' + escapeHtml(item.label) + '</span>' +
          '<span class="about-doc-meta-value">' + escapeHtml(item.value) + '</span>' +
        '</div>'
      );
    }).join('');
  }

  function renderHighlights(items) {
    if (!highlightsEl) return;
    highlightsEl.innerHTML = items.map(function (item) {
      return '<div class="about-doc-rail-pill">' + escapeHtml(item) + '</div>';
    }).join('');
  }

  function renderSections(items) {
    if (!sectionsEl) return;
    sectionsEl.innerHTML = items.map(function (item) {
      return (
        '<section class="about-doc-section">' +
          '<h4>' + escapeHtml(item.title) + '</h4>' +
          '<p>' + escapeHtml(item.body) + '</p>' +
        '</section>'
      );
    }).join('');
  }

  function renderFooterActions() {
    if (!footerActionsEl) return;
    footerActionsEl.innerHTML = [
      '<button type="button" class="about-doc-action" data-switch-doc="privacy">Privacy</button>',
      '<button type="button" class="about-doc-action" data-switch-doc="terms">Terms</button>',
      '<button type="button" class="about-doc-action" data-switch-doc="security">Data &amp; Security</button>'
    ].join('');

    Array.prototype.slice.call(footerActionsEl.querySelectorAll('[data-switch-doc]')).forEach(function (btn) {
      btn.addEventListener('click', function () {
        openDoc(btn.getAttribute('data-switch-doc'), btn);
      });
    });
  }

  function renderDoc(key) {
    var doc = DOCUMENTS[key] || DOCUMENTS.privacy;
    activeDocKey = key in DOCUMENTS ? key : 'privacy';

    if (eyebrowEl) eyebrowEl.textContent = doc.eyebrow;
    if (titleEl) titleEl.textContent = doc.title;
    if (introEl) introEl.textContent = doc.intro;
    renderMeta(doc.meta);
    renderHighlights(doc.highlights);
    renderSections(doc.sections);
    if (noteEl) noteEl.textContent = doc.note;
    if (footerActionsEl) {
      renderFooterActions();
    }
  }

  function openDoc(key, trigger) {
    if (!dialog) return;
    if (trigger && (!dialog.contains(trigger) || !dialog.open)) {
      lastTrigger = trigger;
    }

    renderDoc(key);

    if (!dialog.open) {
      dialog.showModal();
      document.body.style.overflow = 'hidden';
      requestAnimationFrame(function () {
        dialog.classList.add('is-open');
      });
    } else {
      dialog.classList.add('is-open');
    }

    if (closeBtn) {
      closeBtn.focus({ preventScroll: true });
    }
  }

  function closeDoc() {
    if (!dialog || !dialog.open) return;
    dialog.classList.remove('is-open');
    window.setTimeout(function () {
      if (!dialog.open) return;
      dialog.close();
    }, 160);
  }

  function restoreFocus() {
    document.body.style.overflow = '';
    if (lastTrigger && typeof lastTrigger.focus === 'function') {
      lastTrigger.focus({ preventScroll: true });
    }
  }

  function getFocusableElements(root) {
    return Array.prototype.slice.call(root.querySelectorAll(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(function (el) {
      return !el.hasAttribute('disabled');
    });
  }

  function trapFocus(event) {
    if (!dialog || !dialog.open || event.key !== 'Tab') return;

    var focusable = getFocusableElements(dialog);
    if (!focusable.length) return;

    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    var active = document.activeElement;

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function setupSectionReveal() {
    if (!sections.length) return;

    if (reduceMotion || !('IntersectionObserver' in window)) {
      sections.forEach(function (section) {
        section.classList.add('is-visible');
      });
      return;
    }

    var observer = new IntersectionObserver(function (entries, io) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        io.unobserve(entry.target);
      });
    }, {
      threshold: 0.12,
      rootMargin: '0px 0px -6% 0px'
    });

    sections.forEach(function (section, index) {
      section.style.transitionDelay = String(index * 80) + 'ms';
      observer.observe(section);
    });
  }

  function bindEvents() {
    Array.prototype.slice.call(document.querySelectorAll('[data-doc]')).forEach(function (card) {
      card.addEventListener('click', function () {
        openDoc(card.getAttribute('data-doc'), card);
      });
    });

    if (closeBtn) {
      closeBtn.addEventListener('click', closeDoc);
    }

    if (dialog) {
      dialog.addEventListener('cancel', function (event) {
        event.preventDefault();
        closeDoc();
      });

      dialog.addEventListener('click', function (event) {
        if (event.target === dialog) {
          closeDoc();
        }
      });

      dialog.addEventListener('close', restoreFocus);
      dialog.addEventListener('keydown', trapFocus);
    }
  }

  function init() {
    setupSectionReveal();
    bindEvents();
    renderDoc(activeDocKey);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
