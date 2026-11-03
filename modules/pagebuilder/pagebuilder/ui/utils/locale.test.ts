import { describe, expect, it } from 'vitest';

import { formatTimestamp } from './dates';
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

describe('formatTimestamp never throws on a bad locale', () => {
  const UTC: Intl.DateTimeFormatOptions = { timeZone: 'UTC' };

  it.each(['', 'en_US', undefined, 'not a locale!'])('%j falls back to English', (locale) => {
    expect(formatTimestamp('2026-09-21T13:05:00Z', locale, UTC)).toMatch(/^9\/21\/2026/);
  });

  it('writes an Austrian timestamp in German', () => {
    expect(formatTimestamp('2026-09-21T13:05:00Z', 'de-AT', UTC)).toBe('21.9.2026, 13:05:00');
  });
});
