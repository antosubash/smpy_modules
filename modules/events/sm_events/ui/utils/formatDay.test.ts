import { describe, expect, it } from 'vitest';
import { formatDay } from './datetime';

const noon = '2026-11-18T12:00:00Z'; // the same day in every zone that matters

describe('formatDay', () => {
  it('reads day-month-year in English, like the rest of the console', () => {
    expect(formatDay(noon, 'en')).toBe('18 Nov 2026');
    expect(formatDay(noon)).toBe('18 Nov 2026');
  });

  it('follows the console language', () => {
    expect(formatDay(noon, 'de')).toBe('18.11.2026');
  });

  it('shows what it cannot read, as it came', () => {
    expect(formatDay('not a date', 'de')).toBe('not a date');
  });
});
