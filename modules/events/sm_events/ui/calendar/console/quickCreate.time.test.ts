import { describe, expect, it } from 'vitest';
import { isWallTime } from '../time/zones';
import { reexpress, timeProblems } from './quickCreate';
import { timeErrors } from './timeErrors';

// Chrome's datetime-local accepts a five- or six-digit year; Temporal throws on it.
const LONG_YEAR = '012026-03-30T11:00';

describe('an input value nothing can read', () => {
  it('is not a wall time', () => {
    expect(isWallTime(LONG_YEAR)).toBe(false);
    expect(isWallTime('12026-03-30T11:00')).toBe(false);
    expect(isWallTime('2026-02-30T11:00')).toBe(false);
    expect(isWallTime('2026-03-30T11:00')).toBe(true);
    expect(isWallTime('012026-03-30', true)).toBe(false);
    expect(isWallTime('2026-03-30', true)).toBe(true);
  });
  it('is reported by field, never thrown', () => {
    const clock = { allDay: false, start: LONG_YEAR, end: '2026-03-30T12:00' };
    expect(timeProblems(clock, 'Europe/Vienna')).toEqual({ start: 'invalid' });
    const dates = { allDay: true, start: '2026-03-30', end: '012026-03-31' };
    expect(timeProblems(dates, 'Europe/Vienna')).toEqual({ end: 'invalid' });
  });
  it('has a message of its own, apart from the skipped hour', () => {
    const say = (key: string) => key;
    const found = timeErrors({ start: 'invalid', end: 'skipped' }, say);
    expect(found['times.start']).not.toBe(found['times.end']);
  });
  it('does not stop a calendar change', () => {
    const clock = { allDay: false, start: LONG_YEAR, end: LONG_YEAR };
    expect(reexpress(clock, 'Europe/Vienna', 'America/New_York')).toBe(clock);
  });
});
