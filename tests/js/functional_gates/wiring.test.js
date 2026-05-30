import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

function src(rel) {
  return readFileSync(resolve(__dirname, '../../../', rel), 'utf8');
}
const HOME = src('website/features/user_home/js/home.js');
const ZETTELS = src('website/features/user_zettels/js/user_zettels.js');

describe('quota gate wiring — Home & My Zettels', () => {
  it('home.js calls precheck and uses extractQuotaDetail', () => {
    expect(HOME).toMatch(/ZKQuotaGate\.precheck\s*\(/);
    expect(HOME).toMatch(/ZKQuotaGate\.extractQuotaDetail\s*\(/);
    expect(HOME).not.toMatch(/e\.detail\.code\s*===\s*['"]quota_exhausted['"]/);
  });
  it('precheck runs before the add/upload call in home.js', () => {
    expect(HOME.indexOf('ZKQuotaGate.precheck')).toBeGreaterThan(-1);
    expect(HOME.indexOf('ZKQuotaGate.precheck'))
      .toBeLessThan(HOME.indexOf('ZKAddZettel.add'));
  });
  it('home.js precheck runs before any optimistic-UI/button mutation', () => {
    const i = HOME.indexOf('ZKQuotaGate.precheck');
    const firstMutation = HOME.indexOf('addSubmitBtn.disabled = true');
    expect(i).toBeGreaterThan(-1);
    expect(firstMutation).toBeGreaterThan(-1);
    expect(i).toBeLessThan(firstMutation);
  });
  it('user_zettels.js calls precheck and uses extractQuotaDetail', () => {
    expect(ZETTELS).toMatch(/ZKQuotaGate\.precheck\s*\(/);
    expect(ZETTELS).toMatch(/ZKQuotaGate\.extractQuotaDetail\s*\(/);
    expect(ZETTELS).not.toMatch(/err\.detail\.code\s*===\s*['"]quota_exhausted['"]/);
  });
});

describe('quota gate wiring — Mobile', () => {
  const MOBILE = readFileSync(
    resolve(__dirname, '../../../website/mobile/js/summarizer.js'), 'utf8');
  const INDEX = readFileSync(
    resolve(__dirname, '../../../website/mobile/index.html'), 'utf8');

  it('summarizer.js calls precheck and extractQuotaDetail', () => {
    expect(MOBILE).toMatch(/ZKQuotaGate\.precheck\s*\(/);
    expect(MOBILE).toMatch(/ZKQuotaGate\.extractQuotaDetail\s*\(/);
  });
  it('index.html loads the quota gate assets', () => {
    expect(INDEX).toMatch(/quota_gate\.js/);
    expect(INDEX).toMatch(/quota_gate\.css/);
  });
});
