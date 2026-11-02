import { describe, expect, it } from 'vitest';

import { formatDate, formatMoney } from './format';
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

describe('the formatters never throw on a bad locale', () => {
  it.each(['', 'en_US', undefined, 'de-AT', 'not a locale!'])('%j', (locale) => {
    expect(formatMoney(1900, 'eur', locale)).toMatch(/19/);
    expect(formatDate('2026-09-21T00:00:00Z', locale)).toMatch(/2026/);
  });

  it('formats an Austrian locale the Austrian way', () => {
    expect(formatMoney(1900, 'eur', 'de-AT')).toMatch(/^€\s19,00$/);
  });
});
