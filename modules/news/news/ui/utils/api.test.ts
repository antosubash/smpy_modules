import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { formatArticleDate, formatTimestamp } from './api';

// A timezone west of UTC, where midnight UTC is still the previous evening.
// Against the pre-fix implementation (local-time rendering) every assertion
// on the date below would come out one day early.
//
// Restored afterwards: vitest does not reset `process.env` between files that
// share a worker, so setting this at module scope leaks the timezone into
// whichever file runs next.
const TZ = 'America/New_York';
const originalTz = process.env.TZ;

beforeAll(() => {
  process.env.TZ = TZ;
});

afterAll(() => {
  process.env.TZ = originalTz;
});

describe('formatArticleDate', () => {
  it('renders the stored date, not the viewer-local one', () => {
    expect(formatArticleDate('2026-02-01T00:00:00Z', 'en-US')).toBe('Feb 1, 2026');
  });

  it('holds at a year boundary', () => {
    expect(formatArticleDate('2025-12-31T00:00:00Z', 'en-US')).toBe('Dec 31, 2025');
  });

  it('reads the date part even when the server omits the offset', () => {
    expect(formatArticleDate('2026-02-01T00:00:00', 'en-US')).toBe('Feb 1, 2026');
  });

  it('is empty for an undated article', () => {
    expect(formatArticleDate(null, 'en-US')).toBe('');
  });

  it('is empty rather than "Invalid Date" for garbage', () => {
    expect(formatArticleDate('not-a-date', 'en-US')).toBe('');
  });

  it('writes the date in the locale it is given (#189)', () => {
    expect(formatArticleDate('2026-02-01T00:00:00Z', 'de')).toBe('1. Feb. 2026');
  });
});

describe('formatTimestamp', () => {
  it('renders date and time in the given locale, in the viewer timezone', () => {
    // 18:05 UTC is 13:05 in New York.
    expect(formatTimestamp('2026-02-01T18:05:00Z', 'de')).toBe('01.02.2026, 13:05');
    expect(formatTimestamp('2026-02-01T18:05:00Z', 'en-US')).toMatch(/^Feb 1, 2026, 1:05\sPM$/);
  });

  it('hands garbage back unchanged', () => {
    expect(formatTimestamp('nope', 'de')).toBe('nope');
  });
});
