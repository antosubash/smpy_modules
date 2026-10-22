import { describe, expect, it } from 'vitest';

import { formatArticleDate, formatTimestamp } from './api';
import { intlLocale } from './locale';

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

describe('the date helpers never throw on a bad locale', () => {
  it.each(['', 'en_US', undefined, 'de-AT', 'not a locale!'])('%j', (locale) => {
    expect(formatArticleDate('2026-09-21T00:00:00Z', locale)).toMatch(/2026/);
    expect(formatTimestamp('2026-09-21T13:05:00Z', locale)).toMatch(/2026/);
  });

  it('writes an Austrian date in German', () => {
    expect(formatArticleDate('2026-09-21T00:00:00Z', 'de-AT')).toBe('21. Sep. 2026');
  });
});
