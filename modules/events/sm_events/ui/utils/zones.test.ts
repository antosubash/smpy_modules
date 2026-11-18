import { describe, expect, it } from 'vitest';
import { browserZone, todayIn, utcOffset, utcOffsetAt } from './zones';

describe('todayIn', () => {
  const now = new Date('2026-03-29T23:30:00Z');
  it("is the date on the zone's own clock", () => {
    expect(todayIn('Europe/Vienna', now)).toBe('2026-03-30');
    expect(todayIn('America/New_York', now)).toBe('2026-03-29');
  });
  it("is the browser's day for a zone it does not know", () => {
    expect(todayIn('Not/AZone', now)).toBe(todayIn(browserZone(), now));
    expect(todayIn(undefined, now)).toBe(todayIn(browserZone(), now));
  });
});

describe('offsets', () => {
  it("reads the offset at an instant, never the browser's", () => {
    expect(utcOffsetAt('2026-03-23T09:00:00Z', 'Europe/Vienna')).toBe('UTC+01:00');
    expect(utcOffsetAt('2026-03-30T09:00:00Z', 'Europe/Vienna')).toBe('UTC+02:00');
    expect(utcOffsetAt('2026-03-30T09:00:00Z', 'Asia/Kolkata')).toBe('UTC+05:30');
  });
  it('reads the offset of a wall time, next to a clock change too', () => {
    expect(utcOffset('2026-03-29T01:30', 'Europe/Vienna')).toBe('UTC+01:00');
    expect(utcOffset('2026-03-29T03:30', 'Europe/Vienna')).toBe('UTC+02:00');
    expect(utcOffset('2026-10-25T02:30', 'Europe/Vienna')).toBe('UTC+02:00');
  });
  it('is null for a bad value or an unknown zone', () => {
    expect(utcOffsetAt('nope', 'Europe/Vienna')).toBeNull();
    expect(utcOffsetAt('2026-03-30T09:00:00Z', 'Not/AZone')).toBeNull();
    expect(utcOffset('2026-03-30T09:00', 'Not/AZone')).toBeNull();
  });
});
