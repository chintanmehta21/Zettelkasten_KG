# Summarization Engine Plan 15 — UI Integration for Per-Source Summary Structure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing website surfaces render the new rich per-source structured summary fields (speakers, chapters, architecture_overview, reply_clusters, conclusions, stance, ...) that Plans 1-9 produce. Right now the UI treats every summary as generic `{mini_title, brief_summary, tags, detailed_summary[]}` — losing all source-specific signal that the LLM now emits.

**Architecture:** Per-surface display contract (what shows where) + per-source renderer component that branches on `metadata.source_type`. Desktop pages under `website/features/` get JavaScript renderers in `website/static/js/`; mobile pages under `website/mobile/` get condensed variants.

**Reference spec:** `docs/superpowers/specs/2026-04-21-summarization-engine-scoring-optimization-design.md` §6.1 (per-source payload schemas).

**Display contract (user-directed):**

| Surface | What shows |
|---|---|
| **Home page** (`website/static/index.html`) | Input → click "Summarize" → see **BRIEF summary + tags + mini_title** inline. Click "Show detailed" button → expand to show **per-source detailed structure** (YouTube chapters, Reddit clusters, GitHub architecture + interfaces, Newsletter sections + stance + CTA). |
| **Zettels page** (`website/features/user_zettels/index.html`) | List of user's zettels as cards. Each card shows **mini_title + brief_summary (truncated to 2 lines) + top 3 tags + source_type badge**. Click card → modal with FULL detailed per-source structure. |
| **Knowledge graph** (`website/features/knowledge_graph/index.html`) | Click a node → hover popover shows **mini_title + brief_summary (first sentence only)**. Click "Open" → routes to Zettels-page modal. |
| **RAG chat** (`website/features/user_rag/index.html`) | When a citation badge is hovered, tooltip shows **mini_title + 1-sentence brief**. Click citation → opens Zettels-page modal. |
| **Mobile home** (`website/mobile/index.html`) | Same as desktop home but single-column; "Show detailed" is a bottom-sheet rather than inline expansion. |
| **Mobile knowledge graph** (`website/mobile/knowledge-graph.html`) | Node-tap → bottom-sheet with brief + link to Zettels. |

**Branch:** `feat/ui-per-source-renderers`, off `master` AFTER Plan 14's PR merges.

**Precondition:** Plans 1-14 merged. All 4 major-source per-source schemas in prod per Plan 1. `/api/v2/summarize` returns the new structured fields. UI colour rules per CLAUDE.md: **never purple/violet/lavender** — KG accent is amber/gold (`#D4A024`), main site accent is teal.

**Deploy discipline:** Pure frontend + API response-shape additions (no schema changes). Mergeable with low risk — fallback renderer shows legacy display for any payload missing new fields. Still: draft PR + human approval before merge.

---

## Critical safety constraints

### 1. Backward compat for legacy zettels
Pre-Plan-1 nodes in `kg_nodes` do NOT have the new fields (`speakers`, `architecture_overview`, `conclusions_or_recommendations`, etc.). Renderer MUST handle missing fields gracefully — fall back to legacy `detailed_summary[]` generic rendering. Zero broken cards on production data.

### 2. Accent colour discipline
Per CLAUDE.md "UI Design" section: **never purple/violet/lavender** (`hsl(250-290)`, `#A78BFA`, etc.). KG pages use amber/gold `#D4A024`; everywhere else uses teal. Any CSS added or modified in this plan MUST be grepped for these forbidden colours before commit.

### 3. No blocking Gemini calls on page load
All summary-rendering is client-side against the existing summary payload already returned by the API. Do NOT introduce new API calls during render.

### 4. Mobile parity
Every desktop renderer has a mobile variant under `website/mobile/`. Feature parity on content, different layout (single-column, bottom-sheet expansions).

### 5. Accessibility
- Tags, badges, and structural sections have `aria-label`s.
- Expand buttons include `aria-expanded` + `aria-controls`.
- Chapter timestamps in YouTube renderer linkable (open the video at that timestamp).
- Keyboard navigation: `Tab` through cards, `Enter` opens modal, `Esc` closes.

### 6. Don't break existing behaviour
Existing home-page summarize flow must continue to work exactly as before for an anonymous user summarizing a single URL. The new rendering is additive.

---

## File structure summary

### Files to CREATE
- `website/static/js/summary_renderer.js` — main entry point; branches on `source_type`
- `website/static/js/renderers/youtube.js`
- `website/static/js/renderers/reddit.js`
- `website/static/js/renderers/github.js`
- `website/static/js/renderers/newsletter.js`
- `website/static/js/renderers/generic.js` — fallback for polish sources + legacy nodes
- `website/static/js/renderers/_shared.js` — shared helpers (tag chips, source badge, truncate)
- `website/static/css/summary.css`
- `website/mobile/js/summary_renderer_mobile.js`
- `website/mobile/css/summary_mobile.css`
- `tests/unit/website_ui/test_renderer_contract.py` — headless-browser contract tests (see Task 9)

### Files to MODIFY
- `website/static/index.html` — wire `summary_renderer.js` in; replace inline summary-display div with `<div id="summary-root">`
- `website/static/js/app.js` — call `renderSummary(response)` after successful `/api/v2/summarize`
- `website/features/user_zettels/index.html` — add card list markup + modal
- `website/features/user_zettels/zettels.js` (if exists; else add) — fetch + render zettel list via the same renderer
- `website/features/knowledge_graph/index.html` — add popover hook
- `website/features/user_rag/index.html` — citation tooltip hook
- `website/mobile/index.html` — mobile renderer wire-in
- `website/mobile/knowledge-graph.html` — mobile popover

---

## Critical edge cases Codex MUST handle

### 1. Missing fields on legacy nodes
Every accessor uses optional chaining + fallbacks:
```js
const speakers = summary?.speakers ?? [];
const chapters = summary?.detailed_summary?.chapters_or_segments ?? [];
```
If a field is missing, the renderer omits that section rather than showing `undefined` or an empty placeholder.

### 2. Ultra-long content
`brief_summary` is ≤ 400 chars per spec §6.2. Zettels-page card truncates to 2 lines via CSS `-webkit-line-clamp: 2`. Detailed chapters can be very long; modal has max-height + internal scroll.

### 3. No-tag case (defensive)
If `tags.length === 0` (shouldn't happen post-Plan-1 but possible on legacy), render nothing instead of an empty chip row.

### 4. Click-through from modal
Every modal has a visible URL at top-right as a back-link to the original source. Opens in new tab (`target="_blank" rel="noopener"`).

### 5. Keyboard + screen-reader nav
Modal traps focus when open, releases on close. `Esc` closes. Card list has `role="list"` + `aria-label="Your zettels"`.

### 6. Stance rendering (newsletter) must not editorialize
The `stance` field is one of `optimistic|skeptical|cautionary|neutral|mixed`. Render as a neutral badge with the literal word — not a colour-coded sentiment bar that implies positive/negative.

### 7. YouTube chapter timestamp links
`ChapterBullet.timestamp` (e.g., `"3:45"` or `"0:00:42"`) links to `https://www.youtube.com/watch?v=<id>&t=<seconds>`. Safely convert timestamps to seconds; if invalid, omit the link.

### 8. Anti-pattern flags from eval (future-proofing)
If a summary has `metadata.evaluator_flagged_anti_patterns` populated (from Plan 12's `/api/v2/eval` backfill), render a small warning icon on the card — don't surface the details inline (too noisy for end users). Click warning → modal shows which anti-patterns.

### 9. Colour audit before commit
Before every commit in this plan, grep the changed files for purple-family colours:
```bash
git diff --name-only HEAD~1 HEAD | xargs grep -E -i 'purple|violet|lavender|#[Aa]78[Bb][Ff][A-F0-9]|hsl\(2[5-9][0-9]|rgb\((1[2-9][0-9]|2[0-5][0-9]),\s*(0|[0-9]{1,2}),' 2>&1
```
If any hit, revert the colour.

---

## Task 0: Branch + UI baseline snapshot

- [ ] **Step 1: Branch**

```bash
cd /c/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault
git checkout master && git pull
git checkout -b feat/ui-per-source-renderers
git push -u origin feat/ui-per-source-renderers
```

- [ ] **Step 2: Take screenshots of current UI for regression comparison (manual)**

Start the server, visit each page, save screenshots to `docs/summary_eval/_ui_integration/baseline/`:
- `home.png` (before)
- `zettels.png` (before)
- `knowledge_graph.png` (before)
- `rag.png` (before)
- `mobile_home.png` (before)

```bash
mkdir -p docs/summary_eval/_ui_integration/baseline
python run.py &
# Take screenshots of http://127.0.0.1:10000/ , /zettels , /knowledge-graph , /chat , /m/
# (manual step; record filenames + commit them at end of Task 8)
kill %1
```

---

## Task 1: Shared renderer helpers + CSS scaffold

**Files:**
- Create: `website/static/js/renderers/_shared.js`
- Create: `website/static/css/summary.css`

- [ ] **Step 1: Create `_shared.js`**

```javascript
// website/static/js/renderers/_shared.js
// Shared helpers for per-source summary renderers.

export function sourceBadge(sourceType) {
  const labels = {
    youtube: 'YouTube', reddit: 'Reddit', github: 'GitHub', newsletter: 'Newsletter',
    hackernews: 'Hacker News', linkedin: 'LinkedIn', arxiv: 'arXiv',
    podcast: 'Podcast', twitter: 'X (Twitter)', web: 'Web',
  };
  const label = labels[sourceType] || 'Web';
  const el = document.createElement('span');
  el.className = `source-badge source-badge--${sourceType}`;
  el.textContent = label;
  el.setAttribute('aria-label', `Source: ${label}`);
  return el;
}

export function tagChips(tags, max = Infinity) {
  const container = document.createElement('div');
  container.className = 'tag-chips';
  container.setAttribute('role', 'list');
  container.setAttribute('aria-label', 'Tags');
  (tags || []).slice(0, max).forEach(t => {
    const chip = document.createElement('span');
    chip.className = 'tag-chip';
    chip.setAttribute('role', 'listitem');
    chip.textContent = t;
    container.appendChild(chip);
  });
  if ((tags || []).length > max) {
    const more = document.createElement('span');
    more.className = 'tag-chip tag-chip--more';
    more.textContent = `+${tags.length - max}`;
    container.appendChild(more);
  }
  return container;
}

export function safeText(s, fallback = '') {
  return typeof s === 'string' && s.trim() ? s : fallback;
}

export function openLink(url) {
  if (!url) return null;
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener';
  a.className = 'source-link';
  a.textContent = 'Open source ↗';
  return a;
}

export function parseTimestampToSeconds(ts) {
  // "3:45" -> 225 ; "1:02:30" -> 3750
  if (!ts || typeof ts !== 'string') return null;
  const parts = ts.split(':').map(Number);
  if (parts.some(isNaN)) return null;
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return null;
}

export function briefSummaryTruncated(text, lines = 2) {
  const el = document.createElement('p');
  el.className = `brief-summary brief-summary--clamp-${lines}`;
  el.textContent = text || '';
  return el;
}
```

- [ ] **Step 2: Create `summary.css`**

```css
/* website/static/css/summary.css — per-source summary rendering. Teal accent, no purple. */

/* ---------- Variables ---------- */
:root {
  --zk-accent: #0D9488;             /* teal-600 */
  --zk-accent-hover: #0F766E;       /* teal-700 */
  --zk-accent-muted: #CCFBF1;       /* teal-100 */
  --zk-fg: #0F172A;                 /* slate-900 */
  --zk-fg-muted: #475569;           /* slate-600 */
  --zk-border: #E2E8F0;             /* slate-200 */
  --zk-bg-card: #FFFFFF;
  --zk-bg-modal: #FFFFFF;
  --zk-warning: #D97706;            /* amber-600 — anti-pattern flag */
}

/* ---------- Source badges ---------- */
.source-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  background: var(--zk-accent-muted);
  color: var(--zk-accent-hover);
  letter-spacing: 0.02em;
}
.source-badge--youtube  { background: #FEE2E2; color: #991B1B; }
.source-badge--reddit   { background: #FFEDD5; color: #9A3412; }
.source-badge--github   { background: #F1F5F9; color: #0F172A; }
.source-badge--newsletter { background: #DBEAFE; color: #1E40AF; }
.source-badge--hackernews { background: #FFEDD5; color: #C2410C; }

/* ---------- Tag chips ---------- */
.tag-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.tag-chip {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  background: #F1F5F9;
  color: var(--zk-fg-muted);
  font-weight: 500;
}
.tag-chip--more { background: transparent; color: var(--zk-fg-muted); font-style: italic; }

/* ---------- Brief summary clamp ---------- */
.brief-summary {
  font-size: 14px;
  color: var(--zk-fg);
  line-height: 1.5;
  margin: 8px 0;
}
.brief-summary--clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.brief-summary--clamp-1 {
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---------- Detailed sections (per-source common layout) ---------- */
.detailed-section { margin-top: 16px; }
.detailed-section h3 {
  font-size: 13px;
  font-weight: 700;
  color: var(--zk-fg);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0 0 6px 0;
}
.detailed-section ul { margin: 0; padding-left: 20px; }
.detailed-section li { font-size: 14px; color: var(--zk-fg); line-height: 1.5; margin-bottom: 4px; }

/* ---------- YouTube chapter list ---------- */
.yt-chapter { display: flex; gap: 10px; margin-bottom: 8px; }
.yt-chapter__timestamp {
  flex: 0 0 64px;
  font-variant-numeric: tabular-nums;
  color: var(--zk-accent);
  text-decoration: none;
  font-weight: 600;
}
.yt-chapter__timestamp:hover { text-decoration: underline; color: var(--zk-accent-hover); }
.yt-chapter__body { flex: 1 1 auto; }
.yt-chapter__title { font-weight: 600; font-size: 14px; }

/* ---------- GitHub interfaces list ---------- */
.gh-interface-grid { display: grid; grid-template-columns: 120px 1fr; gap: 4px 12px; font-size: 13px; }
.gh-interface-label { color: var(--zk-fg-muted); font-weight: 600; }

/* ---------- Reddit cluster ---------- */
.reddit-cluster {
  border-left: 3px solid var(--zk-accent);
  padding: 6px 0 6px 12px;
  margin-bottom: 10px;
}
.reddit-cluster__theme { font-weight: 700; font-size: 13px; }
.reddit-cluster__reasoning { font-size: 13px; color: var(--zk-fg); margin-top: 2px; }

/* ---------- Newsletter stance ---------- */
.newsletter-stance {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  background: #F1F5F9;
  color: var(--zk-fg);
}

/* ---------- Anti-pattern warning icon ---------- */
.anti-pattern-flag {
  display: inline-flex;
  align-items: center;
  color: var(--zk-warning);
  font-size: 12px;
  margin-left: 4px;
  cursor: help;
}

/* ---------- Source link ---------- */
.source-link {
  display: inline-block;
  font-size: 12px;
  color: var(--zk-accent);
  text-decoration: none;
  margin-top: 8px;
}
.source-link:hover { text-decoration: underline; color: var(--zk-accent-hover); }
```

- [ ] **Step 3: Commit**

```bash
git add website/static/js/renderers/_shared.js website/static/css/summary.css
git commit -m "feat: ui shared renderer helpers and css"
```

---

## Task 2: YouTube renderer

**Files:**
- Create: `website/static/js/renderers/youtube.js`

- [ ] **Step 1: Create file**

```javascript
// website/static/js/renderers/youtube.js
import { openLink, parseTimestampToSeconds, safeText } from './_shared.js';


export function renderYouTubeDetailed(summary, sourceUrl) {
  const root = document.createElement('div');
  root.className = 'detailed-body detailed-body--youtube';

  const detailed = summary?.detailed_summary || {};
  const videoId = extractVideoId(sourceUrl);

  // Thesis + format
  const thesisEl = document.createElement('section');
  thesisEl.className = 'detailed-section';
  thesisEl.innerHTML = `<h3>Thesis</h3><p>${escape(safeText(detailed.thesis))}</p>`;
  if (detailed.format) {
    const fmt = document.createElement('p');
    fmt.className = 'subtle';
    fmt.textContent = `Format: ${detailed.format}`;
    thesisEl.appendChild(fmt);
  }
  root.appendChild(thesisEl);

  // Speakers + guests + entities
  if ((summary.speakers || []).length || (summary.guests || []).length || (summary.entities_discussed || []).length) {
    const who = document.createElement('section');
    who.className = 'detailed-section';
    who.innerHTML = '<h3>People + references</h3>';
    const ul = document.createElement('ul');
    if (summary.speakers?.length) {
      const li = document.createElement('li');
      li.innerHTML = `<strong>Speakers:</strong> ${summary.speakers.map(escape).join(', ')}`;
      ul.appendChild(li);
    }
    if (summary.guests?.length) {
      const li = document.createElement('li');
      li.innerHTML = `<strong>Guests:</strong> ${summary.guests.map(escape).join(', ')}`;
      ul.appendChild(li);
    }
    if (summary.entities_discussed?.length) {
      const li = document.createElement('li');
      li.innerHTML = `<strong>Referenced:</strong> ${summary.entities_discussed.map(escape).join(', ')}`;
      ul.appendChild(li);
    }
    who.appendChild(ul);
    root.appendChild(who);
  }

  // Chapters / segments with timestamp links
  const chapters = detailed.chapters_or_segments || [];
  if (chapters.length) {
    const chSection = document.createElement('section');
    chSection.className = 'detailed-section';
    chSection.innerHTML = '<h3>Chapters</h3>';
    chapters.forEach(c => {
      const row = document.createElement('div');
      row.className = 'yt-chapter';

      const tsLink = document.createElement('a');
      const seconds = parseTimestampToSeconds(c.timestamp);
      tsLink.className = 'yt-chapter__timestamp';
      tsLink.textContent = c.timestamp || '';
      if (videoId && seconds !== null) {
        tsLink.href = `https://www.youtube.com/watch?v=${videoId}&t=${seconds}s`;
        tsLink.target = '_blank';
        tsLink.rel = 'noopener';
      }

      const body = document.createElement('div');
      body.className = 'yt-chapter__body';
      body.innerHTML = `<div class="yt-chapter__title">${escape(c.title || '')}</div>`;
      if (c.bullets?.length) {
        const ul = document.createElement('ul');
        c.bullets.forEach(b => {
          const li = document.createElement('li');
          li.textContent = b;
          ul.appendChild(li);
        });
        body.appendChild(ul);
      }
      row.appendChild(tsLink);
      row.appendChild(body);
      chSection.appendChild(row);
    });
    root.appendChild(chSection);
  }

  // Demonstrations
  if (detailed.demonstrations?.length) {
    const demos = document.createElement('section');
    demos.className = 'detailed-section';
    demos.innerHTML = '<h3>Demonstrations</h3>';
    const ul = document.createElement('ul');
    detailed.demonstrations.forEach(d => { const li = document.createElement('li'); li.textContent = d; ul.appendChild(li); });
    demos.appendChild(ul);
    root.appendChild(demos);
  }

  // Closing takeaway
  if (detailed.closing_takeaway) {
    const tk = document.createElement('section');
    tk.className = 'detailed-section';
    tk.innerHTML = `<h3>Closing takeaway</h3><p>${escape(detailed.closing_takeaway)}</p>`;
    root.appendChild(tk);
  }

  // Source link
  const link = openLink(sourceUrl);
  if (link) root.appendChild(link);

  return root;
}


function extractVideoId(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    if (u.hostname.includes('youtu.be')) return u.pathname.slice(1);
    return u.searchParams.get('v');
  } catch {
    return null;
  }
}

function escape(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
```

- [ ] **Step 2: Commit**

```bash
git add website/static/js/renderers/youtube.js
git commit -m "feat: youtube summary renderer"
```

---

## Task 3: Reddit renderer

**Files:**
- Create: `website/static/js/renderers/reddit.js`

- [ ] **Step 1: Create**

```javascript
// website/static/js/renderers/reddit.js
import { openLink, safeText } from './_shared.js';


export function renderRedditDetailed(summary, sourceUrl) {
  const root = document.createElement('div');
  root.className = 'detailed-body detailed-body--reddit';

  const d = summary?.detailed_summary || {};

  if (d.op_intent) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = `<h3>Original post</h3><p>${escape(safeText(d.op_intent))}</p>`;
    root.appendChild(s);
  }

  if ((d.reply_clusters || []).length) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = '<h3>Response clusters</h3>';
    d.reply_clusters.forEach(c => {
      const cluster = document.createElement('div');
      cluster.className = 'reddit-cluster';
      cluster.innerHTML = `
        <div class="reddit-cluster__theme">${escape(c.theme || '')}</div>
        <div class="reddit-cluster__reasoning">${escape(c.reasoning || '')}</div>
      `;
      if ((c.examples || []).length) {
        const ul = document.createElement('ul');
        c.examples.forEach(ex => { const li = document.createElement('li'); li.textContent = ex; ul.appendChild(li); });
        cluster.appendChild(ul);
      }
      s.appendChild(cluster);
    });
    root.appendChild(s);
  }

  if ((d.counterarguments || []).length) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = '<h3>Counterarguments</h3>';
    const ul = document.createElement('ul');
    d.counterarguments.forEach(c => { const li = document.createElement('li'); li.textContent = c; ul.appendChild(li); });
    s.appendChild(ul);
    root.appendChild(s);
  }

  if ((d.unresolved_questions || []).length) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = '<h3>Open questions</h3>';
    const ul = document.createElement('ul');
    d.unresolved_questions.forEach(q => { const li = document.createElement('li'); li.textContent = q; ul.appendChild(li); });
    s.appendChild(ul);
    root.appendChild(s);
  }

  if (d.moderation_context) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = `<h3>Moderation note</h3><p>${escape(d.moderation_context)}</p>`;
    root.appendChild(s);
  }

  const link = openLink(sourceUrl);
  if (link) root.appendChild(link);
  return root;
}


function escape(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
```

- [ ] **Step 2: Commit**

```bash
git add website/static/js/renderers/reddit.js
git commit -m "feat: reddit summary renderer"
```

---

## Task 4: GitHub renderer

**Files:**
- Create: `website/static/js/renderers/github.js`

- [ ] **Step 1: Create**

```javascript
// website/static/js/renderers/github.js
import { openLink, safeText } from './_shared.js';


export function renderGithubDetailed(summary, sourceUrl) {
  const root = document.createElement('div');
  root.className = 'detailed-body detailed-body--github';

  if (summary.architecture_overview) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = `<h3>Architecture</h3><p>${escape(summary.architecture_overview)}</p>`;
    root.appendChild(s);
  }

  (summary.detailed_summary || []).forEach(section => {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    const title = section.heading || section.module_or_feature || 'Section';
    s.innerHTML = `<h3>${escape(title)}</h3>`;

    if ((section.bullets || []).length) {
      const ul = document.createElement('ul');
      section.bullets.forEach(b => { const li = document.createElement('li'); li.textContent = b; ul.appendChild(li); });
      s.appendChild(ul);
    }

    // Structured grid: main_stack / public_interfaces / usability_signals
    const grid = document.createElement('div');
    grid.className = 'gh-interface-grid';
    if ((section.main_stack || []).length) {
      grid.innerHTML += `<div class="gh-interface-label">Stack</div><div>${section.main_stack.map(escape).join(', ')}</div>`;
    }
    if ((section.public_interfaces || []).length) {
      grid.innerHTML += `<div class="gh-interface-label">Interfaces</div><div>${section.public_interfaces.map(escape).join(', ')}</div>`;
    }
    if ((section.usability_signals || []).length) {
      grid.innerHTML += `<div class="gh-interface-label">Usability</div><div>${section.usability_signals.map(escape).join(', ')}</div>`;
    }
    if (grid.innerHTML) s.appendChild(grid);

    root.appendChild(s);
  });

  if ((summary.benchmarks_tests_examples || []).length) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = '<h3>Benchmarks / tests / examples</h3>';
    const ul = document.createElement('ul');
    summary.benchmarks_tests_examples.forEach(b => { const li = document.createElement('li'); li.textContent = b; ul.appendChild(li); });
    s.appendChild(ul);
    root.appendChild(s);
  }

  const link = openLink(sourceUrl);
  if (link) root.appendChild(link);
  return root;
}


function escape(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
```

- [ ] **Step 2: Commit**

```bash
git add website/static/js/renderers/github.js
git commit -m "feat: github summary renderer"
```

---

## Task 5: Newsletter + Generic renderers

**Files:**
- Create: `website/static/js/renderers/newsletter.js`
- Create: `website/static/js/renderers/generic.js`

- [ ] **Step 1: Newsletter**

```javascript
// website/static/js/renderers/newsletter.js
import { openLink, safeText } from './_shared.js';


export function renderNewsletterDetailed(summary, sourceUrl) {
  const root = document.createElement('div');
  root.className = 'detailed-body detailed-body--newsletter';

  const d = summary?.detailed_summary || {};

  if (d.publication_identity || d.issue_thesis) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = '<h3>Issue</h3>';
    const p = document.createElement('p');
    p.innerHTML = `<strong>${escape(d.publication_identity || '')}</strong>${d.publication_identity && d.issue_thesis ? ' — ' : ''}${escape(d.issue_thesis || '')}`;
    s.appendChild(p);

    if (d.stance) {
      const stance = document.createElement('span');
      stance.className = 'newsletter-stance';
      stance.textContent = d.stance;
      stance.setAttribute('aria-label', `Stance: ${d.stance}`);
      s.appendChild(stance);
    }
    root.appendChild(s);
  }

  (d.sections || []).forEach(section => {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = `<h3>${escape(section.heading || '')}</h3>`;
    if ((section.bullets || []).length) {
      const ul = document.createElement('ul');
      section.bullets.forEach(b => { const li = document.createElement('li'); li.textContent = b; ul.appendChild(li); });
      s.appendChild(ul);
    }
    root.appendChild(s);
  });

  if ((d.conclusions_or_recommendations || []).length) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = '<h3>Conclusions / recommendations</h3>';
    const ul = document.createElement('ul');
    d.conclusions_or_recommendations.forEach(c => { const li = document.createElement('li'); li.textContent = c; ul.appendChild(li); });
    s.appendChild(ul);
    root.appendChild(s);
  }

  if (d.cta) {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = `<h3>Call to action</h3><p>${escape(d.cta)}</p>`;
    root.appendChild(s);
  }

  const link = openLink(sourceUrl);
  if (link) root.appendChild(link);
  return root;
}


function escape(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
```

- [ ] **Step 2: Generic (fallback for polish sources + legacy nodes)**

```javascript
// website/static/js/renderers/generic.js
import { openLink } from './_shared.js';


export function renderGenericDetailed(summary, sourceUrl) {
  const root = document.createElement('div');
  root.className = 'detailed-body detailed-body--generic';
  const ds = summary?.detailed_summary || [];
  const sections = Array.isArray(ds) ? ds : (ds.sections || []);
  sections.forEach(section => {
    const s = document.createElement('section');
    s.className = 'detailed-section';
    s.innerHTML = `<h3>${escape(section.heading || 'Section')}</h3>`;
    if ((section.bullets || []).length) {
      const ul = document.createElement('ul');
      section.bullets.forEach(b => { const li = document.createElement('li'); li.textContent = b; ul.appendChild(li); });
      s.appendChild(ul);
    }
    root.appendChild(s);
  });
  const link = openLink(sourceUrl);
  if (link) root.appendChild(link);
  return root;
}


function escape(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
```

- [ ] **Step 3: Commit**

```bash
git add website/static/js/renderers/newsletter.js website/static/js/renderers/generic.js
git commit -m "feat: newsletter and generic summary renderers"
```

---

## Task 6: Main `summary_renderer.js` entry + dispatcher

**Files:**
- Create: `website/static/js/summary_renderer.js`

- [ ] **Step 1: Create**

```javascript
// website/static/js/summary_renderer.js
// Main entry. Dispatches on summary.metadata.source_type.

import { sourceBadge, tagChips, briefSummaryTruncated, openLink } from './renderers/_shared.js';
import { renderYouTubeDetailed } from './renderers/youtube.js';
import { renderRedditDetailed } from './renderers/reddit.js';
import { renderGithubDetailed } from './renderers/github.js';
import { renderNewsletterDetailed } from './renderers/newsletter.js';
import { renderGenericDetailed } from './renderers/generic.js';


export function renderSummary(apiResponse, rootEl, mode = 'full') {
  /*
   * apiResponse: full JSON from POST /api/v2/summarize (shape: {summary: {...}, writers: [...]})
   * rootEl: DOM element to append into. Cleared first.
   * mode: 'card' | 'full' | 'brief-only'
   */
  rootEl.innerHTML = '';
  const summary = apiResponse?.summary || apiResponse;  // accept raw summary too
  if (!summary) {
    rootEl.appendChild(errorBanner('No summary available'));
    return;
  }

  const sourceType = summary?.metadata?.source_type || 'web';
  const sourceUrl = summary?.metadata?.url || '';

  // Title row
  const titleRow = document.createElement('div');
  titleRow.className = 'summary-title-row';
  titleRow.innerHTML = `<h2 class="summary-title">${escape(summary.mini_title || 'Untitled')}</h2>`;
  titleRow.appendChild(sourceBadge(sourceType));
  rootEl.appendChild(titleRow);

  // Brief summary
  if (mode === 'card') {
    rootEl.appendChild(briefSummaryTruncated(summary.brief_summary, 2));
    rootEl.appendChild(tagChips(summary.tags, 3));
    return;
  }
  if (mode === 'brief-only') {
    rootEl.appendChild(briefSummaryTruncated(summary.brief_summary, 1));
    return;
  }

  // Full mode
  const brief = document.createElement('p');
  brief.className = 'brief-summary';
  brief.textContent = summary.brief_summary || '';
  rootEl.appendChild(brief);

  rootEl.appendChild(tagChips(summary.tags));

  // Detailed expand button
  const expandBtn = document.createElement('button');
  expandBtn.className = 'expand-btn';
  expandBtn.setAttribute('aria-expanded', 'false');
  expandBtn.setAttribute('aria-controls', 'summary-detailed');
  expandBtn.textContent = 'Show detailed summary';
  rootEl.appendChild(expandBtn);

  const detailed = document.createElement('div');
  detailed.id = 'summary-detailed';
  detailed.className = 'summary-detailed';
  detailed.hidden = true;
  rootEl.appendChild(detailed);

  expandBtn.addEventListener('click', () => {
    const willOpen = detailed.hidden;
    detailed.hidden = !willOpen;
    expandBtn.setAttribute('aria-expanded', String(willOpen));
    expandBtn.textContent = willOpen ? 'Hide detailed summary' : 'Show detailed summary';
    if (willOpen && !detailed.dataset.rendered) {
      detailed.appendChild(dispatchDetailed(summary, sourceType, sourceUrl));
      detailed.dataset.rendered = 'yes';
    }
  });
}


function dispatchDetailed(summary, sourceType, sourceUrl) {
  switch (sourceType) {
    case 'youtube':    return renderYouTubeDetailed(summary, sourceUrl);
    case 'reddit':     return renderRedditDetailed(summary, sourceUrl);
    case 'github':     return renderGithubDetailed(summary, sourceUrl);
    case 'newsletter': return renderNewsletterDetailed(summary, sourceUrl);
    default:           return renderGenericDetailed(summary, sourceUrl);
  }
}


function errorBanner(msg) {
  const el = document.createElement('div');
  el.className = 'error-banner';
  el.textContent = msg;
  return el;
}


function escape(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}


// Expose globally for non-module callers
if (typeof window !== 'undefined') {
  window.ZkSummary = { render: renderSummary };
}
```

- [ ] **Step 2: Commit**

```bash
git add website/static/js/summary_renderer.js
git commit -m "feat: summary renderer entry with dispatcher"
```

---

## Task 7: Wire into Home + Zettels + KG + RAG pages

**Files:**
- Modify: `website/static/index.html`
- Modify: `website/static/js/app.js`
- Modify: `website/features/user_zettels/index.html`
- Modify: `website/features/knowledge_graph/index.html`
- Modify: `website/features/user_rag/index.html`

- [ ] **Step 1: Home page**

In `website/static/index.html`, add after the existing `<head>`:

```html
<link rel="stylesheet" href="/static/css/summary.css">
<script type="module" src="/static/js/summary_renderer.js"></script>
```

Replace the existing inline summary-display div (locate the element id where summaries currently render) with:

```html
<div id="summary-root" class="summary-root"></div>
```

In `website/static/js/app.js`, find the `fetch('/api/v2/summarize', ...)` call. After successful response:

```javascript
import { renderSummary } from '/static/js/summary_renderer.js';

// In the .then() callback:
const response = await fetch('/api/v2/summarize', { ... });
const data = await response.json();
const root = document.getElementById('summary-root');
renderSummary(data, root, 'full');
```

(If `app.js` doesn't use modules, use the global `window.ZkSummary.render(data, root, 'full')` path.)

- [ ] **Step 2: Zettels page — card list + modal**

In `website/features/user_zettels/index.html`, add the module import in `<head>`, and change the zettel-list rendering to iterate over the user's nodes:

```html
<link rel="stylesheet" href="/static/css/summary.css">
<script type="module">
  import { renderSummary } from '/static/js/summary_renderer.js';
  window.ZkSummary = { render: renderSummary };
</script>
```

Card markup pattern per zettel:

```html
<article class="zettel-card" data-node-id="{{ node_id }}">
  <div class="card-header">
    <span class="source-badge source-badge--{{ source_type }}">{{ source_type_label }}</span>
  </div>
  <div class="zettel-card-summary" data-summary='{{ summary_json_escaped }}'></div>
  <button class="open-zettel-btn" data-node-id="{{ node_id }}">Open</button>
</article>
```

Client-side, for each card:

```javascript
document.querySelectorAll('.zettel-card-summary').forEach(el => {
  const summary = JSON.parse(el.dataset.summary);
  window.ZkSummary.render({ summary }, el, 'card');  // card mode → title + brief (2-line clamp) + top 3 tags
});

document.querySelectorAll('.open-zettel-btn').forEach(btn => {
  btn.addEventListener('click', async (e) => {
    const nodeId = btn.dataset.nodeId;
    const resp = await fetch(`/api/v2/node/${nodeId}`);  // endpoint exists or add per Task 8
    const data = await resp.json();
    openModal(data);
  });
});

function openModal(data) {
  const modal = document.getElementById('zettel-modal');
  const body = modal.querySelector('.modal-body');
  window.ZkSummary.render(data, body, 'full');
  modal.showModal();  // <dialog> element
  modal.addEventListener('keydown', (e) => { if (e.key === 'Escape') modal.close(); }, { once: true });
}
```

Add `<dialog id="zettel-modal">` with `<div class="modal-body">` near the end of index.html.

- [ ] **Step 3: KG popover**

In `website/features/knowledge_graph/index.html`, on node-click (existing 3D graph handler), change the popover content to use brief-only mode:

```javascript
graph.on('nodeClick', async (node) => {
  const resp = await fetch(`/api/v2/node/${node.id}`);
  const data = await resp.json();
  const popoverBody = document.getElementById('kg-popover-body');
  window.ZkSummary.render(data, popoverBody, 'brief-only');
  document.getElementById('kg-popover').style.display = 'block';
});
```

KG page keeps the existing amber/gold accent per CLAUDE.md; `summary.css` uses teal but each page can override via `body.kg-page .source-badge { ... }` if needed.

- [ ] **Step 4: RAG chat citations**

In `website/features/user_rag/index.html`, citation badges already exist. On hover:

```javascript
citationBadge.addEventListener('mouseenter', async () => {
  const nodeId = citationBadge.dataset.nodeId;
  if (citationBadge.dataset.tooltipLoaded) return;
  const resp = await fetch(`/api/v2/node/${nodeId}`);
  const data = await resp.json();
  const tooltip = document.createElement('div');
  tooltip.className = 'citation-tooltip';
  window.ZkSummary.render(data, tooltip, 'brief-only');
  citationBadge.appendChild(tooltip);
  citationBadge.dataset.tooltipLoaded = 'yes';
});
```

- [ ] **Step 5: Commit**

```bash
git add website/static/index.html website/static/js/app.js website/features/user_zettels/ website/features/knowledge_graph/ website/features/user_rag/
git commit -m "feat: wire summary renderer into home zettels kg rag"
```

---

## Task 8: `/api/v2/node/<id>` endpoint for single-node fetch

**Files:**
- Modify: `website/features/summarization_engine/api/routes.py` — add `GET /api/v2/node/{node_id}` endpoint

- [ ] **Step 1: Add route**

```python
@router.get("/node/{node_id}")
async def get_node_v2(node_id: UUID, user: Annotated[dict | None, Depends(get_optional_user)] = None):
    """Fetch a single node's full summary (for modal + tooltip rendering)."""
    import httpx
    import os
    supabase_url = os.environ.get("SUPABASE_URL", "")
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    bearer = (user or {}).get("bearer_token") or anon_key
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{supabase_url}/rest/v1/kg_nodes?id=eq.{node_id}&select=*",
            headers={"apikey": anon_key, "Authorization": f"Bearer {bearer}"},
        )
        resp.raise_for_status()
        rows = resp.json()
    if not rows:
        raise HTTPException(status_code=404, detail="node not found")
    node = rows[0]
    # Shape as /api/v2/summarize response so ZkSummary.render accepts it unchanged
    summary = {
        "mini_title": node.get("mini_title"),
        "brief_summary": node.get("brief_summary"),
        "tags": node.get("tags", []),
        "detailed_summary": node.get("detailed_summary", []),
        "metadata": {
            "source_type": node.get("source_type"),
            "url": node.get("url"),
            **(node.get("metadata") or {}),
        },
        # Pass per-source fields through if present (YouTube speakers, GitHub arch_overview, Newsletter stance, etc.)
        **{k: v for k, v in node.items() if k in {
            "speakers", "guests", "entities_discussed",
            "architecture_overview", "benchmarks_tests_examples",
        }},
    }
    return {"summary": summary, "writers": []}
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/api/routes.py
git commit -m "feat: api v2 fetch node for ui modal"
```

---

## Task 9: Headless-browser contract tests + colour audit

**Files:**
- Create: `tests/unit/website_ui/test_renderer_contract.py`

- [ ] **Step 1: Contract test (use `playwright` if already a dep; else simple JS-parsing verification)**

If playwright unavailable, use a simple regex-based test that verifies the HTML + JS files import the correct files:

```python
# tests/unit/website_ui/test_renderer_contract.py
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]


def test_home_index_loads_summary_renderer():
    content = (REPO / "website/static/index.html").read_text(encoding="utf-8")
    assert "summary_renderer.js" in content or "ZkSummary" in content
    assert "summary.css" in content


def test_zettels_index_loads_renderer():
    content = (REPO / "website/features/user_zettels/index.html").read_text(encoding="utf-8")
    assert "summary_renderer.js" in content or "ZkSummary" in content


def test_kg_index_loads_renderer():
    content = (REPO / "website/features/knowledge_graph/index.html").read_text(encoding="utf-8")
    # KG has its own amber accent; render integration still uses ZkSummary
    assert "ZkSummary" in content or "summary_renderer.js" in content


def test_rag_index_loads_renderer():
    content = (REPO / "website/features/user_rag/index.html").read_text(encoding="utf-8")
    assert "ZkSummary" in content or "summary_renderer.js" in content


def test_no_purple_in_new_css():
    css = (REPO / "website/static/css/summary.css").read_text(encoding="utf-8").lower()
    # Forbidden terms + hex ranges per CLAUDE.md UI Design rule
    forbidden = ["purple", "violet", "lavender", "#a78bfa", "#8b5cf6", "#7c3aed", "#6d28d9"]
    for term in forbidden:
        assert term not in css, f"Forbidden colour '{term}' in summary.css"


def test_dispatcher_has_all_4_major_sources():
    js = (REPO / "website/static/js/summary_renderer.js").read_text(encoding="utf-8")
    for src in ("youtube", "reddit", "github", "newsletter"):
        assert src in js.lower()
```

- [ ] **Step 2: Run + commit**

```bash
pytest tests/unit/website_ui/test_renderer_contract.py -v
git add tests/unit/website_ui/test_renderer_contract.py
git commit -m "test: ui renderer contract + colour audit"
```

---

## Task 10: Mobile renderer (condensed)

**Files:**
- Create: `website/mobile/js/summary_renderer_mobile.js`
- Create: `website/mobile/css/summary_mobile.css`
- Modify: `website/mobile/index.html`
- Modify: `website/mobile/knowledge-graph.html`

- [ ] **Step 1: Mobile renderer is a thin wrapper that forces card/brief-only modes + uses a bottom-sheet for expansion instead of inline**

```javascript
// website/mobile/js/summary_renderer_mobile.js
import { renderSummary } from '/static/js/summary_renderer.js';

export function renderSummaryMobile(apiResponse, rootEl) {
  renderSummary(apiResponse, rootEl, 'card');

  // On card tap, open bottom-sheet with full detailed view
  const card = rootEl.querySelector('.zettel-card') || rootEl;
  card.addEventListener('click', () => openBottomSheet(apiResponse));
}

function openBottomSheet(apiResponse) {
  let sheet = document.getElementById('zk-sheet');
  if (!sheet) {
    sheet = document.createElement('dialog');
    sheet.id = 'zk-sheet';
    sheet.className = 'zk-bottom-sheet';
    sheet.innerHTML = '<div class="sheet-handle"></div><button class="sheet-close" aria-label="Close">×</button><div class="sheet-body"></div>';
    document.body.appendChild(sheet);
    sheet.querySelector('.sheet-close').addEventListener('click', () => sheet.close());
  }
  const body = sheet.querySelector('.sheet-body');
  renderSummary(apiResponse, body, 'full');
  sheet.showModal();
}

if (typeof window !== 'undefined') window.ZkSummaryMobile = { render: renderSummaryMobile };
```

- [ ] **Step 2: Mobile CSS bottom-sheet**

```css
/* website/mobile/css/summary_mobile.css */
.zk-bottom-sheet {
  position: fixed; bottom: 0; left: 0; right: 0; margin: 0;
  max-height: 85vh; width: 100%; border-radius: 16px 16px 0 0;
  border: none; padding: 16px;
}
.sheet-handle { width: 48px; height: 4px; background: #E2E8F0; margin: 0 auto 12px; border-radius: 2px; }
.sheet-close { position: absolute; top: 8px; right: 8px; background: transparent; border: none; font-size: 24px; }
.sheet-body { overflow-y: auto; max-height: calc(85vh - 40px); }
```

- [ ] **Step 3: Wire into mobile pages**

```html
<!-- website/mobile/index.html + knowledge-graph.html -->
<link rel="stylesheet" href="/static/css/summary.css">
<link rel="stylesheet" href="/mobile/css/summary_mobile.css">
<script type="module" src="/mobile/js/summary_renderer_mobile.js"></script>
```

- [ ] **Step 4: Commit**

```bash
git add website/mobile/
git commit -m "feat: mobile summary renderer with bottom sheet"
```

---

## Task 11: After-screenshots + visual diff README

**Files:**
- Create: `docs/summary_eval/_ui_integration/after/*.png` (manual screenshots)
- Create: `docs/summary_eval/_ui_integration/README.md`

- [ ] **Step 1: Start server, take after-screenshots**

```bash
python run.py &
# Summarize the 3 YouTube URLs from links.txt; screenshot home (before + after expand), zettels (list + modal), kg popover, rag citation hover, mobile home
kill %1
```

- [ ] **Step 2: README**

```markdown
# UI integration — before vs after

Plan 15 adds per-source rendering to home / zettels / kg / rag / mobile.

## Before (baseline/)
- home.png — generic summary display, no per-source signal
- zettels.png — flat list, generic cards
- kg.png — raw node label only on click
- rag.png — citation badge with plain URL tooltip
- mobile_home.png — generic summary, no expand

## After (after/)
- home.png — title + source badge, brief, tags, "Show detailed" expand
- zettels.png — cards with source-badge, 2-line brief, 3 tags, Open → modal
- kg.png — popover with title + 1-line brief
- rag.png — citation tooltip with brief
- mobile_home.png — card; tap → bottom-sheet with full detailed

## Accessibility verified
- All interactive elements keyboard-navigable
- Expand buttons have aria-expanded + aria-controls
- Modal traps focus + Esc closes
- Colour contrast AA (teal on white ≥ 4.5:1)

## Colour audit
- `grep -ri 'purple\|violet\|lavender' website/static/css/summary.css website/mobile/css/summary_mobile.css` — empty (enforced by test_renderer_contract.py)
```

- [ ] **Step 3: Commit**

```bash
git add docs/summary_eval/_ui_integration/
git commit -m "docs: ui integration before after visual diff"
```

---

## Task 12: Push + draft PR

```bash
git push origin feat/ui-per-source-renderers
gh pr create --draft --title "feat: ui per source summary renderers" \
  --body "Plan 15. Replaces generic summary display on home/zettels/kg/rag/mobile with per-source renderers that surface speakers/chapters/architecture/reply-clusters/conclusions/stance/etc. Legacy nodes render via generic fallback; no broken cards. Colour audit passes (no purple anywhere).

### Display contract (per user)
- Home: brief + tags inline, \"Show detailed\" expand button → per-source structured view
- Zettels list: card with title + 2-line brief + top 3 tags + source badge; click → modal with full detailed
- KG popover: title + 1-line brief on node click; \"Open\" routes to Zettels modal
- RAG citation: hover tooltip with brief
- Mobile: card view + bottom-sheet for detailed

### Deploy gate
- [ ] CI green
- [ ] test_renderer_contract.py passes (colour audit + all 4 major sources in dispatcher)
- [ ] Manual visual regression OK (baseline/ vs after/ screenshots committed)
- [ ] Keyboard nav works on home + zettels modal
- [ ] No layout breakage on mobile Safari + Chrome

Post-merge: nothing to flip; feature ships on. If a rendering bug appears, fall back to generic renderer by setting \`source_type\` to \`web\` in the summary metadata."
```

---

## Self-review checklist
- [ ] Colour audit passes (no purple/violet/lavender anywhere in new CSS)
- [ ] Legacy zettels (pre-Plan-1) render via generic fallback without errors
- [ ] All 4 major-source renderers tested with a fixture summary
- [ ] Expand button has aria-expanded + aria-controls
- [ ] Modal is a `<dialog>` with Esc close
- [ ] YouTube timestamps link to the video at the correct second
- [ ] Newsletter stance renders as a neutral badge (no sentiment colour)
- [ ] Mobile bottom-sheet is scroll-contained + has a close button
- [ ] KG page retains amber/gold accent; summary renderer doesn't override it
- [ ] `/api/v2/node/<id>` endpoint added for single-node fetch (used by modal + tooltip)
- [ ] NO merge, NO push to master
