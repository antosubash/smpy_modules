import { describe, expect, it } from 'vitest';

import { formatBytes } from './format-bytes';
import { formatNumber, intlLocale } from './locale';
import { formatCalendarDate, formatDateTime } from './values';

describe('intlLocale — a tag Intl accepts, whatever it is handed (#189)', () => {
  it.each([
    ['', 'en'],
    ['en_US', 'en-US'],
    [undefined, 'en'],
    ['de-AT', 'de-AT'],
    ['not a locale!', 'en'],
  ])('%j -> %s', (input, expected) => {
    expect(intlLocale(input)).toBe(expected);
  });
});

describe('the formatters never throw on a bad locale', () => {
  it.each(['', 'en_US', undefined, 'de-AT', 'not a locale!'])('%j', (locale) => {
    expect(formatCalendarDate('2026-03-01', locale)).toMatch(/2026/);
    expect(formatDateTime('2026-03-01T10:00:00Z', locale)).toMatch(/2026/);
    expect(formatNumber(4749, locale)).toMatch(/4.?749/);
    expect(formatBytes(2048, locale)).toMatch(/2/);
  });
});

describe('numbers follow the console language, not the browser', () => {
  it('groups digits the German way', () => {
    expect(formatNumber(2262.22, 'de')).toBe('2.262,22');
    expect(formatNumber(2262.22, 'en')).toBe('2,262.22');
  });

  it('writes a percentage and a file size in German', () => {
    expect(formatNumber(0.42, 'de', { style: 'percent' })).toMatch(/^42\s%$/);
    expect(formatBytes(1.5 * 1024 * 1024, 'de')).toMatch(/^1,5\sMB$/);
  });
});
