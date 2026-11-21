import { describe, expect, it } from 'vitest';
import { contains, MAX_RANGE_DAYS, paddedRange, rangeKey } from './range';

const r = (start: string, end: string) => ({ start, end });
const days = (range: { start: string; end: string }) =>
  (Date.parse(range.end) - Date.parse(range.start)) / 86_400_000;

describe('paddedRange', () => {
  it('pads by seven days', () => {
    expect(paddedRange(r('2026-03-01T00:00:00Z', '2026-04-12T00:00:00Z'))).toEqual(
      r('2026-02-22T00:00:00Z', '2026-04-19T00:00:00Z'),
    );
  });
  it('never exceeds 366 days and still contains the visible range', () => {
    const visible = r('2026-01-01T00:00:00Z', '2026-12-27T00:00:00Z');
    const padded = paddedRange(visible);
    expect(days(padded)).toBeLessThanOrEqual(MAX_RANGE_DAYS);
    expect(contains(padded, visible)).toBe(true);
  });
  it('leaves a visible range that is already too long alone', () => {
    const visible = r('2026-01-01T00:00:00Z', '2027-03-01T00:00:00Z');
    expect(paddedRange(visible)).toEqual(visible);
  });
});

describe('contains', () => {
  const outer = r('2026-02-22T00:00:00Z', '2026-04-19T00:00:00Z');
  it('is inclusive at both edges', () => {
    expect(contains(outer, outer)).toBe(true);
    expect(contains(outer, r('2026-03-01T00:00:00Z', '2026-04-12T00:00:00Z'))).toBe(true);
  });
  it('is false when either edge sticks out', () => {
    expect(contains(outer, r('2026-02-21T00:00:00Z', '2026-03-01T00:00:00Z'))).toBe(false);
    expect(contains(outer, r('2026-03-01T00:00:00Z', '2026-04-20T00:00:00Z'))).toBe(false);
  });
});

describe('rangeKey', () => {
  const base = { start: 'a', end: 'b', categories: [], types: [], sources: [], locale: 'en' };
  it('ignores filter order', () => {
    expect(rangeKey({ ...base, calendars: ['b', 'a'] })).toBe(
      rangeKey({ ...base, calendars: ['a', 'b'] }),
    );
  });
  it('differs by locale and filters', () => {
    expect(rangeKey({ ...base, calendars: ['a'] })).not.toBe(
      rangeKey({ ...base, calendars: ['a'], locale: 'de' }),
    );
  });
});
