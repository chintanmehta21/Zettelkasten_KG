/* Shared summary popup module.
 * Single source of truth for the .zettels-summary-overlay modal used on
 * /home, /home/zettels, and /knowledge-graph. Exposes window.ZKSummary
 * with { open(node), close(), setCurrentNode(node) }.
 *
 * Helpers (math, mask, render, extract) extracted from user_zettels.js so
 * that page can call window.ZKSummary.open(node) instead of carrying its own
 * inline copy. KG side panel "Summary" button is the third consumer.
 */
(function () {
  'use strict';

  // ---- math + KaTeX-aware $-mask helpers (copied verbatim) ----
  function _mathRenderArxiv(rootEl, sourceType) {
    if (!rootEl) return;
    rootEl.setAttribute('data-math-source', String(sourceType || ''));
    // DYNAMIC GATE: today only 'arxiv'; widen this set later if accuracy holds.
    var MATH_SOURCES = { arxiv: true };
    if (!MATH_SOURCES[String(sourceType || '').toLowerCase()]) return;
    if (typeof window.renderMathInElement !== 'function') return;
    try {
      window.renderMathInElement(rootEl, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '\\[', right: '\\]', display: true },
          { left: '\\(', right: '\\)', display: false },
          { left: '$', right: '$', display: false }
        ],
        // smart-dollar: a $ that opens math must be followed by a
        // non-space, non-digit; closing $ preceded by non-space. KaTeX
        // auto-render has no built-in guard, so pre-mask price-like $.
        preProcess: function (math) { return math; },
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
        ignoredClasses: ['no-math'],
        throwOnError: false,
        trust: false,
        maxExpand: 1000
      });
    } catch (e) {
      // Never let math rendering break the popup.
      if (window.console && console.warn) console.warn('[katex] skipped', e);
    }
  }

  // Pre-mask ONLY genuine currency $ so it can't be mis-paired as math, while
  // preserving real $...$ / $$...$$ KaTeX delimiter pairs (incl. numeric-leading
  // inline LaTeX like $1/N$, $2\pi$). Applied to text nodes only, pre-render.
  // Mirrors KaTeX auto-render delimiter rules: an opening $ may not be
  // immediately followed by whitespace and a closing $ may not be immediately
  // preceded by whitespace; \$ is an escaped literal (never a delimiter).
  function _maskPriceDollarsStr(s) {
    var SENT = '﹩'; // ﹩ small dollar sign sentinel
    var out = '';
    var i = 0;
    var n = s.length;
    while (i < n) {
      var ch = s[i];
      if (ch === '\\' && s[i + 1] === '$') { out += '\\$'; i += 2; continue; }
      if (ch !== '$') { out += ch; i += 1; continue; }
      // $$ display, then $ inline. Try to find a valid closing delimiter.
      var isDisplay = s[i + 1] === '$';
      var openLen = isDisplay ? 2 : 1;
      var contentStart = i + openLen;
      // KaTeX: opening delimiter not immediately followed by whitespace.
      var bad = contentStart >= n || /\s/.test(s[contentStart]);
      var close = -1;
      if (!bad) {
        for (var j = contentStart; j < n; j++) {
          if (s[j] === '\\') { j += 1; continue; }
          if (isDisplay) {
            if (s[j] === '$' && s[j + 1] === '$') {
              if (j > contentStart && !/\s/.test(s[j - 1])) { close = j; }
              break;
            }
          } else if (s[j] === '$') {
            // closing $ not immediately preceded by whitespace, non-empty span.
            if (j > contentStart && !/\s/.test(s[j - 1])) { close = j; }
            break;
          }
        }
      }
      if (close !== -1) {
        // Valid math span: emit verbatim so KaTeX still pairs/renders it.
        var end = close + openLen;
        out += s.slice(i, end);
        i = end;
        continue;
      }
      // Unpaired $: currency iff followed by digit/whitespace → mask it.
      if (contentStart < n && /[\s\d]/.test(s[i + 1])) {
        out += SENT;
      } else {
        out += '$';
      }
      i += 1;
    }
    return out;
  }

  function _maskPriceDollars(rootEl) {
    if (!rootEl) return;
    var walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, null);
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue.indexOf('$') !== -1) {
        node.nodeValue = _maskPriceDollarsStr(node.nodeValue);
      }
    }
  }

  function _unmaskPriceDollars(rootEl) {
    if (!rootEl) return;
    var walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, null);
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue.indexOf('﹩') !== -1) {
        node.nodeValue = node.nodeValue.replace(/﹩/g, '$');
      }
    }
  }

  // ---- body scroll lock (multi-consumer reference-counted) ----
  var _bodyLockCount = 0;
  function setBodyScrollLocked(locked) {
    if (locked) {
      _bodyLockCount += 1;
    } else {
      _bodyLockCount = Math.max(0, _bodyLockCount - 1);
    }
    document.body.style.overflow = _bodyLockCount > 0 ? 'hidden' : '';
  }

  // ---- dual-summary render + extract (copied verbatim) ----
  function renderDualSummary(container, parts) {
    container.innerHTML = '';
    var brief = (parts && parts.brief) ? String(parts.brief).trim() : '';
    var detailed = (parts && parts.detailed) ? String(parts.detailed).trim() : '';
    var structured = (parts && isStructuredDetailed(parts.detailedStructured))
      ? parts.detailedStructured
      : null;
    var hasBrief = brief && brief !== 'No summary available for this zettel.';
    var hasDetailed = structured
      ? true
      : (detailed && detailed !== brief && detailed !== 'No summary available for this zettel.');

    if (!hasBrief && !hasDetailed) {
      container.textContent = 'No summary available for this zettel.';
      return;
    }

    if (hasBrief) {
      var briefWrap = document.createElement('div');
      briefWrap.className = 'zettels-summary-section zettels-summary-brief';
      var briefHeading = document.createElement('h3');
      briefHeading.className = 'zettels-summary-section-heading';
      briefHeading.textContent = 'Brief';
      var briefBody = document.createElement('p');
      briefBody.className = 'zettels-summary-section-body';
      briefBody.textContent = brief;
      briefWrap.appendChild(briefHeading);
      briefWrap.appendChild(briefBody);
      container.appendChild(briefWrap);
    }

    if (hasDetailed) {
      if (hasBrief) {
        var divider = document.createElement('hr');
        divider.className = 'zettels-summary-divider';
        container.appendChild(divider);
      }
      var detailedWrap = document.createElement('div');
      detailedWrap.className = 'zettels-summary-section zettels-summary-detailed';
      var detailedHeading = document.createElement('h3');
      detailedHeading.className = 'zettels-summary-section-heading';
      detailedHeading.textContent = 'Detailed';
      detailedWrap.appendChild(detailedHeading);
      if (structured) {
        renderStructuredDetailed(detailedWrap, structured);
      } else {
        renderMarkdownLite(detailedWrap, detailed);
      }
      container.appendChild(detailedWrap);
    }
  }

  function isStructuredDetailed(value) {
    if (!Array.isArray(value) || value.length === 0) return false;
    for (var i = 0; i < value.length; i++) {
      var section = value[i];
      if (!section || typeof section !== 'object' || Array.isArray(section)) return false;
      if (!('heading' in section || 'bullets' in section || 'sub_sections' in section || 'subSections' in section)) {
        return false;
      }
    }
    return true;
  }

  // Coerce any shape (array / single dict / stringified JSON / Python repr) into
  // a normalized structured-sections array, or null if nothing usable. Central
  // funnel used by extractSummaryParts so every render path gets the same
  // defensive recovery regardless of how the summary was persisted.
  function coerceStructuredDetailed(value) {
    if (value == null) return null;
    if (isStructuredDetailed(value)) return value;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      var wrapped = [value];
      if (isStructuredDetailed(wrapped)) return wrapped;
    }
    if (typeof value !== 'string') return null;
    var trimmed = value.trim();
    if (!trimmed) return null;
    if (trimmed.charAt(0) === '[' || trimmed.charAt(0) === '{') {
      var attempts = [trimmed];
      if (trimmed.indexOf("'") !== -1) attempts.push(trimmed.replace(/'/g, '"'));
      for (var i = 0; i < attempts.length; i++) {
        try {
          var parsed = JSON.parse(attempts[i]);
          if (isStructuredDetailed(parsed)) return parsed;
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            var wrappedParsed = [parsed];
            if (isStructuredDetailed(wrappedParsed)) return wrappedParsed;
          }
        } catch (err) { void err; }
      }
    }
    // Markdown-string fallback: parse "## heading\n- bullet" form into
    // structured sections so the JSON-bullet expander + raw-schema heading
    // renamer kick in. Without this, rows that stored detailed_summary as a
    // plain markdown blob (older writer path, Steve Jobs row etc.) render as
    // literal text with raw "thesis" headings and {timestamp, title, bullets}
    // JSON leaking through as bullets.
    if (trimmed.indexOf('## ') !== -1 || trimmed.indexOf('### ') !== -1) {
      var sections = parseMarkdownToSections(trimmed);
      if (sections && sections.length) return sections;
    }
    return null;
  }

  function parseMarkdownToSections(markdown) {
    var lines = String(markdown || '').split(/\r?\n/);
    var sections = [];
    var current = null;
    var subHeading = null;
    function ensureCurrent() {
      if (!current) { current = { heading: 'Overview', bullets: [], sub_sections: {} }; sections.push(current); }
      return current;
    }
    function pushBullet(text) {
      var c = ensureCurrent();
      if (subHeading) {
        if (!c.sub_sections[subHeading]) c.sub_sections[subHeading] = [];
        c.sub_sections[subHeading].push(text);
      } else {
        c.bullets.push(text);
      }
    }
    for (var i = 0; i < lines.length; i++) {
      var raw = lines[i];
      var line = raw.replace(/\s+$/, '');
      if (!line.trim()) continue;
      var h2 = line.match(/^##\s+(.*)$/);
      var h3 = line.match(/^###\s+(.*)$/);
      var bullet = line.match(/^\s*[-*]\s+(.*)$/);
      if (h2) {
        current = { heading: h2[1].trim(), bullets: [], sub_sections: {} };
        sections.push(current);
        subHeading = null;
        continue;
      }
      if (h3) {
        subHeading = h3[1].trim();
        ensureCurrent();
        continue;
      }
      if (bullet) {
        pushBullet(bullet[1].trim());
        continue;
      }
      // Plain paragraph line → treat as a bullet in current section
      pushBullet(line.trim());
    }
    return sections.length ? sections : null;
  }

  // Map raw pipeline schema keys (youtube/newsletter/github/reddit) to
  // human-facing labels. Drop fields that should never render as their own
  // section (``format`` becomes a bullet inside Overview, never standalone).
  var RAW_HEADING_MAP = {
    'thesis': 'Core argument',
    'core_argument': 'Core argument',
    'issue_thesis': 'Core argument',
    'chapters_or_segments': 'Chapter walkthrough',
    'chapter_walkthrough': 'Chapter walkthrough',
    'demonstrations': 'Demonstrations',
    'closing_takeaway': 'Closing remarks',
    'closing_remarks': 'Closing remarks',
    'publication_identity': 'Publication identity',
    'sections': 'Sections',
    'conclusions_or_recommendations': 'Conclusions & recommendations',
    'cta': 'Call to action',
    'stance': 'Stance',
    'overview': 'Overview',
    'format': 'Format',
    'format_and_speakers': 'Format and speakers'
  };

  function prettyHeading(raw) {
    if (!raw) return raw;
    var key = String(raw).trim().toLowerCase();
    if (RAW_HEADING_MAP.hasOwnProperty(key)) return RAW_HEADING_MAP[key];
    // Title-case snake_case / lowercase fallbacks so "chapter_walkthrough"
    // style keys never leak through to the UI as-is.
    return String(raw)
      .replace(/_+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/^\w/, function (c) { return c.toUpperCase(); });
  }

  // Strip leading timestamp prefix ("00:00 — Title", "1h23m Title",
  // "[12:34] Title") from chapter headings. Per product decision timestamps
  // are never rendered in detailed summaries — too error-prone, low reward.
  function stripTimestampPrefix(label) {
    if (!label) return label;
    return String(label)
      .replace(/^\s*\[?\d{1,2}(?::\d{2}){1,2}\]?\s*[—\-:]\s*/, '')
      .replace(/^\s*\[?\d{1,2}(?::\d{2}){1,2}\]?\s+/, '')
      .replace(/^\s*\d{4}\s*[—\-]\s*/, '')  // year prefixes ("1852 — title")
      .trim();
  }

  // Chapter bullets sometimes arrive as stringified JSON objects
  // ({"timestamp":"...", "title":"...", "bullets":[...]}). Normalize them to
  // proper sub-sections so the renderer never shows a JSON blob.
  function expandChapterJsonBullets(section) {
    var bullets = Array.isArray(section.bullets) ? section.bullets : [];
    if (!bullets.length) return section;
    var subs = {};
    var leftover = [];
    bullets.forEach(function (b) {
      if (typeof b !== 'string') { leftover.push(b); return; }
      var t = b.trim();
      if (t.charAt(0) !== '{') { leftover.push(b); return; }
      try {
        var parsed = JSON.parse(t);
        if (parsed && typeof parsed === 'object') {
          var title = stripTimestampPrefix(String(parsed.title || '').trim());
          if (!title) { leftover.push(b); return; }
          var sub = Array.isArray(parsed.bullets) ? parsed.bullets.filter(Boolean).map(String) : [];
          if (!sub.length && parsed.summary) sub = [String(parsed.summary)];
          var key = title;
          var idx = 2;
          while (Object.prototype.hasOwnProperty.call(subs, key)) { key = title + ' (' + idx + ')'; idx += 1; }
          subs[key] = sub;
          return;
        }
      } catch (e) { void e; }
      leftover.push(b);
    });
    if (!Object.keys(subs).length) return section;
    var merged = {};
    if (section.sub_sections && typeof section.sub_sections === 'object') {
      Object.keys(section.sub_sections).forEach(function (k) { merged[k] = section.sub_sections[k]; });
    }
    Object.keys(subs).forEach(function (k) { merged[k] = subs[k]; });
    return {
      heading: section.heading,
      bullets: leftover,
      sub_sections: merged
    };
  }

  function normalizeRawSchemaSections(sections) {
    if (!Array.isArray(sections)) return sections;
    var out = [];
    sections.forEach(function (section) {
      if (!section || typeof section !== 'object') return;
      // Skip sections that should collapse (format is a tag, not a section)
      var rawKey = String(section.heading || '').trim().toLowerCase();
      if (rawKey === 'format') return;
      var working = expandChapterJsonBullets(section);
      var prettySubs = {};
      var subs = working.sub_sections && typeof working.sub_sections === 'object' ? working.sub_sections : {};
      Object.keys(subs).forEach(function (sk) {
        var cleanSk = stripTimestampPrefix(prettyHeading(sk));
        prettySubs[cleanSk || sk] = subs[sk];
      });
      out.push({
        heading: prettyHeading(working.heading || ''),
        bullets: Array.isArray(working.bullets) ? working.bullets : [],
        sub_sections: prettySubs
      });
    });
    return out;
  }

  // Build a chevron SVG used in the collapsible H1 button.
  function buildChevronSpan() {
    var span = document.createElement('span');
    span.className = 'zettels-summary-h2-chevron';
    span.setAttribute('aria-hidden', 'true');
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none">' +
      '<path d="M6 9L12 15L18 9" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"></path></svg>';
    return span;
  }

  // Toggle a collapsible H1 section. Reads/writes ``aria-expanded`` on the
  // heading and ``data-collapsed`` on the paired panel. Sets max-height on
  // expansion to the panel's natural scrollHeight so the CSS transition
  // animates from 0 -> measured-height -> auto.
  function setSectionExpanded(headingEl, panelEl, expanded) {
    headingEl.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    if (expanded) {
      panelEl.removeAttribute('data-collapsed');
      // Measure target height, then animate. Using requestAnimationFrame
      // so the browser registers the starting 0px state before changing.
      panelEl.style.maxHeight = '0px';
      requestAnimationFrame(function () {
        var target = panelEl.scrollHeight;
        panelEl.style.maxHeight = target + 'px';
      });
      // After the transition completes, drop the inline max-height so
      // dynamic content (image loads, etc.) reflows naturally.
      var clearMax = function () {
        panelEl.style.maxHeight = '';
        panelEl.removeEventListener('transitionend', clearMax);
      };
      panelEl.addEventListener('transitionend', clearMax);
    } else {
      // Capture current height, then transition to 0.
      var current = panelEl.scrollHeight;
      panelEl.style.maxHeight = current + 'px';
      requestAnimationFrame(function () {
        panelEl.setAttribute('data-collapsed', 'true');
        panelEl.style.maxHeight = '0px';
      });
    }
  }

  function attachToggle(headingEl, panelEl) {
    headingEl.setAttribute('role', 'button');
    headingEl.setAttribute('tabindex', '0');
    headingEl.setAttribute('aria-expanded', 'true');
    var sectionId = 'zk-sec-' + Math.random().toString(36).slice(2, 9);
    panelEl.id = sectionId;
    headingEl.setAttribute('aria-controls', sectionId);

    var handler = function (event) {
      var expanded = headingEl.getAttribute('aria-expanded') === 'true';
      setSectionExpanded(headingEl, panelEl, !expanded);
      event.preventDefault();
    };
    headingEl.addEventListener('click', handler);
    headingEl.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
        handler(event);
      }
    });
  }

  function renderStructuredDetailed(container, sections) {
    sections = normalizeRawSchemaSections(sections) || sections;
    var firstSectionRendered = false;
    sections.forEach(function (section) {
      if (!section || typeof section !== 'object') return;
      var heading = section.heading == null ? '' : String(section.heading).trim();

      var bullets = Array.isArray(section.bullets) ? section.bullets : [];
      var subs = section.sub_sections || section.subSections;
      var hasSubs = subs && typeof subs === 'object' && !Array.isArray(subs)
        && Object.keys(subs).length > 0;

      // If there is no heading, render bullets+subs flat (legacy content
      // without an anchor heading — never collapsible).
      if (!heading) {
        appendSectionBody(container, bullets, subs, hasSubs);
        return;
      }

      var h4 = document.createElement('h4');
      h4.className = 'zettels-summary-h2';
      var labelSpan = document.createElement('span');
      labelSpan.className = 'zettels-summary-h2-label';
      labelSpan.textContent = heading;
      h4.appendChild(labelSpan);
      h4.appendChild(buildChevronSpan());
      container.appendChild(h4);

      var panel = document.createElement('div');
      panel.className = 'zettels-summary-panel';
      appendSectionBody(panel, bullets, subs, hasSubs);
      container.appendChild(panel);

      attachToggle(h4, panel);
      // Default state: first section expanded, all others collapsed.
      // Apply collapse SYNCHRONOUSLY at render time — setting aria-expanded
      // and data-collapsed directly avoids the rAF race where the modal
      // opens with measurements still pending and sections appear expanded.
      if (firstSectionRendered) {
        h4.setAttribute('aria-expanded', 'false');
        panel.setAttribute('data-collapsed', 'true');
        panel.style.maxHeight = '0px';
      }
      firstSectionRendered = true;
    });
  }

  function appendSectionBody(parent, bullets, subs, hasSubs) {
    if (bullets && bullets.length) {
      var ul = document.createElement('ul');
      ul.className = 'zettels-summary-list';
      bullets.forEach(function (bullet) {
        var text = bullet == null ? '' : String(bullet).trim();
        if (!text) return;
        var li = document.createElement('li');
        li.className = 'zettels-summary-list-item';
        li.textContent = text;
        ul.appendChild(li);
      });
      if (ul.childNodes.length) parent.appendChild(ul);
    }
    if (hasSubs) {
      Object.keys(subs).forEach(function (subHeading) {
        var subBullets = subs[subHeading];
        if (!Array.isArray(subBullets) || !subBullets.length) return;
        var h5 = document.createElement('h5');
        h5.className = 'zettels-summary-h3';
        h5.textContent = String(subHeading || '').trim();
        parent.appendChild(h5);

        var subUl = document.createElement('ul');
        subUl.className = 'zettels-summary-list';
        subBullets.forEach(function (bullet) {
          var text = bullet == null ? '' : String(bullet).trim();
          if (!text) return;
          var li = document.createElement('li');
          li.className = 'zettels-summary-list-item';
          li.textContent = text;
          subUl.appendChild(li);
        });
        if (subUl.childNodes.length) parent.appendChild(subUl);
      });
    }
  }

  function renderMarkdownLite(container, markdown) {
    markdown = normalizeSummaryMarkdown(markdown);
    var lines = String(markdown || '').split(/\r?\n/);
    var paraBuf = [];
    var listStack = null;
    // Each ``## `` opens a collapsible section (same chevron/panel/toggle
    // contract as renderStructuredDetailed). Content after an h2 routes into
    // the open section's panel via currentTarget instead of the flat container.
    var currentTarget = container;
    var firstH2Seen = false;

    function flushPara() {
      if (!paraBuf.length) return;
      var joined = paraBuf.join(' ').trim();
      if (joined) {
        var p = document.createElement('p');
        p.className = 'zettels-summary-para';
        p.textContent = joined;
        currentTarget.appendChild(p);
      }
      paraBuf = [];
    }
    function closeList() { listStack = null; }

    for (var i = 0; i < lines.length; i++) {
      var trimmed = lines[i].replace(/\s+$/, '');
      if (!trimmed.trim()) { flushPara(); closeList(); continue; }
      var h3 = trimmed.match(/^###\s+(.*)$/);
      var h2 = trimmed.match(/^##\s+(.*)$/);
      var bullet = trimmed.match(/^\s*[-*]\s+(.*)$/);
      if (h2) {
        flushPara(); closeList();
        var h4 = document.createElement('h4');
        h4.className = 'zettels-summary-h2';
        var lbl = document.createElement('span');
        lbl.className = 'zettels-summary-h2-label';
        lbl.textContent = h2[1].trim();
        h4.appendChild(lbl);
        h4.appendChild(buildChevronSpan());
        container.appendChild(h4);
        var panel = document.createElement('div');
        panel.className = 'zettels-summary-panel';
        container.appendChild(panel);
        attachToggle(h4, panel);
        if (firstH2Seen) {
          h4.setAttribute('aria-expanded', 'false');
          panel.setAttribute('data-collapsed', 'true');
          panel.style.maxHeight = '0px';
        }
        firstH2Seen = true;
        currentTarget = panel;
        continue;
      }
      if (h3) {
        flushPara(); closeList();
        var h5 = document.createElement('h5');
        h5.className = 'zettels-summary-h3';
        h5.textContent = h3[1].trim();
        currentTarget.appendChild(h5);
        continue;
      }
      if (bullet) {
        flushPara();
        if (!listStack) {
          listStack = { el: document.createElement('ul') };
          listStack.el.className = 'zettels-summary-list';
          currentTarget.appendChild(listStack.el);
        }
        var li = document.createElement('li');
        li.className = 'zettels-summary-list-item';
        li.textContent = bullet[1].trim();
        listStack.el.appendChild(li);
        continue;
      }
      closeList();
      paraBuf.push(trimmed.trim());
    }
    flushPara();
    closeList();
  }

  function normalizeSummaryMarkdown(markdown) {
    // Defense-in-depth (server render is the source of truth): split an inline
    // ATX heading the model glued mid-line onto its own block, then drop any
    // trailing ``#`` it appended. Whitespace required on both sides of the
    // ``#`` run so C#, "#1" and backtick-adjacent `## x` are left alone.
    return String(markdown || '')
      .replace(/(\S)[ \t]+(#{2,6})[ \t]+(?=\S)/g, '$1\n\n$2 ')
      .replace(/^(#{2,6} .+?)[ \t]+#+[ \t]*$/gm, '$1');
  }

  function extractSummaryParts(rawSummary) {
    // Accept already-parsed objects in case the caller hands us the node
    // payload directly (defensive — today the API stringifies everything,
    // but this keeps the renderer correct if that ever changes).
    var isPlainObject = rawSummary && typeof rawSummary === 'object' && !Array.isArray(rawSummary);
    var rawInput = rawSummary == null ? '' : (typeof rawSummary === 'string' ? rawSummary : '');
    var rawText = normalizeSummaryText(rawInput);
    var parsed = isPlainObject ? rawSummary : tryParseSummaryObject(rawInput);

    if (parsed) {
      var rawDetailed = parsed.detailed_summary != null ? parsed.detailed_summary : parsed.detailedSummary;
      // coerceStructuredDetailed centralizes every recovery path: native array,
      // single dict (wrap → array), stringified JSON, Python repr (single→double
      // quote swap). Anything that can't be salvaged falls through as a flat
      // string for the markdown renderer — no bad data ever reaches the DOM.
      var structuredDetailed = coerceStructuredDetailed(rawDetailed);

      var briefFromParsed = normalizeSummaryText(
        parsed.brief_summary || parsed.briefSummary || parsed.one_line_summary || parsed.summary || ''
      );
      var detailedFromParsed = structuredDetailed
        ? ''
        : normalizeSummaryText(rawDetailed || parsed.summary || '');

      var resolvedBrief = briefFromParsed || detailedFromParsed;
      var resolvedDetailed = detailedFromParsed || briefFromParsed;
      if (resolvedBrief || resolvedDetailed || structuredDetailed) {
        return {
          brief: resolvedBrief || 'No summary available for this zettel.',
          detailed: resolvedDetailed || resolvedBrief || 'No summary available for this zettel.',
          detailedStructured: structuredDetailed
        };
      }
    }

    var fallback = rawText || 'No summary available for this zettel.';
    return { brief: fallback, detailed: fallback, detailedStructured: null };
  }

  function tryParseSummaryObject(rawText) {
    var cleaned = String(rawText || '')
      .replace(/\r\n/g, '\n')
      .trim();
    if (!cleaned) return null;

    cleaned = cleaned
      .replace(/^```(?:json)?/i, '')
      .replace(/```$/i, '')
      .replace(/^json\s*/i, '')
      .trim();

    var candidates = [cleaned];
    var start = cleaned.indexOf('{');
    var end = cleaned.lastIndexOf('}');
    if (start !== -1 && end > start) {
      candidates.push(cleaned.slice(start, end + 1));
    }

    for (var i = 0; i < candidates.length; i++) {
      var candidate = candidates[i].trim();
      if (!candidate) continue;
      try {
        var parsed = JSON.parse(candidate);
        if (parsed && typeof parsed === 'object') return parsed;
        if (typeof parsed === 'string') {
          var nested = JSON.parse(parsed);
          if (nested && typeof nested === 'object') return nested;
        }
      } catch (err) {
        void err;
      }
    }

    var regexBrief = extractSummaryFieldByRegex(cleaned, 'brief_summary');
    var regexDetailed = extractSummaryFieldByRegex(cleaned, 'detailed_summary');
    if (regexBrief || regexDetailed) {
      return {
        brief_summary: regexBrief,
        detailed_summary: regexDetailed
      };
    }

    return null;
  }

  function extractSummaryFieldByRegex(text, fieldName) {
    var pattern = new RegExp('"' + fieldName + '"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"', 'i');
    var match = text.match(pattern);
    if (!match || !match[1]) return '';
    return normalizeSummaryText(match[1]);
  }

  function normalizeSummaryText(value, options) {
    var opts = options || {};
    // Non-string inputs (array / plain object) must never fall through to
    // String(value) — that yields "[object Object],[object Object]" garbage
    // which renders as a literal paragraph. Coerce them to empty so the
    // caller's fallback chain (brief or placeholder) kicks in.
    if (value != null && typeof value === 'object') return '';
    var text = String(value || '')
      .replace(/\r\n/g, '\n')
      .replace(/\\n/g, '\n')
      .replace(/\\r/g, '\r')
      .replace(/\\t/g, '\t')
      .trim();
    if (!opts.preserveEscapedQuotes) {
      text = text.replace(/\\"/g, '"');
    }
    // Defensive: if anything upstream slipped past and produced an
    // "[object Object]" string (JS's default Array/Object toString), strip
    // it rather than render it as user-facing text.
    if (/^(\[object Object\](,\s*)?)+$/.test(text)) return '';
    return text;
  }

  function truncate(value, limit) {
    if (!value || value.length <= limit) return value;
    return value.slice(0, limit - 3).trim() + '...';
  }

  function formatDate(value) {
    var parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: 'short',
      day: '2-digit'
    }).format(parsed);
  }

  // ---- DOM references — lazy-resolved on first .open() call ----
  var summaryOverlay = null;
  var summaryBackdrop = null;
  var summaryClose = null;
  var summarySource = null;
  var summaryDate = null;
  var summaryTitle = null;
  var summaryText = null;
  var summaryTags = null;
  var _domResolved = false;

  function resolveDom() {
    if (_domResolved) return;
    summaryOverlay  = document.getElementById('summary-overlay');
    summaryBackdrop = document.getElementById('summary-backdrop');
    summaryClose    = document.getElementById('summary-close');
    summarySource   = document.getElementById('summary-source');
    summaryDate     = document.getElementById('summary-date');
    summaryTitle    = document.getElementById('summary-title');
    summaryText     = document.getElementById('summary-text');
    summaryTags     = document.getElementById('summary-tags');
    _domResolved = !!summaryOverlay;
  }

  function displayTitle(node) {
    // Prefer the user-visible title; fall back to the KG graph "name" field;
    // last resort, a generic label so the modal never renders blank.
    return (node && (node.title || node.name)) || 'Untitled';
  }

  function resolveSourceKey(node) {
    // user_zettels rows carry .source ('youtube'). KG nodes carry .group.
    // Default to 'web' so the source-badge always has a valid colour class.
    return String((node && (node.source || node.group)) || 'web').toLowerCase();
  }

  function resolveSourceLabel(node, fallbackKey) {
    return (node && (node.sourceLabel || node.group || node.source)) || fallbackKey;
  }

  function openSummary(node) {
    resolveDom();
    if (!summaryOverlay || !summarySource || !summaryDate ||
        !summaryTitle || !summaryText || !summaryTags) return;

    var sourceKey = resolveSourceKey(node);
    var sourceLabel = resolveSourceLabel(node, sourceKey);
    summarySource.className = 'home-card-source ' + sourceKey;
    summarySource.textContent = sourceLabel;
    summaryDate.className = 'home-card-date';
    if (node && node.date) {
      summaryDate.textContent = formatDate(node.date);
      summaryDate.style.display = '';
    } else {
      summaryDate.textContent = '';
      summaryDate.style.display = 'none';
    }
    summaryTitle.textContent = displayTitle(node);

    // Two render paths:
    //   (a) caller already extracted brief/detailed/structured (user_zettels)
    //   (b) raw envelope on node.summary / .description (user_home, KG)
    var brief = node && node.briefSummary;
    var detailed = node && node.detailedSummary;
    var structured = node && node.detailedStructured;
    if (!brief && !detailed && !structured) {
      var primary = (node && (node.summary || node.description)) || '';
      var parts = extractSummaryParts(primary);
      brief = parts.brief;
      detailed = parts.detailed;
      structured = parts.detailedStructured;
      if (!structured && node && node.description && node.description !== primary) {
        var alt = extractSummaryParts(node.description);
        if (alt && (alt.detailedStructured ||
            (alt.detailed && alt.detailed !== detailed))) {
          detailed = alt.detailed || detailed;
          structured = alt.detailedStructured || structured;
        }
      }
    }
    renderDualSummary(summaryText, {
      brief: brief || '',
      detailed: detailed || '',
      detailedStructured: structured || null
    });

    var mathSrc = sourceKey;
    _maskPriceDollars(summaryText);
    _mathRenderArxiv(summaryText, mathSrc);
    _unmaskPriceDollars(summaryText);

    summaryTags.innerHTML = '';
    var tags = (node && Array.isArray(node.tags)) ? node.tags : [];
    tags.forEach(function (tag) {
      var el = document.createElement('span');
      el.className = 'zettels-tag';
      el.textContent = '#' + tag;
      summaryTags.appendChild(el);
    });

    if (window.ZkRefreshButton &&
        typeof window.ZkRefreshButton.setCurrentNode === 'function') {
      window.ZkRefreshButton.setCurrentNode(node);
    }
    summaryOverlay.classList.remove('hidden');
    setBodyScrollLocked(true);
  }

  function closeSummary() {
    resolveDom();
    if (!summaryOverlay) return;
    summaryOverlay.classList.add('hidden');
    setBodyScrollLocked(false);
  }

  function setCurrentNode(node) {
    if (window.ZkRefreshButton &&
        typeof window.ZkRefreshButton.setCurrentNode === 'function') {
      window.ZkRefreshButton.setCurrentNode(node);
    }
  }

  // ---- backdrop + close-button + ESC wiring (idempotent — safe to re-bind) ----
  function bindCloseHandlers() {
    resolveDom();
    if (summaryBackdrop && !summaryBackdrop.dataset.zkSummaryBound) {
      summaryBackdrop.dataset.zkSummaryBound = '1';
      summaryBackdrop.addEventListener('click', closeSummary);
    }
    if (summaryClose && !summaryClose.dataset.zkSummaryBound) {
      summaryClose.dataset.zkSummaryBound = '1';
      summaryClose.addEventListener('click', closeSummary);
    }
    if (!document.body.dataset.zkSummaryEscBound) {
      document.body.dataset.zkSummaryEscBound = '1';
      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        if (summaryOverlay && !summaryOverlay.classList.contains('hidden')) {
          closeSummary();
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindCloseHandlers);
  } else {
    bindCloseHandlers();
  }

  window.ZKSummary = {
    open: openSummary,
    close: closeSummary,
    setCurrentNode: setCurrentNode
  };
})();
