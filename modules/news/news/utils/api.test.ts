import { describe, expect, it } from 'vitest';

import { formatArticleDate } from './api';

// A timezone west of UTC, where midnight UTC is still the previous evening.
// Against the pre-fix implementation (local-time rendering) every assertion
// on the date below would come out one day early.
process.env.TZ = 'America/New_York';

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
});
