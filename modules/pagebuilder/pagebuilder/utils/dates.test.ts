import { describe, expect, it } from 'vitest';

import { formatTimestamp } from './dates';

const UTC: Intl.DateTimeFormatOptions = { timeZone: 'UTC' };

describe('formatTimestamp', () => {
  it('writes the timestamp in the locale it is handed, not the browser one (#189)', () => {
    expect(formatTimestamp('2026-09-21T13:05:00Z', 'de', UTC)).toBe('21.9.2026, 13:05:00');
    expect(formatTimestamp('2026-09-21T13:05:00Z', 'en-US', UTC)).toMatch(
      /^9\/21\/2026, 1:05:00\sPM$/,
    );
  });

  it('takes the caller’s format options', () => {
    const opts: Intl.DateTimeFormatOptions = { ...UTC, day: 'numeric', month: 'short' };
    expect(formatTimestamp('2026-09-21T13:05:00Z', 'de', opts)).toBe('21. Sept.');
  });

  it('is empty for a missing or unparseable value, never "Invalid Date"', () => {
    expect(formatTimestamp(null, 'de')).toBe('');
    expect(formatTimestamp(undefined, 'de')).toBe('');
    expect(formatTimestamp('nope', 'de')).toBe('');
  });
});
