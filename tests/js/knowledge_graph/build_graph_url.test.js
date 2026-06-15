/**
 * A3 root-cause (2026-06-15): the Global toggle must send an EXPLICIT
 * view=global. Omitting it makes the server infer the view from auth
 * (authed -> 'my'), so an authed user's "Global" request silently returned
 * their personal graph. buildGraphApiUrl always emits an explicit view.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const APP_SRC = readFileSync(
  resolve(__dirname, '../../../website/features/knowledge_graph/js/app.js'),
  'utf8',
);
const FENCE = APP_SRC.match(
  /\/\* test-exports:start \*\/([\s\S]*?)\/\* test-exports:end \*\//,
)[1];
const { buildGraphApiUrl } = new Function(
  FENCE + '\nreturn { buildGraphApiUrl };',
)();

describe('buildGraphApiUrl', () => {
  it('sends explicit view=global for the Global view', () => {
    const url = buildGraphApiUrl('global', 0.3);
    expect(url).toContain('view=global');
    expect(url).not.toContain('view=my');
    expect(url).toContain('min_strength=0.3');
  });
  it('sends view=my for the Personal view', () => {
    const url = buildGraphApiUrl('my', 0.5);
    expect(url).toContain('view=my');
    expect(url).toContain('min_strength=0.5');
  });
  it('treats any non-my value as global (never omits view)', () => {
    expect(buildGraphApiUrl(undefined, 0.3)).toContain('view=global');
    expect(buildGraphApiUrl('', 0.3)).toContain('view=global');
  });
});

describe('loadGraphData uses the helper (no inline view-omission)', () => {
  it('loadGraphData calls buildGraphApiUrl', () => {
    expect(APP_SRC).toMatch(/buildGraphApiUrl\(\s*currentView/);
  });
});
