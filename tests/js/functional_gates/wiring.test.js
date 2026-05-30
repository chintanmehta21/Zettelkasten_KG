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
  it('user_zettels.js calls precheck and uses extractQuotaDetail', () => {
    expect(ZETTELS).toMatch(/ZKQuotaGate\.precheck\s*\(/);
    expect(ZETTELS).toMatch(/ZKQuotaGate\.extractQuotaDetail\s*\(/);
    expect(ZETTELS).not.toMatch(/err\.detail\.code\s*===\s*['"]quota_exhausted['"]/);
  });
});
